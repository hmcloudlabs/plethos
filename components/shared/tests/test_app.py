from shared.app import make_app_host


def test_make_app_host():
    assert make_app_host("abc", "plethos-apps", "example.com") == "abc.plethos-apps.example.com"
