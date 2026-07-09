import time
import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from conftest import NAMESPACE, wait_for_job, wait_for_job_recreation, wait_for_phase
from context import VClusterNames
from shared.vclusterclaim import Phase, GROUP, PLURAL, VERSION

from kube import get_statefulset, unwrap_statefulset


class TestCreate:
    def test_provisions_resources_and_reaches_ready(
        self,
        operator,
        clients,
        create_vcluster_claim,
        resource_name,
    ):
        """
        The operator should create the namespace, ServiceAccount, ClusterRoleBinding and Helm Job
        on the way to READY. PROVISIONING and PENDING phases may be skipped between polls
        if the install completes quickly, so we assert on the durable end state READY.
        """

        names = VClusterNames(resource_name)
        create_vcluster_claim()

        obj = wait_for_phase(clients.custom, resource_name, Phase.READY)
        assert "vCluster is ready" in obj["status"]["message"]

        # Panics if any of the resources don't exist
        clients.core.read_namespace(name=names.namespace)
        clients.core.read_namespaced_service_account(
            names.service_account, namespace=names.namespace
        )
        clients.rbac.read_cluster_role_binding(name=names.crb)
        clients.batch.read_namespaced_job(names.install_job, namespace=names.namespace)


class TestCreateIdempotency:
    def test_handles_existing_namespace(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        If the namespace already exists (409), the operator should not enter
        ERROR phase, instead it should continue and eventually reach READY.
        """

        from resources import make_namespace

        names = VClusterNames(resource_name)

        # Create pre-existing namespace
        clients.core.create_namespace(body=make_namespace(names.namespace))

        create_vcluster_claim()
        obj = wait_for_phase(clients.custom, resource_name, Phase.READY)

        assert obj["status"]["phase"] == Phase.READY

    def test_handles_existing_cluster_role_binding(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        If the ClusterRoleBinding already exists (409), the operator should not
        enter ERROR phase, instead it should continue and eventually reach READY.
        """

        from resources import make_cluster_role_binding

        names = VClusterNames(resource_name)

        # Create pre-existing CRB
        clients.rbac.create_cluster_role_binding(
            body=make_cluster_role_binding(names.namespace, names.crb)
        )

        create_vcluster_claim()
        obj = wait_for_phase(clients.custom, resource_name, Phase.READY)

        assert obj["status"]["phase"] == Phase.READY


class TestCreateFailureAndRecovery:
    def test_helm_install_failure_retries_installation(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        A terminally failed install Job keeps the claim in PROVISIONING and
        once the finished Job is gone the controller provisions a fresh one.
        """

        names = VClusterNames(resource_name)

        create_vcluster_claim()

        original_uid = wait_for_job(clients.batch, names.namespace, names.install_job).metadata.uid

        # Force the Job into a terminally-failed state (backoffLimit exceeded).
        # Kubernetes rejects Failed=True unless the interim FailureTarget=True
        # condition is also present, and requires active=0 for a finished Job.
        clients.batch.patch_namespaced_job_status(
            name=names.install_job,
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
                            "lastTransitionTime": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                        },
                        {
                            "type": "Failed",
                            "status": "True",
                            "reason": "BackoffLimitExceeded",
                            "lastTransitionTime": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                        },
                    ],
                }
            },
        )

        # A failed install keeps the claim provisioning (retrying), never Error.
        obj = wait_for_phase(
            clients.custom,
            resource_name,
            Phase.PROVISIONING,
        )
        assert obj["status"]["message"] in (
            "Helm install job failed.",
            "Creating helm install job.",
            "Helm install job running.",
        )

        # Delete job manually (in a real cluster this happens autom. via TTL)
        clients.batch.delete_namespaced_job(
            name=names.install_job,
            namespace=names.namespace,
            propagation_policy="Foreground",
        )

        wait_for_job_recreation(
            clients.batch,
            names.namespace,
            names.install_job,
            original_uid,
        )


class TestUpdate:
    def test_sleep_vcluster(self, operator, clients, create_vcluster_claim, resource_name):
        """Changing state to Sleeping should scale down the vCluster StatefulSet."""

        names = VClusterNames(resource_name)

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )

        wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        apps = client.AppsV1Api()

        vc_set = get_statefulset(apps, names.vcluster, names.namespace)
        vc_set_spec, vc_set_metadata, _ = unwrap_statefulset(vc_set)

        assert vc_set_spec.replicas == 0
        assert vc_set_metadata.annotations.get("loft.sh/paused") == "true"
        assert "loft.sh/paused-replicas" in vc_set_metadata.annotations

    def test_wake_vcluster(self, operator, clients, create_vcluster_claim, resource_name):
        """Changing state back to Running should scale up the vCluster StatefulSet."""

        names = VClusterNames(resource_name)

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        # First sleep
        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )
        wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        # Then wake
        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Running"}},
        )

        obj = wait_for_phase(clients.custom, resource_name, Phase.READY)
        assert "vCluster is ready" in obj["status"]["message"]

        apps = client.AppsV1Api()

        vc_set = get_statefulset(apps, names.vcluster, names.namespace)
        vc_set_spec, vc_set_metadata, _ = unwrap_statefulset(vc_set)

        assert vc_set_spec.replicas > 0
        assert vc_set_metadata.annotations.get("loft.sh/paused") is None

    def test_sleep_already_sleeping(self, operator, clients, create_vcluster_claim, resource_name):
        """Setting state to Sleeping when already sleeping should not error."""

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )
        wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        # Patch again with same value
        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )
        time.sleep(5)

        obj = clients.custom.get_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
        )
        assert obj["status"]["phase"] == Phase.SLEEPING

    def test_immutable_fields_rejected(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """Changing immutable fields like name or ownerSub should be rejected by the API."""

        create_vcluster_claim()

        with pytest.raises(ApiException) as exc_info:
            clients.custom.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=resource_name,
                body={"spec": {"ownerSub": "different-sub"}},
            )
        assert exc_info.value.status == 422
