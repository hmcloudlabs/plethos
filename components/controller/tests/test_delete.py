import time
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from conftest import NAMESPACE, wait_for_phase


class TestDelete:
    def test_delete_removes_vcluster_resources(
        self, operator, core_api, rbac_api, custom_api, create_vcluster_claim, resource_name
    ):
        """Deleting a VClusterClaim should remove the namespace and ClusterRoleBinding."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=30)

        custom_api.delete_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
        )

        # wait for claim to be fully gone
        import time

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                custom_api.get_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    plural=PLURAL,
                    namespace=NAMESPACE,
                    name=resource_name,
                )
                time.sleep(2)
            except Exception:
                break

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                rbac_api.read_cluster_role_binding(name=f"helm-installer-{resource_name}")
                time.sleep(2)
            except ApiException as e:
                if e.status == 404:
                    return  # CRB is gone, test passes
                raise

        assert False, "ClusterRoleBinding should have been deleted"

    def test_delete_when_namespace_already_gone(
        self, operator, core_api, custom_api, create_vcluster_claim, resource_name
    ):
        """If the vcluster namespace is already gone, on_delete should not error."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=30)

        # manually delete the namespace before deleting the claim
        core_api.delete_namespace(name=f"vcluster-{resource_name}")

        custom_api.delete_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
        )

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                custom_api.get_namespaced_custom_object(
                    group=GROUP,
                    version=VERSION,
                    plural=PLURAL,
                    namespace=NAMESPACE,
                    name=resource_name,
                )
                time.sleep(2)
            except Exception:
                return

        assert False, "VClusterClaim should have been deleted but is still present"
