from __future__ import annotations

import json
import sys
from pathlib import Path

from did.api.main import create_app


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_openapi.py OUTPUT")
    destination = Path(sys.argv[1]).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
