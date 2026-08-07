import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import kopf
from kubernetes import client

from config import config
from conftest import NAMESPACE, wait_for_404, wait_for_condition, wait_for_phase
from context import ReconciliationContext, VClusterNames
from handlers.reconcile import compute_claim_expiration, handle_claim_expiration
from kube import get_statefulset, unwrap_statefulset
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


class TestComputeClaimExpiration:
    def test_recently_active_is_not_inactive(self):
        ctx = make_ctx(status={"lastActiveAt": _iso(datetime.now(UTC))})

        expiration = compute_claim_expiration(ctx)

        assert not expiration.is_inactive
        assert not expiration.is_suspended
        assert not expiration.is_expired

    def test_inactive_after_threshold(self):
        last_active = datetime.now(UTC) - timedelta(days=config.inactivity_threshold_days, hours=1)
        ctx = make_ctx(status={"lastActiveAt": _iso(last_active)})

        expiration = compute_claim_expiration(ctx)

        assert expiration.is_inactive
        assert not expiration.is_suspended
        assert not expiration.is_expired

    def test_scheduled_for_sleep_after_one_grace_period(self):
        last_active = datetime.now(UTC) - timedelta(
            days=config.inactivity_threshold_days + config.expiration_grace_period_days, hours=1
        )
        ctx = make_ctx(status={"lastActiveAt": _iso(last_active)})

        expiration = compute_claim_expiration(ctx)

        assert expiration.is_inactive
        assert expiration.is_suspended
        assert not expiration.is_expired

    def test_scheduled_for_deletion_after_two_grace_periods(self):
        last_active = datetime.now(UTC) - timedelta(
            days=config.inactivity_threshold_days + 2 * config.expiration_grace_period_days, hours=1
        )
        ctx = make_ctx(status={"lastActiveAt": _iso(last_active)})

        expiration = compute_claim_expiration(ctx)

        assert expiration.is_inactive
        assert expiration.is_suspended
        assert expiration.is_expired


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

    def test_writes_both_conditions(self):
        ctx = make_ctx(status={"lastActiveAt": _iso(datetime.now(UTC))})

        handle_claim_expiration(ctx)

        types = {c["type"] for c in ctx.patch.status["conditions"]}
        assert types == {
            ConditionType.INACTIVE,
            ConditionType.SUSPENDED,
        }
        assert condition(ctx, ConditionType.INACTIVE)["status"] == "False"


class TestExpirationLifecycle:
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

    def test_inactive_condition_after_inactivity_threshold(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        Crossing the inactivity threshold sets `Inactive` condition to true 
        but without yet triggering sleep or deletion.
        """

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        self._patch_last_active_days_ago(clients, resource_name, config.inactivity_threshold_days + 1)

        obj = wait_for_condition(clients.custom, resource_name, "Inactive", "True")
        conditions = {c["type"]: c["status"] for c in obj["status"]["conditions"]}

        # But not yet scheduled for deletion
        assert conditions["Suspended"] == "False"

    def test_auto_sleep_after_inactivity_and_grace_period(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        Crossing inactivity threshold and one grace period, the vCluster is 
        put to sleep automatically.
        """

        names = VClusterNames(resource_name)
        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        self._patch_last_active_days_ago(
            clients,
            resource_name,
            config.inactivity_threshold_days + config.expiration_grace_period_days + 1,
        )

        wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        apps = client.AppsV1Api()
        vc_set = get_statefulset(apps, names.vcluster, names.namespace)
        vc_set_spec, vc_set_metadata, _ = unwrap_statefulset(vc_set)

        assert vc_set_spec.replicas == 0
        assert vc_set_metadata.annotations.get("loft.sh/paused") == "true"

    def test_auto_delete_after_inactivity_and_two_grace_periods(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        Crossing inactivity threshold and two grace periods, the VClusterClaim
        resource is deleted automatically and tthe vCluster therefore cleaned up.
        """

        names = VClusterNames(resource_name)
        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        self._patch_last_active_days_ago(
            clients,
            resource_name,
            config.inactivity_threshold_days + 2 * config.expiration_grace_period_days + 1,
        )

        wait_for_404(
            lambda: clients.custom.get_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                plural=PLURAL,
                namespace=NAMESPACE,
                name=resource_name,
            ),
            resource_type="VClusterClaim",
        )
        wait_for_404(
            lambda: clients.core.read_namespace(name=names.namespace),
            resource_type="Namespace",
        )

    def test_owner_action_resets_expiration_clock(
        self, operator, clients, create_vcluster_claim, resource_name
    ):
        """
        Any owner spec change resets lastActiveAt, clearing the expiration
        conditions and waking the vCluster even though it was auto-slept.
        """

        create_vcluster_claim()
        wait_for_phase(clients.custom, resource_name, Phase.READY)

        self._patch_last_active_days_ago(
            clients,
            resource_name,
            config.inactivity_threshold_days + config.expiration_grace_period_days + 1,
        )
        wait_for_phase(clients.custom, resource_name, Phase.SLEEPING)

        # Making a spec change by adding a member to a VClusterClaim should
        # mark the VClusterClaim as active, ie. `Inactive` is False
        clients.custom.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            plural=PLURAL,
            namespace=NAMESPACE,
            name=resource_name,
            body={"spec": {"members": [{"email": "member@example.com"}]}},
        )

        obj = wait_for_phase(clients.custom, resource_name, Phase.READY)
        conditions = {c["type"]: c["status"] for c in obj["status"]["conditions"]}
        assert conditions["Inactive"] == "False"
        assert conditions["Suspended"] == "False"
