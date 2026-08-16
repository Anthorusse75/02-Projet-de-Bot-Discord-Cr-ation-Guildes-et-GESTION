# Test evidence storage

`scripts/validate_stage.py XX` creates one immutable directory per run:

```text
artifacts/test-evidence/stage-XX/<run-id>/
```

Run directories are ignored by Git. Local JUnit files may contain machine metadata and must not be
committed. In CI, the complete run directory is uploaded as a GitHub Actions artifact; its
`summary.json` records the tested commit, environment, requirements, commands, gates, artifact
identifier and redaction result. The stage handoff retains only a stable representative run and
the convention for locating the authoritative check on the current PR head.
