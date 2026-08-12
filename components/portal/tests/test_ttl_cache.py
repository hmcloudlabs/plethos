from unittest.mock import Mock

import pytest

import ttl_cache as ttl_cache_module
from ttl_cache import TTLCache


class FakeTime:
    """Mocks stdlib `time` module inside ttl_cache.py."""

    def __init__(self) -> None:
        self._cur_time = 0.0

    def monotonic(self) -> float:
        return self._cur_time

    def tick(self, seconds: float) -> None:
        self._cur_time += seconds


@pytest.fixture
def fake_time(monkeypatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(ttl_cache_module, "time", fake)
    return fake


class TestGetOrSet:
    def test_returns_the_loaded_value(self, fake_time):
        cache = TTLCache(ttl=10)

        assert cache.get_or_set("key", Mock(return_value="value")) == "value"

    def test_only_calls_the_loader_once_within_ttl(self, fake_time):
        cache = TTLCache(ttl=10)
        loader = Mock(return_value="value")

        cache.get_or_set("key", loader)
        cache.get_or_set("key", loader)

        assert loader.call_count == 1

    def test_calls_the_loader_again_after_ttl_expires(self, fake_time):
        cache = TTLCache(ttl=10)
        loader = Mock(return_value="value")

        cache.get_or_set("key", loader)
        fake_time.tick(11)
        cache.get_or_set("key", loader)

        assert loader.call_count == 2

    def test_calls_the_loader_again_after_exactly_ttl_seconds(self, fake_time):
        cache = TTLCache(ttl=10)
        loader = Mock(return_value="value")

        cache.get_or_set("key", loader)
        fake_time.tick(10)
        cache.get_or_set("key", loader)

        assert loader.call_count == 2

    def test_different_keys_are_cached_independently(self, fake_time):
        cache = TTLCache(ttl=10)

        assert cache.get_or_set("a", Mock(return_value="value-a")) == "value-a"
        assert cache.get_or_set("b", Mock(return_value="value-b")) == "value-b"


class TestInvalidate:
    def test_clears_the_given_key(self, fake_time):
        cache = TTLCache(ttl=10)
        loader = Mock(return_value="value")

        cache.get_or_set("key", loader)
        cache.invalidate("key")
        cache.get_or_set("key", loader)

        assert loader.call_count == 2

    def test_does_not_affect_other_keys(self, fake_time):
        cache = TTLCache(ttl=10)

        cache.get_or_set("a", Mock(return_value="value-a"))
        
        loader_b = Mock(return_value="value-b")
        cache.get_or_set("b", loader_b)

        cache.invalidate("a")
        cache.get_or_set("b", loader_b)

        assert loader_b.call_count == 1


class TestInvalidateAll:
    def test_clears_every_key(self, fake_time):
        cache = TTLCache(ttl=10)
        loader_a = Mock(return_value="value-a")
        loader_b = Mock(return_value="value-b")
        cache.get_or_set("a", loader_a)
        cache.get_or_set("b", loader_b)

        cache.invalidate_all()
        cache.get_or_set("a", loader_a)
        cache.get_or_set("b", loader_b)

        assert loader_a.call_count == 2
        assert loader_b.call_count == 2
