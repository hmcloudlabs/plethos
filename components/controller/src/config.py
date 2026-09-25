import os
from dataclasses import dataclass

_DEFAULT_SUPPORTED_VCLUSTER_VERSION = "0.35.0"


@dataclass(frozen=True)
class Config:
    supported_vcluster_versions: tuple[str, ...] = tuple(
        v.strip()
        for v in os.getenv(
            "SUPPORTED_VCLUSTER_VERSIONS", _DEFAULT_SUPPORTED_VCLUSTER_VERSION
        ).split(",")
        if v.strip()
    )
    namespace: str = os.getenv("VCLUSTERCLAIMS_NAMESPACE", "plethos-system")
    reconciliation_interval: int = int(os.getenv("RECONCILIATION_INTERVAL", "10800"))
    transitional_reconciliation_interval: int = int(
        os.getenv("TRANSITIONAL_RECONCILIATION_INTERVAL", "10")
    )
    vcluster_api_base_domain: str = os.getenv("VCLUSTER_API_BASE_DOMAIN", "")
    exposed_apps_base_domain: str = os.getenv("EXPOSED_APPS_BASE_DOMAIN", "")

    ingress_namespace: str = os.getenv("INGRESS_NAMESPACE", "ingress-nginx")


config = Config()
