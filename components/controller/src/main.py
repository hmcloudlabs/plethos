import kopf

from shared.vclusterclaim import GROUP, PLURAL, VERSION
from utils import load_kube_config

import controllers.create
import controllers.update
import controllers.delete


@kopf.on.startup()
def on_startup(logger, **_: object) -> None:
    load_kube_config()
    logger.info("Kubernetes config loaded.")


@kopf.on.update(GROUP, VERSION, PLURAL)
def on_update(spec: kopf.Spec, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim updated: {name}.")

    # TODO: update the vCluster
