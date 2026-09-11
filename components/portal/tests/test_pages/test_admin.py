from unittest.mock import create_autospec
import pytest
from auth import User, require_admin
from conftest import make_test_client

from kube.settings_service import SettingsService
from kube.vclusterclaim_service import VClusterClaimAdminService
from main import app
from pages.admin import get_settings_service, get_vcc_admin_service
from shared.vclusterclaim import State


@pytest.fixture(autouse=True)
def patch_settings_service_list_admins(monkeypatch):
    monkeypatch.setattr(SettingsService, "list_admins", lambda self: ["admin@example.com"])


@pytest.fixture
def user():
    return User(sub="admin-1-sub", email="admin@example.com", name="admin")


@pytest.fixture
def vcc_service():
    service = create_autospec(VClusterClaimAdminService, instance=True)
    service.list_all.return_value = []
    return service


@pytest.fixture
def settings_service():
    service = create_autospec(SettingsService, instance=True)
    service.list_admins.return_value = ["admin@example.com"]
    service.max_clusters_per_user.return_value = 5
    service.max_team_size.return_value = 3
    service.max_clusters_overrides.return_value = {}
    service.max_team_size_overrides.return_value = {}
    return service


@pytest.fixture
def client(user, vcc_service, settings_service):
    app.dependency_overrides[require_admin] = lambda: user
    app.dependency_overrides[get_vcc_admin_service] = lambda: vcc_service
    app.dependency_overrides[get_settings_service] = lambda: settings_service
    yield make_test_client("/admin")
    app.dependency_overrides.clear()


class TestAdminDashboard:
    def test_list_clusters(self, client, vcc_service, make_vcluster_claim):
        vcc_service.list_all.return_value = [
            make_vcluster_claim(owner_email="owner1@example.com"),
            make_vcluster_claim(owner_email="owner2@example.com"),
        ]

        res = client.get("/admin")

        assert "owner1@example.com" in res.text
        assert "owner2@example.com" in res.text

    def test_lists_every_cluster_regardless_of_owner(self, client, vcc_service, make_vcluster_claim):
        vcc_service.list_all.return_value = [make_vcluster_claim(name="someones-cluster")]

        res = client.get("/admin/clusters/list")

        assert "someones-cluster" in res.text


class TestAdminClustersActions:
    def test_sleep_puts_any_cluster_to_sleep(self, client, vcc_service):
        client.post("/admin/clusters/u123-test-cluster/sleep")
        vcc_service.set_state.assert_called_once_with("u123-test-cluster", State.SLEEPING)

    def test_wake_wakes_any_cluster(self, client, vcc_service):
        client.post("/admin/clusters/u123-test-cluster/wake")
        vcc_service.set_state.assert_called_once_with("u123-test-cluster", State.RUNNING)

    def test_delete_deletes_any_cluster(self, client, vcc_service):
        client.post("/admin/clusters/u123-test-cluster/delete")
        vcc_service.delete.assert_called_once_with("u123-test-cluster")

    def test_shows_logs_when_available(self, client, vcc_service, make_vcluster_claim):
        vcc_service.get.return_value = make_vcluster_claim(name="test-cluster")
        vcc_service.get_control_plane_logs.return_value = "interesting logs"

        res = client.get("/admin/clusters/u123-test-cluster/logs")

        assert "test-cluster" in res.text
        assert "interesting logs" in res.text

    def test_shows_not_available_message_when_no_logs_found(self, client, vcc_service, make_vcluster_claim):
        vcc_service.get.return_value = make_vcluster_claim()
        vcc_service.get_control_plane_logs.return_value = None

        res = client.get("/admin/clusters/u123-test-cluster/logs")

        assert "No logs available yet" in res.text


class TestAdminOwnersActions:
    def test_deletes_every_cluster_owned_by_a_given_email(self, client, vcc_service):
        client.post("/admin/owners/delete", data={"email": "Owner@Example.com"})

        vcc_service.delete_all_for_owner.assert_called_once_with("owner@example.com")


class TestAdminSettings:
    def test_rejects_a_max_clusters_value_below_one(self, client, settings_service):
        res = client.post("/admin/settings/max-clusters", data={"max_clusters_per_user": "0"})

        assert "must be at least 1" in res.text
        settings_service.set_max_clusters_per_user.assert_not_called()

    def test_sets_the_max_clusters_value(self, client, settings_service):
        res = client.post("/admin/settings/max-clusters", data={"max_clusters_per_user": "10"})

        settings_service.set_max_clusters_per_user.assert_called_once_with(10)
        assert "set to 10" in res.text

    def test_rejects_a_max_team_size_value_below_one(self, client, settings_service):
        res = client.post("/admin/settings/max-team-size", data={"max_team_size": "0"})

        assert "must be at least 1" in res.text
        settings_service.set_max_team_size.assert_not_called()

    def test_sets_the_max_team_size_value(self, client, settings_service):
        res = client.post("/admin/settings/max-team-size", data={"max_team_size": "8"})

        settings_service.set_max_team_size.assert_called_once_with(8)
        assert "set to 8" in res.text


class TestAdminMaxClustersOverrides:
    def test_rejects_an_invalid_email(self, client, settings_service):
        res = client.post(
            "/admin/settings/max-clusters/override", data={"email": "not-an-email", "max_clusters": "5"}
        )

        assert "Enter a valid email address" in res.text
        settings_service.set_max_clusters_override.assert_not_called()

    def test_rejects_a_value_below_one(self, client, settings_service):
        res = client.post(
            "/admin/settings/max-clusters/override", data={"email": "bob@example.com", "max_clusters": "0"}
        )

        assert "must be at least 1" in res.text
        settings_service.set_max_clusters_override.assert_not_called()

    def test_adds_the_override(self, client, settings_service):
        client.post("/admin/settings/max-clusters/override", data={"email": "Bob@Example.com", "max_clusters": "7"})

        settings_service.set_max_clusters_override.assert_called_once_with("bob@example.com", 7)

    def test_removes_the_override(self, client, settings_service):
        client.post("/admin/settings/max-clusters/override/remove", data={"email": "Bob@Example.com"})

        settings_service.set_max_clusters_override.assert_called_once_with("bob@example.com", None)


class TestAdminMaxTeamSizeOverrides:
    def test_rejects_an_invalid_email(self, client, settings_service):
        res = client.post(
            "/admin/settings/max-team-size/override", data={"email": "not-an-email", "max_team_size": "5"}
        )

        assert "Enter a valid email address" in res.text
        settings_service.set_max_team_size_override.assert_not_called()

    def test_rejects_a_value_below_one(self, client, settings_service):
        res = client.post(
            "/admin/settings/max-team-size/override", data={"email": "bob@example.com", "max_team_size": "0"}
        )

        assert "must be at least 1" in res.text
        settings_service.set_max_team_size_override.assert_not_called()

    def test_adds_the_override(self, client, settings_service):
        client.post("/admin/settings/max-team-size/override", data={"email": "Bob@Example.com", "max_team_size": "7"})

        settings_service.set_max_team_size_override.assert_called_once_with("bob@example.com", 7)

    def test_removes_the_override(self, client, settings_service):
        client.post("/admin/settings/max-team-size/override/remove", data={"email": "Bob@Example.com"})

        settings_service.set_max_team_size_override.assert_called_once_with("bob@example.com", None)


class TestAdminManageAdmins:
    def test_rejects_an_invalid_email(self, client, settings_service):
        res = client.post("/admin/settings/admins/add", data={"email": "not-an-email"})

        assert "Enter a valid email address" in res.text
        settings_service.add_admin.assert_not_called()

    def test_rejects_adding_yourself(self, client, settings_service, user):
        res = client.post("/admin/settings/admins/add", data={"email": user.email})

        assert "add yourself" in res.text
        settings_service.add_admin.assert_not_called()

    def test_adds_valid_admin_email(self, client, settings_service):
        client.post("/admin/settings/admins/add", data={"email": "new-admin@example.com"})

        settings_service.add_admin.assert_called_once_with("new-admin@example.com")

    def test_rejects_removing_yourself(self, client, settings_service, user):
        res = client.post("/admin/settings/admins/remove", data={"email": user.email})

        assert "remove yourself" in res.text
        settings_service.remove_admin.assert_not_called()

    def test_removes_admin_by_email(self, client, settings_service):
        client.post("/admin/settings/admins/remove", data={"email": "old-admin@example.com"})

        settings_service.remove_admin.assert_called_once_with("old-admin@example.com")
