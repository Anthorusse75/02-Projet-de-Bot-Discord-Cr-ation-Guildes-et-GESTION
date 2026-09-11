"""Stage 09 remediation: add the missing GUILD glossary scope tier.

Revision ID: 0024_stage_09
Revises: 0023_stage_09

External-review finding (REQ-MSG-014): the canonical requirement is
"glossaries ... avec une priorite deterministe du plus specifique au plus
general" across language/scope/template -- the shipped model only had
CAMPAIGN (the "template" tier: a campaign's own message content) and
GLOBAL_USER, missing a GUILD tier entirely. Adds it, with a dual-condition
RLS policy: a GUILD-scoped row is visible under Guild tenant context
(app.current_guild_id()), while GLOBAL_USER/CAMPAIGN rows stay visible under
owner context (app.current_user_id()) exactly as before -- both session GUCs
are already set together by apply_rls_context() whenever a caller opens a
TenantContext(guild_id, user_id=owner_id), so no new session-scoping
mechanism is needed.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0024_stage_09"
down_revision: str | None = "0023_stage_09"
branch_labels: str | None = None
depends_on: str | None = None

_OLD_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX uq_message_glossary_entries_term ON message_glossary_entries "
    "(owner_discord_user_id, scope_kind, "
    "coalesce(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid), "
    "lower(source_term), coalesce(target_language_code, ''))"
)
_NEW_UNIQUE_INDEX_SQL = (
    "CREATE UNIQUE INDEX uq_message_glossary_entries_term ON message_glossary_entries "
    "(owner_discord_user_id, scope_kind, "
    "coalesce(guild_id, 0), "
    "coalesce(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid), "
    "lower(source_term), coalesce(target_language_code, ''))"
)


def upgrade() -> None:
    op.add_column("message_glossary_entries", sa.Column("guild_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_message_glossary_entries_guild",
        "message_glossary_entries",
        "guild_installations",
        ["guild_id"],
        ["guild_id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "ck_message_glossary_entries_scope", "message_glossary_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_message_glossary_entries_scope",
        "message_glossary_entries",
        "scope_kind IN ('GLOBAL_USER','GUILD','CAMPAIGN')",
    )

    op.drop_constraint(
        "ck_message_glossary_entries_scope_shape", "message_glossary_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_message_glossary_entries_scope_shape",
        "message_glossary_entries",
        "(scope_kind = 'CAMPAIGN' AND campaign_id IS NOT NULL AND guild_id IS NULL) OR "
        "(scope_kind = 'GUILD' AND guild_id IS NOT NULL AND campaign_id IS NULL) OR "
        "(scope_kind = 'GLOBAL_USER' AND campaign_id IS NULL AND guild_id IS NULL)",
    )

    op.execute("DROP INDEX uq_message_glossary_entries_term")
    op.execute(_NEW_UNIQUE_INDEX_SQL)

    op.execute("DROP POLICY message_glossary_entries_owner_isolation ON message_glossary_entries")
    op.execute(
        "CREATE POLICY message_glossary_entries_scope_isolation ON message_glossary_entries "
        "USING ("
        "(guild_id IS NOT NULL AND guild_id = app.current_guild_id()) OR "
        "(guild_id IS NULL AND owner_discord_user_id = app.current_user_id())"
        ") "
        "WITH CHECK ("
        "(guild_id IS NOT NULL AND guild_id = app.current_guild_id()) OR "
        "(guild_id IS NULL AND owner_discord_user_id = app.current_user_id())"
        ")"
    )


def downgrade() -> None:
    op.execute("DELETE FROM message_glossary_entries WHERE scope_kind = 'GUILD'")

    op.execute("DROP POLICY message_glossary_entries_scope_isolation ON message_glossary_entries")
    op.execute(
        "CREATE POLICY message_glossary_entries_owner_isolation ON message_glossary_entries "
        "USING (owner_discord_user_id = app.current_user_id()) "
        "WITH CHECK (owner_discord_user_id = app.current_user_id())"
    )

    op.execute("DROP INDEX uq_message_glossary_entries_term")
    op.execute(_OLD_UNIQUE_INDEX_SQL)

    op.drop_constraint(
        "ck_message_glossary_entries_scope_shape", "message_glossary_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_message_glossary_entries_scope_shape",
        "message_glossary_entries",
        "(scope_kind = 'CAMPAIGN' AND campaign_id IS NOT NULL) OR "
        "(scope_kind = 'GLOBAL_USER' AND campaign_id IS NULL)",
    )

    op.drop_constraint(
        "ck_message_glossary_entries_scope", "message_glossary_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_message_glossary_entries_scope",
        "message_glossary_entries",
        "scope_kind IN ('GLOBAL_USER','CAMPAIGN')",
    )

    op.drop_constraint(
        "fk_message_glossary_entries_guild", "message_glossary_entries", type_="foreignkey"
    )
    op.drop_column("message_glossary_entries", "guild_id")
