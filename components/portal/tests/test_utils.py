from utils import is_valid_email


class TestIsValidEmail:
    def test_accepts_a_valid_email(self):
        assert is_valid_email("bob@example.com") is True

    def test_rejects_a_missing_at_symbol(self):
        assert is_valid_email("bob.example.com") is False

    def test_rejects_a_missing_domain_dot(self):
        assert is_valid_email("bob@example") is False

    def test_rejects_whitespace(self):
        assert is_valid_email("bob @example.com") is False

    def test_rejects_an_empty_string(self):
        assert is_valid_email("") is False
