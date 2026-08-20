import pytest

from kube.vclusterclaim_model import VClusterClaim
from shared.vclusterclaim import Member, State, VClusterClaimSpec, VClusterClaimStatus


@pytest.fixture
def make_vcluster_claim():
    def _make(
        name: str = "test-cluster",
        object_name: str | None = None,
        owner_subject: str = "owner-sub",
        owner_email: str = "owner@example.com",
        members: list[Member] | None = None,
        state: State = State.RUNNING,
        status: VClusterClaimStatus | None = None,
        annotations: dict[str, str] | None = None,
        creation_timestamp: str | None = "2024-01-01T00:00:00Z",
    ) -> VClusterClaim:
        return VClusterClaim(
            # In reality object_name is derived from the given name but still
            # allow passing fabricated object_name for tests that need one.
            object_name=object_name or f"u123-{name}",
            spec=VClusterClaimSpec(
                name=name,
                owner_subject=owner_subject,
                owner_email=owner_email,
                members=members or [],
                state=state,
            ),
            status=status or VClusterClaimStatus(),
            creation_timestamp=creation_timestamp,
            annotations=annotations or {},
        )

    return _make
