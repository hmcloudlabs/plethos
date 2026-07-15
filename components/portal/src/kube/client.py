
from functools import lru_cache

import kubernetes
from kubernetes import client


def load_kube_config() -> None:
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()


@lru_cache(maxsize=1)
def custom_objects_api() -> client.CustomObjectsApi:
    """Shared CustomObjectsApi client, that is cached so we reuse one client/connection pool. """
    
    return client.CustomObjectsApi()
