from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid5

from did.domain.read_model import GuildSnapshot
from did.planning.canonical import canonical_hash
from did.planning.dag import validate_dag
from did.planning.diff import DiffEngine
from did.planning.models import (
    CompensationClass,
    DesiredNode,
    DesiredStateGraph,
    DiffAction,
    DiffEntry,
    OperationType,
    PlanOperation,
    RecoveryStrategy,
    ReferenceKind,
    ResourceType,
    RiskLevel,
    VerificationStrategy,
    freeze_json_object,
    thaw_json_object,
)

PLAN_OPERATION_NAMESPACE = UUID("fcb7d5ee-74b5-4e49-ac83-e8078df5340e")


class PlanCompiler:
    version = "did-plan-compiler-v1"

    def __init__(self, diff_engine: DiffEngine | None = None) -> None:
        self._diff = diff_engine or DiffEngine()

    def compile(
        self, observed: GuildSnapshot, desired: DesiredStateGraph, *, plan_id: UUID
    ) -> tuple[PlanOperation, ...]:
        graph_hash = canonical_hash(desired)
        entries = self._diff.compare(observed, desired)
        operations: list[PlanOperation] = []
        role_moves: list[DiffEntry] = []
        channel_moves: list[DiffEntry] = []
        last_for_node: dict[str, UUID] = {}
        for entry in entries:
            if entry.action is DiffAction.NO_CHANGE:
                continue
            move_fields = {"position", "parent_id"}.intersection(entry.changed_fields)
            non_move_fields = set(entry.changed_fields) - move_fields
            if move_fields:
                if entry.node.resource_type is ResourceType.ROLE:
                    role_moves.append(entry)
                elif entry.node.resource_type in {ResourceType.CATEGORY, ResourceType.CHANNEL}:
                    channel_moves.append(entry)
            if entry.action is DiffAction.MOVE_OR_REORDER and not non_move_fields:
                continue
            operation = self._compile_entry(
                plan_id, graph_hash, observed, desired, entry, non_move_fields
            )
            operations.append(operation)
            last_for_node[entry.node.logical_key] = operation.operation_id
        if role_moves:
            operation = self._bulk_reorder(
                plan_id, graph_hash, observed, desired, role_moves, roles=True
            )
            operation = replace(
                operation,
                predecessors=tuple(
                    sorted(
                        {
                            last_for_node[entry.node.logical_key]
                            for entry in role_moves
                            if entry.node.logical_key in last_for_node
                        },
                        key=str,
                    )
                ),
            )
            operations.append(operation)
        position_only = [
            entry for entry in channel_moves if "parent_id" not in entry.changed_fields
        ]
        parent_moves = [entry for entry in channel_moves if "parent_id" in entry.changed_fields]
        channel_batches = ([position_only] if position_only else []) + [
            [entry] for entry in sorted(parent_moves, key=lambda item: item.node.logical_key)
        ]
        for batch_index, channel_batch in enumerate(channel_batches):
            # Discord currently accepts at most one parent_id change per bulk request.
            operation = self._bulk_reorder(
                plan_id,
                graph_hash,
                observed,
                desired,
                channel_batch,
                roles=False,
                key_suffix=str(batch_index),
            )
            operation = replace(
                operation,
                predecessors=tuple(
                    sorted(
                        {
                            last_for_node[entry.node.logical_key]
                            for entry in channel_batch
                            if entry.node.logical_key in last_for_node
                        },
                        key=str,
                    )
                ),
            )
            operations.append(operation)
        operations = self._bind_symbol_dependencies(desired, operations)
        operations = self._bind_category_delete_dependencies(desired, operations)
        ordered = tuple(sorted(operations, key=lambda operation: str(operation.operation_id)))
        validate_dag(ordered)
        return ordered

    def _compile_entry(
        self,
        plan_id: UUID,
        graph_hash: str,
        observed: GuildSnapshot,
        desired: DesiredStateGraph,
        entry: DiffEntry,
        non_move_fields: set[str],
    ) -> PlanOperation:
        node = entry.node
        operation_type = self._operation_type(entry)
        payload = self._payload(desired, node)
        payload.pop("current_assigned", None)
        if non_move_fields:
            identity_fields = {
                key
                for key in payload
                if key == "id"
                or key == "target_type"
                or key.endswith("_id")
                or key.endswith("_symbol")
            }
            payload = {
                key: value
                for key, value in payload.items()
                if key in non_move_fields or key in identity_fields
            }
        operation_id = self._operation_id(
            plan_id, graph_hash, node.logical_key, operation_type.value
        )
        is_create = operation_type in {OperationType.CREATE_ROLE, OperationType.CREATE_CHANNEL}
        is_delete = operation_type in {OperationType.DELETE_ROLE, OperationType.DELETE_CHANNEL}
        capability = (
            "MANAGE_ROLES"
            if node.resource_type
            in {ResourceType.ROLE, ResourceType.OVERWRITE, ResourceType.MEMBER_ROLE}
            else "MANAGE_CHANNELS"
        )
        if node.resource_type is ResourceType.OVERWRITE:
            capability = "MANAGE_ROLES"
        return PlanOperation(
            operation_id,
            operation_type,
            node.resource_type,
            node.logical_key,
            freeze_json_object(payload),
            entry.before,
            (capability,),
            (
                CompensationClass.RECREATABLE_NOT_RESTORABLE
                if is_delete
                else CompensationClass.REVERSIBLE
            ),
            RiskLevel.HIGH if is_delete else RiskLevel.LOW,
            (
                VerificationStrategy.TARGETED_LIST_AND_MATCH
                if is_create
                else VerificationStrategy.ABSENCE_WITH_OBSERVABILITY
                if is_delete
                else VerificationStrategy.TARGETED_GET
            ),
            (
                RecoveryStrategy.CREATE_RECONCILE
                if is_create
                else RecoveryStrategy.DELETE_PROVE_ABSENCE
                if is_delete
                else RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED
            ),
            self._gateway_events(operation_type),
            preconditions=freeze_json_object(
                self._preconditions(observed, operation_type, node.resource_type, payload, entry)
            ),
            produces_symbol=node.symbol if is_create else None,
            consumes_symbols=self._consumed_symbols(desired, node),
        )

    def _bulk_reorder(
        self,
        plan_id: UUID,
        graph_hash: str,
        observed: GuildSnapshot,
        desired: DesiredStateGraph,
        entries: list[DiffEntry],
        *,
        roles: bool,
        key_suffix: str | None = None,
    ) -> PlanOperation:
        operation_type = (
            OperationType.REORDER_ROLES if roles else OperationType.MOVE_OR_REORDER_CHANNELS
        )
        items: list[dict[str, object]] = []
        before_items: list[dict[str, object]] = []
        consumed: set[str] = set()
        for entry in sorted(entries, key=lambda item: item.node.logical_key):
            payload = self._payload(desired, entry.node)
            item: dict[str, object] = {"resource_ref": entry.node.logical_key}
            for key in ("id", "position", "parent_id", "lock_permissions"):
                if key in payload:
                    item[key] = payload[key]
            if entry.node.discord_id is not None:
                item["id"] = entry.node.discord_id
            consumed.update(self._consumed_symbols(desired, entry.node))
            if entry.node.symbol:
                consumed.add(entry.node.symbol)
            items.append(item)
            before = thaw_json_object(entry.before)
            before_items.append(
                {key: before[key] for key in ("id", "position", "parent_id") if key in before}
            )
        expected_position_segment: list[dict[str, object]] | None = None
        expected_before_segment: list[dict[str, object]] | None = None
        if roles:
            (
                items,
                before_items,
                expected_position_segment,
                expected_before_segment,
            ) = self._expand_role_reorder(observed, entries)
        key = "bulk:roles" if roles else f"bulk:channels:{key_suffix or '0'}"
        desired_payload: dict[str, object] = {"items": items}
        before_payload: dict[str, object] = {"items": before_items}
        precondition_items = before_items
        if expected_position_segment is not None and expected_before_segment is not None:
            desired_payload["expected_position_segment"] = expected_position_segment
            before_payload["expected_position_segment"] = expected_before_segment
            precondition_items = expected_before_segment
        return PlanOperation(
            self._operation_id(plan_id, graph_hash, key, operation_type.value),
            operation_type,
            ResourceType.ROLE if roles else ResourceType.CHANNEL,
            key,
            freeze_json_object(desired_payload),
            freeze_json_object(before_payload),
            ("MANAGE_ROLES" if roles else "MANAGE_CHANNELS",),
            CompensationClass.REVERSIBLE,
            RiskLevel.MEDIUM,
            VerificationStrategy.TARGETED_LIST_AND_MATCH,
            RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
            ("GUILD_ROLE_UPDATE",) if roles else ("CHANNEL_UPDATE",),
            preconditions=freeze_json_object(
                {
                    "schema_version": "did-operation-precondition-v1",
                    "mode": "MATCH_BEFORE",
                    "resource_type": "ROLE" if roles else "CHANNEL",
                    "before": {"items": precondition_items},
                    "before_fingerprint": canonical_hash({"items": precondition_items}),
                    "coverage_complete": (
                        observed.roles_complete if roles else observed.channels_complete
                    ),
                }
            ),
            consumes_symbols=tuple(sorted(consumed)),
        )

    def _expand_role_reorder(
        self,
        observed: GuildSnapshot,
        entries: list[DiffEntry],
    ) -> tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
    ]:
        """Separate explicit REST targets from the predicted shifted segment."""
        original = {role.role_id: role.position for role in observed.roles}
        positions = dict(original)
        requested_refs = {
            entry.node.discord_id: entry.node.logical_key
            for entry in entries
            if entry.node.discord_id is not None
        }
        for entry in sorted(entries, key=lambda item: item.node.logical_key):
            role_id = entry.node.discord_id
            target = thaw_json_object(entry.node.properties).get("position")
            if role_id is None or target is None or role_id not in positions:
                continue
            current = positions[role_id]
            target_position = int(target)
            for shifted_id, shifted_position in tuple(positions.items()):
                if shifted_id == role_id:
                    continue
                if current < target_position and current < shifted_position <= target_position:
                    positions[shifted_id] = shifted_position - 1
                elif target_position < current and target_position <= shifted_position < current:
                    positions[shifted_id] = shifted_position + 1
            positions[role_id] = target_position

        requested_items: list[dict[str, object]] = []
        requested_before: list[dict[str, object]] = []
        for entry in sorted(entries, key=lambda item: item.node.logical_key):
            role_id = entry.node.discord_id
            target = thaw_json_object(entry.node.properties).get("position")
            if role_id is None or target is None or role_id not in original:
                continue
            target_position = int(target)
            # With a single explicit role in Discord's bulk endpoint, removing
            # a role below its destination shifts the original coordinate down
            # by one before insertion. Keep implicit roles out of the REST
            # payload and compensate that coordinate here; verification still
            # uses the desired final position segment below.
            rest_position = (
                target_position + 1 if original[role_id] < target_position else target_position
            )
            requested_items.append(
                {
                    "resource_ref": entry.node.logical_key,
                    "id": role_id,
                    "position": rest_position,
                }
            )
            requested_before.append({"id": role_id, "position": original[role_id]})

        changed = sorted(
            (role_id for role_id, position in positions.items() if position != original[role_id]),
            key=lambda role_id: (positions[role_id], role_id),
        )
        expected_items: list[dict[str, object]] = [
            {
                "resource_ref": requested_refs.get(role_id, f"discord.role.{role_id}"),
                "id": role_id,
                "position": positions[role_id],
            }
            for role_id in changed
        ]
        expected_before: list[dict[str, object]] = [
            {"id": role_id, "position": original[role_id]} for role_id in changed
        ]
        return requested_items, requested_before, expected_items, expected_before

    def _bind_symbol_dependencies(
        self, desired: DesiredStateGraph, operations: list[PlanOperation]
    ) -> list[PlanOperation]:
        del desired
        producers = {
            operation.produces_symbol: operation.operation_id
            for operation in operations
            if operation.produces_symbol is not None
        }
        result = []
        for operation in operations:
            predecessors = set(operation.predecessors)
            for symbol in operation.consumes_symbols:
                producer = producers.get(symbol)
                if producer is not None and producer != operation.operation_id:
                    predecessors.add(producer)
            result.append(replace(operation, predecessors=tuple(sorted(predecessors, key=str))))
        return result

    def _bind_category_delete_dependencies(
        self, desired: DesiredStateGraph, operations: list[PlanOperation]
    ) -> list[PlanOperation]:
        by_ref = {operation.resource_ref: operation for operation in operations}
        result: list[PlanOperation] = []
        for operation in operations:
            if (
                operation.operation_type is OperationType.DELETE_CHANNEL
                and operation.resource_type is ResourceType.CATEGORY
            ):
                predecessors = set(operation.predecessors)
                for node in desired.nodes:
                    parent = node.relation("parent")
                    if parent is None:
                        continue
                    references_category = (
                        parent.kind is ReferenceKind.LOGICAL
                        and parent.value == operation.resource_ref
                    )
                    if references_category and node.logical_key in by_ref:
                        predecessors.add(by_ref[node.logical_key].operation_id)
                operation = replace(operation, predecessors=tuple(sorted(predecessors, key=str)))
            result.append(operation)
        return result

    @staticmethod
    def _operation_type(entry: DiffEntry) -> OperationType:
        resource = entry.node.resource_type
        if resource is ResourceType.ROLE:
            return {
                DiffAction.CREATE: OperationType.CREATE_ROLE,
                DiffAction.UPDATE: OperationType.UPDATE_ROLE,
                DiffAction.DELETE: OperationType.DELETE_ROLE,
            }[entry.action]
        if resource in {ResourceType.CATEGORY, ResourceType.CHANNEL}:
            return {
                DiffAction.CREATE: OperationType.CREATE_CHANNEL,
                DiffAction.UPDATE: OperationType.UPDATE_CHANNEL,
                DiffAction.DELETE: OperationType.DELETE_CHANNEL,
            }[entry.action]
        if resource is ResourceType.OVERWRITE:
            return (
                OperationType.DELETE_OVERWRITE
                if entry.action is DiffAction.DELETE
                else OperationType.UPSERT_OVERWRITE
            )
        if resource is ResourceType.MEMBER_ROLE:
            return (
                OperationType.ADD_MEMBER_ROLE
                if bool(entry.node.property_map().get("assigned", False))
                else OperationType.REMOVE_MEMBER_ROLE
            )
        raise ValueError(f"unsupported diff resource/action: {resource}/{entry.action}")

    @staticmethod
    def _payload(desired: DesiredStateGraph, node: DesiredNode) -> dict[str, object]:
        payload: dict[str, object] = thaw_json_object(node.properties)
        if node.discord_id is not None:
            payload["id"] = node.discord_id
        for name, reference in node.relations:
            if reference.kind is ReferenceKind.DISCORD_ID:
                payload[f"{name}_id"] = int(reference.value)
            elif reference.kind is ReferenceKind.LOGICAL:
                target = desired.node(reference.value)
                payload[f"{name}_id"] = target.discord_id if target else None
                if target and target.symbol:
                    payload[f"{name}_symbol"] = target.symbol
            else:
                payload[f"{name}_symbol"] = reference.value
        if node.resource_type is ResourceType.CATEGORY:
            payload["type"] = 4
        return payload

    @staticmethod
    def _consumed_symbols(desired: DesiredStateGraph, node: DesiredNode) -> tuple[str, ...]:
        symbols: set[str] = set()
        for _, reference in node.relations:
            if reference.kind is ReferenceKind.SYMBOL:
                symbols.add(reference.value)
            elif reference.kind is ReferenceKind.LOGICAL:
                target = desired.node(reference.value)
                if target is not None and target.symbol is not None:
                    symbols.add(target.symbol)
        return tuple(sorted(symbols))

    @staticmethod
    def _gateway_events(operation_type: OperationType) -> tuple[str, ...]:
        if operation_type is OperationType.CREATE_ROLE:
            return ("GUILD_ROLE_CREATE",)
        if operation_type is OperationType.DELETE_ROLE:
            return ("GUILD_ROLE_DELETE",)
        if operation_type in {OperationType.UPDATE_ROLE, OperationType.REORDER_ROLES}:
            return ("GUILD_ROLE_UPDATE",)
        if operation_type in {OperationType.ADD_MEMBER_ROLE, OperationType.REMOVE_MEMBER_ROLE}:
            return ("GUILD_MEMBER_UPDATE",)
        if operation_type is OperationType.CREATE_CHANNEL:
            return ("CHANNEL_CREATE",)
        if operation_type is OperationType.DELETE_CHANNEL:
            return ("CHANNEL_DELETE", "CHANNEL_UPDATE")
        return ("CHANNEL_UPDATE",)

    @staticmethod
    def _operation_id(
        plan_id: UUID, graph_hash: str, resource_ref: str, operation_type: str
    ) -> UUID:
        return uuid5(
            PLAN_OPERATION_NAMESPACE,
            f"{plan_id}:{graph_hash}:{resource_ref}:{operation_type}",
        )

    @staticmethod
    def _preconditions(
        observed: GuildSnapshot,
        operation_type: OperationType,
        resource_type: ResourceType,
        payload: dict[str, object],
        entry: DiffEntry,
    ) -> dict[str, object]:
        before = thaw_json_object(entry.before)
        is_create = operation_type in {
            OperationType.CREATE_ROLE,
            OperationType.CREATE_CHANNEL,
        }
        return {
            "schema_version": "did-operation-precondition-v1",
            "mode": "ABSENT_OR_UNCHANGED" if is_create else "MATCH_BEFORE",
            "resource_type": resource_type.value,
            "resource_id": payload.get("id"),
            "identity": {
                key: payload[key]
                for key in ("name", "type", "channel_id", "subject_id", "target_id", "target_type")
                if key in payload
            },
            "before": before,
            "before_fingerprint": canonical_hash(before),
            "coverage_complete": (
                observed.roles_complete
                if resource_type in {ResourceType.ROLE, ResourceType.MEMBER_ROLE}
                else observed.channels_complete
            ),
        }
