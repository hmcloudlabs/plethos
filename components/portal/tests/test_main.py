import json
from base64 import b64encode
from unittest.mock import create_autospec
import itsdangerous
import pytest
from fastapi.testclient import TestClient

import auth
from auth import User
from config import config
from kube.settings_service import SettingsService
from main import app


def _session_cookie(user: User) -> str:
    signer = itsdangerous.TimestampSigner(config.session_secret)
    payload = b64encode(json.dumps({"user": user.to_session()}).encode("utf-8"))
    return signer.sign(payload).decode("utf-8")


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestAuthExceptionHandlers:
    def test_redirects_to_login_when_not_authenticated(self, client):
        res = client.get("/clusters", follow_redirects=False)

        assert res.status_code == 303
        assert res.headers["location"] == "/login"

    def test_prevents_non_admins_to_access_admin_area(self, client):
        user = User(sub="user-1-sub", email="bob@example.com", name="bob")
        client.cookies.set("session", _session_cookie(user))

        settings_service = create_autospec(SettingsService, instance=True)
        settings_service.is_admin.return_value = False
        app.dependency_overrides[auth.get_settings_service] = lambda: settings_service

        res = client.get("/admin")

        assert res.status_code == 403
        assert "Forbidden" in res.text

class TestLogout:
    def test_clears_session_and_redirects_home(self, client):
        user = User(sub="user-1-sub", email="bob@example.com", name="bob")
        client.cookies.set("session", _session_cookie(user))

        res = client.get("/logout", follow_redirects=False)

        assert res.status_code == 303
        assert res.headers["location"] == "/"
        assert "session=null" in res.headers["set-cookie"]
