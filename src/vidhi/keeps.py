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

WHAT IS LEFT OUT: the record of a running server (``serve.json``, and its
lock), which would name a process that isn't there, and each run's
working folder (``work/``), which Yantra fills and nothing reads back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

FORMAT = "vidhi.keeps.v1"
LEAVE_OUT = ["serve.json", "serve.lock", "work"]


def report(state: Path) -> dict[str, Any]:
    keeps = [{"id": "state", "path": str(Path(state).resolve()),
              "what": "your routines, their runs and questions, your templates and "
                      "the reviewers you trust",
              "leave_out": LEAVE_OUT, "exists": Path(state).exists()}]
    return {"format": FORMAT, "keeps": keeps}
