"""How fast the app may ask c411: two queues, one per limit c411 applies.

Measured on 2026-10-22 (docs/research/rate-limits.md):

- Searches, Catalogue pages and the profile share a budget of 1,200 requests per
  rolling hour, which c411's JSON API reports in `x-ratelimit-*` headers; its guide also
  documents 120 requests a minute. Every key of the account draws on that one budget.
- .torrent downloads do not count in it. Each key may download 30 in any 60 seconds,
  which c411 only reports when it refuses one; a longer limit refused a key after 292
  in 20 minutes.

So a Library search never waits behind a Plan's downloads, and goes as fast as c411
allows while the budget lasts.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager

DOWNLOAD_INTERVAL = 2.05  # seconds between a key's .torrent downloads: 29 a minute
# Rolling limits on a key's downloads: (downloads, seconds). 30 a minute is c411's; 280 in
# 20 minutes stays under the refusal seen after 292.
DOWNLOAD_LIMITS = ((30, 60.0), (280, 1200.0))
API_INTERVAL = 0.5  # 120 requests a minute, as c411's guide documents
API_BUDGET = 1200  # requests per rolling hour on searches, listings and the profile
API_WINDOW = 3600.0
LOW_BUDGET = 100  # below this, slow down to what the hour can sustain (3 s a request)
SHORT_WINDOW = 600.0  # a refusal's window up to this is a pace to adopt, not the hourly budget
REFUSAL_MARGIN = 1.05  # adopted paces stay a little under the reported limit


def cancellable_sleep(seconds: float, stop: threading.Event | None, sleep=time.sleep) -> None:
    """Honor the configured clock's sleeper while checking cancellation during long waits."""
    if stop is None:
        sleep(seconds)
        return
    while seconds > 0:
        if stop.is_set():
            raise InterruptedError("Request cancelled while waiting for quota.")
        interval = min(seconds, 0.1)
        sleep(interval)
        seconds -= interval
    if stop.is_set():
        raise InterruptedError("Request cancelled while waiting for quota.")


class Queue:
    """One request at a time, at least `interval` seconds apart.

    A request the user is waiting for passes before background ones (a Plan being sent,
    Catalogue updates): a background request lets every waiting foreground one go
    first. Pacing waits happen outside the queue, so a foreground request arriving
    during a background one's wait still goes first.
    """

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._state = threading.Condition()
        self._busy = False  # a request is in flight
        self._foreground = 0  # foreground requests waiting for their turn

    def next_in(self) -> float:
        """Seconds before the next request may go."""
        if self._last is None:
            return 0.0
        return max(0.0, self._last + self._interval() - self._clock())

    @contextmanager
    def turn(self, background: bool = False, stop: threading.Event | None = None) -> Iterator[None]:
        """Wait for this request's turn, then hold the queue while it is sent."""
        self._claim(background, stop)
        try:
            yield
        finally:
            with self._state:
                self._busy = False
                self._state.notify_all()

    def wait_turn(self, background: bool = False) -> None:
        """Wait for a turn and count it as sent, for callers sending on their own."""
        with self.turn(background):
            pass

    def _claim(self, background: bool, stop: threading.Event | None = None) -> None:
        with self._state:
            if not background:
                self._foreground += 1
        try:
            while True:
                with self._state:
                    while self._busy or (background and self._foreground > 0):
                        if stop is not None and stop.is_set():
                            raise InterruptedError("Request stopped before sending.")
                        self._state.wait(0.1 if stop is not None else None)
                    if stop is not None and stop.is_set():
                        raise InterruptedError("Request stopped before sending.")
                    wait = self.next_in()
                    if wait <= 0:
                        self._busy = True
                        self._last = self._clock()
                        self._sent()
                        return
                cancellable_sleep(wait, stop, self._sleep)  # outside the queue lock
        finally:
            if not background:
                with self._state:
                    self._foreground -= 1
                    self._state.notify_all()

    def _interval(self) -> float:
        return self.interval

    def _sent(self) -> None:
        pass

    def observe(self, headers: Mapping[str, str]) -> None:
        """What c411 said about the budget in a response; plain queues ignore it."""

    def adopt_refusal(self, headers: Mapping[str, str]) -> float | None:
        """After a 429: keep to the short-window limit c411 reports from now on
        (`x-ratelimit-limit` requests per `x-ratelimit-window` seconds), so the queue
        is paced at the real rate instead of meeting the refusal again. Returns the new
        interval, or None when the refusal reports no such limit."""
        try:
            limit = int(headers["x-ratelimit-limit"])
            window = float(headers["x-ratelimit-window"])
        except (KeyError, ValueError):
            return None
        if limit <= 0 or not 0 < window <= SHORT_WINDOW:
            return None
        self.interval = max(self.interval, window / limit * REFUSAL_MARGIN)
        return self.interval


class WindowQueue(Queue):
    """A queue that also keeps to rolling limits: at most n requests in any w seconds."""

    def __init__(
        self,
        interval: float = DOWNLOAD_INTERVAL,
        limits: tuple[tuple[int, float], ...] = DOWNLOAD_LIMITS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(interval, clock, sleep)
        self.limits = limits
        self._sent_at: deque[float] = deque()

    def next_in(self) -> float:
        now = self._clock()
        longest = max((w for _, w in self.limits), default=0.0)
        while self._sent_at and self._sent_at[0] <= now - longest:
            self._sent_at.popleft()
        wait = super().next_in()
        for count, window in self.limits:
            recent = [t for t in self._sent_at if t > now - window]
            if len(recent) >= count:
                # The oldest request that keeps the window full must leave it first.
                wait = max(wait, recent[len(recent) - count] + window - now)
        return wait

    def _sent(self) -> None:
        self._sent_at.append(self._clock())


def sending_seconds(downloads: int, keys: int) -> float:
    """About how long `downloads` .torrent files take, spread over `keys` keys."""
    per_key = -(-downloads // max(keys, 1))
    clock = [0.0]
    queue = WindowQueue(clock=lambda: clock[0], sleep=lambda _s: None)
    for _ in range(per_key):
        clock[0] += queue.next_in()
        queue._sent()
        queue._last = clock[0]
    return clock[0]


class BudgetQueue(Queue):
    """A queue drawing on a budget of requests per rolling window.

    It counts its own requests over the window, and trusts `x-ratelimit-remaining` and
    `x-ratelimit-reset` whenever c411 sends them (other apps may use the same key).
    """

    def __init__(
        self,
        interval: float = API_INTERVAL,
        budget: int = API_BUDGET,
        window: float = API_WINDOW,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(interval, clock, sleep)
        self.budget = budget
        self.window = window
        self._wall = wall
        self._sent_at: deque[float] = deque()
        self._reported: int | None = None  # remaining, as c411 last said
        self._since_report = 0
        self._reset: float | None = None  # on this queue's clock

    def left(self) -> int:
        """Requests left in the budget, by our count or c411's, whichever is lower."""
        now = self._clock()
        while self._sent_at and self._sent_at[0] <= now - self.window:
            self._sent_at.popleft()
        left = self.budget - len(self._sent_at)
        if self._reported is not None and self._reset is not None and now < self._reset:
            left = min(left, self._reported - self._since_report)
        return left

    def _interval(self) -> float:
        left = self.left()
        if left > LOW_BUDGET:
            return self.interval
        if left > 0:
            return max(self.interval, self.window / self.budget)
        return self._until_refill()

    def _until_refill(self) -> float:
        """Seconds from the last request until the budget gives one back."""
        assert self._last is not None
        ends = [t + self.window for t in list(self._sent_at)[:1]]
        if self._reset is not None:
            ends.append(self._reset)
        refill = min(ends) if ends else self._clock() + self.interval
        return max(self.interval, refill - self._last)

    def _sent(self) -> None:
        self._sent_at.append(self._clock())
        self._since_report += 1

    def observe(self, headers: Mapping[str, str]) -> None:
        try:
            remaining = int(headers["x-ratelimit-remaining"])
            reset = float(headers["x-ratelimit-reset"])
        except (KeyError, ValueError):
            return
        if limit := headers.get("x-ratelimit-limit"):
            try:
                self.budget = int(limit)
            except ValueError:
                pass
        self._reported, self._since_report = remaining, 0
        self._reset = self._clock() + max(0.0, reset - self._wall())


class Pacer(Queue):
    """An Indexer's pace: no limit of ours, only what that Indexer asks for.

    Requests go one at a time with no pause until the Indexer refuses one with 429; then
    the pacer rests as long as `Retry-After` says and keeps to any limit the refusal
    reports (`x-ratelimit-limit` per `x-ratelimit-window`). A response that reports no
    request left (`x-ratelimit-remaining: 0`) rests until `x-ratelimit-reset`.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(0.0, clock, sleep)
        self._until = 0.0

    def rest(self, seconds: float) -> None:
        self._until = max(self._until, self._clock() + max(seconds, 0.0))

    def next_in(self) -> float:
        return max(super().next_in(), self._until - self._clock(), 0.0)

    def observe(self, headers: Mapping[str, str]) -> None:
        try:
            if int(headers["x-ratelimit-remaining"]) <= 0:
                self.rest(float(headers["x-ratelimit-reset"]))
        except (KeyError, ValueError):
            pass
