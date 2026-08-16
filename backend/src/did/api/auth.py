from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from did.api.dependencies import (
    ApiProblem,
    CsrfSessionDep,
    ServicesDep,
    oauth_binding_cookie_name,
    session_cookie_name,
)
from did.application.auth.service import AuthenticationError
from did.oauth.discord import DiscordOAuthError
from did.oauth.stores import OAuthStateError
from did.settings import AppEnvironment

router = APIRouter(tags=["auth"])


@router.get("/auth/discord/login")
async def discord_login(
    container: ServicesDep,
    return_to: Annotated[str, Query()] = "/",
) -> RedirectResponse:
    try:
        transaction, url = await container.auth.start(return_to=return_to)
    except OAuthStateError as exc:
        raise ApiProblem(
            status_code=400,
            code="OAUTH_RETURN_PATH_INVALID",
            message_key="errors.auth.returnPath",
        ) from exc
    assert transaction.browser_binding is not None
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        oauth_binding_cookie_name(container.settings),
        transaction.browser_binding,
        max_age=container.settings.oauth_state_ttl_seconds,
        httponly=True,
        secure=container.settings.app_env is AppEnvironment.PRODUCTION,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/auth/discord/callback")
async def discord_callback(
    request: Request,
    container: ServicesDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    binding = request.cookies.get(oauth_binding_cookie_name(container.settings))
    if error is not None:
        if state:
            try:
                await container.auth.state_store.consume(state, binding)
            except OAuthStateError:
                pass
        return _callback_problem(
            request,
            container,
            ApiProblem(
                status_code=400,
                code="OAUTH_PROVIDER_DENIED",
                message_key="errors.auth.providerDenied",
            ),
        )
    if not code or not state:
        return _callback_problem(
            request,
            container,
            ApiProblem(
                status_code=400,
                code="OAUTH_CALLBACK_INVALID",
                message_key="errors.auth.callback",
            ),
        )
    previous = request.cookies.get(session_cookie_name(container.settings))
    try:
        result = await container.auth.callback(
            code=code,
            state=state,
            browser_binding=binding,
            previous_session_id=previous,
        )
    except OAuthStateError:
        return _callback_problem(
            request,
            container,
            ApiProblem(
                status_code=400,
                code="OAUTH_STATE_INVALID",
                message_key="errors.auth.state",
            ),
        )
    except (AuthenticationError, DiscordOAuthError):
        return _callback_problem(
            request,
            container,
            ApiProblem(
                status_code=502,
                code="OAUTH_EXCHANGE_FAILED",
                message_key="errors.auth.exchange",
            ),
        )
    response = RedirectResponse(url=result.return_to, status_code=303)
    _delete_oauth_binding(response, container)
    response.set_cookie(
        session_cookie_name(container.settings),
        result.session.session_id,
        max_age=container.settings.session_idle_ttl_seconds,
        httponly=True,
        secure=container.settings.app_env is AppEnvironment.PRODUCTION,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> Response:
    session_id = request.cookies.get(session_cookie_name(container.settings))
    if session_id:
        await container.auth.logout(session_id)
    response = Response(status_code=204)
    response.delete_cookie(
        session_cookie_name(container.settings),
        path="/",
        secure=container.settings.app_env is AppEnvironment.PRODUCTION,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/api/v1/me/oauth/discord/revoke", status_code=204)
async def revoke_discord(
    session: CsrfSessionDep,
    container: ServicesDep,
) -> Response:
    await container.auth.revoke_discord(session)
    response = Response(status_code=204)
    response.delete_cookie(
        session_cookie_name(container.settings),
        path="/",
        secure=container.settings.app_env is AppEnvironment.PRODUCTION,
        httponly=True,
        samesite="lax",
    )
    return response


def problem_response(problem: ApiProblem, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status_code,
        content={
            "error": {
                "code": problem.code,
                "message_key": problem.message_key,
                "params": {},
                "request_id": request_id,
            }
        },
    )


def _callback_problem(
    request: Request, container: ServicesDep, problem: ApiProblem
) -> JSONResponse:
    response = problem_response(problem, getattr(request.state, "correlation_id", "unknown"))
    _delete_oauth_binding(response, container)
    return response


def _delete_oauth_binding(response: Response, container: ServicesDep) -> None:
    response.delete_cookie(
        oauth_binding_cookie_name(container.settings),
        path="/",
        secure=container.settings.app_env is AppEnvironment.PRODUCTION,
        httponly=True,
        samesite="lax",
    )
