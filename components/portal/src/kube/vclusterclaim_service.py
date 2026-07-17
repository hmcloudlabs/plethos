import base64
import re
from hashlib import sha256
from typing import Any, cast

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from config import config
from kube.client import core_v1_api, custom_objects_api
from kube.vclusterclaim_model import AccessType, VClusterClaim
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
    """The VClusterClaim object name: owner-hash prefix + the user-chosen name."""
    return f"{owner_subject_hash(sub)}-{name}"


def vcluster_namespace(object_name: str) -> str:
    return f"vcluster-{object_name}"


def kubeconfig_secret_name(object_name: str) -> str:
    return f"vc-vcluster-{object_name}"


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

    @staticmethod
    def access_type(vc_claim: VClusterClaim, sub: str, email: str = "") -> AccessType | None:
        """The caller's access to a VClusterClaim: OWNER, MEMBER, or None (no access).

        The `email` is only needed to detect MEMBER access, OWNER-only checks don't need it.
        """
        if vc_claim.spec.owner_subject == sub:
            return AccessType.OWNER

        email = email.lower()
        if any(rule.email.lower() == email for rule in vc_claim.spec.access_rules):
            return AccessType.MEMBER

        return None

    def list_for_owner(self, sub: str) -> list[VClusterClaim]:
        """List all VClusterClaims owned a user given their subject id."""

        res = self._api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            label_selector=f"{OWNER_LABEL}={owner_subject_hash(sub)}",
        )

        vc_claims = [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

        # The label-selector only embeds the sub's hash so re-check raw sub to avoid hash collisions
        return [vc_claim for vc_claim in vc_claims if vc_claim.spec.owner_subject == sub]

    def get_by_object_name(self, object_name: str) -> VClusterClaim | None:
        """Fetch a VClusterClaim by its full object name."""

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

    def _patch_state(self, object_name: str, state: State) -> None:
        """Patch spec.state. No authorization; tolerates a claim deleted mid-flight."""
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

    def _delete(self, object_name: str) -> None:
        """Delete a claim. No authorization; tolerates a claim already gone."""
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

    def set_state(self, object_name: str, sub: str, email: str, state: State) -> None:
        """Sleep/wake. Allowed for the owner or any shared member; a no-op otherwise."""

        vc_claim = self.get_by_object_name(object_name)
        if vc_claim is None or self.access_type(vc_claim, sub, email) is None:
            return

        self._patch_state(object_name, state)

    def delete(self, object_name: str, sub: str) -> None:
        """Delete a cluster (owner only)."""

        vc_claim = self.get_by_object_name(object_name)
        if vc_claim is None or self.access_type(vc_claim, sub) is not AccessType.OWNER:
            return

        self._delete(object_name)

    def list_shared_with(self, email: str) -> list[VClusterClaim]:
        """Lists all clusters that a user's email was invited to (ie. written into the `accessRules`).

        Access is keyed by email, which no label indexes, so we list every VClusterClaim in the (single) 
        namespace and filter in memory. This is fine for now (as long as the amount of clusters 
        stay in small scale).
        """

        # Fetches *all* VClusterClaims
        res = self._api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
        )
        vc_claims = [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

        email = email.lower()
        return [
            vc_claim for vc_claim in vc_claims
            if vc_claim.spec.owner_email.lower() != email
            and any(rule.email.lower() == email for rule in vc_claim.spec.access_rules)
        ]

    def add_access(self, object_name: str, owner_sub: str, email: str) -> VClusterClaim | None:
        """Grants a member access (owner only), returns None if not found/owned."""

        vc_claim = self.get_by_object_name(object_name)
        if vc_claim is None or self.access_type(vc_claim, owner_sub) is not AccessType.OWNER:
            return None

        # Drop any existing rule for this email in the current VClusterClaim before re-adding.
        rules = [rule for rule in vc_claim.spec.access_rules if rule.email != email]
        rules.append(AccessRule(email=email))

        return self._patch_access_rules(object_name, rules)

    def remove_access(self, object_name: str, owner_sub: str, email: str) -> VClusterClaim | None:
        """Revoke a member's access. Owner only; returns None if not found/not owned."""

        vc_claim = self.get_by_object_name(object_name)
        if vc_claim is None or self.access_type(vc_claim, owner_sub) is not AccessType.OWNER:
            return None

        rules = [rule for rule in vc_claim.spec.access_rules if rule.email != email]

        return self._patch_access_rules(object_name, rules)

    def _patch_access_rules(self, object_name: str, rules: list[AccessRule]) -> VClusterClaim:
        obj = self._api.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            name=object_name,
            body={"spec": {"accessRules": [rule.model_dump(by_alias=True) for rule in rules]}},
        )
        return VClusterClaim.from_obj(cast(dict[str, Any], obj))

    def get_kubeconfig(self, object_name: str, sub: str, email: str) -> tuple[str, str] | None:
        """Returns (display_name, kubeconfig_yaml) for the owner or a shared member.

        None if the caller has no access, or the vcluster isn't provisioned yet.
        """

        vc_claim = self.get_by_object_name(object_name)
        if vc_claim is None or self.access_type(vc_claim, sub, email) is None:
            return None

        try:
            secret = self._core.read_namespaced_secret(
                name=kubeconfig_secret_name(object_name),
                namespace=vcluster_namespace(object_name),
            )
        except ApiException as e:
            if e.status == 404:
                return None  # provisioning not finished yet
            raise

        raw = (secret.data or {}).get("config")
        if not raw:
            return None

        return vc_claim.spec.name, base64.b64decode(raw).decode("utf-8")

    def list_all_as_admin(self) -> list[VClusterClaim]:
        """Every VClusterClaim across all users (admin view)."""

        res = self._api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
        )
        return [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

    def get_logs_as_admin(self, object_name: str, tail_lines: int = 200) -> str | None:
        """Logs of the vcluster control-plane pod, or None if it isn't up yet.

        Our vclusters run a single container, so we just tail that one. We still
        read the container name off the pod (rather than hardcoding "syncer") so a
        rename in a future chart version won't break this.
        """

        namespace = vcluster_namespace(object_name)

        # The vcluster helm release is named after the namespace, so its
        # StatefulSet's first pod is "<namespace>-0".
        pod_name = f"{namespace}-0"

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
                    _preload_content=False, # returns the raw HTTP response
                ),
            )
        except ApiException as e:
            # 400 = container hasn't started yet (still ContainerCreating); 404 = gone.
            if e.status in (400, 404):
                return None
            raise

        ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

        raw = resp.data
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        
        return ANSI_ESCAPE_RE.sub("", text)

    def set_state_as_admin(self, object_name: str, state: State) -> None:
        """Sleep/wake any cluster, regardless of ownership."""

        self._patch_state(object_name, state)

    def delete_as_admin(self, object_name: str) -> None:
        """Delete any cluster, regardless of ownership."""

        self._delete(object_name)

    def delete_all_user_clusters_as_admin(self, owner_email: str) -> int:
        """Delete every cluster owned by the given email. Returns the count deleted."""

        owner_email = owner_email.lower()
        owned = [
            claim
            for claim in self.list_all_as_admin()
            if claim.spec.owner_email.lower() == owner_email
        ]
        for claim in owned:
            self._delete(claim.object_name)

        return len(owned)
