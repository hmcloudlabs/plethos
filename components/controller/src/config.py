import os
from dataclasses import dataclass, field
from kubernetes import client

@dataclass(slots=True)
class KubernetesClients:
    core: client.CoreV1Api = field(default_factory=client.CoreV1Api)
    batch: client.BatchV1Api = field(default_factory=client.BatchV1Api)
    apps: client.AppsV1Api = field(default_factory=client.AppsV1Api)
    rbac: client.RbacAuthorizationV1Api = field(default_factory=client.RbacAuthorizationV1Api)
    custom: client.CustomObjectsApi = field(default_factory=client.CustomObjectsApi)

@dataclass(frozen=True)
class Settings:
    vcluster_version: str = "0.19.0"
    namespace: str = os.getenv("VCLUSTERCLAIMS_NAMESPACE", "vkube-system")
    reconciliation_interval: int = int(os.getenv("RECONCILIATION_INTERVAL", "30"))


settings = Settings()
