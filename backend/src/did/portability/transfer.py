from __future__ import annotations

from enum import StrEnum


class TransferState(StrEnum):
    CREATED = "CREATED"
    SOURCE_AUTHORIZED = "SOURCE_AUTHORIZED"
    EXPORTED = "EXPORTED"
    MAPPING_REQUIRED = "MAPPING_REQUIRED"
    READY = "READY"
    COMPILED = "COMPILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    def can_transition_to(self, target: TransferState) -> bool:
        return target in _TRANSITIONS[self]


_TRANSITIONS: dict[TransferState, frozenset[TransferState]] = {
    TransferState.CREATED: frozenset(
        {
            TransferState.SOURCE_AUTHORIZED,
            TransferState.EXPORTED,
            TransferState.FAILED,
            TransferState.CANCELLED,
        }
    ),
    TransferState.SOURCE_AUTHORIZED: frozenset(
        {TransferState.EXPORTED, TransferState.FAILED, TransferState.CANCELLED}
    ),
    TransferState.EXPORTED: frozenset(
        {
            TransferState.MAPPING_REQUIRED,
            TransferState.READY,
            TransferState.FAILED,
            TransferState.CANCELLED,
        }
    ),
    TransferState.MAPPING_REQUIRED: frozenset(
        {TransferState.READY, TransferState.FAILED, TransferState.CANCELLED}
    ),
    TransferState.READY: frozenset(
        {TransferState.COMPILED, TransferState.FAILED, TransferState.CANCELLED}
    ),
    TransferState.COMPILED: frozenset(),
    TransferState.FAILED: frozenset(),
    TransferState.CANCELLED: frozenset(),
}


def assert_transfer_transition(current: TransferState, target: TransferState) -> None:
    if not current.can_transition_to(target):
        raise ValueError(f"invalid transfer state transition: {current.value}->{target.value}")
