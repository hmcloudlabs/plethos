import json
from typing import cast
from kubernetes import client

from config import config
from kube.client import core_v1_api

SETTINGS_CONFIGMAP_NAME = "vkube-portal-settings"

_ADMIN_EMAILS_KEY = "adminEmails"
_MAX_VCLUSTERS_PER_USER_KEY = "maxVclustersPerUser"
_DEFAULT_MAX_VCLUSTERS_PER_USER = 5
_MAX_VCLUSTERS_PER_USER_OVERRIDES_KEY = "maxVclustersPerUserOverrides"
_MAX_TEAM_SIZE_KEY = "maxTeamSize"
_DEFAULT_MAX_TEAM_SIZE = 5
_MAX_TEAM_SIZE_OVERRIDES_KEY = "maxTeamSizeOverrides"


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

    def _patch_config(self, data: dict[str, str]) -> None:
        self._core.patch_namespaced_config_map(
            name=SETTINGS_CONFIGMAP_NAME,
            namespace=self._namespace,
            body={"data": data},
        )

    def _get_overrides(self, key: str) -> dict[str, int]:
        raw = self._read_data().get(key)
        return json.loads(raw) if raw else {}

    def _set_override(self, key: str, email: str, value: int | None) -> None:
        """Upserts the override for `email` or clears it if `value` is None."""

        overrides = self._get_overrides(key)
        email = email.strip().lower()
        if value is None:
            overrides.pop(email, None)
        else:
            overrides[email] = value

        self._patch_config({key: json.dumps(overrides)})

    def max_clusters_per_user(self, email: str | None = None) -> int:
        if email is not None:
            override = self._get_overrides(_MAX_VCLUSTERS_PER_USER_OVERRIDES_KEY).get(email.strip().lower())
            if override is not None:
                return override

        raw = self._read_data().get(_MAX_VCLUSTERS_PER_USER_KEY)
        return int(raw) if raw is not None else _DEFAULT_MAX_VCLUSTERS_PER_USER

    def set_max_clusters_per_user(self, max_clusters: int) -> None:
        self._patch_config({_MAX_VCLUSTERS_PER_USER_KEY: str(max_clusters)})

    def max_clusters_overrides(self) -> dict[str, int]:
        return self._get_overrides(_MAX_VCLUSTERS_PER_USER_OVERRIDES_KEY)

    def set_max_clusters_override(self, email: str, max_clusters: int | None) -> None:
        self._set_override(_MAX_VCLUSTERS_PER_USER_OVERRIDES_KEY, email, max_clusters)

    def max_team_size(self, email: str | None = None) -> int:
        if email is not None:
            override = self._get_overrides(_MAX_TEAM_SIZE_OVERRIDES_KEY).get(email.strip().lower())
            if override is not None:
                return override

        raw = self._read_data().get(_MAX_TEAM_SIZE_KEY)
        return int(raw) if raw is not None else _DEFAULT_MAX_TEAM_SIZE

    def set_max_team_size(self, max_team_size: int) -> None:
        self._patch_config({_MAX_TEAM_SIZE_KEY: str(max_team_size)})

    def max_team_size_overrides(self) -> dict[str, int]:
        return self._get_overrides(_MAX_TEAM_SIZE_OVERRIDES_KEY)

    def set_max_team_size_override(self, email: str, max_team_size: int | None) -> None:
        self._set_override(_MAX_TEAM_SIZE_OVERRIDES_KEY, email, max_team_size)

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

        self._patch_config({_ADMIN_EMAILS_KEY: ",".join(admins)})

    def remove_admin(self, email: str) -> None:
        email = email.strip().lower()
        self._patch_config({_ADMIN_EMAILS_KEY: ",".join(a for a in self.list_admins() if a != email)})
