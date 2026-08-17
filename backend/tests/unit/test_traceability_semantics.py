from pathlib import Path
from runpy import run_path


def test_stage03_traceability_does_not_promote_future_subsystems() -> None:
    root = Path(__file__).resolve().parents[3]
    namespace = run_path(str(root / "scripts/generate_traceability.py"))
    progress = namespace["STAGE03_REQUIREMENT_PROGRESS"]

    assert progress["REQ-RATE-005"][0] == "PLANNED"
    assert progress["REQ-GW-006"][0] == "PLANNED"
    assert progress["REQ-CACHE-004"][0] == "PLANNED"
    assert progress["REQ-CACHE-007"][0] == "PLANNED"
    assert progress["REQ-AUD-002"][0] == "PLANNED"
    assert progress["REQ-AUD-003"][0] == "PLANNED"
    assert progress["REQ-TEN-008"][0] == "PLANNED"

    assert progress["REQ-RATE-002"][0] == "IMPLEMENTED"
    assert progress["REQ-RATE-004"][0] == "IMPLEMENTED"
    assert progress["REQ-RATE-006"][0] == "IMPLEMENTED"
    assert len(progress) == 38
