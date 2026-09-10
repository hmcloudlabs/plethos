import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    host: str = os.getenv("PORTAL_HOST", "0.0.0.0")
    port: int = int(os.getenv("PORTAL_PORT", "8000"))

    session_secret: str = os.getenv("PORTAL_SESSION_SECRET", "dev-secret-change-me")
    csrf_token_secret: str = os.getenv("CSRF_TOKEN_SECRET", "dev-secret-change-me")

    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_dir: str = os.getenv("LOG_DIR", "")

    oidc_issuer: str = os.getenv("OIDC_ISSUER", "http://localhost:9090/realms/plethos-portal")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "plethos-portal")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")
    oidc_scopes: str = os.getenv("OIDC_SCOPES", "openid email profile")

    # Namespace the VClusterClaim CRDs live in. Must match the controller's
    # VCLUSTERCLAIMS_NAMESPACE (see components/controller/src/config.py).
    claims_namespace: str = os.getenv("VCLUSTERCLAIMS_NAMESPACE", "plethos-system")

    # Domain each vCluster's public host is built from. Must match the controller's
    # VCLUSTERS_BASE_DOMAIN (see components/controller/src/config.py).
    vclusters_base_domain: str = os.getenv("VCLUSTERS_BASE_DOMAIN", "")

    cache_ttl_seconds: float = float(os.getenv("CACHE_TTL_SECONDS", "3.0"))

    support_email: str = os.getenv("SUPPORT_EMAIL", "")
    portal_base_url: str = os.getenv("PORTAL_BASE_URL", "http://localhost:8000")

    expiry_period_days: float = float(os.getenv("EXPIRY_PERIOD_DAYS", "90"))
    grace_period_days: float = float(os.getenv("GRACE_PERIOD_DAYS", "60"))
    warning_lead_days: float = float(os.getenv("WARNING_LEAD_DAYS", "7"))

    # How long signed links (member invites, keep-alive) stay valid.
    token_max_age_seconds: int = int(os.getenv("TOKEN_MAX_AGE_SECONDS", str(7 * 24 * 60 * 60)))

    smtp_host: str = os.getenv("SMTP_HOST", "localhost")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_address: str = os.getenv("SMTP_FROM_ADDRESS", "plethos@example.com")

    # vCluster versions the controller accepts (the portal always provisions the newest of these)
    supported_vcluster_versions: tuple[str, ...] = tuple(
        v.strip()
        for v in os.getenv("SUPPORTED_VCLUSTER_VERSIONS", "0.35.0").split(",")
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
