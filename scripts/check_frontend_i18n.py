from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISIBLE_TEXT = re.compile(r"<([A-Za-z][\w.]*)\b[^>]*>\s*([^<>{}\n]*[A-Za-z][^<>{}\n]*)\s*</\1\s*>")
VISIBLE_ATTRIBUTE = re.compile(
    r"\b(?:aria-label|alt|placeholder|title)\s*=\s*[\"']([A-Za-z][^\"']*)[\"']"
)
ALLOWLIST = {"DID", "Ctrl K"}


def violations(scan_root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted((*scan_root.rglob("*.ts"), *scan_root.rglob("*.tsx"))):
        if path.name.endswith((".test.ts", ".test.tsx", ".d.ts")) or "localization" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in (VISIBLE_TEXT, VISIBLE_ATTRIBUTE):
            for match in pattern.finditer(source):
                value = " ".join(match.group(pattern.groups).split())
                if value and value not in ALLOWLIST:
                    line = source.count("\n", 0, match.start()) + 1
                    found.append(f"{path.relative_to(scan_root)}:{line}: {value}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject visible frontend literals outside i18n")
    parser.add_argument("--scan-root", type=Path, default=ROOT / "frontend" / "src")
    args = parser.parse_args()
    found = violations(args.scan_root.resolve())
    if found:
        print("Visible frontend literals must use the typed localization catalogue:")
        print("\n".join(found))
        return 1
    print("Frontend visible literal scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
