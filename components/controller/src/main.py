import kopf

from utils import load_kube_config


@kopf.on.startup()
def on_startup(logger, **_: object) -> None:
    load_kube_config()
    logger.info("Kubernetes config loaded.")
