from datetime import datetime, UTC
from typing import cast
import kopf
from kubernetes import client
from kubernetes.client import V1PodList, V1StatefulSet
from kubernetes.client.exceptions import ApiException

from shared.gateway import GatewayConvention
from shared.vclusterclaim import GROUP, PLURAL, VERSION, ConditionType, Phase, State
from context import ReconciliationContext
from resources import (
    make_namespace,
    make_service_account,
    make_cluster_role_binding,
    make_helm_install_job,
    make_gateway_ingress,
)
from config import config
from kube import (
    JobStatus,
    get_job_status,
    get_job,
    get_statefulset,
    unwrap_statefulset,
    get_crd_object,
    find_gateway_service_name,
    is_namespace_managed,
    SCALED_DOWN_REPLICAS_ANNOTATION,
    VCLUSTER_MANAGED_BY_LABEL,
)


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.timer(GROUP, VERSION, PLURAL, interval=config.reconciliation_interval)
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

    ensure_namespace(ctx)
    ensure_service_account(ctx)
    ensure_rbac(ctx)

    vc_set = get_vcluster(ctx)
    if not vc_set:
        provision_vcluster(ctx)
    else:
        reconcile_vcluster(ctx, vc_set)

    ensure_gateway_exposure(ctx)

    sync_ready_condition(ctx)

    ctx.patch.status["observedGeneration"] = ctx.generation


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
    version = ctx.spec.get("vClusterVersion")
    if version not in config.supported_vcluster_versions:
        ctx.patch.status["phase"] = Phase.ERROR
        ctx.patch.status["message"] = (
            f"vCluster version '{version}' is not supported by this controller (supported: {config.supported_vcluster_versions})."
        )
        return

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
                    vcluster_version=version,
                    base_domain=config.base_domain,
                    ingress_namespace=config.ingress_namespace,
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
        ctx.patch.status["phase"] = Phase.PROVISIONING
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
    vc_set_spec, _, vc_set_status = unwrap_statefulset(vc_set)

    should_be_sleeping = ctx.spec.get("state", State.RUNNING) == State.SLEEPING
    vcluster_scaled_down = (vc_set_spec.replicas or 0) == 0

    if should_be_sleeping:
        if not vcluster_scaled_down:
            sleep_vcluster(ctx.clients.apps, vc_set, ctx.logger)

        # When it should be sleeping, delete all workload pods. Has to be checked every
        # reconciliation cycle because the syncer recreates them until the control plane is gone.
        delete_workload_pods(ctx)

        ctx.patch.status["phase"] = Phase.SLEEPING
        ctx.patch.status["message"] = "vCluster sleeping."
        return

    if not should_be_sleeping and vcluster_scaled_down:
        wake_vcluster(ctx.clients.apps, vc_set, ctx.logger)
        ctx.patch.status["phase"] = Phase.WAKING
        ctx.patch.status["message"] = "Waking vCluster."
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


def delete_workload_pods(ctx: ReconciliationContext) -> None:
    """
    Finds and deletes all running workload pods. They will be recreated if the vCluster control plane
    has one or more replicas (pods not running in a StatefulSet or ReplicaSet will be deleted forever)
    """

    label_selector = f"{VCLUSTER_MANAGED_BY_LABEL}={ctx.names.vcluster}"

    try:
        synced_pods = cast(
            V1PodList,
            ctx.clients.core.list_namespaced_pod(
                namespace=ctx.names.namespace,
                label_selector=label_selector,
                resource_version="0",
            ),
        ).items or []

        running_pods = [
            pod for pod in synced_pods
            if pod.metadata is None or pod.metadata.deletion_timestamp is None
        ]
        if len(running_pods) > 0:
            ctx.clients.core.delete_collection_namespaced_pod(
                namespace=ctx.names.namespace,
                label_selector=label_selector,
            )
            ctx.logger.info(
                f"Deleted {len(running_pods)} workload pod(s) of sleeping vCluster {ctx.names.vcluster}."
            )
    except ApiException as e:
        ctx.patch.status["phase"] = Phase.ERROR
        ctx.patch.status["message"] = f"Failed to delete workload pods: {e.reason}"
        raise


def sleep_vcluster(apps, vc_set, logger) -> None:
    """
    Scales the vCluster control plane replicas to 0, so that deleted user workload pods aren't resynced.
    """

    if not vc_set.spec.replicas or vc_set.spec.replicas <= 0:
        return

    current_annotations = vc_set.metadata.annotations or {}
    vc_set.metadata.annotations = {
        **current_annotations,
        SCALED_DOWN_REPLICAS_ANNOTATION: str(vc_set.spec.replicas),
    }
    vc_set.spec.replicas = 0

    apps.patch_namespaced_stateful_set(
        name=vc_set.metadata.name, namespace=vc_set.metadata.namespace, body=vc_set
    )
    logger.info(f"Scaled down StatefulSet of vCluster {vc_set.metadata.name}.")


def wake_vcluster(apps, vc_set, logger) -> None:
    current_annotations = vc_set.metadata.annotations or {}
    original_replica_amount = int(current_annotations.get(SCALED_DOWN_REPLICAS_ANNOTATION, 1))

    vc_set.metadata.annotations = {SCALED_DOWN_REPLICAS_ANNOTATION: None}
    vc_set.spec.replicas = original_replica_amount

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
            namespace=config.namespace,
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
            namespace=config.namespace,
            name=ctx.name,
            body={"status": dict(ctx.patch.status)},
        )
    except ApiException as e:
        if e.status != 404:
            raise


@kopf.on.field("batch/v1", "jobs", field="status", labels={f"{GROUP}/job-type": "install"})
def on_install_job_event(labels, logger, **_: object) -> None:
    reconcile_claim_by_name(labels[f"{GROUP}/vcluster-claim"], logger)


def sync_ready_condition(ctx: ReconciliationContext) -> None:
    """Derives `Ready` from `status.phase`, so `kubectl wait --for=condition=Ready` works."""

    phase = ctx.patch.status.get("phase")
    if phase is not None:
        set_condition(
            ctx,
            cond_type=ConditionType.READY,
            cond_status="True" if phase == Phase.READY else "False",
            reason=str(phase),
            message=ctx.patch.status.get("message", ""),
        )


def ensure_gateway_exposure(ctx: ReconciliationContext) -> None:
    """
    Makes the vCluster's gateway host (see `GatewayConvention`) reach whatever the owner has
    deployed behind their gateway Service. Skipped if `base_domain` isn't configured, the
    namespace wasn't provisioned by this controller, or no such Service is deployed.
    """

    if not config.base_domain:
        return

    # Don't touch vCluster namespaces not provisioned/managed by this controller
    if not is_namespace_managed(ctx.clients.core, ctx.names.namespace):
        return

    gateway_service_on_host = find_gateway_service_name(ctx.clients.core, ctx.names)
    if not gateway_service_on_host:
        return

    ensure_gateway_ingress(ctx, gateway_service_on_host)


def ensure_gateway_ingress(ctx: ReconciliationContext, target_service: str) -> None:
    host = GatewayConvention.host(ctx.names.vcluster, config.base_domain)
    ingress_manifest = make_gateway_ingress(
        host,
        ctx.names.namespace,
        target_service,
    )

    try:
        ctx.clients.networking.create_namespaced_ingress(
            namespace=ctx.names.namespace, body=ingress_manifest
        )
        ctx.logger.info(f"Created Ingress gateway in {ctx.names.namespace}.")
    except ApiException as e:
        if e.status != 409:
            ctx.patch.status["phase"] = Phase.ERROR
            ctx.patch.status["message"] = f"Failed to create gateway Ingress: {e.reason}"
            raise


def set_condition(
    ctx: ReconciliationContext, *, cond_type: str, cond_status: str, reason: str, message: str
) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    conditions = ctx.patch.status.get("conditions") or ctx.status.get("conditions") or []
    conditions = {c["type"]: dict(c) for c in conditions}

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
