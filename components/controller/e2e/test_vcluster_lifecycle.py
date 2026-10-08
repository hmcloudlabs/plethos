from typing import cast

from conftest import (
    NAMESPACE,
    vcluster_api_connection,
    wait_for_404,
    wait_for_no_running_pods,
    wait_for_phase,
    wait_for_synced_pods,
)
from context import VClusterNames
from shared.vclusterclaim import Phase, GROUP, PLURAL, VERSION

from kubernetes import client
from kubernetes.client import V1ConfigMap


def test_vcluster_provisioning(
    controller,
    clients,
    create_vcluster_claim,
    resource_name,
):
    """
    The controller should create the namespace, ServiceAccount, ClusterRoleBinding and Helm Job
    on the way to RUNNING. PROVISIONING and PENDING phases may be skipped between polls
    if the install completes quickly, so we assert on the durable end state RUNNING.
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
    clients.core.read_namespaced_service_account(names.service_account, namespace=names.namespace)
    clients.rbac.read_namespaced_role_binding(
        names.installer_role_binding, namespace=names.namespace
    )
    clients.batch.read_namespaced_job(names.install_job, namespace=names.namespace)


def test_vcluster_sleeping_and_waking(
    controller, cluster, clients, create_vcluster_claim, resource_name, tmp_path
):
    """
    Sleeping should take down the vCluster's control plane and the workload pods it synced to
    the host, so they stay gone. Waking should bring both back.
    """

    names = VClusterNames(resource_name)

    create_vcluster_claim()
    wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

    # Wait for vCluster's syncer to create pods on the host
    wait_for_synced_pods(clients, names)

    # Create something (a ConfigMap) inside the vCluster so we can check that
    # it is still there after sleep and wakeup.
    with vcluster_api_connection(clients, names, cluster, tmp_path) as vc:
        vc.create_namespaced_config_map(
            "default",
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name="test-configmap"), data={"value": "test-content"}
            ),
        )

    # Put to sleep
    clients.custom.patch_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        plural=PLURAL,
        namespace=NAMESPACE,
        name=resource_name,
        body={"spec": {"state": "Sleeping"}},
    )
    wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

    # Nothing should run in the namespace anymore, neither the control plane nor any workload pods
    wait_for_no_running_pods(clients, names)

    # Then wake up
    clients.custom.patch_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        plural=PLURAL,
        namespace=NAMESPACE,
        name=resource_name,
        body={"spec": {"state": "Running"}},
    )
    wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

    # The syncer is back and syncs the vCluster's workloads to the host again
    wait_for_synced_pods(clients, names)

    # Check that the ConfigMap survided the sleep/wake
    with vcluster_api_connection(clients, names, cluster, tmp_path) as vc:
        cm = cast(V1ConfigMap, vc.read_namespaced_config_map("test-configmap", "default"))
        assert cm.data and cm.data["value"] == "test-content"


def test_vcluster_deletion(controller, clients, create_vcluster_claim, resource_name):
    """
    Deleting a VClusterClaim should run the uninstall job and then remove
    the namespace, the ClusterRoleBinding and the claim itself.
    """

    names = VClusterNames(resource_name)

    create_vcluster_claim()
    wait_for_phase(clients.custom, resource_name, Phase.RUNNING)

    # Remove VClusterClaim resource
    clients.custom.delete_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        plural=PLURAL,
        namespace=NAMESPACE,
        name=resource_name,
    )

    # Expects the claim and namespace to disappear (the ServiceAccount and its
    # RoleBinding are namespaced, so they go with it)
    wait_for_404(
        lambda: clients.custom.get_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
        ),
        resource_type="VClusterClaim",
    )
    wait_for_404(
        lambda: clients.core.read_namespace(name=names.namespace),
        resource_type="Namespace",
    )
