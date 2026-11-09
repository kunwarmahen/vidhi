"""What Vidhi keeps on this computer, for a backup to take.

A backup of the house (Sarathi's ``sarathi backup``) is one file holding
every program's own files, and each program says where its are --
``vidhi keeps --json``, asked the way ``status --json`` is -- so the
program that packs it knows nothing of what is inside.

Vidhi's is its state folder: the routines and their inputs, every run
and what each step gave, the questions and their answers
(``vidhi.sqlite``, copied with SQLite's own backup), your own templates,
the ones fetched from a marketplace with their signatures, the reviewers
you trust, and the page's key.

A MARKETPLACE THIS COMPUTER RUNS (``vidhi market serve``, kept in
``~/.vidhi-market`` or ``$VIDHI_MARKET_DIR``) is kept too, when there is
one: its reviewers' keys, what waits for review, and what was listed with
each reviewer's signature -- none of which can be made again.

WHAT IS LEFT OUT: the record of a running server (``serve.json``, and its
lock), which would name a process that isn't there, and each run's
working folder (``work/``), which Yantra fills and nothing reads back.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

FORMAT = "vidhi.keeps.v1"
LEAVE_OUT = ["serve.json", "serve.lock", "work"]


def report(state: Path) -> dict[str, Any]:
    keeps = [{"id": "state", "path": str(Path(state).resolve()),
              "what": "your routines, their runs and questions, your templates and "
                      "the reviewers you trust",
              "leave_out": LEAVE_OUT, "exists": Path(state).exists()}]
    shop = market_dir()
    if shop.is_dir():
        keeps.append({"id": "market", "path": str(shop.resolve()),
                      "what": "the marketplace this computer runs: its reviewers, its "
                              "queue, and what it lists, signed",
                      "leave_out": [], "exists": True})
    return {"format": FORMAT, "keeps": keeps}


def market_dir() -> Path:
    """Where ``vidhi market serve`` keeps a marketplace when not told."""
    raw = os.environ.get("VIDHI_MARKET_DIR", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".vidhi-market"
