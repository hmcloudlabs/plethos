from dataclasses import dataclass
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

    @classmethod
    def from_obj(cls, obj: dict) -> "VClusterClaim":
        meta = obj.get("metadata", {})
        return cls(
            object_name=meta.get("name", ""),
            spec=VClusterClaimSpec.model_validate(obj.get("spec", {})),
            status=VClusterClaimStatus.model_validate(obj.get("status") or {}),
            creation_timestamp=meta.get("creationTimestamp"),
        )

    def access_for(self, sub: str, email: str = "") -> AccessType | None:
        """The caller's access to this claim: OWNER, MEMBER, or None (no access).

        The email is only needed to detect MEMBER access; OWNER-only checks can omit it.
        """
        
        if self.spec.owner_subject == sub:
            return AccessType.OWNER

        email = email.lower()
        if any(rule.email.lower() == email for rule in self.spec.access_rules):
            return AccessType.MEMBER

        return None