import kopf

from kube import load_kube_config

import handlers.reconcile  # noqa: F401
import handlers.delete  # noqa: F401


@kopf.on.startup()
def on_startup(logger, **_: object) -> None:
    load_kube_config()
    logger.info("Kubernetes config loaded.")
