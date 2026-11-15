# SPDX-License-Identifier: Apache-2.0
"""Publish tracks to Lattice: throttle, newest-wins queue, retries.

One publisher per service. A track waits in a queue keyed by entity, so if a
newer report for the same vessel or aircraft arrives first, only the newer one
is sent. HTTP 408, 429 and 5xx answers and network failures are retried with
backoff. Any other 4xx is a validation error: it is logged with the entity ID
and never retried. On shutdown nothing is deleted; tracks simply expire.
"""

import asyncio
import logging
import random
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Hashable
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import httpx
from anduril.core.api_error import ApiError

from lattice_cop.clean.throttle import Throttle
from lattice_cop.lattice.entity import entity_id, track_to_entity
from lattice_cop.models import Track

DEFAULT_CONCURRENCY: Final = 8
DEFAULT_MAX_ATTEMPTS: Final = 4
RETRY_BASE_SECONDS: Final = 0.5
RETRY_MAX_SECONDS: Final = 8.0
ERROR_LOG_INTERVAL_SECONDS: Final = 30.0
FORGET_AFTER_SECONDS: Final = 3600.0
"""A track not published for this long is forgotten (first-seen time and throttle)."""

_REQUEST_TIMEOUT: Final = 408
_TOO_MANY_REQUESTS: Final = 429
_SERVER_ERROR: Final = 500
_MAX_BODY_TEXT: Final = 300

# Counter names.
SUBMITTED: Final = "submitted"
THROTTLED: Final = "throttled"
PUBLISHED: Final = "published"
RETRIED: Final = "retried"
REJECTED: Final = "rejected"
FAILED: Final = "failed"
SUPERSEDED: Final = "superseded"

log = logging.getLogger("lattice_cop.lattice.publisher")


class EntitiesClient(Protocol):
    """The part of the SDK's async entities client the publisher uses."""

    async def publish_entity(self, **kwargs: Any) -> Any:
        """Create or update one entity."""
        ...  # pragma: no cover - protocol stub


def is_retryable(status_code: int | None) -> bool:
    """Return whether an HTTP status is worth retrying: 408, 429 or any 5xx."""
    if status_code is None:
        return False
    return status_code in {_REQUEST_TIMEOUT, _TOO_MANY_REQUESTS} or status_code >= _SERVER_ERROR


def retry_delay(attempt: int, rng: Callable[[], float] = random.random) -> float:
    """Return the wait before retry number ``attempt`` (1 is the first retry).

    The ceiling doubles from 0.5 s to 8 s; the delay is a random point in its top half.
    """
    ceiling = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2.0 ** max(attempt - 1, 0))
    return ceiling * (0.5 + 0.5 * rng())


class Publisher:
    """Sends tracks to Lattice for one service."""

    def __init__(  # noqa: PLR0913 - the extra arguments are test seams
        self,
        entities: EntitiesClient,
        *,
        expiry_seconds: float,
        throttle: Throttle,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Create a publisher.

        Args:
            entities: The SDK's async entities client.
            expiry_seconds: How long a track stays live after each update.
            throttle: Limits how often one track is sent.
            concurrency: How many updates may be in flight at once.
            max_attempts: Tries per update, the first one included.
            sleep: Waits between retries. Tests pass a fake.
            rng: Source of jitter in ``[0, 1)``.
            monotonic: Clock for the throttle and for limiting error logs.
            wall_clock: Clock for created and expiry times.
        """
        self.counts: Counter[str] = Counter()
        self._entities = entities
        self._expiry_seconds = expiry_seconds
        self._throttle = throttle
        self._concurrency = concurrency
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._rng = rng
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._pending: dict[str, Track] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._first_seen: dict[str, datetime] = {}
        self._last_error_log: dict[str, float] = {}

    @property
    def backlog(self) -> int:
        """How many tracks are waiting to be sent."""
        return len(self._pending)

    def submit(self, track: Track, fingerprint: Hashable = None) -> bool:
        """Queue a track for publishing unless the throttle holds it back.

        Args:
            track: The cleaned report.
            fingerprint: Identity data (such as name and static details). A change
                lets the update through before the throttle interval is up.

        Returns:
            True if the track was queued.
        """
        self.counts[SUBMITTED] += 1
        key = entity_id(track)
        if not self._throttle.allow(key, self._monotonic(), fingerprint):
            self.counts[THROTTLED] += 1
            return False
        self._first_seen.setdefault(key, self._wall_clock())
        if key in self._pending:
            # An older report is still waiting: the newer one takes its place.
            self.counts[SUPERSEDED] += 1
        else:
            self._queue.put_nowait(key)
        self._pending[key] = track
        return True

    async def run(self) -> None:
        """Publish queued tracks until cancelled."""
        async with asyncio.TaskGroup() as group:
            for index in range(self._concurrency):
                group.create_task(self._worker(), name=f"publisher-{index}")

    async def drain(self) -> None:
        """Wait until everything queued so far has been handled. Used by tests."""
        await self._queue.join()

    async def _worker(self) -> None:
        """Take entity IDs off the queue and publish the newest track for each."""
        while True:
            key = await self._queue.get()
            try:
                # Every queued ID has exactly one pending track.
                await self._publish(key, self._pending.pop(key))
            finally:
                self._queue.task_done()

    async def _publish(self, key: str, track: Track) -> None:
        """Send one track, retrying transient failures."""
        attempt = 0
        while True:
            attempt += 1
            entity = track_to_entity(
                track,
                created_time=self._first_seen.get(key, track.observed_at),
                now=self._wall_clock(),
                expiry_seconds=self._expiry_seconds,
            )
            try:
                await self._entities.publish_entity(**entity)
            except ApiError as error:
                status, detail = error.status_code, str(error.body)[:_MAX_BODY_TEXT]
                if not is_retryable(status):
                    self.counts[REJECTED] += 1
                    # Status and body only: the error's headers can carry tokens.
                    self._log_error("Lattice rejected an entity", key, status, detail)
                    return
            except httpx.TransportError as error:
                status, detail = None, type(error).__name__
            else:
                self.counts[PUBLISHED] += 1
                return

            if attempt >= self._max_attempts:
                self.counts[FAILED] += 1
                self._log_error("gave up publishing an entity after retries", key, status, detail)
                return
            if key in self._pending:
                # A newer report is already queued; send that instead of retrying this one.
                self.counts[SUPERSEDED] += 1
                return
            self.counts[RETRIED] += 1
            await self._sleep(retry_delay(attempt, self._rng))

    def _log_error(self, message: str, key: str, status: int | None, detail: str) -> None:
        """Log a publish error, at most once per interval for each kind of failure."""
        kind = f"{message}:{status}"
        now = self._monotonic()
        last = self._last_error_log.get(kind)
        if last is not None and now - last < ERROR_LOG_INTERVAL_SECONDS:
            return
        self._last_error_log[kind] = now
        log.error(message, extra={"entity_id": key, "status_code": status, "detail": detail})

    def prune(self) -> int:
        """Forget tracks that have not been published for a long time. Returns how many."""
        forgotten = self._throttle.prune(self._monotonic(), FORGET_AFTER_SECONDS)
        for key in forgotten:
            self._first_seen.pop(key, None)
        return len(forgotten)
