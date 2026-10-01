from enum import StrEnum
import hashlib
from typing import cast
import kubernetes
from kubernetes import client
from kubernetes.client import V1Job
from kubernetes.client import V1Namespace
from kubernetes.client import V1StatefulSet

from shared.app import AppExposureConvention
from shared.vclusterclaim import GROUP, Phase


# Set by vCluster's syncer on every object it copies to the host cluster, recording which
# vCluster synced it.
VCLUSTER_MANAGED_BY_LABEL = "vcluster.loft.sh/managed-by"

# Set by us (not vCluster) when sleeping a vCluster, to remember what to scale it back up to
SCALED_DOWN_REPLICAS_ANNOTATION = f"{GROUP}/scaled-down-replicas"

# Phases of a vCluster set during state transitions
TRANSITIONAL_PHASES = frozenset({Phase.PROVISIONING, Phase.PENDING, Phase.WAKING})


class JobStatus(StrEnum):
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"


def load_kube_config() -> None:
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()


def get_statefulset(
    apps: client.AppsV1Api,
    name: str,
    namespace: str,
) -> V1StatefulSet:
    obj = apps.read_namespaced_stateful_set(
        name=name,
        namespace=namespace,
    )
    return cast(V1StatefulSet, obj)


def unwrap_statefulset(sts: V1StatefulSet):
    if sts.spec is None or sts.metadata is None or sts.status is None:
        raise ValueError("Invalid StatefulSet: missing spec/metadata.")
    return sts.spec, sts.metadata, sts.status


def get_job(
    batch: client.BatchV1Api,
    name: str,
    namespace: str,
) -> V1Job:
    obj = batch.read_namespaced_job(
        name=name,
        namespace=namespace,
    )
    return cast(V1Job, obj)


def unwrap_job(job: V1Job):
    if job.status is None or job.metadata is None:
        raise ValueError("Invalid Job: missing status/metadata.")
    return job.status, job.metadata


def get_job_status(job: V1Job) -> JobStatus:
    job_status, _ = unwrap_job(job)

    for condition in job_status.conditions or []:
        if condition.type == "Complete" and condition.status == "True":
            return JobStatus.SUCCEEDED
        if condition.type == "Failed" and condition.status == "True":
            return JobStatus.FAILED

    return JobStatus.RUNNING


def is_transitional(status, **_: object) -> bool:
    """Checks whether the status of a VClusterClaim in a transitional phase"""

    return (status or {}).get("phase") in TRANSITIONAL_PHASES


def app_service_host_name(vcluster_name: str) -> str:
    """
    The host-cluster name of the vClusters's app Service, which an owner deploys inside their
    vCluster as `AppExposureConvention.SERVICE_NAME` in `AppExposureConvention.NAMESPACE`.
    vCluster's syncer renames synced objects to `<name>-x-<namespace>-x-<vcluster>`. Once longer
    than 63 characters, it cuts that to 52 characters plus a hash of the full name, ported from
    vCluster's `translate.SafeConcatName` (v0.35.0).

    Note: This function is tightly coupled with vCluster's internal implementation and must be watched carefully.
    Newer vCluster versions might break this. In this case we might fall back to finding Services on the host by
    their vCluster annotations instead.
    """

    full_name = f"{AppExposureConvention.SERVICE_NAME}-x-{AppExposureConvention.NAMESPACE}-x-{vcluster_name}"
    if len(full_name) <= 63:
        return full_name

    digest = hashlib.sha256(full_name.encode()).hexdigest()
    return f"{full_name[:52]}-{digest[:10]}".replace(".-", "-")


def is_namespace_managed(core: client.CoreV1Api, namespace: str) -> bool:
    """Whether a given `namespace` was created by the Plethos controller."""

    ns = cast(V1Namespace, core.read_namespace(name=namespace))
    if ns.metadata is None:
        raise ValueError("Invalid Namespace: missing metadata.")

    return (ns.metadata.labels or {}).get(f"{GROUP}/managed") == "true"
