from kube.vclusterclaim_model import AccessType
from shared.vclusterclaim import Member


class TestAccessFor:
    def test_returns_owner_when_sub_matches_owner_subject(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(owner_subject="owner-sub")

        assert vcluster_claim.access_for("owner-sub") is AccessType.OWNER

    def test_returns_member_when_email_matches_a_member(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(members=[Member(email="bob@example.com")])

        assert vcluster_claim.access_for("bobs-sub", "bob@example.com") is AccessType.MEMBER

    def test_member_email_match_is_case_insensitive(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(members=[Member(email="Bob@Example.com")])

        assert vcluster_claim.access_for("bobs-sub", "bob@example.com") is AccessType.MEMBER

    def test_returns_none_when_neither_owner_nor_member(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(members=[Member(email="bob@example.com")])

        assert vcluster_claim.access_for("teds-sub", "ted@example.com") is None

    def test_owner_match_takes_priority_over_member_match(self, make_vcluster_claim):
        # This test is only relevant for the edge case that the
        # owner email ends up in the members list as well.

        vcluster_claim = make_vcluster_claim(
            owner_subject="owner-sub", members=[Member(email="owner@example.com")]
        )
        assert vcluster_claim.access_for("owner-sub", "owner@example.com") is AccessType.OWNER
