import re

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from did.api.dependencies import CsrfSessionDep, CurrentSessionDep, ServicesDep

router = APIRouter(prefix="/api/v1/me", tags=["me"])
LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ui_locale_override_code: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)


@router.get("")
async def me(
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    user = await container.repository.get_user(session.discord_user_id)
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "discord_user_id": str(user.discord_user_id),
            "username": user.username,
            "global_name": user.global_name,
            "avatar_hash": user.avatar_hash,
        },
        "active_guild_id": None
        if session.active_guild_id is None
        else str(session.active_guild_id),
        "csrf_token": session.csrf_token,
        "policy_version": session.policy_version,
    }


@router.get("/preferences")
async def preferences(
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, str | None]:
    locale, timezone = await container.repository.get_preferences(session.discord_user_id)
    return {"ui_locale_override_code": locale, "timezone": timezone}


@router.patch("/preferences")
async def update_preferences(
    body: PreferenceUpdate,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, str | None]:
    if body.ui_locale_override_code is not None and not LOCALE_PATTERN.fullmatch(
        body.ui_locale_override_code
    ):
        from did.api.dependencies import ApiProblem

        raise ApiProblem(
            status_code=422,
            code="LOCALE_INVALID",
            message_key="errors.preferences.locale",
        )
    await container.repository.save_preferences(
        session.discord_user_id,
        locale=body.ui_locale_override_code,
        timezone=body.timezone,
    )
    return body.model_dump()
