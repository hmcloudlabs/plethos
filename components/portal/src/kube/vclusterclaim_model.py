from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from config import config
from shared.vclusterclaim import GROUP, VClusterClaimSpec, VClusterClaimStatus


class ExpiryAnnotation(StrEnum):
    """Annotation keys the expiry job/portal read and write to a VClusterClaim."""

    RENEWED_AT = f"{GROUP}/renewed-at"
    SLEEP_WARNING = f"{GROUP}/sleep-warning-sent"
    EXPIRED = f"{GROUP}/expired"
    DELETION_WARNING = f"{GROUP}/deletion-warning-sent"


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

    @property
    def expires_at(self) -> datetime:
        """When this VClusterClaim expires (EXPIRY_PERIOD_DAYS after its last renewal, or after creation if never renewed before)."""

        renewed_at = self.renewed_at or datetime.strptime(cast(str, self.creation_timestamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        return renewed_at + timedelta(days=config.expiry_period_days)

    @property
    def renewed_at(self) -> datetime | None:
        """When this VClusterClaim was last renewed after an upcoming expiration."""
        
        renewed_at_annotation = self.annotations.get(ExpiryAnnotation.RENEWED_AT)
        if not renewed_at_annotation:
            return None
        return datetime.strptime(renewed_at_annotation, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)