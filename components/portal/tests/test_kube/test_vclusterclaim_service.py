from unittest.mock import MagicMock, call, create_autospec

import pytest

from kube.settings_service import SettingsService
from kube.vclusterclaim_repository import VClusterClaimRepository
from kube.vclusterclaim_service import VClusterClaimAdminService, VClusterClaimUserService
from shared.vclusterclaim import Member, State
from tokens import invite_tokens, keep_alive_tokens


@pytest.fixture
def repo():
    return create_autospec(VClusterClaimRepository, instance=True)


@pytest.fixture
def service(repo):
    return VClusterClaimUserService(repo=repo)


@pytest.fixture
def admin_service(repo):
    return VClusterClaimAdminService(repo=repo)


@pytest.fixture
def settings_service():
    return MagicMock(spec=SettingsService)


class TestList:
    def test_list_for_owner_returns_the_owners_claims(self, service, repo, make_vcluster_claim):
        claim = make_vcluster_claim(owner_subject="alice-sub")

        repo.list_by_owner.return_value = [claim]
        assert service.list_for_owner("alice-sub") == [claim]

    def test_list_shared_with_returns_claims_where_email_is_a_member(self, service, repo, make_vcluster_claim):
        claim = make_vcluster_claim(members=[Member(email="bob@example.com")])
        repo.list_by_shared_member.return_value = [claim]

        assert service.list_shared_with("bob@example.com") == [claim]

    def test_list_shared_with_excludes_claims_where_the_email_is_the_owner(
        self, service, repo, make_vcluster_claim
    ):
        claim = make_vcluster_claim(owner_email="bob@example.com", members=[Member(email="bob@example.com")])

        repo.list_by_shared_member.return_value = [claim]
        assert service.list_shared_with("bob@example.com") == []


class TestSetState:
    def test_owner_can_change_state(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(owner_subject="owner-sub")

        service.set_state("u123-test-cluster", "owner-sub", "", State.SLEEPING)
        repo.patch_state.assert_called_once_with("u123-test-cluster", State.SLEEPING)

    def test_shared_member_can_change_state(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(members=[Member(email="bob@example.com")])

        service.set_state("u123-test-cluster", "bobs-sub", "bob@example.com", State.SLEEPING)
        repo.patch_state.assert_called_once_with("u123-test-cluster", State.SLEEPING)

    def test_stranger_cannot_change_state(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim()

        service.set_state("u123-test-cluster", "strangers-sub", "", State.SLEEPING)
        repo.patch_state.assert_not_called()


class TestDelete:
    def test_owner_can_delete(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(owner_subject="owner-sub")

        service.delete("u123-test-cluster", "owner-sub")
        repo.delete.assert_called_once_with("u123-test-cluster")

    def test_shared_member_cannot_delete(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(members=[Member(email="bob@example.com")])

        service.delete("u123-test-cluster", "bobs-sub")
        repo.delete.assert_not_called()


class TestInviteMember:
    def test_owner_can_invite(self, service, repo, make_vcluster_claim):
        claim = make_vcluster_claim(owner_subject="owner-sub")
        repo.get.return_value = claim

        result = service.invite_member("u123-test-cluster", "owner-sub", "new@example.com")
        assert result is not None and result[0] == claim

    def test_non_owner_cannot_invite(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(members=[Member(email="bob@example.com")])
        assert service.invite_member("u123-test-cluster", "bobs-sub", "new@example.com") is None


class TestAcceptInvite:
    def test_adds_the_invited_email_as_a_member(self, service, repo, settings_service, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(object_name="u123-test-cluster")
        settings_service.max_team_size.return_value = 5

        token = invite_tokens.generate({"object_name": "u123-test-cluster", "email": "new@example.com"})

        service.accept_invite(token, settings_service)
        repo.add_member.assert_called_once_with(
            "u123-test-cluster", [Member(email="new@example.com")], "new@example.com"
        )

    def test_returns_none_for_an_invalid_token(self, service, repo, settings_service):
        assert service.accept_invite("invalid-token", settings_service) is None
        repo.get.assert_not_called()

    def test_returns_none_if_the_claim_no_longer_exists(self, service, repo, settings_service):
        repo.get.return_value = None

        token = invite_tokens.generate({"object_name": "u123-test-cluster", "email": "new@example.com"})

        assert service.accept_invite(token, settings_service) is None

    def test_skips_if_already_a_member(self, service, repo, settings_service, make_vcluster_claim):
        claim = make_vcluster_claim(members=[Member(email="new@example.com")])
        repo.get.return_value = claim

        token = invite_tokens.generate({"object_name": "u123-test-cluster", "email": "new@example.com"})

        result = service.accept_invite(token, settings_service)
        assert result == claim
        repo.add_member.assert_not_called()

    def test_rejects_when_the_team_quota_is_reached(self, service, repo, settings_service, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(members=[Member(email="existing@example.com")])
        token = invite_tokens.generate({"object_name": "u123-test-cluster", "email": "new@example.com"})

        settings_service.max_team_size.return_value = 1

        result = service.accept_invite(token, settings_service)

        assert result is None
        repo.add_member.assert_not_called()


class TestRemoveMember:
    def test_owner_can_remove_a_member(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(
            owner_subject="owner-sub", members=[Member(email="bob@example.com")]
        )

        service.remove_member("u123-test-cluster", "owner-sub", "bob@example.com")
        repo.remove_member.assert_called_once_with("u123-test-cluster", [], "bob@example.com")

    def test_member_cannot_remove_a_member(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(members=[Member(email="bob@example.com")])

        service.remove_member("u123-test-cluster", "bobs-sub", "bob@example.com")
        repo.remove_member.assert_not_called()


class TestGetKubeconfig:
    def test_returns_none_if_the_kubeconfig_is_missing(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(owner_subject="owner-sub")
        repo.read_kubeconfig.return_value = None

        assert service.get_kubeconfig("u123-test-cluster", "owner-sub", "") is None

    def test_returns_the_claim_name_and_kubeconfig(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(owner_subject="owner-sub")
        repo.read_kubeconfig.return_value = "some-kubeconfig-yaml"

        result = service.get_kubeconfig("u123-test-cluster", "owner-sub", "")
        assert result == ("test-cluster", "some-kubeconfig-yaml")


class TestGetMountedVolumeContents:
    def test_returns_none_if_there_is_no_data(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(owner_subject="owner-sub")
        repo.read_mounted_volume_contents.return_value = None

        assert service.get_mounted_volume_contents("u123-test-cluster", "owner-sub", "") is None

    def test_returns_the_claim_name_and_data(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(owner_subject="owner-sub")
        repo.read_mounted_volume_contents.return_value = b"some-bytes"

        result = service.get_mounted_volume_contents("u123-test-cluster", "owner-sub", "")
        assert result == ("test-cluster", b"some-bytes")


class TestAdminGetKubeconfig:
    def test_returns_none_if_the_claim_doesnt_exist(self, admin_service, repo):
        repo.get.return_value = None

        assert admin_service.get_kubeconfig("u123-test-cluster") is None

    def test_returns_none_if_the_kubeconfig_is_missing(self, admin_service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim()
        repo.read_kubeconfig.return_value = None

        assert admin_service.get_kubeconfig("u123-test-cluster") is None

    def test_returns_the_claim_name_and_kubeconfig(self, admin_service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim()
        repo.read_kubeconfig.return_value = "some-kubeconfig-yaml"

        result = admin_service.get_kubeconfig("u123-test-cluster")
        assert result == ("test-cluster", "some-kubeconfig-yaml")


class TestAdminDeleteAllForOwner:
    def test_deletes_only_claims_owned_by_the_given_email(self, admin_service, repo, make_vcluster_claim):
        owner_a_first = make_vcluster_claim(object_name="u1-first-cluster", owner_email="bob@example.com")
        owner_a_second = make_vcluster_claim(object_name="u1-second-cluster", owner_email="bob@example.com")
        owner_b_first = make_vcluster_claim(object_name="u2-first-cluster", owner_email="ted@example.com")

        repo.list_all.return_value = [owner_a_first, owner_a_second, owner_b_first]

        count = admin_service.delete_all_for_owner("bob@example.com")

        assert count == 2
        assert repo.delete.call_args_list == [call("u1-first-cluster"), call("u1-second-cluster")]

    def test_matches_owner_email_case_insensitively(self, admin_service, repo, make_vcluster_claim):
        repo.list_all.return_value = [make_vcluster_claim(object_name="u1-first-cluster", owner_email="Bob@Example.com")]

        count = admin_service.delete_all_for_owner("bob@example.com")

        assert count == 1
        repo.delete.assert_called_once_with("u1-first-cluster")



class TestConfirmKeepClusterAlive:
    def test_resets_activity_for_valid_token(self, service, repo, make_vcluster_claim):
        repo.get.return_value = make_vcluster_claim(object_name="u123-test-cluster")

        token = keep_alive_tokens.generate({"object_name": "u123-test-cluster"})
        service.confirm_keep_alive(token)

        repo.reset_activity.assert_called_once_with("u123-test-cluster")

    def test_returns_none_for_invalid_token(self, service, repo):
        assert service.confirm_keep_alive("invalid-token") is None
        repo.reset_activity.assert_not_called()

    def test_returns_none_if_claim_no_longer_exists(self, service, repo):
        repo.get.return_value = None

        token = keep_alive_tokens.generate({"object_name": "u123-test-cluster"})
        assert service.confirm_keep_alive(token) is None
        repo.reset_activity.assert_not_called()

