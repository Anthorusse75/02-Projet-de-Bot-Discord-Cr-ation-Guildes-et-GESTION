"""Make clone relationships durable and transfer intent immutable.

Revision ID: 0012_stage_06
Revises: 0011_stage_06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_stage_06"
down_revision: str | None = "0011_stage_06"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portable_clone_relationships",
        sa.Column("relationship_id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_guild_id", sa.BigInteger(), nullable=False),
        sa.Column("creation_key", sa.String(64), nullable=False),
        sa.Column(
            "source_descriptor_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), server_default="ACTIVE", nullable=False),
        sa.Column("last_transfer_id", sa.Uuid(), nullable=True),
        sa.Column("last_artifact_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(creation_key) = 64", name="ck_clone_relationship_creation"),
        sa.CheckConstraint(
            "last_artifact_hash IS NULL OR length(last_artifact_hash) = 64",
            name="ck_clone_relationship_hash",
        ),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name="ck_clone_relationship_status"),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"], ["users.discord_user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("relationship_id", name="pk_portable_clone_relationships"),
        sa.UniqueConstraint(
            "owner_discord_user_id",
            "destination_guild_id",
            "relationship_id",
            name="uq_clone_relationship_owner_destination_id",
        ),
        sa.UniqueConstraint(
            "owner_discord_user_id", "creation_key", name="uq_clone_relationship_creation"
        ),
    )
    op.execute("ALTER TABLE portable_clone_relationships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portable_clone_relationships FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY portable_clone_relationships_owner_isolation "
        "ON portable_clone_relationships "
        "USING (owner_discord_user_id = app.current_user_id()) "
        "WITH CHECK (owner_discord_user_id = app.current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON portable_clone_relationships TO did_app")

    op.add_column("cross_guild_transfers", sa.Column("relationship_id", sa.Uuid()))
    op.add_column("cross_guild_transfers", sa.Column("request_hash", sa.String(64)))
    op.add_column("cross_guild_transfers", sa.Column("mapping_hash", sa.String(64)))
    op.add_column("cross_guild_transfers", sa.Column("report_hash", sa.String(64)))
    op.add_column("portable_clone_bindings", sa.Column("relationship_id", sa.Uuid()))
    op.add_column("portable_clone_bindings", sa.Column("tombstoned_at", sa.DateTime(timezone=True)))

    op.execute(
        "INSERT INTO portable_clone_relationships "
        "(relationship_id,owner_discord_user_id,destination_guild_id,creation_key,"
        "source_descriptor_json,last_artifact_hash) "
        "SELECT gen_random_uuid(), owner_id, destination_id, relationship_key, "
        "jsonb_build_object('legacy_relationship_key', relationship_key), artifact_hash "
        "FROM ("
        "SELECT actor_discord_user_id AS owner_id,destination_guild_id AS destination_id,"
        "relationship_key,max(artifact_content_hash) AS artifact_hash "
        "FROM cross_guild_transfers WHERE relationship_key IS NOT NULL "
        "GROUP BY actor_discord_user_id,destination_guild_id,relationship_key "
        "UNION "
        "SELECT owner_discord_user_id,destination_guild_id,relationship_key,"
        "max(source_artifact_hash) FROM portable_clone_bindings "
        "GROUP BY owner_discord_user_id,destination_guild_id,relationship_key"
        ") legacy ON CONFLICT (owner_discord_user_id,creation_key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO portable_clone_relationships "
        "(relationship_id,owner_discord_user_id,destination_guild_id,creation_key,"
        "source_descriptor_json,last_artifact_hash) "
        "SELECT gen_random_uuid(),actor_discord_user_id,destination_guild_id,"
        "md5(id::text)||md5(id::text||'-legacy'),"
        "jsonb_build_object('legacy_transfer_id', id::text),artifact_content_hash "
        "FROM cross_guild_transfers WHERE relationship_key IS NULL"
    )
    op.execute(
        "UPDATE cross_guild_transfers t SET relationship_id=r.relationship_id "
        "FROM portable_clone_relationships r WHERE "
        "r.owner_discord_user_id=t.actor_discord_user_id AND "
        "r.destination_guild_id=t.destination_guild_id AND "
        "r.creation_key=coalesce(t.relationship_key,md5(t.id::text)||md5(t.id::text||'-legacy'))"
    )
    op.execute(
        "UPDATE portable_clone_bindings b SET relationship_id=r.relationship_id "
        "FROM portable_clone_relationships r WHERE "
        "r.owner_discord_user_id=b.owner_discord_user_id AND "
        "r.destination_guild_id=b.destination_guild_id AND "
        "r.creation_key=b.relationship_key"
    )
    op.execute(
        "UPDATE cross_guild_transfers SET request_hash=artifact_content_hash,"
        "mapping_hash=CASE WHEN status IN ('READY','COMPILED') THEN "
        "md5(mapping_json::text)||md5('mapping-'||mapping_json::text) END,"
        "report_hash=CASE WHEN report_json IS NOT NULL THEN "
        "md5(report_json::text)||md5('report-'||report_json::text) END"
    )

    op.alter_column("cross_guild_transfers", "relationship_id", nullable=False)
    op.alter_column("cross_guild_transfers", "request_hash", nullable=False)
    op.alter_column("portable_clone_bindings", "relationship_id", nullable=False)
    op.create_check_constraint(
        "ck_transfers_request_hash", "cross_guild_transfers", "length(request_hash) = 64"
    )
    op.create_check_constraint(
        "ck_transfers_mapping_hash",
        "cross_guild_transfers",
        "mapping_hash IS NULL OR length(mapping_hash) = 64",
    )
    op.create_check_constraint(
        "ck_transfers_report_hash",
        "cross_guild_transfers",
        "report_hash IS NULL OR length(report_hash) = 64",
    )
    op.create_foreign_key(
        "fk_transfers_clone_relationship",
        "cross_guild_transfers",
        "portable_clone_relationships",
        ["actor_discord_user_id", "destination_guild_id", "relationship_id"],
        ["owner_discord_user_id", "destination_guild_id", "relationship_id"],
        ondelete="RESTRICT",
    )

    op.drop_index("ix_clone_bindings_scope", table_name="portable_clone_bindings")
    op.drop_constraint("uq_clone_binding_destination", "portable_clone_bindings", type_="unique")
    op.drop_constraint("pk_portable_clone_bindings", "portable_clone_bindings", type_="primary")
    op.drop_constraint(
        "portable_clone_bindings_transfer_id_fkey", "portable_clone_bindings", type_="foreignkey"
    )
    op.alter_column("portable_clone_bindings", "transfer_id", new_column_name="last_transfer_id")
    op.alter_column("portable_clone_bindings", "last_transfer_id", nullable=True)
    op.create_foreign_key(
        "fk_clone_bindings_relationship",
        "portable_clone_bindings",
        "portable_clone_relationships",
        ["owner_discord_user_id", "destination_guild_id", "relationship_id"],
        ["owner_discord_user_id", "destination_guild_id", "relationship_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_clone_bindings_last_transfer",
        "portable_clone_bindings",
        "cross_guild_transfers",
        ["last_transfer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_primary_key(
        "pk_portable_clone_bindings",
        "portable_clone_bindings",
        ["owner_discord_user_id", "destination_guild_id", "relationship_id", "logical_ref"],
    )
    op.create_unique_constraint(
        "uq_clone_binding_destination",
        "portable_clone_bindings",
        [
            "owner_discord_user_id",
            "destination_guild_id",
            "relationship_id",
            "resource_type",
            "destination_resource_id",
        ],
    )
    op.create_index(
        "ix_clone_bindings_scope",
        "portable_clone_bindings",
        ["owner_discord_user_id", "destination_guild_id", "relationship_id", "active"],
    )
    op.drop_column("portable_clone_bindings", "relationship_key")
    op.drop_constraint("ck_transfers_relationship_key", "cross_guild_transfers", type_="check")
    op.drop_column("cross_guild_transfers", "relationship_key")


def downgrade() -> None:
    op.add_column("cross_guild_transfers", sa.Column("relationship_key", sa.String(64)))
    op.add_column("portable_clone_bindings", sa.Column("relationship_key", sa.String(64)))
    op.execute(
        "UPDATE cross_guild_transfers t SET relationship_key=r.creation_key "
        "FROM portable_clone_relationships r WHERE r.relationship_id=t.relationship_id"
    )
    op.execute(
        "UPDATE portable_clone_bindings b SET relationship_key=r.creation_key "
        "FROM portable_clone_relationships r WHERE r.relationship_id=b.relationship_id"
    )
    op.alter_column("cross_guild_transfers", "relationship_key", nullable=True)
    op.alter_column("portable_clone_bindings", "relationship_key", nullable=False)
    op.create_check_constraint(
        "ck_transfers_relationship_key",
        "cross_guild_transfers",
        "relationship_key IS NULL OR length(relationship_key) = 64",
    )

    op.drop_index("ix_clone_bindings_scope", table_name="portable_clone_bindings")
    op.drop_constraint("uq_clone_binding_destination", "portable_clone_bindings", type_="unique")
    op.drop_constraint("pk_portable_clone_bindings", "portable_clone_bindings", type_="primary")
    op.drop_constraint(
        "fk_clone_bindings_last_transfer", "portable_clone_bindings", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_clone_bindings_relationship", "portable_clone_bindings", type_="foreignkey"
    )
    op.execute("DELETE FROM portable_clone_bindings WHERE last_transfer_id IS NULL")
    op.alter_column("portable_clone_bindings", "last_transfer_id", nullable=False)
    op.alter_column("portable_clone_bindings", "last_transfer_id", new_column_name="transfer_id")
    op.create_foreign_key(
        "portable_clone_bindings_transfer_id_fkey",
        "portable_clone_bindings",
        "cross_guild_transfers",
        ["transfer_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_primary_key(
        "pk_portable_clone_bindings",
        "portable_clone_bindings",
        ["owner_discord_user_id", "destination_guild_id", "relationship_key", "logical_ref"],
    )
    op.create_unique_constraint(
        "uq_clone_binding_destination",
        "portable_clone_bindings",
        [
            "owner_discord_user_id",
            "destination_guild_id",
            "relationship_key",
            "resource_type",
            "destination_resource_id",
        ],
    )
    op.create_index(
        "ix_clone_bindings_scope",
        "portable_clone_bindings",
        ["owner_discord_user_id", "destination_guild_id", "relationship_key", "active"],
    )

    op.drop_constraint(
        "fk_transfers_clone_relationship", "cross_guild_transfers", type_="foreignkey"
    )
    op.drop_constraint("ck_transfers_report_hash", "cross_guild_transfers", type_="check")
    op.drop_constraint("ck_transfers_mapping_hash", "cross_guild_transfers", type_="check")
    op.drop_constraint("ck_transfers_request_hash", "cross_guild_transfers", type_="check")
    op.drop_column("portable_clone_bindings", "tombstoned_at")
    op.drop_column("portable_clone_bindings", "relationship_id")
    op.drop_column("cross_guild_transfers", "report_hash")
    op.drop_column("cross_guild_transfers", "mapping_hash")
    op.drop_column("cross_guild_transfers", "request_hash")
    op.drop_column("cross_guild_transfers", "relationship_id")
    op.drop_table("portable_clone_relationships")
