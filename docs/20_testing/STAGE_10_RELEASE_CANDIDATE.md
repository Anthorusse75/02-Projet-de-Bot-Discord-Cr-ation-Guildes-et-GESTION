# Stage 10 release candidate status

Status: `QUALIFIED_PRE_MERGE_REBUILD_REQUIRED`.

## Qualified source versus final immutable RC

The Discord-live qualified product commit is:

```text
0d9a913cd8171827fd896b16608eb1d583eadb08
```

The canonical Stage 10 qualification run passed the RC gates included in the
Stage 10 acceptance flow, including backend image build/import and the zero
critical-vulnerability gate.

The repository-level `artifacts/stage10-audit/` package is older historical
evidence created before the final live qualification. Its manifest references
an earlier SHA/worktree state, so it must **not** be relabeled as the final
immutable Stage 10 release candidate.

## Security state carried into closure

Recorded Stage 10 disposition:

- backend image critical vulnerabilities: **0**;
- backend image High findings: **1** known Debian zlib finding,
  `CVE-2026-85091`;
- the retained scan reported no fixed version for that zlib finding at the time
  of packaging;
- frontend `npm audit --audit-level=moderate`: **0** vulnerabilities in the
  Stage 10 acceptance pass;
- prior OpenSSL findings were removed by the Stage 10 Dockerfile/package update
  work;
- the production frontend chunk warning was removed by route-level lazy loading.

The zlib High remains visible and must be rescanned. It is neither filtered nor
silently reclassified.

## SBOM and package contents

Stage 10 packaging produces:

```text
backend-image.cdx.json
frontend.cdx.json
backend-image-cves.sarif
release-manifest.json
SHA256SUMS
frontend production dist
```

The historical package remains useful as build/scan evidence, but a new package
must be generated after the Stage 10 merge.

## Required post-merge rebuild

After `stage/10-acceptance` is merged into `main`, rebuild the release candidate
from the clean merged SHA. Do not reuse the historical manifest or digest.

Required sequence:

```bash
git switch main
git pull --ff-only
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_documentation.py
python scripts/package_stage10_rc.py --output-dir artifacts/stage10-audit --image did-stage10-backend:rc-candidate
docker compose -f compose.test.yaml down
```

The backend image itself must first be rebuilt from the merged SHA using the
Stage 10 Dockerfile, then smoke-imported and rescanned before the packaging
command records the final manifest/checksums.

The post-merge manifest must record a clean source SHA and remain explicit that
production deployment is false until STAGE 11 authorizes it.

## Tag and deployment policy

At this handoff:

```text
git_tag_created = false
production_deployed = false
```

No Stage 10 tag should be created until:

1. the Stage 10 offline CI workflow is green on the PR/merge candidate;
2. the PR is reviewed and merged with a merge commit preserving the qualified
   `0d9a913` ancestor;
3. the RC/SBOM/SARIF/checksums are rebuilt on the clean merged SHA;
4. the image is rescanned and the zlib High is redispositioned against the
   package versions available on that date;
5. explicit human authorization is given for the tag.

No production deployment, DNS, TLS or reverse-proxy action is authorized by
this document.

See also:

- [`STAGE_10_HANDOFF.md`](../90_handoffs/STAGE_10_HANDOFF.md)
- [`STAGE_10_DISCORD_LIVE_STATUS.md`](STAGE_10_DISCORD_LIVE_STATUS.md)
- [`STAGE_10_SECURITY_ACCEPTANCE.md`](../30_security/STAGE_10_SECURITY_ACCEPTANCE.md)
