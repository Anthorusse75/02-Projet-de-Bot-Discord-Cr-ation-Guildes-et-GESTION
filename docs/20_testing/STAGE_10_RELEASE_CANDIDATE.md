# Stage 10 local release candidate

Status: packaged locally, not tagged, pushed or deployed.

The canonical Stage 10 default validator builds
`did-stage10-backend:rc-candidate`, smoke-imports the application, generates
backend-image and frontend CycloneDX SBOMs, scans the image with Docker Scout,
builds the frontend production bundle and writes a manifest plus SHA-256 sums.

Current local candidate:

- Source HEAD: `ca48bd8ebfbf7561ae3926ee221001d45aa9654e` with the requested uncommitted Stage 10 working tree.
- Backend image digest: `sha256:98ac0b0437421dcb8ec506718f6b738ebefd53fb56f221121075d3bf5d6929c1` (`linux/amd64`, 72 MB, 180 indexed packages).
- Critical image vulnerabilities: zero.
- High image vulnerabilities: one, Debian zlib `CVE-2026-85091`; Docker Scout reports `Fixed version: not fixed`. It is retained as an explicit base-image risk, not suppressed. Rebuild and rescan when Debian publishes a fix.
- Frontend npm audit: zero vulnerabilities at moderate-or-higher severity.
- Checksums: 61 entries covering lock/manifest inputs, both SBOMs, scan report, RC manifest and frontend distribution files.
- `git_tag_created=false`; `production_deployed=false`.

Local evidence is under `artifacts/stage10-audit/`: `release-manifest.json`,
`SHA256SUMS`, `backend-image.cdx.json`, `frontend.cdx.json` and
`backend-image-cves.sarif`. Canonical validator runs write the same artifact
set into their immutable run directory.

The Dockerfile updates Debian packages at build time and removes the temporary
global `uv` installer after the locked production environment is created. This
removed four fixed OpenSSL high/critical findings and reduced the indexed
package count from 717 to 180.
