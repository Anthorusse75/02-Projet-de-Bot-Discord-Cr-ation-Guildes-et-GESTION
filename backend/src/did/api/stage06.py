from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from did.api.dependencies import ApiProblem, CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.application.portability import ArtifactKind, MappingRequired
from did.cloning import ArtifactSelection, support_matrix
from did.domain.auth import AuthorizationScope, Capability
from did.portability import ArtifactType, CloneMode, ExplicitMapping, PortableResourceType
from did.portability.artifact import MAX_RAW_FILE_BYTES

router = APIRouter(tags=["stage-06-portability"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: ArtifactType
    category_ids: list[str] = Field(default_factory=list, max_length=1000)
    channel_ids: list[str] = Field(default_factory=list, max_length=1000)
    role_ids: list[str] = Field(default_factory=list, max_length=1000)
    logical_group_id: UUID | None = None

    @field_validator("category_ids", "channel_ids", "role_ids")
    @classmethod
    def snowflakes(cls, values: list[str]) -> list[str]:
        return [str(parse_snowflake(value)) for value in values]

    def domain(self) -> ArtifactSelection:
        return ArtifactSelection(
            self.artifact_type,
            tuple(int(value) for value in self.category_ids),
            tuple(int(value) for value in self.channel_ids),
            tuple(int(value) for value in self.role_ids),
        )


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: SelectionInput
    kind: ArtifactKind = ArtifactKind.EXPORT_BUNDLE
    name: str | None = Field(default=None, min_length=1, max_length=160)


class MappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_logical_ref: str = Field(min_length=1, max_length=256)
    destination_ref: str
    resource_type: PortableResourceType
    confirmed: bool

    @field_validator("destination_ref")
    @classmethod
    def destination_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))

    def domain(self, destination_guild_id: int) -> ExplicitMapping:
        return ExplicitMapping(
            self.source_logical_ref,
            destination_guild_id,
            self.destination_ref,
            self.resource_type,
            self.confirmed,
        )


class CompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    mode: CloneMode = CloneMode.COPY_AS_NEW
    mappings: list[MappingInput] = Field(default_factory=list, max_length=1000)


class CloneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_guild_id: str
    mode: CloneMode = CloneMode.COPY_AS_NEW
    mappings: list[MappingInput] = Field(default_factory=list, max_length=1000)

    @field_validator("destination_guild_id")
    @classmethod
    def destination_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))


class LiveTransferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_guild_id: str
    destination_guild_id: str
    selection: SelectionInput
    mode: CloneMode = CloneMode.COPY_AS_NEW
    mappings: list[MappingInput] = Field(default_factory=list, max_length=1000)
    name: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("source_guild_id", "destination_guild_id")
    @classmethod
    def guild_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))


class TemplateCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    name: str = Field(min_length=1, max_length=160)


class TemplateApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: CloneMode = CloneMode.COPY_AS_NEW
    mappings: list[MappingInput] = Field(default_factory=list, max_length=1000)


def _portable(container: Any) -> Any:
    if container.portability is None or container.portability_repository is None:
        raise ApiProblem(
            status_code=503,
            code="PORTABILITY_NOT_CONFIGURED",
            message_key="errors.portability.notConfigured",
        )
    return container.portability


async def _authorize(guild_id: int, session: Any, container: Any, capability: Capability) -> None:
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=guild_id,
        capability=capability,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )


async def _authorize_destination(guild_id: int, session: Any, container: Any) -> None:
    await _authorize(guild_id, session, container, Capability.PLANS_CREATE)
    await _authorize(guild_id, session, container, Capability.STRUCTURE_WRITE)


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "artifact_type": str(row["artifact_type"]),
        "source_guild_id": (
            str(row["source_guild_id"]) if row.get("source_guild_id") is not None else None
        ),
        "schema_version": str(row["schema_version"]),
        "name": row.get("name"),
        "content_hash": str(row["content_hash"]),
        "content_size_bytes": int(row["content_size_bytes"]),
        "created_at": row["created_at"],
        "expires_at": row.get("expires_at"),
    }


def _transfer(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "source_guild_id": (
            str(row["source_guild_id"]) if row.get("source_guild_id") is not None else None
        ),
        "destination_guild_id": str(row["destination_guild_id"]),
        "portable_artifact_id": str(row["portable_artifact_id"]),
        "artifact_content_hash": str(row["artifact_content_hash"]),
        "destination_plan_id": (
            str(row["destination_plan_id"]) if row.get("destination_plan_id") is not None else None
        ),
        "transfer_mode": str(row["transfer_mode"]),
        "mapping": row.get("mapping_json") or [],
        "report": row.get("report_json"),
        "status": str(row["status"]),
        "error_code": row.get("error_code"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "local_result": row.get("local_result_json"),
        "finalized_at": row.get("finalized_at"),
    }


def _plan(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "guild_id": str(row["guild_id"]),
        "status": str(row["status"]),
        "state_version": int(row["state_version"]),
        "plan_hash": str(row["plan_hash"]),
        "risk_level": str(row["risk_level"]),
        "risk": dict(row["risk_summary"]),
        "impact": dict(row["impact_summary"]),
        "reinforced_confirmation_required": bool(row["confirmation_required"]),
    }


def _mapping_problem(exc: MappingRequired) -> ApiProblem:
    del exc
    return ApiProblem(
        status_code=409,
        code="PORTABLE_MAPPING_REQUIRED",
        message_key="errors.portability.mappingRequired",
    )


async def _compile(
    *,
    body: CompileInput,
    destination: int,
    request: Request,
    idempotency_key: str,
    session: Any,
    container: Any,
) -> dict[str, Any]:
    service = _portable(container)
    try:
        transfer, plan, created = await service.compile_stored(
            actor_user_id=session.discord_user_id,
            artifact_id=body.artifact_id,
            destination_guild_id=destination,
            mode=body.mode,
            explicit_mappings=tuple(item.domain(destination) for item in body.mappings),
            idempotency_key=idempotency_key,
            correlation_id=UUID(str(request.state.correlation_id)),
        )
    except MappingRequired as exc:
        raise _mapping_problem(exc) from exc
    return {"created": created, "transfer": _transfer(transfer), "plan": _plan(plan)}


@router.post("/api/v1/guilds/{guild_id}/exports/portable", status_code=status.HTTP_201_CREATED)
async def export_portable(
    guild_id: str,
    body: ExportInput,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    source = parse_snowflake(guild_id)
    await _authorize(source, session, container, Capability.STRUCTURE_READ)
    row, created = await _portable(container).export_live(
        source_guild_id=source,
        actor_user_id=session.discord_user_id,
        selection=body.selection.domain(),
        kind=body.kind,
        name=body.name,
        idempotency_key=idempotency_key,
        correlation_id=UUID(str(request.state.correlation_id)),
        logical_group_id=body.selection.logical_group_id,
    )
    return {"created": created, "artifact": _metadata(row)}


@router.get("/api/v1/me/portable-artifacts")
async def list_portable_artifacts(
    session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    _portable(container)
    rows = await container.portability_repository.list_artifacts(session.discord_user_id)
    return {"artifacts": [_metadata(row) for row in rows]}


@router.get("/api/v1/me/portable-artifacts/{artifact_id}")
async def get_portable_artifact(
    artifact_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    _portable(container)
    row, _ = await container.portability_repository.get_artifact(
        session.discord_user_id, artifact_id
    )
    return _metadata(row)


@router.delete(
    "/api/v1/me/portable-artifacts/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_portable_artifact(
    artifact_id: UUID, session: CsrfSessionDep, container: ServicesDep
) -> Response:
    _portable(container)
    await container.portability_repository.delete_artifact(session.discord_user_id, artifact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/me/portable-artifacts/{artifact_id}/file")
async def export_portable_file(
    artifact_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> Response:
    raw = await _portable(container).export_file(session.discord_user_id, artifact_id)
    return Response(
        raw,
        media_type="application/vnd.did.portable+json",
        headers={"Content-Disposition": f'attachment; filename="{artifact_id}.did.json"'},
    )


@router.post("/api/v1/me/portable-artifacts/import", status_code=status.HTTP_201_CREATED)
async def import_portable_file(
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
    name: Annotated[str | None, Header(alias="X-Artifact-Name", max_length=160)] = None,
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"application/json", "application/vnd.did.portable+json"}:
        raise ApiProblem(
            status_code=415,
            code="PORTABLE_MEDIA_TYPE_INVALID",
            message_key="errors.portability.mediaType",
        )
    if request.headers.get("content-encoding"):
        raise ApiProblem(
            status_code=415,
            code="PORTABLE_COMPRESSION_FORBIDDEN",
            message_key="errors.portability.compressionForbidden",
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise ApiProblem(
                status_code=400,
                code="PORTABLE_CONTENT_LENGTH_INVALID",
                message_key="errors.portability.contentLength",
            ) from exc
        if declared_length < 0 or declared_length > MAX_RAW_FILE_BYTES:
            raise ApiProblem(
                status_code=413,
                code="PORTABLE_FILE_TOO_LARGE",
                message_key="errors.portability.fileTooLarge",
            )
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_RAW_FILE_BYTES:
            raise ApiProblem(
                status_code=413,
                code="PORTABLE_FILE_TOO_LARGE",
                message_key="errors.portability.fileTooLarge",
            )
    try:
        row, created = await _portable(container).import_file(
            actor_user_id=session.discord_user_id,
            raw=bytes(raw),
            name=name,
            idempotency_key=idempotency_key,
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="PORTABLE_FILE_INVALID",
            message_key="errors.portability.fileInvalid",
        ) from exc
    return {"created": created, "artifact": _metadata(row)}


@router.post("/api/v1/me/portable-artifacts/{artifact_id}/clone")
async def clone_portable_artifact(
    artifact_id: UUID,
    body: CloneInput,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    destination = int(body.destination_guild_id)
    await _authorize_destination(destination, session, container)
    compile_body = CompileInput(artifact_id=artifact_id, mode=body.mode, mappings=body.mappings)
    return await _compile(
        body=compile_body,
        destination=destination,
        request=request,
        idempotency_key=idempotency_key,
        session=session,
        container=container,
    )


@router.post("/api/v1/guilds/{guild_id}/imports/plan")
async def import_plan(
    guild_id: str,
    body: CompileInput,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    destination = parse_snowflake(guild_id)
    await _authorize_destination(destination, session, container)
    return await _compile(
        body=body,
        destination=destination,
        request=request,
        idempotency_key=idempotency_key,
        session=session,
        container=container,
    )


@router.post("/api/v1/guilds/{guild_id}/imports/preview")
async def import_preview(
    guild_id: str,
    body: CompileInput,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    destination = parse_snowflake(guild_id)
    await _authorize_destination(destination, session, container)
    mappings = await _portable(container).preview_stored(
        actor_user_id=session.discord_user_id,
        artifact_id=body.artifact_id,
        destination_guild_id=destination,
        mode=body.mode,
        explicit_mappings=tuple(item.domain(destination) for item in body.mappings),
    )
    return {"artifact_id": str(body.artifact_id), "mappings": mappings}


@router.post("/api/v1/transfers", status_code=status.HTTP_201_CREATED)
async def create_live_transfer(
    body: LiveTransferInput,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    source = int(body.source_guild_id)
    destination = int(body.destination_guild_id)
    await _authorize(source, session, container, Capability.STRUCTURE_READ)
    artifact, _ = await _portable(container).export_live(
        source_guild_id=source,
        actor_user_id=session.discord_user_id,
        selection=body.selection.domain(),
        kind=ArtifactKind.EXPORT_BUNDLE,
        name=body.name,
        idempotency_key=f"{idempotency_key}:export"[:160],
        correlation_id=UUID(str(request.state.correlation_id)),
        logical_group_id=body.selection.logical_group_id,
    )
    await _authorize_destination(destination, session, container)
    result = await _compile(
        body=CompileInput(
            artifact_id=UUID(str(artifact["id"])),
            mode=body.mode,
            mappings=body.mappings,
        ),
        destination=destination,
        request=request,
        idempotency_key=f"{idempotency_key}:compile"[:160],
        session=session,
        container=container,
    )
    if result["created"]:
        transfer = result["transfer"]
        await container.portability_repository.audit_boundary(
            guild_id=source,
            actor_user_id=session.discord_user_id,
            transfer_id=UUID(transfer["id"]),
            event_type="CROSS_GUILD_SOURCE_EXPORTED",
            artifact_hash=transfer["artifact_content_hash"],
            correlation_id=UUID(str(request.state.correlation_id)),
        )
    return result


@router.get("/api/v1/transfers/{transfer_id}")
async def get_transfer(
    transfer_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    _portable(container)
    row = await container.portability_repository.get_transfer(session.discord_user_id, transfer_id)
    await _authorize_destination(int(row["destination_guild_id"]), session, container)
    return _transfer(row)


@router.post("/api/v1/transfers/{transfer_id}/finalize")
async def finalize_transfer(
    transfer_id: UUID,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    service = _portable(container)
    row = await container.portability_repository.get_transfer(session.discord_user_id, transfer_id)
    await _authorize_destination(int(row["destination_guild_id"]), session, container)
    try:
        finalized = await service.finalize_transfer(
            actor_user_id=session.discord_user_id,
            transfer_id=transfer_id,
            correlation_id=UUID(str(request.state.correlation_id)),
        )
    except ValueError as exc:
        raise ApiProblem(
            status_code=409,
            code="PORTABLE_FINALIZATION_NOT_READY",
            message_key="errors.portability.finalizationNotReady",
        ) from exc
    return _transfer(finalized)


@router.get("/api/v1/portability/support-matrix")
async def portability_support_matrix(session: CurrentSessionDep) -> dict[str, Any]:
    del session
    return support_matrix()


@router.get("/api/v1/guilds/{guild_id}/templates")
async def list_templates(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.TEMPLATES_READ)
    _portable(container)
    rows = await container.portability_repository.list_templates(parsed, session.discord_user_id)
    return {"templates": [_template(row) for row in rows]}


@router.post("/api/v1/guilds/{guild_id}/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    guild_id: str,
    body: TemplateCreateInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.TEMPLATES_WRITE)
    row = await _portable(container).create_template(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        artifact_id=body.artifact_id,
        name=body.name,
        correlation_id=UUID(str(request.state.correlation_id)),
    )
    return _template(row)


@router.post("/api/v1/guilds/{guild_id}/templates/{template_id}/apply")
async def apply_template(
    guild_id: str,
    template_id: UUID,
    body: TemplateApplyInput,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    destination = parse_snowflake(guild_id)
    await _authorize(destination, session, container, Capability.TEMPLATES_READ)
    await _authorize_destination(destination, session, container)
    service = _portable(container)
    try:
        transfer, plan, created = await service.compile_template(
            guild_id=destination,
            actor_user_id=session.discord_user_id,
            template_id=template_id,
            mode=body.mode,
            explicit_mappings=tuple(item.domain(destination) for item in body.mappings),
            idempotency_key=idempotency_key,
            correlation_id=UUID(str(request.state.correlation_id)),
        )
    except MappingRequired as exc:
        raise _mapping_problem(exc) from exc
    return {
        "created": created,
        "transfer": _transfer(transfer),
        "plan": _plan(plan),
    }


def _template(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "guild_id": str(row["guild_id"]),
        "name": str(row["name"]),
        "artifact_type": str(row["artifact_type"]),
        "schema_version": str(row["schema_version"]),
        "content_hash": str(row["content_hash"]),
        "version": int(row["version"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
