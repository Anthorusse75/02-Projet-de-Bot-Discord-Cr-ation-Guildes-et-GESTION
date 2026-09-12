from __future__ import annotations

import hashlib

from scripts import package_stage10_rc as rc


def test_sha256_file_matches_known_digest(tmp_path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"stage10-rc")

    assert rc.sha256_file(artifact) == hashlib.sha256(b"stage10-rc").hexdigest()


def test_sarif_summary_counts_critical_high_and_other() -> None:
    payload = {
        "runs": [
            {
                "results": [
                    {"message": {"text": "Severity         :CRITICAL\nPackage:x"}},
                    {"message": {"text": "Severity         :HIGH\nPackage:y"}},
                    {"message": {"text": "Severity         :MEDIUM\nPackage:z"}},
                ]
            }
        ]
    }

    assert rc.sarif_summary(payload) == {"critical": 1, "high": 1, "other": 1}
