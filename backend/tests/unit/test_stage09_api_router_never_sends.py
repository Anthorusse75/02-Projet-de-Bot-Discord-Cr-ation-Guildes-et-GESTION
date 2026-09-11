"""Proves the Stage 09 campaign API router (``did.api.stage09``) never
imports or references the Discord-sending adapter.

Mission-critical constraint: activation must ONLY create/reserve durable
work (``did.campaigns.activation.fan_out_occurrence`` only ever creates
``message_deliveries`` rows; ``did.campaigns.dispatch
.route_pending_deliveries_to_jobs`` only ever enqueues durable
``discord_io_jobs`` rows) and must NEVER call
``did.infrastructure.discord_message_sender.DiscordPyMessageSender`` (or any
other Discord-sending adapter) directly from the API layer -- actually
sending is exclusively the durable worker's job
(``did.campaigns.dispatch.CampaignDeliveryExecutor``/
``did.campaigns.delivery_worker.process_delivery``), entirely outside any
HTTP request.

Two independent proofs, so a subtle indirect import cannot slip past either
alone: the module's own source text never mentions the sender class or its
module path, and importing the router does not pull that module into
``sys.modules`` at all.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys

import pytest

pytestmark = [pytest.mark.security]

_FORBIDDEN_MODULE = "did.infrastructure.discord_message_sender"
_FORBIDDEN_NAMES = ("DiscordPyMessageSender", "discord_message_sender")


def test_router_source_never_mentions_the_discord_sender() -> None:
    import did.api.stage09 as stage09

    source = inspect.getsource(stage09)
    for forbidden in _FORBIDDEN_NAMES:
        assert forbidden not in source, (
            f"did.api.stage09 must never reference {forbidden!r} -- activation must "
            "only create/reserve durable work, never send to Discord directly"
        )


def test_router_has_no_import_statement_for_the_discord_sender_module() -> None:
    import did.api.stage09 as stage09

    tree = ast.parse(inspect.getsource(stage09))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert _FORBIDDEN_MODULE not in imported_modules


def test_importing_the_router_does_not_load_the_discord_sender_module() -> None:
    # Reload in isolation: if some OTHER already-imported module had pulled
    # discord_message_sender into sys.modules first, a plain membership
    # check against the ambient sys.modules could pass for the wrong
    # reason. Removing both modules first and re-importing proves
    # did.api.stage09's own import graph -- not some unrelated fixture --
    # is what is (or is not) responsible.
    for name in (_FORBIDDEN_MODULE, "did.api.stage09"):
        sys.modules.pop(name, None)
    importlib.import_module("did.api.stage09")
    assert _FORBIDDEN_MODULE not in sys.modules, (
        "importing did.api.stage09 must never load the Discord-sending adapter module"
    )
