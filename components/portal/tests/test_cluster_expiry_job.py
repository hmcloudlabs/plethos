from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, create_autospec

import pytest

from cluster_expiry_job import _check_vcluster_claim, check_inactive_clusters
from config import config
from kube.vclusterclaim_model import ExpiryAnnotation
from kube.vclusterclaim_repository import VClusterClaimRepository
from mailer import EmailDeliveryError
from shared.vclusterclaim import State

EXPIRY = config.expiry_period_days
GRACE = config.grace_period_days
LEAD = config.warning_lead_days

# A comfortable margin past a threshold, so ">=" comparisons never flake on timing jitter.
PAST = 0.01


@pytest.fixture
def repo():
    return create_autospec(VClusterClaimRepository, instance=True)


@pytest.fixture(autouse=True)
def send_email_mock(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("cluster_expiry_job.send_email", mock)
    return mock


def _vcluster_claim(
    make_vcluster_claim,
    *,
    renewed_days_ago: float,
    object_name: str | None = None,
    annotations: dict | None = None,
    state: State = State.RUNNING,
):
    renewed_at = (datetime.now(UTC) - timedelta(days=renewed_days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    return make_vcluster_claim(
        object_name=object_name,
        state=state,
        annotations={ExpiryAnnotation.RENEWED_AT: renewed_at, **(annotations or {})},
    )


class TestNotExpiredClaim:
    def test_does_nothing_for_non_expired_claim(self, make_vcluster_claim, repo, send_email_mock):
        claim = _vcluster_claim(make_vcluster_claim, renewed_days_ago=1)

        _check_vcluster_claim(repo, claim)

        send_email_mock.assert_not_called()
        repo.patch_annotations.assert_not_called()
        repo.patch_state.assert_not_called()
        repo.delete.assert_not_called()


class TestSleepWarningStage:
    def test_warns_and_sets_annotation_once_past_lead_time_of_expiry(
        self, make_vcluster_claim, repo, send_email_mock
    ):
        claim = _vcluster_claim(make_vcluster_claim, renewed_days_ago=EXPIRY - LEAD + PAST)

        _check_vcluster_claim(repo, claim)

        send_email_mock.assert_called_once()
        assert "put to sleep soon" in send_email_mock.call_args.kwargs["subject"]
        repo.patch_annotations.assert_called_once_with(
            claim.object_name, {ExpiryAnnotation.SLEEP_WARNING: "True"}
        )
        repo.patch_state.assert_not_called()
        repo.delete.assert_not_called()

    def test_does_not_repeat_if_already_warned(self, make_vcluster_claim, repo, send_email_mock):
        claim = _vcluster_claim(
            make_vcluster_claim,
            renewed_days_ago=EXPIRY - LEAD + PAST,
            annotations={ExpiryAnnotation.SLEEP_WARNING: "True"},
        )

        _check_vcluster_claim(repo, claim)

        send_email_mock.assert_not_called()
        repo.patch_annotations.assert_not_called()


class TestExpiryStage:
    def test_sleeps_cluster_warns_and_marks_expired_once_past_expiry_date(
        self, make_vcluster_claim, repo, send_email_mock
    ):
        claim = _vcluster_claim(make_vcluster_claim, renewed_days_ago=EXPIRY + PAST)

        _check_vcluster_claim(repo, claim)

        repo.patch_state.assert_called_once_with(claim.object_name, State.SLEEPING)
        send_email_mock.assert_called_once()
        assert "has been put to sleep" in send_email_mock.call_args.kwargs["subject"]
        repo.patch_annotations.assert_called_once_with(
            claim.object_name, {ExpiryAnnotation.EXPIRED: "True"}
        )

    def test_warns_and_marks_expired_even_if_already_asleep(
        self, make_vcluster_claim, repo, send_email_mock
    ):
        """
        The cluster might already be asleep because the owner set it asleep manuall,
        we still add the annotations and send the warning email.
        """

        claim = _vcluster_claim(
            make_vcluster_claim, renewed_days_ago=EXPIRY + PAST, state=State.SLEEPING
        )

        _check_vcluster_claim(repo, claim)

        repo.patch_state.assert_not_called()  # no re-patch SLEEPING state, since it's already asleep
        send_email_mock.assert_called_once()
        repo.patch_annotations.assert_called_once_with(
            claim.object_name, {ExpiryAnnotation.EXPIRED: "True"}
        )

    def test_does_not_repeat_if_already_expired(self, make_vcluster_claim, repo, send_email_mock):
        claim = _vcluster_claim(
            make_vcluster_claim,
            renewed_days_ago=EXPIRY + PAST,
            annotations={ExpiryAnnotation.SLEEP_WARNING: "True", ExpiryAnnotation.EXPIRED: "True"},
            state=State.SLEEPING,
        )

        _check_vcluster_claim(repo, claim)

        send_email_mock.assert_not_called()
        repo.patch_state.assert_not_called()
        repo.patch_annotations.assert_not_called()


class TestDeletionWarningStage:
    def test_warns_once_past_lead_time_of_deletion(
        self, make_vcluster_claim, repo, send_email_mock
    ):
        claim = _vcluster_claim(
            make_vcluster_claim,
            renewed_days_ago=EXPIRY + GRACE - LEAD + PAST,
            annotations={ExpiryAnnotation.EXPIRED: "True"},
            state=State.SLEEPING,
        )

        _check_vcluster_claim(repo, claim)

        send_email_mock.assert_called_once()
        assert "will be deleted soon" in send_email_mock.call_args.kwargs["subject"]
        repo.patch_annotations.assert_called_once_with(
            claim.object_name, {ExpiryAnnotation.DELETION_WARNING: "True"}
        )
        repo.delete.assert_not_called()

    def test_does_not_repeat_if_already_warned(self, make_vcluster_claim, repo, send_email_mock):
        claim = _vcluster_claim(
            make_vcluster_claim,
            renewed_days_ago=EXPIRY + GRACE - LEAD + PAST,
            annotations={
                ExpiryAnnotation.SLEEP_WARNING: "True",
                ExpiryAnnotation.EXPIRED: "True",
                ExpiryAnnotation.DELETION_WARNING: "True",
            },
            state=State.SLEEPING,
        )

        _check_vcluster_claim(repo, claim)

        send_email_mock.assert_not_called()
        repo.patch_annotations.assert_not_called()
        repo.delete.assert_not_called()


class TestDeletionStage:
    def test_deletes_once_grace_period_is_over_and_it_was_warned(self, make_vcluster_claim, repo):
        claim = _vcluster_claim(
            make_vcluster_claim,
            renewed_days_ago=EXPIRY + GRACE + PAST,
            annotations={
                ExpiryAnnotation.EXPIRED: "True",
                ExpiryAnnotation.DELETION_WARNING: "True",
            },
            state=State.SLEEPING,
        )

        _check_vcluster_claim(repo, claim)

        repo.delete.assert_called_once_with(claim.object_name)

    def test_never_deletes_without_a_deletion_warning_having_been_sent(
        self, make_vcluster_claim, repo, send_email_mock
    ):
        """Make sure nothing gets deleted without having send deletion warning first. This should not happen, but better safe than sorry."""

        claim = _vcluster_claim(
            make_vcluster_claim,
            renewed_days_ago=EXPIRY + GRACE + PAST,
            annotations={ExpiryAnnotation.EXPIRED: "True"},
            state=State.SLEEPING,
        )

        _check_vcluster_claim(repo, claim)

        repo.delete.assert_not_called()
        send_email_mock.assert_called_once()
        repo.patch_annotations.assert_called_once_with(
            claim.object_name, {ExpiryAnnotation.DELETION_WARNING: "True"}
        )


class TestFailedWarningEmail:
    def test_does_not_mark_as_warned_if_the_email_failed(
        self, make_vcluster_claim, repo, send_email_mock
    ):
        send_email_mock.side_effect = EmailDeliveryError("smtp is down")
        claim = _vcluster_claim(make_vcluster_claim, renewed_days_ago=EXPIRY - LEAD + PAST)

        with pytest.raises(EmailDeliveryError):
            _check_vcluster_claim(repo, claim)

        repo.patch_annotations.assert_not_called()


class TestCheckInactiveClusters:
    def test_continues_processing_after_one_claim_fails(self, make_vcluster_claim, repo):
        broken = make_vcluster_claim(object_name="broken", creation_timestamp=None, annotations={})

        healthy = _vcluster_claim(
            make_vcluster_claim,
            object_name="healthy",
            renewed_days_ago=EXPIRY + GRACE + PAST,
            annotations={
                ExpiryAnnotation.EXPIRED: "True",
                ExpiryAnnotation.DELETION_WARNING: "True",
            },
            state=State.SLEEPING,
        )

        repo.list_all.return_value = [broken, healthy]

        check_inactive_clusters(repo)

        repo.delete.assert_called_once_with("healthy")
