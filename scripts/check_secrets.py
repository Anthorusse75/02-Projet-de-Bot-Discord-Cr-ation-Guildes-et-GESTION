from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "Discord token": re.compile(r"[A-Za-z\d_-]{23,28}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}"),
}
FRONTEND_FORBIDDEN_NAMES = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_CLIENT_SECRET",
    "DATABASE_URL",
    "SESSION_SECRET",
)
GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable is required for the secret scan")


def repository_files() -> list[Path]:
    result = subprocess.run(
        [GIT, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def main() -> int:
    failures: list[str] = []
    for path in repository_files():
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative == "scripts/check_secrets.py":
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                failures.append(f"{relative}: possible {label}")
        if relative.startswith("frontend/"):
            for name in FRONTEND_FORBIDDEN_NAMES:
                if name in content:
                    failures.append(f"{relative}: backend-only setting name {name}")

    tracked_local = subprocess.run(
        [GIT, "ls-files", "--error-unmatch", ".env.local"],
        cwd=ROOT,
        capture_output=True,
    )
    ignored_local = subprocess.run(
        [GIT, "check-ignore", "-q", ".env.local"],
        cwd=ROOT,
    )
    if tracked_local.returncode == 0:
        failures.append(".env.local is tracked")
    if ignored_local.returncode != 0:
        failures.append(".env.local is not ignored")

    if failures:
        print("Secret scan FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Secret scan PASSED ({len(repository_files())} repository files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
