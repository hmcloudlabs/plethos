from typing import Any, cast
import kubernetes
from kubernetes import client
from kubernetes.client import V1Job
from kubernetes.client import V1StatefulSet

from enums import JobStatus


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

    if job_status.succeeded:
        return JobStatus.SUCCEEDED

    if job_status.failed:
        return JobStatus.FAILED

    return JobStatus.RUNNING


def get_crd_object(
    custom: client.CustomObjectsApi,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
) -> dict[str, Any]:
    obj = custom.get_namespaced_custom_object(
        group=group, version=version, plural=plural,
        namespace=namespace, name=name,
    )
    return cast(dict[str, Any], obj)