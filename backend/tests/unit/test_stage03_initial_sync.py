import asyncio

from did.application.reconciliation import DiscordSyncService

GUILD = 730303030303030301


class AdapterProbe:
    def __init__(self) -> None:
        self.channel_calls = 0
        self.role_calls = 0

    async def fetch_channels(self, guild_id: int):
        self.channel_calls += 1
        return [
            {
                "channel_id": GUILD + 1,
                "type": 0,
                "name": "channel",
                "position": 0,
                "permission_overwrites": [],
            }
        ]

    async def fetch_roles(self, guild_id: int):
        self.role_calls += 1
        return [{"role_id": GUILD, "name": "@everyone", "position": 0}]


class RepositoryProbe:
    def __init__(self) -> None:
        self.channel_snapshots = 0
        self.role_snapshots = 0
        self.completions = 0

    async def apply_rest_channel_snapshot(self, **_: object) -> None:
        self.channel_snapshots += 1

    async def apply_rest_role_snapshot(self, **_: object) -> None:
        self.role_snapshots += 1

    async def mark_structure_sync_complete(self, guild_id: int, **_: object) -> None:
        self.completions += 1


class SingleFlightProbe:
    async def run(self, guild_id: int, logical_key: str, operation):
        return await operation()


def service(adapter: AdapterProbe, repository: RepositoryProbe) -> DiscordSyncService:
    return DiscordSyncService(
        adapter=adapter,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        singleflight=SingleFlightProbe(),  # type: ignore[arg-type]
    )


async def test_initial_sync_is_bounded_idempotent_and_marks_full_coverage() -> None:
    adapter = AdapterProbe()
    repository = RepositoryProbe()
    sync = service(adapter, repository)
    assert await sync.initial_sync(GUILD) == {"channels": 1, "roles": 1, "interrupted": 0}
    assert await sync.initial_sync(GUILD) == {"channels": 1, "roles": 1, "interrupted": 0}
    assert adapter.channel_calls == 2
    assert adapter.role_calls == 2
    assert repository.channel_snapshots == 2
    assert repository.role_snapshots == 2
    assert repository.completions == 2


async def test_initial_sync_is_interruptible_before_any_rest_call() -> None:
    adapter = AdapterProbe()
    repository = RepositoryProbe()
    stop = asyncio.Event()
    stop.set()
    result = await service(adapter, repository).initial_sync(GUILD, stop_event=stop)
    assert result == {"channels": 0, "roles": 0, "interrupted": 1}
    assert adapter.channel_calls == 0
    assert adapter.role_calls == 0
