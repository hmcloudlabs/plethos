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

from config import config
from kube.client import load_kube_config
from kube.vclusterclaim_model import VClusterClaim
from kube.vclusterclaim_repository import VClusterClaimRepository
from logging_setup import setup_logging
from mailer import send_email
from shared.vclusterclaim import ConditionType, State
from tokens import keep_alive_tokens

logger = logging.getLogger(__name__)


def check_inactive_clusters(repo: VClusterClaimRepository) -> None:
    for claim in repo.list_all():
        try:
            _check_vcluster_claim(repo, claim)
        except Exception:
            logger.exception(f"Inactivity check failed for cluster '{claim.object_name}'")


def _check_vcluster_claim(repo: VClusterClaimRepository, claim: VClusterClaim) -> None:
    if not claim.status.has_condition(ConditionType.INACTIVE):

        # Activity can reset through paths other than the keep-alive link (e.g. through manually waking, editing members),
        # which don't otherwise clear these annotations. Check for and remove these dangling annoations.
        if repo.has_sleep_warning_annotation(claim.object_name) or repo.has_deletion_warning_annotation(claim.object_name):
            repo.clear_inactivity_warning_annotations(claim.object_name)
        return

    if claim.status.last_active_at is None:
        return

    inactive_for = datetime.now(UTC) - datetime.strptime(claim.status.last_active_at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )

    inactivity_threshold = timedelta(days=config.inactivity_period_days)
    sleep_threshold = inactivity_threshold + timedelta(days=config.notice_period_days)
    delete_threshold = sleep_threshold + timedelta(days=config.notice_period_days)

    has_sleep_warning = repo.has_sleep_warning_annotation(claim.object_name)
    has_deletion_warning = repo.has_deletion_warning_annotation(claim.object_name)

    # Final stage of inactiveness: Delete the cluster
    if inactive_for >= delete_threshold and has_deletion_warning:
        repo.delete(claim.object_name)

        logger.info(f"Deleted cluster '{claim.object_name}' because of inactivity")
        return

    # Second stage: Put cluster to sleep and warn about possible deletion
    if inactive_for >= sleep_threshold and not has_deletion_warning:
        repo.patch_state(claim.object_name, State.SLEEPING)
        _send_warning_email(
            claim,
            subject=f"Cluster '{claim.spec.name}' put to sleep, will be deleted soon",
            body_intro=(
                f"Cluster '{claim.spec.name}' has been inactive and was put to sleep. "
                f"It will be deleted in {config.notice_period_days:g} day(s) unless you confirm "
                f"you're still using it."
            ),
        )
        repo.mark_deletion_warning_annotation(claim.object_name)

        logger.info(f"Sent deletion warning for cluster '{claim.object_name}'")
        return

    # First stage: Warn about inactivness and automatic sleeping
    if inactive_for >= inactivity_threshold and not has_sleep_warning:
        _send_warning_email(
            claim,
            subject=f"Cluster '{claim.spec.name}' will be put to sleep soon",
            body_intro=(
                f"Cluster '{claim.spec.name}' has been inactive. It will be put to sleep in "
                f"{config.notice_period_days:g} day(s) unless you confirm you're still using it."
            ),
        )
        repo.mark_sleep_warning_annotation(claim.object_name)

        logger.info(f"Sent sleep warning for cluster '{claim.object_name}'")


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
