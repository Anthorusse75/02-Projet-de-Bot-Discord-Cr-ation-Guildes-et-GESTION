"""A durable, best-effort cleanup registry for Stage09 live Discord
qualification scripts.

Root cause this fixes (external review finding): the full-chain live
qualification used to register created channels into ``ctx.temp_channels``
immediately, but only copied that list into the OUTER list actually deleted
by the ``finally`` block after every scenario group had already completed
successfully (``temp_channels.extend(ctx.temp_channels)`` at the very end of
the scenario loop). Any exception, timeout, cancellation, or discord.py's own
event-handler exception-swallowing that interrupted the loop before that one
line left the outer list empty, so the ``finally`` block deleted nothing --
even though real Discord channels had already been created. This explains
the orphan ``did-s09-fc-...`` channels observed accumulating in the sandbox
after failed/interrupted live runs.

This registry is the fix: resources are registered HERE, directly, the
instant they are created -- never batched into a second list synced only on
success. A caller keeps exactly one ``CleanupRegistry`` instance alive for
the whole run (created before anything else, referenced by whatever context
object scenario functions use) and calls :meth:`cleanup_all` from a
``finally`` block that is guaranteed to run regardless of how the try block
above it exits. Because the registry is a single mutable object referenced
by identity (not copied), it is correct under every exit path: normal
completion, an assertion/provider failure partway through, a timeout,
a cancellation, or a partially-executed scenario group.

Generic over resource kind (not just text channels) -- a caller registers
any awaitable delete callback, so future resource types (roles, categories,
webhooks, ...) need no change to this module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class _CleanupEntry:
    kind: str
    label: str
    delete: Callable[[], Awaitable[None]]
    #: The exception type(s) that mean "already gone -- not a failure worth
    #: counting or logging loudly", e.g. Discord's own 404 NotFound. Kept
    #: per-entry (not hardcoded to discord.py) so this module has no
    #: dependency on discord.py itself and stays trivially unit-testable.
    already_absent_exceptions: tuple[type[BaseException], ...] = ()


@dataclass(slots=True)
class CleanupRegistry:
    """Tracks every resource created by one live-qualification run and
    deletes them best-effort: one failing deletion never aborts cleanup of
    the resources registered after it (or before it -- order does not
    matter to correctness here)."""

    _entries: list[_CleanupEntry] = field(default_factory=list)
    deleted: int = 0
    already_absent: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def register(
        self,
        *,
        kind: str,
        label: str,
        delete: Callable[[], Awaitable[None]],
        already_absent_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        """Registers a resource for cleanup IMMEDIATELY -- call this right
        after the resource is actually created, never batched/deferred."""
        self._entries.append(
            _CleanupEntry(
                kind=kind,
                label=label,
                delete=delete,
                already_absent_exceptions=already_absent_exceptions,
            )
        )

    @property
    def created_count(self) -> int:
        return len(self._entries)

    @property
    def remaining_count(self) -> int:
        return self.created_count - self.deleted - self.already_absent

    async def cleanup_all(self) -> None:
        """Best-effort: attempts every registered deletion exactly once,
        regardless of earlier failures. Safe to call even if nothing was
        registered (created_count == 0)."""
        for entry in self._entries:
            try:
                await entry.delete()
                self.deleted += 1
            except entry.already_absent_exceptions:
                self.already_absent += 1
            except Exception as exc:  # deliberately broad, see class docstring
                self.failed += 1
                self.failures.append(f"{entry.kind} {entry.label}: {exc!r}")

    def summary(self) -> dict[str, int]:
        return {
            "created": self.created_count,
            "deletion_attempted": self.created_count,
            "deleted_or_already_absent": self.deleted + self.already_absent,
            "failed": self.failed,
            "remaining": self.remaining_count,
        }
