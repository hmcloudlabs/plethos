import json
from unittest.mock import create_autospec

import pytest
from kubernetes import client

from kube.settings_service import _SETTINGS_CONFIGMAP_NAME, SettingsService, _settings_cache, _SettingsKey

_NAMESPACE = "vkube-system"


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    `_settings_cache` is globally shared by every SettingsService instance,
    so we clear it that it wont leak into the next test.
    """

    _settings_cache.invalidate_all()


@pytest.fixture
def core_api():
    return create_autospec(client.CoreV1Api, instance=True)


@pytest.fixture
def settings(core_api):
    return SettingsService(core_api=core_api, namespace=_NAMESPACE)


class TestAdminList:
    def test_parse_admin_list(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.ADMIN_EMAILS: " Bob@Example.com ,ted@example.com,"
        }

        assert settings.list_admins() == ["bob@example.com", "ted@example.com"]

    def test_is_admin_is_true_for_a_listed_admin(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.ADMIN_EMAILS: "ted@example.com"}

        assert settings.is_admin("Ted@Example.com") is True

    def test_is_admin_false_for_a_non_admin(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.ADMIN_EMAILS: "bob@example.com"}

        assert settings.is_admin("ted@example.com") is False

    def test_add_admin_appends_a_new_admin(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.ADMIN_EMAILS: "ted@example.com"}

        settings.add_admin("bob@example.com")

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.ADMIN_EMAILS: "ted@example.com,bob@example.com"}},
        )

    def test_add_admin_does_not_duplicate_an_existing_admin(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.ADMIN_EMAILS: "ted@example.com"}

        settings.add_admin("ted@example.com")

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.ADMIN_EMAILS: "ted@example.com"}},
        )

    def test_remove_admin_removes_the_admin(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.ADMIN_EMAILS: "ted@example.com,bob@example.com"
        }

        settings.remove_admin("ted@example.com")

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.ADMIN_EMAILS: "bob@example.com"}},
        )


class TestMaxClusters:
    def test_returns_the_default_when_no_override(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.MAX_VCLUSTERS_PER_USER: "3"}

        assert settings.max_clusters_per_user("bob@example.com") == 3

    def test_returns_the_override_for_that_email(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.MAX_VCLUSTERS_PER_USER: "3",
            _SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES: json.dumps({"bob@example.com": 10}),
        }

        assert settings.max_clusters_per_user("Bob@Example.com") == 10

    def test_raises_if_the_configmap_is_missing_key(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {}

        with pytest.raises(RuntimeError):
            settings.max_clusters_per_user()

    def test_set_override(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES: "{}"
        }

        settings.set_max_clusters_override("bob@example.com", 7)

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES: json.dumps({"bob@example.com": 7})}},
        )

    def test_set_override_none_clears_existing_override(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES: json.dumps({"bob@example.com": 7})
        }

        settings.set_max_clusters_override("bob@example.com", None)

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.MAX_VCLUSTERS_PER_USER_OVERRIDES: json.dumps({})}},
        )


class TestMaxTeamSize:
    def test_returns_the_default_when_no_override(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.MAX_TEAM_SIZE: "5"}

        assert settings.max_team_size() == 5

    def test_returns_the_override_for_that_email(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.MAX_TEAM_SIZE: "5",
            _SettingsKey.MAX_TEAM_SIZE_OVERRIDES: json.dumps({"bob@example.com": 12}),
        }

        assert settings.max_team_size("Bob@Example.com") == 12

    def test_raises_if_the_configmap_is_missing_key(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {}

        with pytest.raises(RuntimeError):
            settings.max_team_size()

    def test_set_override(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.MAX_TEAM_SIZE_OVERRIDES: "{}"}

        settings.set_max_team_size_override("bob@example.com", 7)

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.MAX_TEAM_SIZE_OVERRIDES: json.dumps({"bob@example.com": 7})}},
        )

    def test_set_override_none_clears_existing_override(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.MAX_TEAM_SIZE_OVERRIDES: json.dumps({"bob@example.com": 7})
        }

        settings.set_max_team_size_override("bob@example.com", None)

        core_api.patch_namespaced_config_map.assert_called_once_with(
            name=_SETTINGS_CONFIGMAP_NAME,
            namespace=_NAMESPACE,
            body={"data": {_SettingsKey.MAX_TEAM_SIZE_OVERRIDES: json.dumps({})}},
        )


class TestSettingsCaching:
    def test_reads_are_cached_within_ttl(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.ADMIN_EMAILS: "ted@example.com"}

        settings.list_admins()
        settings.list_admins()

        assert core_api.read_namespaced_config_map.call_count == 1

    def test_writes_invalidate_the_cache(self, settings, core_api):
        core_api.read_namespaced_config_map.return_value.data = {_SettingsKey.ADMIN_EMAILS: "ted@example.com"}
        settings.list_admins()

        settings.add_admin("bob@example.com")
        core_api.read_namespaced_config_map.return_value.data = {
            _SettingsKey.ADMIN_EMAILS: "ted@example.com,bob@example.com"
        }

        assert settings.list_admins() == ["ted@example.com", "bob@example.com"]
        assert core_api.read_namespaced_config_map.call_count == 2