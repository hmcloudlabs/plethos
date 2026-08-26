from enum import StrEnum
from typing import Any, cast
import kubernetes
from kubernetes import client
from kubernetes.client import V1Job
from kubernetes.client import V1Namespace
from kubernetes.client import V1ServiceList
from kubernetes.client import V1StatefulSet

from shared.vclusterclaim import GROUP
from resources import (
    VCLUSTER_MANAGED_BY_LABEL,
    VCLUSTER_OBJECT_NAME_ANNOTATION,
    VCLUSTER_OBJECT_NAMESPACE_ANNOTATION,
    TENANT_GATEWAY_SERVICE_NAME,
    TENANT_GATEWAY_SERVICE_NAMESPACE,
)


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


def find_gateway_service_name(
    core: client.CoreV1Api, host_namespace: str, vcluster_name: str
) -> str | None:
    """
    Finds the host-cluster name for the gateway Service, which might be deployed inside a vCluster 
    under the name `TENANT_GATEWAY_SERVICE_NAME`, by matching the labels/annotations vCluster sets 
    on every object it syncs. Returns `None` if no `TENANT_GATEWAY_SERVICE_NAME` Service exists yet.
    """

    services = cast(
        V1ServiceList,
        core.list_namespaced_service(
            namespace=host_namespace,
            label_selector=f"{VCLUSTER_MANAGED_BY_LABEL}={vcluster_name}",
        ),
    )

    for service in services.items or []:
        if service.metadata is None:
            continue
        
        annotations = service.metadata.annotations or {}
        if (
            annotations.get(VCLUSTER_OBJECT_NAME_ANNOTATION) == TENANT_GATEWAY_SERVICE_NAME
            and annotations.get(VCLUSTER_OBJECT_NAMESPACE_ANNOTATION) == TENANT_GATEWAY_SERVICE_NAMESPACE
        ):
            return service.metadata.name

    return None


def is_namespace_managed(core: client.CoreV1Api, namespace: str) -> bool:
    """Whether this controller's own code created a given `namespace`."""

    ns = cast(V1Namespace, core.read_namespace(name=namespace))
    if ns.metadata is None:
        raise ValueError("Invalid Namespace: missing metadata.")
    
    return (ns.metadata.labels or {}).get(f"{GROUP}/managed") == "true"


def get_crd_object(
    custom: client.CustomObjectsApi,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
) -> dict[str, Any]:
    obj = custom.get_namespaced_custom_object(
        group=group,
        version=version,
        plural=plural,
        namespace=namespace,
        name=name,
    )
    return cast(dict[str, Any], obj)
