import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from did.application.auth.service import AuthorizationService, AuthService
from did.application.installations.service import InstallationService
from did.infrastructure.auth_repository import AuthRepository
from did.oauth.stores import RedisSessionStore, SessionData
from did.settings import AppEnvironment, Settings


class ApiProblem(RuntimeError):
    def __init__(self, *, status_code: int, code: str, message_key: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message_key = message_key
        super().__init__(code)


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    repository: AuthRepository
    auth: AuthService
    authorization: AuthorizationService
    installations: InstallationService
    sessions: RedisSessionStore


def services(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "services", None)
    if not isinstance(container, ServiceContainer):
        raise ApiProblem(
            status_code=503,
            code="AUTH_NOT_CONFIGURED",
            message_key="errors.auth.notConfigured",
        )
    return container


def session_cookie_name(settings: Settings) -> str:
    if settings.app_env is AppEnvironment.PRODUCTION:
        return "__Host-did_session"
    return "did_session"


ServicesDep = Annotated[ServiceContainer, Depends(services)]


async def current_session(request: Request, container: ServicesDep) -> SessionData:
    session = await container.sessions.load(
        request.cookies.get(session_cookie_name(container.settings))
    )
    if session is None:
        raise ApiProblem(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message_key="errors.auth.required",
        )
    return session


CurrentSessionDep = Annotated[SessionData, Depends(current_session)]


async def csrf_session(
    request: Request,
    session: CurrentSessionDep,
) -> SessionData:
    supplied = request.headers.get("X-CSRF-Token")
    if supplied is None or not secrets_compare(supplied, session.csrf_token):
        raise ApiProblem(
            status_code=403,
            code="CSRF_INVALID",
            message_key="errors.auth.csrf",
        )
    return session


CsrfSessionDep = Annotated[SessionData, Depends(csrf_session)]


def secrets_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
