import time

from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from conftest import NAMESPACE, wait_for_phase, wait_for_404, wait_for_job
from context import VClusterNames


class TestDelete:
    def test_delete_removes_vcluster_resources(
        self, operator, core_api, rbac_api, custom_api, create_vcluster_claim, resource_name
    ):
        """
        Deleting a VClusterClaim should run the uninstall job and then remove
        the namespace, the ClusterRoleBinding and the claim itself.
        """

        names = VClusterNames(resource_name)
        
        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=30)

        # Remove VClusterClaim resource
        custom_api.delete_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
        )

        # Expects the claim, namespace and CRB to disappear
        wait_for_404(
            lambda: custom_api.get_namespaced_custom_object(
                group=GROUP, version=VERSION, plural=PLURAL,
                namespace=NAMESPACE, name=resource_name,
            ),
            resource_type="VClusterClaim",
            timeout=30,
        )
        wait_for_404(
            lambda: core_api.read_namespace(name=names.namespace),
            resource_type="Namespace",
        )
        wait_for_404(
            lambda: rbac_api.read_cluster_role_binding(name=names.crb),
            resource_type="ClusterRoleBinding",
        )

    def test_delete_when_namespace_already_gone(
        self, operator, core_api, rbac_api, custom_api, create_vcluster_claim, resource_name
    ):
        """
        If the vcluster namespace is already gone (e.g. deleted manually), 
        on_delete should skip the uninstall job entirely, but still
        clean up the cluster-scoped ClusterRoleBinding.
        """

        names = VClusterNames(resource_name)
        
        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=30)

        # Manually delete the namespace before deleting the claim
        core_api.delete_namespace(name=names.namespace)
        wait_for_404(
            lambda: core_api.read_namespace(name=names.namespace),
            resource_type="Namespace",
            timeout=30,
        )

        custom_api.delete_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
        )

        wait_for_404(
            lambda: custom_api.get_namespaced_custom_object(
                group=GROUP, version=VERSION, plural=PLURAL,
                namespace=NAMESPACE, name=resource_name,
            ),
            resource_type="VClusterClaim",
        )

        # Cluster-scoped cleanup should still have run, even though no uninstall job ran.
        wait_for_404(
            lambda: rbac_api.read_cluster_role_binding(name=names.crb),
            resource_type="ClusterRoleBinding",
        )


class TestDeleteFailure:
    def test_uninstall_job_failure_sets_error_phase(
        self, operator, custom_api, batch_api, create_vcluster_claim, resource_name
    ):
        """
        If the helm uninstall Job fails, phase should move to ERROR and the
        claim should remain (finalizer held) rather than disappearing.
        """

        names = VClusterNames(resource_name)

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=30)

        custom_api.delete_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
        )

        wait_for_job(batch_api, names.namespace, names.uninstall_job, timeout=30)

        batch_api.patch_namespaced_job_status(
            name=names.uninstall_job,
            namespace=names.namespace,
            body={
                "status": {
                    "active": 0,
                    "ready": 0,
                    "failed": 1,
                    "succeeded": 0,
                    "conditions": [
                        {
                            "type": "FailureTarget",
                            "status": "True",
                            "reason": "BackoffLimitExceeded",
                            "lastTransitionTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        },
                        {
                            "type": "Failed",
                            "status": "True",
                            "reason": "BackoffLimitExceeded",
                            "lastTransitionTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        },
                    ],
                }
            },
        )

        obj = wait_for_phase(custom_api, resource_name, Phase.ERROR, timeout=30)
        assert "Helm uninstall job failed" in obj["status"]["message"]

        # The claim should still exist since uninstall job failed
        custom_api.get_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
        )