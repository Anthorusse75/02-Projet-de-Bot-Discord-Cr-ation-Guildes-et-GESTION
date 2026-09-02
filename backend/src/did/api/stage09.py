"""Stage 09 campaign & message engine HTTP API.

Thin FastAPI router over the already-built, fully-tested ``did.campaigns.*``
business-logic layer and ``did.infrastructure.campaigns_repository
.CampaignsRepository`` -- exactly the Stage 08 convention (see
``did.api.stage08``): no direct SQL, no direct Discord calls, every request
body a Pydantic model with ``extra="forbid"``.

Two identity rules this router enforces at every boundary, matching the
mission's explicit non-negotiables:

* Ownership (``owner_discord_user_id``) is ALWAYS the authenticated
  session's own Discord user id (``CurrentSessionDep``/``CsrfSessionDep``),
  never a client-supplied field -- no request body below even has an
  owner/approver id field a client could set.
* A foreign or nonexistent campaign/trigger id is always reported through
  the SAME generic not-found shape (``did.campaigns.authorization
  .CampaignNotOwnedByCaller``/``ForeignOrUnknownResourceError``, mapped to
  404 by a global handler in ``did.api.main``) -- never a 403/404 split
  that would let a caller distinguish "exists but is not yours" from
  "does not exist at all".

Activation is deliberately narrow (mission's critical constraint): it only
transitions campaign lifecycle state and, for ``IMMEDIATE`` campaigns,
creates/reserves durable work through ``did.campaigns.activation
.fan_out_occurrence`` (which only ever creates ``message_deliveries`` rows)
and ``did.campaigns.dispatch.route_pending_deliveries_to_jobs`` (which only
ever enqueues durable ``discord_io_jobs`` rows). This module never imports
or references a Discord-sending adapter -- see
``backend/tests/unit/test_stage09_api_router_never_sends.py`` for the
regression test proving it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from did.api.dependencies import ApiProblem, CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.campaigns.activation import (
    FanOutLeaseLostError,
    OccurrenceNotClaimable,
    fan_out_occurrence,
)
from did.campaigns.approved_variants import (
    VariantApproval,
    approve_variant,
    compute_source_fingerprint,
    resolve_variant_for_delivery,
)
from did.campaigns.authorization import (
    CampaignGuildAuthorizationChecker,
    CampaignNotOwnedByCaller,
    create_authorized_campaign_target,
    create_authorized_trigger_source,
)
from did.campaigns.causality import ConditionEvaluationError
from did.campaigns.context import campaign_from_row, load_fan_out_context
from did.campaigns.dispatch import (
    enqueue_delete_job,
    enqueue_edit_job,
    route_pending_deliveries_to_jobs,
)
from did.campaigns.event_transport import trigger_from_row
from did.campaigns.message_content_policy import (
    MessageContentCapabilityBlocked,
    PermanentlyUnavailableMessageContentChecker,
    validate_message_content_capability,
)
from did.campaigns.retention import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS, RetentionPolicy
from did.campaigns.scheduling import ScheduleEvaluationError, evaluate_recurring
from did.campaigns.simulation import CampaignSimulationReport, simulate_campaign
from did.domain.campaigns import (
    ApprovedVariant,
    AttachmentPolicy,
    CampaignSchedule,
    CampaignTarget,
    CampaignTemplateVariable,
    CampaignTrigger,
    DstAmbiguousPolicy,
    DstNonexistentPolicy,
    GlossaryBehavior,
    GlossaryEntry,
    GlossaryMatchMode,
    GlossaryScope,
    LifecycleStatus,
    MessageCampaign,
    MessageOccurrence,
    MisfirePolicy,
    OccurrenceSource,
    PublicationMode,
    ScheduleKind,
    TargetKind,
    TranslationPublicationMode,
    TriggerSourceBinding,
    TriggerSourceScopeKind,
)
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
)
from did.messaging.message_model import MessageModel, MessageModelViolation, validate_message_model
from did.messaging.template_variables import TemplateVariableType
from did.permissions.capabilities import BotCapabilityChecker

router = APIRouter(tags=["stage-09-campaigns"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


# ---------------------------------------------------------------------------
# Request bodies -- every one ``extra="forbid"``, none carries an owner/
# approver identity field a client could smuggle a value into.
# ---------------------------------------------------------------------------


class CampaignCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    source_language_code: str = Field(min_length=2, max_length=16)
    message_model: dict[str, Any] = Field(default_factory=dict)
    allowed_mentions_policy: dict[str, Any] = Field(default_factory=dict)
    publication_mode: PublicationMode
    attachment_policy: AttachmentPolicy = AttachmentPolicy.PRESERVE_EXISTING


class CampaignUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    message_model: dict[str, Any] | None = None
    allowed_mentions_policy: dict[str, Any] | None = None
    attachment_policy: AttachmentPolicy | None = None


class TargetCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guild_id: str
    target_kind: TargetKind
    discord_channel_id: str | None = None
    translation_group_id: UUID | None = None
    translation_publication_mode: TranslationPublicationMode | None = None
    selected_language_profile_ids: list[UUID] = Field(default_factory=list, max_length=64)
    logical_group_id: UUID | None = None

    @field_validator("guild_id")
    @classmethod
    def guild_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))

    @field_validator("discord_channel_id")
    @classmethod
    def channel_snowflake(cls, value: str | None) -> str | None:
        return str(parse_snowflake(value)) if value is not None else None


class ScheduleCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_kind: ScheduleKind
    fire_at: datetime | None = None
    rrule: str | None = Field(default=None, max_length=1000)
    timezone: str | None = Field(default=None, max_length=64)
    starts_at: datetime | None = None
    misfire_policy: MisfirePolicy = MisfirePolicy.SKIP_MISSED
    dst_nonexistent_policy: DstNonexistentPolicy = DstNonexistentPolicy.SHIFT_FORWARD
    dst_ambiguous_policy: DstAmbiguousPolicy = DstAmbiguousPolicy.EARLIEST
    catch_up_bound: int = Field(default=1, ge=0, le=50)


class VariantApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    localized_message_model: dict[str, Any]


class TriggerCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=128)
    condition_ast: dict[str, Any]
    max_causation_depth: int = Field(default=8, ge=1, le=32)
    requires_message_content: bool = False


class TriggerSourceCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guild_id: str
    source_scope_kind: TriggerSourceScopeKind
    discord_resource_id: str | None = None

    @field_validator("guild_id")
    @classmethod
    def guild_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))

    @field_validator("discord_resource_id")
    @classmethod
    def resource_snowflake(cls, value: str | None) -> str | None:
        return str(parse_snowflake(value)) if value is not None else None


class TemplateVariableCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    variable_type: TemplateVariableType
    value: str | None = None
    values_by_language: dict[str, str] | None = None


class TemplateVariableUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable_type: TemplateVariableType
    value: str | None = None
    values_by_language: dict[str, str] | None = None


class GlossaryEntryCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_kind: GlossaryScope
    source_term: str = Field(min_length=1, max_length=200)
    behavior: GlossaryBehavior
    campaign_id: UUID | None = None
    guild_id: str | None = None
    target_language_code: str | None = Field(default=None, min_length=2, max_length=16)
    forced_translation: str | None = Field(default=None, max_length=2000)
    match_mode: GlossaryMatchMode = GlossaryMatchMode.CASE_INSENSITIVE

    @field_validator("guild_id")
    @classmethod
    def guild_snowflake(cls, value: str | None) -> str | None:
        return str(parse_snowflake(value)) if value is not None else None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_campaigns(container: ServicesDep) -> tuple[CampaignsRepository, Any]:
    if container.campaigns_repository is None or container.campaigns_admin_factory is None:
        raise ApiProblem(
            status_code=503,
            code="CAMPAIGNS_NOT_CONFIGURED",
            message_key="errors.campaigns.notConfigured",
        )
    return container.campaigns_repository, container.campaigns_admin_factory


def _require_campaign_runtime(
    container: ServicesDep,
) -> tuple[CampaignsRepository, Any, LanguageProfileRepository, TranslationGroupRepository]:
    """Narrower variant of :func:`_require_campaigns` for the two endpoints
    (simulate, activate) that also need Stage 08's language/translation-
    group repositories to assemble a ``did.campaigns.context.FanOutContext``
    -- keeps every downstream ``Optional``-typed ``ServiceContainer`` field
    explicitly narrowed to non-``None`` here, once, rather than at each call
    site."""
    if (
        container.campaigns_repository is None
        or container.campaigns_admin_factory is None
        or container.stage08_language_repository is None
        or container.stage08_group_repository is None
    ):
        raise ApiProblem(
            status_code=503,
            code="CAMPAIGNS_NOT_CONFIGURED",
            message_key="errors.campaigns.notConfigured",
        )
    return (
        container.campaigns_repository,
        container.campaigns_admin_factory,
        container.stage08_language_repository,
        container.stage08_group_repository,
    )


def _checker(container: Any) -> CampaignGuildAuthorizationChecker:
    return CampaignGuildAuthorizationChecker(
        authorization=container.authorization,
        read_models=container.stage04_repository,
        bot_checker=BotCapabilityChecker(),
        translation_groups=container.stage08_group_repository,
    )


async def _load_owned_campaign(
    repo: CampaignsRepository, owner_discord_user_id: int, campaign_id: UUID
) -> dict[str, Any]:
    """Never distinguishes "does not exist" from "belongs to another
    owner" -- both raise the identical :class:`CampaignNotOwnedByCaller`,
    mapped by ``did.api.main``'s global handler to the same generic 404."""
    row = await repo.get_campaign(owner_discord_user_id, campaign_id)
    if row is None:
        raise CampaignNotOwnedByCaller(str(campaign_id))
    return row


def _campaign_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "owner_discord_user_id": str(row["owner_discord_user_id"]),
        "logical_campaign_key": row["logical_campaign_key"],
        "name": row["name"],
        "source_language_code": row["source_language_code"],
        "message_model": row["message_model"],
        "allowed_mentions_policy": row["allowed_mentions_policy"],
        "publication_mode": row["publication_mode"],
        "attachment_policy": row["attachment_policy"],
        "lifecycle_status": row["lifecycle_status"],
        "version": int(row["version"]),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _target_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "guild_id": str(row["guild_id"]),
        "campaign_id": str(row["campaign_id"]),
        "target_kind": row["target_kind"],
        "discord_channel_id": (
            str(row["discord_channel_id"]) if row.get("discord_channel_id") is not None else None
        ),
        "translation_group_id": (
            str(row["translation_group_id"])
            if row.get("translation_group_id") is not None
            else None
        ),
        "translation_publication_mode": row.get("translation_publication_mode"),
        "selected_language_profile_ids": list(row.get("selected_language_profile_ids") or []),
        "logical_group_id": (
            str(row["logical_group_id"]) if row.get("logical_group_id") is not None else None
        ),
    }


def _target_response_from_domain(target: CampaignTarget) -> dict[str, Any]:
    return {
        "id": str(target.id),
        "guild_id": str(target.guild_id),
        "campaign_id": str(target.campaign_id),
        "target_kind": target.target_kind.value,
        "discord_channel_id": (
            str(target.discord_channel_id) if target.discord_channel_id is not None else None
        ),
        "translation_group_id": (
            str(target.translation_group_id) if target.translation_group_id is not None else None
        ),
        "translation_publication_mode": (
            target.translation_publication_mode.value
            if target.translation_publication_mode is not None
            else None
        ),
        "selected_language_profile_ids": [
            str(value) for value in target.selected_language_profile_ids
        ],
        "logical_group_id": (
            str(target.logical_group_id) if target.logical_group_id is not None else None
        ),
    }


def _schedule_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "campaign_id": str(row["campaign_id"]),
        "schedule_kind": row["schedule_kind"],
        "fire_at": row.get("fire_at"),
        "rrule": row.get("rrule"),
        "timezone": row.get("timezone"),
        "starts_at": row.get("starts_at"),
        "misfire_policy": row["misfire_policy"],
        "dst_nonexistent_policy": row["dst_nonexistent_policy"],
        "dst_ambiguous_policy": row["dst_ambiguous_policy"],
        "catch_up_bound": int(row["catch_up_bound"]),
        "next_fire_at": row.get("next_fire_at"),
        "version": int(row["version"]),
    }


def _delivery_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "guild_id": str(row["guild_id"]),
        "campaign_id": str(row["campaign_id"]),
        "occurrence_id": str(row["occurrence_id"]),
        "target_id": str(row["target_id"]),
        "language_profile_id": (
            str(row["language_profile_id"]) if row.get("language_profile_id") is not None else None
        ),
        "delivery_key": row["delivery_key"],
        "discord_channel_id": str(row["discord_channel_id"]),
        "status": row["status"],
        "discord_message_id": (
            str(row["discord_message_id"]) if row.get("discord_message_id") is not None else None
        ),
        "attempt_count": int(row["attempt_count"]),
        "last_error": row.get("last_error"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _approved_variant_from_row(row: dict[str, Any]) -> ApprovedVariant:
    return ApprovedVariant(
        id=row["id"],
        owner_discord_user_id=row["owner_discord_user_id"],
        campaign_id=row["campaign_id"],
        target_language_code=row["target_language_code"],
        source_fingerprint=row["source_fingerprint"],
        localized_message_model=row["localized_message_model"],
        approved_by_discord_user_id=row["approved_by_discord_user_id"],
        approved_at=row.get("approved_at"),
    )


def _variant_response(variant: ApprovedVariant) -> dict[str, Any]:
    return {
        "id": str(variant.id),
        "campaign_id": str(variant.campaign_id),
        "target_language_code": variant.target_language_code,
        "source_fingerprint": variant.source_fingerprint,
        "localized_message_model": variant.localized_message_model,
        "approved_by_discord_user_id": str(variant.approved_by_discord_user_id),
        "approved_at": variant.approved_at,
    }


def _trigger_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "campaign_id": str(row["campaign_id"]),
        "event_type": row["event_type"],
        "condition_ast": row["condition_ast"],
        "max_causation_depth": int(row["max_causation_depth"]),
        "requires_message_content": bool(row["requires_message_content"]),
        "version": int(row["version"]),
    }


def _trigger_source_response_from_domain(binding: TriggerSourceBinding) -> dict[str, Any]:
    return {
        "id": str(binding.id),
        "guild_id": str(binding.guild_id),
        "trigger_id": str(binding.trigger_id),
        "source_scope_kind": binding.source_scope_kind.value,
        "discord_resource_id": (
            str(binding.discord_resource_id) if binding.discord_resource_id is not None else None
        ),
    }


def _trigger_source_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "guild_id": str(row["guild_id"]),
        "trigger_id": str(row["trigger_id"]),
        "source_scope_kind": row["source_scope_kind"],
        "discord_resource_id": (
            str(row["discord_resource_id"]) if row.get("discord_resource_id") is not None else None
        ),
    }


def _template_variable_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "campaign_id": str(row["campaign_id"]),
        "name": row["name"],
        "variable_type": row["variable_type"],
        "value": row.get("value"),
        "values_by_language": row.get("values_by_language"),
    }


def _glossary_entry_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "scope_kind": row["scope_kind"],
        "source_term": row["source_term"],
        "behavior": row["behavior"],
        "campaign_id": str(row["campaign_id"]) if row.get("campaign_id") is not None else None,
        "guild_id": str(row["guild_id"]) if row.get("guild_id") is not None else None,
        "target_language_code": row.get("target_language_code"),
        "forced_translation": row.get("forced_translation"),
        "match_mode": row["match_mode"],
    }


def _simulation_response(report: CampaignSimulationReport) -> dict[str, Any]:
    return {
        "destinations": [
            {
                "guild_id": str(destination.guild_id),
                "discord_channel_id": str(destination.discord_channel_id),
                "language_profile_id": (
                    str(destination.language_profile_id)
                    if destination.language_profile_id is not None
                    else None
                ),
                "ready": destination.ready,
                "blocked_reason": (
                    destination.blocked_reason.value
                    if destination.blocked_reason is not None
                    else None
                ),
                "translation_state": destination.translation_state.value,
                "delivery_executable": destination.delivery_executable,
            }
            for destination in report.destinations
        ],
        "total_destinations": report.total_destinations,
        "ready_destinations": report.ready_destinations,
        "blocked_destinations": report.blocked_destinations,
        "estimated_delivery_count": report.estimated_delivery_count,
        "blockers": report.blockers,
        "message_content_warnings": [
            {
                "trigger_id": warning.trigger_id,
                "available": warning.available,
                "is_blocking": warning.is_blocking,
            }
            for warning in report.message_content_warnings
        ],
        "undeclared_template_variable_names": sorted(report.undeclared_template_variable_names),
        "matched_glossary_terms": list(report.matched_glossary_terms),
    }


async def _domain_campaign(
    repo: CampaignsRepository, owner_id: int, campaign_id: UUID
) -> MessageCampaign:
    row = await _load_owned_campaign(repo, owner_id, campaign_id)
    return campaign_from_row(row)


async def _transition_campaign(
    repo: CampaignsRepository, owner_id: int, campaign_id: UUID, target: LifecycleStatus
) -> MessageCampaign:
    """Loads, transitions (raising ``CampaignLifecycleError`` -- mapped by
    ``did.api.main``'s global handler to 409 -- if disallowed) and
    CAS-persists the campaign's lifecycle status. Returns the transitioned
    domain object (not yet re-read from the DB) for the caller's own
    further use (e.g. deciding whether to fan out)."""
    campaign = await _domain_campaign(repo, owner_id, campaign_id)
    transitioned = campaign.transition_to(target)
    updated = await repo.update_campaign_lifecycle_status(
        owner_id, campaign_id, campaign.version, new_status=transitioned.lifecycle_status.value
    )
    if not updated:
        raise ApiProblem(
            status_code=409,
            code="CAMPAIGN_LIFECYCLE_CONFLICT",
            message_key="errors.campaigns.lifecycleConflict",
        )
    return transitioned


# ---------------------------------------------------------------------------
# 1. Campaign CRUD
# ---------------------------------------------------------------------------


@router.post("/api/v1/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    existing = await repo.get_campaign_by_key(session.discord_user_id, idempotency_key)
    if existing is not None:
        return {"created": False, "campaign": _campaign_response(existing)}
    try:
        validate_message_model(MessageModel.from_dict(body.message_model))
        campaign = MessageCampaign(
            id=uuid4(),
            owner_discord_user_id=session.discord_user_id,
            logical_campaign_key=idempotency_key,
            name=body.name,
            source_language_code=body.source_language_code,
            message_model=body.message_model,
            allowed_mentions_policy=body.allowed_mentions_policy,
            publication_mode=body.publication_mode,
            attachment_policy=body.attachment_policy,
        )
    except (ValueError, MessageModelViolation) as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_INPUT_INVALID",
            message_key="errors.campaigns.inputInvalid",
        ) from exc
    try:
        await repo.create_campaign(campaign)
    except IntegrityError:
        replayed = await repo.get_campaign_by_key(session.discord_user_id, idempotency_key)
        if replayed is None:
            raise
        return {"created": False, "campaign": _campaign_response(replayed)}
    row = await repo.get_campaign(session.discord_user_id, campaign.id)
    assert row is not None
    return {"created": True, "campaign": _campaign_response(row)}


@router.get("/api/v1/campaigns")
async def list_campaigns(session: CurrentSessionDep, container: ServicesDep) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    rows = await repo.list_campaigns(session.discord_user_id)
    return {"campaigns": [_campaign_response(row) for row in rows]}


@router.get("/api/v1/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    row = await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    return _campaign_response(row)


@router.patch("/api/v1/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdateInput,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    if body.message_model is not None:
        try:
            validate_message_model(MessageModel.from_dict(body.message_model))
        except (ValueError, MessageModelViolation) as exc:
            raise ApiProblem(
                status_code=422,
                code="CAMPAIGN_INPUT_INVALID",
                message_key="errors.campaigns.inputInvalid",
            ) from exc
    updated = await repo.update_campaign_draft_fields(
        session.discord_user_id,
        campaign_id,
        body.expected_version,
        name=body.name,
        message_model=body.message_model,
        allowed_mentions_policy=body.allowed_mentions_policy,
        attachment_policy=(body.attachment_policy.value if body.attachment_policy else None),
    )
    if not updated:
        raise ApiProblem(
            status_code=409,
            code="CAMPAIGN_UPDATE_CONFLICT",
            message_key="errors.campaigns.updateConflict",
        )
    row = await repo.get_campaign(session.discord_user_id, campaign_id)
    assert row is not None
    return _campaign_response(row)


# ---------------------------------------------------------------------------
# 2. Targets
# ---------------------------------------------------------------------------


@router.post("/api/v1/campaigns/{campaign_id}/targets", status_code=status.HTTP_201_CREATED)
async def create_target(
    campaign_id: UUID,
    body: TargetCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    try:
        target = CampaignTarget(
            id=uuid4(),
            guild_id=int(body.guild_id),
            campaign_id=campaign_id,
            target_kind=body.target_kind,
            discord_channel_id=(
                int(body.discord_channel_id) if body.discord_channel_id is not None else None
            ),
            translation_group_id=body.translation_group_id,
            translation_publication_mode=body.translation_publication_mode,
            selected_language_profile_ids=tuple(body.selected_language_profile_ids),
            logical_group_id=body.logical_group_id,
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TARGET_INPUT_INVALID",
            message_key="errors.campaigns.targetInputInvalid",
        ) from exc
    # create_authorized_campaign_target itself re-loads the campaign through
    # the authenticated owner's own RLS-scoped context and raises
    # CampaignNotOwnedByCaller/GuildNotAuthorizedForCampaign/
    # ForeignOrUnknownResourceError as appropriate -- see
    # did.campaigns.authorization's module docstring. Every one of those is
    # mapped by did.api.main's global handlers.
    result = await create_authorized_campaign_target(
        repository=repo,
        checker=_checker(container),
        owner_discord_user_id=session.discord_user_id,
        target=target,
    )
    return {
        "target": _target_response_from_domain(result.target),
        "bot_send_preflight_ok": result.bot_send_preflight_ok,
    }


@router.get("/api/v1/campaigns/{campaign_id}/targets")
async def list_targets(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, admin_factory = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    rows = await repo.list_targets_for_campaign(admin_factory, session.discord_user_id, campaign_id)
    return {"targets": [_target_response(row) for row in rows]}


# ---------------------------------------------------------------------------
# 3. Schedule
# ---------------------------------------------------------------------------


@router.post("/api/v1/campaigns/{campaign_id}/schedule", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    campaign_id: UUID,
    body: ScheduleCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    now = datetime.now(UTC)
    try:
        schedule = CampaignSchedule(
            id=uuid4(),
            owner_discord_user_id=session.discord_user_id,
            campaign_id=campaign_id,
            schedule_kind=body.schedule_kind,
            fire_at=body.fire_at,
            rrule=body.rrule,
            timezone=body.timezone,
            starts_at=body.starts_at,
            misfire_policy=body.misfire_policy,
            dst_nonexistent_policy=body.dst_nonexistent_policy,
            dst_ambiguous_policy=body.dst_ambiguous_policy,
            catch_up_bound=body.catch_up_bound,
            # Not IMMEDIATE: an initial next_fire_at of "now" is what makes
            # the row visible at all to CampaignsRepository
            # .claim_due_schedules's own `next_fire_at <= now` filter --
            # did.campaigns.scheduling's own evaluate_one_shot/
            # evaluate_recurring then self-corrects it (to fire_at, or to
            # the RRULE's own next real occurrence) on the very first claim.
            # IMMEDIATE campaigns never go through this claim path at all
            # (see did.campaigns.scheduling.evaluate_schedule) -- fired
            # directly by POST .../activate instead.
            next_fire_at=(None if body.schedule_kind is ScheduleKind.IMMEDIATE else now),
        )
        if schedule.schedule_kind is ScheduleKind.RECURRING:
            evaluate_recurring(schedule, now=now)  # eager RRULE validation
    except (ValueError, ScheduleEvaluationError) as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_SCHEDULE_INPUT_INVALID",
            message_key="errors.campaigns.scheduleInputInvalid",
        ) from exc
    await repo.create_schedule(schedule)
    row = await repo.get_schedule(session.discord_user_id, schedule.id)
    assert row is not None
    return _schedule_response(row)


# ---------------------------------------------------------------------------
# 4. Simulation (read-only, no mutation, no CSRF/idempotency requirement --
# mirrors did.api.stage08's own compile_routes/capacity_preflight pattern
# for a pure preview endpoint).
# ---------------------------------------------------------------------------


@router.post("/api/v1/campaigns/{campaign_id}/simulate")
async def simulate(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, admin_factory, language_profiles, translation_groups = _require_campaign_runtime(
        container
    )
    campaign = await _domain_campaign(repo, session.discord_user_id, campaign_id)
    context = await load_fan_out_context(
        campaigns_repository=repo,
        admin_factory=admin_factory,
        language_profiles=language_profiles,
        translation_groups=translation_groups,
        campaign=campaign,
        translation_provider=None,
        stage04_repository=container.stage04_repository,
        provider_bindings=container.stage08_provider_repository,
    )
    approved_raw = await repo.list_approved_variants(session.discord_user_id, campaign_id)
    approved = {code: _approved_variant_from_row(row) for code, row in approved_raw.items()}
    trigger_rows = await repo.list_triggers_for_campaign(session.discord_user_id, campaign_id)
    triggers = [trigger_from_row(row) for row in trigger_rows]
    report = await simulate_campaign(
        campaign=campaign,
        targets=context.targets,
        authorization=_checker(container),
        topology_by_target=context.topology_by_target,
        approved_variants=approved,
        language_profile_codes=context.language_profile_codes,
        # No live translation provider is wired into this synchronous
        # preview call (see the module docstring / final report for why) --
        # this flag stays truthfully in sync with that, never claims a
        # provider is available when none was passed above.
        translation_provider_available=False,
        triggers=triggers,
        # REQ-MSG-020/022, Option B: MESSAGE_CONTENT is unavailable for
        # every Guild right now (see PermanentlyUnavailableMessageContent
        # Checker's docstring) -- guild_id is never consulted by this
        # checker, so a single placeholder value correctly represents every
        # destination's answer without iterating them.
        message_content_checker=PermanentlyUnavailableMessageContentChecker(),
        message_content_guild_id=0,
        logical_group_expansion_by_target=context.logical_group_expansion_by_target,
        template_variable_definitions=context.template_variable_definitions,
        glossary_entries=context.glossary_entries,
    )
    return _simulation_response(report)


# ---------------------------------------------------------------------------
# 5. Activation / lifecycle
# ---------------------------------------------------------------------------


@router.post("/api/v1/campaigns/{campaign_id}/activate")
async def activate_campaign(
    campaign_id: UUID,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, admin_factory, language_profiles, translation_groups = _require_campaign_runtime(
        container
    )
    campaign = await _domain_campaign(repo, session.discord_user_id, campaign_id)
    if campaign.publication_mode is PublicationMode.ONE_SHOT_DEFERRED or (
        campaign.publication_mode is PublicationMode.RECURRING
    ):
        target_status = LifecycleStatus.SCHEDULED_ARMED
    else:
        # IMMEDIATE fires directly at activation (did.campaigns.scheduling
        # never evaluates it); EVENT_TRIGGERED starts listening immediately
        # -- both go straight to ACTIVE_RUNNING. Durable trigger-source
        # bindings/schedules were already created by the earlier
        # POST .../targets, .../schedule, .../triggers calls -- activation
        # itself only flips the lifecycle gate
        # did.campaigns.scheduling/event_consumer already require before
        # any due schedule/event may fire.
        target_status = LifecycleStatus.ACTIVE_RUNNING
    transitioned = await _transition_campaign(
        repo, session.discord_user_id, campaign_id, target_status
    )

    durable_work: dict[str, Any] = {
        "occurrence_created": False,
        "deliveries_created": 0,
        "deliveries_routed": 0,
        "is_fully_healthy": True,
    }
    if campaign.publication_mode is PublicationMode.IMMEDIATE:
        context = await load_fan_out_context(
            campaigns_repository=repo,
            admin_factory=admin_factory,
            language_profiles=language_profiles,
            translation_groups=translation_groups,
            campaign=transitioned,
            translation_provider=None,
            stage04_repository=container.stage04_repository,
            provider_bindings=container.stage08_provider_repository,
        )
        occurrence = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=session.discord_user_id,
            campaign_id=campaign_id,
            occurrence_key=f"immediate:{campaign_id}",
            occurrence_source=OccurrenceSource.SCHEDULE,
            scheduled_for=datetime.now(UTC),
            # REQ-MSG-030: an IMMEDIATE activation is its own causal root,
            # exactly like a SCHEDULE-fired occurrence.
            source_causation_depth=0,
            source_ancestry=frozenset({str(campaign_id)}),
        )
        try:
            # fan_out_occurrence ONLY ever creates message_deliveries rows
            # (PENDING) -- it never calls Discord. See the module docstring.
            outcome = await fan_out_occurrence(
                repository=repo,
                checker=_checker(container),
                campaign=transitioned,
                targets=context.targets,
                occurrence=occurrence,
                lease_owner=f"api-activate-{campaign_id}",
                topology_by_target=context.topology_by_target,
                logical_group_expansion_by_target=context.logical_group_expansion_by_target,
                language_profile_codes=context.language_profile_codes,
                compiled_mentions=context.compiled_mentions,
                # REQ-MSG-018 (mission section 10): the author's own
                # durably persisted declarations.
                template_variable_definitions=context.template_variable_definitions,
                glossary_entries=context.glossary_entries,
                translate_masked_text_for_language=context.translate_masked_text_for_language,
            )
        except (OccurrenceNotClaimable, FanOutLeaseLostError) as exc:
            raise ApiProblem(
                status_code=409,
                code="CAMPAIGN_ACTIVATION_CONFLICT",
                message_key="errors.campaigns.activationConflict",
            ) from exc
        durable_work["occurrence_created"] = True
        durable_work["deliveries_created"] = outcome.deliveries_created
        durable_work["is_fully_healthy"] = outcome.is_fully_healthy
        # route_pending_deliveries_to_jobs ONLY ever enqueues durable
        # discord_io_jobs rows -- it never calls Discord either. Actually
        # sending is the durable worker's job, entirely outside this
        # request.
        routed = 0
        for guild_id in {target.guild_id for target in context.targets}:
            routed += await route_pending_deliveries_to_jobs(
                repo, container.runtime_repository, guild_id=guild_id
            )
        durable_work["deliveries_routed"] = routed

    row = await repo.get_campaign(session.discord_user_id, campaign_id)
    assert row is not None
    return {"campaign": _campaign_response(row), "durable_work": durable_work}


@router.post("/api/v1/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: UUID,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    await _transition_campaign(repo, session.discord_user_id, campaign_id, LifecycleStatus.PAUSED)
    row = await repo.get_campaign(session.discord_user_id, campaign_id)
    assert row is not None
    return _campaign_response(row)


@router.post("/api/v1/campaigns/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: UUID,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    campaign = await _domain_campaign(repo, session.discord_user_id, campaign_id)
    target_status = (
        LifecycleStatus.SCHEDULED_ARMED
        if campaign.lifecycle_status is LifecycleStatus.PAUSED
        and campaign.publication_mode
        in (PublicationMode.ONE_SHOT_DEFERRED, PublicationMode.RECURRING)
        else LifecycleStatus.ACTIVE_RUNNING
    )
    await _transition_campaign(repo, session.discord_user_id, campaign_id, target_status)
    row = await repo.get_campaign(session.discord_user_id, campaign_id)
    assert row is not None
    return _campaign_response(row)


@router.post("/api/v1/campaigns/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: UUID,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    await _transition_campaign(
        repo, session.discord_user_id, campaign_id, LifecycleStatus.CANCELLED
    )
    row = await repo.get_campaign(session.discord_user_id, campaign_id)
    assert row is not None
    return _campaign_response(row)


# ---------------------------------------------------------------------------
# 6. Delivery history
# ---------------------------------------------------------------------------


@router.get("/api/v1/campaigns/{campaign_id}/deliveries")
async def list_deliveries(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, admin_factory = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    rows = await repo.list_deliveries_for_campaign(
        admin_factory, session.discord_user_id, campaign_id
    )
    return {"deliveries": [_delivery_response(row) for row in rows]}


class InterventionResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["SENT", "FAILED"]
    #: Required only for SENT -- the owner's own report of the message they
    #: observed in their Guild after manually checking, never invented or
    #: looked up by this endpoint. Rejected (extra="forbid" has no effect
    #: on validating its presence, so this is checked explicitly below) for
    #: FAILED, where no message exists to report.
    discord_message_id: str | None = None


@router.post("/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/intervention/resolve")
async def resolve_intervention(
    campaign_id: UUID,
    delivery_id: UUID,
    body: InterventionResolutionInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """REQ-MSG-029 product surface: never a universal "Retry" button -- an
    INTERVENTION_REQUIRED delivery only ever resolves to the caller's own
    attested true outcome (they manually checked their Guild). This
    endpoint never calls Discord and never resends anything; it only
    records a human judgment call. A delivery confirmed FAILED here can
    then be requeued through :func:`requeue_intervention_delivery` for a
    genuinely fresh, unambiguous send attempt."""
    del idempotency_key
    repo, admin_factory = _require_campaigns(container)
    if body.resolution == "SENT" and body.discord_message_id is None:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_INTERVENTION_MESSAGE_ID_REQUIRED",
            message_key="errors.campaigns.interventionMessageIdRequired",
        )
    if body.resolution == "FAILED" and body.discord_message_id is not None:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_INTERVENTION_MESSAGE_ID_NOT_ALLOWED",
            message_key="errors.campaigns.interventionMessageIdNotAllowed",
        )
    message_id = (
        parse_snowflake(body.discord_message_id) if body.discord_message_id is not None else None
    )
    now = datetime.now(UTC)
    claimed = await repo.claim_intervention_delivery_for_owner(
        admin_factory,
        session.discord_user_id,
        campaign_id,
        delivery_id,
        lease_owner=f"api-{session.discord_user_id}",
        now=now,
    )
    if claimed is None:
        raise ApiProblem(
            status_code=404,
            code="CAMPAIGN_DELIVERY_INTERVENTION_NOT_CLAIMABLE",
            message_key="errors.campaigns.interventionNotClaimable",
        )
    resolved = await repo.resolve_intervention_delivery(
        claimed["id"],
        claimed["guild_id"],
        claimed["lease_token"],
        status=body.resolution,
        discord_message_id=message_id,
    )
    if not resolved:
        raise ApiProblem(
            status_code=409,
            code="CAMPAIGN_DELIVERY_INTERVENTION_LOST_LEASE",
            message_key="errors.campaigns.interventionLostLease",
        )
    row = await repo.list_deliveries_for_campaign(
        admin_factory, session.discord_user_id, campaign_id
    )
    resolved_row = next(item for item in row if item["id"] == delivery_id)
    return {"delivery": _delivery_response(resolved_row)}


@router.post("/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/requeue")
async def requeue_intervention_delivery(
    campaign_id: UUID,
    delivery_id: UUID,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Only valid for a FAILED delivery (confirmed nothing was ever sent --
    see :func:`resolve_intervention` and REQ-MSG-029) -- creates durable
    work only (the delivery becomes PENDING again with a fresh nonce; the
    existing durable dispatch/worker discovers and sends it through the
    ordinary path). Never calls Discord directly from this handler."""
    del idempotency_key
    repo, admin_factory = _require_campaigns(container)
    requeued = await repo.requeue_failed_delivery_for_owner(
        admin_factory, session.discord_user_id, campaign_id, delivery_id
    )
    if requeued is None:
        raise ApiProblem(
            status_code=404,
            code="CAMPAIGN_DELIVERY_NOT_REQUEUABLE",
            message_key="errors.campaigns.deliveryNotRequeuable",
        )
    row = await repo.list_deliveries_for_campaign(
        admin_factory, session.discord_user_id, campaign_id
    )
    requeued_row = next(item for item in row if item["id"] == delivery_id)
    return {"delivery": _delivery_response(requeued_row)}


class DeliveryEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_model: dict[str, Any]


@router.post("/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/edit")
async def edit_owned_delivery(
    campaign_id: UUID,
    delivery_id: UUID,
    body: DeliveryEditInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """REQ-MSG owned edit (mission section 7): only ever acts on a delivery
    the caller's own campaign produced -- never a client-supplied
    channel/message id (see
    ``CampaignsRepository.prepare_owned_edit_for_owner``'s docstring). Only
    a SENT delivery with a real ``discord_message_id`` is eligible. Creates
    durable work only -- ``did.campaigns.dispatch.enqueue_edit_job`` -- the
    real Discord edit happens exclusively in the durable worker
    (``did.campaigns.delivery_worker.execute_owned_edit``), never from this
    handler."""
    del idempotency_key
    repo, admin_factory = _require_campaigns(container)
    try:
        validate_message_model(MessageModel.from_dict(body.message_model))
    except (ValueError, MessageModelViolation) as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_DELIVERY_EDIT_INPUT_INVALID",
            message_key="errors.campaigns.deliveryEditInputInvalid",
        ) from exc
    prepared = await repo.prepare_owned_edit_for_owner(
        admin_factory,
        session.discord_user_id,
        campaign_id,
        delivery_id,
        message_model=body.message_model,
    )
    if prepared is None:
        raise ApiProblem(
            status_code=404,
            code="CAMPAIGN_DELIVERY_NOT_EDITABLE",
            message_key="errors.campaigns.deliveryNotEditable",
        )
    await enqueue_edit_job(
        container.runtime_repository, guild_id=prepared["guild_id"], delivery_id=delivery_id
    )
    row = await repo.list_deliveries_for_campaign(
        admin_factory, session.discord_user_id, campaign_id
    )
    edited_row = next(item for item in row if item["id"] == delivery_id)
    return {"delivery": _delivery_response(edited_row)}


@router.post("/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/delete")
async def delete_owned_delivery(
    campaign_id: UUID,
    delivery_id: UUID,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """REQ-MSG owned delete (mission section 8): same ownership/ledger-only
    sourcing as :func:`edit_owned_delivery`. The delivery's status stays
    SENT until the durable worker
    (``did.campaigns.delivery_worker.execute_owned_delete``) confirms the
    real (or already-happened) Discord deletion and transitions it to
    DELETED -- this handler creates durable work only, never calls Discord."""
    del idempotency_key
    repo, admin_factory = _require_campaigns(container)
    verified = await repo.verify_owned_sent_delivery_for_owner(
        admin_factory, session.discord_user_id, campaign_id, delivery_id
    )
    if verified is None:
        raise ApiProblem(
            status_code=404,
            code="CAMPAIGN_DELIVERY_NOT_DELETABLE",
            message_key="errors.campaigns.deliveryNotDeletable",
        )
    await enqueue_delete_job(
        container.runtime_repository, guild_id=verified["guild_id"], delivery_id=delivery_id
    )
    row = await repo.list_deliveries_for_campaign(
        admin_factory, session.discord_user_id, campaign_id
    )
    current_row = next(item for item in row if item["id"] == delivery_id)
    return {"delivery": _delivery_response(current_row)}


# ---------------------------------------------------------------------------
# 7. Approved variants
# ---------------------------------------------------------------------------


@router.get("/api/v1/campaigns/{campaign_id}/variants/{language_code}")
async def preview_variant(
    campaign_id: UUID, language_code: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    campaign = await _domain_campaign(repo, session.discord_user_id, campaign_id)
    approved_raw = await repo.list_approved_variants(session.discord_user_id, campaign_id)
    approved = {code: _approved_variant_from_row(row) for code, row in approved_raw.items()}
    resolution = resolve_variant_for_delivery(campaign, language_code, approved)
    return {
        "campaign_id": str(campaign_id),
        "target_language_code": language_code,
        "outcome": resolution.outcome.value,
        "current_source_fingerprint": compute_source_fingerprint(campaign),
        "approved_variant": (
            _variant_response(resolution.variant) if resolution.variant is not None else None
        ),
    }


@router.post(
    "/api/v1/campaigns/{campaign_id}/variants/{language_code}/approve",
    status_code=status.HTTP_201_CREATED,
)
async def approve_variant_endpoint(
    campaign_id: UUID,
    language_code: str,
    body: VariantApprovalInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    campaign = await _domain_campaign(repo, session.discord_user_id, campaign_id)
    try:
        variant = await approve_variant(
            repo,
            owner_discord_user_id=session.discord_user_id,
            # ALWAYS the authenticated caller -- VariantApprovalInput has no
            # field a client could use to smuggle a different reviewer id
            # (extra="forbid" rejects any attempt with a 422 before this
            # handler even runs).
            approving_discord_user_id=session.discord_user_id,
            approval=VariantApproval(
                campaign_id=campaign_id,
                target_language_code=language_code,
                localized_message_model=body.localized_message_model,
                source_fingerprint=compute_source_fingerprint(campaign),
            ),
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_VARIANT_INPUT_INVALID",
            message_key="errors.campaigns.variantInputInvalid",
        ) from exc
    return _variant_response(variant)


# ---------------------------------------------------------------------------
# 8. Triggers
# ---------------------------------------------------------------------------


@router.post("/api/v1/campaigns/{campaign_id}/triggers", status_code=status.HTTP_201_CREATED)
async def create_trigger(
    campaign_id: UUID,
    body: TriggerCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    try:
        trigger = CampaignTrigger(
            id=uuid4(),
            owner_discord_user_id=session.discord_user_id,
            campaign_id=campaign_id,
            event_type=body.event_type,
            condition_ast=body.condition_ast,
            max_causation_depth=body.max_causation_depth,
            requires_message_content=body.requires_message_content,
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TRIGGER_INPUT_INVALID",
            message_key="errors.campaigns.triggerInputInvalid",
        ) from exc
    try:
        # REQ-MSG-020, Option B (see did.campaigns.message_content_policy's
        # module docstring): a trigger may still declare
        # requires_message_content=True (an honest statement of intent for
        # a future capability), but Stage09 has no content-capture
        # capability at all right now, so creation is always blocked --
        # guild_id=0 is never consulted by this checker, see its docstring.
        await validate_message_content_capability(
            trigger, guild_id=0, checker=PermanentlyUnavailableMessageContentChecker()
        )
    except MessageContentCapabilityBlocked as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TRIGGER_MESSAGE_CONTENT_UNAVAILABLE",
            message_key="errors.campaigns.triggerMessageContentUnavailable",
        ) from exc
    try:
        await repo.create_trigger(trigger)
    except ConditionEvaluationError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TRIGGER_CONDITION_INVALID",
            message_key="errors.campaigns.triggerConditionInvalid",
        ) from exc
    row = await repo.get_trigger(session.discord_user_id, trigger.id)
    assert row is not None
    return _trigger_response(row)


@router.get("/api/v1/campaigns/{campaign_id}/triggers")
async def list_triggers(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    rows = await repo.list_triggers_for_campaign(session.discord_user_id, campaign_id)
    return {"triggers": [_trigger_response(row) for row in rows]}


@router.post(
    "/api/v1/campaigns/{campaign_id}/triggers/{trigger_id}/sources",
    status_code=status.HTTP_201_CREATED,
)
async def create_trigger_source(
    campaign_id: UUID,
    trigger_id: UUID,
    body: TriggerSourceCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    del idempotency_key
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    trigger_row = await repo.get_trigger(session.discord_user_id, trigger_id)
    if trigger_row is None or trigger_row["campaign_id"] != campaign_id:
        # Same non-disclosure shape as every other cross-owner/cross-path
        # mismatch in this router -- a trigger that is not this caller's
        # own, or that belongs to a different one of their own campaigns
        # than the URL names, looks identical to a nonexistent trigger.
        raise CampaignNotOwnedByCaller(str(trigger_id))
    try:
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=int(body.guild_id),
            trigger_id=trigger_id,
            source_scope_kind=body.source_scope_kind,
            discord_resource_id=(
                int(body.discord_resource_id) if body.discord_resource_id is not None else None
            ),
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TRIGGER_SOURCE_INPUT_INVALID",
            message_key="errors.campaigns.triggerSourceInputInvalid",
        ) from exc
    result = await create_authorized_trigger_source(
        repository=repo,
        checker=_checker(container),
        owner_discord_user_id=session.discord_user_id,
        trigger_id=trigger_id,
        binding=binding,
    )
    return _trigger_source_response_from_domain(result.binding)


@router.get("/api/v1/campaigns/{campaign_id}/triggers/{trigger_id}/sources")
async def list_trigger_sources(
    campaign_id: UUID,
    trigger_id: UUID,
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Trigger source bindings are Guild-scoped (RLS), not owner-scoped --
    unlike every other list endpoint in this router there is no single
    context that can see every Guild's bindings for a trigger at once, so
    the caller names one explicit Guild at a time (mirroring how a
    destination Guild is picked for a CHANNEL/LOGICAL_GROUP/
    TRANSLATION_GROUP target in the UI)."""
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    trigger_row = await repo.get_trigger(session.discord_user_id, trigger_id)
    if trigger_row is None or trigger_row["campaign_id"] != campaign_id:
        raise CampaignNotOwnedByCaller(str(trigger_id))
    rows = await repo.load_trigger_sources(parse_snowflake(guild_id), trigger_id)
    return {"trigger_sources": [_trigger_source_response(dict(row)) for row in rows]}


# ---------------------------------------------------------------------------
# 9. Template variables
# ---------------------------------------------------------------------------


@router.get("/api/v1/campaigns/{campaign_id}/template-variables")
async def list_template_variables(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    rows = await repo.list_template_variables_for_campaign(session.discord_user_id, campaign_id)
    return {"template_variables": [_template_variable_response(row) for row in rows]}


@router.post(
    "/api/v1/campaigns/{campaign_id}/template-variables", status_code=status.HTTP_201_CREATED
)
async def create_template_variable(
    campaign_id: UUID,
    body: TemplateVariableCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """REQ-MSG-018 (mission section 10): the shape rule (LOCALIZED_VALUE
    carries values_by_language only, every other type carries a single
    value only) is enforced by did.messaging.template_variables
    .TemplateVariableDefinition itself -- never duplicated here."""
    del idempotency_key
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    try:
        variable = CampaignTemplateVariable(
            id=uuid4(),
            owner_discord_user_id=session.discord_user_id,
            campaign_id=campaign_id,
            name=body.name,
            variable_type=body.variable_type,
            value=body.value,
            values_by_language=body.values_by_language,
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TEMPLATE_VARIABLE_INPUT_INVALID",
            message_key="errors.campaigns.templateVariableInputInvalid",
        ) from exc
    try:
        await repo.create_template_variable(variable)
    except IntegrityError as exc:
        raise ApiProblem(
            status_code=409,
            code="CAMPAIGN_TEMPLATE_VARIABLE_NAME_CONFLICT",
            message_key="errors.campaigns.templateVariableNameConflict",
        ) from exc
    rows = await repo.list_template_variables_for_campaign(session.discord_user_id, campaign_id)
    created_row = next(row for row in rows if row["id"] == variable.id)
    return _template_variable_response(created_row)


@router.patch("/api/v1/campaigns/{campaign_id}/template-variables/{variable_id}")
async def update_template_variable(
    campaign_id: UUID,
    variable_id: UUID,
    body: TemplateVariableUpdateInput,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    rows = await repo.list_template_variables_for_campaign(session.discord_user_id, campaign_id)
    existing = next((row for row in rows if row["id"] == variable_id), None)
    if existing is None:
        raise CampaignNotOwnedByCaller(str(variable_id))
    try:
        # Validated the same way as creation, via the same domain type --
        # never a second, looser validation path for updates. The name is
        # never editable through this endpoint (see the repository
        # method's own docstring for why).
        CampaignTemplateVariable(
            id=variable_id,
            owner_discord_user_id=session.discord_user_id,
            campaign_id=campaign_id,
            name=existing["name"],
            variable_type=body.variable_type,
            value=body.value,
            values_by_language=body.values_by_language,
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_TEMPLATE_VARIABLE_INPUT_INVALID",
            message_key="errors.campaigns.templateVariableInputInvalid",
        ) from exc
    updated = await repo.update_template_variable(
        session.discord_user_id,
        campaign_id,
        variable_id,
        variable_type=body.variable_type.value,
        value=body.value,
        values_by_language=body.values_by_language,
    )
    if not updated:
        raise CampaignNotOwnedByCaller(str(variable_id))
    rows = await repo.list_template_variables_for_campaign(session.discord_user_id, campaign_id)
    updated_row = next(row for row in rows if row["id"] == variable_id)
    return _template_variable_response(updated_row)


@router.delete(
    "/api/v1/campaigns/{campaign_id}/template-variables/{variable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template_variable(
    campaign_id: UUID,
    variable_id: UUID,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> None:
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    deleted = await repo.delete_template_variable(session.discord_user_id, campaign_id, variable_id)
    if not deleted:
        raise CampaignNotOwnedByCaller(str(variable_id))


# ---------------------------------------------------------------------------
# 10. Glossary
# ---------------------------------------------------------------------------


@router.post("/api/v1/glossary", status_code=status.HTTP_201_CREATED)
async def create_glossary_entry_endpoint(
    body: GlossaryEntryCreateInput,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """REQ-MSG-014 (mission section 11): authorized CRUD across all three
    scopes -- CAMPAIGN requires owning the named campaign, GUILD requires
    real Guild authorization (never merely "the caller is logged in"),
    GLOBAL_USER requires nothing beyond authentication (it is scoped to the
    caller's own owner id by construction). The shape/behavior validation
    (CAMPAIGN needs campaign_id xor guild_id, FORCED_TRANSLATION needs
    forced_translation text, ...) is delegated entirely to
    did.domain.campaigns.GlossaryEntry.__post_init__, never duplicated
    here."""
    del idempotency_key
    repo, _ = _require_campaigns(container)
    if body.scope_kind is GlossaryScope.CAMPAIGN:
        if body.campaign_id is None:
            raise ApiProblem(
                status_code=422,
                code="CAMPAIGN_GLOSSARY_INPUT_INVALID",
                message_key="errors.campaigns.glossaryInputInvalid",
            )
        await _load_owned_campaign(repo, session.discord_user_id, body.campaign_id)
    elif body.scope_kind is GlossaryScope.GUILD:
        if body.guild_id is None:
            raise ApiProblem(
                status_code=422,
                code="CAMPAIGN_GLOSSARY_INPUT_INVALID",
                message_key="errors.campaigns.glossaryInputInvalid",
            )
        if not await _checker(container).is_guild_authorized(
            guild_id=int(body.guild_id), owner_discord_user_id=session.discord_user_id
        ):
            raise ApiProblem(
                status_code=403,
                code="CAMPAIGN_GUILD_NOT_AUTHORIZED",
                message_key="errors.campaigns.guildNotAuthorized",
            )
    try:
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=session.discord_user_id,
            scope_kind=body.scope_kind,
            source_term=body.source_term,
            behavior=body.behavior,
            campaign_id=body.campaign_id if body.scope_kind is GlossaryScope.CAMPAIGN else None,
            guild_id=(
                int(body.guild_id)
                if body.scope_kind is GlossaryScope.GUILD and body.guild_id is not None
                else None
            ),
            target_language_code=body.target_language_code,
            forced_translation=body.forced_translation,
            match_mode=body.match_mode,
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="CAMPAIGN_GLOSSARY_INPUT_INVALID",
            message_key="errors.campaigns.glossaryInputInvalid",
        ) from exc
    try:
        await repo.create_glossary_entry(entry)
    except IntegrityError as exc:
        raise ApiProblem(
            status_code=409,
            code="CAMPAIGN_GLOSSARY_TERM_CONFLICT",
            message_key="errors.campaigns.glossaryTermConflict",
        ) from exc
    if entry.scope_kind is GlossaryScope.CAMPAIGN:
        assert entry.campaign_id is not None
        rows = await repo.list_campaign_glossary_entries(session.discord_user_id, entry.campaign_id)
    elif entry.scope_kind is GlossaryScope.GUILD:
        assert entry.guild_id is not None
        rows = await repo.list_guild_glossary_entries(entry.guild_id, session.discord_user_id)
    else:
        rows = await repo.list_global_user_glossary_entries(session.discord_user_id)
    created_row = next(row for row in rows if row["id"] == entry.id)
    return _glossary_entry_response(created_row)


@router.get("/api/v1/campaigns/{campaign_id}/glossary")
async def list_campaign_glossary(
    campaign_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    await _load_owned_campaign(repo, session.discord_user_id, campaign_id)
    rows = await repo.list_campaign_glossary_entries(session.discord_user_id, campaign_id)
    return {"glossary_entries": [_glossary_entry_response(row) for row in rows]}


@router.get("/api/v1/guilds/{guild_id}/glossary")
async def list_guild_glossary(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed_guild_id = parse_snowflake(guild_id)
    if not await _checker(container).is_guild_authorized(
        guild_id=parsed_guild_id, owner_discord_user_id=session.discord_user_id
    ):
        raise ApiProblem(
            status_code=403,
            code="CAMPAIGN_GUILD_NOT_AUTHORIZED",
            message_key="errors.campaigns.guildNotAuthorized",
        )
    repo, _ = _require_campaigns(container)
    rows = await repo.list_guild_glossary_entries(parsed_guild_id, session.discord_user_id)
    return {"glossary_entries": [_glossary_entry_response(row) for row in rows]}


@router.get("/api/v1/glossary")
async def list_global_user_glossary(
    session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    repo, _ = _require_campaigns(container)
    rows = await repo.list_global_user_glossary_entries(session.discord_user_id)
    return {"glossary_entries": [_glossary_entry_response(row) for row in rows]}


@router.delete("/api/v1/glossary/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_entry_endpoint(
    entry_id: UUID, session: CsrfSessionDep, container: ServicesDep
) -> None:
    """A CAMPAIGN/GLOBAL_USER entry may only be deleted by its own owner. A
    GUILD entry may be deleted by any of the Guild's authorized owners
    (matching CampaignsRepository.list_guild_glossary_entries's own
    rationale for that scope) -- verified by a real Guild-authorization
    check here, never merely inferred from the entry's own stored
    owner_discord_user_id."""
    repo, admin_factory = _require_campaigns(container)
    existing = await repo.get_glossary_entry_for_management(admin_factory, entry_id)
    if existing is None:
        raise CampaignNotOwnedByCaller(str(entry_id))
    guild_id = existing.get("guild_id")
    if guild_id is not None:
        if not await _checker(container).is_guild_authorized(
            guild_id=int(guild_id), owner_discord_user_id=session.discord_user_id
        ):
            raise CampaignNotOwnedByCaller(str(entry_id))
    elif existing["owner_discord_user_id"] != session.discord_user_id:
        raise CampaignNotOwnedByCaller(str(entry_id))
    deleted = await repo.delete_glossary_entry(
        entry_id,
        guild_id=int(guild_id) if guild_id is not None else None,
        owner_discord_user_id=session.discord_user_id,
    )
    if not deleted:
        raise CampaignNotOwnedByCaller(str(entry_id))


# ---------------------------------------------------------------------------
# 11. Retention policy (REQ-MSG-019/REQ-DATA-002, mission section 13)
# ---------------------------------------------------------------------------


@router.get("/api/v1/retention-policy")
async def get_retention_policy(session: CurrentSessionDep) -> dict[str, Any]:
    """Delivery-history retention (did.campaigns.retention) is a
    system-level policy, not a per-campaign or per-Guild setting -- there
    is no durable per-owner override anywhere in the schema, and this
    endpoint must never invent one. It truthfully reports the single
    policy every Guild's terminal deliveries are subject to whenever a
    purge is applied, and the bounds any override would have to respect.
    A caller only needs to be authenticated; the policy is not scoped to
    them."""
    del session
    policy = RetentionPolicy()
    return {
        "retention_days": policy.retention_days,
        "min_retention_days": MIN_RETENTION_DAYS,
        "max_retention_days": MAX_RETENTION_DAYS,
        # Matches did.campaigns.retention's own module docstring exactly --
        # PENDING/CLAIMED/SENDING/UNKNOWN/INTERVENTION_REQUIRED deliveries
        # are never purged by age regardless of retention_days.
        "purged_delivery_statuses": ["SENT", "FAILED"],
    }
