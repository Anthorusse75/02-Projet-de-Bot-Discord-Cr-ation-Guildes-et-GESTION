"""PostgreSQL integration tests for durable template-variable persistence
(REQ-MSG-018, mission section 10): CampaignsRepository CRUD, ownership
isolation, and the real did.campaigns.context.load_fan_out_context wiring
that replaced the previous hardcoded template_variable_definitions={}
default.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from did.campaigns.context import load_fan_out_context
from did.domain.campaigns import (
    CampaignTemplateVariable,
    LifecycleStatus,
    MessageCampaign,
    PublicationMode,
)
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
)
from did.messaging.template_variables import TemplateVariableType

pytestmark = [pytest.mark.integration, pytest.mark.security]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
OWNER_A = 880001011
OWNER_B = 880001012

CLEANUP_STATEMENTS = (
    "DELETE FROM message_campaign_template_variables WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id IN (:oa,:ob)",
)
CLEANUP_PARAMS = {"oa": OWNER_A, "ob": OWNER_B}


@pytest.fixture
async def repo_context() -> AsyncIterator[CampaignsRepository]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
                    "ON CONFLICT (discord_user_id) DO NOTHING"
                ),
                {"id": OWNER_A, "name": "owner-a"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
                    "ON CONFLICT (discord_user_id) DO NOTHING"
                ),
                {"id": OWNER_B, "name": "owner-b"},
            )
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield CampaignsRepository(factory)
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
        await app_engine.dispose()
        await admin_engine.dispose()


async def _create_campaign(
    repo: CampaignsRepository, *, owner: int = OWNER_A, content: str = "Hello {{name}}"
) -> MessageCampaign:
    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=owner,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Launch",
        source_language_code="en",
        message_model={"content": content},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    await repo.create_campaign(campaign)
    return campaign


@pytest.mark.asyncio
class TestTemplateVariableRepositoryCrud:
    async def test_create_list_update_delete_round_trip(
        self, repo_context: CampaignsRepository
    ) -> None:
        repo = repo_context
        campaign = await _create_campaign(repo)
        variable = CampaignTemplateVariable(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            name="name",
            variable_type=TemplateVariableType.TRANSLATABLE_TEXT,
            value="Alex",
        )
        await repo.create_template_variable(variable)

        rows = await repo.list_template_variables_for_campaign(OWNER_A, campaign.id)
        assert len(rows) == 1
        assert rows[0]["name"] == "name"
        assert rows[0]["value"] == "Alex"

        updated = await repo.update_template_variable(
            OWNER_A,
            campaign.id,
            variable.id,
            variable_type=TemplateVariableType.NON_TRANSLATABLE.value,
            value="Fixed Value",
            values_by_language=None,
        )
        assert updated is True
        rows = await repo.list_template_variables_for_campaign(OWNER_A, campaign.id)
        assert rows[0]["variable_type"] == "NON_TRANSLATABLE"
        assert rows[0]["value"] == "Fixed Value"

        deleted = await repo.delete_template_variable(OWNER_A, campaign.id, variable.id)
        assert deleted is True
        assert await repo.list_template_variables_for_campaign(OWNER_A, campaign.id) == []

    async def test_localized_value_shape_round_trips_through_jsonb(
        self, repo_context: CampaignsRepository
    ) -> None:
        repo = repo_context
        campaign = await _create_campaign(repo)
        variable = CampaignTemplateVariable(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            name="price",
            variable_type=TemplateVariableType.LOCALIZED_VALUE,
            values_by_language={"en": "$10", "fr": "10 €"},
        )
        await repo.create_template_variable(variable)
        [row] = await repo.list_template_variables_for_campaign(OWNER_A, campaign.id)
        assert row["value"] is None
        assert row["values_by_language"] == {"en": "$10", "fr": "10 €"}

    async def test_duplicate_name_within_a_campaign_conflicts(
        self, repo_context: CampaignsRepository
    ) -> None:
        repo = repo_context
        campaign = await _create_campaign(repo)
        first = CampaignTemplateVariable(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            name="name",
            variable_type=TemplateVariableType.TRANSLATABLE_TEXT,
            value="Alex",
        )
        await repo.create_template_variable(first)
        second = CampaignTemplateVariable(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            name="name",
            variable_type=TemplateVariableType.TRANSLATABLE_TEXT,
            value="Jordan",
        )
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await repo.create_template_variable(second)

    async def test_ownership_isolation_a_foreign_owner_never_mutates_another_owners_variable(
        self, repo_context: CampaignsRepository
    ) -> None:
        repo = repo_context
        campaign = await _create_campaign(repo, owner=OWNER_A)
        variable = CampaignTemplateVariable(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            name="name",
            variable_type=TemplateVariableType.TRANSLATABLE_TEXT,
            value="Alex",
        )
        await repo.create_template_variable(variable)

        assert await repo.list_template_variables_for_campaign(OWNER_B, campaign.id) == []
        assert (
            await repo.update_template_variable(
                OWNER_B,
                campaign.id,
                variable.id,
                variable_type=TemplateVariableType.NON_TRANSLATABLE.value,
                value="hijacked",
                values_by_language=None,
            )
            is False
        )
        assert await repo.delete_template_variable(OWNER_B, campaign.id, variable.id) is False
        # Untouched by the foreign owner's attempts.
        [row] = await repo.list_template_variables_for_campaign(OWNER_A, campaign.id)
        assert row["value"] == "Alex"


@pytest.mark.asyncio
class TestLoadFanOutContextWiresPersistedTemplateVariables:
    async def test_a_persisted_definition_flows_into_the_real_fan_out_context(
        self, repo_context: CampaignsRepository
    ) -> None:
        """The core wiring fix this pass makes: did.campaigns.runtime
        .CampaignSchedulerRuntime/did.api.stage09.activate_campaign/did
        .campaigns.event_transport previously all passed a hardcoded {}
        regardless of what an author declared -- this proves the real,
        durable path from CampaignsRepository through
        load_fan_out_context actually surfaces it."""
        repo = repo_context
        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        try:
            campaign = await _create_campaign(repo, content="Hello {{name}}")
            variable = CampaignTemplateVariable(
                id=uuid4(),
                owner_discord_user_id=OWNER_A,
                campaign_id=campaign.id,
                name="name",
                variable_type=TemplateVariableType.TRANSLATABLE_TEXT,
                value="Alex",
            )
            await repo.create_template_variable(variable)

            app_engine = create_database_engine(APP_URL, pool_size=1)
            try:
                factory = async_sessionmaker(app_engine, expire_on_commit=False)
                context = await load_fan_out_context(
                    campaigns_repository=repo,
                    admin_factory=admin_factory,
                    language_profiles=LanguageProfileRepository(factory),
                    translation_groups=TranslationGroupRepository(factory),
                    campaign=campaign,
                    translation_provider=None,
                )
            finally:
                await app_engine.dispose()

            assert "name" in context.template_variable_definitions
            definition = context.template_variable_definitions["name"]
            assert definition.resolve(target_language="en") == "Alex"
        finally:
            await admin_engine.dispose()
