import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import kopf

from config import config
from conftest import NAMESPACE, wait_for_condition, wait_for_phase
from context import ReconciliationContext
from handlers.reconcile import track_activity
from shared.vclusterclaim import GROUP, PLURAL, VERSION, ConditionType, Phase

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


class TestTrackActivity:
    def test_recently_active_is_not_inactive(self):
        ctx = make_ctx(status={"observedGeneration": 1, "lastActiveAt": _iso(datetime.now(UTC))})

        track_activity(ctx)

        assert condition(ctx, ConditionType.INACTIVE)["status"] == "False"

    def test_inactive_after_threshold(self):
        last_active = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days, hours=1)
        ctx = make_ctx(status={"observedGeneration": 1, "lastActiveAt": _iso(last_active)})

        track_activity(ctx)

        assert condition(ctx, ConditionType.INACTIVE)["status"] == "True"

    def test_resets_last_active_at_when_generation_advances(self):
        old = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days + 5)
        ctx = make_ctx(status={"observedGeneration": 1, "lastActiveAt": _iso(old)}, generation=2)

        track_activity(ctx)

        assert "lastActiveAt" in ctx.patch.status
        assert condition(ctx, ConditionType.INACTIVE)["status"] == "False"

    def test_keeps_last_active_at_when_generation_unchanged(self):
        old = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days + 5)
        ctx = make_ctx(status={"observedGeneration": 2, "lastActiveAt": _iso(old)}, generation=2)

        track_activity(ctx)

        assert "lastActiveAt" not in ctx.patch.status
        assert condition(ctx, ConditionType.INACTIVE)["status"] == "True"


class TestActivityLifecycle:
    def _patch_last_active_days_ago(self, clients, name: str, days_ago: float) -> None:
        """Used to simulate inactivity by patching an old date into `status.lastActiveAt`"""

        last_active_at = _iso(datetime.now(UTC) - timedelta(days=days_ago))
        clients.custom.patch_namespaced_custom_object_status(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=name,
            body={"status": {"lastActiveAt": last_active_at}},
        )

    def test_inactive_condition_after_threshold(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """Crossing the inactivity threshold sets `Inactive` to true; the vCluster keeps running."""

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        self._patch_last_active_days_ago(clients, resource_name, config.inactivity_threshold_days + 1)

        obj = wait_for_condition(clients.custom, resource_name, "Inactive", "True")

        # Still running - the controller doesn't act on the condition
        assert obj["status"]["phase"] == Phase.READY

    def test_owner_action_resets_inactivity_clock(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """Any owner spec change resets `lastActiveAt`, clearing the `Inactive` condition."""

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        self._patch_last_active_days_ago(clients, resource_name, config.inactivity_threshold_days + 1)
        wait_for_condition(clients.custom, resource_name, "Inactive", "True")

        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"members": [{"email": "member@example.com"}]}},
        )

        obj = wait_for_condition(clients.custom, resource_name, "Inactive", "False")
        assert obj["status"]["phase"] == Phase.READY
