import pytest

from auth import (
    NotAuthenticatedError,
    NotAuthorizedError,
    User,
    clear_session_user,
    get_session_user,
    require_admin,
    require_user,
    set_session_user,
)
from conftest import make_request
from kube.settings_service import SettingsService


def make_user(sub: str = "user-1", email: str = "bob@example.com", name: str = "bob") -> User:
    return User(sub=sub, email=email, name=name)


class TestFromClaims:
    def test_uses_all_standard_fields(self):
        user = User.from_claims({"sub": "abc", "email": "bob@example.com", "name": "bob"})
        assert user == User(sub="abc", email="bob@example.com", name="bob")

    def test_falls_back_to_preferred_username_when_name_missing(self):
        user = User.from_claims(
            {"sub": "abc", "email": "bob@example.com", "preferred_username": "bob"}
        )
        assert user.name == "bob"

    def test_falls_back_to_email_when_name_and_preferred_username_missing(self):
        user = User.from_claims({"sub": "abc", "email": "bob@example.com"})
        assert user.name == "bob@example.com"


class TestSessionHelpers:
    def test_set_then_get_round_trip(self):
        request = make_request()
        user = make_user()

        set_session_user(request, user)

        assert get_session_user(request) == user

    def test_clear_removes_the_session_entry(self):
        request = make_request()
        set_session_user(request, make_user())

        clear_session_user(request)
        assert get_session_user(request) is None

        clear_session_user(request)  # calling again doesn't raise


class TestRequireUser:
    def test_returns_the_logged_in_user(self):
        request = make_request()
        user = make_user()
        set_session_user(request, user)

        assert require_user(request) == user

    def test_raises_when_not_logged_in(self):
        with pytest.raises(NotAuthenticatedError):
            require_user(make_request())


class TestRequireAdmin:
    def test_raises_when_logged_in_but_not_admin(self, monkeypatch):
        monkeypatch.setattr(SettingsService, "is_admin", lambda _self, _email: False)

        request = make_request()
        set_session_user(request, make_user())

        with pytest.raises(NotAuthorizedError):
            require_admin(request)

    def test_returns_the_user_when_admin(self, monkeypatch):
        monkeypatch.setattr(SettingsService, "is_admin", lambda _self, _email: True)

        request = make_request()
        user = make_user()
        set_session_user(request, user)

        assert require_admin(request) == user
