#!/usr/bin/env python3
"""Generate local Stage 10 RC metadata, frontend SBOM and checksums.

The script never creates a Git tag or pushes an image. Image build, image SBOM
and vulnerability scan remain explicit validator steps so their failures are
visible independently in the validation summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
INPUTS = (
    ROOT / "pyproject.toml",
    ROOT / "uv.lock",
    ROOT / "backend" / "Dockerfile",
    FRONTEND / "package.json",
    FRONTEND / "package-lock.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sarif_summary(payload: dict[str, Any]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "other": 0}
    for run in payload.get("runs", []):
        for result in run.get("results", []):
            message = str(result.get("message", {}).get("text", ""))
            if "Severity         :CRITICAL" in message:
                counts["critical"] += 1
            elif "Severity         :HIGH" in message:
                counts["high"] += 1
            else:
                counts["other"] += 1
    return counts


def run_json(command: list[str], *, cwd: Path) -> Any:
    environment = os.environ.copy()
    environment.pop("NODE_TLS_REJECT_UNAUTHORIZED", None)
    completed = subprocess.run(  # noqa: S603 - argv-only call to a resolved required tool
        command,
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image", default="did-stage10-backend:rc-candidate")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    output = arguments.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    docker = shutil.which("docker")
    git = shutil.which("git")
    if npm is None or docker is None or git is None:
        raise RuntimeError("npm, docker and git are required for RC packaging")

    frontend_sbom = run_json(
        [npm, "sbom", "--sbom-format", "cyclonedx"],
        cwd=FRONTEND,
    )
    if not isinstance(frontend_sbom, dict):
        raise ValueError("expected npm SBOM to be a JSON object")
    frontend_sbom_path = output / "frontend.cdx.json"
    frontend_sbom_path.write_text(
        json.dumps(frontend_sbom, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    inspect = run_json([docker, "inspect", arguments.image], cwd=ROOT)
    if not isinstance(inspect, list) or len(inspect) != 1:
        raise ValueError("expected docker inspect to return exactly one image")
    scan_path = output / "backend-image-cves.sarif"
    backend_sbom_path = output / "backend-image.cdx.json"
    for required in (scan_path, backend_sbom_path):
        if not required.is_file():
            raise FileNotFoundError(f"required validator artifact is missing: {required}")
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    scan_counts = sarif_summary(scan)
    if scan_counts["critical"]:
        raise RuntimeError("critical image vulnerabilities must be zero")

    commit = subprocess.run(  # noqa: S603 - argv-only call to resolved git
        [git, "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    dirty = bool(
        subprocess.run(  # noqa: S603 - argv-only call to resolved git
            [git, "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    )
    image = inspect[0]
    manifest = {
        "schema_version": 1,
        "stage": 10,
        "candidate": "stage10-local-rc",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": commit,
        "source_worktree_dirty": dirty,
        "git_tag_created": False,
        "production_deployed": False,
        "backend_image": {
            "reference": arguments.image,
            "id": image["Id"],
            "repo_digests": image.get("RepoDigests", []),
        },
        "frontend": {
            "build_directory": "frontend/dist",
            "sbom": frontend_sbom_path.name,
        },
        "scan": {
            "scanner": "docker scout",
            "critical": scan_counts["critical"],
            "high": scan_counts["high"],
            "other_in_critical_high_report": scan_counts["other"],
            "report": scan_path.name,
        },
        "backend_sbom": backend_sbom_path.name,
    }
    manifest_path = output / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    checksum_targets = [*INPUTS, backend_sbom_path, frontend_sbom_path, scan_path, manifest_path]
    checksum_targets.extend(sorted((FRONTEND / "dist").rglob("*")))
    checksum_lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        if path.is_relative_to(ROOT)
        else f"{sha256_file(path)}  {path.name}"
        for path in checksum_targets
        if path.is_file()
    ]
    (output / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        "Stage10 RC packaged: "
        f"critical={scan_counts['critical']} high={scan_counts['high']} "
        f"checksums={len(checksum_lines)} tag_created=false deployed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
