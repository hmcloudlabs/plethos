import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import kopf

from config import config
from context import ReconciliationContext
from handlers.reconcile import compute_claim_expiration, handle_claim_expiration
from shared.vclusterclaim import ConditionType

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _iso(dt: datetime) -> str:
    return dt.strftime(TIME_FORMAT)


def make_ctx(*, status=None, generation=1) -> ReconciliationContext:
    return ReconciliationContext(
        name="test-claim",
        spec=cast(kopf.Spec, {}),
        meta=cast(kopf.Meta, {"generation": generation}),
        patch=kopf.Patch(),
        status=status or {},
        logger=logging.getLogger("test"),
    )


def condition(ctx: ReconciliationContext, cond_type: str) -> dict:
    return next(c for c in ctx.patch.status["conditions"] if c["type"] == cond_type)


class TestComputeClaimExpiration:
    def test_recently_active_is_not_inactive(self):
        ctx = make_ctx(status={"lastActiveAt": _iso(datetime.now(UTC))})

        expiration = compute_claim_expiration(ctx)

        assert not expiration.is_inactive
        assert not expiration.is_scheduled_for_sleep
        assert not expiration.is_scheduled_for_deletion

    def test_inactive_after_threshold(self):
        last_active = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days, hours=1)
        ctx = make_ctx(status={"lastActiveAt": _iso(last_active)})

        expiration = compute_claim_expiration(ctx)

        assert expiration.is_inactive
        assert not expiration.is_scheduled_for_sleep
        assert not expiration.is_scheduled_for_deletion

    def test_scheduled_for_sleep_after_one_grace_period(self):
        last_active = datetime.now(UTC) - timedelta(
            days=config.inactivity_threshold_days + config.expiration_grace_period_days, hours=1
        )
        ctx = make_ctx(status={"lastActiveAt": _iso(last_active)})

        expiration = compute_claim_expiration(ctx)

        assert expiration.is_inactive
        assert expiration.is_scheduled_for_sleep
        assert not expiration.is_scheduled_for_deletion

    def test_scheduled_for_deletion_after_two_grace_periods(self):
        last_active = datetime.now(UTC) - timedelta(
            days=config.inactivity_threshold_days + 2 * config.expiration_grace_period_days, hours=1
        )
        ctx = make_ctx(status={"lastActiveAt": _iso(last_active)})

        expiration = compute_claim_expiration(ctx)

        assert expiration.is_inactive
        assert expiration.is_scheduled_for_sleep
        assert expiration.is_scheduled_for_deletion


class TestHandleClaimExpiration:
    def test_resets_last_active_at_when_generation_advances(self):
        old = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days + 5)
        ctx = make_ctx(status={"observedGeneration": 1, "lastActiveAt": _iso(old)}, generation=2)

        expiration = handle_claim_expiration(ctx)

        assert "lastActiveAt" in ctx.patch.status
        assert not expiration.is_inactive

    def test_keeps_last_active_at_when_generation_unchanged(self):
        old = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days + 5)
        ctx = make_ctx(status={"observedGeneration": 2, "lastActiveAt": _iso(old)}, generation=2)

        expiration = handle_claim_expiration(ctx)

        assert "lastActiveAt" not in ctx.patch.status
        assert expiration.is_inactive

    def test_writes_all_three_conditions(self):
        ctx = make_ctx(status={"lastActiveAt": _iso(datetime.now(UTC))})

        handle_claim_expiration(ctx)

        types = {c["type"] for c in ctx.patch.status["conditions"]}
        assert types == {
            ConditionType.INACTIVE,
            ConditionType.SCHEDULED_FOR_SLEEP,
            ConditionType.SCHEDULED_FOR_DELETION,
        }
        assert condition(ctx, ConditionType.INACTIVE)["status"] == "False"
