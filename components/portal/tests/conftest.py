import pytest

from kube.vclusterclaim_model import VClusterClaim
from shared.vclusterclaim import Member, VClusterClaimSpec, VClusterClaimStatus


@pytest.fixture
def make_vcluster_claim():
    def _make(
        object_name: str = "u123-test-cluster",
        owner_subject: str = "owner-sub",
        owner_email: str = "owner@example.com",
        members: list[Member] | None = None,
    ) -> VClusterClaim:
        return VClusterClaim(
            object_name=object_name,
            spec=VClusterClaimSpec(
                name="test-cluster",
                owner_subject=owner_subject,
                owner_email=owner_email,
                members=members or [],
            ),
            status=VClusterClaimStatus(),
            creation_timestamp=None,
        )

    return _make
