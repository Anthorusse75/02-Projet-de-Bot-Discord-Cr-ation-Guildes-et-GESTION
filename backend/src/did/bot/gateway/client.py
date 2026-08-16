from __future__ import annotations

from uuid import uuid4

import discord

from did.application.discord_runtime import (
    GatewayContractError,
    GatewaySessionTracker,
    normalize_gateway_dispatch,
)
from did.domain.discord_runtime import GatewayContinuity, MemberDataCapability
from did.infrastructure.runtime_repository import RuntimeRepository


def minimal_gateway_intents(*, enable_member_events: bool = False) -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = enable_member_events
    return intents


def member_data_capability(*, enable_member_events: bool) -> MemberDataCapability:
    return (
        MemberDataCapability.FULL_MEMBER_EVENTS
        if enable_member_events
        else MemberDataCapability.ON_DEMAND_MEMBER_LOOKUP
    )


class DiscordGatewayClient(discord.Client):
    """Gateway-only client: raw dispatches are durably normalized before projection."""

    def __init__(
        self,
        repository: RuntimeRepository,
        *,
        enable_member_events: bool = False,
    ) -> None:
        super().__init__(
            intents=minimal_gateway_intents(enable_member_events=enable_member_events),
            member_cache_flags=discord.MemberCacheFlags.none(),
            max_messages=None,
        )
        self.repository = repository
        self.session_tracker = GatewaySessionTracker()
        self.member_capability = member_data_capability(enable_member_events=enable_member_events)
        self.rejected_packets = 0

    async def on_socket_response(self, packet: dict[str, object]) -> None:
        event_type = packet.get("t")
        data = packet.get("d")
        if event_type == "READY" and isinstance(data, dict):
            session_id = data.get("session_id")
            if isinstance(session_id, str):
                self.session_tracker.ready(session_id)
            application = data.get("application")
            user = data.get("user")
            if isinstance(application, dict) and isinstance(user, dict):
                try:
                    application_id = int(application["id"])
                    bot_user_id = int(user["id"])
                except (KeyError, TypeError, ValueError):
                    self.rejected_packets += 1
                else:
                    self.repository.bind_bot_identity(
                        application_id=application_id, bot_user_id=bot_user_id
                    )
            return
        if event_type == "RESUMED":
            if self.session_tracker.session_id is not None:
                self.session_tracker.resumed(self.session_tracker.session_id)
            return
        session_id = self.session_tracker.session_id
        if session_id is None:
            return
        sequence = packet.get("s")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            previous_continuity = self.session_tracker.continuity
            continuity = self.session_tracker.observe_sequence(sequence)
        else:
            previous_continuity = self.session_tracker.continuity
            continuity = self.session_tracker.continuity
        try:
            envelope = normalize_gateway_dispatch(packet, discord_session_id=session_id)
        except GatewayContractError:
            self.rejected_packets += 1
            self.repository.metrics.gateway_signal("rejected")
            return
        if envelope is None:
            return
        if (
            continuity is GatewayContinuity.GAP_DETECTED
            and previous_continuity is not GatewayContinuity.GAP_DETECTED
        ):
            self.repository.metrics.gateway_signal("gap")
            await self.repository.record_gateway_discontinuity(
                guild_id=envelope.guild_id,
                continuity=continuity.value,
                correlation_id=uuid4(),
            )
        await self.repository.ingest_gateway_event(envelope)

    async def on_ready(self) -> None:
        if self.session_tracker.continuity is not GatewayContinuity.NON_RESUMED:
            return
        self.repository.metrics.gateway_signal("non_resumed")
        for guild in self.guilds:
            await self.repository.record_gateway_discontinuity(
                guild_id=int(guild.id),
                continuity=GatewayContinuity.NON_RESUMED.value,
                correlation_id=uuid4(),
            )

    async def on_disconnect(self) -> None:
        self.session_tracker.disconnected()
        self.repository.metrics.gateway_signal("disconnected")
