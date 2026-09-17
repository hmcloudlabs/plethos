"""
Standalone entrypoint: checks every VClusterClaim for their upcoming expiration, sending owners a
warning email (with a keep-alive link) before sleeping and eventually deleting their cluster.

Meant to be run on a schedule by something external to the portal, optimally the K8s CRON job
already configured in the /k8s folder.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from config import config
from kube.client import load_kube_config
from kube.vclusterclaim_model import ExpiryAnnotation, VClusterClaim
from kube.vclusterclaim_repository import VClusterClaimRepository
from logging_setup import setup_logging
from mailer import EmailDeliveryError, send_email
from shared.vclusterclaim import State
from templating import templates
from tokens import keep_alive_tokens

logger = logging.getLogger(__name__)


def check_inactive_clusters(repo: VClusterClaimRepository) -> None:
    for claim in repo.list_all():
        try:
            _check_vcluster_claim(repo, claim)
        except EmailDeliveryError as e:
            logger.warning(
                f"Failed to send warning email for cluster '{claim.object_name}'. Error:\n{e}"
            )
        except Exception as e:
            logger.exception(
                f"Inactivity check failed for cluster '{claim.object_name}'. Error:\n{e}"
            )


def _check_vcluster_claim(repo: VClusterClaimRepository, claim: VClusterClaim) -> None:
    renewed_at = claim.renewed_at or datetime.strptime(
        cast(str, claim.creation_timestamp), "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=UTC)
    time_since_renewal = datetime.now(UTC) - renewed_at

    warning_lead = timedelta(days=config.warning_lead_days)

    sleep_at = timedelta(days=config.expiry_period_days)
    delete_at = sleep_at + timedelta(days=config.grace_period_days)

    has_sleep_warning = ExpiryAnnotation.SLEEP_WARNING in claim.annotations
    has_deletion_warning = ExpiryAnnotation.DELETION_WARNING in claim.annotations
    has_already_expired = ExpiryAnnotation.EXPIRED in claim.annotations

    # Final stage: delete the cluster
    if time_since_renewal >= delete_at and has_deletion_warning:
        repo.delete(claim.object_name)

        logger.info(f"Deleted cluster '{claim.object_name}' because it was not renewed in time")
        return

    # Warn that the cluster (already asleep) will be deleted soon
    if time_since_renewal >= delete_at - warning_lead and not has_deletion_warning:
        _send_warning_email(
            claim,
            subject=f"Cluster '{claim.spec.name}' will be deleted soon",
            body_intro=(
                f"Cluster '{claim.spec.name}' is asleep and will be deleted in "
                f"{config.warning_lead_days:g} day(s) unless you confirm you're still using it."
            ),
        )
        repo.patch_annotations(claim.object_name, {ExpiryAnnotation.DELETION_WARNING: "True"})

        logger.info(f"Sent deletion warning for cluster '{claim.object_name}'")
        return

    # Put the cluster to sleep once it's past its expiry date and notify the owner.
    if time_since_renewal >= sleep_at and not has_already_expired:
        if claim.spec.state != State.SLEEPING:
            repo.patch_state(claim.object_name, State.SLEEPING)

        _send_warning_email(
            claim,
            subject=f"Cluster '{claim.spec.name}' has been put to sleep",
            body_intro=(
                f"Cluster '{claim.spec.name}' reached its expiry date and has been put to sleep. "
                f"It will be deleted in {config.grace_period_days:g} day(s) unless you confirm you're still using it."
            ),
        )
        repo.patch_annotations(claim.object_name, {ExpiryAnnotation.EXPIRED: "True"})

        logger.info(f"Cluster '{claim.object_name}' has expired and has been put to sleep")
        return

    # Warn that the cluster will reach its expiry date soon
    if time_since_renewal >= sleep_at - warning_lead and not has_sleep_warning:
        _send_warning_email(
            claim,
            subject=f"Cluster '{claim.spec.name}' will be put to sleep soon",
            body_intro=(
                f"Cluster '{claim.spec.name}' will reach its expiry date in {config.warning_lead_days:g} "
                f"day(s) and will then be put to sleep automatically unless you confirm you're still using it."
            ),
        )
        repo.patch_annotations(claim.object_name, {ExpiryAnnotation.SLEEP_WARNING: "True"})

        logger.info(f"Sent expiry warning for cluster '{claim.object_name}'")


def _send_warning_email(claim: VClusterClaim, *, subject: str, body_intro: str) -> None:
    """
    Callers must check if this raises EmailDeliveryError, because the warning annotations
    must only be written once the owner was actually warned, otherwise the next run would
    sleep or delete the cluster unannounced.
    """

    token = keep_alive_tokens.generate({"object_name": claim.object_name})
    confirm_url = f"{config.portal_base_url}/keep-alive/confirm?token={token}"
    button_text = "Confirm you're still using it"

    html = templates.env.get_template("emails/keep_alive.html").render(
        subject=subject,
        preheader=body_intro,
        heading=subject,
        intro=body_intro,
        button_text=button_text,
        button_url=confirm_url,
        support_email=config.support_email,
    )

    send_email(
        to=claim.spec.owner_email,
        subject=subject,
        body=f"{body_intro}\n\n{button_text}: {confirm_url}",
        html=html,
    )


def main() -> None:
    setup_logging()
    load_kube_config()
    check_inactive_clusters(VClusterClaimRepository())


if __name__ == "__main__":
    main()
