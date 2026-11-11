"""Everything Vidhi keeps, in one SQLite file: ``~/.vidhi/vidhi.sqlite``.

    routines    each person's installed routines: the TOML, the inputs they
                filled, which road it runs on
    runs        each run: a COPY of the routine as it was when the run
                started, its inputs, who started it, where it is
    steps       each step of each run: waiting, done, skipped, failed, and
                what it gave
    questions   what a run asked its person, the answer, and by when

A RUN IS ROWS, NOT A PROCESS. Every step's result is written the moment
it is known, so a run that stops to ask somebody -- for a minute or for a
day -- is nothing but rows saying where it got to. ``vidhi serve`` (or a
restart of it) picks it up from there. A run that was half way through a
step when the process died does that step again, and says so.

A RUN KEEPS ITS OWN COPY. Mending a routine while one of its runs waits
on a question changes the next run, never that one: the steps a person
saw start are the steps that finish.

THE SAME FILE FROM EVERY CONTAINER. Sarathi mounts ``~/.vidhi`` in each
container that may start a run (Samay's, Prahari's, Dvara's), as it does
``~/.prahari``. Starting one is adding a row; WAL lets them all read
while one writes.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

#: Runs kept per routine, newest; older ones go.
RUNS_KEPT = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    owner TEXT NOT NULL, name TEXT NOT NULL, toml TEXT NOT NULL,
    inputs TEXT NOT NULL DEFAULT '{}', runner TEXT NOT NULL DEFAULT 'direct',
    agent TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'local',
    signed_by TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'active',
    installed_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (owner, name));
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, routine TEXT NOT NULL,
    toml TEXT NOT NULL, inputs TEXT NOT NULL DEFAULT '{}',
    runner TEXT NOT NULL DEFAULT 'direct', agent TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'queued', started_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, started_at TEXT, ended_at TEXT, wake_at TEXT,
    heartbeat TEXT, detail TEXT NOT NULL DEFAULT '',
    cost_usd REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS runs_by_routine ON runs (owner, routine, created_at);
CREATE INDEX IF NOT EXISTS runs_by_state ON runs (state);
CREATE TABLE IF NOT EXISTS steps (
    run_id TEXT NOT NULL, step_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', result TEXT NOT NULL DEFAULT '',
    why TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
    started_at TEXT, ended_at TEXT, wake_at TEXT,
    cost_usd REAL NOT NULL DEFAULT 0, passes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, step_id));
CREATE TABLE IF NOT EXISTS questions (
    code TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
    owner TEXT NOT NULL, text TEXT NOT NULL, asked_at TEXT NOT NULL,
    until TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
    answered_at TEXT, via TEXT NOT NULL DEFAULT '', told TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'yesno', choices TEXT NOT NULL DEFAULT '[]',
    expects TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS questions_by_owner ON questions (owner, answer);
CREATE TABLE IF NOT EXISTS revoked (
    sha256 TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
    reviewer TEXT NOT NULL, why TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT '', market TEXT NOT NULL DEFAULT '',
    learned_at TEXT NOT NULL);
"""


#: Columns a file made before them lacks, added when it is opened.
ADDED = {"steps": (("passes", "INTEGER NOT NULL DEFAULT 0"),),
         "questions": (("kind", "TEXT NOT NULL DEFAULT 'yesno'"),
                       ("choices", "TEXT NOT NULL DEFAULT '[]'"),
                       ("expects", "TEXT NOT NULL DEFAULT ''"))}


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(when: datetime | None) -> str | None:
    return when.astimezone(UTC).isoformat(timespec="seconds") if when else None


def from_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


@dataclass
class Installed:
    owner: str
    name: str
    toml: str
    inputs: dict = field(default_factory=dict)
    runner: str = "direct"
    agent: str = ""
    #: local (written here), catalog (a template from this computer), or
    #: the marketplace's address it came from.
    source: str = "local"
    #: The reviewer whose signature it carried, for one from a marketplace.
    signed_by: str = ""
    state: str = "active"
    installed_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Run:
    id: str
    owner: str
    routine: str
    toml: str
    inputs: dict = field(default_factory=dict)
    runner: str = "direct"
    agent: str = ""
    #: queued, running, waiting (on a person or the clock), done, failed,
    #: stopped (by the person)
    state: str = "queued"
    #: who started it, in words: "page", "dvara", "samay:ID", "prahari:ID",
    #: "agent", "cli"
    started_by: str = ""
    created_at: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    wake_at: str | None = None
    heartbeat: str | None = None
    detail: str = ""
    cost_usd: float = 0.0

    def as_dict(self) -> dict:
        out = asdict(self)
        out.pop("toml")
        return out


@dataclass
class StepRow:
    run_id: str
    step_id: str
    #: pending, running, waiting, done, skipped, failed
    state: str = "pending"
    result: str = ""
    why: str = ""
    detail: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    wake_at: str | None = None
    cost_usd: float = 0.0
    #: A repeat's passes so far.
    passes: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Question:
    code: str
    run_id: str
    step_id: str
    owner: str
    text: str
    asked_at: str
    until: str
    answer: str = ""
    answered_at: str | None = None
    via: str = ""
    #: where the question was put: "dvara", "nowhere"
    told: str = ""
    #: what it takes: yesno, choice (one of ``choices``), or words
    kind: str = "yesno"
    choices: list = field(default_factory=list)
    #: what typed words must be: "" (any words), "number", "number:60:80", "time"
    expects: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30,
                                   isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.executescript(SCHEMA)
        for table, columns in ADDED.items():
            have = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns:
                if name not in have:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @classmethod
    def at(cls, state: Path) -> Store:
        return cls(Path(state) / "vidhi.sqlite")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._db.execute(sql, params)
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def _run(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            return self._db.execute(sql, params).rowcount

    # -- installed routines ---------------------------------------------------------

    def install(self, routine: Installed) -> Installed:
        stamp = iso(now_utc())
        routine.installed_at = routine.installed_at or stamp
        routine.updated_at = stamp
        self._run(
            "INSERT INTO routines (owner, name, toml, inputs, runner, agent, source, "
            "signed_by, state, installed_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(owner, name) DO UPDATE SET toml=excluded.toml, "
            "inputs=excluded.inputs, runner=excluded.runner, agent=excluded.agent, "
            "source=excluded.source, signed_by=excluded.signed_by, state=excluded.state, "
            "updated_at=excluded.updated_at",
            (routine.owner, routine.name, routine.toml, json.dumps(routine.inputs),
             routine.runner, routine.agent, routine.source, routine.signed_by,
             routine.state, routine.installed_at, routine.updated_at))
        return routine

    def routine(self, owner: str, name: str) -> Installed | None:
        rows = self._rows("SELECT * FROM routines WHERE owner = ? AND name = ?",
                          (owner, name))
        return _installed(rows[0]) if rows else None

    def routines(self, owner: str | None = None) -> list[Installed]:
        if owner is None:
            rows = self._rows("SELECT * FROM routines ORDER BY owner, name")
        else:
            rows = self._rows("SELECT * FROM routines WHERE owner = ? ORDER BY name",
                              (owner,))
        return [_installed(r) for r in rows]

    def set_routine(self, owner: str, name: str, **values) -> None:
        values["updated_at"] = iso(now_utc())
        if "inputs" in values:
            values["inputs"] = json.dumps(values["inputs"])
        sets = ", ".join(f"{k} = ?" for k in values)
        self._run(f"UPDATE routines SET {sets} WHERE owner = ? AND name = ?",
                  (*values.values(), owner, name))

    def uninstall(self, owner: str, name: str) -> bool:
        return self._run("DELETE FROM routines WHERE owner = ? AND name = ?",
                         (owner, name)) > 0

    # -- runs -----------------------------------------------------------------------

    def new_run(self, run: Run, step_ids: list[str]) -> Run:
        run.id = run.id or secrets.token_hex(4)
        run.created_at = run.created_at or iso(now_utc())
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute(
                    "INSERT INTO runs (id, owner, routine, toml, inputs, runner, agent, "
                    "state, started_by, created_at, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (run.id, run.owner, run.routine, run.toml, json.dumps(run.inputs),
                     run.runner, run.agent, run.state, run.started_by, run.created_at,
                     run.detail))
                self._db.executemany(
                    "INSERT INTO steps (run_id, step_id) VALUES (?, ?)",
                    [(run.id, s) for s in step_ids])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        self._trim(run.owner, run.routine)
        return run

    def _trim(self, owner: str, routine: str) -> None:
        old = self._rows(
            "SELECT id FROM runs WHERE owner = ? AND routine = ? AND state IN "
            "('done', 'failed', 'stopped') ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (owner, routine, RUNS_KEPT))
        for row in old:
            self.forget_run(row["id"])

    def forget_run(self, run_id: str) -> None:
        for table, key in (("questions", "run_id"), ("steps", "run_id"), ("runs", "id")):
            self._run(f"DELETE FROM {table} WHERE {key} = ?", (run_id,))

    def run(self, run_id: str) -> Run | None:
        rows = self._rows("SELECT * FROM runs WHERE id = ?", (run_id,))
        return _run_row(rows[0]) if rows else None

    def runs(self, owner: str | None = None, routine: str | None = None,
             state: str | None = None, limit: int = 50) -> list[Run]:
        where, params = [], []
        for column, value in (("owner", owner), ("routine", routine), ("state", state)):
            if value is not None:
                where.append(f"{column} = ?")
                params.append(value)
        sql = "SELECT * FROM runs" + (f" WHERE {' AND '.join(where)}" if where else "")
        rows = self._rows(sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                          (*params, max(1, min(int(limit), 1000))))
        return [_run_row(r) for r in rows]

    def set_run(self, run_id: str, **values) -> None:
        sets = ", ".join(f"{k} = ?" for k in values)
        self._run(f"UPDATE runs SET {sets} WHERE id = ?", (*values.values(), run_id))

    def claim(self, run_id: str, *, states: tuple[str, ...] = ("queued",)) -> bool:
        """Take a run to work on, if nobody else has: one process runs it."""
        marks = ",".join("?" for _ in states)
        stamp = iso(now_utc())
        return self._run(
            f"UPDATE runs SET state = 'running', heartbeat = ?, "
            f"started_at = COALESCE(started_at, ?) WHERE id = ? AND state IN ({marks})",
            (stamp, stamp, run_id, *states)) > 0

    def due(self, now: datetime) -> list[Run]:
        """Runs ready to go on: queued, or waiting and their time has come."""
        rows = self._rows(
            "SELECT * FROM runs WHERE state = 'queued' OR (state = 'waiting' AND "
            "wake_at IS NOT NULL AND wake_at <= ?) ORDER BY created_at", (iso(now),))
        return [_run_row(r) for r in rows]

    def stale(self, before: datetime) -> list[Run]:
        """Runs marked running whose worker stopped beating before ``before``."""
        rows = self._rows("SELECT * FROM runs WHERE state = 'running' AND "
                          "(heartbeat IS NULL OR heartbeat < ?)", (iso(before),))
        return [_run_row(r) for r in rows]

    # -- steps ----------------------------------------------------------------------

    def steps(self, run_id: str) -> list[StepRow]:
        rows = self._rows("SELECT * FROM steps WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [StepRow(**r) for r in rows]

    def set_step(self, run_id: str, step_id: str, **values) -> None:
        sets = ", ".join(f"{k} = ?" for k in values)
        self._run(f"UPDATE steps SET {sets} WHERE run_id = ? AND step_id = ?",
                  (*values.values(), run_id, step_id))

    # -- questions ------------------------------------------------------------------

    def ask(self, question: Question) -> Question:
        question.code = question.code or _code()
        self._run(
            "INSERT INTO questions (code, run_id, step_id, owner, text, asked_at, until, "
            "told, kind, choices, expects) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (question.code, question.run_id, question.step_id, question.owner,
             question.text, question.asked_at, question.until, question.told,
             question.kind, json.dumps(question.choices), question.expects))
        return question

    def question(self, code: str) -> Question | None:
        rows = self._rows("SELECT * FROM questions WHERE code = ?", (code.strip().upper(),))
        return _question(rows[0]) if rows else None

    def question_for(self, run_id: str, step_id: str) -> Question | None:
        rows = self._rows("SELECT * FROM questions WHERE run_id = ? AND step_id = ?",
                          (run_id, step_id))
        return _question(rows[0]) if rows else None

    def forget_question(self, run_id: str, step_id: str) -> None:
        """A repeated step's old question, so its next pass asks afresh."""
        self._run("DELETE FROM questions WHERE run_id = ? AND step_id = ?", (run_id, step_id))

    def questions(self, owner: str | None = None, *, open_only: bool = True) -> list[Question]:
        where = ["answer = ''"] if open_only else []
        params: list = []
        if owner is not None:
            where.append("owner = ?")
            params.append(owner)
        sql = "SELECT * FROM questions" + (f" WHERE {' AND '.join(where)}" if where else "")
        return [_question(r) for r in self._rows(sql + " ORDER BY asked_at DESC",
                                                 tuple(params))]

    def answer(self, code: str, answer: str, via: str) -> bool:
        """Write an answer once; a second answer is refused (False)."""
        return self._run(
            "UPDATE questions SET answer = ?, answered_at = ?, via = ? "
            "WHERE code = ? AND answer = ''",
            (answer, iso(now_utc()), via, code.strip().upper())) > 0

    def set_question(self, code: str, **values) -> None:
        sets = ", ".join(f"{k} = ?" for k in values)
        self._run(f"UPDATE questions SET {sets} WHERE code = ?", (*values.values(), code))


    # -- reviews taken back (market.py) ----------------------------------------------

    def add_revoked(self, entry: dict, market: str = "") -> bool:
        """A review a trusted reviewer took back, kept by the exact text's
        sha256. True when it is new here."""
        return self._run(
            "INSERT OR IGNORE INTO revoked (sha256, name, version, reviewer, why, "
            "revoked_at, market, learned_at) VALUES (?,?,?,?,?,?,?,?)",
            (entry["sha256"], entry["name"], str(entry["version"]), entry["reviewer"],
             str(entry.get("why") or "")[:1000], str(entry.get("revoked_at") or ""),
             market, iso(now_utc()))) > 0

    def revoked_for(self, sha256: str) -> dict | None:
        rows = self._rows("SELECT * FROM revoked WHERE sha256 = ?", (sha256,))
        return dict(rows[0]) if rows else None

    def revoked(self) -> list[dict]:
        return [dict(r) for r in self._rows("SELECT * FROM revoked ORDER BY learned_at DESC",
                                            ())]


#: A question's code: short enough to type on a phone, no 0/O or 1/I.
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _code() -> str:
    return "".join(secrets.choice(CODE_LETTERS) for _ in range(6))


def _question(row: dict) -> Question:
    row = dict(row)
    try:
        row["choices"] = json.loads(row.get("choices") or "[]")
    except ValueError:
        row["choices"] = []
    return Question(**{f.name: row[f.name] for f in fields(Question) if f.name in row})


def _installed(row: dict) -> Installed:
    row = dict(row)
    row["inputs"] = json.loads(row.get("inputs") or "{}")
    return Installed(**{f.name: row[f.name] for f in fields(Installed) if f.name in row})


def _run_row(row: dict) -> Run:
    row = dict(row)
    row["inputs"] = json.loads(row.get("inputs") or "{}")
    return Run(**{f.name: row[f.name] for f in fields(Run) if f.name in row})
