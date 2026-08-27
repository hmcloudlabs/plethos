from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
import logging
import kopf
from kubernetes import client

from shared.vclusterclaim import GROUP


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
    def crb(self) -> str:
        return f"helm-installer-{self.name}"

    @property
    def install_job(self) -> str:
        return f"helm-install-{self.name}"

    @property
    def uninstall_job(self) -> str:
        return f"helm-uninstall-{self.name}"


class GatewayConvention:
    """
    The contract for exposing a workload publicly within a vCluster.

    An owner deploys a Service named `SERVICE_NAME` in `NAMESPACE` on port 80 *inside* their
    vCluster, the controller finds its synced counterpart on the host and creates an Ingress for it.
    """

    SERVICE_NAME = "gateway"
    NAMESPACE = "default"
    SUBDOMAIN = "plethos-apps"

    @classmethod
    def host(cls, vcluster_name: str, base_domain: str) -> str:
        """The public host a vClusters gateway Service is served under."""

        return f"{vcluster_name}.{cls.SUBDOMAIN}.{base_domain}"


class VClusterAnnotations:
    PAUSED = f"{GROUP}/paused"
    PAUSED_DATE = f"{GROUP}/paused-date"
    PAUSED_REPLICAS = f"{GROUP}/paused-replicas"


@dataclass(slots=True)
class ReconciliationContext:
    name: str
    spec: kopf.Spec
    meta: kopf.Meta
    patch: kopf.Patch
    logger: logging.Logger
    status: Mapping[str, Any] = field(default_factory=dict)
    clients: KubernetesClients = field(default_factory=KubernetesClients)
    names: VClusterNames = field(init=False)

    def __post_init__(self):
        self.names = VClusterNames(self.name)

    @property
    def generation(self) -> int:
        return self.meta["generation"]


@dataclass(slots=True)
class DeletionContext:
    name: str
    patch: kopf.Patch
    logger: logging.Logger
    names: VClusterNames = field(init=False)

    def __post_init__(self):
        self.names = VClusterNames(self.name)
