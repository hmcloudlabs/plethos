from enum import StrEnum
from typing import cast
import kubernetes
from kubernetes import client
from kubernetes.client import V1Job
from kubernetes.client import V1Namespace
from kubernetes.client import V1ServiceList
from kubernetes.client import V1StatefulSet

from shared.app import AppExposureConvention
from shared.vclusterclaim import GROUP, Phase
from context import VClusterNames


# Set by vCluster's syncer on every object it copies to the host cluster, recording which
# vCluster synced it and its name/namespace inside the virtual cluster.
VCLUSTER_MANAGED_BY_LABEL = "vcluster.loft.sh/managed-by"
VCLUSTER_OBJECT_NAME_ANNOTATION = "vcluster.loft.sh/object-name"
VCLUSTER_OBJECT_NAMESPACE_ANNOTATION = "vcluster.loft.sh/object-namespace"

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


def find_app_service_name(core: client.CoreV1Api, names: VClusterNames) -> str | None:
    """
    Finds the host-cluster name of the owner's app Service, which they deploy inside their
    vCluster as `AppExposureConvention.SERVICE_NAME` in `AppExposureConvention.NAMESPACE`, by
    matching the labels/annotations vCluster sets on every object it syncs. Returns `None` if no
    such Service exists yet.
    """

    host_synced_services = cast(
        V1ServiceList,
        core.list_namespaced_service(
            namespace=names.namespace,
            label_selector=f"{VCLUSTER_MANAGED_BY_LABEL}={names.vcluster}",
        ),
    )

    for service in host_synced_services.items or []:
        if service.metadata is None:
            continue

        annotations = service.metadata.annotations or {}
        if (
            annotations.get(VCLUSTER_OBJECT_NAME_ANNOTATION) == AppExposureConvention.SERVICE_NAME
            and annotations.get(VCLUSTER_OBJECT_NAMESPACE_ANNOTATION)
            == AppExposureConvention.NAMESPACE
        ):
            return service.metadata.name

    return None


def is_namespace_managed(core: client.CoreV1Api, namespace: str) -> bool:
    """Whether this controller created a given `namespace`."""

    ns = cast(V1Namespace, core.read_namespace(name=namespace))
    if ns.metadata is None:
        raise ValueError("Invalid Namespace: missing metadata.")

    return (ns.metadata.labels or {}).get(f"{GROUP}/managed") == "true"
