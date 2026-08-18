from tokens import TokenSigner


class TestTokenSigner:
    def test_returns_the_original_payload_for_a_valid_token(self):
        signer = TokenSigner(purpose="test", max_age_seconds=60)
        token = signer.generate({"object_name": "u123-my-cluster", "email": "bob@example.com"})

        assert signer.verify(token) == {
            "object_name": "u123-my-cluster",
            "email": "bob@example.com",
        }

    def test_rejects_a_tampered_token(self):
        signer = TokenSigner(purpose="test", max_age_seconds=60)
        token = signer.generate({"object_name": "u123-my-cluster"})

        tampered = ("a" if token[0] != "a" else "b") + token[1:]  # structurally valid token
        assert signer.verify(tampered) is None

    def test_rejects_a_malformed_token(self):
        signer = TokenSigner(purpose="test", max_age_seconds=60)
        assert signer.verify("not-a-real-token") is None

    def test_rejects_an_expired_token(self):
        signer = TokenSigner(purpose="test", max_age_seconds=-1)
        token = signer.generate({"object_name": "u123-my-cluster"})

        assert signer.verify(token) is None

    def test_tokens_are_scoped_to_their_purpose(self):
        """A token signed for one purpose must not verify under a different one."""

        signer_a = TokenSigner(purpose="purpose-a", max_age_seconds=60)
        signer_b = TokenSigner(purpose="purpose-b", max_age_seconds=60)

        token = signer_a.generate({"object_name": "u123-my-cluster"})
        assert signer_b.verify(token) is None
