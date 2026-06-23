import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("PORTAL_HOST", "0.0.0.0")
    port: int = int(os.getenv("PORTAL_PORT", "8000"))
    session_secret: str = os.getenv("PORTAL_SESSION_SECRET", "dev-secret-change-me")

    oidc_issuer: str = os.getenv("OIDC_ISSUER", "http://localhost:8080/realms/vkube")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "vkube-portal")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")


settings = Settings()
