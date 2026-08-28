from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from did.api.main import create_app

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> int:
    checked_json = FRONTEND / "openapi.json"
    expected = create_app().openapi()
    actual = json.loads(checked_json.read_text(encoding="utf-8"))
    if actual != expected:
        raise SystemExit("frontend/openapi.json drifted; run npm run openapi:generate")
    with tempfile.TemporaryDirectory(prefix="did-openapi-") as directory:
        temporary_schema = Path(directory) / "openapi.json"
        output = Path(directory) / "openapi.d.ts"
        temporary_schema.write_bytes(checked_json.read_bytes())
        npm = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run(  # noqa: S603 - fixed local executable and checked-in input
            [npm, "exec", "--", "openapi-typescript", str(temporary_schema), "-o", str(output)],
            cwd=FRONTEND,
            check=True,
        )
        if output.read_bytes() != (FRONTEND / "src/api/openapi.d.ts").read_bytes():
            raise SystemExit("frontend/src/api/openapi.d.ts drifted; run npm run openapi:generate")
    print("OpenAPI snapshot and generated TypeScript are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
