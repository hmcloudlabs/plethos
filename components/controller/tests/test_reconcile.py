import time
import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from conftest import (
    NAMESPACE,
    wait_for_404,
    wait_for_job,
    wait_for_job_recreation,
    wait_for_phase,
)
from context import VClusterNames
from shared.vclusterclaim import Phase, GROUP, PLURAL, VERSION

from kube import get_statefulset, unwrap_statefulset, VCLUSTER_MANAGED_BY_LABEL


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

        obj = wait_for_phase(clients.custom, resource_name, Phase.RUNNING)
        assert "vCluster is ready" in obj["status"]["message"]

        # Check that `Ready` status condition is true with reason "Running"
        ready = next((c for c in obj["status"].get("conditions", []) if c["type"] == "Ready"), None)
        assert ready is not None
        assert ready["status"] == "True"
        assert ready["reason"] == Phase.RUNNING

        # Panics if any of the resources don't exist
        clients.core.read_namespace(name=names.namespace)
        clients.core.read_namespaced_service_account(
            names.service_account, namespace=names.namespace
        )
        clients.rbac.read_namespaced_role_binding(
            names.installer_role_binding, namespace=names.namespace
        )
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
        obj = wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

        assert obj["status"]["phase"] == Phase.RUNNING

    def test_handles_existing_role_binding(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        If the RoleBinding already exists (409), the operator should not
        enter ERROR phase, instead it should continue and eventually reach READY.
        """

        from resources import make_namespace, make_role_binding

        names = VClusterNames(resource_name)

        # Create pre-existing namespace + RoleBinding
        clients.core.create_namespace(body=make_namespace(names.namespace))
        clients.rbac.create_namespaced_role_binding(
            namespace=names.namespace,
            body=make_role_binding(
                names.namespace, names.service_account, names.installer_role_binding
            ),
        )

        create_vcluster_claim()
        obj = wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

        assert obj["status"]["phase"] == Phase.RUNNING


class TestCreateFailureAndRecovery:
    def test_helm_install_failure_retries_installation(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        A terminally failed install Job keeps the claim in PROVISIONING and
        once the finished Job is gone the controller provisions a fresh one.

        TODO:
        Delete or rewrite this test because the recreation is driven by our manual
        delete and not the failure, so it doesn't truely verify failure recovery.
        """

        names = VClusterNames(resource_name)

        create_vcluster_claim()

        original_uid = wait_for_job(clients.batch, names.namespace, names.install_job).metadata.uid

        # Force the Job into a terminally-failed state (backoffLimit exceeded).
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


class TestVClusterVersion:
    def test_rejects_malformed_version(self, clients, create_vcluster_claim, resource_name):
        """Non semver style versions are rejected by the CRD pattern."""

        with pytest.raises(ApiException) as exc_info:
            create_vcluster_claim(
                spec={
                    "name": resource_name,
                    "ownerSubject": "test-sub",
                    "ownerEmail": "test@example.com",
                    "vClusterVersion": "invalid.version",
                }
            )
        assert exc_info.value.status == 422

    def test_unsupported_version_enters_error(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """An unsupported version is refused by the controller, lands in ERROR and no install Job is created."""

        names = VClusterNames(resource_name)

        create_vcluster_claim(
            spec={
                "name": resource_name,
                "ownerSubject": "test-sub",
                "ownerEmail": "test@example.com",
                "vClusterVersion": "99.99.99",
            }
        )

        obj = wait_for_phase(clients.custom, resource_name, Phase.ERROR)
        assert "99.99.99" in obj["status"]["message"]

        # The version gate ran before provisioning, so no install Job exists.
        with pytest.raises(ApiException) as exc_info:
            clients.batch.read_namespaced_job(names.install_job, namespace=names.namespace)
        assert exc_info.value.status == 404


class TestUpdate:
    def test_sleep_vcluster(self, operator, clients, create_vcluster_claim, resource_name):
        """Changing state to Sleeping should scale down the vCluster StatefulSet."""

        names = VClusterNames(resource_name)

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )

        obj = wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        # Check that `Ready` status condition is false with reason "Sleeping"
        ready = next((c for c in obj["status"].get("conditions", []) if c["type"] == "Ready"), None)
        assert ready is not None
        assert ready["status"] == "False"
        assert ready["reason"] == Phase.SLEEPING

        apps = client.AppsV1Api()

        vc_set = get_statefulset(apps, names.vcluster, names.namespace)
        vc_set_spec, vc_set_metadata, _ = unwrap_statefulset(vc_set)

        assert vc_set_spec.replicas == 0
        assert vc_set_metadata.annotations.get(f"{GROUP}/scaled-down-replicas") == "1"

    def test_sleep_deletes_workload_pods(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """Sleeping should also delete the pods the vCluster synced into the host namespace."""

        names = VClusterNames(resource_name)

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

        clients.core.create_namespaced_pod(
            namespace=names.namespace,
            body=client.V1Pod(
                metadata=client.V1ObjectMeta(
                    name="synced-workload",
                    labels={VCLUSTER_MANAGED_BY_LABEL: names.vcluster},
                ),
                spec=client.V1PodSpec(
                    containers=[client.V1Container(name="pause", image="registry.k8s.io/pause:3.9")]
                ),
            ),
        )

        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )
        wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        wait_for_404(
            lambda: clients.core.read_namespaced_pod(
                name="synced-workload", namespace=names.namespace
            ),
            "workload pod",
        )

    def test_wake_vcluster(self, operator, clients, create_vcluster_claim, resource_name):
        """Changing state back to Running should scale up the vCluster StatefulSet."""

        names = VClusterNames(resource_name)

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

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

        obj = wait_for_phase(clients.custom, resource_name, Phase.RUNNING)
        assert "vCluster is ready" in obj["status"]["message"]

        apps = client.AppsV1Api()

        vc_set = get_statefulset(apps, names.vcluster, names.namespace)
        vc_set_spec, vc_set_metadata, _ = unwrap_statefulset(vc_set)

        assert vc_set_spec.replicas > 0
        assert vc_set_metadata.annotations.get(f"{GROUP}/scaled-down-replicas") is None

    def test_sleep_already_sleeping(self, operator, clients, create_vcluster_claim, resource_name):
        """Setting state to Sleeping when already sleeping should not error."""

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

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
        """Changing immutable fields like ownerSubject or vClusterVersion is rejected by the API."""

        create_vcluster_claim()

        with pytest.raises(ApiException) as exc_info:
            clients.custom.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=resource_name,
                body={"spec": {"ownerSubject": "different-sub"}},
            )
        assert exc_info.value.status == 422

        with pytest.raises(ApiException) as exc_info:
            clients.custom.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=resource_name,
                body={"spec": {"vClusterVersion": "0.19.0"}},
            )
        assert exc_info.value.status == 422
