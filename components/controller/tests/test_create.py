from conftest import wait_for_phase
from shared.vclusterclaim import Phase


class TestCreate:
    def test_provisioning_to_pending_phase(
        self,
        operator,
        core_api,
        rbac_api,
        batch_api,
        custom_api,
        create_vcluster_claim,
        resource_name,
    ):
        """Waits until PROVISIONING phase is over and moved to PENDING and tests if all resources were created."""

        create_vcluster_claim()

        obj = wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=35)

        # Panics if any of the resources don't exist
        core_api.read_namespace(name=f"vcluster-{resource_name}")
        core_api.read_namespaced_service_account(
            "helm-installer", namespace=f"vcluster-{resource_name}"
        )
        rbac_api.read_cluster_role_binding(name=f"helm-installer-{resource_name}")
        batch_api.read_namespaced_job(
            f"helm-install-{resource_name}", namespace=f"vcluster-{resource_name}"
        )

        assert "Helm install job running" in obj["status"]["message"]

    def test_pending_to_ready_phase(
        self, operator, custom_api, create_vcluster_claim, resource_name
    ):
        """Status should move to READY once the helm install job succeeds."""

        create_vcluster_claim()
        obj = wait_for_phase(custom_api, resource_name, Phase.READY, timeout=120)

        assert "vCluster is ready" in obj["status"]["message"]


class TestCreateIdempotency:
    def test_handles_existing_namespace(
        self, operator, custom_api, core_api, create_vcluster_claim, resource_name
    ):
        """
        If the namespace already exists (409), the operator should not enter ERROR phase, it should continue and reach PENDING.
        """

        from resources import make_namespace

        core_api.create_namespace(body=make_namespace(resource_name))

        create_vcluster_claim()
        obj = wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=35)
        assert obj["status"]["phase"] == Phase.PENDING

    def test_handles_existing_cluster_role_binding(
        self, operator, custom_api, rbac_api, create_vcluster_claim, resource_name
    ):
        """
        If the ClusterRoleBinding already exists (409), the operator should not enter ERROR phase, it should continue and reach PENDING.
        """

        from resources import make_cluster_role_binding

        rbac_api.create_cluster_role_binding(body=make_cluster_role_binding(resource_name))

        create_vcluster_claim()
        obj = wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=35)
        assert obj["status"]["phase"] == Phase.PENDING


class TestCreateFailureAndRecovery:
    def test_helm_failure_sets_error_phase(
        self, operator, custom_api, batch_api, create_vcluster_claim, resource_name
    ):
        """If the helm install Job fails, phase should move to ERROR."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=35)

        # Force the Job into a failed state
        batch_api.patch_namespaced_job_status(
            name=f"helm-install-{resource_name}",
            namespace=f"vcluster-{resource_name}",
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
                        },
                        {"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded"},
                    ],
                }
            },
        )

        obj = wait_for_phase(custom_api, resource_name, Phase.ERROR, timeout=35)
        assert "Helm install job failed" in obj["status"]["message"]
