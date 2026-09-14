from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
import logging
import kopf
from kubernetes import client


@dataclass(slots=True)
class KubernetesClients:
    core: client.CoreV1Api = field(default_factory=client.CoreV1Api)
    batch: client.BatchV1Api = field(default_factory=client.BatchV1Api)
    apps: client.AppsV1Api = field(default_factory=client.AppsV1Api)
    rbac: client.RbacAuthorizationV1Api = field(default_factory=client.RbacAuthorizationV1Api)
    custom: client.CustomObjectsApi = field(default_factory=client.CustomObjectsApi)
    networking: client.NetworkingV1Api = field(default_factory=client.NetworkingV1Api)


@dataclass(frozen=True, slots=True)
class VClusterNames:
    name: str

    @property
    def namespace(self) -> str:
        return f"vcluster-{self.name}"

    @property
    def vcluster(self) -> str:
        return self.name

    @property
    def service_account(self) -> str:
        return "helm-installer"

    @property
    def installer_role_binding(self) -> str:
        return "helm-installer-rb"

    @property
    def install_job(self) -> str:
        return f"helm-install-{self.name}"

    @property
    def uninstall_job(self) -> str:
        return f"helm-uninstall-{self.name}"


@dataclass(slots=True)
class ReconciliationContext:
    claim_name: str
    spec: kopf.Spec
    meta: kopf.Meta
    patch: kopf.Patch
    logger: logging.Logger
    status: Mapping[str, Any] = field(default_factory=dict)
    clients: KubernetesClients = field(default_factory=KubernetesClients)
    names: VClusterNames = field(init=False)

    def __post_init__(self):
        self.names = VClusterNames(self.claim_name)

    @property
    def generation(self) -> int:
        return self.meta["generation"]


@dataclass(slots=True)
class DeletionContext:
    claim_name: str
    patch: kopf.Patch
    logger: logging.Logger
    clients: KubernetesClients = field(default_factory=KubernetesClients)
    names: VClusterNames = field(init=False)

    def __post_init__(self):
        self.names = VClusterNames(self.claim_name)
