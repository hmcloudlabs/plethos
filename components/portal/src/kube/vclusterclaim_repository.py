import base64
import re
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
    AccessRule,
    State,
    VClusterClaimSpec,
)

OWNER_LABEL = f"{GROUP}/owner-subject-hash"


def owner_subject_hash(sub: str) -> str:
    return sha256(sub.encode()).hexdigest()[:16]


def vcc_name(sub: str, name: str) -> str:
    """The VClusterClaim object name: owner-hash prefix + the user-chosen cluster name."""

    return f"{owner_subject_hash(sub)}-{name}"


def vcluster_namespace(object_name: str) -> str:
    return f"vcluster-{object_name}"


def kubeconfig_secret_name(object_name: str) -> str:
    """The chart names its kubeconfig secret `vc-<release>`, and the release is
    named after the claim (see `VClusterNames.vcluster` in the controller)."""

    return f"vc-{object_name}"


class VClusterClaimAlreadyExistsError(Exception):
    """Raised when a claim with the requested object name already exists."""


class VClusterClaimRepository:
    """CRUD against the Kubernetes API. No authorization of any kind lives here."""

    def __init__(
        self,
        api: client.CustomObjectsApi | None = None,
        core_api: client.CoreV1Api | None = None,
        namespace: str | None = None,
    ) -> None:
        self._api = api or custom_objects_api()
        self._core = core_api or core_v1_api()
        self._namespace = namespace or config.claims_namespace

    def list_all(self) -> list[VClusterClaim]:
        """Lists every VClusterClaim in the global namespace."""

        res = self._api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
        )
        return [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

    def list_by_owner_hash(self, owner_hash: str) -> list[VClusterClaim]:
        """VClusterClaims labeled with the given owner identifier."""

        res = self._api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            label_selector=f"{OWNER_LABEL}={owner_hash}",
        )
        return [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

    def get(self, object_name: str) -> VClusterClaim | None:
        """Gets a VClusterClaim by its resource name"""

        try:
            obj = self._api.get_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=object_name,
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise

        return VClusterClaim.from_obj(cast(dict[str, Any], obj))

    def create(self, object_name: str, owner_hash: str, spec: VClusterClaimSpec) -> VClusterClaim:
        """Creates a new VClusterClaim."""
        
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
                        "name": object_name,
                        "labels": {OWNER_LABEL: owner_hash},
                    },
                    "spec": spec.model_dump(by_alias=True),
                },
            )
        except ApiException as e:
            if e.status == 409:
                raise VClusterClaimAlreadyExistsError(object_name) from e
            raise

        return VClusterClaim.from_obj(cast(dict[str, Any], obj))

    def patch_state(self, object_name: str, state: State) -> None:
        """Updates the desired state."""

        try:
            self._api.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=object_name,
                body={"spec": {"state": state.value}},
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def patch_access_rules(self, object_name: str, rules: list[AccessRule]) -> VClusterClaim:
        """Upadates the access rules of a VClusterClaim (i.e emails invited to the cluster)."""

        obj = self._api.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            name=object_name,
            body={"spec": {"accessRules": [rule.model_dump(by_alias=True) for rule in rules]}},
        )
        return VClusterClaim.from_obj(cast(dict[str, Any], obj))

    def delete(self, object_name: str) -> None:
        """Deletes a VClusterClaim."""

        try:
            self._api.delete_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=object_name,
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def read_kubeconfig(self, object_name: str) -> str | None:
        """Returns the kubeconfig for a vCluster (or None if the kubeconfig secret doesn't exist)."""

        try:
            secret = cast(
                client.V1Secret,
                self._core.read_namespaced_secret(
                    name=kubeconfig_secret_name(object_name),
                    namespace=vcluster_namespace(object_name),
                ),
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise

        raw = (secret.data or {}).get("config")
        if not raw:
            return None

        return base64.b64decode(raw).decode("utf-8")

    def read_control_plane_logs(self, object_name: str, tail_lines: int = 200) -> str | None:
        """Logs of the vcluster control-plane pod, or None if it isn't up yet.

        The vClusters run a single container, so we just use that one. We still
        read the container name off the pod (rather than hardcoding "syncer") so a
        rename in a future chart version won't break this.
        """

        namespace = vcluster_namespace(object_name)

        # The control plane runs as a single-replica StatefulSet named after the
        # helm release, so its only pod is "<release>-0".
        pod_name = f"{object_name}-0"

        try:
            pod = cast(Any, self._core.read_namespaced_pod(name=pod_name, namespace=namespace))
        except ApiException as e:
            if e.status == 404:
                return None
            raise

        containers = [c.name for c in (pod.spec.containers or [])]
        if not containers:
            return None

        try:
            resp = cast(
                Any,
                self._core.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    container=containers[0],
                    tail_lines=tail_lines,
                    _preload_content=False,  # returns the raw HTTP response
                ),
            )
        except ApiException as e:
            if e.status in (400, 404):  # 400 = container hasn't started yet; 404 = gone.
                return None
            raise

        ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

        raw = resp.data
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)

        return ANSI_ESCAPE_RE.sub("", text)