
from datetime import datetime, UTC
import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from utils import get_statefulset, unwrap_statefulset
from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase, State


@kopf.on.update(GROUP, VERSION, PLURAL, field="spec.state")
def on_state_change(spec, name, patch, old, new, logger, **_: object) -> None:
    logger.info(f"Reconciling State of VClusterClaim {name}.")

    if new == State.SLEEPING:
        _sleep_vcluster(name, patch, logger)
    elif new == State.RUNNING:
        _wake_vcluster(name, patch, logger)


def _sleep_vcluster(name: str, patch, logger) -> None:
    patch.status["phase"] = Phase.SLEEPING
    patch.status["message"] = "Putting vCluster asleep."

    apps = client.AppsV1Api()

    try:
        vc_set = get_statefulset(
            apps,
            name=f"vcluster-{name}",
            namespace=f"vcluster-{name}",
        )
  
    except ApiException as e:
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise

    spec, metadata = unwrap_statefulset(vc_set)

    if spec.replicas > 0:
        metadata.annotations = {
            **(metadata.annotations or {}),
            "loft.sh/paused": "true",
            "loft.sh/paused-date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "loft.sh/paused-replicas": str(spec.replicas),
        }
        spec.replicas = 0

        apps.patch_namespaced_stateful_set(
            name=metadata.name,
            namespace=f"vcluster-{name}",
            body=vc_set,
        )

        patch.status["message"] = "vCluster sleeping."
        logger.info(f"Scaled down StatefulSet {metadata.name} in vcluster-{name}.")


def _wake_vcluster(name: str, patch, logger) -> None:
    patch.status["phase"] = Phase.WAKING
    patch.status["message"] = "Waking vCluster."

    apps = client.AppsV1Api()

    try:
        vc_set = get_statefulset(
            apps,
            name=f"vcluster-{name}",
            namespace=f"vcluster-{name}",
        )
    except ApiException as e:
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise

    spec, metadata = unwrap_statefulset(vc_set)

    annotations = dict(metadata.annotations or {})
    if annotations.get("loft.sh/paused") == "true":
        original_replicas = int(annotations.get("loft.sh/paused-replicas", 1))

        # Explicit None marks these for deletion in a strategic merge patch
        metadata.annotations = {
            "loft.sh/paused": None,
            "loft.sh/paused-date": None,
            "loft.sh/paused-replicas": None,
        }
        spec.replicas = original_replicas

        apps.patch_namespaced_stateful_set(
            name=metadata.name,
            namespace=f"vcluster-{name}",
            body=vc_set,
        )

        patch.status["phase"] = Phase.READY
        patch.status["message"] = "VCluster is ready."

        logger.info(f"Scaled up StatefulSet {metadata.name} in vcluster-{name}.")


@kopf.on.update(GROUP, VERSION, PLURAL, field="spec.accessRules")
def on_access_rules_change(meta, patch, name, logger, **_: object) -> None:
    logger.info(f"accessRules changed for VClusterClaim {name}.")
    patch.status["observedGeneration"] = meta["generation"]