import kopf

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase


@kopf.on.create(GROUP, VERSION, PLURAL)
def on_create(spec: kopf.Spec, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim created: f{name}.")

    # TODO: provision the vCluster

    patch.status["phase"] = Phase.PENDING
    patch.status["message"] = "Awaiting provisioning"


@kopf.on.update(GROUP, VERSION, PLURAL)
def on_update(spec: kopf.Spec, name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim updated: f{name}.")

    # TODO: update the vCluster


@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name: str | None, patch: kopf.Patch, logger, **_: object) -> None:
    logger.info(f"VClusterClaim deleted: f{name}.")

    patch.status["phase"] = Phase.DELETING

    # TODO: delete the vCluster

