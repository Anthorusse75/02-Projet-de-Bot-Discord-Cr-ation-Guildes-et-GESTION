"""Failure-path tests for the Stage09 live-qualification cleanup registry.

Root cause this proves fixed (external review finding): the full-chain live
qualification script used to batch created Discord channels into a second
list, copied from the per-run registration list only after every scenario
group had already completed successfully -- so a mid-run exception, timeout,
or cancellation left the copy step never reached, and the script's own
`finally` block (which only ever looked at the copy) deleted nothing, even
though real channels had already been created. `CleanupRegistry`
(scripts/_stage09_cleanup_registry.py) fixes this by registering each
resource for cleanup the instant it is created, and by being referenced
directly (never copied) from the `finally` block that calls
`cleanup_all()`. These tests exercise the registry in isolation -- no
discord.py or live sandbox required -- proving cleanup survives every exit
path the mission requires: a mid-run exception, a cancellation, one deletion
that itself raises while others still succeed, and normal completion.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from _stage09_cleanup_registry import CleanupRegistry

pytestmark = [pytest.mark.security]


class _NotFound(Exception):
    """Stands in for discord.NotFound without depending on discord.py."""


class _FakeResource:
    """A minimal stand-in for a real Discord resource (e.g. a TextChannel):
    tracks whether `delete()` was actually awaited, and can be configured to
    raise on delete."""

    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.raises = raises
        self.delete_called = False

    async def delete(self) -> None:
        self.delete_called = True
        if self.raises is not None:
            raise self.raises


def _register(registry: CleanupRegistry, resource: _FakeResource, label: str) -> None:
    registry.register(
        kind="fake-resource",
        label=label,
        delete=resource.delete,
        already_absent_exceptions=(_NotFound,),
    )


class TestNormalCompletion:
    @pytest.mark.asyncio
    async def test_all_registered_resources_are_deleted(self) -> None:
        registry = CleanupRegistry()
        resources = [_FakeResource() for _ in range(4)]
        for i, resource in enumerate(resources):
            _register(registry, resource, f"resource-{i}")

        await registry.cleanup_all()

        assert all(resource.delete_called for resource in resources)
        assert registry.summary() == {
            "created": 4,
            "deletion_attempted": 4,
            "deleted_or_already_absent": 4,
            "failed": 0,
            "remaining": 0,
        }

    @pytest.mark.asyncio
    async def test_empty_registry_is_a_safe_no_op(self) -> None:
        registry = CleanupRegistry()
        await registry.cleanup_all()
        assert registry.summary() == {
            "created": 0,
            "deletion_attempted": 0,
            "deleted_or_already_absent": 0,
            "failed": 0,
            "remaining": 0,
        }


class TestExceptionAfterSeveralResourcesCreated:
    """The exact regression this registry fixes: an exception raised after
    N resources were already registered must never prevent those N from
    being cleaned up once `cleanup_all()` finally runs -- proving
    registration and cleanup are decoupled from whether the run "succeeded"."""

    @pytest.mark.asyncio
    async def test_registry_retains_resources_registered_before_a_mid_run_exception(
        self,
    ) -> None:
        registry = CleanupRegistry()
        resources = [_FakeResource() for _ in range(3)]

        async def simulate_interrupted_run() -> None:
            for i, resource in enumerate(resources):
                _register(registry, resource, f"resource-{i}")
                if i == 1:
                    raise RuntimeError("provider failure mid-run")

        with pytest.raises(RuntimeError, match="provider failure mid-run"):
            try:
                await simulate_interrupted_run()
            finally:
                # This is the real fix under test: cleanup runs from a
                # finally block that always executes, and it sees every
                # resource registered so far -- never an empty snapshot
                # taken before the interruption.
                await registry.cleanup_all()

        # Only resource-0 and resource-1 were ever registered (the loop
        # never reached resource-2) -- both must have been cleaned up.
        assert resources[0].delete_called is True
        assert resources[1].delete_called is True
        assert resources[2].delete_called is False  # never created, correctly untouched
        assert registry.created_count == 2
        assert registry.remaining_count == 0


class TestCancellation:
    @pytest.mark.asyncio
    async def test_registry_retains_resources_registered_before_a_cancellation(self) -> None:
        registry = CleanupRegistry()
        resources = [_FakeResource() for _ in range(3)]

        async def simulate_run() -> None:
            for i, resource in enumerate(resources):
                _register(registry, resource, f"resource-{i}")
                if i == 1:
                    raise asyncio.CancelledError()
                await asyncio.sleep(0)

        task = asyncio.ensure_future(simulate_run())
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await registry.cleanup_all()

        assert resources[0].delete_called is True
        assert resources[1].delete_called is True
        assert resources[2].delete_called is False
        assert registry.remaining_count == 0


class TestBestEffortAcrossFailingDeletions:
    @pytest.mark.asyncio
    async def test_one_delete_raising_does_not_abort_cleanup_of_later_resources(self) -> None:
        registry = CleanupRegistry()
        first = _FakeResource()
        second = _FakeResource(raises=RuntimeError("Discord API 500"))
        third = _FakeResource()
        for i, resource in enumerate((first, second, third)):
            _register(registry, resource, f"resource-{i}")

        await registry.cleanup_all()

        assert first.delete_called is True
        assert second.delete_called is True
        assert third.delete_called is True  # never skipped despite `second` raising
        assert registry.summary() == {
            "created": 3,
            "deletion_attempted": 3,
            "deleted_or_already_absent": 2,
            "failed": 1,
            "remaining": 1,
        }
        assert any("resource-1" in failure for failure in registry.failures)

    @pytest.mark.asyncio
    async def test_already_absent_resource_counts_as_cleaned_not_failed(self) -> None:
        registry = CleanupRegistry()
        already_gone = _FakeResource(raises=_NotFound())
        _register(registry, already_gone, "resource-0")

        await registry.cleanup_all()

        assert registry.summary() == {
            "created": 1,
            "deletion_attempted": 1,
            "deleted_or_already_absent": 1,
            "failed": 0,
            "remaining": 0,
        }

    @pytest.mark.asyncio
    async def test_multiple_failures_are_all_recorded_and_none_block_the_others(self) -> None:
        registry = CleanupRegistry()
        resources = [
            _FakeResource(raises=RuntimeError("boom-a")),
            _FakeResource(),
            _FakeResource(raises=RuntimeError("boom-b")),
        ]
        for i, resource in enumerate(resources):
            _register(registry, resource, f"resource-{i}")

        await registry.cleanup_all()

        assert all(resource.delete_called for resource in resources)
        assert registry.failed == 2
        assert registry.deleted == 1
        assert registry.remaining_count == 2
        assert len(registry.failures) == 2
