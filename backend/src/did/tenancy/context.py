from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantContext:
    guild_id: int
    user_id: int | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.user_id is not None and self.user_id <= 0:
            raise ValueError("user_id must be positive when provided")


_tenant_context: ContextVar[TenantContext | None] = ContextVar("did_tenant_context", default=None)


def current_tenant() -> TenantContext | None:
    return _tenant_context.get()


@contextmanager
def tenant_scope(context: TenantContext) -> Iterator[TenantContext]:
    token: Token[TenantContext | None] = _tenant_context.set(context)
    try:
        yield context
    finally:
        _tenant_context.reset(token)
