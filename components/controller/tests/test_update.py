import time
import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from shared.vclusterclaim import GROUP, PLURAL, VERSION, Phase
from conftest import NAMESPACE, wait_for_phase, wait_for_404


class TestUpdate:
    def test_sleep_vcluster(self, operator, custom_api, create_vcluster_claim, resource_name):
        """Changing state to Sleeping should scale down the vCluster StatefulSet."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=120)

        custom_api.patch_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )

        wait_for_phase(custom_api, resource_name, Phase.SLEEPING, timeout=30)

        # verify StatefulSet is scaled down
        apps = client.AppsV1Api()
        vc_set = apps.read_namespaced_stateful_set(
            name=f"vcluster-{resource_name}",
            namespace=f"vcluster-{resource_name}",
        )

        assert vc_set.spec.replicas == 0
        assert vc_set.metadata.annotations.get("loft.sh/paused") == "true"
        assert "loft.sh/paused-replicas" in vc_set.metadata.annotations

    def test_wake_vcluster(self, operator, custom_api, create_vcluster_claim, resource_name):
        """Changing state back to Running should scale up the vCluster StatefulSet."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=120)

        # first sleep
        custom_api.patch_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )
        wait_for_phase(custom_api, resource_name, Phase.SLEEPING, timeout=30)

        # then wake
        custom_api.patch_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
            body={"spec": {"state": "Running"}},
        )
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=30)

        apps = client.AppsV1Api()
        vc_set = apps.read_namespaced_stateful_set(
            name=f"vcluster-{resource_name}",
            namespace=f"vcluster-{resource_name}",
        )

        assert vc_set.spec.replicas > 0
        assert vc_set.metadata.annotations.get("loft.sh/paused") is None

    def test_sleep_already_sleeping(self, operator, custom_api, create_vcluster_claim, resource_name):
        """Setting state to Sleeping when already sleeping should not error."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.READY, timeout=120)

        custom_api.patch_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )
        wait_for_phase(custom_api, resource_name, Phase.SLEEPING, timeout=30)

        # patch again with same value
        custom_api.patch_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
            body={"spec": {"state": "Sleeping"}},
        )

        time.sleep(5)
        obj = custom_api.get_namespaced_custom_object(
            group=GROUP, version=VERSION, plural=PLURAL,
            namespace=NAMESPACE, name=resource_name,
        )
        assert obj["status"]["phase"] != Phase.ERROR

    def test_immutable_fields_rejected(self, operator, custom_api, create_vcluster_claim, resource_name):
        """Changing immutable fields like name or ownerSub should be rejected by the API."""

        create_vcluster_claim()
        wait_for_phase(custom_api, resource_name, Phase.PENDING, timeout=30)

        with pytest.raises(ApiException) as exc_info:
            custom_api.patch_namespaced_custom_object(
                group=GROUP, version=VERSION, plural=PLURAL,
                namespace=NAMESPACE, name=resource_name,
                body={"spec": {"ownerSub": "different-sub"}},
            )
        assert exc_info.value.status == 422