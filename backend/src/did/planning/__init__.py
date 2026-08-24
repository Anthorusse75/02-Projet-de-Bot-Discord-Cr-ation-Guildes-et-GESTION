"""Pure STAGE 05 desired-state and plan domain."""

from did.planning.canonical import canonical_hash, canonical_json
from did.planning.compiler import PlanCompiler
from did.planning.dag import DagValidationError, topological_order, validate_dag
from did.planning.diff import DiffEngine
from did.planning.models import (
    AttemptState,
    CompensationClass,
    DesiredNode,
    DesiredStateGraph,
    DiffAction,
    DiffEntry,
    ExecutionTarget,
    NodePresence,
    OperationState,
    OperationType,
    PlanOperation,
    PlanState,
    RecoveryStrategy,
    ReferenceKind,
    ResourceReference,
    ResourceType,
    RiskLevel,
    VerificationStrategy,
    freeze_json_object,
    thaw_json_object,
)
from did.planning.preflight import (
    DEFAULT_DISCORD_LIMITS,
    DiscordLimits,
    PreflightContext,
    PreflightEngine,
    PreflightResult,
)
from did.planning.risk import ImpactSummary, RiskAssessment, RiskEngine
from did.planning.state import (
    InvalidStateTransition,
    transition_attempt,
    transition_operation,
    transition_plan,
)

__all__ = [
    "DEFAULT_DISCORD_LIMITS",
    "AttemptState",
    "CompensationClass",
    "DagValidationError",
    "DesiredNode",
    "DesiredStateGraph",
    "DiffAction",
    "DiffEngine",
    "DiffEntry",
    "DiscordLimits",
    "ExecutionTarget",
    "ImpactSummary",
    "InvalidStateTransition",
    "NodePresence",
    "OperationState",
    "OperationType",
    "PlanCompiler",
    "PlanOperation",
    "PlanState",
    "PreflightContext",
    "PreflightEngine",
    "PreflightResult",
    "RecoveryStrategy",
    "ReferenceKind",
    "ResourceReference",
    "ResourceType",
    "RiskAssessment",
    "RiskEngine",
    "RiskLevel",
    "VerificationStrategy",
    "canonical_hash",
    "canonical_json",
    "freeze_json_object",
    "thaw_json_object",
    "topological_order",
    "transition_attempt",
    "transition_operation",
    "transition_plan",
    "validate_dag",
]
