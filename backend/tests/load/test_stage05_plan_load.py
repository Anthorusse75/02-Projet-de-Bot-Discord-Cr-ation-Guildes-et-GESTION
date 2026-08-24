from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest

from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.read_model import CoverageSnapshot, FreshnessSnapshot, GuildSnapshot, RoleSnapshot
from did.planning.canonical import canonical_hash
from did.planning.compiler import PlanCompiler
from did.planning.dag import topological_order
from did.planning.models import DesiredNode, DesiredStateGraph, ResourceType

pytestmark = pytest.mark.load
GUILD = 650505050505050501
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def empty_guild() -> GuildSnapshot:
    freshness = FreshnessSnapshot(FreshnessState.FRESH, "LOAD", 1, NOW, NOW, NOW)
    return GuildSnapshot(
        GUILD,
        650505050505050502,
        (RoleSnapshot(GUILD, GUILD, "@everyone", 0, 0, False, freshness),),
        (),
        CoverageSnapshot(
            GUILD,
            CoverageMode.FULL,
            FreshnessState.FRESH,
            "LOAD",
            1,
            known_roles=1,
            overwrites_complete=True,
        ),
        freshness,
        source_versions=("load:1",),
    )


def test_large_plan_compile_hash_and_dag_are_bounded_and_deterministic() -> None:
    nodes = tuple(
        DesiredNode.build(
            logical_key=f"role.load.{index:04d}",
            resource_type=ResourceType.ROLE,
            symbol=f"sym.role.load.{index:04d}",
            properties={"name": f"DID load {index:04d}", "permissions": "0"},
        )
        for index in range(500)
    )
    graph = DesiredStateGraph(GUILD, tuple(reversed(nodes)))
    started = perf_counter()
    operations = PlanCompiler().compile(empty_guild(), graph, plan_id=uuid4())
    duration = perf_counter() - started
    assert len(operations) == 500
    assert len(topological_order(operations)) == 500
    assert canonical_hash(graph) == canonical_hash(DesiredStateGraph(GUILD, nodes))
    assert duration < 3.0
    report = {
        "scenario": "stage05-large-dag",
        "nodes": len(nodes),
        "operations": len(operations),
        "duration_seconds": round(duration, 6),
        "threshold_seconds": 3.0,
        "deterministic": True,
    }
    report_path = os.environ.get("DID_STAGE05_LOAD_REPORT")
    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
