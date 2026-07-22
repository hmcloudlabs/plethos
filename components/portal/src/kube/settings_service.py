import json
from typing import cast
from kubernetes import client

from config import config
from kube.client import core_v1_api

SETTINGS_CONFIGMAP_NAME = "vkube-portal-settings"

_ADMIN_EMAILS_KEY = "adminEmails"
_MAX_VCLUSTERS_PER_USER_KEY = "maxVclustersPerUser"
_DEFAULT_MAX_VCLUSTERS_PER_USER = 5


class SettingsService:
    """Reads/writes the portal's admin-editable settings, backed by a single ConfigMap."""

    def __init__(
        self,
        core_api: client.CoreV1Api | None = None,
        namespace: str | None = None,
    ) -> None:
        self._core = core_api or core_v1_api()
        self._namespace = namespace or config.claims_namespace

    def _read_data(self) -> dict[str, str]:
        cm = cast(
            client.V1ConfigMap,
            self._core.read_namespaced_config_map(
                name=SETTINGS_CONFIGMAP_NAME,
                namespace=self._namespace,
            ),
        )
        return cm.data or {}

    def _patch_data(self, data: dict[str, str]) -> None:
        self._core.patch_namespaced_config_map(
            name=SETTINGS_CONFIGMAP_NAME,
            namespace=self._namespace,
            body={"data": data},
        )

    def max_clusters_per_user(self) -> int:
        raw = self._read_data().get(_MAX_VCLUSTERS_PER_USER_KEY)
        return int(raw) if raw is not None else _DEFAULT_MAX_VCLUSTERS_PER_USER

    def set_max_clusters_per_user(self, max_clusters: int) -> None:
        self._patch_data({_MAX_VCLUSTERS_PER_USER_KEY: str(max_clusters)})

    def list_admins(self) -> list[str]:
        raw = self._read_data().get(_ADMIN_EMAILS_KEY, "")
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def is_admin(self, email: str) -> bool:
        return email.strip().lower() in self.list_admins()

    def add_admin(self, email: str) -> None:
        admins = self.list_admins()
        
        email = email.strip().lower()
        if email not in admins:
            admins.append(email)

        self._patch_data({_ADMIN_EMAILS_KEY: ",".join(admins)})

    def remove_admin(self, email: str) -> None:
        email = email.strip().lower()
        self._patch_data({_ADMIN_EMAILS_KEY: ",".join(a for a in self.list_admins() if a != email)})
