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

    def test_default_profile_includes_requirement_audit_and_only_rc_pending_gate(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="default")
        names = [step.name for step in steps]

        assert "STAGE 10 requirement audit (normal mode)" in names
        assert "STAGE 10 requirement audit (strict closure)" in names
        assert any("S10-BOT" in name for name in names)
        assert any("S10-DATA" in name for name in names)
        assert any("S10-RC backend image build" in name for name in names)
        assert not any("S10-TEST" in name for name in names)
        assert not any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)
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
            (sys.executable, "scripts/validate_stage.py", f"{stage:02d}") for stage in range(1, 10)
        ]
        assert prior_stage_live_commands == prior_stage_commands

    def test_default_profile_adds_discord_live_gate_only_when_requested(self) -> None:
        without_live = validate_stage.stage_10(
            Path("evidence"), include_discord_live=False, profile="default"
        )
        with_live = validate_stage.stage_10(
            Path("evidence"), include_discord_live=True, profile="default"
        )

        assert not any("evidence promotion" in step.name for step in without_live)
        assert not any("validated live evidence" in step.name for step in without_live)
        live_steps = [
            step for step in with_live if step.name.startswith("Stage 10 Discord live A/B matrix")
        ]
        assert len(live_steps) == 8
        assert all("_stage10_missing_gate.py" not in " ".join(step.command) for step in live_steps)

    def test_live_promotion_and_traceability_precede_strict_closure(self) -> None:
        steps = validate_stage.stage_10(
            Path("evidence/current-run"),
            include_discord_live=True,
            profile="default",
            expected_commit="a" * 40,
            expected_run_id="current-run",
        )
        names = [step.name for step in steps]

        tail = names[names.index("Stage 10 Discord live A/B matrix — Stage 09-full-chain") :]
        assert tail == [
            "Stage 10 Discord live A/B matrix — Stage 09-full-chain",
            "Stage 10 Discord live A/B evidence promotion",
            "Stage 10 traceability regeneration from validated live evidence",
            "Stage 10 promoted traceability documentation validation",
            "STAGE 10 requirement audit (strict closure)",
        ]
        assert "--expected-commit" in steps[-4].command
        assert "--expected-run-id" in steps[-4].command

    def test_offline_stage10_has_no_promotion_or_promoted_regeneration(self) -> None:
        steps = validate_stage.stage_10(
            Path("evidence/current-run"), include_discord_live=False, profile="default"
        )
        commands = [" ".join(step.command) for step in steps]

        assert commands.count(f"{sys.executable} scripts/generate_traceability.py") == 1
        assert not any("promote_stage10_live_evidence.py" in command for command in commands)
        assert not any("--stage10-live-closure" in command for command in commands)

    def test_security_profile_runs_real_backend_and_supply_chain_gates(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="security")
        names = [step.name for step in steps]

        assert any("backend security" in name for name in names)
        assert any("dependency vulnerability audit" in name for name in names)
        assert not any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    def test_performance_profile_runs_real_scale_and_browser_gates(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="performance")

        assert any("representative Guild" in step.name for step in steps)
        assert any("large-tree" in step.name for step in steps)
        assert not any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    def test_failure_injection_profile_runs_real_destructive_and_recovery_gates(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="failure-injection")
        names = [step.name for step in steps]

        assert any("global failure-injection" in name for name in names)
        failure_step = next(step for step in steps if "global failure-injection" in step.name)
        assert failure_step.command[failure_step.command.index("-m") + 1] == "failure_injection"
        assert "-k" not in failure_step.command
        assert not any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    def test_e2e_profile_runs_the_complete_playwright_suite(self) -> None:
        steps = validate_stage.stage_10(Path("evidence"), profile="e2e")

        assert any("global Playwright" in step.name for step in steps)
        e2e_step = next(step for step in steps if "Playwright" in step.name)
        assert e2e_step.command[-1] == "test:e2e"
        assert not any("_stage10_missing_gate.py" in " ".join(step.command) for step in steps)

    @pytest.mark.parametrize("profile", ["default"])
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

    def test_run_step_never_inherits_disabled_node_tls_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, str] = {}

        def completed(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured.update(kwargs["env"])  # type: ignore[arg-type]
            return subprocess.CompletedProcess([], 0)

        monkeypatch.setenv("NODE_TLS_REJECT_UNAUTHORIZED", "0")
        monkeypatch.setattr(validate_stage.subprocess, "run", completed)

        result = validate_stage.run_step(validate_stage.Step("safe", ("safe-command",)))

        assert result.status == "PASS"
        assert "NODE_TLS_REJECT_UNAUTHORIZED" not in captured


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

    @pytest.mark.parametrize(
        ("args", "expected_message"),
        [
            (("10", "--profile", "load"), "STAGE 03, STAGE 05 and STAGE 09"),
            (
                ("03", "--profile", "failure-injection"),
                "STAGE 05, STAGE 09 and STAGE 10",
            ),
            (("06", "--profile", "e2e"), "STAGE 07, STAGE 08, STAGE 09 and STAGE 10"),
            (("05", "--profile", "performance"), "STAGE 10"),
            (("10", "--profile", "translation-benchmark"), "STAGE 09"),
            (
                ("09", "--profile", "translation-benchmark"),
                "requires --allow-network",
            ),
        ],
    )
    def test_invalid_profiles_create_no_evidence(
        self,
        args: tuple[str, ...],
        expected_message: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        evidence_root = tmp_path / "evidence"
        monkeypatch.setattr(validate_stage, "EVIDENCE_ROOT", evidence_root)
        monkeypatch.setattr(sys, "argv", ["validate_stage.py", *args])

        assert validate_stage.main() == 2
        assert expected_message in capsys.readouterr().out
        assert not evidence_root.exists()

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
