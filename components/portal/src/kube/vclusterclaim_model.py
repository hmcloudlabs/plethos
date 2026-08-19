from dataclasses import dataclass, field
from enum import StrEnum

from shared.vclusterclaim import VClusterClaimSpec, VClusterClaimStatus


class AccessType(StrEnum):
    """A caller's level of access to a cluster."""

    OWNER = "owner"
    MEMBER = "member"


@dataclass(frozen=True)
class VClusterClaim:
    object_name: str
    spec: VClusterClaimSpec
    status: VClusterClaimStatus
    creation_timestamp: str | None
    annotations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_obj(cls, obj: dict) -> "VClusterClaim":
        meta = obj.get("metadata", {})
        return cls(
            object_name=meta.get("name", ""),
            spec=VClusterClaimSpec.model_validate(obj.get("spec", {})),
            status=VClusterClaimStatus.model_validate(obj.get("status") or {}),
            creation_timestamp=meta.get("creationTimestamp"),
            annotations=meta.get("annotations") or {},
        )

    def access_for(self, sub: str, email: str = "") -> AccessType | None:
        """
        The caller's access to this claim: OWNER, MEMBER, or None (no access).
        The email is only needed to detect MEMBER access; OWNER-only checks can omit it.
        """

        if self.spec.owner_subject == sub:
            return AccessType.OWNER

        email = email.lower()
        if any(member.email.lower() == email for member in self.spec.members):
            return AccessType.MEMBER

        return None