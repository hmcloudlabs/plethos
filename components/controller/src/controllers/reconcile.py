from datetime import datetime, UTC
import kopf
from kubernetes import client
from kubernetes.client import V1StatefulSet
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase, State
from context import ReconciliationContext
from enums import JobStatus
from resources import (
    make_namespace,
    make_service_account,
    make_cluster_role_binding,
    make_helm_install_job,
)
from config import settings
from utils import get_job_status, get_job, get_statefulset, unwrap_statefulset, get_crd_object


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.timer(GROUP, VERSION, PLURAL, interval=settings.reconciliation_interval)
def on_reconcile(
    spec: kopf.Spec, meta, name: str | None, patch: kopf.Patch, logger, **_: object
) -> None:
    """
    Time interval based handler that reconciles the vCluster, while also being
    triggered by a VClusterClaim creation or update event.
    """

    if not name or name.startswith("vcluster"):
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    reconcile(
        ReconciliationContext(
            name=name,
            spec=spec,
            meta=meta,
            patch=patch,
            logger=logger,
        )
    )


def reconcile(ctx: ReconciliationContext) -> None:
    ctx.logger.info(f"Reconciliation started for {ctx.name}.")

    ensure_namespace(ctx)
    ensure_service_account(ctx)
    ensure_rbac(ctx)

    vc_set = get_vcluster(ctx)
    if vc_set is not None:
        reconcile_vcluster_state(ctx, vc_set)
    else:
        provision_vcluster(ctx)

    ctx.patch.status["observedGeneration"] = ctx.generation


def provision_vcluster(ctx: ReconciliationContext) -> None:
    if ensure_install_job(ctx) is not JobStatus.RUNNING:
        remove_install_job(ctx)


def ensure_namespace(ctx: ReconciliationContext) -> None:
    try:
        ctx.clients.core.create_namespace(body=make_namespace(ctx.names.namespace))
        ctx.logger.info(f"Created namespace {ctx.names.namespace}.")
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create namespace: {e.reason}"
            raise


def ensure_service_account(ctx: ReconciliationContext) -> None:
    try:
        ctx.clients.core.create_namespaced_service_account(
            namespace=ctx.names.namespace,
            body=make_service_account(ctx.names.namespace, ctx.names.service_account),
        )
        ctx.logger.info(
            f"Created ServiceAccount {ctx.names.service_account} in {ctx.names.namespace}."
        )
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create ServiceAccount: {e.reason}"
            raise


def ensure_rbac(ctx: ReconciliationContext) -> None:
    try:
        ctx.clients.rbac.create_cluster_role_binding(
            body=make_cluster_role_binding(ctx.names.namespace, ctx.names.crb)
        )
        ctx.logger.info(f"Created ClusterRoleBinding {ctx.names.crb}.")
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create ClusterRoleBinding: {e.reason}"
            raise


def ensure_install_job(ctx: ReconciliationContext) -> JobStatus:
    try:
        job = get_job(ctx.clients.batch, name=ctx.names.install_job, namespace=ctx.names.namespace)
    except ApiException as e:
        if e.status != 404:
            raise

        ctx.patch.status["phase"] = Phase.PROVISIONING
        ctx.patch.status["message"] = "Creating helm install job."

        try:
            ctx.clients.batch.create_namespaced_job(
                namespace=ctx.names.namespace,
                body=make_helm_install_job(
                    ctx.name,
                    ctx.names.namespace,
                    ctx.names.install_job,
                    ctx.names.vcluster,
                    vcluster_version=settings.vcluster_version,
                ),
            )
            ctx.logger.info(f"Created Job {ctx.names.install_job}.")

        except ApiException as create_err:
            if create_err.status != 409:
                ctx.patch.status["phase"] = Phase.ERROR
                ctx.patch.status["message"] = (
                    f"Failed to create helm install job: {create_err.reason}"
                )

                return JobStatus.FAILED

        return JobStatus.RUNNING

    install_job_status = get_job_status(job)

    match install_job_status:
        case JobStatus.FAILED:
            ctx.patch.status["phase"] = Phase.PROVISIONING
            ctx.patch.status["message"] = "Helm install job failed, will retry later."

        case JobStatus.RUNNING:
            ctx.patch.status["phase"] = Phase.PENDING
            ctx.patch.status["message"] = "Helm install job running."

    return install_job_status


def remove_install_job(ctx: ReconciliationContext) -> None:
    try:
        ctx.clients.batch.delete_namespaced_job(
            name=ctx.names.install_job,
            namespace=ctx.names.namespace,
            propagation_policy="Foreground",
        )
    except ApiException as e:
        if e.status != 404:
            raise


def get_vcluster(ctx: ReconciliationContext) -> V1StatefulSet | None:
    try:
        return get_statefulset(
            ctx.clients.apps, name=ctx.names.vcluster, namespace=ctx.names.namespace
        )
    except ApiException as e:
        if e.status == 404:
            return None

        ctx.patch.status["phase"] = Phase.ERROR
        ctx.patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise


def reconcile_vcluster_state(ctx: ReconciliationContext, vc_set: V1StatefulSet) -> None:
    vc_set_spec, vc_set_metadata, vc_set_status = unwrap_statefulset(vc_set)

    currently_sleeping = (vc_set_metadata.annotations or {}).get("loft.sh/paused") == "true"
    should_be_sleeping = ctx.spec.get("state", State.RUNNING) == State.SLEEPING

    if should_be_sleeping and not currently_sleeping:
        sleep_vcluster(ctx.clients.apps, vc_set, ctx.logger)
        ctx.patch.status["phase"] = Phase.SLEEPING
        ctx.patch.status["message"] = "vCluster sleeping."
        return

    if not should_be_sleeping and currently_sleeping:
        wake_vcluster(ctx.clients.apps, vc_set, ctx.logger)
        ctx.patch.status["phase"] = Phase.WAKING
        ctx.patch.status["message"] = "Waking vCluster."
        return

    # Desired and actual sleep state already agree -> nothing to change
    if should_be_sleeping and currently_sleeping:
        ctx.patch.status["phase"] = Phase.SLEEPING
        ctx.patch.status["message"] = "vCluster sleeping."
        return

    # Last case: should not be sleeping, is not sleeping -> either ready or waking up
    desired_replicas = vc_set_spec.replicas or 0
    ready_replicas = vc_set_status.ready_replicas or 0
    if desired_replicas > 0 and ready_replicas >= desired_replicas:
        ctx.patch.status["phase"] = Phase.READY
        ctx.patch.status["message"] = "vCluster is ready."
    else:
        ctx.patch.status["phase"] = Phase.WAKING
        ctx.patch.status["message"] = "Waking vCluster."


def sleep_vcluster(apps, vc_set, logger) -> None:
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
        name=vc_set.metadata.name, namespace=vc_set.metadata.namespace, body=vc_set
    )
    logger.info(f"Scaled down StatefulSet of vCluster {vc_set.metadata.name}.")


def wake_vcluster(apps, vc_set, logger) -> None:
    current_annotations = vc_set.metadata.annotations or {}
    original_replicas = int(current_annotations.get("loft.sh/paused-replicas", 1))

    vc_set.metadata.annotations = {
        "loft.sh/paused": None,
        "loft.sh/paused-date": None,
        "loft.sh/paused-replicas": None,
    }
    vc_set.spec.replicas = original_replicas

    apps.patch_namespaced_stateful_set(
        name=vc_set.metadata.name, namespace=vc_set.metadata.namespace, body=vc_set
    )
    logger.info(f"Scaled up StatefulSet of vCluster {vc_set.metadata.name}.")


def reconcile_claim_by_name(claim_name: str, logger) -> None:
    custom = client.CustomObjectsApi()

    try:
        claim = get_crd_object(
            custom,
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=settings.namespace,
            name=claim_name,
        )
    except ApiException as e:
        if e.status == 404:
            logger.info(f"VClusterClaim '{claim_name}' no longer exists, skipping wake-up.")
            return
        raise

    ctx = ReconciliationContext(
        name=claim["metadata"]["name"],
        spec=claim["spec"],
        meta=claim["metadata"],
        patch=kopf.Patch(),
        logger=logger,
    )

    reconcile(ctx)

    try:
        # Since the here the reconciliation ran outside of a CRD event handler,
        # the status is written manually from the context into the custom resource.
        custom.patch_namespaced_custom_object_status(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=settings.namespace,
            name=ctx.name,
            body={"status": dict(ctx.patch.status)},
        )
    except ApiException as e:
        if e.status != 404:
            raise


@kopf.on.field("batch/v1", "jobs", field="status", labels={f"{GROUP}/job-type": "install"})
def on_install_job_event(labels, logger, **_: object) -> None:
    reconcile_claim_by_name(labels[f"{GROUP}/vcluster-claim"], logger)
