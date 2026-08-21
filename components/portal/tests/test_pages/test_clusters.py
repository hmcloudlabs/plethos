from datetime import UTC, datetime, timedelta
from unittest.mock import create_autospec
import pytest
from fastapi.testclient import TestClient

from auth import User, require_user
from config import config
from kube.settings_service import SettingsService
from kube.vclusterclaim_model import ExpiryAnnotation
from kube.vclusterclaim_repository import VClusterClaimAlreadyExistsError
from kube.vclusterclaim_service import VClusterClaimUserService
from main import app
from pages.clusters import _pending_renewal, _validate_new_cluster, get_settings_service, get_vcc_service
from shared.vclusterclaim import Member


@pytest.fixture(autouse=True)
def patch_settings_service_list_admins(monkeypatch):
    # Prevent reading from real ConfigMap when listing admins because k8s API is unmocked
    # Also, /clusters has no admin specific logic, so the list stays empty
    monkeypatch.setattr(SettingsService, "list_admins", lambda self: [])


@pytest.fixture
def user():
    return User(sub="user-1-sub", email="bob@example.com", name="bob")


@pytest.fixture
def vcc_service(make_vcluster_claim):
    service = create_autospec(VClusterClaimUserService, instance=True)

    service.list_for_owner.return_value = [make_vcluster_claim(name="owned-cluster")]
    service.list_shared_with.return_value = [make_vcluster_claim(name="shared-cluster")]
    return service


@pytest.fixture
def settings_service():
    return create_autospec(SettingsService, instance=True)


@pytest.fixture
def client(user, vcc_service, settings_service):
    app.dependency_overrides[require_user] = lambda: user
    app.dependency_overrides[get_vcc_service] = lambda: vcc_service
    app.dependency_overrides[get_settings_service] = lambda: settings_service
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestListClusters:
    def test_shows_owned_and_shared_clusters(self, client):
        res = client.get("/clusters")

        assert "owned-cluster" in res.text
        assert "shared-cluster" in res.text


class TestCreateCluster:
    def test_rejects_an_invalid_name(self, client, vcc_service):
        client.post("/clusters", data={"name": "Invalid_Name!"})

        vcc_service.create.assert_not_called()

    def test_rejects_when_quota_is_reached(self, client, vcc_service, settings_service, make_vcluster_claim):
        settings_service.max_clusters_per_user.return_value = 1
        vcc_service.list_for_owner.return_value = [make_vcluster_claim()]

        client.post("/clusters", data={"name": "test-cluster"})

        vcc_service.create.assert_not_called()

    def test_creates_the_cluster_when_valid(self, client, vcc_service, settings_service, user):
        settings_service.max_clusters_per_user.return_value = 5

        client.post("/clusters", data={"name": "test-cluster"})

        vcc_service.create.assert_called_once()
        assert vcc_service.create.call_args.args[0] == user.sub
        assert vcc_service.create.call_args.args[2] == "test-cluster"

    def test_rejects_a_duplicate_name(self, client, vcc_service, settings_service):
        settings_service.max_clusters_per_user.return_value = 5
        vcc_service.create.side_effect = VClusterClaimAlreadyExistsError("u123-test-cluster")

        res = client.post("/clusters", data={"name": "test-cluster"})

        assert "already have a cluster" in res.text


class TestClusterInvitation:
    def test_rejects_inviting_yourself(self, client, vcc_service, user, make_vcluster_claim):
        vcc_service.get_by_object_name.return_value = make_vcluster_claim(owner_subject=user.sub)

        res = client.post("/clusters/u123-test-cluster/members", data={"email": user.email})

        assert "add yourself" in res.text
        vcc_service.invite_member.assert_not_called()

    def test_rejects_invalid_email(self, client, vcc_service, user, make_vcluster_claim):
        vcc_service.get_by_object_name.return_value = make_vcluster_claim(owner_subject=user.sub)

        res = client.post("/clusters/u123-test-cluster/members", data={"email": "not-an-email"})

        assert "Enter a valid email address" in res.text
        vcc_service.invite_member.assert_not_called()

    def test_rejects_when_team_quota_is_reached(
        self, client, vcc_service, settings_service, user, make_vcluster_claim
    ):
        vcc_service.get_by_object_name.return_value = make_vcluster_claim(
            owner_subject=user.sub, members=[Member(email="existing@example.com")]
        )
        
        settings_service.max_team_size.return_value = 1

        res = client.post("/clusters/u123-test-cluster/members", data={"email": "new@example.com"})

        assert "maximum of 1 shared member" in res.text
        vcc_service.invite_member.assert_not_called()

    def test_sends_invite_email_on_success(
        self, client, vcc_service, settings_service, user, make_vcluster_claim, monkeypatch
    ):
        claim = make_vcluster_claim(owner_subject=user.sub)
        vcc_service.get_by_object_name.return_value = claim
        settings_service.max_team_size.return_value = 5
        vcc_service.invite_member.return_value = (claim, "some-token")

        sent_email_args = {}
        monkeypatch.setattr("pages.clusters.send_email", lambda **mail_args: sent_email_args.update(mail_args))

        res = client.post("/clusters/u123-test-cluster/members", data={"email": "new@example.com"})

        assert sent_email_args["to"] == "new@example.com"
        assert "some-token" in sent_email_args["body"]
        assert "Invite sent to new@example.com" in res.text

    def test_accepting_invalid_invite_token_shows_error_message(self, client, vcc_service):
        vcc_service.accept_invite.return_value = None

        res = client.get("/invites/accept", params={"token": "invalid-tokeen"})

        assert "invalid or has expired" in res.text

    def test_accepting_valid_token_shows_success_message(self, client, vcc_service, make_vcluster_claim):
        vcc_service.accept_invite.return_value = make_vcluster_claim()

        res = client.get("/invites/accept", params={"token": "good-token"})

        assert "You now have access" in res.text


class TestKeepClusterAlive:
    def test_confirming_invalid_token_shows_error_message(self, client, vcc_service):
        vcc_service.confirm_keep_alive.return_value = None

        res = client.get("/keep-alive/confirm", params={"token": "invalid-token"})

        assert "invalid or has expired" in res.text

    def test_confirming_valid_token_shows_success_message(self, client, vcc_service, make_vcluster_claim):
        vcc_service.confirm_keep_alive.return_value = make_vcluster_claim()

        res = client.get("/keep-alive/confirm", params={"token": "good-token"})

        assert "marked as active" in res.text


class TestDownloadKubeconfig:
    def test_shows_error_message_when_not_available(self, client, vcc_service):
        vcc_service.get_kubeconfig.return_value = None

        res = client.get("/clusters/u123-test-cluster/kubeconfig")

        assert "Kubeconfig not available" in res.text

    def test_returns_kubeconfig_as_a_download(self, client, vcc_service):
        vcc_service.get_kubeconfig.return_value = ("test-cluster", "apiVersion: v1")

        res = client.get("/clusters/u123-test-cluster/kubeconfig")

        assert res.status_code == 200
        assert res.text == "apiVersion: v1"
        assert "application/yaml" in str(res.headers)
        assert "test-cluster-kubeconfig.yaml" in str(res.headers)


class TestDownloadData:
    def test_shows_error_message_when_not_available(self, client, vcc_service):
        vcc_service.get_mounted_volume_contents.return_value = None

        res = client.get("/clusters/u123-test-cluster/data")

        assert "No data available" in res.text

    def test_returns_data_as_a_download(self, client, vcc_service):
        vcc_service.get_mounted_volume_contents.return_value = ("test-cluster", b"tar-bytes")

        res = client.get("/clusters/u123-test-cluster/data")

        assert res.status_code == 200
        assert res.content == b"tar-bytes"
        assert "application/x-tar" in str(res.headers)
        assert "test-cluster-data.tar" in str(res.headers)


class TestValidateNewCluster:
    def test_accepts_a_valid_name(self):
        assert _validate_new_cluster("test-cluster") is None

    def test_rejects_an_empty_name(self):
        assert _validate_new_cluster("") is not None

    def test_rejects_uppercase_letters(self):
        assert _validate_new_cluster("TestCluster") is not None

    def test_rejects_a_leading_and_trailing_hyphen(self):
        assert _validate_new_cluster("-test-cluster") is not None
        assert _validate_new_cluster("test-cluster-") is not None

    def test_rejects_underscores(self):
        assert _validate_new_cluster("test_cluster") is not None

    def test_accepts_max_63_characters(self):
        assert _validate_new_cluster("a" * 63) is None
        assert _validate_new_cluster("a" * 64) is not None


class TestRenewCluster:
    def test_renews_via_vcc_service(self, client, vcc_service, user):
        client.post("/clusters/u123-test-cluster/renew")

        vcc_service.renew.assert_called_once_with("u123-test-cluster", user.sub, user.email)


class TestCheckPendingRenewals:
    def test_excludes_claims_with_no_expiry_annotations(self, make_vcluster_claim):
        claim = make_vcluster_claim(annotations={})

        assert _pending_renewal([claim]) == {}

    def test_includes_claims_with_sleep_warning_as_not_yet_expired(self, make_vcluster_claim):
        claim = make_vcluster_claim(annotations={ExpiryAnnotation.SLEEP_WARNING: "True"})
        result = _pending_renewal([claim])

        assert result[claim.object_name]["expired"] is False

    def test_includes_claims_with_expired_annotation_as_expired(self, make_vcluster_claim):
        claim = make_vcluster_claim(
            annotations={ExpiryAnnotation.SLEEP_WARNING: "True", ExpiryAnnotation.EXPIRED: "True"}
        )
        result = _pending_renewal([claim])

        assert result[claim.object_name]["expired"] is True

    def test_deletion_date_equals_expiry_period_plus_grace_period_from_renewal(self, make_vcluster_claim):
        claim = make_vcluster_claim(
            annotations={
                ExpiryAnnotation.RENEWED_AT: "2024-01-01T00:00:00Z",
                ExpiryAnnotation.SLEEP_WARNING: "True",
            }
        )

        expected_date = (
            datetime(2024, 1, 1, tzinfo=UTC)
            + timedelta(days=config.expiry_period_days + config.grace_period_days)
        ).strftime("%Y-%m-%d")
        assert _pending_renewal([claim])[claim.object_name]["date"] == expected_date