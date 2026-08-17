from pathlib import Path


def test_stage03_live_runner_is_opt_in_redacted_and_non_mutating() -> None:
    source = Path("scripts/validate_discord_live_stage03.py").read_text(encoding="utf-8")
    assert 'status="SKIPPED_NOT_VERIFIED"' in source
    assert '"discord_mutations": 0' in source
    assert '"secrets_recorded": False' in source
    assert "PASS_WITH_APPROVED_LIMITATION" in source
    assert "CONTRACT_ONLY_NOT_LIVE_VERIFIED" in source
    assert ".delete_channel(" not in source
    assert ".create_text_channel(" not in source
    assert ".edit(" not in source
