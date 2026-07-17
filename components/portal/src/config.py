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

    # Emails (lowercased, comma seperated) that get admin access.
    # TODO: Move to ConfigMap that also carries per-user vcluster quotas.
    admin_emails: tuple[str, ...] = tuple(
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "").split(",")
        if e.strip()
    )

    # vCluster versions the controller accepts (its SUPPORTED_VCLUSTER_VERSIONS).
    # The portal always provisions the newest of these; it isn't user-selectable.
    supported_vcluster_versions: tuple[str, ...] = tuple(
        v.strip()
        for v in os.getenv("SUPPORTED_VCLUSTER_VERSIONS", "0.19.0,0.35.0").split(",")
        if v.strip()
    )

    @property
    def latest_vcluster_version(self) -> str:
        """Newest supported version (semver-ordered), used for every new cluster."""
        return max(
            self.supported_vcluster_versions,
            key=lambda v: tuple(int(part) for part in v.split(".")),
        )


config = Config()
