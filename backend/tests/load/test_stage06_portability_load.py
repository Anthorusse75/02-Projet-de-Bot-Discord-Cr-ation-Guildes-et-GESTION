from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter

import pytest

from did.cloning import DestinationPlanCompiler
from did.portability import (
    ArtifactType,
    CloneMode,
    DependencyGraph,
    MappingResolver,
    PortableArtifact,
    PortableDependency,
    PortableResource,
    PortableResourceType,
    artifact_to_bytes,
)

pytestmark = pytest.mark.load


def test_large_portable_graph_build_mapping_and_compile_is_bounded() -> None:
    resources: list[PortableResource] = []
    dependencies: list[PortableDependency] = []
    roots: list[str] = []
    for index in range(200):
        role = f"role.r{index:04d}"
        category = f"category.c{index:04d}"
        channel = f"channel.c{index:04d}"
        resources.extend(
            (
                PortableResource.build(
                    role,
                    PortableResourceType.ROLE,
                    {"name": f"Role {index}", "permissions": "0", "position": index},
                ),
                PortableResource.build(
                    category,
                    PortableResourceType.CATEGORY,
                    {"name": f"Category {index}", "position": index},
                ),
                PortableResource.build(
                    channel,
                    PortableResourceType.CHANNEL,
                    {"name": f"channel-{index}", "type": 0, "position": index},
                ),
            )
        )
        dependencies.append(PortableDependency(channel, category, "parent"))
        roots.extend((role, category, channel))

    started = perf_counter()
    artifact = PortableArtifact(
        ArtifactType.GUILD_CONFIG,
        tuple(resources),
        tuple(dependencies),
        tuple(roots),
    )
    artifact_seconds = perf_counter() - started
    started = perf_counter()
    graph = DependencyGraph.build(artifact)
    closure = graph.closure(tuple(roots))
    graph_seconds = perf_counter() - started
    started = perf_counter()
    mappings = MappingResolver().resolve(
        graph,
        destination_guild_id=987654321098765432,
        mode=CloneMode.COPY_AS_NEW,
    )
    mapping_seconds = perf_counter() - started
    started = perf_counter()
    compilation = DestinationPlanCompiler().compile(
        artifact,
        destination_guild_id=987654321098765432,
        mode=CloneMode.COPY_AS_NEW,
        resolutions=mappings,
    )
    compile_seconds = perf_counter() - started

    assert len(artifact.resources) == 600
    assert len(closure) == 600
    assert len(mappings) == 600
    assert len(compilation.graph.nodes) == 600
    assert max(artifact_seconds, graph_seconds, mapping_seconds, compile_seconds) < 10.0
    report = {
        "scenario": "stage06-portable-600-resources",
        "resources": 600,
        "dependencies": 200,
        "artifact_bytes": len(artifact_to_bytes(artifact)),
        "artifact_build_seconds": artifact_seconds,
        "graph_seconds": graph_seconds,
        "mapping_seconds": mapping_seconds,
        "compile_seconds": compile_seconds,
        "network_calls": 0,
        "database_calls": 0,
    }
    configured = os.environ.get("DID_STAGE06_LOAD_REPORT")
    if configured:
        path = Path(configured)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
