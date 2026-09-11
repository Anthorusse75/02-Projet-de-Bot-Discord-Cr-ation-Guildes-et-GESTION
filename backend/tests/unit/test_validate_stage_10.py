from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts import validate_stage


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/validate_stage.py", *args],
        cwd=validate_stage.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class TestStageRegistration:
    def test_stage_10_is_registered(self) -> None:
        assert "10" in validate_stage.STAGES
        assert validate_stage.STAGES["10"].steps is validate_stage.stage_10

    def test_stage_10_requirements_cover_its_primary_ids(self) -> None:
        requirements = set(validate_stage.STAGES["10"].requirements)

        assert requirements == {
            "REQ-BOT-004",
            "REQ-BOT-005",
            "REQ-BOT-006",
            "REQ-DATA-001",
            "REQ-DATA-002",
            "REQ-TEST-001",
            "REQ-TEST-002",
            "REQ-TEST-003",
            "REQ-TEST-004",
            "REQ-TEST-005",
        }

    def test_prior_stages_are_still_registered(self) -> None:
        assert set(validate_stage.STAGES) == {
            "01",
            "02",
            "03",
            "04",
            "05",
            "06",
            "07",
            "08",
            "09",
            "10",
        }


class TestStage10ProfileStepLists:
    """Pure inspection of the Step tuples stage_10() returns -- no subprocess
    is ever executed here, only the declarative Step objects are checked."""

    def test_default_profile_includes_requirement_audit_and_pending_gates(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="default")
        names = [step.name for step in steps]

        assert "STAGE 10 requirement audit (normal mode)" in names
        assert "STAGE 10 requirement audit (strict closure)" in names
        assert any("S10-BOT" in name for name in names)
        assert any("S10-DATA" in name for name in names)
        assert any("S10-TEST" in name for name in names)
        assert any("S10-RC" in name for name in names)
        # the strict-closure audit is the final honest gate, run last
        assert names[-1] == "STAGE 10 requirement audit (strict closure)"

    def test_default_profile_orchestrates_all_prior_stage_validators(self) -> None:
        stage10_steps = validate_stage.stage_10(Path("evidence"), profile="default")
        stage10_live_steps = validate_stage.stage_10(
            Path("evidence"), include_discord_live=True, profile="default"
        )
        prior_stage_commands = [
            step.command
            for step in stage10_steps
            if step.name.startswith("STAGE ") and step.name.endswith(" validator")
        ]
        prior_stage_live_commands = [
            step.command
            for step in stage10_live_steps
            if step.name.startswith("STAGE ") and step.name.endswith(" validator")
        ]

        assert prior_stage_commands == [
            (sys.executable, "scripts/validate_stage.py", f"{stage:02d}")
            for stage in range(1, 10)
        ]
        assert prior_stage_live_commands == [
            (
                sys.executable,
                "scripts/validate_stage.py",
                f"{stage:02d}",
                "--include-discord-live",
            )
            for stage in range(1, 10)
        ]

    def test_default_profile_adds_discord_live_gate_only_when_requested(self) -> None:
        without_live = validate_stage.stage_10(
            Path("evidence"), include_discord_live=False, profile="default"
        )
        with_live = validate_stage.stage_10(
            Path("evidence"), include_discord_live=True, profile="default"
        )

        assert not any("Discord live" in step.name for step in without_live)
        assert any("Discord live" in step.name for step in with_live)

    def test_security_profile_has_a_pending_gate_and_no_fabricated_pass(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="security")

        assert any("S10-SEC" in step.name for step in steps)
        assert any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    def test_performance_profile_has_a_pending_gate(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="performance")

        assert any("performance" in step.name.lower() for step in steps)
        assert any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    def test_failure_injection_profile_has_a_pending_gate(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="failure-injection")

        assert any("failure" in step.name.lower() for step in steps)
        assert any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    def test_e2e_profile_has_a_pending_gate(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="e2e")

        assert any("E2E" in step.name for step in steps)
        assert any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    @pytest.mark.parametrize(
        "profile", ["default", "security", "performance", "failure-injection", "e2e"]
    )
    def test_no_profile_silently_claims_full_stage10_pass(self, profile: str) -> None:
        """Every Stage 10 profile must contain at least one step that is either
        the strict requirement-closure audit or an explicit pending-gate marker
        -- i.e. none of them can currently produce a false full PASS."""
        steps = validate_stage.stage_10(Path("evidence"), profile=profile)

        has_honesty_gate = any(
            "_stage10_missing_gate.py" in " ".join(step.command)
            or "audit_requirements.py" in " ".join(step.command)
            for step in steps
        )
        assert has_honesty_gate


class TestMissingGateStep:
    def test_missing_gate_step_command_always_fails(self) -> None:
        step = validate_stage.missing_gate_step("EXAMPLE", "example reason")
        result = subprocess.run(
            list(step.command), cwd=validate_stage.ROOT, capture_output=True, text=True
        )

        assert result.returncode != 0
        assert "EXAMPLE" in result.stderr
        assert "example reason" in result.stderr


class TestCliProfileValidation:
    """These only exercise the early argument-validation path in main(), which
    returns before any Step is executed -- no docker/uv/npm subprocess runs."""

    def test_stage_10_help_lists_new_profiles(self) -> None:
        result = run_cli("--help")

        assert result.returncode == 0
        assert "10" in result.stdout
        assert "performance" in result.stdout

    def test_performance_profile_rejected_for_other_stages(self) -> None:
        result = run_cli("05", "--profile", "performance")

        assert result.returncode == 2
        assert "STAGE 10" in result.stdout

    def test_load_profile_still_rejected_for_stage_10(self) -> None:
        result = run_cli("10", "--profile", "load")

        assert result.returncode == 2
        assert "STAGE 03, STAGE 05 and STAGE 09" in result.stdout

    def test_failure_injection_rejected_for_unrelated_stage(self) -> None:
        result = run_cli("03", "--profile", "failure-injection")

        assert result.returncode == 2

    def test_e2e_rejected_for_unrelated_stage(self) -> None:
        result = run_cli("06", "--profile", "e2e")

        assert result.returncode == 2

    def test_unknown_stage_rejected(self) -> None:
        result = run_cli("11")

        assert result.returncode != 0
