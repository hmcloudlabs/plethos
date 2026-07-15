import base64
from hashlib import sha256
from typing import Any, cast

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from config import config
from kube.client import core_v1_api, custom_objects_api
from kube.vclusterclaim_model import VClusterClaim
from shared.vclusterclaim import (
    GROUP,
    KIND,
    PLURAL,
    VERSION,
    State,
    VClusterClaimSpec,
)

OWNER_LABEL = f"{GROUP}/owner-subject-hash"


def owner_subject_hash(sub: str) -> str:
    return sha256(sub.encode()).hexdigest()[:16]


def vcc_name(sub: str, name: str) -> str:
    return f"{owner_subject_hash(sub)}-{name}"


def vcluster_namespace(sub: str, name: str) -> str:
    return f"vcluster-{vcc_name(sub, name)}"


def kubeconfig_secret_name(sub: str, name: str) -> str:
    return f"vc-vcluster-{vcc_name(sub, name)}"


class VClusterClaimAlreadyExistsError(Exception):
    """Raised when the user already has a cluster with the requested name."""


class VClusterClaimService:
    def __init__(
        self,
        api: client.CustomObjectsApi | None = None,
        core_api: client.CoreV1Api | None = None,
        namespace: str | None = None,
    ) -> None:
        self._api = api or custom_objects_api()
        self._core = core_api or core_v1_api()
        self._namespace = namespace or config.claims_namespace

    def list_for_owner(self, sub: str) -> list[VClusterClaim]:
        res = self._api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            label_selector=f"{OWNER_LABEL}={owner_subject_hash(sub)}",
        )

        claims = [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

        # The label-selector only embeds the sub's hash so re-check raw sub to avoid hash collisions
        return [claim for claim in claims if claim.spec.owner_subject == sub]

    def get(self, sub: str, name: str) -> VClusterClaim | None:
        try:
            obj = self._api.get_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=vcc_name(sub, name),
            )

        except ApiException as e:
            if e.status == 404:
                return None
            raise

        claim = VClusterClaim.from_obj(cast(dict[str, Any], obj))

        # The name only embeds the sub's hash so re-check raw sub to avoid hash collisions
        if claim.spec.owner_subject != sub:
            return None

        return claim

    def create(self, sub: str, email: str, name: str, vcluster_version: str) -> VClusterClaim:
        spec = VClusterClaimSpec(
            name=name,
            owner_subject=sub,
            owner_email=email,
            v_cluster_version=vcluster_version,
        )

        try:
            obj = self._api.create_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                body={
                    "apiVersion": f"{GROUP}/{VERSION}",
                    "kind": KIND,
                    "metadata": {
                        "name": vcc_name(sub, name),
                        "labels": {OWNER_LABEL: owner_subject_hash(sub)},
                    },
                    "spec": spec.model_dump(by_alias=True),
                },
            )

        except ApiException as e:
            if e.status == 409:
                raise VClusterClaimAlreadyExistsError(name) from e
            raise

        return VClusterClaim.from_obj(cast(dict[str, Any], obj))

    def set_state(self, sub: str, name: str, state: State) -> None:
        try:
            self._api.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=vcc_name(sub, name),
                body={"spec": {"state": state.value}},
            )
        except ApiException as e:
            # Tolerate a cluster that was deleted between listing and the action.
            if e.status != 404:
                raise

    def delete(self, sub: str, name: str) -> None:
        try:
            self._api.delete_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=vcc_name(sub, name),
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def get_kubeconfig(self, sub: str, name: str) -> str | None:
        """The vCluster's kubeconfig, or None if the user doesn't own it or it isn't provisioned yet."""

        # Calling get() to re-check spec.ownerSubject
        if self.get(sub, name) is None:
            return None

        try:
            secret = self._core.read_namespaced_secret(
                name=kubeconfig_secret_name(sub, name),
                namespace=vcluster_namespace(sub, name),
            )
        except ApiException as e:
            if e.status == 404:
                return None  # provisioning not finished yet
            raise

        raw = (secret.data or {}).get("config")
        if not raw:
            return None

        return base64.b64decode(raw).decode("utf-8")
