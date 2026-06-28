import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from resources import make_helm_uninstall_job


@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"Deleting VClusterClaim: {name}.")

    if not name:
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    patch.status["phase"] = Phase.DELETING

    batch = client.BatchV1Api()

    try:
        batch.create_namespaced_job(
            namespace=f"vcluster-{name}",
            body=make_helm_uninstall_job(name),
        )
        logger.info(f"Created Job helm-uninstall-{name}.")
    except ApiException as e:
        if e.status in (404, 403):
            logger.info(f"Namespace vcluster-{name} already gone, skipping uninstall.")
            return
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = (
                f"Failed to delete vCluster resources via helm job: {e.reason}."
            )
            raise


@kopf.on.field("batch/v1", "jobs", field="status", labels={f"{GROUP}/job-type": "uninstall"})
def on_uninstall_job_status(labels, status, logger, **_: object) -> None:
    if not status.get("succeeded"):
        return

    vc_claim_name = labels[f"{GROUP}/vcluster-claim"]
    logger.info(f"Helm uninstall job succeeded for {vc_claim_name}, cleaning up.")

    core = client.CoreV1Api()
    rbac = client.RbacAuthorizationV1Api()

    try:
        rbac.delete_cluster_role_binding(name=f"helm-installer-{vc_claim_name}")
        logger.info(f"Deleted ClusterRoleBinding helm-installer-{vc_claim_name}.")
    except ApiException as e:
        if e.status != 404:
            raise

    try:
        core.delete_namespace(name=f"vcluster-{vc_claim_name}")
        logger.info(f"Deleted namespace vcluster-{vc_claim_name}.")
    except ApiException as e:
        if e.status != 404:
            raise
