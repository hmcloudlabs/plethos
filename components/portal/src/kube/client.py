import logging
from functools import lru_cache
import kubernetes
from kubernetes import client

logger = logging.getLogger(__name__)


def load_kube_config() -> None:
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster kube config")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kube config")


@lru_cache(maxsize=1)
def custom_objects_api() -> client.CustomObjectsApi:
    """Shared CustomObjectsApi client, that is cached so we reuse one client/connection pool."""

    return client.CustomObjectsApi()


@lru_cache(maxsize=1)
def core_v1_api() -> client.CoreV1Api:
    """Shared CoreV1Api client (used to read the vCluster kubeconfig Secret)."""

    return client.CoreV1Api()
