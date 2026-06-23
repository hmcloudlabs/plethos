import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from resources import (
    make_namespace,
    make_service_account,
    make_cluster_role_binding,
    make_helm_install_job,
)
from utils import load_kube_config
from config import settings


@kopf.on.startup()
def on_startup(logger, **_: object) -> None:
    load_kube_config()
    logger.info("Kubernetes config loaded.")


@kopf.on.create(GROUP, VERSION, PLURAL)
def on_create(spec: kopf.Spec, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim created: {name}.")

    if not name or name.startswith("vcluster"):
        raise kopf.PermanentError(f"Invalid resource name '{name}'.")

    patch.status["phase"] = Phase.PROVISIONING
    patch.status["message"] = "Creating namespace and RBAC."

    core = client.CoreV1Api()
    rbac = client.RbacAuthorizationV1Api()
    batch = client.BatchV1Api()

    # 1. create namespace
    try:
        core.create_namespace(body=make_namespace(name))
        logger.info(f"Created namespace vcluster-{name}.")
    except ApiException as e:
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = f"Failed to create namespace: {e.reason}"
            raise

    # 2. create service account
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

    # 3. create cluster role binding
    try:
        rbac.create_cluster_role_binding(body=make_cluster_role_binding(name))
        logger.info(f"Created ClusterRoleBinding helm-installer-{name}.")
    except ApiException as e:
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = f"Failed to create ClusterRoleBinding: {e.reason}"
            raise

    patch.status["message"] = "Running helm install job."

    # 4. create helm install job
    try:
        batch.create_namespaced_job(
            namespace=f"vcluster-{name}",
            body=make_helm_install_job(name, vcluster_version=settings.vcluster_version),
        )
        logger.info(f"Created Job helm-install-{name}.")
    except ApiException as e:
        if e.status != 409:
            patch.status["phase"] = Phase.ERROR
            patch.status["message"] = f"Failed to run helm Job: {e.reason}."
            raise

    patch.status["phase"] = Phase.PENDING
    patch.status["message"] = "Helm install job running."


@kopf.on.field("batch/v1", "jobs", field="status", labels={f"{GROUP}/vcluster-claim": kopf.PRESENT})
def on_job_status(labels, status, logger, **_: object) -> None:
    custom = client.CustomObjectsApi()

    vc_claim_name = labels[f"{GROUP}/vcluster-claim"]

    logger.info(f"Updating status of VClusterClaim resource {vc_claim_name}.")

    if status.get("succeeded"):
        custom.patch_namespaced_custom_object_status(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=settings.namespace,
            name=vc_claim_name,
            body={"status": {"phase": Phase.READY, "message": "VCluster is ready."}},
        )
        logger.info(f"Helm install job finished successfully. vCluster '{vc_claim_name}' is ready.")

    elif status.get("failed"):
        custom.patch_namespaced_custom_object_status(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=settings.namespace,
            name=vc_claim_name,
            body={"status": {"phase": Phase.ERROR, "message": "Helm install failed."}},
        )
        logger.info(f"Helm install job faild. vCluster '{vc_claim_name}' could not be provisioned.")


@kopf.on.update(GROUP, VERSION, PLURAL)
def on_update(spec: kopf.Spec, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim updated: {name}.")

    # TODO: update the vCluster


@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim deleted: {name}.")

    patch.status["phase"] = Phase.DELETING

    # TODO: delete the vCluster
