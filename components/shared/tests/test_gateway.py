from shared.gateway import make_gateway_host


def test_make_gateway_host():
    assert make_gateway_host("abc", "plethos-apps", "example.com") == "abc.plethos-apps.example.com"
