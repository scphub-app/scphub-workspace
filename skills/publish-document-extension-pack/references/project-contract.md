# SCPHub document extension pack contract

## Source of truth

Re-check these workspace files before a production publish:

- `README.md`: distinguishes extension packs from core site packs.
- `scphub-backend/pack-server/worker.js`: routes, validation, R2 keys, publish order, and auth.
- `scphub-backend/pack-server/admin.html`: canonical ZIP validation and operator workflow.
- `scphub/scphub/src/Core/Networking/HubAPI.swift`: client API contract.
- `scphub/scphub/src/Core/PackManager.swift`: client manifest decoding and installed layout.

Do not use `scphub-backend/pack-server/example/manifest.json` as a template. It uses the obsolete `documents` shape and includes `.html` in filenames; the live contract requires `files` and extensionless filenames.

## Formats that must not be mixed

Document extension pack:

```text
ZIP input                     R2/public API
manifest.json                 packs/{packId}/manifest.json
docs/{filename}.html          packs/{packId}/docs/{filename}
```

Installed client layout:

```text
packs/{siteId}/{packId}/manifest.json
packs/{siteId}/{packId}/SCPs/{siteId}-{filename}.html
```

Core site packs are unrelated `.scppack` SQLite files under `site-packs/*`. Never use the site-pack builder or release orchestrator for an extension pack.

## Canonical manifest

```json
{
  "id": "cn-tales-001",
  "site_id": "cn",
  "name": "故事精选 Vol.1",
  "summary": "未收录进离线库的精选故事",
  "version": 1,
  "files": [
    {
      "name": "SCP-CN-XXXX - 某标题",
      "tags": ["scp", "euclid"],
      "filename": "scp-cn-xxxx",
      "discuss_url": "https://scp-wiki-cn.wikidot.com/forum/t-XXXXXXX/discuss"
    }
  ]
}
```

Rules:

- `id` is globally unique and matches `[A-Za-z0-9][A-Za-z0-9._-]*`.
- `site_id` is one of `en ru ko cn fr pl es th jp de it ua pt cs zh vn`.
- `name` is non-empty; `summary` is optional string or null.
- `version` is an integer starting at 1. Increase it for every update visible to installed clients.
- `files` is non-empty. Each item has non-empty `name`, string-array `tags`, URL-safe extensionless `filename`, and a full `discuss_url`.
- Filenames are unique within the manifest and must not collide with a core document for the same site. A collision makes the core document win at read time, so the extension document would be shadowed.
- The ZIP contains exactly one `docs/{filename}.html` per manifest item. HTML is complete, standalone, UTF-8 content.
- The served manifest omits `summary`; summary belongs to the global list entry.

## Publication behavior

Admin API authentication uses `Authorization: Bearer <ADMIN_TOKEN>`.

```text
GET  /admin/api/packs
GET  /admin/api/packs/{id}
PUT  /admin/api/packs/{id}/docs/{filename}
POST /admin/api/packs/{id}/publish
```

The publish endpoint validates the manifest, requires every referenced document to exist, prunes old unreferenced documents, writes the served manifest, then writes `index.json` last. Equal versions are accepted for an idempotent retry; lower versions are rejected. The client only offers an update when the listed version is greater than the installed version.

The index update is read-modify-write with last-write-wins semantics. Keep a single administrator/publisher active at a time.

## Public verification

```text
GET /api/v1/packs?site={siteId}
GET /api/v1/packs/{packId}
GET /api/v1/packs/{packId}/docs/{filename}
```

List, manifest, and document responses advertise `Cache-Control: public, max-age=300`. Use unique query parameters for immediate verification. Verify content, not only status codes.
