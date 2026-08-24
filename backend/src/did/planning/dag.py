from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from did.planning.models import PlanOperation


class DagValidationError(ValueError):
    pass


def validate_dag(operations: Iterable[PlanOperation]) -> None:
    materialized = tuple(operations)
    ids = {operation.operation_id for operation in materialized}
    if len(ids) != len(materialized):
        raise DagValidationError("duplicate operation ID")
    for operation in materialized:
        unknown = set(operation.predecessors) - ids
        if unknown:
            raise DagValidationError("dependency references an unknown operation")
        if operation.operation_id in operation.predecessors:
            raise DagValidationError("self dependency")
    topological_order(materialized)


def topological_order(operations: Iterable[PlanOperation]) -> tuple[UUID, ...]:
    materialized = tuple(operations)
    by_id = {operation.operation_id: operation for operation in materialized}
    indegree = {operation_id: 0 for operation_id in by_id}
    children: dict[UUID, list[UUID]] = defaultdict(list)
    for operation in materialized:
        for predecessor in operation.predecessors:
            if predecessor not in by_id:
                raise DagValidationError("dependency references an unknown operation")
            indegree[operation.operation_id] += 1
            children[predecessor].append(operation.operation_id)
    ready = sorted((item for item, degree in indegree.items() if degree == 0), key=str)
    ordered: list[UUID] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in sorted(children[current], key=str):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort(key=str)
    if len(ordered) != len(materialized):
        raise DagValidationError("operation dependency cycle")
    return tuple(ordered)
