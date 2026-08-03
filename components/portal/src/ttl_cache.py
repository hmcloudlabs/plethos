import threading
import time
from typing import Callable, Generic, TypeVar


V = TypeVar("V")


class TTLCache(Generic[V]):
    """A thread-safe, keyed cache where each entry expires `ttl` seconds after it was set."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._entries: dict[str, tuple[float, V]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get_or_set(self, key: str, loader: Callable[[], V]) -> V:
        """Returns the cached value for `key`, or calls `loader` and caches its result.

        Locks per key, so a miss for one key never blocks lookups of other keys.
        """

        with self._lock_for(key):
            entry = self._entries.get(key)
            if entry is not None and time.monotonic() - entry[0] < self._ttl:
                return entry[1]

            value = loader()
            self._entries[key] = (time.monotonic(), value)
            return value

    def invalidate(self, key: str) -> None:
        """Clears one entry."""

        with self._lock_for(key):
            self._entries.pop(key, None)

    def invalidate_all(self) -> None:
        """Clears every entry."""

        self._entries.clear()
        self._locks.clear()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())
