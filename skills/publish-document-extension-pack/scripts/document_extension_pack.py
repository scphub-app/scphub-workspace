#!/usr/bin/env python3
"""Validate, build, publish, and verify SCPHub document extension packs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo


SITES = ("en", "ru", "ko", "cn", "fr", "pl", "es", "th", "jp", "de", "it", "ua", "pt", "cs", "zh", "vn")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DEFAULT_BASE_URL = "https://scphub-api.swiftc.cc"
MAX_ZIP_SIZE = 2_000_000_000


class PackError(RuntimeError):
    pass


class LoadedPack:
    def __init__(self, manifest: Any, docs: dict[str, bytes], source: Path):
        self.manifest = manifest
        self.docs = docs
        self.source = source


def load_json(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PackError(f"{label} is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PackError(f"{label} is not valid JSON: {exc}") from exc


def load_directory(path: Path) -> LoadedPack:
    manifest_path = path / "manifest.json"
    docs_dir = path / "docs"
    if not manifest_path.is_file():
        raise PackError(f"missing {manifest_path}")
    if not docs_dir.is_dir():
        raise PackError(f"missing directory {docs_dir}")
    docs: dict[str, bytes] = {}
    extras: list[str] = []
    for item in sorted(docs_dir.iterdir(), key=lambda value: value.name):
        if not item.is_file() or item.suffix != ".html":
            extras.append(item.name)
            continue
        docs[item.stem] = item.read_bytes()
    if extras:
        raise PackError("docs contains non-canonical entries: " + ", ".join(extras))
    return LoadedPack(load_json(manifest_path.read_bytes(), str(manifest_path)), docs, path)


def safe_zip_names(zf: ZipFile) -> list[str]:
    names: list[str] = []
    for info in zf.infolist():
        raw = info.filename
        path = PurePosixPath(raw)
        if "\\" in raw or path.is_absolute() or ".." in path.parts:
            raise PackError(f"unsafe ZIP path: {raw}")
        if info.flag_bits & 0x1:
            raise PackError(f"encrypted ZIP entries are unsupported: {raw}")
        if info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
            raise PackError(f"unsupported ZIP compression method for {raw}")
        if info.file_size >= 0xFFFFFFFF or info.compress_size >= 0xFFFFFFFF:
            raise PackError("ZIP64 entries are unsupported")
        if info.is_dir() or raw.startswith("__MACOSX/") or path.name == ".DS_Store":
            continue
        names.append(raw)
    return names


def load_zip(path: Path) -> LoadedPack:
    if path.stat().st_size >= MAX_ZIP_SIZE:
        raise PackError("ZIP must be smaller than 2 GB")
    try:
        with ZipFile(path) as zf:
            names = safe_zip_names(zf)
            if "manifest.json" in names:
                prefix = ""
            else:
                candidates = [name for name in names if name.endswith("/manifest.json") and name.count("/") == 1]
                if len(candidates) != 1:
                    raise PackError("ZIP must contain manifest.json at root or inside one wrapper directory")
                prefix = candidates[0].split("/", 1)[0] + "/"
            relative: list[str] = []
            for name in names:
                if prefix and not name.startswith(prefix):
                    raise PackError(f"ZIP entry is outside wrapper directory: {name}")
                relative.append(name[len(prefix):])
            allowed = {"manifest.json"}
            docs: dict[str, bytes] = {}
            for name in relative:
                if name == "manifest.json":
                    continue
                match = re.fullmatch(r"docs/([^/]+)\.html", name)
                if not match:
                    raise PackError(f"non-canonical ZIP entry: {name}")
                filename = match.group(1)
                if filename in docs:
                    raise PackError(f"duplicate ZIP document: {filename}")
                docs[filename] = zf.read(prefix + name)
                allowed.add(name)
            manifest = load_json(zf.read(prefix + "manifest.json"), "manifest.json")
            return LoadedPack(manifest, docs, path)
    except BadZipFile as exc:
        raise PackError(f"invalid ZIP: {exc}") from exc


def load_pack(path: Path) -> LoadedPack:
    path = path.expanduser().resolve()
    if path.is_dir():
        return load_directory(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        return load_zip(path)
    raise PackError(f"expected a source directory or .zip: {path}")


def workspace_signature(path: Path) -> bool:
    return all((path / rel).exists() for rel in (
        "README.md",
        "data/scpdata-full",
        "scphub-backend/pack-server/worker.js",
        "scphub-backend/pack-server/admin.html",
    ))


def find_workspace(explicit: str | None, source: Path) -> Path | None:
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not workspace_signature(root):
            raise PackError(f"not an SCPHub workspace root: {root}")
        return root
    starts = [Path.cwd().resolve(), source.resolve()]
    for start in starts:
        cursor = start if start.is_dir() else start.parent
        for candidate in (cursor, *cursor.parents):
            if workspace_signature(candidate):
                return candidate
    return None


def full_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def core_filenames(root: Path, site: str) -> set[str]:
    site_dir = root / "data" / "scpdata-full" / site
    if not site_dir.is_dir():
        raise PackError(f"core data directory is missing: {site_dir}")
    result: set[str] = set()
    for path in sorted(site_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackError(f"cannot inspect core catalog {path}: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("files"), list):
            continue
        for entry in value["files"]:
            if isinstance(entry, dict) and isinstance(entry.get("filename"), str):
                result.add(entry["filename"])
    return result


def validate_loaded(pack: LoadedPack, workspace: Path | None, skip_collision_check: bool) -> dict[str, Any]:
    man = pack.manifest
    errors: list[str] = []
    if not isinstance(man, dict):
        raise PackError("manifest must be a JSON object")

    pack_id = man.get("id")
    site = man.get("site_id")
    name = man.get("name")
    summary = man.get("summary")
    version = man.get("version")
    files = man.get("files")

    if not isinstance(pack_id, str) or not NAME_RE.fullmatch(pack_id):
        errors.append("id must match [A-Za-z0-9][A-Za-z0-9._-]*")
    if site not in SITES:
        errors.append("site_id must be one of: " + " ".join(SITES))
    if not isinstance(name, str) or not name.strip():
        errors.append("name must be a non-empty string")
    if summary is not None and not isinstance(summary, str):
        errors.append("summary must be a string or null")
    if type(version) is not int or version < 1:
        errors.append("version must be an integer >= 1")
    if not isinstance(files, list) or not files:
        errors.append("files must be a non-empty array")
        files = []

    expected: set[str] = set()
    for index, item in enumerate(files):
        label = f"files[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            errors.append(f"{label}.name must be a non-empty string")
        tags = item.get("tags")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            errors.append(f"{label}.tags must be an array of strings")
        filename = item.get("filename")
        if not isinstance(filename, str) or not NAME_RE.fullmatch(filename):
            errors.append(f"{label}.filename must be URL-safe")
        elif filename.lower().endswith(".html"):
            errors.append(f"{label}.filename must not include .html")
        elif filename in expected:
            errors.append(f"{label}.filename duplicates {filename}")
        else:
            expected.add(filename)
        discuss_url = item.get("discuss_url")
        if not isinstance(discuss_url, str) or not full_url(discuss_url):
            errors.append(f"{label}.discuss_url must be a full http(s) URL")

    actual = set(pack.docs)
    for filename in sorted(expected - actual):
        errors.append(f"missing docs/{filename}.html")
    for filename in sorted(actual - expected):
        errors.append(f"extra docs/{filename}.html is not listed in manifest")
    for filename, data in sorted(pack.docs.items()):
        try:
            html = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"docs/{filename}.html is not UTF-8: {exc}")
            continue
        lowered = html.lower()
        if "<html" not in lowered[:4096] or "</html>" not in lowered:
            errors.append(f"docs/{filename}.html must be a complete standalone HTML document")

    if not skip_collision_check:
        if workspace is None:
            errors.append("SCPHub workspace not found; pass --workspace-root or explicitly use --skip-core-collision-check")
        elif site in SITES:
            collisions = expected & core_filenames(workspace, site)
            if collisions:
                errors.append("filenames collide with the core site library: " + ", ".join(sorted(collisions)))

    if errors:
        raise PackError("validation failed:\n- " + "\n- ".join(errors))
    return {
        "id": pack_id,
        "site_id": site,
        "name": name,
        "version": version,
        "document_count": len(files),
        "total_bytes": sum(len(data) for data in pack.docs.values()),
        "sha256": hashlib.sha256(
            b"".join(filename.encode("utf-8") + b"\0" + pack.docs[filename] for filename in sorted(pack.docs))
        ).hexdigest(),
    }


def validate_path(path: str, workspace_arg: str | None, skip_collision_check: bool) -> tuple[LoadedPack, dict[str, Any], Path | None]:
    pack = load_pack(Path(path))
    workspace = find_workspace(workspace_arg, pack.source)
    summary = validate_loaded(pack, workspace, skip_collision_check)
    return pack, summary, workspace


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def add_zip_bytes(zf: ZipFile, name: str, data: bytes) -> None:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    zf.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)


def build_zip(pack: LoadedPack, output: Path, overwrite: bool) -> None:
    output = output.expanduser().resolve()
    if output.exists() and not overwrite:
        raise PackError(f"output already exists (use --overwrite): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False) as temp:
            temp_name = temp.name
        with ZipFile(temp_name, "w", compression=ZIP_DEFLATED, allowZip64=False) as zf:
            add_zip_bytes(zf, "manifest.json", canonical_manifest_bytes(pack.manifest))
            for filename in sorted(pack.docs):
                add_zip_bytes(zf, f"docs/{filename}.html", pack.docs[filename])
        if Path(temp_name).stat().st_size >= MAX_ZIP_SIZE:
            raise PackError("built ZIP is too large")
        os.replace(temp_name, output)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def normalize_base_url(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PackError(f"invalid base URL: {value}")
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise PackError("non-local publishing requires HTTPS")
    return value


def request_bytes(url: str, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 120) -> tuple[bytes, Any]:
    request_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept-Encoding": "identity",
    }
    request_headers.update(headers or {})
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers
    except HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error", detail)
            if parsed.get("details"):
                message += ": " + "; ".join(parsed["details"])
            if parsed.get("missing"):
                message += ": " + ", ".join(parsed["missing"])
        except (json.JSONDecodeError, AttributeError, TypeError):
            message = detail
        raise PackError(f"HTTP {exc.code} for {method} {url}: {message}") from exc
    except URLError as exc:
        raise PackError(f"request failed for {method} {url}: {exc.reason}") from exc


def request_json(url: str, method: str = "GET", value: Any = None, token: str | None = None) -> Any:
    headers: dict[str, str] = {"Accept": "application/json"}
    body = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if value is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    data, _ = request_bytes(url, method=method, body=body, headers=headers)
    return load_json(data, url)


def cache_buster() -> str:
    return str(time.time_ns())


def public_list(base: str, site: str) -> list[dict[str, Any]]:
    query = urlencode({"site": site, "verify": cache_buster()})
    value = request_json(f"{base}/api/v1/packs?{query}")
    if not isinstance(value, dict) or not isinstance(value.get("packs"), list):
        raise PackError("public pack list has an invalid shape")
    return value["packs"]


def current_summary(base: str, pack_id: str, site: str) -> dict[str, Any] | None:
    return next((item for item in public_list(base, site) if item.get("id") == pack_id), None)


def served_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": manifest["id"],
        "site_id": manifest["site_id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "files": [
            {
                "name": item["name"],
                "tags": item["tags"],
                "filename": item["filename"],
                "discuss_url": item["discuss_url"],
            }
            for item in manifest["files"]
        ],
    }


def verify_public(pack: LoadedPack, summary: dict[str, Any], base: str) -> dict[str, Any]:
    pack_id = summary["id"]
    site = summary["site_id"]
    listed = current_summary(base, pack_id, site)
    if listed is None:
        raise PackError(f"public list does not contain {pack_id}")
    expected_list = {
        "id": pack_id,
        "site_id": site,
        "name": pack.manifest["name"],
        "summary": pack.manifest.get("summary") or None,
        "version": summary["version"],
        "doc_count": summary["document_count"],
        "download_size": summary["total_bytes"],
    }
    actual_list = {key: listed.get(key) for key in expected_list}
    if actual_list != expected_list:
        raise PackError(f"public list mismatch: expected {expected_list}, got {actual_list}")

    encoded_id = quote(pack_id, safe="")
    manifest_url = f"{base}/api/v1/packs/{encoded_id}?verify={cache_buster()}"
    actual_manifest = request_json(manifest_url)
    expected_manifest = served_manifest(pack.manifest)
    if actual_manifest != expected_manifest:
        raise PackError("served manifest does not match the package manifest")

    verified_bytes = 0
    for filename, expected in sorted(pack.docs.items()):
        encoded_filename = quote(filename, safe="")
        url = f"{base}/api/v1/packs/{encoded_id}/docs/{encoded_filename}?verify={cache_buster()}"
        actual, _ = request_bytes(url, headers={"Accept": "text/html", "Accept-Encoding": "identity"})
        if actual != expected:
            raise PackError(f"public document differs from ZIP: {filename}")
        verified_bytes += len(actual)
    return {
        "verified": True,
        "id": pack_id,
        "site_id": site,
        "version": summary["version"],
        "document_count": summary["document_count"],
        "verified_bytes": verified_bytes,
    }


def make_plan(pack: LoadedPack, summary: dict[str, Any], base: str) -> dict[str, Any]:
    current = current_summary(base, summary["id"], summary["site_id"])
    current_version = current.get("version") if current else None
    if current is None:
        action = "new"
        blocked = False
    elif summary["version"] > current_version:
        action = "update"
        blocked = False
    elif summary["version"] == current_version:
        action = "same-version-retry"
        blocked = True
    else:
        action = "downgrade"
        blocked = True
    return {
        "base_url": base,
        "id": summary["id"],
        "site_id": summary["site_id"],
        "requested_version": summary["version"],
        "current_version": current_version,
        "action": action,
        "blocked_by_default": blocked,
        "document_count": summary["document_count"],
        "total_bytes": summary["total_bytes"],
        "content_sha256": summary["sha256"],
    }


def publish(pack: LoadedPack, summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    base = normalize_base_url(args.base_url)
    plan = make_plan(pack, summary, base)
    current_version = plan["current_version"]
    if plan["action"] == "downgrade":
        raise PackError(f"version {summary['version']} is below published version {current_version}")
    if plan["action"] == "same-version-retry" and not args.allow_same_version:
        raise PackError("same-version publish is only for an identical retry; pass --allow-same-version after verifying that condition")
    if plan["action"] == "update" and args.resume:
        raise PackError("--resume is unsafe for a normal update because changed content can have the same size")

    expected_confirmation = f"{summary['id']}@{summary['version']}"
    confirmed = args.confirm
    if confirmed is None and sys.stdin.isatty():
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        confirmed = input(f"Type {expected_confirmation} to publish: ").strip()
    if confirmed != expected_confirmation:
        raise PackError(f"production confirmation missing; pass --confirm {expected_confirmation!r} only after explicit approval")

    token = os.environ.get(args.token_env)
    if not token:
        raise PackError(f"environment variable {args.token_env} is not set")

    encoded_id = quote(summary["id"], safe="")
    admin_base = f"{base}/admin/api/packs/{encoded_id}"
    status = request_json(admin_base, token=token)
    existing_sizes = {
        item.get("filename"): item.get("size")
        for item in status.get("docs", [])
        if isinstance(item, dict)
    }

    skipped = 0
    uploaded = 0
    for index, (filename, data) in enumerate(sorted(pack.docs.items()), 1):
        if args.resume and existing_sizes.get(filename) == len(data):
            skipped += 1
            print(f"[{index}/{len(pack.docs)}] skip same-size existing document: {filename}")
            continue
        url = f"{admin_base}/docs/{quote(filename, safe='')}"
        request_bytes(
            url,
            method="PUT",
            body=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/html; charset=utf-8"},
        )
        uploaded += 1
        print(f"[{index}/{len(pack.docs)}] uploaded {filename} ({len(data)} bytes)")

    result = request_json(f"{admin_base}/publish", method="POST", value=pack.manifest, token=token)
    published = result.get("published") if isinstance(result, dict) else None
    if not isinstance(published, dict):
        raise PackError("publish response is missing published metadata")
    if published.get("id") != summary["id"] or published.get("version") != summary["version"]:
        raise PackError(f"unexpected publish response: {published}")

    verified = verify_public(pack, summary, base)
    return {
        "plan": plan,
        "uploaded_documents": uploaded,
        "skipped_documents": skipped,
        "orphans_deleted": result.get("orphans_deleted", []),
        "published": published,
        "verification": verified,
    }


def add_validation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-root", help="SCPHub workspace root; auto-detected when omitted")
    parser.add_argument(
        "--skip-core-collision-check",
        action="store_true",
        help="unsafe unless core data is unavailable and the risk was explicitly accepted",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate a source directory or ZIP")
    validate_parser.add_argument("package")
    add_validation_options(validate_parser)

    build_parser = subparsers.add_parser("build", help="build a canonical ZIP from a source directory")
    build_parser.add_argument("source")
    build_parser.add_argument("output")
    build_parser.add_argument("--overwrite", action="store_true")
    add_validation_options(build_parser)

    plan_parser = subparsers.add_parser("plan", help="validate and inspect current public state without writing")
    plan_parser.add_argument("package")
    plan_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    add_validation_options(plan_parser)

    publish_parser = subparsers.add_parser("publish", help="upload, publish, and verify a pack")
    publish_parser.add_argument("package")
    publish_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    publish_parser.add_argument("--token-env", default="SCPHUB_ADMIN_TOKEN")
    publish_parser.add_argument("--confirm")
    publish_parser.add_argument("--allow-same-version", action="store_true")
    publish_parser.add_argument("--resume", action="store_true")
    add_validation_options(publish_parser)

    verify_parser = subparsers.add_parser("verify", help="verify public list, manifest, and document bytes")
    verify_parser.add_argument("package")
    verify_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    add_validation_options(verify_parser)

    args = parser.parse_args(argv)
    try:
        pack, summary, _ = validate_path(
            args.package if hasattr(args, "package") else args.source,
            args.workspace_root,
            args.skip_core_collision_check,
        )
        if args.command == "validate":
            print(json.dumps({"valid": True, **summary}, ensure_ascii=False, indent=2))
        elif args.command == "build":
            build_zip(pack, Path(args.output), args.overwrite)
            built, built_summary, _ = validate_path(args.output, args.workspace_root, args.skip_core_collision_check)
            del built
            print(json.dumps({"built": str(Path(args.output).expanduser().resolve()), **built_summary}, ensure_ascii=False, indent=2))
        elif args.command == "plan":
            print(json.dumps(make_plan(pack, summary, normalize_base_url(args.base_url)), ensure_ascii=False, indent=2))
        elif args.command == "publish":
            print(json.dumps(publish(pack, summary, args), ensure_ascii=False, indent=2))
        elif args.command == "verify":
            print(json.dumps(verify_public(pack, summary, normalize_base_url(args.base_url)), ensure_ascii=False, indent=2))
        return 0
    except (PackError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
