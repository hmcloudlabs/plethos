from datetime import UTC, datetime, timedelta

from config import config
from kube.vclusterclaim_model import AccessType, ExpiryAnnotation
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


class TestRenewedAt:
    def test_returns_none_when_never_renewed(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(annotations={})

        assert vcluster_claim.renewed_at is None

    def test_parses_the_renewed_at_annotation(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(
            annotations={ExpiryAnnotation.RENEWED_AT: "2024-06-01T12:00:00Z"}
        )

        assert vcluster_claim.renewed_at == datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


class TestExpiresAt:
    def test_falls_back_to_use_creation_timestamp_when_never_renewed(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(
            creation_timestamp="2024-01-01T00:00:00Z", annotations={}
        )

        expected = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=config.expiry_period_days)
        assert vcluster_claim.expires_at == expected

    def test_uses_renewed_at_when_renewed(self, make_vcluster_claim):
        vcluster_claim = make_vcluster_claim(
            creation_timestamp="2020-01-01T00:00:00Z",
            annotations={ExpiryAnnotation.RENEWED_AT: "2024-06-01T00:00:00Z"},
        )

        expected = datetime(2024, 6, 1, tzinfo=UTC) + timedelta(days=config.expiry_period_days)
        assert vcluster_claim.expires_at == expected
