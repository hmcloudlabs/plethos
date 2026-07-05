from typing import cast
import kubernetes
from kubernetes import client
from kubernetes.client import V1StatefulSet


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


def unwrap_statefulset(vc: V1StatefulSet):
    if vc.spec is None or vc.metadata is None:
        raise ValueError("Invalid StatefulSet: missing spec/metadata")
    return vc.spec, vc.metadata