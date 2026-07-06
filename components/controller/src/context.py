from dataclasses import dataclass, field
import logging
import kopf

from config import KubernetesClients


@dataclass(frozen=True, slots=True)
class VClusterNames:
    name: str

    @property
    def namespace(self) -> str:
        return f"vcluster-{self.name}"

    @property
    def vcluster(self) -> str:
        return f"vcluster-{self.name}"

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


@dataclass(slots=True)
class ReconciliationContext:
    name: str
    spec: kopf.Spec
    meta: kopf.Meta
    patch: kopf.Patch
    logger: logging.Logger
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