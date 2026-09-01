"""WP12 runtime glue: assembles everything
``did.campaigns.activation.fan_out_occurrence`` needs to actually execute a
real, durably-persisted campaign -- target listing across Guilds, glossary
entries, language-profile codes, real Stage 08 Translation Group topology, a
real translation provider bound per-language, and compiled allowed mentions.

Every WP12 module before this one (``activation``/``rendering``
/``target_resolution``) deliberately takes this context as parameters rather
than loading it itself -- this is the one place that actually reads it from
durable storage for the real runtime (schedulers/event consumers), as
opposed to a test hand-constructing it. A production caller (the scheduler
runtime, the event-consumer runtime) uses :func:`load_fan_out_context`; a
test may still construct ``FanOutContext``'s pieces directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from did.campaigns.logical_groups import LogicalGroupExpansion, expand_logical_group
from did.campaigns.rendering import TranslateMaskedText
from did.campaigns.target_resolution import TranslationGroupTopologySnapshot
from did.domain.campaigns import (
    AttachmentPolicy,
    CampaignTarget,
    GlossaryBehavior,
    GlossaryEntry,
    GlossaryMatchMode,
    GlossaryScope,
    LifecycleStatus,
    MessageCampaign,
    PublicationMode,
    TargetKind,
    TranslationPublicationMode,
)
from did.domain.translation_provider import CampaignTranslationProvider
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    Stage08NotFound,
    TranslationGroupRepository,
)
from did.messaging.allowed_mentions import (
    AllowedMentionsCompiler,
    AllowedMentionsPolicy,
    CompiledAllowedMentions,
    MentionPolicyError,
)


class FanOutContextError(RuntimeError):
    """The durable context needed for fan-out could not be safely
    assembled -- the caller must never fan out with partial/guessed
    context (e.g. an allowed_mentions_policy that cannot be honestly
    compiled)."""


@dataclass(frozen=True, slots=True)
class FanOutContext:
    targets: tuple[CampaignTarget, ...]
    topology_by_target: dict[UUID, TranslationGroupTopologySnapshot | None]
    logical_group_expansion_by_target: dict[UUID, LogicalGroupExpansion | None]
    language_profile_codes: dict[UUID, str]
    compiled_mentions: CompiledAllowedMentions
    glossary_entries: tuple[GlossaryEntry, ...]
    translate_masked_text_for_language: Callable[[str], TranslateMaskedText] | None


def _allowed_mentions_policy_from_dict(raw: dict[str, object]) -> AllowedMentionsPolicy:
    """``MessageCampaign.allowed_mentions_policy`` is stored as an opaque
    JSON blob (``dict[str, object]``); this is the one place it is
    interpreted, using the same field names as ``AllowedMentionsPolicy``
    itself. Any missing/malformed key defaults to the safe "no mentions"
    value, never guessed toward a more permissive one."""
    allowed_user_ids = raw.get("allowed_user_ids") or ()
    allowed_role_ids = raw.get("allowed_role_ids") or ()
    if not isinstance(allowed_user_ids, list | tuple):
        allowed_user_ids = ()
    if not isinstance(allowed_role_ids, list | tuple):
        allowed_role_ids = ()
    return AllowedMentionsPolicy(
        allow_everyone=bool(raw.get("allow_everyone", False)),
        allowed_user_ids=tuple(int(value) for value in allowed_user_ids),
        allowed_role_ids=tuple(int(value) for value in allowed_role_ids),
        replied_user=bool(raw.get("replied_user", False)),
    )


def _target_from_row(row: dict[str, Any]) -> CampaignTarget:
    languages_raw = row.get("selected_language_profile_ids") or ()
    return CampaignTarget(
        id=row["id"],
        guild_id=row["guild_id"],
        campaign_id=row["campaign_id"],
        target_kind=TargetKind(row["target_kind"]),
        discord_channel_id=row.get("discord_channel_id"),
        translation_group_id=row.get("translation_group_id"),
        translation_publication_mode=(
            TranslationPublicationMode(row["translation_publication_mode"])
            if row.get("translation_publication_mode")
            else None
        ),
        selected_language_profile_ids=tuple(UUID(str(value)) for value in languages_raw),
        logical_group_id=row.get("logical_group_id"),
    )


def campaign_from_row(row: dict[str, Any]) -> MessageCampaign:
    """Reconstructs the real domain object from a ``message_campaigns`` row
    -- every enum column must be explicitly coerced (a raw DB string is
    never ``is`` the same as an enum member, see
    ``did.campaigns.event_consumer``'s identical fix for
    ``TriggerSourceScopeKind`` -- the same class of bug applies here)."""
    return MessageCampaign(
        id=row["id"],
        owner_discord_user_id=row["owner_discord_user_id"],
        logical_campaign_key=row["logical_campaign_key"],
        name=row["name"],
        source_language_code=row["source_language_code"],
        message_model=dict(row["message_model"]),
        allowed_mentions_policy=dict(row["allowed_mentions_policy"]),
        publication_mode=PublicationMode(row["publication_mode"]),
        attachment_policy=AttachmentPolicy(row["attachment_policy"]),
        lifecycle_status=LifecycleStatus(row["lifecycle_status"]),
        version=row["version"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def load_campaign(
    campaigns_repository: CampaignsRepository, *, owner_discord_user_id: int, campaign_id: UUID
) -> MessageCampaign | None:
    row = await campaigns_repository.get_campaign(owner_discord_user_id, campaign_id)
    return campaign_from_row(row) if row is not None else None


def _glossary_entry_from_row(row: dict[str, Any]) -> GlossaryEntry:
    return GlossaryEntry(
        id=row["id"],
        owner_discord_user_id=row["owner_discord_user_id"],
        scope_kind=GlossaryScope(row["scope_kind"]),
        source_term=row["source_term"],
        behavior=GlossaryBehavior(row["behavior"]),
        campaign_id=row.get("campaign_id"),
        guild_id=row.get("guild_id"),
        target_language_code=row.get("target_language_code"),
        forced_translation=row.get("forced_translation"),
        match_mode=GlossaryMatchMode(row["match_mode"])
        if row.get("match_mode")
        else GlossaryMatchMode.CASE_INSENSITIVE,
    )


async def load_targets_for_campaign(
    campaigns_repository: CampaignsRepository,
    admin_factory: async_sessionmaker[Any],
    *,
    owner_discord_user_id: int,
    campaign_id: UUID,
) -> tuple[CampaignTarget, ...]:
    rows = await campaigns_repository.list_targets_for_campaign(
        admin_factory, owner_discord_user_id, campaign_id
    )
    return tuple(_target_from_row(row) for row in rows)


async def load_translation_group_topology(
    translation_groups: TranslationGroupRepository,
    *,
    guild_id: int,
    translation_group_id: UUID,
) -> TranslationGroupTopologySnapshot | None:
    """Resolves REAL Stage 08 topology for one Translation Group.

    Only unambiguous groups (exactly one ``translation_channel_groups``
    row) are resolvable: ``CampaignTarget`` currently names only a
    ``translation_group_id``, with no field to disambiguate between
    multiple channel sets a single Translation Group can legitimately
    contain in Stage 08's own model -- a genuine, pre-existing gap in
    Stage09's target model this loader deliberately does not paper over by
    guessing which channel set was meant. Returns ``None`` (topology
    unavailable) in that case, which ``did.campaigns.target_resolution``
    already handles as a safe ``TRANSLATION_GROUP_NOT_FOUND``-shaped block,
    never a crash or a silent wrong guess."""
    try:
        group = await translation_groups.workspace_group(
            guild_id=guild_id, group_id=translation_group_id
        )
    except Stage08NotFound:
        return None
    channel_groups = group.get("channel_groups") or []
    if len(channel_groups) != 1:
        return None
    channel_group = channel_groups[0]
    source_language_profile_id = channel_group.get("source_language_profile_id")
    if source_language_profile_id is None:
        return None
    variants = [
        row
        for row in (group.get("channel_variants") or [])
        if str(row["translation_channel_group_id"]) == str(channel_group["id"])
    ]
    source_variant = next(
        (
            variant
            for variant in variants
            if str(variant["language_profile_id"]) == str(source_language_profile_id)
        ),
        None,
    )
    if source_variant is None:
        return None
    non_source = tuple(
        (UUID(str(variant["language_profile_id"])), int(variant["discord_channel_id"]))
        for variant in variants
        if str(variant["language_profile_id"]) != str(source_language_profile_id)
        and str(variant.get("state", "ACTIVE")) == "ACTIVE"
    )
    return TranslationGroupTopologySnapshot(
        source_channel_id=int(source_variant["discord_channel_id"]), variants=non_source
    )


def bind_translation_provider(
    provider: CampaignTranslationProvider, *, source_language: str
) -> Callable[[str], TranslateMaskedText]:
    """The real production binder ``fan_out_occurrence``'s
    ``translate_masked_text_for_language`` expects: called once per
    destination with that destination's own resolved target language,
    returning a ``TranslateMaskedText`` callable bound to translate
    ``source_language -> target_language`` through the real provider."""

    def _for_language(target_language: str) -> TranslateMaskedText:
        async def _translate(masked_text: str) -> str:
            result = await provider.translate(
                masked_text, source_language=source_language, target_language=target_language
            )
            return result.translated_text

        return _translate

    return _for_language


async def load_fan_out_context(
    *,
    campaigns_repository: CampaignsRepository,
    admin_factory: async_sessionmaker[Any],
    language_profiles: LanguageProfileRepository,
    translation_groups: TranslationGroupRepository,
    campaign: MessageCampaign,
    translation_provider: CampaignTranslationProvider | None,
    stage04_repository: Stage04Repository | None = None,
) -> FanOutContext:
    """Assemble a complete :class:`FanOutContext` for ``campaign`` from
    durable storage. ``translation_provider=None`` yields a context that can
    still fan out source-language-only destinations; any destination
    genuinely requiring translation becomes an honest
    :class:`~did.campaigns.activation.RenderFailure`, never a silent
    untranslated send."""
    targets = await load_targets_for_campaign(
        campaigns_repository,
        admin_factory,
        owner_discord_user_id=campaign.owner_discord_user_id,
        campaign_id=campaign.id,
    )
    guild_ids = sorted({target.guild_id for target in targets})

    language_profile_codes: dict[UUID, str] = {}
    for guild_id in guild_ids:
        for profile in await language_profiles.list_profiles(guild_id):
            language_profile_codes[UUID(str(profile["id"]))] = str(profile["code"])

    topology_by_target: dict[UUID, TranslationGroupTopologySnapshot | None] = {}
    logical_group_expansion_by_target: dict[UUID, LogicalGroupExpansion | None] = {}
    for target in targets:
        if target.target_kind is TargetKind.TRANSLATION_GROUP and target.translation_group_id:
            topology_by_target[target.id] = await load_translation_group_topology(
                translation_groups,
                guild_id=target.guild_id,
                translation_group_id=target.translation_group_id,
            )
        elif (
            target.target_kind is TargetKind.LOGICAL_GROUP
            and target.logical_group_id
            and stage04_repository is not None
        ):
            logical_group_expansion_by_target[target.id] = await expand_logical_group(
                stage04_repository,
                guild_id=target.guild_id,
                logical_group_id=target.logical_group_id,
            )
        else:
            topology_by_target[target.id] = None

    glossary_entries: list[GlossaryEntry] = []
    for guild_id in guild_ids:
        rows = await campaigns_repository.list_applicable_glossary_entries(
            owner_discord_user_id=campaign.owner_discord_user_id, guild_id=guild_id
        )
        glossary_entries.extend(_glossary_entry_from_row(row) for row in rows)
    # A GLOBAL_USER/CAMPAIGN entry (owner-scoped, not Guild-scoped) is
    # returned by every Guild's query above -- de-duplicate by id so a
    # multi-Guild campaign does not glossary-protect the same term twice.
    deduped_glossary = tuple({entry.id: entry for entry in glossary_entries}.values())

    try:
        compiled_mentions = AllowedMentionsCompiler().compile(
            _allowed_mentions_policy_from_dict(campaign.allowed_mentions_policy),
            capability_allows_everyone=False,
        )
    except MentionPolicyError as exc:
        raise FanOutContextError(f"allowed_mentions_policy could not be compiled: {exc}") from exc

    translate_masked_text_for_language = (
        bind_translation_provider(
            translation_provider, source_language=campaign.source_language_code
        )
        if translation_provider is not None
        else None
    )

    return FanOutContext(
        targets=targets,
        topology_by_target=topology_by_target,
        logical_group_expansion_by_target=logical_group_expansion_by_target,
        language_profile_codes=language_profile_codes,
        compiled_mentions=compiled_mentions,
        glossary_entries=deduped_glossary,
        translate_masked_text_for_language=translate_masked_text_for_language,
    )
