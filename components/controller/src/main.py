import kopf

from shared.vclusterclaim import GROUP, PLURAL, VERSION
from utils import load_kube_config

#import controllers.create
#import controllers.update
import controllers.delete
import controllers.reconcilation


@kopf.on.startup()
def on_startup(logger, **_: object) -> None:
    load_kube_config()
    logger.info("Kubernetes config loaded.")
