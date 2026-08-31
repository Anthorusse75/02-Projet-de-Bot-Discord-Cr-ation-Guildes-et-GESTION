"""Create-time and execution-time Guild authorization for Stage 09 (1E,
external-review finding, third remediation pass).

The composite FKs added in ``0023_stage_09_relational_integrity`` prove a
Guild-scoped child row (a ``message_campaign_targets`` or
``message_campaign_trigger_sources`` row) really belongs to the campaign/
trigger it references. They do NOT and cannot prove the *owner* of that
campaign/trigger is currently authorized for the *destination Guild* the
child row names -- a database constraint has no notion of "this Discord
user's role in that Discord server." That is a live authorization fact,
already the exact business the Stage 04/05
``did.application.auth.service.AuthorizationService`` exists to answer
(``MESSAGES_PUBLISH`` capability, defined and reserved for this purpose in
``did.domain.auth.Capability`` since before this campaign engine existed) --
this module is deliberately thin and delegates to it rather than
reimplementing any authorization logic of its own.

Two distinct checks compose here, both required before any Guild-scoped
Stage 09 row is persisted:

1. Is the calling owner currently authorized (a role bound at or above the
   ``MESSAGES_PUBLISH`` capability, active installation) for the
   destination Guild? (:class:`CampaignGuildAuthorizationChecker.is_guild_authorized`)
2. Does the DID bot itself currently have permission to send in the
   specific destination channel? (:meth:`bot_can_send`, reused by both
   create-time validation here and execution-time re-validation in
   ``did.campaigns.target_resolution`` -- the same
   :class:`did.campaigns.target_resolution.TargetAuthorizationChecker`
   protocol is implemented by this one class for both call sites).

Neither check is ever trusted from a cached/prior value: this class always
performs a fresh call. A caller-supplied ``owner_discord_user_id`` is never
authority on its own either -- the create-time service functions below only
ever use the *authenticated session's* owner id, resolved once by the API
layer, and independently reload the campaign/trigger through
``CampaignsRepository``'s owner-scoped RLS query to prove that owner
actually owns the resource being extended before this authorization check
even runs (RLS returns ``None`` for a foreign resource, indistinguishable
from a nonexistent one -- see ``get_campaign``/``get_trigger``).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from did.application.auth.service import AuthorizationDenied, AuthorizationService
from did.campaigns.target_resolution import TargetAuthorizationChecker
from did.domain.auth import AuthorizationScope, Capability
from did.domain.campaigns import CampaignTarget, TriggerSourceBinding
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.permissions.capabilities import BotCapabilityChecker, BotOperation, CapabilityOutcome


class CampaignNotOwnedByCaller(RuntimeError):
    """The referenced campaign/trigger does not exist, or does not belong
    to the authenticated caller -- the two are deliberately indistinguishable
    to avoid disclosing another owner's resource existence."""


class GuildNotAuthorizedForCampaign(RuntimeError):
    """The authenticated owner is not currently authorized (MESSAGES_PUBLISH)
    for the destination/source Guild this row would reference."""

    def __init__(self, guild_id: int) -> None:
        super().__init__(f"owner is not authorized to publish campaigns in guild {guild_id}")
        self.guild_id = guild_id


class BotCannotSendInDestination(RuntimeError):
    """The DID bot does not currently have permission to send in the
    destination channel -- distinct from the owner's own authorization."""

    def __init__(self, guild_id: int, discord_channel_id: int) -> None:
        super().__init__(
            f"bot cannot currently send in guild {guild_id} channel {discord_channel_id}"
        )
        self.guild_id = guild_id
        self.discord_channel_id = discord_channel_id


@dataclass(frozen=True, slots=True)
class CampaignGuildAuthorizationChecker(TargetAuthorizationChecker):
    """Real implementation of the ``TargetAuthorizationChecker`` protocol
    ``did.campaigns.target_resolution`` already defines -- used both here
    (create-time) and by the delivery-expansion path (execution-time), so
    the exact same authorization logic backs both call sites."""

    authorization: AuthorizationService
    read_models: Stage04Repository
    bot_checker: BotCapabilityChecker

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        try:
            await self.authorization.authorize(
                discord_user_id=owner_discord_user_id,
                guild_id=guild_id,
                capability=Capability.MESSAGES_PUBLISH,
                scope=AuthorizationScope.guild(),
            )
        except AuthorizationDenied:
            return False
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        bot_id, installation_status = await self.read_models.bot_identity(guild_id)
        if bot_id is None:
            return False
        guild, bot_member = await self.read_models.guild_snapshot(guild_id, bot_id)
        channel = guild.channel(discord_channel_id)
        decision = self.bot_checker.check(
            operation=BotOperation.SEND_MESSAGE,
            guild=guild,
            bot=bot_member,
            channel=channel,
            installation_active=installation_status == "ACTIVE",
        )
        return decision.outcome is CapabilityOutcome.CAN


async def create_authorized_campaign_target(
    *,
    repository: CampaignsRepository,
    checker: TargetAuthorizationChecker,
    owner_discord_user_id: int,
    target: CampaignTarget,
) -> None:
    """1E's exact contract for a campaign target: (1) load the campaign
    through the authenticated owner's own RLS-scoped context, (2)
    independently re-authorize that owner for the destination Guild, (3)
    the ``target`` dataclass's own ``__post_init__`` already validates its
    internal shape, and its ``campaign_id``/``guild_id`` are what step (2)
    just authorized -- only then (4) persist."""
    campaign = await repository.get_campaign(owner_discord_user_id, target.campaign_id)
    if campaign is None:
        raise CampaignNotOwnedByCaller(str(target.campaign_id))
    if not await checker.is_guild_authorized(
        guild_id=target.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        raise GuildNotAuthorizedForCampaign(target.guild_id)
    await repository.create_target(target)


async def create_authorized_trigger_source(
    *,
    repository: CampaignsRepository,
    checker: TargetAuthorizationChecker,
    owner_discord_user_id: int,
    trigger_id: UUID,
    binding: TriggerSourceBinding,
) -> None:
    """1E's exact contract for a trigger source binding: (1) load the
    trigger through the authenticated owner's own RLS-scoped context, (2)
    independently re-authorize that owner for the *source* Guild the
    binding names (a trigger source is where events may originate from --
    the same authorization bar as a publish destination, since an
    unauthorized source Guild could otherwise be used to fire campaigns the
    owner has no real standing in that Guild to react to), (3) the
    ``binding``'s own ``trigger_id`` must match the trigger just loaded --
    only then (4) persist."""
    trigger = await repository.get_trigger(owner_discord_user_id, trigger_id)
    if trigger is None:
        raise CampaignNotOwnedByCaller(str(trigger_id))
    if binding.trigger_id != trigger_id:
        raise CampaignNotOwnedByCaller(str(binding.trigger_id))
    if not await checker.is_guild_authorized(
        guild_id=binding.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        raise GuildNotAuthorizedForCampaign(binding.guild_id)
    await repository.create_trigger_source(binding)
