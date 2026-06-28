
from datetime import datetime, UTC
import kopf
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase, State


@kopf.on.update(GROUP, VERSION, PLURAL, field="spec.State")
def on_desired_state_change(spec, name, patch, old, new, logger, **_: object) -> None:
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
        vc_set = apps.read_namespaced_stateful_set(
            name=f"vcluster-{name}",
            namespace=f"vcluster-{name}"
        )
    except ApiException as e:
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise

    if vc_set.spec.replicas > 0:
        vc_set.metadata.annotations = {
            **(vc_set.metadata.annotations or {}),
            "loft.sh/paused": "true",
            "loft.sh/paused-date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "loft.sh/paused-replicas": str(vc_set.spec.replicas),
        }
        vc_set.spec.replicas = 0

        apps.patch_namespaced_stateful_set(
            name=vc_set.metadata.name,
            namespace=f"vcluster-{name}",
            body=vc_set,
        )

        patch.status["message"] = "vCluster sleeping."

        logger.info(f"Scaled down StatefulSet {vc_set.metadata.name} in vcluster-{name}.")


def _wake_vcluster(name: str, patch, logger) -> None:
    patch.status["phase"] = Phase.WAKING
    patch.status["message"] = "Waking vCluster."

    apps = client.AppsV1Api()

    try:
        vc_set = apps.read_namespaced_stateful_set(
            name=f"vcluster-{name}",
            namespace=f"vcluster-{name}"
        )
    except ApiException as e:
        patch.status["phase"] = Phase.ERROR
        patch.status["message"] = f"Failed to get the vCluster StatefulSet: {e.reason}"
        raise

    annotations = vc_set.metadata.annotations or {}
    if annotations.get("loft.sh/paused") == "true":
        original_replicas = int(annotations.get("loft.sh/paused-replicas", 1))

        annotations.pop("loft.sh/paused", None)
        annotations.pop("loft.sh/paused-date", None)
        annotations.pop("loft.sh/paused-replicas", None)
        vc_set.metadata.annotations = annotations
        vc_set.spec.replicas = original_replicas

        apps.patch_namespaced_stateful_set(
            name=vc_set.metadata.name,
            namespace=f"vcluster-{name}",
            body=vc_set,
        )

        patch.status["phase"] = Phase.READY
        patch.status["message"] = "VCluster is ready."

        logger.info(f"Scaled up StatefulSet {vc_set.metadata.name} in vcluster-{name}.")