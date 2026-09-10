"""
OIDC/SSO wiring for the portal.

The portal is IdP-agnostic: it speaks standard OpenID Connect and configures
itself entirely from the issuer's discovery document, so any compliant provider
(Keycloak, Auth0, Entra ID, Dex, Google, ...) works by pointing `OIDC_ISSUER`
at it. We rely only on standard OIDC claims (`sub`, `email`, `name`); `sub` is
the stable identifier used to scope a user's VClusterClaims. After login those
claims are kept in the signed session cookie.
"""

from dataclasses import dataclass

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends
from starlette.requests import Request

from config import config
from kube.settings_service import SettingsService


SSO_PROVIDER = "sso"

oauth = OAuth()
oauth.register(
    name=SSO_PROVIDER,
    client_id=config.oidc_client_id,
    client_secret=config.oidc_client_secret or None,
    server_metadata_url=f"{config.oidc_issuer}/.well-known/openid-configuration",
    client_kwargs={
        "scope": config.oidc_scopes,
        "code_challenge_method": "S256",  # PKCE
    },
)


def sso_client():
    return oauth.create_client(SSO_PROVIDER)


_SESSION_KEY = "user"


@dataclass(frozen=True)
class User:
    sub: str
    email: str
    name: str

    @classmethod
    def from_oidc_claims(cls, oidc_claims: dict) -> "User":
        return cls(
            sub=oidc_claims["sub"],
            email=oidc_claims.get("email", ""),
            name=oidc_claims.get("name")
            or oidc_claims.get("preferred_username")
            or oidc_claims.get("email", ""),
        )

    def to_session(self) -> dict:
        return {"sub": self.sub, "email": self.email, "name": self.name}

    def is_admin(self, settings_service: SettingsService | None = None) -> bool:
        return (settings_service or SettingsService()).is_admin(self.email)


class NotAuthenticatedError(Exception):
    """
    Raised by `require_user` when there is no logged-in user.
    """


class NotAuthorizedError(Exception):
    """
    Raised by `require_admin` when a logged-in user is not an admin.
    """


def set_session_user(request: Request, user: User) -> None:
    request.session[_SESSION_KEY] = user.to_session()


def clear_session_user(request: Request) -> None:
    request.session.pop(_SESSION_KEY, None)


def get_session_user(request: Request) -> User | None:
    data = request.session.get(_SESSION_KEY)
    if not data:
        return None

    return User(
        sub=data["sub"],
        email=data.get("email", ""),
        name=data.get("name", ""),
    )


def require_user(request: Request) -> User:
    """FastAPI dependency which returns the logged-in user or triggers a login redirect."""

    user = get_session_user(request)
    if user is None:
        raise NotAuthenticatedError()

    return user


def get_settings_service() -> SettingsService:
    return SettingsService()


def require_admin(
    request: Request, settings_service: SettingsService = Depends(get_settings_service)
) -> User:
    """FastAPI dependency: the logged-in user, but only if they're an admin."""

    user = require_user(request)
    if not user.is_admin(settings_service):
        raise NotAuthorizedError()

    return user


def add_csrf_token(request: Request):
    return {"csrf_token": request.cookies.get("csrftoken", None)}