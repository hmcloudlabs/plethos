import os
from pathlib import Path
import subprocess
import time
import uuid
import pytest
from kopf.testing import KopfRunner
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from shared.vclusterclaim import GROUP, PLURAL, VERSION

CLUSTER_NAME = "e2e-testing-cluster"
NAMESPACE = os.environ["VCLUSTERCLAIMS_NAMESPACE"]

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CRD_PATH = PROJECT_ROOT / "k8s" / "crds" / "vclusterclaim.yaml"
OPERATOR_PATH = PROJECT_ROOT / "components" / "controller" / "src" / "main.py"


@pytest.fixture(scope="session", autouse=True)
def kind_cluster():
    """
    Reuses an existing kind cluster if one is already running (speeds up local
    dev), or creates a fresh one if not. Either way, installs the CRDs before.
    """

    existing = subprocess.run(["kind", "get", "clusters"], capture_output=True, text=True)
    already_exists = CLUSTER_NAME in existing.stdout.splitlines()

    if not already_exists:
        subprocess.run(
            ["kind", "create", "cluster", "--name", CLUSTER_NAME, "--wait", "60s"],
            check=True,
        )

    config.load_kube_config(context=f"kind-{CLUSTER_NAME}")

    core = client.CoreV1Api()
    try:
        core.create_namespace(body=client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE)))
    except Exception:
        pass

    subprocess.run(["kubectl", "apply", "-f", CRD_PATH], check=True)
    time.sleep(1)

    yield

    if not already_exists:
        subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER_NAME], check=True)


@pytest.fixture(scope="session")
def core_api(kind_cluster):
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def rbac_api(kind_cluster):
    return client.RbacAuthorizationV1Api()


@pytest.fixture(scope="session")
def batch_api(kind_cluster):
    return client.BatchV1Api()


@pytest.fixture(scope="session")
def custom_api(kind_cluster):
    return client.CustomObjectsApi()


@pytest.fixture
def operator(kind_cluster):
    """
    Run the operator as a background subprocess for the duration of a single
    test, then shut it down cleanly. Uses --standalone to skip leader election.
    """

    with KopfRunner(["run", "--standalone", str(OPERATOR_PATH)]) as runner:
        time.sleep(2)  # give the operator time to start and load kube config
        yield runner

    assert runner.exception is None, f"Operator crashed: {runner.exception}"


@pytest.fixture
def resource_name():
    """
    Unique resource name per test.
    Keeps names distinct across runs and across tests within the same run.
    """

    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup(custom_api, core_api, rbac_api, resource_name):
    """
    Deletes the VClusterClaim (and wait for propagation) before and after
    each test so leftover resources from a crashed previous run don't cause conflicts.
    """

    def delete():
        try:
            custom_api.delete_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=resource_name,
            )
        except Exception:
            pass

        try:
            core_api.delete_namespace(name=f"vcluster-{resource_name}")
        except Exception:
            pass

        try:
            rbac_api.delete_cluster_role_binding(name=f"helm-installer-{resource_name}")
        except Exception:
            pass

        # Wait until namespace has been deleted
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                core_api.read_namespace(name=f"vcluster-{resource_name}")
                time.sleep(2)
            except ApiException as e:
                if e.status == 404:
                    break

    yield

    delete()


def wait_for_phase(custom_api, name, expected_phase, timeout=60):
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


def wait_for_404(api_fn, resource_type: str, timeout=60):
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


@pytest.fixture
def create_vcluster_claim(custom_api, resource_name):
    """
    Helper fixture that creates a VClusterClaim and returns its name.
    """

    def _create(spec=None):
        custom_api.create_namespaced_custom_object(
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
                    "ownerSub": "test-sub",
                    "ownerEmail": "test@example.com",
                },
            },
        )
        return resource_name

    return _create
