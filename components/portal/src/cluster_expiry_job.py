"""
Standalone entrypoint: checks every VClusterClaim for prolonged inactivity, sending owners a
warning email (with a keep-alive link) before sleeping and eventually deleting their cluster.

Meant to be run on a schedule by something external to the portal - a k8s CronJob, in-cluster,
reusing the portal's own image and ServiceAccount (see k8s/base/notifier/cronjob.yaml) - rather
than as a background task inside the portal process. That keeps this a single, one-shot run per
tick no matter how many portal replicas exist, instead of every replica running its own copy.

    python src/cluster_expiry_job.py
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from config import config
from kube.client import load_kube_config
from kube.vclusterclaim_model import VClusterClaim
from kube.vclusterclaim_repository import VClusterClaimRepository
from logging_setup import setup_logging
from mailer import send_email
from shared.vclusterclaim import State
from tokens import keep_alive_tokens

logger = logging.getLogger(__name__)


def check_inactive_clusters(repo: VClusterClaimRepository) -> None:
    for claim in repo.list_all():
        try:
            _check_vcluster_claim(repo, claim)
        except Exception:
            logger.exception(f"Inactivity check failed for cluster '{claim.object_name}'")


def _check_vcluster_claim(repo: VClusterClaimRepository, claim: VClusterClaim) -> None:
    renewed_at = cast(str, repo.get_renewed_at(claim.object_name) or claim.creation_timestamp)
    time_since_renewal = datetime.now(UTC) - datetime.strptime(renewed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    warning_lead = timedelta(days=config.warning_lead_days)

    sleep_at = timedelta(days=config.expiry_period_days)
    delete_at = sleep_at + timedelta(days=config.grace_period_days)

    has_sleep_warning = repo.has_sleep_warning(claim.object_name)
    has_deletion_warning = repo.has_deletion_warning(claim.object_name)
    has_already_expired = repo.has_expired(claim.object_name)

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
        repo.add_auto_deletion_warning(claim.object_name)

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
        repo.mark_as_expired(claim.object_name)

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
        repo.add_auto_sleep_warning(claim.object_name)

        logger.info(f"Sent expiry warning for cluster '{claim.object_name}'")


def _send_warning_email(claim: VClusterClaim, *, subject: str, body_intro: str) -> None:
    token = keep_alive_tokens.generate({"object_name": claim.object_name})
    confirm_url = f"{config.portal_base_url}/keep-alive/confirm?token={token}"

    send_email(
        to=claim.spec.owner_email,
        subject=subject,
        body=f"{body_intro}\n\nConfirm you're still using it: {confirm_url}",
    )


def main() -> None:
    setup_logging()
    load_kube_config()
    check_inactive_clusters(VClusterClaimRepository())


if __name__ == "__main__":
    main()
