"""
End-to-end tests against a full k3s cluster that really installs vCluster, unlike the integration
tests in `tests/`, which fake it. Not part of the default `uv run pytest`, run them with
`uv run pytest e2e`. Needs Docker and k3d.
"""

import base64
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
import pytest
from kopf.testing import KopfRunner
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from shared.vclusterclaim import GROUP, PLURAL, VERSION

from context import KubernetesClients
from kube import VCLUSTER_MANAGED_BY_LABEL

CLUSTER_NAME = "e2e-testing-cluster"
K3S_IMAGE = "rancher/k3s:v1.36.5-k3s1"
NAMESPACE = os.environ["VCLUSTERCLAIMS_NAMESPACE"]

TIMEOUT = int(os.getenv("E2E_TIMEOUT", "300"))

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

os.environ.pop("RECONCILIATION_INTERVAL", "10800")  # 3 hrs, like in production


@pytest.fixture(scope="session", autouse=True)
def cluster():
    """
    Reuses an existing k3d cluster if one is already running (speeds up local
    dev), or creates a fresh one if not. Either way, installs the CRDs before.
    """

    existing = subprocess.run(["k3d", "cluster", "get", CLUSTER_NAME], capture_output=True)
    already_exists = existing.returncode == 0

    if not already_exists:
        subprocess.run(
            [
                "k3d",
                "cluster",
                "create",
                CLUSTER_NAME,
                "--image",
                K3S_IMAGE,
                "--k3s-arg",
                "--disable=traefik,servicelb,metrics-server@server:*",
                "--wait",
            ],
            check=True,
        )

    # Own kubeconfig file, independent of the current context
    kubeconfig = subprocess.run(
        ["k3d", "kubeconfig", "write", CLUSTER_NAME],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    config.kube_config.KUBE_CONFIG_DEFAULT_LOCATION = kubeconfig
    config.load_kube_config(config_file=kubeconfig)

    core = client.CoreV1Api()
    try:
        core.create_namespace(body=client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE)))
    except Exception:
        pass

    subprocess.run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", CRD_PATH], check=True)
    subprocess.run(
        [
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

    subprocess.run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", ROLE_PATH], check=True)

    yield kubeconfig

    if not already_exists:
        subprocess.run(["k3d", "cluster", "delete", CLUSTER_NAME], check=True)


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
            clients.custom.delete_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=resource_name,
            )
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


def wait_for_phase(custom_api, name, expected_phase, timeout=TIMEOUT):
    """
    Polls the VClusterClaim status until it reaches `expected_phase` or times out.
    Raises AssertionError immediately if the resource enters Error phase (unless that's what we want).
    """

    deadline = time.time() + timeout
    last_phase = None

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

        if last_phase == expected_phase:
            return obj

        if last_phase == "Error" and expected_phase != "Error":
            msg = obj.get("status", {}).get("message", "")
            raise AssertionError(f"Reached Error phase while waiting for {expected_phase}: {msg}")

        time.sleep(2)

    raise TimeoutError(
        f"Timed out after {timeout}s waiting for phase '{expected_phase}', last observed: '{last_phase}'."
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


def wait_for_synced_pods(clients, names, timeout=TIMEOUT):
    """Polls until the host namespace has pods the vCluster syncer created there."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        pods = clients.core.list_namespaced_pod(
            namespace=names.namespace,
            label_selector=f"{VCLUSTER_MANAGED_BY_LABEL}={names.vcluster}",
        ).items
        if pods:
            return

        time.sleep(2)

    raise TimeoutError(f"Synced pods of {names.vcluster} did not appear after {timeout}s.")


def wait_for_no_running_pods(clients, names, timeout=TIMEOUT):
    """
    Polls until no pod runs in the vCluster's host namespace anymore, neither the control plane
    nor any synced workload. Finished pods (e.g. of the helm install Job) don't count.
    """

    deadline = time.time() + timeout
    running = []
    while time.time() < deadline:
        running = clients.core.list_namespaced_pod(
            namespace=names.namespace,
            field_selector="status.phase!=Succeeded,status.phase!=Failed",
        ).items
        if not running:
            return

        time.sleep(2)

    left = ", ".join(pod.metadata.name for pod in running)
    raise TimeoutError(f"Pods still running in {names.namespace} after {timeout}s: {left}")


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


@contextmanager
def vcluster_api_connection(clients, names, kubeconfig, tmp_path):
    """Port-forwards to the vCluster's API server and yields a CoreV1Api for inside the vCluster."""

    secret = clients.core.read_namespaced_secret(f"vc-{names.vcluster}", names.namespace)
    vc_kubeconfig = base64.b64decode(secret.data["config"]).decode()

    # Find a local port, so parallel runs don't collide
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    forward = subprocess.Popen(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "port-forward",
            "--namespace",
            names.namespace,
            f"svc/{names.vcluster}",
            f"{port}:443",
        ],
        stdout=subprocess.DEVNULL,
    )
    try:
        path = tmp_path / "vcluster-kubeconfig"
        path.write_text(vc_kubeconfig.replace("localhost:8443", f"localhost:{port}"))

        api = client.CoreV1Api(config.new_client_from_config(config_file=str(path)))
        time.sleep(5)  # port-forward takes some time

        yield api
    finally:
        forward.terminate()
