import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from resources import make_helm_uninstall_job
from utils import get_job, unwrap_job


@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    if not name:
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    logger.info(f"Deleting vCluster {name}.")

    patch.status["phase"] = Phase.DELETING

    namespace = f"vcluster-{name}"
    job_name = f"helm-uninstall-{name}"

    batch = client.BatchV1Api()
    core = client.CoreV1Api()

    # Check if namespace still exists, otherwise a helm uninstall job can't be run
    try:
        core.read_namespace(name=namespace)
    except ApiException as e:
        if e.status == 404:
            cleanup_cluster_scoped_resources(name, logger)
            logger.info(f"Namespace {namespace} already gone, nothing to clean up.")
            return
        raise

    # If the helm uninstall job doesn't exist yet, create it
    try:
        job = get_job(batch, name=job_name, namespace=namespace)
    except ApiException as e:
        if e.status != 404:
            raise
        
        try:
            batch.create_namespaced_job(namespace=namespace, body=make_helm_uninstall_job(name))
            logger.info(f"Created Job {job_name}.")
        except ApiException as create_err:
            if create_err.status not in (403, 404, 409):
                patch.status["phase"] = Phase.ERROR
                patch.status["message"] = (
                    f"Failed to delete vCluster resources via helm job: {create_err.reason}."
                )
                raise

        raise kopf.TemporaryError("Uninstall job created, waiting for completion.", delay=10)

    current_job_status, _ = unwrap_job(job)

    if current_job_status.succeeded:
        cleanup_cluster_scoped_resources(name, logger)
        return

    if current_job_status.failed:
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = "Helm uninstall job failed."
        raise kopf.TemporaryError("Uninstall job failed, will keep retrying.", delay=30)

    raise kopf.TemporaryError("Uninstall job still running.", delay=10)


def cleanup_cluster_scoped_resources(name: str, logger) -> None:
    rbac = client.RbacAuthorizationV1Api()
    core = client.CoreV1Api()

    try:
        rbac.delete_cluster_role_binding(name=f"helm-installer-{name}")
        logger.info(f"Deleted ClusterRoleBinding helm-installer-{name}.")
    except ApiException as e:
        if e.status != 404:
            raise

    try:
        core.delete_namespace(name=f"vcluster-{name}")
        logger.info(f"Deleted namespace vcluster-{name}.")
    except ApiException as e:
        if e.status != 404:
            raise