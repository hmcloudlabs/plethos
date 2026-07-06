from datetime import datetime, UTC
import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase, State
from context import ReconciliationContext
from resources import (
    make_namespace,
    make_service_account,
    make_cluster_role_binding,
    make_helm_install_job,
)
from config import settings
from utils import get_job, get_statefulset, unwrap_job, unwrap_statefulset, get_crd_object


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.timer(GROUP, VERSION, PLURAL, interval=settings.reconciliation_interval)
def on_reconcile(spec: kopf.Spec, meta, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    if not name or name.startswith("vcluster"):
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    reconcile(ReconciliationContext(
        name=name,
        spec=spec,
        meta=meta,
        patch=patch,
        logger=logger,
    ))


def reconcile(ctx: ReconciliationContext) -> None:
    ctx.logger.info(f"Reconciliation started for {ctx.name}.")

    reconcile_namespace_and_rbac(ctx)

    installed = reconcile_install_job(ctx)
    if installed:
        reconcile_vcluster_state(ctx)

    ctx.patch.status["observedGeneration"] = ctx.generation


def reconcile_namespace_and_rbac(ctx: ReconciliationContext) -> None:
    core = client.CoreV1Api()
    rbac = client.RbacAuthorizationV1Api()

    try:
        core.create_namespace(body=make_namespace(ctx.names.namespace))
        ctx.logger.info(f"Created namespace {ctx.names.namespace}.")
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create namespace: {e.reason}"
            raise

    try:
        core.create_namespaced_service_account(
            namespace=ctx.names.namespace,
            body=make_service_account(ctx.names.namespace, ctx.names.service_account),
        )
        ctx.logger.info(f"Created ServiceAccount helm-installer in {ctx.names.namespace}.")
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create ServiceAccount: {e.reason}"
            raise

    try:
        rbac.create_cluster_role_binding(body=make_cluster_role_binding(ctx.name, ctx.names.crb))
        ctx.logger.info(f"Created ClusterRoleBinding helm-installer-{ctx.name}.")
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create ClusterRoleBinding: {e.reason}"
            raise


def reconcile_install_job(ctx: ReconciliationContext) -> bool:
    batch = client.BatchV1Api()

    try:
        job = get_job(batch, name=ctx.names.install_job, namespace=ctx.names.namespace)
    except ApiException as e:
        if e.status != 404:
            raise

        ctx.patch.status["phase"] = Phase.PROVISIONING
        ctx.patch.status["message"] = "Creating helm install job."

        try:
            batch.create_namespaced_job(
                namespace=ctx.names.namespace,
                body=make_helm_install_job(
                    ctx.names.namespace,
                    ctx.names.install_job,
                    ctx.names.vcluster,
                    vcluster_version=settings.vcluster_version),
            )
            ctx.logger.info(f"Created Job {ctx.names.install_job}.")
        except ApiException as create_err:
            if create_err.status != 409:
                ctx.patch.status["phase"] = Phase.ERROR
                ctx.patch.status["message"] = f"Failed to create helm install job: {create_err.reason}"
                raise

        return False
    
    current_job_status, _ = unwrap_job(job)

    if current_job_status.succeeded:
        return True

    if current_job_status.failed:
        ctx.patch.status["phase"] = Phase.ERROR
        ctx.patch.status["message"] = "Helm install job failed."
        return False

    ctx.patch.status["phase"] = Phase.PENDING
    ctx.patch.status["message"] = "Helm install job running."
    return False


def reconcile_vcluster_state(ctx: ReconciliationContext) -> None:
    apps = client.AppsV1Api()

    try:
        vc_set = get_statefulset(apps, name=ctx.name, namespace=ctx.names.namespace)
    except ApiException as e:
        if e.status == 404:
            ctx.patch.status["phase"] = Phase.PENDING
            ctx.patch.status["message"] = "Waiting for vCluster StatefulSet to appear."
            return
        
        ctx.patch.status["phase"] = Phase.ERROR
        ctx.patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise

    vc_set_spec, vc_set_metadata, vc_set_status = unwrap_statefulset(vc_set)

    currently_sleeping = (vc_set_metadata.annotations or {}).get("loft.sh/paused") == "true"
    should_be_sleeping = ctx.spec.get("state", State.RUNNING) == State.SLEEPING

    if should_be_sleeping and not currently_sleeping:
        sleep_vcluster(apps, vc_set, ctx.logger)
        ctx.patch.status["phase"] = Phase.SLEEPING
        ctx.patch.status["message"] = "vCluster sleeping."
        return

    if not should_be_sleeping and currently_sleeping:
        wake_vcluster(apps, vc_set, ctx.logger)
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
        name=vc_set.metadata.name,
        namespace=vc_set.metadata.namespace,
        body=vc_set
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
        name=vc_set.metadata.name,
        namespace=vc_set.metadata.namespace,
        body=vc_set
    )
    logger.info(f"Scaled up StatefulSet of vCluster {vc_set.metadata.name}.")


def reconcile_claim_by_name(claim_name: str, logger) -> None:
    custom = client.CustomObjectsApi()

    try:
        claim = get_crd_object(
            custom, group=GROUP, version=VERSION, plural=PLURAL,
            namespace=settings.namespace, name=claim_name,
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