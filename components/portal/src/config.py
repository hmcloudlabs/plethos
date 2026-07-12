import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    host: str = os.getenv("PORTAL_HOST", "0.0.0.0")
    port: int = int(os.getenv("PORTAL_PORT", "8000"))
    session_secret: str = os.getenv("PORTAL_SESSION_SECRET", "dev-secret-change-me")

    oidc_issuer: str = os.getenv("OIDC_ISSUER", "http://localhost:9090/realms/vkube-portal")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "vkube-portal")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")
    oidc_scopes: str = os.getenv("OIDC_SCOPES", "openid email profile")

    # Namespace the VClusterClaim CRDs live in. Must match the controller's
    # VCLUSTERCLAIMS_NAMESPACE (see components/controller/src/config.py).
    claims_namespace: str = os.getenv("VCLUSTERCLAIMS_NAMESPACE", "vkube-system")


config = Config()
