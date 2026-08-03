import json
from enum import StrEnum
from typing import cast
from kubernetes import client

from config import config
from kube.client import core_v1_api
from ttl_cache import TTLCache


_SETTINGS_CONFIGMAP_NAME = "vkube-portal-settings"

_SETTINGS_CACHE_KEY = "settings"
_settings_cache: TTLCache[dict[str, str]] = TTLCache(config.cache_ttl_seconds)



class _SettingsKey(StrEnum):
    ADMIN_EMAILS = "adminEmails"
    MAX_VCLUSTERS_PER_USER = "maxVclustersPerUser"
    MAX_VCLUSTERS_PER_USER_OVERRIDES = "maxVclustersPerUserOverrides"
    MAX_TEAM_SIZE = "maxTeamSize"
    MAX_TEAM_SIZE_OVERRIDES = "maxTeamSizeOverrides"


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
        def fetch() -> dict[str, str]:
            cm = cast(
                client.V1ConfigMap,
                self._core.read_namespaced_config_map(
                    name=_SETTINGS_CONFIGMAP_NAME,
                    namespace=self._namespace,
                ),
            )
            return cm.data or {}

        return _settings_cache.get_or_set(_SETTINGS_CACHE_KEY, fetch)

    def _patch_config(self, data: dict[str, str]) -> None:
        self._core.patch_namespaced_config_map(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=self._namespace,
            body={"data": data},
        )
        _settings_cache.invalidate(_SETTINGS_CACHE_KEY)

    def _require(self, key: _SettingsKey) -> str:
        value = self._read_data().get(key)
        if value is None:
            raise RuntimeError(f"{_SETTINGS_CONFIGMAP_NAME} is missing required key {key!r}")
        return value

    def _get_overrides(self, key: _SettingsKey) -> dict[str, int]:
        raw = self._read_data().get(key)
        return json.loads(raw) if raw else {}

    def _set_override(self, key: _SettingsKey, email: str, value: int | None) -> None:
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
            override = self._get_overrides(_SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES).get(email.strip().lower())
            if override is not None:
                return override

        return int(self._require(_SettingsKey.MAX_VCLUSTERS_PER_USER))

    def set_max_clusters_per_user(self, max_clusters: int) -> None:
        self._patch_config({_SettingsKey.MAX_VCLUSTERS_PER_USER: str(max_clusters)})

    def max_clusters_overrides(self) -> dict[str, int]:
        return self._get_overrides(_SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES)

    def set_max_clusters_override(self, email: str, max_clusters: int | None) -> None:
        self._set_override(_SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES, email, max_clusters)

    def max_team_size(self, email: str | None = None) -> int:
        if email is not None:
            override = self._get_overrides(_SettingsKey.MAX_TEAM_SIZE_OVERRIDES).get(email.strip().lower())
            if override is not None:
                return override

        return int(self._require(_SettingsKey.MAX_TEAM_SIZE))

    def set_max_team_size(self, max_team_size: int) -> None:
        self._patch_config({_SettingsKey.MAX_TEAM_SIZE: str(max_team_size)})

    def max_team_size_overrides(self) -> dict[str, int]:
        return self._get_overrides(_SettingsKey.MAX_TEAM_SIZE_OVERRIDES)

    def set_max_team_size_override(self, email: str, max_team_size: int | None) -> None:
        self._set_override(_SettingsKey.MAX_TEAM_SIZE_OVERRIDES, email, max_team_size)

    def list_admins(self) -> list[str]:
        raw = self._read_data().get(_SettingsKey.ADMIN_EMAILS, "")
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def is_admin(self, email: str) -> bool:
        return email.strip().lower() in self.list_admins()

    def add_admin(self, email: str) -> None:
        admins = self.list_admins()

        email = email.strip().lower()
        if email not in admins:
            admins.append(email)

        self._patch_config({_SettingsKey.ADMIN_EMAILS: ",".join(admins)})

    def remove_admin(self, email: str) -> None:
        email = email.strip().lower()
        self._patch_config(
            {_SettingsKey.ADMIN_EMAILS: ",".join(a for a in self.list_admins() if a != email)}
        )
