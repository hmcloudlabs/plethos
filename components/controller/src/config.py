import os
from dataclasses import dataclass


_DEFAULT_SUPPORTED_VCLUSTER_VERSIONS = "0.20.0,0.35.0"


@dataclass(frozen=True)
class Config:
    supported_vcluster_versions: tuple[str, ...] = tuple(
        v.strip()
        for v in os.getenv(
            "SUPPORTED_VCLUSTER_VERSIONS", _DEFAULT_SUPPORTED_VCLUSTER_VERSIONS
        ).split(",")
        if v.strip()
    )
    namespace: str = os.getenv("VCLUSTERCLAIMS_NAMESPACE", "plethos-system")
    reconciliation_interval: int = int(os.getenv("RECONCILIATION_INTERVAL", "30"))
    base_domain: str = os.getenv("VCLUSTERS_BASE_DOMAIN", "")
    ingress_namespace: str = os.getenv("VCLUSTERS_INGRESS_NAMESPACE", "ingress-nginx")


config = Config()
