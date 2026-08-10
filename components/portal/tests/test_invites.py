import invites
from invites import generate_invite_token, verify_invite_token


class TestVerifyInviteToken:
    def test_returns_the_original_payload_for_a_valid_token(self):
        token = generate_invite_token("u123-my-cluster", "bob@example.com")
        assert verify_invite_token(token) == {
            "object_name": "u123-my-cluster",
            "email": "bob@example.com",
        }

    def test_rejects_a_tampered_token(self):
        token = generate_invite_token("u123-my-cluster", "bob@example.com")

        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")  # structurally valid token
        assert verify_invite_token(tampered) is None

    def test_rejects_a_malformed_token(self):
        assert verify_invite_token("not-a-real-token") is None

    def test_rejects_an_expired_token(self, monkeypatch):
        monkeypatch.setattr(invites, "_MAX_AGE_SECONDS", -1)

        token = generate_invite_token("u123-my-cluster", "bob@example.com")
        assert verify_invite_token(token) is None
