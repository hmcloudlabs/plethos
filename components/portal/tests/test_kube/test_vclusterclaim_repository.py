from unittest.mock import Mock, create_autospec
import base64

import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from kube.vclusterclaim_repository import (
    _MEMBER_LABEL_PREFIX,
    _OWNER_LABEL,
    _vclusterclaim_cache,
    VClusterClaimAlreadyExistsError,
    VClusterClaimRepository,
    get_member_hash,
    get_owner_hash,
    vcluster_namespace,
)
from shared.vclusterclaim import GROUP, PLURAL, VERSION, Member, State, VClusterClaimSpec

_NAMESPACE = "plethos-system"


def raw_vcluster_claim(object_name: str, owner_subject: str = "owner-sub", owner_email: str = "owner@example.com") -> dict:
    return {
        "metadata": {"name": object_name},
        "spec": {
            "name": object_name,
            "ownerSubject": owner_subject,
            "ownerEmail": owner_email,
        },
    }


def make_spec(name="test-cluster", owner_subject: str = "owner-sub", owner_email: str = "owner@example.com") -> VClusterClaimSpec:
    return VClusterClaimSpec(name=name, owner_subject=owner_subject, owner_email=owner_email)


@pytest.fixture(autouse=True)
def clear_vclusterclaim_cache():
    """`_vclusterclaim_cache` is globally shared by every repository instance."""

    _vclusterclaim_cache.invalidate_all()


@pytest.fixture
def api():
    return create_autospec(client.CustomObjectsApi, instance=True)


@pytest.fixture
def core_api():
    return create_autospec(client.CoreV1Api, instance=True)


@pytest.fixture
def repo(api, core_api):
    return VClusterClaimRepository(api=api, core_api=core_api, namespace=_NAMESPACE)


class TestHelpers:
    def test_get_member_hash_is_case_insensitive(self):
        assert get_member_hash("Bob@Example.com") == get_member_hash("bob@example.com")

    def test_vcluster_namespace_prefixes_the_object_name(self):
        assert vcluster_namespace("u123-test-cluster") == "vcluster-u123-test-cluster"


class TestListAndGet:
    def test_list_all_returns_every_claim(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": [raw_vcluster_claim("u1"), raw_vcluster_claim("u2")]}

        all_vcluster_claims = repo.list_all()
        assert [c.object_name for c in all_vcluster_claims] == ["u1", "u2"]

    def test_claims_are_cached_within_the_all_cache_entry(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_all()
        repo.list_all()

        assert api.list_namespaced_custom_object.call_count == 1

    def test_filters_by_owner_hash_label(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_by_owner("ted-sub")
        api.list_namespaced_custom_object.assert_called_once_with(
            group=GROUP,
            version=VERSION,
            namespace=_NAMESPACE,
            plural=PLURAL,
            label_selector=f"{_OWNER_LABEL}={get_owner_hash('ted-sub')}",
        )

    def test_caches_filter_by_owner_hash_label(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_by_owner("ted-sub")
        repo.list_by_owner("ted-sub")

        assert api.list_namespaced_custom_object.call_count == 1

    def test_filters_by_member_hash_label(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_by_shared_member("bob@example.com")
        api.list_namespaced_custom_object.assert_called_once_with(
            group=GROUP,
            version=VERSION,
            namespace=_NAMESPACE,
            plural=PLURAL,
            label_selector=f"{_MEMBER_LABEL_PREFIX}{get_member_hash('bob@example.com')}=true",
        )

    def test_caches_filter_by_member_hash_label(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}
        
        repo.list_by_shared_member("bob@example.com")
        repo.list_by_shared_member("bob@example.com")

        assert api.list_namespaced_custom_object.call_count == 1

    def test_returns_claim_by_name_when_found(self, repo, api):
        api.get_namespaced_custom_object.return_value = raw_vcluster_claim("u123-test-cluster")

        assert repo.get("u123-test-cluster").object_name == "u123-test-cluster"

    def test_returns_none_for_non_existing_claim_name(self, repo, api):
        api.get_namespaced_custom_object.side_effect = ApiException(status=404)

        assert repo.get("u123-test-cluster") is None


class TestCreate:
    def test_builds_the_object_name_from_owner_hash_and_given_name(self, repo, api):
        api.create_namespaced_custom_object.return_value = raw_vcluster_claim("ignored")

        repo.create("ted-sub", "test-cluster", make_spec(owner_subject="ted-sub"))

        body = api.create_namespaced_custom_object.call_args.kwargs["body"]
        assert body["metadata"]["name"] == f"u{get_owner_hash('ted-sub')}-test-cluster"
        assert body["metadata"]["labels"] == {_OWNER_LABEL: get_owner_hash("ted-sub")}

    def test_raises_if_claim_already_exists(self, repo, api):
        api.create_namespaced_custom_object.side_effect = ApiException(status=409)

        with pytest.raises(VClusterClaimAlreadyExistsError):
            repo.create("ted-sub", "test-cluster", make_spec(owner_subject="ted-sub"))

    def test_invalidates_all_and_owner_cache_entries(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_all()
        repo.list_by_owner("ted-sub")
        repo.list_by_shared_member("bob@example.com")

        # Creating new VClusterClaim invalidates "all" and owner cache entries, but not member entries
        api.create_namespaced_custom_object.return_value = raw_vcluster_claim("u123-new-cluster")
        repo.create("ted-sub", "test-cluster", make_spec(owner_subject="ted-sub"))

        repo.list_all()
        repo.list_by_owner("ted-sub")
        repo.list_by_shared_member("bob@example.com")   # not being refetched

        assert api.list_namespaced_custom_object.call_count == 5


class TestPatchState:
    def test_patches_the_desired_state(self, repo, api):
        repo.patch_state("u123-test-cluster", State.SLEEPING)

        api.patch_namespaced_custom_object.assert_called_once_with(
            group=GROUP,
            version=VERSION,
            namespace=_NAMESPACE,
            plural=PLURAL,
            name="u123-test-cluster",
            body={"spec": {"state": "Sleeping"}},
        )

    def test_ignores_non_existing_claim(self, repo, api):
        api.patch_namespaced_custom_object.side_effect = ApiException(status=404)

        repo.patch_state("u1", State.SLEEPING)  # doesn't raise

    def test_invalidates_entire_cache(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_all()
        repo.list_by_owner("ted-sub")
        repo.list_by_shared_member("bob@example.com")

        # Patching a VClusterClaim invalidates every cache entry, not just "all"/owner
        repo.patch_state("u123-test-cluster", State.SLEEPING)

        repo.list_all()
        repo.list_by_owner("ted-sub")
        repo.list_by_shared_member("bob@example.com")

        assert api.list_namespaced_custom_object.call_count == 6


class TestManageMembers:
    def test_adds_member_and_member_label(self, repo, api):
        api.patch_namespaced_custom_object.return_value = raw_vcluster_claim("u123-test-cluster")

        repo.add_member("u123-test-cluster", [Member(email="bob@example.com")], "bob@example.com")

        api.patch_namespaced_custom_object.assert_called_once_with(
            group=GROUP,
            version=VERSION,
            namespace=_NAMESPACE,
            plural=PLURAL,
            name="u123-test-cluster",
            body={
                "spec": {"members": [{"email": "bob@example.com"}]},
                "metadata": {"labels": {f"{_MEMBER_LABEL_PREFIX}{get_member_hash('bob@example.com')}": "true"}},
            },
        )

    def test_adding_invalidates_the_all_and_member_cache_entries(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_all()
        repo.list_by_shared_member("bob@example.com")

        # Adding a member to a VClusterClaim invalidates every cache entry, not just "all"/owner
        api.patch_namespaced_custom_object.return_value = raw_vcluster_claim("u1")
        repo.add_member("u123-test-cluster", [Member(email="bob@example.com")], "bob@example.com")

        repo.list_all()
        repo.list_by_shared_member("bob@example.com")

        assert api.list_namespaced_custom_object.call_count == 4

    def test_removes_members_and_unsets_member_label(self, repo, api):
        api.patch_namespaced_custom_object.return_value = raw_vcluster_claim("u123-test-cluster")

        repo.remove_member("u123-test-cluster", [Member(email="previous@member.com")], "bob@example.com")

        api.patch_namespaced_custom_object.assert_called_once_with(
            group=GROUP,
            version=VERSION,
            namespace=_NAMESPACE,
            plural=PLURAL,
            name="u123-test-cluster",
            body={
                "spec": {"members": [{"email": "previous@member.com"}]},
                "metadata": {"labels": {f"{_MEMBER_LABEL_PREFIX}{get_member_hash('bob@example.com')}": None}},
            },
        )

    def test_deletion_invalidates_the_all_and_member_cache_entries(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_all()
        repo.list_by_shared_member("bob@example.com")

        api.patch_namespaced_custom_object.return_value = raw_vcluster_claim("u123-test-cluster")
        repo.remove_member("u123-test-cluster", [], "bob@example.com")

        repo.list_all()
        repo.list_by_shared_member("bob@example.com")

        assert api.list_namespaced_custom_object.call_count == 4


class TestDelete:
    def test_deletes_the_object(self, repo, api):
        repo.delete("u123-test-cluster")

        api.delete_namespaced_custom_object.assert_called_once_with(
            group=GROUP, version=VERSION, namespace=_NAMESPACE, plural=PLURAL, name="u123-test-cluster"
        )

    def test_ignores_non_existing_claim(self, repo, api):
        api.delete_namespaced_custom_object.side_effect = ApiException(status=404)

        repo.delete("u123-test-cluster")  # doesn't raise

    def test_invalidates_the_entire_cache(self, repo, api):
        api.list_namespaced_custom_object.return_value = {"items": []}

        repo.list_all()
        repo.list_by_owner("ted-sub")

        repo.delete("u123-test-cluster")

        repo.list_all()
        repo.list_by_owner("ted-sub")

        assert api.list_namespaced_custom_object.call_count == 4


class TestReadKubeconfig:
    def test_returns_the_decoded_kubeconfig(self, repo, core_api):
        core_api.read_namespaced_secret.return_value.data = {
            "config": base64.b64encode(b"apiVersion: v1").decode()
        }

        assert repo.read_kubeconfig("u123-test-cluster") == "apiVersion: v1"

    def test_uses_vc_prefixed_secret_name_in_the_vcluster_namespace(self, repo, core_api):
        core_api.read_namespaced_secret.return_value.data = {"config": base64.b64encode(b"x").decode()}

        repo.read_kubeconfig("u123-test-cluster")
        core_api.read_namespaced_secret.assert_called_once_with(name="vc-u123-test-cluster", namespace="vcluster-u123-test-cluster")

    def test_returns_none_when_secret_is_missing(self, repo, core_api):
        core_api.read_namespaced_secret.side_effect = ApiException(status=404)

        assert repo.read_kubeconfig("u123-test-cluster") is None


class TestReadControlPlaneLogs:
    def test_returns_none_when_pod_is_missing(self, repo, core_api):
        core_api.read_namespaced_pod.side_effect = ApiException(status=404)

        assert repo.read_control_plane_logs("u123-test-cluster") is None

    def test_returns_none_when_the_pod_has_no_containers(self, repo, core_api):
        core_api.read_namespaced_pod.return_value.spec.containers = []

        assert repo.read_control_plane_logs("u123-test-cluster") is None

    def test_strips_ansi_escape_codes(self, repo, core_api):
        container = Mock()
        container.name = "syncer"
        core_api.read_namespaced_pod.return_value.spec.containers = [container]
        core_api.read_namespaced_pod_log.return_value.data = b"\x1b[31mhello\x1b[0m world"

        assert repo.read_control_plane_logs("u123-test-cluster") == "hello world"

    def test_reads_the_first_containers_log_with_given_tail(self, repo, core_api):
        container = Mock()
        container.name = "syncer"
        core_api.read_namespaced_pod.return_value.spec.containers = [container]
        core_api.read_namespaced_pod_log.return_value.data = b"Interesting logs..."

        repo.read_control_plane_logs("u123-test-cluster", tail_lines=50)

        core_api.read_namespaced_pod_log.assert_called_once_with(
            name="u123-test-cluster-0", namespace="vcluster-u123-test-cluster", container="syncer", tail_lines=50, _preload_content=False
        )
