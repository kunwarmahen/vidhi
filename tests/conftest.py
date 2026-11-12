"""Shared pieces: a scratch state folder (never ~/.vidhi), and roads that
answer from a table instead of starting Yantra, Prahari or Dvara."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from vidhi.roads import Done, Who
from vidhi.runner import Runner
from vidhi.store import Store


class FakeRoads:
    """Answers each step from ``answers``: a tool name or a word in the
    prompt -> Done (or a function of the arguments). Records everything."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.told: list[tuple[str, str, list | None]] = []
        self.answers: dict = {}
        self.delay = 0.0
        self.started: dict[str, float] = {}
        self._lock = threading.Lock()
        self.dvara = None
        self.kept_readings: list[dict] = []

    def readings(self, owner: str) -> list[dict]:
        self.calls.append(("readings", owner))
        return self.kept_readings

    def _log(self, key, *rest):
        with self._lock:
            self.calls.append((key, *rest))
            self.started[str(key)] = time.monotonic()
        if self.delay:
            time.sleep(self.delay)

    def _answer(self, key, *args) -> Done:
        got = self.answers.get(key)
        if callable(got):
            return got(*args)
        return got if isinstance(got, Done) else Done(True, f"<{key}>")

    def call(self, who: Who, tool: str, args: dict, *, granted: bool) -> Done:
        self._log(tool, args, granted)
        return self._answer(tool, args)

    def ask(self, who: Who, prompt: str, *, tools: bool) -> Done:
        self._log("ask", prompt, tools)
        for word, done in self.answers.items():
            if isinstance(word, str) and word.startswith("ask:") and word[4:] in prompt:
                return done
        return Done(True, "ANSWER", cost_usd=0.01)

    def read(self, who: Who, name: str, max_age: str = "") -> Done:
        self._log("read", name)
        return self._answer(f"read:{name}")

    def tell(self, who: Who, text: str, taps: list | None = None) -> Done:
        with self._lock:
            self.told.append((who.owner, text, taps))
        return Done(True, "sent")


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "vidhi"


@pytest.fixture
def store(state: Path) -> Store:
    found = Store.at(state)
    yield found
    found.close()


@pytest.fixture
def roads() -> FakeRoads:
    return FakeRoads()


@pytest.fixture
def runner(store: Store, roads: FakeRoads) -> Runner:
    return Runner(store, roads)
