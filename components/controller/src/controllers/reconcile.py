from datetime import datetime, UTC
import kopf
from kubernetes import client
from kubernetes.client import V1StatefulSet
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
from kube import (
    JobStatus,
    get_job_status,
    get_job,
    get_statefulset,
    unwrap_statefulset,
    get_crd_object,
)


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.timer(GROUP, VERSION, PLURAL, interval=settings.reconciliation_interval)
def on_reconcile(
    spec: kopf.Spec, meta, name: str | None, patch: kopf.Patch, status, logger, **_: object
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
            status=status,
            logger=logger,
        )
    )


def reconcile(ctx: ReconciliationContext) -> None:
    ctx.logger.info(f"Reconciliation started for {ctx.name}.")

    ctx.patch.status["observedGeneration"] = ctx.generation

    ensure_namespace(ctx)
    ensure_service_account(ctx)
    ensure_rbac(ctx)

    vc_set = get_vcluster(ctx)
    if not vc_set:
        provision_vcluster(ctx)
    else:
        reconcile_vcluster(ctx, vc_set)

    sync_conditions(ctx)


def sync_conditions(ctx: ReconciliationContext) -> None:
    """
    Derive the status conditions from the state gathered during this reconcile.
    These conditions are used for machine-readable condition tooling which expects
    `kubectl wait --for=condition=Ready`.

    Conditions:
        * `Ready`: Only `True` when the vCluster is actually up, otherwise `False` with 
          the `status.phase` as the reason (Provisioning, Pending, Sleeping, ...)
        * futher conditions get derived here
    """

    # Sync `Ready` condition
    phase = ctx.patch.status.get("phase")
    if phase is not None:
        set_condition(
            ctx,
            cond_type="Ready",
            cond_status="True" if phase == Phase.READY else "False",
            reason=str(phase),
            message=ctx.patch.status.get("message", ""),
        )


def set_condition(
    ctx: ReconciliationContext, *, cond_type: str, cond_status: str, reason: str, message: str
) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conditions = {c["type"]: dict(c) for c in (ctx.status.get("conditions") or [])}

    previous = conditions.get(cond_type)
    if previous and previous.get("status") == cond_status:
        last_transition = previous.get("lastTransitionTime", now)
    else:
        last_transition = now

    conditions[cond_type] = {
        "type": cond_type,
        "status": cond_status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": last_transition,
        "observedGeneration": ctx.generation,
    }
    ctx.patch.status["conditions"] = list(conditions.values())


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


def provision_vcluster(ctx: ReconciliationContext) -> None:
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
        except ApiException as e:
            if e.status != 409:
                ctx.patch.status["phase"] = Phase.ERROR
                ctx.patch.status["message"] = f"Failed to create helm install job: {e.reason}"

        return

    status = get_job_status(job)

    # Running -> installation in progress, will retry on failures
    if status is JobStatus.RUNNING:
        ctx.patch.status["phase"] = Phase.PENDING
        ctx.patch.status["message"] = "Helm install job running."

    # Failed after all retries -> will be deleted by the Job's TTL and retried next reconciliation loop
    elif status is JobStatus.FAILED:
        ctx.patch.status["phase"] = Phase.PROVISIONING
        ctx.patch.status["message"] = "Helm install job failed."

    # Finished but vCluster isn't there -> same as above: the TTL
    # deletes the job and the next reconciliation cycle recreates it.
    elif status is JobStatus.SUCCEEDED:
        ctx.patch.status["phase"] = Phase.PROVISIONING
        ctx.patch.status["message"] = "Helm install job finished but no vCluster found, will retry."


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


def reconcile_vcluster(ctx: ReconciliationContext, vc_set: V1StatefulSet) -> None:
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

    # Last case: should not be sleeping, is not sleeping -> either ready or getting ready after wakeup
    desired_replicas = vc_set_spec.replicas or 0
    ready_replicas = vc_set_status.ready_replicas or 0
    if desired_replicas > 0 and ready_replicas >= desired_replicas:
        ctx.patch.status["phase"] = Phase.READY
        ctx.patch.status["message"] = "vCluster is ready."
    else:
        ctx.patch.status["phase"] = Phase.PENDING
        ctx.patch.status["message"] = "Waiting for vCluster to be ready."


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
        status=claim.get("status") or {},
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
