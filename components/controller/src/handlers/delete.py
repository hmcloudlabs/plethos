import kopf
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from context import DeletionContext
from resources import make_helm_uninstall_job
from kube import JobStatus, get_job_status, get_job


@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    """
    Delete handler that runs when `metadata.deletionTimestamp` is set on an object
    still holding kopf's finalizer. Kopf checks this also on startup, which is why
    this handler is even-based and not part of a reconciliation loop.
    """

    if not name:
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    delete(DeletionContext(name, patch, logger))


def delete(ctx: DeletionContext) -> None:
    ctx.logger.info(f"Deleting vCluster {ctx.names.vcluster}.")

    ctx.patch.status["phase"] = Phase.DELETING

    # Check if namespace still exists, otherwise a helm uninstall job can't be run
    try:
        ctx.clients.core.read_namespace(name=ctx.names.namespace)
    except ApiException as e:
        if e.status == 404:
            ctx.logger.info(f"Namespace {ctx.names.namespace} already gone, nothing to clean up.")
            return
        raise

    # If the helm uninstall job doesn't exist yet, create it
    try:
        job = get_job(
            ctx.clients.batch, name=ctx.names.uninstall_job, namespace=ctx.names.namespace
        )
    except ApiException as e:
        if e.status != 404:
            raise

        try:
            ctx.clients.batch.create_namespaced_job(
                namespace=ctx.names.namespace,
                body=make_helm_uninstall_job(
                    ctx.claim_name,
                    ctx.names.namespace,
                    ctx.names.service_account,
                    ctx.names.uninstall_job,
                    ctx.names.vcluster,
                ),
            )
            ctx.logger.info(f"Created Job {ctx.names.uninstall_job}.")
        except ApiException as create_err:
            if create_err.status not in (403, 404, 409):
                ctx.patch.status["phase"] = Phase.ERROR
                ctx.patch.status["message"] = (
                    f"Failed to delete vCluster resources via helm job: {create_err.reason}."
                )
                raise

        raise kopf.TemporaryError("Uninstall job created, waiting for completion.", delay=10)

    uninstall_job_status = get_job_status(job)

    match uninstall_job_status:
        case JobStatus.SUCCEEDED:
            delete_namespace(ctx)
        case JobStatus.RUNNING:
            raise kopf.TemporaryError("Uninstall job still running.", delay=10)
        case JobStatus.FAILED:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = "Helm uninstall job failed."
            raise kopf.TemporaryError("Uninstall job failed, will keep retrying.", delay=30)


def delete_namespace(ctx: DeletionContext) -> None:
    """
    Everything the controller creates per vCluster is namespaced, so deleting the namespace is
    the whole cleanup (deletes the ServiceAccount its RoleBinding and the Helm uninstall Job).
    """

    try:
        ctx.clients.core.delete_namespace(name=ctx.names.namespace)
        ctx.logger.info(f"Deleted namespace {ctx.names.namespace}.")
    except ApiException as e:
        if e.status != 404:
            raise
