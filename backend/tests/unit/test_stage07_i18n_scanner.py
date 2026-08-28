from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_i18n_scanner_rejects_new_visible_literal(tmp_path: Path) -> None:
    fixture = tmp_path / "DeleteButton.tsx"
    fixture.write_text(
        "export const DeleteButton = () => <button>Delete now</button>\n", encoding="utf-8"
    )
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/check_frontend_i18n.py", "--scan-root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "Delete now" in completed.stdout
