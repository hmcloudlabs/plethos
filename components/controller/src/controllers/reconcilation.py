from datetime import datetime, UTC
import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase, State
from resources import (
    make_namespace,
    make_service_account,
    make_cluster_role_binding,
    make_helm_install_job,
)
from config import settings


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.timer(GROUP, VERSION, PLURAL, interval=30)
def reconcile(spec: kopf.Spec, meta, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    if not name or name.startswith("vcluster"):
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    ensure_namespace_and_rbac(name, patch, logger)

    installed = reconcile_install_job(spec, name, patch, logger)
    if installed:
        reconcile_vcluster_state(spec, name, patch, logger)

    patch.status["observedGeneration"] = meta["generation"]


def ensure_namespace_and_rbac(name: str, patch: kopf.Patch, logger) -> None:
    core = client.CoreV1Api()
    rbac = client.RbacAuthorizationV1Api()

    try:
        core.create_namespace(body=make_namespace(name))
        logger.info(f"Created namespace vcluster-{name}.")
    except ApiException as e:
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = f"Failed to create namespace: {e.reason}"
            raise

    try:
        core.create_namespaced_service_account(
            namespace=f"vcluster-{name}",
            body=make_service_account(name),
        )
        logger.info(f"Created ServiceAccount helm-installer in vcluster-{name}.")
    except ApiException as e:
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = f"Failed to create ServiceAccount: {e.reason}"
            raise

    try:
        rbac.create_cluster_role_binding(body=make_cluster_role_binding(name))
        logger.info(f"Created ClusterRoleBinding helm-installer-{name}.")
    except ApiException as e:
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = f"Failed to create ClusterRoleBinding: {e.reason}"
            raise


def reconcile_install_job(spec: kopf.Spec, name: str, patch: kopf.Patch, logger) -> bool:
    batch = client.BatchV1Api()
    namespace = f"vcluster-{name}"
    job_name = f"helm-install-{name}"

    try:
        job = batch.read_namespaced_job(name=job_name, namespace=namespace)
    except ApiException as e:
        if e.status != 404:
            raise

        patch.status["phase"] = Phase.PROVISIONING
        patch.status["message"] = "Creating helm install job."
        try:
            batch.create_namespaced_job(
                namespace=namespace,
                body=make_helm_install_job(name, vcluster_version=settings.vcluster_version),
            )
            logger.info(f"Created Job {job_name}.")
        except ApiException as create_err:
            if create_err.status != 409:
                patch.status["phase"] = Phase.ERROR
                patch.status["message"] = f"Failed to create helm install job: {create_err.reason}"
                raise
        return False

    if job.status.succeeded:
        return True

    if job.status.failed:
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = "Helm install job failed."
        return False

    patch.status["phase"] = Phase.PENDING
    patch.status["message"] = "Helm install job running."
    return False


def reconcile_vcluster_state(spec: kopf.Spec, name: str, patch: kopf.Patch, logger) -> None:
    apps = client.AppsV1Api()
    vcluster_name = f"vcluster-{name}"

    try:
        vc_set = apps.read_namespaced_stateful_set(name=vcluster_name, namespace=vcluster_name)
    except ApiException as e:
        if e.status == 404:
            patch.status["phase"] = Phase.PENDING
            patch.status["message"] = "Waiting for vCluster StatefulSet to appear."
            return
        
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise

    current_annotations = vc_set.metadata.annotations or {}

    currently_paused = current_annotations.get("loft.sh/paused") == "true"
    should_be_paused = spec.get("state", State.RUNNING) == State.SLEEPING

    if should_be_paused and not currently_paused:
        _sleep_vcluster(apps, vc_set, logger)
        patch.status["phase"] = Phase.SLEEPING
        patch.status["message"] = "vCluster sleeping."
        return

    if not should_be_paused and currently_paused:
        _wake_vcluster(apps, vc_set, logger)
        patch.status["phase"] = Phase.WAKING
        patch.status["message"] = "Waking vCluster."
        return

    # Desired and actual pause state already agree -> nothing to change
    if should_be_paused and currently_paused:
        patch.status["phase"] = Phase.SLEEPING
        patch.status["message"] = "vCluster sleeping."
        return

    # Last case: should not be paused, is not paused -> either ready or waking up
    desired_replicas = vc_set.spec.replicas or 0
    ready_replicas = vc_set.status.ready_replicas or 0
    if desired_replicas > 0 and ready_replicas >= desired_replicas:
        patch.status["phase"] = Phase.READY
        patch.status["message"] = "vCluster is ready."
    else:
        patch.status["phase"] = Phase.WAKING
        patch.status["message"] = "Waking vCluster."


def _sleep_vcluster(apps, vc_set, logger) -> None:
    if not vc_set.spec.replicas or vc_set.spec.replicas <= 0:
        return

    current_annotations = vc_set.metadata.annotations or {}
    vc_set.metadata.annotations = {
        **current_annotations,
        "loft.sh/paused": "true",
        "loft.sh/paused-date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "loft.sh/paused-replicas": str(vc_set.spec.replicas),
    }
    vc_set.spec.replicas = 0

    apps.patch_namespaced_stateful_set(
        name=vc_set.metadata.name,
        namespace=vc_set.metadata.namespace,
        body=vc_set
    )
    logger.info(f"Scaled down StatefulSet of vCluster {vc_set.metadata.name}.")


def _wake_vcluster(apps, vc_set, logger) -> None:
    current_annotations = vc_set.metadata.annotations or {}
    original_replicas = int(current_annotations.get("loft.sh/paused-replicas", 1))

    vc_set.metadata.annotations = {
        "loft.sh/paused": None,
        "loft.sh/paused-date": None,
        "loft.sh/paused-replicas": None,
    }
    vc_set.spec.replicas = original_replicas

    apps.patch_namespaced_stateful_set(
        name=vc_set.metadata.name,
        namespace=vc_set.metadata.namespace,
        body=vc_set
    )
    logger.info(f"Scaled up StatefulSet of vCluster {vc_set.metadata.name}.")
