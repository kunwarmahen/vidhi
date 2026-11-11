"""The marketplace: anyone may publish a routine; only a reviewed one is
listed, and only a signed one is installed.

TWO KINDS OF THING ARE SHARED. A routine (routine.py), and an INDRIYA
TEMPLATE: a reading for Prahari with blanks ("the outside temperature
for {latitude}, {longitude}, every 15m"), said by ``kind = "indriya"`` at
the top of its file. Both are published, reviewed, signed and checked
the same way; Prahari installs an indriya template, filled in, with its
owner's own accounts (``prahari indriya install NAME --from-market``,
which fetches it through ``vidhi market get``). Nobody runs a reading
for anybody else: each person runs their own copy.

    vidhi market publish FILE --to URL --as NAME     anyone: into the queue
    vidhi market queue --from URL                    what waits for review
    vidhi market show ID --from URL                  one, with the review notes
    vidhi market approve ID --key KEY --as REVIEWER  sign it, here, and list it
    vidhi market reject ID --why WORDS --key KEY --as REVIEWER
    vidhi market list --from URL                     what is listed
    vidhi market get NAME --from URL                 fetch one, check its signature
    vidhi market trust NAME 'ssh-ed25519 AAAA...'    a reviewer you trust
    vidhi market revoke NAME --version V --why WORDS --key KEY --as REVIEWER
    vidhi market check --from URL                    take-backs, applied here

and the server, ``vidhi market serve --dir DIR`` (or ``vidhi serve
--market DIR``, on the page's own port):

    GET  /market/                   a page: what is listed, the reviewers'
                                    keys, and how to fetch one
    GET  /market/index              the listed things, newest version each
    GET  /market/routines/NAME      one: its TOML, signature and reviewer
    GET  /market/reviewers          who may approve, with their public keys
    POST /market/publish            {toml, publisher, note}: into the queue
    GET  /market/queue              what waits, oldest first
    GET  /market/queue/ID           one, with the review notes
    POST /market/review/ID          {decision, reviewer, signature, why}
    GET  /market/routines/NAME/V    one version, listed or taken back
    POST /market/revoke/NAME        {version, reviewer, signature, why}
    GET  /market/revoked            every review taken back, each signed

REACHABLE FROM OUTSIDE, ALONE. ``vidhi market serve`` serves only
``/market/`` -- no page of anybody's routines, no API -- so it can be
put on the internet by itself (Tailscale Funnel: deploy/public-market-
tailscale.sh), as Prahari's inlet is. Behind such a proxy every request
comes from 127.0.0.1, so the address a publish is counted against is
the proxy's ``X-Forwarded-For`` -- taken ONLY from a request that came
from this computer, never from one that came straight in. The queue
holds ``MAX_QUEUE`` at most: a flood fills it and stops, it doesn't fill
the disk.

THE REVIEWERS' KEYS ARE SHOWN, NOT TRUSTED FROM HERE. ``/market/reviewers``
lists them so a person can compare them with what the reviewer published
somewhere else; ``vidhi market trust`` is still each person's own act. A
key a person trusts because the server said so would let a broken-into
server sign for itself.

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

A REVIEW CAN BE TAKEN BACK, BY WHO GAVE IT. A reviewer who finds they
were wrong signs ``revoke NAME VERSION SHA256: why`` (namespace
``vidhi-revoke``) on their own computer: ``vidhi market revoke NAME
--version V --why WORDS --key KEY --as REVIEWER``. The server takes it
only from the reviewer whose signature listed that version -- another
reviewer can disagree, not unsign -- and stops listing it (an older
version, still signed, is listed again). It keeps the signed take-back
at ``/market/revoked`` for everybody who already fetched it.

EACH VIDHI CHECKS THE TAKE-BACKS ITSELF. ``vidhi market check`` (and
``vidhi serve``, every six hours, against the marketplaces it fetched
from) reads ``/market/revoked`` and believes a take-back only when it is
signed by a reviewer THIS person trusts -- the same list ``get`` checks
against -- so a broken-into server can't pause anybody's routines. A
believed take-back is kept by the exact text's sha256 (store.py): that
text is refused by ``vidhi install``, and an installed routine whose
text it is gets PAUSED, its open runs stopped, and its owner told who
took the review back and why. Resuming it is refused; a mended copy is
another text, the person's own. The hash is what makes this exact: a
routine with the same name and a changed line is not the one reviewed.

THE ROUTINE ITSELF IS THE SAFETY. A routine has no code steps and no
loops (routine.py): every call, address and prompt is in the file, in
words, for the reviewer and then the installer to read. And every run
follows the person's own permissions, as any other turn does.

STANDARD LIBRARY ONLY, plus OpenSSH's ``ssh-keygen``, which signs and
verifies.
"""

from __future__ import annotations

import hashlib
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
REVOKE_NAMESPACE = "vidhi-revoke"
#: What a trusted reviewer's signature may be for.
NAMESPACES = (NAMESPACE, REJECT_NAMESPACE, REVOKE_NAMESPACE)
MAX_ROUTINE = 64 * 1024
#: Routines one address may publish in an hour.
PUBLISH_PER_HOUR = 10
#: Things waiting for review, at most: past it, publishing waits.
MAX_QUEUE = 100
#: What a file in the marketplace can be.
KINDS = ("routine", "indriya")
#: What an indriya template may say at its top, and in its check.
INDRIYA_TOP = {"kind", "name", "title", "about", "version", "author", "thing", "every",
               "pushed", "share", "inputs", "check"}
INDRIYA_CHECK = {"tool", "args", "pick"}
INDRIYA_INPUTS = ("text", "number")
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
    _upgrade(Path(allowed))
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


def _upgrade(path: Path) -> None:
    """A reviewers file written before take-backs lets its reviewers sign
    those too: the same people, one more thing they may sign."""
    try:
        text = path.read_text()
    except OSError:
        return
    wanted = f'namespaces="{",".join(NAMESPACES)}"'
    lines = [re.sub(r'namespaces="[^"]*"', wanted, ln) if "namespaces=" in ln else ln
             for ln in text.splitlines()]
    new = "\n".join(lines) + "\n"
    if new != text:
        path.write_text(new)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
    lines.append(f'{name} namespaces="{",".join(NAMESPACES)}" {words[0]} {words[1]}')
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


def refuse_revoked(store, text: str) -> None:
    """MarketError when a trusted reviewer took back their review of this
    exact text (``check``)."""
    found = store.revoked_for(sha256(text))
    if found:
        raise MarketError(f"{found['reviewer']} took back their review of {found['name']} "
                          f"version {found['version']}: {found['why'] or 'no reason given'}."
                          " It is not installed or run here")


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


# -- what a file is ----------------------------------------------------------------


def kind_of(text: str) -> str:
    """``routine`` or ``indriya``, from the file's own ``kind`` (a routine
    says none)."""
    import tomllib
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise MarketError(f"not TOML: {exc}") from None
    kind = str(data.get("kind") or "routine")
    if kind not in KINDS:
        raise MarketError(f"kind is {' or '.join(KINDS)}, not {kind!r}")
    return kind


def read_item(text: str) -> dict:
    """What a marketplace says about a file: its kind, name, title,
    version, about, cost and what it touches -- or an error in words."""
    if kind_of(text) == "routine":
        routine = rt.parse(text)
        return {"kind": "routine", "name": routine.name, "title": routine.title,
                "version": routine.version, "about": routine.about,
                "cost": rt.cost(routine), "touches": rt.touches(routine)}
    data = indriya_template(text)
    return {"kind": "indriya", "name": data["name"], "title": data["title"],
            "version": data["version"], "about": data["about"], "cost": "no model",
            "touches": indriya_touches(data)}


def indriya_template(text: str) -> dict:
    """An indriya template's shape, checked here; its full check is
    Prahari's, when it is installed. A template is ONE call (or a value
    pushed in), a pick, how often, and blanks: no code, nothing else."""
    import tomllib
    data = tomllib.loads(text)
    unknown = sorted(set(data) - INDRIYA_TOP)
    if unknown:
        raise MarketError(f"unknown keys for an indriya template: {', '.join(unknown)}")
    name = str(data.get("name") or "")
    if not rt.NAME_RE.match(name):
        raise MarketError(f"name {name!r}: one short lowercase word (outside-temp)")
    pushed = data.get("pushed", False)
    if not isinstance(pushed, bool):
        raise MarketError("pushed is true or false")
    check = data.get("check") or {}
    if not isinstance(check, dict) or set(check) - INDRIYA_CHECK:
        raise MarketError("check is a table: tool, args, pick")
    if pushed and check.get("tool"):
        raise MarketError("a pushed indriya makes no call: leave out check.tool")
    if not pushed:
        tool = check.get("tool")
        if not isinstance(tool, str) or not tool.strip() or " " in tool.strip():
            raise MarketError("check.tool is a tool's exact name (web_fetch)")
        if not isinstance(check.get("args", {}), dict):
            raise MarketError("check.args is a table: args = { url = \"...\" }")
    if not isinstance(check.get("pick", ""), str):
        raise MarketError("check.pick is words: json:a.b, number, text:PATTERN")
    every = str(data.get("every") or "15m")
    try:
        if rt.duration(every) < rt.MIN_EVERY:
            raise MarketError("every is 5 minutes at the least")
    except rt.RoutineError as exc:
        raise MarketError(str(exc)) from None
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise MarketError("inputs is a table of tables: [inputs.latitude] kind = \"number\"")
    for key, spec in inputs.items():
        spec = spec if isinstance(spec, dict) else {}
        if not rt.STEP_RE.match(key) or str(spec.get("kind") or "text") not in INDRIYA_INPUTS:
            raise MarketError(f"input {key!r}: one lowercase word, kind text or number")
    for found in rt.REF_RE.finditer(json.dumps(check)):
        if found.group(1) != "inputs" or (found.group(2) or "") not in inputs:
            raise MarketError(f"{found.group(0)} is not one of this template's inputs")
    return {"name": name, "title": str(data.get("title") or name)[:120],
            "version": str(data.get("version") or "1")[:20],
            "about": str(data.get("about") or "")[:2000], "every": every,
            "pushed": pushed, "check": check, "inputs": inputs,
            "thing": str(data.get("thing") or "")}


def indriya_touches(data: dict) -> list[str]:
    if data["pushed"]:
        return [f"waits for a value sent in (Home Assistant, a webhook), one every "
                f"{data['every']} at least; makes no call"]
    return [f"calls {data['check']['tool']} every {data['every']}, with no model: "
            f"{json.dumps(data['check'].get('args') or {})[:200]}",
            "with your own accounts, as you"]


def review_notes(text: str) -> list[str]:
    """What a reviewer should look at, worked out from the file itself."""
    if kind_of(text) == "indriya":
        data = indriya_template(text)
        notes = ["an indriya template (a reading for Prahari); no model"]
        if not data["pushed"] and data["check"]["tool"] not in PLAIN_READS \
                and not data["check"]["tool"].startswith("mcp__"):
            notes.append(f"CALLS {data['check']['tool']}, which is not a plain read: check "
                         "what it does")
        hosts = sorted({urllib.parse.urlparse(u).netloc
                        for v in _strings(data["check"].get("args") or {})
                        for u in re.findall(r"https?://[^\s\"'{}]+", v)})
        if hosts:
            notes.append("reaches: " + ", ".join(hosts))
        return notes + [f"touches: {line}" for line in indriya_touches(data)]
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
    def reviewers_file(self) -> Path:
        return self.root / "reviewers"

    def publish(self, text: str, publisher: str, note: str = "", *,
                address: str = "") -> dict:
        if len(text.encode()) > MAX_ROUTINE:
            raise MarketError(f"a routine is {MAX_ROUTINE // 1024} KB at most")
        publisher = publisher.strip()
        if not REVIEWER_RE.match(publisher):
            raise MarketError("publisher is your name, one word")
        item = read_item(text)
        if len(list((self.root / "queue").iterdir())) >= MAX_QUEUE:
            raise MarketError(f"{MAX_QUEUE} things already wait for review; try later")
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
        meta = {"id": ident, "kind": item["kind"], "name": item["name"],
                "title": item["title"], "version": item["version"], "publisher": publisher,
                "note": note[:1000], "submitted_at": iso(now_utc())}
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
        except (rt.RoutineError, MarketError) as exc:
            notes = [f"does not read: {exc}"]
        return {**_meta(folder), "toml": text, "notes": notes}

    def review(self, ident: str, decision: str, reviewer: str, signature: str,
               why: str = "") -> dict:
        folder = self._queued(ident)
        text = (folder / "routine.toml").read_text()
        meta = _meta(folder)
        if decision == "approve":
            signer = verify(text, signature, self.reviewers_file)
            if signer != reviewer:
                raise MarketError(f"signed by {signer}, not {reviewer}")
            item = read_item(text)
            target = self.root / "listed" / item["name"] / _safe(item["version"])
            other = self._kind_listed(item["name"])
            if other and other != item["kind"]:
                raise MarketError(f"{item['name']} is already listed as {_a(other)}; "
                                  f"{_a(item['kind'])} needs another name")
            if target.exists():
                raise MarketError(f"{item['name']} version {item['version']} is already "
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
            signer = verify(_reject_words(ident, why), signature, self.reviewers_file,
                            namespace=REJECT_NAMESPACE)
            if signer != reviewer:
                raise MarketError(f"signed by {signer}, not {reviewer}")
            meta.update(reviewer=signer, rejected_at=iso(now_utc()), why=why[:1000])
            target = self.root / "rejected" / ident
            shutil.move(str(folder), str(target))
            (target / "meta.json").write_text(json.dumps(meta, indent=2))
            return {**meta, "status": "rejected"}
        raise MarketError("decision is approve or reject")

    def revoke(self, name: str, version: str, reviewer: str, signature: str,
               why: str) -> dict:
        """Take a review back: only its own reviewer, signed, with a why."""
        if not why.strip():
            raise MarketError("a take-back says why")
        folder = self.root / "listed" / _safe(name) / _safe(version)
        if not (folder / "routine.toml").is_file():
            raise MarketError(f"no {name} version {version} is listed")
        meta = _meta(folder)
        if (folder / "revoked.json").exists():
            raise MarketError(f"{name} version {version}'s review was already taken back")
        text = (folder / "routine.toml").read_text()
        signer = verify(_revoke_words(name, version, sha256(text), why), signature,
                        self.reviewers_file, namespace=REVOKE_NAMESPACE)
        if signer != reviewer:
            raise MarketError(f"signed by {signer}, not {reviewer}")
        if signer != meta.get("reviewer"):
            raise MarketError(f"{name} version {version} was reviewed by "
                              f"{meta.get('reviewer')}; only they can take it back (you can "
                              "publish a newer version, or tell people why)")
        entry = {"name": meta.get("name") or name, "version": str(meta.get("version")
                                                                   or version),
                 "sha256": sha256(text), "reviewer": signer, "why": why.strip()[:1000],
                 "signature": signature, "revoked_at": iso(now_utc())}
        (folder / "revoked.json").write_text(json.dumps(entry, indent=2))
        return {**entry, "status": "taken back"}

    def revoked(self) -> list[dict]:
        out = []
        for path in sorted((self.root / "listed").glob("*/*/revoked.json")):
            try:
                entry = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(entry, dict):
                out.append(entry)
        return sorted(out, key=lambda e: e.get("revoked_at") or "")

    def version(self, name: str, version: str) -> dict:
        """One version, listed or taken back, with its signature."""
        folder = self.root / "listed" / _safe(name) / _safe(version)
        if not (folder / "routine.toml.sig").is_file():
            raise MarketError(f"no {name} version {version} was listed")
        text = (folder / "routine.toml").read_text()
        revoked = folder / "revoked.json"
        return {**_meta(folder), "kind": kind_of(text), "toml": text,
                "signature": (folder / "routine.toml.sig").read_text(),
                "sha256": sha256(text),
                "revoked": json.loads(revoked.read_text()) if revoked.exists() else None}

    def _versions(self, name_dir: Path) -> list[Path]:
        """A name's versions still listed: signed, and not taken back."""
        return [v for v in name_dir.iterdir() if (v / "routine.toml.sig").exists()
                and not (v / "revoked.json").exists()]

    def index(self) -> list[dict]:
        out = []
        for name_dir in sorted((self.root / "listed").iterdir()):
            versions = self._versions(name_dir)
            if not versions:
                continue
            newest = max(versions, key=lambda v: (_meta(v).get("approved_at") or ""))
            meta = _meta(newest)
            try:
                item = read_item((newest / "routine.toml").read_text())
            except (rt.RoutineError, MarketError):
                continue
            meta.update(kind=item["kind"], about=item["about"], cost=item["cost"],
                        touches=item["touches"])
            out.append(meta)
        return out

    def _kind_listed(self, name: str) -> str:
        """The kind already listed under ``name``, or ""."""
        folder = self.root / "listed" / _safe(name)
        for version in (folder.iterdir() if folder.is_dir() else []):
            path = version / "routine.toml"
            if path.is_file():
                try:
                    return kind_of(path.read_text())
                except MarketError:
                    continue
        return ""

    def reviewers(self) -> list[dict]:
        """Who may approve here, each with their public key: for a person
        to compare with what the reviewer published elsewhere."""
        out = []
        lines = self.reviewers_file.read_text().splitlines() \
            if self.reviewers_file.is_file() else []
        for line in lines:
            words = line.split()
            if len(words) >= 3:
                out.append({"name": words[0], "key": f"{words[-2]} {words[-1]}",
                            "trust": f"vidhi market trust {words[0]} "
                                     f"'{words[-2]} {words[-1]}'"})
        return out

    def listed(self, name: str) -> dict:
        folder = self.root / "listed" / _safe(name)
        versions = self._versions(folder) if folder.is_dir() else []
        if not versions:
            raise MarketError(f"no routine {name} is listed")
        newest = max(versions, key=lambda v: (_meta(v).get("approved_at") or ""))
        text = (newest / "routine.toml").read_text()
        return {**_meta(newest), "kind": kind_of(text), "toml": text,
                "signature": (newest / "routine.toml.sig").read_text()}

    def _queued(self, ident: str) -> Path:
        if not ID_RE.match(ident or ""):
            raise MarketError("no such routine in the queue")
        folder = self.root / "queue" / ident
        if not (folder / "routine.toml").is_file():
            raise MarketError("no such routine in the queue (reviewed already?)")
        return folder


def _a(kind: str) -> str:
    return ("an " if kind[:1] in "aeiou" else "a ") + kind


def _reject_words(ident: str, why: str) -> str:
    return f"reject {ident}: {why.strip()}\n"


def _revoke_words(name: str, version: str, digest: str, why: str) -> str:
    return f"revoke {name} {version} {digest}: {why.strip()}\n"


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
        read_item(text)    # say what's wrong here, not after a round trip
    except (rt.RoutineError, MarketError) as exc:
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


def revoke(base: str, name: str, version: str, why: str, key: Path,
           reviewer: str) -> dict:
    """Take back a review: the version's exact text fetched, its hash and
    the why signed HERE, the signature sent."""
    if not why.strip():
        raise MarketError("a take-back says why (--why)")
    item = _http("GET", _url(base, f"/market/routines/{urllib.parse.quote(name)}/"
                                   f"{urllib.parse.quote(str(version))}"))
    digest = sha256(str(item.get("toml") or ""))
    signature = sign(_revoke_words(name, str(version), digest, why), key, REVOKE_NAMESPACE)
    return _http("POST", _url(base, f"/market/revoke/{urllib.parse.quote(name)}"),
                 {"version": str(version), "reviewer": reviewer, "signature": signature,
                  "why": why})


def take_backs(base: str, state: Path) -> tuple[list[dict], list[str]]:
    """The marketplace's take-backs, each checked HERE: (believed -- signed
    by a reviewer this person trusts -- and what was set aside, in words)."""
    found = _http("GET", _url(base, "/market/revoked"))
    believed, ignored = [], []
    for entry in found if isinstance(found, list) else []:
        try:
            words = _revoke_words(str(entry["name"]), str(entry["version"]),
                                  str(entry["sha256"]), str(entry.get("why") or ""))
            signer = verify(words, str(entry.get("signature") or ""), trusted_file(state),
                            namespace=REVOKE_NAMESPACE)
        except (KeyError, TypeError):
            ignored.append("a take-back that doesn't read")
            continue
        except MarketError as exc:
            ignored.append(f"{entry.get('name')} v{entry.get('version')}: {exc}")
            continue
        if signer != entry.get("reviewer"):
            ignored.append(f"{entry.get('name')} v{entry.get('version')}: signed by "
                           f"{signer}, said to be {entry.get('reviewer')}")
            continue
        believed.append(entry)
    return believed, ignored


def apply_take_backs(store, runner, entries: list[dict], market: str = "") -> list[str]:
    """Keep each believed take-back, and pause every installed routine
    whose exact text it names: its open runs stopped, its owner told.
    What was done, one line each."""
    from vidhi.roads import Who
    said = []
    for entry in entries:
        new = store.add_revoked(entry, market)
        for installed in store.routines(None):
            if sha256(installed.toml) != entry["sha256"]:
                continue
            if installed.state == "active":
                store.set_routine(installed.owner, installed.name, state="paused")
            stopped = []
            for run in store.runs(owner=installed.owner, routine=installed.name, limit=100):
                if run.state in ("queued", "running", "waiting"):
                    try:
                        runner.stop(run.id)
                        stopped.append(run.id)
                    except ValueError:
                        pass
            if new:
                line = (f"{installed.name}: paused. {entry['reviewer']} took back their "
                        f"review of version {entry['version']}: "
                        f"{entry.get('why') or 'no reason given'}"
                        + (f" (stopped {len(stopped)} open run"
                           f"{'s' if len(stopped) != 1 else ''})" if stopped else ""))
                said.append(f"{installed.owner}: {line}")
                runner.roads.tell(Who(owner=installed.owner, runner=installed.runner,
                                      agent=installed.agent, run_id="",
                                      routine=installed.name),
                                  f"Vidhi: {line}. It stays paused; a mended copy is your "
                                  "own (vidhi edit), or install a newer reviewed version.")
        if new:
            said.append(f"taken back: {entry['name']} v{entry['version']} by "
                        f"{entry['reviewer']}")
    return said


def markets_used(state: Path) -> list[str]:
    """Every marketplace this Vidhi fetched from, and VIDHI_MARKET."""
    found = {p.read_text().strip().rstrip("/")
             for p in (Path(state) / "market").rglob("*.from") if p.is_file()}
    env = os.environ.get("VIDHI_MARKET", "").strip().rstrip("/")
    if env:
        found.add(env)
    return sorted(u for u in found if u)


def check(state: Path, store, runner, base: str = "") -> tuple[list[str], list[str]]:
    """Take-backs from one marketplace (or every one used): (done, set aside)."""
    done, ignored = [], []
    for url in ([base.rstrip("/")] if base else markets_used(state)):
        try:
            believed, skipped = take_backs(url, state)
        except MarketError as exc:
            ignored.append(f"{url}: {exc}")
            continue
        done += apply_take_backs(store, runner, believed, url)
        ignored += skipped
    return done, ignored


def index(base: str) -> list:
    return _http("GET", _url(base, "/market/index"))


def reviewers(base: str) -> list:
    return _http("GET", _url(base, "/market/reviewers"))


def get(base: str, name: str, state: Path) -> tuple[Path, str]:
    """Fetch a listed routine or indriya template, check its signature
    against the reviewers THIS person trusts, and keep it as a template:
    (where, signed by). An indriya template is kept apart
    (``market/indriyas/``): it is Prahari's to install, not a routine."""
    item = _http("GET", _url(base, f"/market/routines/{urllib.parse.quote(name)}"))
    text, signature = str(item.get("toml") or ""), str(item.get("signature") or "")
    signer = verify(text, signature, trusted_file(state))
    found = read_item(text)
    folder = Path(state) / "market" / ("indriyas" if found["kind"] == "indriya" else "")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{found['name']}.toml"
    path.write_text(text)
    Path(str(path) + ".sig").write_text(signature)
    (folder / f"{found['name']}.signer").write_text(signer + "\n")
    (folder / f"{found['name']}.from").write_text(_url(base, "") + "\n")
    return path, signer


# -- the marketplace's own page -----------------------------------------------------


def page(shop: Market, base: str = "") -> bytes:
    """``GET /market/``: what is listed, who reviews, and how to fetch one,
    for somebody who found the address and has nothing else."""
    from html import escape as e
    rows = []
    for item in shop.index():
        how = (f"prahari indriya install {item['name']} --from-market"
               if item.get("kind") == "indriya" else f"vidhi market get {item['name']}")
        rows.append(f"<li><b>{e(item['title'])}</b> <code>{e(item['name'])}</code> "
                    f"v{e(str(item['version']))} · {e(item.get('kind') or 'routine')} · "
                    f"{e(item.get('cost') or '')}<br><small>by {e(item.get('publisher') or '')}"
                    f", reviewed by {e(item.get('reviewer') or '')}</small>"
                    + (f"<p>{e(item['about'])}</p>" if item.get("about") else "")
                    + "<ul>" + "".join(f"<li>{e(t)}</li>" for t in item.get("touches") or [])
                    + f"</ul><pre>{e(how)}</pre></li>")
    keys = "".join(f"<li><b>{e(r['name'])}</b><pre>{e(r['trust'])}</pre></li>"
                   for r in shop.reviewers())
    where = e(base or "THIS-ADDRESS")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vidhi marketplace</title><style>
:root {{ color-scheme: light dark; --bg: #faf8f3; --ink: #1d1b16; --soft: #6f6a62; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #17161a; --ink: #ece8df;
  --soft: #a49e94; }} }}
body {{ background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif;
  max-width: 46rem; margin: 0 auto; padding: 1.5rem 16px; }}
small, .soft {{ color: var(--soft); }} li {{ margin: .6rem 0; }}
pre {{ white-space: pre-wrap; word-break: break-all; font-size: 13px; }}
</style></head><body>
<h1>Vidhi marketplace</h1>
<p class="soft">Routines and readings people wrote, each read and signed by a reviewer
before it is listed. Nothing here runs anything: you fetch one, read it, and install it
on your own computer, where it runs with your accounts and your permissions.</p>
<h2>Listed</h2><ul>{"".join(rows) or "<li class='soft'>nothing yet</li>"}</ul>
<h2>Fetch one</h2>
<pre>export VIDHI_MARKET={where}
vidhi market trust REVIEWER 'ssh-ed25519 AAAA...'   # a reviewer you trust
vidhi market get NAME                               # checked against YOUR trust list</pre>
<h2>Reviewers</h2>
<p class="soft">Their keys, as this marketplace has them. Compare a key with the one the
reviewer published somewhere else before you trust it: a key trusted because this page
said so is only as safe as this page.</p>
<ul>{keys or "<li class='soft'>none yet</li>"}</ul>
<h2>Publish</h2>
<pre>vidhi market publish my-routine.toml --to {where} --as YOUR-NAME</pre>
</body></html>""".encode()
