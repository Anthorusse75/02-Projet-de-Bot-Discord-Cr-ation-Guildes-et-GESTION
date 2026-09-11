"""Unit tests for the Stage 09 campaign domain: lifecycle CAS, delivery state
machine, trigger-source authorization matching and glossary priority.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from did.domain.campaigns import (
    ApprovedVariant,
    CampaignLifecycleError,
    CampaignSchedule,
    CampaignTarget,
    DeliveryStatus,
    DeliveryTransitionError,
    GlossaryBehavior,
    GlossaryEntry,
    GlossaryScope,
    LifecycleStatus,
    MessageCampaign,
    MessageDelivery,
    PublicationMode,
    ScheduleKind,
    TargetKind,
    TranslationPublicationMode,
    TriggerSourceBinding,
    TriggerSourceScopeKind,
)

pytestmark = [pytest.mark.security]


def _campaign(**overrides: object) -> MessageCampaign:
    fields: dict[str, Any] = dict(
        id=uuid4(),
        owner_discord_user_id=1001,
        logical_campaign_key="camp-1",
        name="Launch announcement",
        source_language_code="en",
        message_model={"content": "hello"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
    )
    fields.update(overrides)
    return MessageCampaign(**fields)


class TestSourceLanguageIndependentOfUiLocale:
    """REQ-MSG-028: campaign source language is an explicit campaign
    property, never derived from or coupled to the dashboard UI locale."""

    def test_source_language_is_a_required_explicit_field(self) -> None:
        campaign = _campaign(source_language_code="de")
        assert campaign.source_language_code == "de"

    def test_source_language_survives_independent_of_any_ui_locale_value(self) -> None:
        """Simulates a UI session whose locale is 'fr' while the campaign's
        own source language is 'ja' -- the two must never be conflated;
        MessageCampaign has no field, default, or derivation path that reads
        a UI/session locale at all."""
        simulated_ui_locale = "fr"
        campaign = _campaign(source_language_code="ja")
        assert campaign.source_language_code == "ja"
        assert campaign.source_language_code != simulated_ui_locale
        assert not hasattr(campaign, "ui_locale")

    def test_blank_source_language_is_rejected_not_defaulted_from_locale(self) -> None:
        with pytest.raises(ValueError, match="source_language_code"):
            _campaign(source_language_code="")


class TestCampaignLifecycle:
    def test_draft_to_scheduled_armed_increments_version(self) -> None:
        campaign = _campaign()
        moved = campaign.transition_to(LifecycleStatus.SCHEDULED_ARMED)
        assert moved.lifecycle_status is LifecycleStatus.SCHEDULED_ARMED
        assert moved.version == campaign.version + 1
        # original is untouched (frozen/pure transition)
        assert campaign.lifecycle_status is LifecycleStatus.DRAFT

    def test_completed_is_terminal(self) -> None:
        campaign = _campaign(lifecycle_status=LifecycleStatus.COMPLETED)
        with pytest.raises(CampaignLifecycleError):
            campaign.transition_to(LifecycleStatus.ACTIVE_RUNNING)

    def test_cancelled_is_terminal(self) -> None:
        campaign = _campaign(lifecycle_status=LifecycleStatus.CANCELLED)
        with pytest.raises(CampaignLifecycleError):
            campaign.transition_to(LifecycleStatus.DRAFT)

    def test_draft_cannot_jump_to_completed(self) -> None:
        campaign = _campaign()
        with pytest.raises(CampaignLifecycleError):
            campaign.transition_to(LifecycleStatus.COMPLETED)

    def test_failed_intervention_can_resume_or_cancel_only(self) -> None:
        campaign = _campaign(lifecycle_status=LifecycleStatus.FAILED_INTERVENTION)
        assert (
            campaign.transition_to(LifecycleStatus.ACTIVE_RUNNING).lifecycle_status
            is LifecycleStatus.ACTIVE_RUNNING
        )
        with pytest.raises(CampaignLifecycleError):
            campaign.transition_to(LifecycleStatus.COMPLETED)

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            _campaign(name="   ")

    def test_non_positive_owner_rejected(self) -> None:
        with pytest.raises(ValueError, match="owner"):
            _campaign(owner_discord_user_id=0)


class TestCampaignSchedule:
    def test_one_shot_requires_fire_at(self) -> None:
        with pytest.raises(ValueError, match="fire_at"):
            CampaignSchedule(
                id=uuid4(),
                owner_discord_user_id=1,
                campaign_id=uuid4(),
                schedule_kind=ScheduleKind.ONE_SHOT,
            )

    def test_recurring_requires_rrule_and_timezone(self) -> None:
        with pytest.raises(ValueError, match="rrule"):
            CampaignSchedule(
                id=uuid4(),
                owner_discord_user_id=1,
                campaign_id=uuid4(),
                schedule_kind=ScheduleKind.RECURRING,
                rrule="FREQ=DAILY",
            )

    def test_recurring_requires_starts_at(self) -> None:
        with pytest.raises(ValueError, match="starts_at"):
            CampaignSchedule(
                id=uuid4(),
                owner_discord_user_id=1,
                campaign_id=uuid4(),
                schedule_kind=ScheduleKind.RECURRING,
                rrule="FREQ=DAILY",
                timezone="Europe/Paris",
            )

    def test_catch_up_bound_range_enforced(self) -> None:
        with pytest.raises(ValueError, match="catch_up_bound"):
            CampaignSchedule(
                id=uuid4(),
                owner_discord_user_id=1,
                campaign_id=uuid4(),
                schedule_kind=ScheduleKind.IMMEDIATE,
                catch_up_bound=51,
            )


class TestDeliveryStateMachine:
    def _delivery(self, **overrides: object) -> MessageDelivery:
        fields: dict[str, Any] = dict(
            id=uuid4(),
            guild_id=880000001,
            campaign_id=uuid4(),
            occurrence_id=uuid4(),
            target_id=uuid4(),
            delivery_key="k1",
            discord_channel_id=555,
            allowed_mentions_snapshot={"parse": []},
        )
        fields.update(overrides)
        return MessageDelivery(**fields)

    def test_normal_happy_path(self) -> None:
        d = self._delivery()
        d = d.transition_to(DeliveryStatus.CLAIMED)
        d = d.transition_to(DeliveryStatus.SENDING)
        d = d.transition_to(DeliveryStatus.SENT)
        assert d.status is DeliveryStatus.SENT

    def test_sent_is_terminal_no_blind_resend(self) -> None:
        d = self._delivery(status=DeliveryStatus.SENT)
        with pytest.raises(DeliveryTransitionError):
            d.transition_to(DeliveryStatus.PENDING)
        with pytest.raises(DeliveryTransitionError):
            d.transition_to(DeliveryStatus.SENDING)

    def test_unknown_outcome_never_moves_directly_to_pending(self) -> None:
        """Ambiguous send: never a blind retry, only intervention or resolved evidence."""
        d = self._delivery(status=DeliveryStatus.UNKNOWN)
        with pytest.raises(DeliveryTransitionError):
            d.transition_to(DeliveryStatus.PENDING)
        moved = d.transition_to(DeliveryStatus.INTERVENTION_REQUIRED)
        assert moved.status is DeliveryStatus.INTERVENTION_REQUIRED

    def test_unknown_can_resolve_to_sent_via_reconciliation_evidence(self) -> None:
        d = self._delivery(status=DeliveryStatus.UNKNOWN)
        moved = d.transition_to(DeliveryStatus.SENT)
        assert moved.status is DeliveryStatus.SENT

    def test_failed_can_be_retried_to_pending(self) -> None:
        d = self._delivery(status=DeliveryStatus.FAILED)
        moved = d.transition_to(DeliveryStatus.PENDING)
        assert moved.status is DeliveryStatus.PENDING


class TestTriggerSourceAuthorization:
    """REQ-MSG-027/030: an event_type alone never authorizes a trigger."""

    def test_guild_scope_binding_matches_any_resource_in_that_guild(self) -> None:
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=880000001,
            trigger_id=uuid4(),
            source_scope_kind=TriggerSourceScopeKind.GUILD,
        )
        assert binding.matches(880000001, None) is True
        assert binding.matches(880000001, 42) is True

    def test_guild_scope_binding_never_matches_other_guild(self) -> None:
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=880000001,
            trigger_id=uuid4(),
            source_scope_kind=TriggerSourceScopeKind.GUILD,
        )
        assert binding.matches(880000002, None) is False

    def test_unbound_guild_b_cannot_trigger_guild_a_campaign(self) -> None:
        """The concrete security invariant from the Stage 09 spec, at domain level."""
        guild_a_binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=111,
            trigger_id=uuid4(),
            source_scope_kind=TriggerSourceScopeKind.GUILD,
        )
        event_from_guild_b = 222
        assert guild_a_binding.matches(event_from_guild_b, None) is False

    def test_channel_scope_binding_requires_exact_channel_match(self) -> None:
        binding = TriggerSourceBinding(
            id=uuid4(),
            guild_id=880000001,
            trigger_id=uuid4(),
            source_scope_kind=TriggerSourceScopeKind.CHANNEL,
            discord_resource_id=999,
        )
        assert binding.matches(880000001, 999) is True
        assert binding.matches(880000001, 1000) is False

    def test_channel_scope_requires_positive_resource_id(self) -> None:
        with pytest.raises(ValueError, match="resource id"):
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=880000001,
                trigger_id=uuid4(),
                source_scope_kind=TriggerSourceScopeKind.CHANNEL,
            )

    def test_guild_scope_must_not_carry_resource_id(self) -> None:
        with pytest.raises(ValueError, match="resource id"):
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=880000001,
                trigger_id=uuid4(),
                source_scope_kind=TriggerSourceScopeKind.GUILD,
                discord_resource_id=1,
            )


class TestCampaignTarget:
    def test_channel_target_requires_channel_id(self) -> None:
        with pytest.raises(ValueError, match="discord_channel_id"):
            CampaignTarget(
                id=uuid4(),
                guild_id=880000001,
                campaign_id=uuid4(),
                target_kind=TargetKind.CHANNEL,
            )

    def test_translation_group_target_requires_publication_mode(self) -> None:
        with pytest.raises(ValueError, match="publication mode"):
            CampaignTarget(
                id=uuid4(),
                guild_id=880000001,
                campaign_id=uuid4(),
                target_kind=TargetKind.TRANSLATION_GROUP,
                translation_group_id=uuid4(),
            )

    def test_selected_languages_requires_at_least_one_language(self) -> None:
        with pytest.raises(ValueError, match="SELECTED_LANGUAGES"):
            CampaignTarget(
                id=uuid4(),
                guild_id=880000001,
                campaign_id=uuid4(),
                target_kind=TargetKind.TRANSLATION_GROUP,
                translation_group_id=uuid4(),
                translation_publication_mode=TranslationPublicationMode.SELECTED_LANGUAGES,
            )

    def test_channel_target_rejects_translation_group_id(self) -> None:
        with pytest.raises(ValueError, match="translation_group_id"):
            CampaignTarget(
                id=uuid4(),
                guild_id=880000001,
                campaign_id=uuid4(),
                target_kind=TargetKind.CHANNEL,
                discord_channel_id=1,
                translation_group_id=uuid4(),
            )


class TestGlossaryPriority:
    def test_campaign_scope_outranks_global_user(self) -> None:
        campaign_id = uuid4()
        campaign_entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.CAMPAIGN,
            campaign_id=campaign_id,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        global_entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        assert campaign_entry.specificity() > global_entry.specificity()

    def test_guild_scope_outranks_global_user_but_not_campaign(self) -> None:
        """REQ-MSG-014 external-review finding: the missing GUILD tier
        (langue/scope/template) must rank strictly between CAMPAIGN and
        GLOBAL_USER."""
        campaign_entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.CAMPAIGN,
            campaign_id=uuid4(),
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        guild_entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.GUILD,
            guild_id=880000001,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        global_entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        assert campaign_entry.specificity() > guild_entry.specificity() > global_entry.specificity()

    def test_guild_scope_requires_positive_guild_id(self) -> None:
        with pytest.raises(ValueError, match="guild_id"):
            GlossaryEntry(
                id=uuid4(),
                owner_discord_user_id=1,
                scope_kind=GlossaryScope.GUILD,
                source_term="Widget",
                behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
            )

    def test_guild_scope_must_not_carry_campaign_id(self) -> None:
        with pytest.raises(ValueError, match="campaign_id"):
            GlossaryEntry(
                id=uuid4(),
                owner_discord_user_id=1,
                scope_kind=GlossaryScope.GUILD,
                guild_id=880000001,
                campaign_id=uuid4(),
                source_term="Widget",
                behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
            )

    def test_campaign_scope_must_not_carry_guild_id(self) -> None:
        with pytest.raises(ValueError, match="guild_id"):
            GlossaryEntry(
                id=uuid4(),
                owner_discord_user_id=1,
                scope_kind=GlossaryScope.CAMPAIGN,
                campaign_id=uuid4(),
                guild_id=880000001,
                source_term="Widget",
                behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
            )

    def test_language_specific_outranks_language_agnostic_within_scope(self) -> None:
        specific = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Widget",
            behavior=GlossaryBehavior.FORCED_TRANSLATION,
            forced_translation="Widgeto",
            target_language_code="fr",
        )
        agnostic = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=1,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        assert specific.specificity() > agnostic.specificity()

    def test_forced_translation_requires_text(self) -> None:
        with pytest.raises(ValueError, match="forced_translation"):
            GlossaryEntry(
                id=uuid4(),
                owner_discord_user_id=1,
                scope_kind=GlossaryScope.GLOBAL_USER,
                source_term="Widget",
                behavior=GlossaryBehavior.FORCED_TRANSLATION,
            )

    def test_do_not_translate_rejects_forced_translation_text(self) -> None:
        with pytest.raises(ValueError, match="DO_NOT_TRANSLATE"):
            GlossaryEntry(
                id=uuid4(),
                owner_discord_user_id=1,
                scope_kind=GlossaryScope.GLOBAL_USER,
                source_term="Widget",
                behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
                forced_translation="nope",
            )


class TestApprovedVariant:
    def test_stale_when_fingerprint_diverges(self) -> None:
        variant = ApprovedVariant(
            id=uuid4(),
            owner_discord_user_id=1,
            campaign_id=uuid4(),
            target_language_code="fr",
            source_fingerprint="a" * 64,
            localized_message_model={"content": "bonjour"},
            approved_by_discord_user_id=1,
        )
        assert variant.is_stale_for("a" * 64) is False
        assert variant.is_stale_for("b" * 64) is True

    def test_rejects_malformed_fingerprint(self) -> None:
        with pytest.raises(ValueError, match="fingerprint"):
            ApprovedVariant(
                id=uuid4(),
                owner_discord_user_id=1,
                campaign_id=uuid4(),
                target_language_code="fr",
                source_fingerprint="short",
                localized_message_model={},
                approved_by_discord_user_id=1,
            )
