"""The clock ``vidhi serve`` keeps: start what is queued, wake what waited.

Every ``TICK`` seconds it:

* puts back in the queue each waiting run whose time has come (a ``wait``
  step's, or a question's deadline);
* starts every queued run, each on a thread of its own, at most
  ``RUNNING`` at once -- a run started from Samay, a watch, a chat or the
  page is only a row until this picks it up;
* once a minute, finds runs whose worker died (``Runner.recover``);
* every six hours, reads the reviews taken back on the marketplaces it
  fetched from (``market.check``): believed only when a reviewer this
  person trusts signed them, and then the routines they name are paused.
  A marketplace out of reach is said once and tried at the next check.

THE QUEUE IS THE TABLE. Nothing tells the clock a run was added: the
program that adds one (``vidhi start``, in Samay's container or
Prahari's) only writes the row, and the clock finds it within a tick. So
a trigger needs no address, no token and no running server to reach --
only the state folder they share.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from vidhi.runner import Runner

TICK = 2.0
RUNNING = 4
RECOVER_EVERY = 60.0
TAKE_BACKS_EVERY = 6 * 3600.0


class Clock:
    def __init__(self, runner: Runner, *, tick: float = TICK,
                 take_backs: Callable[[], tuple[list[str], list[str]]] | None = None) -> None:
        self.runner = runner
        self.tick = tick
        self.take_backs = take_backs
        self._checked = 0.0
        self._pool = ThreadPoolExecutor(max_workers=RUNNING, thread_name_prefix="vidhi-run")
        self._busy: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._recovered = 0.0

    def once(self) -> list[str]:
        """One tick: what was started."""
        if time.monotonic() - self._recovered > RECOVER_EVERY:
            self.runner.recover()
            self._recovered = time.monotonic()
        if self.take_backs and (not self._checked
                                or time.monotonic() - self._checked > TAKE_BACKS_EVERY):
            self._checked = time.monotonic()
            threading.Thread(target=self._take_backs, daemon=True,
                             name="vidhi-take-backs").start()
        self.runner.wake()
        started = []
        for run in self.runner.store.due(self.runner.now()):
            if run.state != "queued":
                continue
            with self._lock:
                if run.id in self._busy or len(self._busy) >= RUNNING:
                    continue
                self._busy.add(run.id)
            self._pool.submit(self._go, run.id)
            started.append(run.id)
        return started

    def _take_backs(self) -> None:
        try:
            done, ignored = self.take_backs()
        except Exception as exc:             # never stops the clock
            print(f"vidhi: take-backs: {type(exc).__name__}: {exc}", flush=True)
            return
        for line in done:
            print(f"vidhi: {line}", flush=True)
        for line in ignored:
            print(f"vidhi: take-backs set aside: {line}", flush=True)

    def _go(self, run_id: str) -> None:
        try:
            self.runner.go(run_id)
        finally:
            with self._lock:
                self._busy.discard(run_id)

    def loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.once()
            except Exception as exc:          # the clock keeps going
                print(f"vidhi: clock: {type(exc).__name__}: {exc}", flush=True)
            self._stop.wait(self.tick)

    def stop(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=False)

    def drain(self, timeout: float = 30.0) -> None:
        """Wait until nothing is running (tests)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if not self._busy:
                    return
            time.sleep(0.02)
