from __future__ import annotations

import base64
import os
import secrets
import stat
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"


def generated_values() -> dict[str, str]:
    return {
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "OAUTH_TOKEN_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32))
        .decode("ascii")
        .rstrip("="),
        "DID_OAUTH_TOKEN_KEY_VERSION": "1",
    }


def configure() -> tuple[str, ...]:
    original = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = original.splitlines()
    positions: dict[str, int] = {}
    current: dict[str, str] = {}
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in {"SESSION_SECRET", "OAUTH_TOKEN_ENCRYPTION_KEY", "DID_OAUTH_TOKEN_KEY_VERSION"}:
            positions[name] = index
            current[name] = value.strip()

    generated = generated_values()
    changed: list[str] = []
    for name, generated_value in generated.items():
        value = current.get(name) or generated_value
        if current.get(name) != value:
            changed.append(name)
        rendered = f"{name}={value}"
        if name in positions:
            lines[positions[name]] = rendered
        else:
            lines.append(rendered)
            changed.append(name)

    content = "\n".join(lines).rstrip() + "\n"
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".env.local.", suffix=".tmp", dir=ENV_FILE.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ENV_FILE)
        ENV_FILE.chmod(stat.S_IREAD | stat.S_IWRITE)
    finally:
        if temporary.exists():
            temporary.unlink()
    return tuple(dict.fromkeys(changed))


if __name__ == "__main__":
    configured = configure()
    names = ", ".join(configured) if configured else "none (already configured)"
    print(f"Local STAGE 02 secret names configured: {names}; values were not displayed.")
