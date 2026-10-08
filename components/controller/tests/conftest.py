import os
from pathlib import Path
import subprocess
import time
import uuid
import pytest
from kopf.testing import KopfRunner
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from shared.vclusterclaim import GROUP, PLURAL, VERSION, State

from context import KubernetesClients

NAMESPACE = os.environ["VCLUSTERCLAIMS_NAMESPACE"]
TIMEOUT = int(os.getenv("TEST_TIMEOUT", "90"))

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CRD_PATH = PROJECT_ROOT / "charts" / "plethos" / "crds" / "vclusterclaim.yaml"
ROLE_PATH = (
    PROJECT_ROOT
    / "charts"
    / "plethos"
    / "templates"
    / "controller"
    / "vcluster-installer-rbac.yaml"
)
CONTROLLER_PATH = PROJECT_ROOT / "components" / "controller" / "src" / "main.py"


@pytest.fixture(scope="session", autouse=True)
def cluster(tmp_path_factory):
    """
    Runs only the k3s API server and controller-manager, without kubelet or container
    runtime, so no Docker is needed but also means that no Pod ever runs. Disables much
    of k3s functionality to make the cluster more lightweight.
    """

    data_dir = tmp_path_factory.mktemp("k3s")
    kubeconfig = data_dir / "kubeconfig"
    log_path = data_dir / "k3s.log"

    k3s = subprocess.Popen(
        [
            "k3s",
            "server",
            "--disable-agent",
            f"--data-dir={data_dir}",
            f"--write-kubeconfig={kubeconfig}",
            f"--log={log_path}",
            "--https-listen-port=16443",
            "--disable=coredns,servicelb,traefik,local-storage,metrics-server",
            "--disable-scheduler",
            "--disable-cloud-controller",
            "--disable-helm-controller",
            "--disable-network-policy",
            # Deactivate StatefulSet and Job controllers since they depend on running Pods
            "--kube-controller-manager-arg=controllers=*,-statefulset,-job",
            "--kube-controller-manager-arg=secure-port=0",
        ]
    )

    try:
        wait_for_api_server(k3s, kubeconfig, log_path)

        config.kube_config.KUBE_CONFIG_DEFAULT_LOCATION = str(kubeconfig)
        config.load_kube_config(config_file=str(kubeconfig))

        core = client.CoreV1Api()
        core.create_namespace(body=client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE)))

        subprocess.run(
            ["k3s", "kubectl", "--kubeconfig", kubeconfig, "apply", "-f", CRD_PATH], check=True
        )
        subprocess.run(
            [
                "k3s",
                "kubectl",
                "--kubeconfig",
                kubeconfig,
                "wait",
                "--for=condition=Established",
                "-f",
                CRD_PATH,
            ],
            check=True,
        )

        subprocess.run(
            ["k3s", "kubectl", "--kubeconfig", kubeconfig, "apply", "-f", ROLE_PATH], check=True
        )

        yield
    finally:
        k3s.terminate()
        k3s.wait(timeout=30)


def wait_for_api_server(k3s, kubeconfig, log_path, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if k3s.poll() is not None:
            raise RuntimeError(f"k3s exited with {k3s.returncode}:\n{log_path.read_text()[-3000:]}")

        ready = subprocess.run(
            ["k3s", "kubectl", f"--kubeconfig={kubeconfig}", "get", "--raw", "/readyz"],
            capture_output=True,
        )
        if ready.returncode == 0:
            return

        time.sleep(1)

    raise TimeoutError(
        f"k3s API server not ready after {timeout}s:\n{log_path.read_text()[-3000:]}"
    )


@pytest.fixture(scope="session")
def clients(cluster):
    return KubernetesClients()


@pytest.fixture
def controller(cluster):
    """Runs the controller for the duration of a single test, then shut it down cleanly."""

    with KopfRunner(["run", "--standalone", str(CONTROLLER_PATH)]) as runner:
        time.sleep(2)
        yield runner

    assert runner.exception is None, f"Controller crashed: {runner.exception}"


@pytest.fixture
def resource_name():
    """Unique resource name per test. Keeps names distinct across runs and across tests within the same run."""

    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup(clients, resource_name):
    """
    Deletes the VClusterClaim (and wait for propagation) after each test so leftover
    resources from a crashed previous run don't cause conflicts.
    """

    def delete():
        try:
            delete_vcluster_claim(clients, resource_name)
        except Exception:
            pass

        try:
            clients.core.delete_namespace(name=f"vcluster-{resource_name}")
        except Exception:
            pass

        # Wait until namespace has been deleted
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                clients.core.read_namespace(name=f"vcluster-{resource_name}")
                time.sleep(2)
            except ApiException as e:
                if e.status == 404:
                    break

    yield

    delete()


def fake_vcluster_install(clients, names, vcluster_version="0.35.0", replicas=1):
    """
    Waits for the controller's helm install Job, then creates the ready vCluster
    StatefulSet the Job would have, since without a kubelet it never runs.
    """

    wait_for_job(clients.batch, names.namespace, names.install_job)

    selector_labels = {"app": "vcluster", "release": names.vcluster}

    clients.apps.create_namespaced_stateful_set(
        namespace=names.namespace,
        body={
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": names.vcluster,
                "namespace": names.namespace,
                "labels": {**selector_labels, "chart": f"vcluster-{vcluster_version}"},
                "annotations": {
                    "meta.helm.sh/release-name": names.vcluster,
                    "meta.helm.sh/release-namespace": names.namespace,
                },
            },
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": selector_labels},
                "template": {
                    "metadata": {"labels": selector_labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "syncer",
                                "image": f"ghcr.io/loft-sh/vcluster-oss:{vcluster_version}",
                            }
                        ],
                    },
                },
            },
        },
    )

    # What the StatefulSet controller would report when the control plane Pods are ready
    clients.apps.patch_namespaced_stateful_set_status(
        name=names.vcluster,
        namespace=names.namespace,
        body={
            "status": {
                "replicas": replicas,
                "readyReplicas": replicas,
                "availableReplicas": replicas,
            }
        },
    )


def fake_vcluster_uninstall(clients, names):
    """
    Waits for the controller's helm uninstall Job, then does what it would on success: removes the
    vCluster StatefulSet and marks the Job `Complete`.
    """

    wait_for_job(clients.batch, names.namespace, names.uninstall_job)

    clients.apps.delete_namespaced_stateful_set(name=names.vcluster, namespace=names.namespace)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    clients.batch.patch_namespaced_job_status(
        name=names.uninstall_job,
        namespace=names.namespace,
        body={
            "status": {
                "startTime": now,
                "completionTime": now,
                "active": 0,
                "ready": 0,
                "succeeded": 1,
                "failed": 0,
                "conditions": [
                    {
                        "type": "SuccessCriteriaMet",
                        "status": "True",
                        "reason": "CompletionsReached",
                        "lastTransitionTime": now,
                    },
                    {
                        "type": "Complete",
                        "status": "True",
                        "reason": "CompletionsReached",
                        "lastTransitionTime": now,
                    },
                ],
            }
        },
    )


def delete_vcluster_claim(clients, resource_name):
    clients.custom.delete_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        plural=PLURAL,
        namespace=NAMESPACE,
        name=resource_name,
    )


def set_vcluster_state(clients, resource_name, state: State):
    clients.custom.patch_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        plural=PLURAL,
        namespace=NAMESPACE,
        name=resource_name,
        body={"spec": {"state": state}},
    )


def wait_for_phase(custom_api, name, expected_phase, expected_message=None, timeout=TIMEOUT):
    """
    Polls the VClusterClaim status until it reaches `expected_phase` (and `expected_message`,
    if given) or times out. Raises AssertionError immediately if the resource enters Error
    phase (unless that's what we want).
    """

    deadline = time.time() + timeout
    last_phase = None
    last_message = None

    while time.time() < deadline:
        try:
            obj = custom_api.get_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=name,
            )
        except Exception:
            time.sleep(2)
            continue

        last_phase = obj.get("status", {}).get("phase")
        last_message = obj.get("status", {}).get("message")

        if last_phase == expected_phase and expected_message in (None, last_message):
            return obj

        if last_phase == "Error" and expected_phase != "Error":
            msg = obj.get("status", {}).get("message", "")
            raise AssertionError(f"Reached Error phase while waiting for {expected_phase}: {msg}")

        time.sleep(2)

    raise TimeoutError(
        f"Timed out after {timeout}s waiting for phase '{expected_phase}', "
        f"last observed: '{last_phase}' ({last_message})."
    )


def wait_for_404(api_fn, resource_type: str, timeout=TIMEOUT):
    """
    Polls read_fn until it raises a 404 ApiException (resource is gone).
    Raises TimeoutError if the resource still exists after timeout seconds.
    """

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            api_fn()
            time.sleep(2)
        except ApiException as e:
            if e.status == 404:
                return
            raise

    raise TimeoutError(f"Resource {resource_type} should have been deleted after {timeout}s.")


def wait_for_job(batch_api, namespace: str, job_name: str, timeout: int = TIMEOUT):
    """
    Polls until the named Job exists, returning it.
    """

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return batch_api.read_namespaced_job(name=job_name, namespace=namespace)
        except ApiException as e:
            if e.status != 404:
                raise
            time.sleep(1)

    raise TimeoutError(f"Job '{job_name}' in '{namespace}' did not appear after {timeout}s.")


def wait_for_job_recreation(
    batch_api, namespace: str, job_name: str, old_uid: str, timeout: int = TIMEOUT
):
    """
    Polls until a Job named `job_name` exists with a uid different from `old_uid`,
    i.e. the previous Job was deleted and the controller recreated a fresh one.
    """

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            job = batch_api.read_namespaced_job(name=job_name, namespace=namespace)
            if job.metadata.uid != old_uid:
                return job
        except ApiException as e:
            if e.status != 404:
                raise
        time.sleep(1)

    raise TimeoutError(f"Job '{job_name}' in '{namespace}' was not recreated after {timeout}s.")


@pytest.fixture
def create_vcluster_claim(clients, resource_name):
    """
    Helper fixture that creates a VClusterClaim and returns its name.
    """

    def _create(spec=None):
        clients.custom.create_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            body={
                "apiVersion": f"{GROUP}/{VERSION}",
                "kind": "VClusterClaim",
                "metadata": {"name": resource_name, "namespace": NAMESPACE},
                "spec": spec
                or {
                    "name": resource_name,
                    "ownerSubject": "test-sub",
                    "ownerEmail": "test@example.com",
                },
            },
        )
        return resource_name

    return _create
