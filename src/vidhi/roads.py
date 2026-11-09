"""Who does each step's work: never Vidhi itself.

Vidhi keeps the routine and the order; every step is done by a program
that already does that one thing, started as a program, its JSON read
back. Vidhi imports none of them and has no dependencies of its own.

    call    ``yantra --call TOOL --args JSON`` (no model), here -- or, on
            the Dvara road, ``POST /call`` AS THE PERSON, with their own
            accounts (Dvara's notes/56)
    ask     ``yantra --prompt``: with NO TOOLS by default (the model reads
            and writes, nothing else, and nothing is remembered); with
            ``tools = true``, an ordinary unattended agent turn -- here,
            or through Dvara as the person, their rules and allowance
    read    ``prahari indriya get NAME --json --as PERSON``: Prahari
            decides what this person may read
    notify  Dvara's ``POST /notify``, the person's own channels

THE ROAD IS THE PERSON'S. A routine installed for somebody in the house
runs as them: its calls read THEIR mail, through Dvara, never the
owner's. One installed at the computer (``local``) runs here, with this
computer's accounts -- or through Dvara as its owner, when it was
installed with ``--runner dvara``.

A CALL IS GRANTED WORD FOR WORD. Exactly as a Prahari look:
``--allow-tools`` holds a grant fixing every argument, so the call the
person said yes to runs, and nothing else does. A call whose arguments
came from an earlier step gets no grant, and runs only if its tool only
reads.

A QUESTION TO THE PERSON IS A NOTICE WITH TWO BUTTONS. ``tell`` passes
``taps``: words a channel draws as buttons, which a press sends as if
typed (``/routines yes K7Q2MX``). The words are in the text too, for a
channel that draws no buttons.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CALL_FORMAT = "yantra.call.v1"
RUN_FORMAT = "yantra.run.v1"
CALL_LIMIT = 180
ASK_LIMIT = 600
READ_LIMIT = 60
QUICK = 30.0
KILL_GRACE = 5.0
STDERR_TAIL = 15
LOCAL = "local"


class RunnerMissing(RuntimeError):
    """A program a step needs is not where it was looked for."""


@dataclass
class Done:
    """What one step's worker said."""

    ok: bool
    text: str = ""
    detail: str = ""
    cost_usd: float = 0.0


@dataclass
class Who:
    """Whose run this is, and how it goes."""

    owner: str
    runner: str = "direct"
    agent: str = ""
    run_id: str = ""
    routine: str = ""

    @property
    def asked_by(self) -> str:
        """For a phone's log (Sparsh's page): which program asked."""
        return f"Vidhi: {self.routine or 'a routine'}"


def find(program: str, env: str) -> list[str]:
    configured = os.environ.get(env, "").strip()
    if configured:
        return shlex.split(configured)
    beside = Path(sys.executable).parent / program
    if beside.exists():
        return [str(beside)]
    found = shutil.which(program)
    if found:
        return [found]
    raise RunnerMissing(f"cannot find {program}: set {env} to the command that starts it")


def grant_for(tool: str, args: dict) -> str | None:
    """The grant covering exactly this call (Yantra's Grant form), or None."""
    if not args:
        return None
    parts = []
    for key, value in args.items():
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, str):
            text = value.strip()
        else:
            text = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if any(c in text for c in ',()" \\') or not text:
            text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        parts.append(f"{key}={text}")
    return f"{tool}(" + ", ".join(parts) + ")"


@dataclass(frozen=True)
class Dvara:
    url: str
    token: str
    #: Who a routine installed here ("local") is for.
    actor: str = ""

    @classmethod
    def from_env(cls) -> Dvara | None:
        url = os.environ.get("VIDHI_DVARA_URL", "").strip().rstrip("/")
        if not url:
            return None
        token = os.environ.get("VIDHI_DVARA_TOKEN", "").strip()
        if not token:
            raise RuntimeError("VIDHI_DVARA_URL is set but VIDHI_DVARA_TOKEN is not: "
                               "Dvara refuses a caller without its token")
        return cls(url=url, token=token,
                   actor=os.environ.get("VIDHI_DVARA_ACTOR", "").strip())

    def actor_for(self, owner: str) -> str:
        return owner if owner and owner != LOCAL else self.actor

    def call(self, method: str, path: str, body: dict | None = None,
             timeout: float = QUICK) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.url + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                said = json.loads(exc.read() or b"{}").get("detail")
            except (json.JSONDecodeError, AttributeError):
                said = None
            raise RuntimeError(f"dvara said {exc.code}: {said or exc.reason}") from None
        except TimeoutError:
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError(str(exc.reason)) from None
            raise RuntimeError(f"cannot reach dvara at {self.url}: {exc.reason}") from None


class Roads:
    """Every step's worker, on the run's own road."""

    def __init__(self, work: Path, *, dvara: Dvara | None = None,
                 yantra: list[str] | None = None, prahari: list[str] | None = None,
                 home: Path | None = None) -> None:
        self.work = Path(work)
        self.dvara = dvara
        self.yantra = yantra
        self.prahari = prahari
        raw = os.environ.get("VIDHI_YANTRA_HOME", "").strip()
        self.home = home or (Path(raw).expanduser() if raw else None)

    # -- one tool, no model ---------------------------------------------------------

    def call(self, who: Who, tool: str, args: dict, *, granted: bool) -> Done:
        grant = grant_for(tool, args) if granted else None
        if who.runner == "dvara":
            dvara, actor = self._dvara(who)
            if dvara is None:
                return Done(False, detail=actor)
            body = {"actor": actor, "agent": who.agent, "tool": tool, "args": args,
                    "allow_tools": [grant] if grant else [], "came_by": "vidhi",
                    "label": who.routine}
            try:
                data = dvara.call("POST", "/call", body, timeout=CALL_LIMIT)
            except TimeoutError:
                return Done(False, detail=f"the call took longer than {CALL_LIMIT}s")
            except RuntimeError as exc:
                return Done(False, detail=str(exc))
            if data.get("format") != CALL_FORMAT:
                return Done(False, detail=f"dvara answered in a format this Vidhi does not "
                                          f"know ({data.get('format')!r})")
            return Done(bool(data.get("ok")), str(data.get("text") or ""),
                        _needs(data) or str(data.get("detail") or ""))
        try:
            command = self.yantra or find("yantra", "VIDHI_YANTRA")
        except RunnerMissing as exc:
            return Done(False, detail=str(exc))
        where = self._where(who)
        argv = [*command, "--cwd", str(where), "--json", "--call", tool,
                "--args", json.dumps(args)]
        if who.agent:
            argv += ["--agent", who.agent]
        if grant:
            argv += ["--allow-tools", grant]
        out, err, timed_out = _run(argv, cwd=self._cwd(where), limit=CALL_LIMIT,
                                   env={**os.environ, "YANTRA_ASKED_BY": who.asked_by})
        if timed_out:
            return Done(False, detail=f"the call took longer than {CALL_LIMIT}s")
        data = _json_line(out, CALL_FORMAT)
        if isinstance(data, str):
            return Done(False, detail=data or _tail(err) or "yantra printed no answer")
        return Done(bool(data.get("ok")), str(data.get("text") or ""),
                    _needs(data) or str(data.get("detail") or ""))

    # -- a question to the model ----------------------------------------------------

    def ask(self, who: Who, prompt: str, *, tools: bool) -> Done:
        if tools and who.runner == "dvara":
            dvara, actor = self._dvara(who)
            if dvara is None:
                return Done(False, detail=actor)
            body = {"actor": actor, "agent": who.agent, "text": prompt,
                    "thread": f"vidhi-{who.routine}-{who.run_id}", "unattended": True,
                    "came_by": "vidhi", "label": who.routine, "allow_tools": [],
                    "wait": 600}
            try:
                reply = dvara.call("POST", "/message", body, timeout=ASK_LIMIT + 600)
            except TimeoutError:
                return Done(False, detail="no answer from dvara in time")
            except RuntimeError as exc:
                return Done(False, detail=str(exc))
            return Done(bool(reply.get("ok")), str(reply.get("text") or ""),
                        _needs(reply) or str(reply.get("detail") or ""),
                        float(reply.get("cost_usd") or 0.0))
        try:
            command = self.yantra or find("yantra", "VIDHI_YANTRA")
        except RunnerMissing as exc:
            return Done(False, detail=str(exc))
        where = self._where(who)
        env = {**os.environ, "YANTRA_UNATTENDED": "1", "YANTRA_ASKED_BY": who.asked_by}
        if tools:
            argv = [*command, "--cwd", str(where), "--json", "--unattended"]
            if who.agent:
                argv += ["--agent", who.agent]
            if self.dvara is not None and self.dvara.actor_for(who.owner):
                env.update(YANTRA_ASK_URL=self.dvara.url, YANTRA_ASK_TOKEN=self.dvara.token,
                           YANTRA_ASK_ACTOR=self.dvara.actor_for(who.owner),
                           YANTRA_ASK_WAIT="600")
        else:
            # Words in, words out: no tool, no sibling, nothing remembered.
            argv = [*command, "--cwd", str(where), "--json", "--unattended", "--no-skills",
                    "--no-setu", "--no-samay", "--no-sparsh", "--no-prahari",
                    "--memory", "off", "--learn", "off", "--reflect", "off"]
            env.update(YANTRA_DISABLED_TOOLS="*", YANTRA_ENV_CONTEXT="off")
        argv += ["--prompt", prompt]
        out, err, timed_out = _run(argv, cwd=self._cwd(where), limit=ASK_LIMIT, env=env)
        if timed_out:
            return Done(False, detail=f"the model took longer than {ASK_LIMIT}s")
        data = _json_line(out, RUN_FORMAT)
        if isinstance(data, str):
            return Done(False, detail=data or _tail(err) or "yantra printed no answer")
        return Done(bool(data.get("ok")), str(data.get("text") or "").strip(),
                    _needs(data) or str(data.get("detail") or ""),
                    float(data.get("cost_usd") or 0.0))

    # -- a reading Prahari keeps ----------------------------------------------------

    def read(self, who: Who, name: str, max_age: str = "") -> Done:
        try:
            command = self.prahari or find("prahari", "VIDHI_PRAHARI")
        except RunnerMissing as exc:
            return Done(False, detail=str(exc))
        argv = [*command, "indriya", "get", name, "--json"]
        if who.owner and who.owner != LOCAL:
            argv.append(f"--as={who.owner}")
        if max_age:
            argv.append(f"--max-age={max_age}")
        self.work.mkdir(parents=True, exist_ok=True)
        out, err, timed_out = _run(argv, cwd=self.work, limit=READ_LIMIT + 200)
        if timed_out:
            return Done(False, detail="prahari took too long to answer")
        try:
            card = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
        except json.JSONDecodeError:
            card = None
        if not isinstance(card, dict):
            return Done(False, detail=_tail(err) or _tail(out) or "prahari said nothing")
        if card.get("value") in (None, ""):
            return Done(False, detail=f"the reading {name} has no value yet"
                        + (f" ({card.get('last_error')})" if card.get("last_error") else ""))
        age = str(card.get("age") or "")
        return Done(True, str(card["value"]), f"read {age}".strip())

    # -- telling the person ---------------------------------------------------------

    def tell(self, who: Who, text: str, taps: list[dict] | None = None) -> Done:
        """On their channels, through Dvara. ``ok`` with ``text`` saying
        where it went: sent, kept (for a channel to collect), or nowhere."""
        if self.dvara is None:
            return Done(True, "nowhere", "this Vidhi has no Dvara to tell anyone through "
                                         "(VIDHI_DVARA_URL); kept on the run")
        actor = self.dvara.actor_for(who.owner)
        if not actor:
            return Done(True, "nowhere", "no person to tell: set VIDHI_DVARA_ACTOR")
        body: dict = {"actor": actor, "text": text}
        if taps:
            body["taps"] = taps
        try:
            sent = self.dvara.call("POST", "/notify", body)
        except (RuntimeError, TimeoutError) as exc:
            return Done(False, detail=str(exc))
        where = ("sent" if sent.get("sent") else "kept" if sent.get("kept")
                 else "nowhere")
        return Done(True, where, "" if where != "nowhere" else
                    f"{actor} has no channel Dvara can reach")

    # -- where ----------------------------------------------------------------------

    def _dvara(self, who: Who) -> tuple[Dvara | None, str]:
        if self.dvara is None:
            return None, ("this routine runs through Dvara, as its person, and this Vidhi "
                          "has no Dvara (set VIDHI_DVARA_URL and VIDHI_DVARA_TOKEN)")
        actor = self.dvara.actor_for(who.owner)
        if not actor or not who.agent:
            return None, ("a step through Dvara names its person and their agent; this "
                          "routine has " + ("no agent" if actor else "nobody"))
        return self.dvara, actor

    def _where(self, who: Who) -> Path:
        where = self.work / (who.run_id or "now")
        where.mkdir(parents=True, exist_ok=True)
        return where

    def _cwd(self, where: Path) -> Path:
        return self.home if self.home and self.home.is_dir() else where


def _needs(data: dict) -> str:
    needs = [str(n) for n in data.get("needs_person") or []]
    return ("needs you: " + "; ".join(needs)) if needs else ""


def _run(argv: list[str], *, cwd: Path, limit: float,
         env: dict[str, str] | None = None) -> tuple[str, str, bool]:
    """(stdout, stderr, timed out). A session of its own, so anything the
    program started goes down with it at the limit."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    except OSError as exc:
        return "", f"could not start {argv[0]}: {exc}", False
    try:
        out, err = proc.communicate(timeout=limit)
        return out, err, False
    except subprocess.TimeoutExpired:
        for sig, wait in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, None)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                out, err = proc.communicate(timeout=wait)
                return out, err, True
            except subprocess.TimeoutExpired:
                continue
        out, err = proc.communicate()
        return out, err, True


def _json_line(out: str, want: str) -> dict | str:
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("format") != want:
            return (f"yantra answered in a format this Vidhi does not know "
                    f"({data.get('format')!r}; want {want})")
        return data
    return ""


def _tail(err: str) -> str:
    return "\n".join((err or "").strip().splitlines()[-STDERR_TAIL:])
