# SPDX-License-Identifier: Apache-2.0
"""Publish throttle: at most one update per track per interval."""

from collections.abc import Hashable


def should_publish(
    last_time: float | None,
    last_fingerprint: Hashable,
    now: float,
    fingerprint: Hashable,
    min_interval_seconds: float,
) -> bool:
    """Return whether an update may go out now.

    Args:
        last_time: When the last update for this track went out, or ``None``.
        last_fingerprint: The fingerprint sent with that update.
        now: Current time in seconds, on the same clock as ``last_time``.
        fingerprint: Identity data of the new update (such as name and static
            data). A change lets the update through early.
        min_interval_seconds: Shortest time between two unchanged updates.
    """
    if last_time is None:
        return True
    if fingerprint != last_fingerprint:
        return True
    return now - last_time >= min_interval_seconds


class Throttle:
    """Remembers when each track was last published."""

    def __init__(self, min_interval_seconds: float) -> None:
        """Create a throttle with the given minimum interval."""
        self.min_interval_seconds = min_interval_seconds
        self._last: dict[str, tuple[float, Hashable]] = {}

    def allow(self, key: str, now: float, fingerprint: Hashable = None) -> bool:
        """Return whether ``key`` may publish now, and record it if so."""
        last_time, last_fingerprint = self._last.get(key, (None, None))
        if not should_publish(
            last_time, last_fingerprint, now, fingerprint, self.min_interval_seconds
        ):
            return False
        self._last[key] = (now, fingerprint)
        return True

    def prune(self, now: float, older_than_seconds: float) -> list[str]:
        """Forget tracks not published for ``older_than_seconds``. Returns their keys."""
        stale = [key for key, (at, _) in self._last.items() if now - at > older_than_seconds]
        for key in stale:
            del self._last[key]
        return stale

    def __len__(self) -> int:
        """Return how many tracks are remembered."""
        return len(self._last)
