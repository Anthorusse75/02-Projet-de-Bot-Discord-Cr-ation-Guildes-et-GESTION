"""Create-time and execution-time Guild authorization for Stage 09 (1E,
external-review findings across the third and fourth remediation passes).

The composite FKs added in ``0023_stage_09_relational_integrity`` prove a
Guild-scoped child row (a ``message_campaign_targets`` or
``message_campaign_trigger_sources`` row) really belongs to the campaign/
trigger it references. They do NOT and cannot prove:

* the *owner* of that campaign/trigger is currently authorized for the
  *destination Guild* the child row names -- a database constraint has no
  notion of "this Discord user's role in that Discord server";
* a caller-supplied ``discord_channel_id``/``discord_resource_id`` or
  ``translation_group_id`` actually belongs to the declared Guild at all --
  Discord snowflakes are globally unique but NOT globally scoped to one
  Guild by construction, and Stage 09 has no FK into Stage04's channel
  topology or Stage08's Translation Group tables to enforce this at the
  database layer.

Both are live facts this module proves through the real, already-existing
authoritative sources -- ``did.application.auth.service.AuthorizationService``
(owner authorization) and Stage04's read-model / Stage08's
``TranslationGroupRepository`` (resource-to-Guild membership) -- rather than
trusting anything the caller supplies.

**The exact create-time contract, resolved (external-review finding, fourth
remediation pass: this module's docstring previously claimed bot-send
capability was create-time-blocking while the code never actually checked
it)**:

1. Owner Guild authorization (``MESSAGES_PUBLISH``) is a HARD create-time
   gate -- who may create a target/binding in a Guild at all is a security
   decision, never soft.
2. Resource-to-Guild membership (a channel/category/Translation Group
   really belongs to the declared Guild, and a trigger-source resource has
   the expected type) is a HARD create-time gate -- this is a structural
   identity fact, not an operational one, and a mismatch here is exactly
   the cross-Guild attack class REQ-MSG-002/027 exist to prevent.
3. Bot-send capability (does the DID bot currently have SEND_MESSAGES in
   this specific channel) is explicitly NOT a create-time blocker. Per
   REQ-MSG-003's own wording -- cross-Guild targets are "autorisé et
   revalidé... au moment de la livraison" (authorized and revalidated AT
   DELIVERY TIME) -- the authoritative enforcement point for this
   operational, time-varying fact is execution time
   (``did.campaigns.target_resolution.resolve_target``, which already fails
   closed with ``BlockReason.BOT_CANNOT_SEND``), not creation time. A
   channel's permission overwrites can change at any moment between
   authoring a campaign and it actually sending; blocking campaign
   *authoring* on a transient bot-permission gap would be a worse product
   experience than simply warning about it. Create-time still PERFORMS the
   check and returns its result as a non-blocking preflight signal (see
   ``TargetCreationResult``/``TriggerSourceCreationResult``) so a caller/UI
   can surface the warning immediately rather than only discovering it at
   send time.

Neither authorization nor resource-membership check is ever trusted from a
cached/prior value: this module always performs a fresh call. A
caller-supplied ``owner_discord_user_id`` is never authority on its own
either -- the create-time service functions below only ever use the
*authenticated session's* owner id, resolved once by the API layer, and
independently reload the campaign/trigger through ``CampaignsRepository``'s
owner-scoped RLS query to prove that owner actually owns the resource being
extended before any check below even runs (RLS returns ``None`` for a
foreign resource, indistinguishable from a nonexistent one -- see
``get_campaign``/``get_trigger``).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from did.application.auth.service import AuthorizationDenied, AuthorizationService
from did.campaigns.target_resolution import TargetAuthorizationChecker
from did.domain.auth import AuthorizationScope, Capability
from did.domain.campaigns import (
    CampaignTarget,
    TargetKind,
    TriggerSourceBinding,
    TriggerSourceScopeKind,
)
from did.domain.read_model.models import ChannelType
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_repository import Stage08NotFound, TranslationGroupRepository
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


class ForeignOrUnknownResourceError(RuntimeError):
    """A caller-supplied Discord resource (channel/category) or Stage08
    Translation Group does not belong to the declared Guild -- proven
    against authoritative Stage04/Stage08 state, never inferred from the
    caller-supplied id alone. Deliberately does not distinguish "belongs to
    a different Guild" from "does not exist at all", for the same
    non-disclosure reason as :class:`CampaignNotOwnedByCaller`."""

    def __init__(self, guild_id: int, resource_id: int | UUID) -> None:
        super().__init__(f"resource {resource_id} does not belong to guild {guild_id}")
        self.guild_id = guild_id
        self.resource_id = resource_id


class WrongResourceTypeError(RuntimeError):
    """A Discord resource exists and belongs to the declared Guild, but is
    not of the type the caller declared (e.g. a CATEGORY-scoped trigger
    source binding naming an ordinary text channel's id)."""

    def __init__(self, guild_id: int, resource_id: int, expected: str, actual: str) -> None:
        super().__init__(
            f"resource {resource_id} in guild {guild_id} is a {actual}, expected {expected}"
        )
        self.guild_id = guild_id
        self.resource_id = resource_id
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True, slots=True)
class TargetCreationResult:
    target: CampaignTarget
    #: None when not applicable (TRANSLATION_GROUP targets, or the bot's
    #: identity/snapshot could not be resolved at all -- see
    #: ``CampaignGuildAuthorizationChecker.bot_can_send``). Never a
    #: create-time blocker -- see the module docstring.
    bot_send_preflight_ok: bool | None


@dataclass(frozen=True, slots=True)
class TriggerSourceCreationResult:
    binding: TriggerSourceBinding


@dataclass(frozen=True, slots=True)
class CampaignGuildAuthorizationChecker(TargetAuthorizationChecker):
    """Real implementation of the ``TargetAuthorizationChecker`` protocol
    ``did.campaigns.target_resolution`` already defines -- used both here
    (create-time) and by the delivery-expansion path (execution-time), so
    the exact same authorization logic backs both call sites.

    ``translation_groups`` is optional only so a caller that never creates
    TRANSLATION_GROUP targets/never needs Stage08 wiring can construct this
    without it; :func:`create_authorized_campaign_target` raises
    ``RuntimeError`` if a TRANSLATION_GROUP target is created without it.
    """

    authorization: AuthorizationService
    read_models: Stage04Repository
    bot_checker: BotCapabilityChecker
    translation_groups: TranslationGroupRepository | None = None

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

    async def channel_belongs_to_guild(self, *, guild_id: int, discord_channel_id: int) -> bool:
        """Authoritative structural check (external-review finding, fourth
        remediation pass): proves ``discord_channel_id`` is a real, known
        channel of ``guild_id`` via Stage04's read-model snapshot -- never
        inferred from the caller-supplied pair alone. A snowflake that
        exists but belongs to a different Guild, or does not exist in the
        cached topology at all, both return False."""
        bot_id, _installation_status = await self.read_models.bot_identity(guild_id)
        if bot_id is None:
            return False
        guild, _bot_member = await self.read_models.guild_snapshot(guild_id, bot_id)
        return guild.channel(discord_channel_id) is not None

    async def resource_type(self, *, guild_id: int, discord_resource_id: int) -> ChannelType | None:
        """Returns the resource's real ``ChannelType`` (categories are
        represented as a channel of type ``GUILD_CATEGORY`` in Stage04's
        model) if it belongs to ``guild_id``, else ``None``."""
        bot_id, _installation_status = await self.read_models.bot_identity(guild_id)
        if bot_id is None:
            return None
        guild, _bot_member = await self.read_models.guild_snapshot(guild_id, bot_id)
        channel = guild.channel(discord_resource_id)
        if channel is None:
            return None
        return ChannelType(channel.channel_type)

    async def translation_group_belongs_to_guild(
        self, *, guild_id: int, translation_group_id: UUID
    ) -> bool:
        if self.translation_groups is None:
            raise RuntimeError(
                "CampaignGuildAuthorizationChecker was constructed without a "
                "TranslationGroupRepository -- cannot validate a TRANSLATION_GROUP target"
            )
        try:
            await self.translation_groups.get(guild_id, translation_group_id)
        except Stage08NotFound:
            return False
        return True


async def create_authorized_campaign_target(
    *,
    repository: CampaignsRepository,
    checker: CampaignGuildAuthorizationChecker,
    owner_discord_user_id: int,
    target: CampaignTarget,
) -> TargetCreationResult:
    """1E's exact contract for a campaign target (see the module docstring
    for the full create-time-hard vs. execution-time-authoritative
    rationale):

    1. Load the campaign through the authenticated owner's own RLS-scoped
       context -- proves ownership, never trusts a caller-supplied id.
    2. Independently re-authorize that owner for the destination Guild
       (HARD gate).
    3. Prove the declared resource (channel, or Translation Group) actually
       belongs to that Guild through authoritative Stage04/Stage08 state
       (HARD gate) -- never the caller-supplied id/Guild pair alone.
    4. For a CHANNEL target, additionally check bot-send capability as a
       non-blocking preflight, returned to the caller rather than raised.
    5. Only then persist.
    """
    campaign = await repository.get_campaign(owner_discord_user_id, target.campaign_id)
    if campaign is None:
        raise CampaignNotOwnedByCaller(str(target.campaign_id))
    if not await checker.is_guild_authorized(
        guild_id=target.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        raise GuildNotAuthorizedForCampaign(target.guild_id)

    bot_send_preflight_ok: bool | None = None
    if target.target_kind is TargetKind.CHANNEL:
        assert target.discord_channel_id is not None
        if not await checker.channel_belongs_to_guild(
            guild_id=target.guild_id, discord_channel_id=target.discord_channel_id
        ):
            raise ForeignOrUnknownResourceError(target.guild_id, target.discord_channel_id)
        bot_send_preflight_ok = await checker.bot_can_send(
            guild_id=target.guild_id, discord_channel_id=target.discord_channel_id
        )
    else:
        assert target.translation_group_id is not None
        if not await checker.translation_group_belongs_to_guild(
            guild_id=target.guild_id, translation_group_id=target.translation_group_id
        ):
            raise ForeignOrUnknownResourceError(target.guild_id, target.translation_group_id)

    await repository.create_target(target)
    return TargetCreationResult(target=target, bot_send_preflight_ok=bot_send_preflight_ok)


_EXPECTED_TYPE_FOR_SOURCE_SCOPE = {
    TriggerSourceScopeKind.CHANNEL: "CHANNEL",
    TriggerSourceScopeKind.CATEGORY: "CATEGORY",
}


async def create_authorized_trigger_source(
    *,
    repository: CampaignsRepository,
    checker: CampaignGuildAuthorizationChecker,
    owner_discord_user_id: int,
    trigger_id: UUID,
    binding: TriggerSourceBinding,
) -> TriggerSourceCreationResult:
    """1E's exact contract for a trigger source binding:

    1. Load the trigger through the authenticated owner's own RLS-scoped
       context.
    2. The ``binding``'s own ``trigger_id`` must match the trigger just
       loaded.
    3. Independently re-authorize that owner for the *source* Guild the
       binding names (HARD gate) -- a trigger source is where events may
       originate from, the same authorization bar as a publish destination.
    4. For a CHANNEL/CATEGORY-scoped binding, prove ``discord_resource_id``
       both belongs to the declared Guild AND has the expected resource
       type through authoritative Stage04 state (HARD gate) -- never
       Discord snowflake global uniqueness alone.
    5. Only then persist.
    """
    trigger = await repository.get_trigger(owner_discord_user_id, trigger_id)
    if trigger is None:
        raise CampaignNotOwnedByCaller(str(trigger_id))
    if binding.trigger_id != trigger_id:
        raise CampaignNotOwnedByCaller(str(binding.trigger_id))
    if not await checker.is_guild_authorized(
        guild_id=binding.guild_id, owner_discord_user_id=owner_discord_user_id
    ):
        raise GuildNotAuthorizedForCampaign(binding.guild_id)

    if binding.source_scope_kind is not TriggerSourceScopeKind.GUILD:
        assert binding.discord_resource_id is not None
        actual_type = await checker.resource_type(
            guild_id=binding.guild_id, discord_resource_id=binding.discord_resource_id
        )
        if actual_type is None:
            raise ForeignOrUnknownResourceError(binding.guild_id, binding.discord_resource_id)
        expected = _EXPECTED_TYPE_FOR_SOURCE_SCOPE[binding.source_scope_kind]
        is_category = actual_type is ChannelType.GUILD_CATEGORY
        matches = is_category if expected == "CATEGORY" else not is_category
        if not matches:
            raise WrongResourceTypeError(
                binding.guild_id,
                binding.discord_resource_id,
                expected=expected,
                actual="CATEGORY" if is_category else "CHANNEL",
            )

    await repository.create_trigger_source(binding)
    return TriggerSourceCreationResult(binding=binding)
