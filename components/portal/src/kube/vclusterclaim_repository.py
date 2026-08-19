import base64
import io
import os
import re
import shlex
import tarfile
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream

from config import config
from kube.client import core_v1_api, custom_objects_api
from kube.vclusterclaim_model import ExpiryAnnotation, VClusterClaim
from shared.vclusterclaim import (
    GROUP,
    KIND,
    PLURAL,
    VERSION,
    Member,
    State,
    VClusterClaimSpec,
)
from ttl_cache import TTLCache


_OWNER_LABEL = f"{GROUP}/owner-subject-hash"
_MEMBER_LABEL_PREFIX = f"{GROUP}/member-"

_vclusterclaim_cache: TTLCache[list[VClusterClaim]] = TTLCache(config.cache_ttl_seconds)


def get_owner_hash(sub: str) -> str:
    return sha256(sub.encode()).hexdigest()[:32]


def get_member_hash(email: str) -> str:
    return sha256(email.lower().encode()).hexdigest()[:32]


def vcluster_namespace(object_name: str) -> str:
    return f"vcluster-{object_name}"


class VClusterClaimAlreadyExistsError(Exception):
    """Raised when a VClusterClaim with the requested object name already exists."""


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

        def fetch() -> list[VClusterClaim]:
            res = self._api.list_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
            )
            return [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

        return _vclusterclaim_cache.get_or_set("all", fetch)

    def list_by_owner(self, sub: str) -> list[VClusterClaim]:
        """VClusterClaims labeled as owned by the given subject id."""

        owner_hash = get_owner_hash(sub)

        def fetch() -> list[VClusterClaim]:
            res = self._api.list_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                label_selector=f"{_OWNER_LABEL}={owner_hash}",
            )
            return [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

        return _vclusterclaim_cache.get_or_set(owner_hash, fetch)

    def list_by_shared_member(self, email: str) -> list[VClusterClaim]:
        """VClusterClaims labeled as shared with the given email."""

        member_hash = get_member_hash(email)

        def fetch() -> list[VClusterClaim]:
            res = self._api.list_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                label_selector=f"{_MEMBER_LABEL_PREFIX}{member_hash}=true",
            )
            return [VClusterClaim.from_obj(obj) for obj in cast(dict[str, Any], res).get("items", [])]

        return _vclusterclaim_cache.get_or_set(member_hash, fetch)

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

    def create(self, sub: str, given_name: str, spec: VClusterClaimSpec) -> VClusterClaim:
        """Creates a new VClusterClaim."""

        # Object name must start with a letter (RFC 1035) hence the "u" prefix.
        object_name = f"u{get_owner_hash(sub)}-{given_name}"

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
                        "labels": {_OWNER_LABEL: get_owner_hash(sub)},
                    },
                    "spec": spec.model_dump(by_alias=True),
                },
            )
        except ApiException as e:
            if e.status == 409:
                raise VClusterClaimAlreadyExistsError(object_name) from e
            raise

        _vclusterclaim_cache.invalidate("all")
        _vclusterclaim_cache.invalidate(get_owner_hash(sub))

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
            return

        _vclusterclaim_cache.invalidate_all()

    def patch_annotations(self, object_name: str, annotations: dict[str, str | None]) -> None:
        """Sets annotations on a claim, or clears via a `None`."""

        try:
            self._api.patch_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=self._namespace,
                plural=PLURAL,
                name=object_name,
                body={"metadata": {"annotations": annotations}},
            )
        except ApiException as e:
            if e.status != 404:
                raise
            return

        _vclusterclaim_cache.invalidate_all()

    def add_member(self, object_name: str, members: list[Member], email: str) -> VClusterClaim:
        """Sets `members` and labels the claim as shared with `email`, in a single patch."""

        member_label = f"{_MEMBER_LABEL_PREFIX}{get_member_hash(email)}"

        obj = self._api.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            name=object_name,
            body={
                "spec": {"members": [member.model_dump(by_alias=True) for member in members]},
                "metadata": {"labels": {member_label: "true"}},
            },
        )

        _vclusterclaim_cache.invalidate("all")
        _vclusterclaim_cache.invalidate(get_member_hash(email))

        return VClusterClaim.from_obj(cast(dict[str, Any], obj))

    def remove_member(self, object_name: str, members: list[Member], email: str) -> VClusterClaim:
        """Sets `members` and removes the shared-with-`email` label, in a single patch."""

        member_label = f"{_MEMBER_LABEL_PREFIX}{get_member_hash(email)}"

        obj = self._api.patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self._namespace,
            plural=PLURAL,
            name=object_name,
            body={
                "spec": {"members": [member.model_dump(by_alias=True) for member in members]},
                "metadata": {"labels": {member_label: None}},
            },
        )

        _vclusterclaim_cache.invalidate("all")
        _vclusterclaim_cache.invalidate(get_member_hash(email))

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
            return

        _vclusterclaim_cache.invalidate_all()

    def read_kubeconfig(self, object_name: str) -> str | None:
        """Returns the kubeconfig for a vCluster (or None if the kubeconfig secret doesn't exist)."""

        # The chart names its kubeconfig secret `vc-<release>`, and the release is
        # named after the claim (see `VClusterNames.vcluster` in the controller).
        kubeconfig_secret_name = f"vc-{object_name}"
        try:
            secret = cast(
                client.V1Secret,
                self._core.read_namespaced_secret(
                    name=kubeconfig_secret_name,
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
                    _preload_content=False,
                ),
            )
        except ApiException as e:
            if e.status in (400, 404):  # 400 = container hasn't started yet
                return None
            raise

        ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

        raw = resp.data
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)

        return ANSI_ESCAPE_RE.sub("", text)

    def read_mounted_volume_contents(self, object_name: str) -> bytes | None:
        """Tars up volumes mounted by the vCluster's workload pods if there are any."""

        namespace = vcluster_namespace(object_name)
        pods = cast(Any, self._core.list_namespaced_pod(namespace=namespace)).items

        workload_pods = [
            pod
            for pod in pods
            if not pod.metadata.owner_references
            or pod.metadata.owner_references[0].kind != "StatefulSet"
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            has_data = False
            for pod in workload_pods:

                pod_dir = os.path.join(tmp_dir, pod.metadata.name)
                if self._extract_pvc_mounts(pod, namespace, pod_dir):
                    has_data = True

            if not has_data:
                return None

            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w") as archive:
                archive.add(tmp_dir, arcname=object_name)

            return buffer.getvalue()

    def _extract_pvc_mounts(self, pod: Any, namespace: str, dest_dir: str) -> bool:
        """
        Execs into a pod, tars each of its volume mounts, extracts them 
        into `dest_dir` and returns whether any data was written.
        """

        pvc_volume_names = {volume.name for volume in (pod.spec.volumes or []) if volume.persistent_volume_claim}
        if not pvc_volume_names:
            return False

        wrote_data = False
        for container in pod.spec.containers:
            mounts = [mount for mount in (container.volume_mounts or []) if mount.name in pvc_volume_names]

            for mount in mounts:
                archive_bytes = self._tar_remote_path(pod.metadata.name, namespace, mount.mount_path)
                if not archive_bytes:
                    continue

                os.makedirs(dest_dir, exist_ok=True)
                with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tar:
                    tar.extractall(path=dest_dir, filter="data")
                wrote_data = True

        return wrote_data

    def _tar_remote_path(self, pod_name: str, namespace: str, mount_path: str) -> bytes:
        """Runs `tar cf -` for `mount_path` inside a pod and returns the resulting bytes."""

        dirname = shlex.quote(os.path.dirname(mount_path))
        basename = shlex.quote(os.path.basename(mount_path))

        res = stream(
            self._core.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=["/bin/sh", "-c", f"cd {dirname} && tar cf - {basename}"],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            binary=True,
            _preload_content=False,
        )

        data = io.BytesIO()
        try:
            while res.is_open():
                res.update(timeout=1)
                if res.peek_stdout():
                    data.write(res.read_stdout())
        finally:
            res.close()

        return data.getvalue()

    def mark_renewed(self, object_name: str) -> None:
        """Renews a VClusterClaim after the owner was notified about expiration, clearing any pending warnings."""

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.patch_annotations(
            object_name,
            {
                ExpiryAnnotation.RENEWED_AT: now,
                ExpiryAnnotation.SLEEP_WARNING: None,
                ExpiryAnnotation.EXPIRED: None,
                ExpiryAnnotation.DELETION_WARNING: None,
            },
        )