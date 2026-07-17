from dataclasses import dataclass
from enum import StrEnum

from shared.vclusterclaim import VClusterClaimSpec, VClusterClaimStatus


@dataclass(frozen=True)
class VClusterClaim:

    object_name: str
    spec: VClusterClaimSpec
    status: VClusterClaimStatus
    creation_timestamp: str | None

    @classmethod
    def from_obj(cls, obj: dict) -> "VClusterClaim":
        meta = obj.get("metadata", {})
        return cls(
            object_name=meta.get("name", ""),
            spec=VClusterClaimSpec.model_validate(obj.get("spec", {})),
            status=VClusterClaimStatus.model_validate(obj.get("status") or {}),
            creation_timestamp=meta.get("creationTimestamp"),
        )


class AccessType(StrEnum):
    """A caller's level of access to a cluster."""

    OWNER = "owner"
    MEMBER = "member"