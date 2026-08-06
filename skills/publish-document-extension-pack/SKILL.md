---
name: publish-document-extension-pack
description: Build, validate, publish, update, retry, and verify SCPHub document extension packs (文档扩展包) using the `manifest.json` plus `docs/*.html` format and `/api/v1/packs` admin API. Use for new or revised downloadable document packs, their ZIP archives, manifests, HTML payloads, version checks, production upload plans, and post-publish verification. Do not use for core site packs, `.scppack` files, `site-packs/index.json`, or the site-pack release pipeline.
---

# Publish SCPHub Document Extension Packs

## Keep the two pack systems separate

Operate only on document extension packs served from `packs/{packId}` and listed by `/api/v1/packs`. Never invoke `tools/scripts/release.mjs`, `site-pack-builder`, `publish-site-packs.mjs`, or write `site-packs/*` for this task. Read [references/project-contract.md](references/project-contract.md) before preparing or publishing a pack.

## Locate the workspace and inputs

Find the workspace root by requiring all of these paths:

- `README.md`
- `data/scpdata-full/`
- `scphub-backend/pack-server/worker.js`
- `scphub-backend/pack-server/admin.html`

Accept either a source directory containing `manifest.json` and `docs/*.html`, or a finished ZIP. If metadata or document inputs are missing, ask only for the missing values; do not invent titles, tags, discussion URLs, or article content.

Treat `worker.js`, `admin.html`, `HubAPI.swift`, and `PackManager.swift` as the live contract. If they differ from the bundled reference, follow the live code and update this skill before publishing.

## Validate and build

Use the bundled script for deterministic checks. It validates the manifest, UTF-8 standalone HTML, the exact document set, URL-safe identifiers, discussion URLs, and collisions with the core library for the same site.

```bash
python3 <skill-dir>/scripts/document_extension_pack.py validate <source-dir-or-zip> \
  --workspace-root <workspace-root>

python3 <skill-dir>/scripts/document_extension_pack.py build <source-dir> <output.zip> \
  --workspace-root <workspace-root>
```

Do not bypass the core filename collision check unless the workspace data is genuinely unavailable and the user explicitly accepts that risk. Build the canonical archive with `manifest.json` and `docs/` at its root; do not include `.DS_Store`, `__MACOSX`, source notes, or unrelated files.

## Plan the production change

Run the read-only plan before any upload:

```bash
python3 <skill-dir>/scripts/document_extension_pack.py plan <pack.zip> \
  --workspace-root <workspace-root> \
  --base-url https://scphub-api.swiftc.cc
```

Summarize the base URL, pack ID, site, requested version, current published version, document count, byte size, and whether this is a new publish, update, or same-version retry.

For a new pack, require that its ID is not already listed. For an update, keep the ID and increment `version`; any content or manifest change requires a higher version so installed clients see an update. Permit the same version only to retry the exact same artifact after a failed/interrupted publish, and pass `--allow-same-version` explicitly.

## Obtain confirmation and publish

Publishing writes production R2 objects and the public index. Show the plan and obtain explicit user confirmation immediately before the write. Do not treat an earlier request to inspect, validate, or build as publish authorization.

Read the admin token only from the environment; never request it in chat, put it in a command argument, print it, or persist it in the skill/project. The default variable is `SCPHUB_ADMIN_TOKEN`.

```bash
python3 <skill-dir>/scripts/document_extension_pack.py publish <pack.zip> \
  --workspace-root <workspace-root> \
  --base-url https://scphub-api.swiftc.cc \
  --confirm '<pack-id>@<version>'
```

Use `--resume` only when retrying the identical archive after interruption; it skips server documents with the same byte size. Never use `--resume` for a normal update because same-size content can still differ. The script uploads documents first, publishes the manifest/index last, and performs a byte-for-byte public verification.

If the token is available only in the dashboard session, use the same-origin `/admin` dashboard instead: select the validated ZIP, inspect its report, obtain confirmation, and click publish. Do not paste the token into automation or logs.

## Verify and report

Re-run public verification when needed:

```bash
python3 <skill-dir>/scripts/document_extension_pack.py verify <pack.zip> \
  --workspace-root <workspace-root> \
  --base-url https://scphub-api.swiftc.cc
```

Verification must confirm the site list entry, served manifest, every document body, computed document count, and total download size. Report the published ID/version, document count, bytes, verification result, and any orphan documents the server pruned. Mention that public responses advertise a five-minute cache even though the verifier uses cache-busting queries.

If publication fails after some document uploads, preserve the ZIP and report that the server keeps uploaded documents for a safe identical-artifact retry. Do not delete or unlist a pack unless the user separately asks for deletion.
