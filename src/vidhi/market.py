"""The marketplace: anyone may publish a routine; only a reviewed one is
listed, and only a signed one is installed.

    vidhi market publish FILE --to URL --as NAME     anyone: into the queue
    vidhi market queue --from URL                    what waits for review
    vidhi market show ID --from URL                  one, with the review notes
    vidhi market approve ID --key KEY --as REVIEWER  sign it, here, and list it
    vidhi market reject ID --why WORDS --key KEY --as REVIEWER
    vidhi market list --from URL                     what is listed
    vidhi market get NAME --from URL                 fetch one, check its signature
    vidhi market trust NAME 'ssh-ed25519 AAAA...'    a reviewer you trust

and the server, ``vidhi market serve --dir DIR`` (or ``vidhi serve
--market DIR``, on the page's own port):

    GET  /market/index              the listed routines, newest version each
    GET  /market/routines/NAME      one: its TOML, signature and reviewer
    POST /market/publish            {toml, publisher, note}: into the queue
    GET  /market/queue              what waits, oldest first
    GET  /market/queue/ID           one, with the review notes
    POST /market/review/ID          {decision, reviewer, signature, why}

ANYONE MAY PUBLISH; NOTHING PUBLISHED IS INSTALLABLE. A routine sent in
is read and checked (it must parse: no loops, no unknown keys) and waits
in the queue. Nobody can install it from there. A REVIEWER reads it --
the review notes list every call and every address it reaches, every
question to the model, whether any step runs the agent with its tools
-- and approves or rejects it.

A SIGNATURE, NOT A CHECKBOX. Approving is signing the routine's exact
bytes with the reviewer's own SSH key (``ssh-keygen -Y sign``, namespace
``vidhi-routine``), on the reviewer's own computer: the private key never
reaches the server. The server lists it only if the signature verifies
against its list of reviewers (``DIR/reviewers``, OpenSSH's
allowed_signers form). A rejection is signed too (namespace
``vidhi-reject``), so nobody but a reviewer can empty the queue.

THE INSTALLER CHECKS AGAIN, AGAINST THEIR OWN LIST. ``vidhi market get``
verifies the signature against ``~/.vidhi/reviewers`` -- the reviewers
THIS person trusts (``vidhi market trust``), not the server's -- and
refuses a routine whose signature doesn't verify, or whose signer they
haven't trusted. A server that was broken into can't make a routine
installable here; it can only fail to list one. ``vidhi install`` checks
once more, so a file changed on disk after it was fetched isn't
installed.

THE ROUTINE ITSELF IS THE SAFETY. A routine has no code steps and no
loops (routine.py): every call, address and prompt is in the file, in
words, for the reviewer and then the installer to read. And every run
follows the person's own permissions, as any other turn does.

STANDARD LIBRARY ONLY, plus OpenSSH's ``ssh-keygen``, which signs and
verifies.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

from vidhi import routine as rt
from vidhi.store import iso, now_utc

NAMESPACE = "vidhi-routine"
REJECT_NAMESPACE = "vidhi-reject"
MAX_ROUTINE = 64 * 1024
#: Routines one address may publish in an hour.
PUBLISH_PER_HOUR = 10
REVIEWER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
ID_RE = re.compile(r"^[a-f0-9]{12}$")
QUICK = 30.0


class MarketError(ValueError):
    """A market request refused, in words."""


# -- signing, with OpenSSH ----------------------------------------------------------


def _keygen() -> str:
    found = shutil.which("ssh-keygen")
    if not found:
        raise MarketError("ssh-keygen is not installed: it signs and checks routines "
                          "(apt install openssh-client)")
    return found


def sign(text: str, key: Path, namespace: str = NAMESPACE) -> str:
    """The signature of ``text`` by the private ``key``, made here."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "routine.toml"
        path.write_text(text)
        done = subprocess.run([_keygen(), "-Y", "sign", "-f", str(Path(key).expanduser()),
                               "-n", namespace, str(path)], capture_output=True, text=True,
                              timeout=QUICK, stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            raise MarketError(f"ssh-keygen could not sign: {done.stderr.strip()}")
        return (Path(tmp) / "routine.toml.sig").read_text()


def verify(text: str, signature: str, allowed: Path, *,
           namespace: str = NAMESPACE) -> str:
    """The reviewer whose key signed ``text`` -- one listed in ``allowed``
    -- or MarketError."""
    if not Path(allowed).is_file() or not Path(allowed).read_text().strip():
        raise MarketError(f"no reviewers are trusted yet ({allowed}): vidhi market trust "
                          "NAME 'ssh-ed25519 AAAA...'")
    with tempfile.TemporaryDirectory() as tmp:
        sig = Path(tmp) / "sig"
        sig.write_text(signature)
        found = subprocess.run([_keygen(), "-Y", "find-principals", "-s", str(sig),
                                "-f", str(allowed)], capture_output=True, text=True,
                               timeout=QUICK, stdin=subprocess.DEVNULL)
        names = [n.strip() for n in found.stdout.splitlines() if n.strip()]
        if found.returncode != 0 or not names:
            raise MarketError("its signature is by nobody on the trusted reviewers' list")
        for name in names:
            done = subprocess.run([_keygen(), "-Y", "verify", "-f", str(allowed), "-I", name,
                                   "-n", namespace, "-s", str(sig)], input=text,
                                  capture_output=True, text=True, timeout=QUICK)
            if done.returncode == 0:
                return name
    raise MarketError("its signature does not match it: it was changed after it was "
                      "signed, or signed for something else")


def trusted_file(state: Path) -> Path:
    return Path(state) / "reviewers"


def trust(state: Path, name: str, public_key: str) -> Path:
    """Add a reviewer this person trusts (OpenSSH allowed_signers form)."""
    if not REVIEWER_RE.match(name):
        raise MarketError("a reviewer's name is one word: letters, digits, . _ @ -")
    words = public_key.split()
    if len(words) < 2 or not words[0].startswith(("ssh-", "ecdsa-", "sk-")):
        raise MarketError("a public key looks like 'ssh-ed25519 AAAA... comment' (the .pub "
                          "file's line)")
    path = trusted_file(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [ln for ln in (path.read_text().splitlines() if path.exists() else [])
             if ln.strip() and ln.split()[0] != name]
    lines.append(f'{name} namespaces="{NAMESPACE},{REJECT_NAMESPACE}" {words[0]} {words[1]}')
    path.write_text("\n".join(lines) + "\n")
    return path


def signer_of(path: Path) -> str:
    """The reviewer recorded beside a fetched template (``NAME.signer``)."""
    try:
        return Path(str(path)[:-len(".toml")] + ".signer").read_text().strip()
    except OSError:
        return ""


def check_installable(state: Path, path: Path, text: str) -> str:
    """A template from a marketplace, checked again before it is installed:
    the reviewer it is signed by, or MarketError."""
    sig = Path(str(path) + ".sig")
    if not sig.is_file():
        raise MarketError(f"{path.name} has no signature beside it: not installable")
    return verify(text, sig.read_text(), trusted_file(state))


#: Tools a call may use that are plainly reading: anything else is said.
PLAIN_READS = ("web_fetch", "read_file", "list_dir", "grep", "glob")


def look_closer(routine: rt.Routine) -> list[str]:
    """What deserves a second look before a yes, in capitals: a step that
    runs the agent with its tools, a call whose arguments come from an
    earlier step, a tool that is neither a plain read nor a connected
    account's. A reviewer is shown these; so is a person about to install."""
    out = []
    for step in routine.steps:
        name = step.title or step.id
        if step.kind == "ask" and step.tools:
            out.append(f"{name}: RUNS YOUR AGENT WITH ITS TOOLS (each still asked as your "
                       "rules say)")
        if step.kind == "call":
            if rt.uses_results(step.args):
                out.append(f"{name}: CALLS {step.body} WITH WHAT AN EARLIER STEP FOUND "
                           "(it runs only if that tool only reads)")
            if step.body not in PLAIN_READS and not step.body.startswith("mcp__"):
                out.append(f"{name}: CALLS {step.body}, which is not a plain read: check "
                           "what it does")
    return out


def reaches(routine: rt.Routine) -> list[str]:
    """Every web address a routine's calls name."""
    hosts: set[str] = set()
    for step in routine.steps:
        if step.kind == "call":
            for value in _strings(step.args):
                for url in re.findall(r"https?://[^\s\"'{}]+", value):
                    hosts.add(urllib.parse.urlparse(url).netloc)
    return sorted(hosts)


def review_notes(text: str) -> list[str]:
    """What a reviewer should look at, worked out from the routine itself."""
    routine = rt.parse(text)
    notes = [f"{len(routine.steps)} steps; {rt.cost(routine)}"]
    notes += look_closer(routine)
    hosts = reaches(routine)
    if hosts:
        notes.append("reaches: " + ", ".join(hosts))
    accounts = rt.needs_accounts(routine)
    if accounts:
        notes.append("needs accounts: " + ", ".join(accounts))
    notes += [f"touches: {line}" for line in rt.touches(routine)]
    return notes


def _strings(value) -> list[str]:
    out: list[str] = []
    rt._strings(value, out)
    return out


# -- the server's side --------------------------------------------------------------


class Market:
    """A marketplace kept in a folder:

        DIR/reviewers                    who may approve (allowed_signers)
        DIR/queue/ID/routine.toml        waiting, with meta.json
        DIR/listed/NAME/VERSION/         routine.toml, routine.toml.sig, meta.json
        DIR/rejected/ID/                 routine.toml, meta.json (with why)
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        for part in ("queue", "listed", "rejected"):
            (self.root / part).mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._published: dict[str, deque] = {}

    @property
    def reviewers(self) -> Path:
        return self.root / "reviewers"

    def publish(self, text: str, publisher: str, note: str = "", *,
                address: str = "") -> dict:
        if len(text.encode()) > MAX_ROUTINE:
            raise MarketError(f"a routine is {MAX_ROUTINE // 1024} KB at most")
        publisher = publisher.strip()
        if not REVIEWER_RE.match(publisher):
            raise MarketError("publisher is your name, one word")
        routine = rt.parse(text)
        with self._lock:
            sent = self._published.setdefault(address, deque())
            hour_ago = time.monotonic() - 3600
            while sent and sent[0] < hour_ago:
                sent.popleft()
            if len(sent) >= PUBLISH_PER_HOUR:
                raise MarketError(f"{PUBLISH_PER_HOUR} routines an hour from one address, "
                                  "at most; try later")
            sent.append(time.monotonic())
        ident = secrets.token_hex(6)
        folder = self.root / "queue" / ident
        folder.mkdir(parents=True)
        (folder / "routine.toml").write_text(text)
        meta = {"id": ident, "name": routine.name, "title": routine.title,
                "version": routine.version, "publisher": publisher, "note": note[:1000],
                "submitted_at": iso(now_utc())}
        (folder / "meta.json").write_text(json.dumps(meta, indent=2))
        return {**meta, "status": "waiting for review"}

    def queue(self) -> list[dict]:
        out = []
        for folder in (self.root / "queue").iterdir():
            meta = _meta(folder)
            if meta:
                out.append(meta)
        return sorted(out, key=lambda m: m.get("submitted_at") or "")

    def queued(self, ident: str) -> dict:
        folder = self._queued(ident)
        text = (folder / "routine.toml").read_text()
        try:
            notes = review_notes(text)
        except rt.RoutineError as exc:
            notes = [f"does not read: {exc}"]
        return {**_meta(folder), "toml": text, "notes": notes}

    def review(self, ident: str, decision: str, reviewer: str, signature: str,
               why: str = "") -> dict:
        folder = self._queued(ident)
        text = (folder / "routine.toml").read_text()
        meta = _meta(folder)
        if decision == "approve":
            signer = verify(text, signature, self.reviewers)
            if signer != reviewer:
                raise MarketError(f"signed by {signer}, not {reviewer}")
            routine = rt.parse(text)
            target = self.root / "listed" / routine.name / _safe(routine.version)
            if target.exists():
                raise MarketError(f"{routine.name} version {routine.version} is already "
                                  "listed; a new one needs a new version")
            target.mkdir(parents=True)
            (target / "routine.toml").write_text(text)
            (target / "routine.toml.sig").write_text(signature)
            meta.update(reviewer=signer, approved_at=iso(now_utc()))
            (target / "meta.json").write_text(json.dumps(meta, indent=2))
            shutil.rmtree(folder)
            return {**meta, "status": "listed"}
        if decision == "reject":
            if not why.strip():
                raise MarketError("a rejection says why")
            signer = verify(_reject_words(ident, why), signature, self.reviewers,
                            namespace=REJECT_NAMESPACE)
            if signer != reviewer:
                raise MarketError(f"signed by {signer}, not {reviewer}")
            meta.update(reviewer=signer, rejected_at=iso(now_utc()), why=why[:1000])
            target = self.root / "rejected" / ident
            shutil.move(str(folder), str(target))
            (target / "meta.json").write_text(json.dumps(meta, indent=2))
            return {**meta, "status": "rejected"}
        raise MarketError("decision is approve or reject")

    def index(self) -> list[dict]:
        out = []
        for name_dir in sorted((self.root / "listed").iterdir()):
            versions = [v for v in name_dir.iterdir() if (v / "routine.toml.sig").exists()]
            if not versions:
                continue
            newest = max(versions, key=lambda v: (_meta(v).get("approved_at") or ""))
            meta = _meta(newest)
            try:
                routine = rt.parse((newest / "routine.toml").read_text())
                meta.update(about=routine.about, cost=rt.cost(routine),
                            touches=rt.touches(routine))
            except rt.RoutineError:
                continue
            out.append(meta)
        return out

    def listed(self, name: str) -> dict:
        folder = self.root / "listed" / _safe(name)
        versions = [v for v in folder.iterdir()] if folder.is_dir() else []
        versions = [v for v in versions if (v / "routine.toml.sig").exists()]
        if not versions:
            raise MarketError(f"no routine {name} is listed")
        newest = max(versions, key=lambda v: (_meta(v).get("approved_at") or ""))
        return {**_meta(newest), "toml": (newest / "routine.toml").read_text(),
                "signature": (newest / "routine.toml.sig").read_text()}

    def _queued(self, ident: str) -> Path:
        if not ID_RE.match(ident or ""):
            raise MarketError("no such routine in the queue")
        folder = self.root / "queue" / ident
        if not (folder / "routine.toml").is_file():
            raise MarketError("no such routine in the queue (reviewed already?)")
        return folder


def _reject_words(ident: str, why: str) -> str:
    return f"reject {ident}: {why.strip()}\n"


def _meta(folder: Path) -> dict:
    try:
        data = json.loads((folder / "meta.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _safe(word: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(word))[:40]
    return cleaned if cleaned.strip(".") else "_"


# -- the person's side --------------------------------------------------------------


def _url(base: str, path: str) -> str:
    base = (base or os.environ.get("VIDHI_MARKET", "")).strip().rstrip("/")
    if not base:
        raise MarketError("which marketplace? --from URL (or set VIDHI_MARKET)")
    return base + path


def _http(method: str, url: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=QUICK) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            said = json.loads(exc.read() or b"{}").get("detail")
        except (json.JSONDecodeError, AttributeError):
            said = None
        raise MarketError(f"the marketplace said {exc.code}: {said or exc.reason}") from None
    except urllib.error.URLError as exc:
        raise MarketError(f"cannot reach the marketplace at {url}: {exc.reason}") from None


def publish(base: str, text: str, publisher: str, note: str = "") -> dict:
    try:
        rt.parse(text)     # say what's wrong here, not after a round trip
    except rt.RoutineError as exc:
        raise MarketError(f"it does not read: {exc}") from None
    return _http("POST", _url(base, "/market/publish"),
                 {"toml": text, "publisher": publisher, "note": note})


def queue(base: str) -> list:
    return _http("GET", _url(base, "/market/queue"))


def show(base: str, ident: str) -> dict:
    return _http("GET", _url(base, f"/market/queue/{urllib.parse.quote(ident)}"))


def approve(base: str, ident: str, key: Path, reviewer: str) -> dict:
    """Sign the queued routine's exact text HERE, and send the signature."""
    item = show(base, ident)
    signature = sign(item["toml"], key)
    return _http("POST", _url(base, f"/market/review/{urllib.parse.quote(ident)}"),
                 {"decision": "approve", "reviewer": reviewer, "signature": signature})


def reject(base: str, ident: str, why: str, key: Path, reviewer: str) -> dict:
    signature = sign(_reject_words(ident, why), key, REJECT_NAMESPACE)
    return _http("POST", _url(base, f"/market/review/{urllib.parse.quote(ident)}"),
                 {"decision": "reject", "reviewer": reviewer, "signature": signature,
                  "why": why})


def index(base: str) -> list:
    return _http("GET", _url(base, "/market/index"))


def get(base: str, name: str, state: Path) -> tuple[Path, str]:
    """Fetch a listed routine, check its signature against the reviewers
    THIS person trusts, and keep it as a template: (where, signed by)."""
    item = _http("GET", _url(base, f"/market/routines/{urllib.parse.quote(name)}"))
    text, signature = str(item.get("toml") or ""), str(item.get("signature") or "")
    signer = verify(text, signature, trusted_file(state))
    routine = rt.parse(text)
    folder = Path(state) / "market"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{routine.name}.toml"
    path.write_text(text)
    Path(str(path) + ".sig").write_text(signature)
    (folder / f"{routine.name}.signer").write_text(signer + "\n")
    (folder / f"{routine.name}.from").write_text(_url(base, "") + "\n")
    return path, signer
