import kopf

from kube import load_kube_config

import controllers.reconcile
import controllers.delete


@kopf.on.startup()
def on_startup(logger, **_: object) -> None:
    load_kube_config()
    logger.info("Kubernetes config loaded.")
