"""What Vidhi can tell a harness: is it here, is it running, how to talk
to it -- ``vidhi status --json``, the shape Setu, Samay and Prahari set for
this family of programs.

THE RUNNER HOLDS A LOCK, NOT A PID, as Samay's clock and Prahari's watch
do: ``vidhi serve`` takes an exclusive ``flock`` on ``serve.lock`` for as
long as it runs, which the kernel lets go however it dies, and which
every container mounting the same folder sees.

NO SECRET IS IN IT: not the page's token.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

from vidhi import version
from vidhi.store import Store

FORMAT = "vidhi.status.v1"
LOCK_FILE = "serve.lock"


def vidhi_command() -> str:
    beside = Path(sys.executable).parent / "vidhi"
    if beside.exists():
        return str(beside)
    return shutil.which("vidhi") or "vidhi"


def hold(state: Path):
    """Take the lock for this process's lifetime; the open file, or None
    when another ``vidhi serve`` holds it."""
    state.mkdir(parents=True, exist_ok=True)
    held = open(state / LOCK_FILE, "a")  # noqa: SIM115 -- held until exit
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        held.close()
        return None
    return held


def serving(state: Path) -> dict | None:
    """What ``vidhi serve`` wrote when it started, if it still runs."""
    try:
        with open(state / LOCK_FILE) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                return None
    except OSError:
        return None
    try:
        info = json.loads((state / "serve.json").read_text())
    except (OSError, ValueError):
        info = {}
    return info if isinstance(info, dict) else {}


def report(state: Path, store: Store) -> dict:
    counts: dict[str, int] = {}
    for installed in store.routines():
        counts[installed.state] = counts.get(installed.state, 0) + 1
    runs: dict[str, int] = {}
    for state_name in ("queued", "running", "waiting"):
        runs[state_name] = len(store.runs(state=state_name, limit=1000))
    served = serving(state)
    return {
        "format": FORMAT,
        "version": version.version(),
        "commit": version.commit(),
        "state": str(state),
        "serving": served is not None,
        "url": served.get("url") if served else None,
        "market": served.get("market") if served else None,
        "routines": counts,
        "runs": runs,
        "questions": len(store.questions()),
        "dvara": ((served or {}).get("dvara")
                  or os.environ.get("VIDHI_DVARA_URL", "").strip() or None),
        "mcp": {"command": vidhi_command(), "args": ["--state", str(state), "mcp"]},
    }
