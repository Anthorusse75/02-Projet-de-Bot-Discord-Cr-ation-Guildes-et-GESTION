from __future__ import annotations

from dataclasses import dataclass

from did.portability.artifact import PortableArtifact, PortableDependency, PortableResource


class DependencyGraphError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    nodes: tuple[PortableResource, ...]
    edges: tuple[PortableDependency, ...]

    @classmethod
    def build(cls, artifact: PortableArtifact) -> DependencyGraph:
        graph = cls(artifact.resources, artifact.dependencies)
        graph.topological_order()
        return graph

    def topological_order(self) -> tuple[str, ...]:
        keys = {node.logical_key for node in self.nodes}
        required_by: dict[str, set[str]] = {key: set() for key in keys}
        in_degree = dict.fromkeys(keys, 0)
        for edge in self.edges:
            if edge.source not in keys or edge.target not in keys:
                raise DependencyGraphError("unknown dependency reference")
            required_by[edge.target].add(edge.source)
            in_degree[edge.source] += 1
        ready = sorted(key for key, degree in in_degree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            key = ready.pop(0)
            ordered.append(key)
            for consumer in sorted(required_by[key]):
                in_degree[consumer] -= 1
                if in_degree[consumer] == 0:
                    ready.append(consumer)
                    ready.sort()
        if len(ordered) != len(keys):
            raise DependencyGraphError("portable dependency graph contains a cycle")
        return tuple(ordered)

    def closure(self, roots: tuple[str, ...]) -> tuple[str, ...]:
        known = {node.logical_key for node in self.nodes}
        if any(root not in known for root in roots):
            raise DependencyGraphError("closure root is unknown")
        dependencies: dict[str, set[str]] = {key: set() for key in known}
        for edge in self.edges:
            if edge.required:
                dependencies[edge.source].add(edge.target)
        selected = set(roots)
        pending = list(roots)
        while pending:
            current = pending.pop()
            for dependency in dependencies[current]:
                if dependency not in selected:
                    selected.add(dependency)
                    pending.append(dependency)
        order = self.topological_order()
        return tuple(key for key in order if key in selected)
