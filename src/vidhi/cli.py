"""``vidhi`` -- routines you draw once, which a schedule, a watch, a button or
a chat can start.

    vidhi templates                          what can be installed
    vidhi install morning-brief --input latitude=51.5
    vidhi list                               installed routines, in words
    vidhi run morning-brief                  start one now, and follow it
    vidhi start morning-brief --by samay:ID  only queue it (for a trigger)
    vidhi runs [NAME]                        how its runs went
    vidhi steps RUN                          one run, step by step
    vidhi questions / vidhi answer CODE yes  what runs wait to hear
    vidhi check FILE                         read a routine; what it would do
    vidhi save NAME FILE                     mend one (the canvas does this too)
    vidhi serve                              the page, and the clock that runs
    vidhi mcp --for PERSON                   tools for an agent
    vidhi keeps                              where it all is, for a backup
    vidhi market ...                         publish, review, fetch (market.py)

``--as PERSON`` acts for somebody in the house; leave it out for this
computer's own person (``local``). Every command that a program reads
takes ``--json``.

A RUN STARTED HERE GOES ON HERE when ``vidhi serve`` isn't running, so
``vidhi run`` works on a laptop with nothing else started; with a
server running it is queued for the server and followed until it ends
or waits.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from vidhi import catalog, market, routines, starters
from vidhi import routine as rt
from vidhi.clock import Clock
from vidhi.roads import Dvara, Roads
from vidhi.runner import RunError, Runner, describe, installed_card
from vidhi.status import hold, report, serving
from vidhi.store import Store

LOCAL = "local"
FOLLOW_LIMIT = 900.0


def state_dir(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser()
    configured = os.environ.get("VIDHI_STATE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".vidhi"


def make_runner(state: Path, store: Store, page: str = "") -> Runner:
    try:
        dvara = Dvara.from_env()
    except RuntimeError as exc:
        print(f"vidhi: {exc}", file=sys.stderr)
        dvara = None
    roads = Roads(state / "work", dvara=dvara)
    page = page or os.environ.get("VIDHI_PUBLIC_URL", "").strip()
    if not page:
        served = serving(state)
        page = str((served or {}).get("url") or "")
    return Runner(store, roads, page=page)


def _inputs(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise rt.RoutineError(f"--input is NAME=VALUE, not {pair!r}")
        out[key.strip()] = value
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vidhi", description=(
        "routines you draw once, which a schedule, a watch, a button or a chat can start"))
    parser.add_argument("--state", default=None, help="state folder (default ~/.vidhi, "
                                                      "or $VIDHI_STATE)")
    sub = parser.add_subparsers(dest="command", required=True)

    def who(p):
        p.add_argument("--as", dest="as_actor", default=LOCAL, metavar="PERSON",
                       help="for somebody in the house (default: this computer's person)")

    def js(p):
        p.add_argument("--json", action="store_true", dest="json_out")

    p = sub.add_parser("status", help="is Vidhi here, is it running")
    js(p)
    p = sub.add_parser("keeps", help="where the routines are kept, for a backup")
    js(p)
    p = sub.add_parser("templates", help="routines ready to install")
    js(p)
    p = sub.add_parser("install", help="install a template, or a routine from a file")
    p.add_argument("what", help="a template's name, or a .toml file")
    p.add_argument("--input", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--runner", default="direct", choices=routines.RUNNERS)
    p.add_argument("--agent", default="", help="the agent its steps run as")
    p.add_argument("--replace", action="store_true")
    who(p)
    js(p)
    p = sub.add_parser("list", help="installed routines")
    p.add_argument("--all", action="store_true", help="everyone's")
    who(p)
    js(p)
    p = sub.add_parser("show", help="one routine, in words")
    p.add_argument("name")
    p.add_argument("--toml", action="store_true", help="print its TOML")
    who(p)
    js(p)
    p = sub.add_parser("check", help="read a routine file: what's wrong, or what it does")
    p.add_argument("file")
    js(p)
    p = sub.add_parser("save", help="mend an installed routine from a file")
    p.add_argument("name")
    p.add_argument("file")
    who(p)
    p = sub.add_parser("inputs", help="change what a routine's blanks are filled with")
    p.add_argument("name")
    p.add_argument("pairs", nargs="+", metavar="NAME=VALUE")
    who(p)
    p = sub.add_parser("starts", help="what starts a routine (Samay schedules, Prahari "
                                      "watches); or make or remove one")
    p.add_argument("name", nargs="?", default="",
                   help="the routine (leave out: every routine's)")
    p.add_argument("--at", default="", metavar="WHEN",
                   help="make a Samay schedule that starts it: 'at 20:00', "
                        "'at 07:30 on mon-fri'")
    p.add_argument("--on", default="", metavar="READING",
                   help="make a Prahari watch on this reading that starts it "
                        "(with --when)")
    p.add_argument("--when", default="", metavar="TEST",
                   help="with --on: 'below 35', 'above 80'")
    p.add_argument("--input", action="append", default=[], metavar="NAME=VALUE",
                   help="the starter's own value for one of the routine's blanks")
    p.add_argument("--rm", default="", metavar="BY:ID",
                   help="remove one of its starters: samay:3e02c5cd, prahari:43dff0b2")
    who(p)
    js(p)
    for name, text in (("run", "start one now, and follow it"),
                       ("start", "queue a run and say its id (for a trigger)")):
        p = sub.add_parser(name, help=text)
        p.add_argument("name")
        p.add_argument("--input", action="append", default=[], metavar="NAME=VALUE")
        p.add_argument("--by", default="cli", help="who started it, in words "
                                                   "(samay:ID, prahari:ID)")
        p.add_argument("--found", default=None, metavar="WORDS",
                       help="what a watch saw: the routine's input found, if it has one")
        if name == "run":
            p.add_argument("--no-wait", action="store_true")
        who(p)
        js(p)
    p = sub.add_parser("runs", help="how its runs went")
    p.add_argument("name", nargs="?")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--all", action="store_true", help="everyone's")
    who(p)
    js(p)
    p = sub.add_parser("steps", help="one run, step by step")
    p.add_argument("run")
    js(p)
    p = sub.add_parser("questions", help="what runs are waiting to hear")
    p.add_argument("--all", action="store_true")
    who(p)
    js(p)
    p = sub.add_parser("answer", help="answer a run's question: yes or no, a choice "
                                      "(its words or number), or a few words")
    p.add_argument("code")
    p.add_argument("word", nargs="+")
    p.add_argument("--via", default="the terminal")
    p.add_argument("--any", action="store_true", help="whoever it was put to (the "
                                                      "computer's own person may)")
    who(p)
    js(p)
    p = sub.add_parser("stop", help="stop a run")
    p.add_argument("run")
    who(p)
    js(p)
    for name in ("pause", "resume", "rm"):
        p = sub.add_parser(name, help=f"{name} a routine")
        p.add_argument("name")
        who(p)
    p = sub.add_parser("serve", help="the page, its API, and the clock that runs routines")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8786)
    p.add_argument("--public-url", default=None)
    p.add_argument("--market", default=None, metavar="DIR",
                   help="also serve a marketplace kept in DIR")
    p = sub.add_parser("mcp", help="tools for an agent (stdin/stdout)")
    p.add_argument("--for", dest="person", default=LOCAL)
    p.add_argument("--agent", default="")
    p.add_argument("--runner", default="direct", choices=routines.RUNNERS)

    m = sub.add_parser("market", help="publish, review and fetch routines")
    msub = m.add_subparsers(dest="verb", required=True)
    q = msub.add_parser("publish", help="send a routine (or an indriya template) to a "
                                        "marketplace's queue")
    q.add_argument("file")
    q.add_argument("--to", dest="base", default="")
    q.add_argument("--as", dest="publisher", required=True, metavar="YOUR_NAME")
    q.add_argument("--note", default="")
    q = msub.add_parser("queue", help="what waits for review")
    q.add_argument("--from", dest="base", default="")
    q = msub.add_parser("show", help="one waiting routine, with the review notes")
    q.add_argument("id")
    q.add_argument("--from", dest="base", default="")
    for verb in ("approve", "reject"):
        q = msub.add_parser(verb, help=f"{verb} one, signed with your key")
        q.add_argument("id")
        q.add_argument("--from", dest="base", default="")
        q.add_argument("--key", required=True, help="your private SSH key (~/.ssh/id_ed25519)")
        q.add_argument("--as", dest="reviewer", required=True, metavar="REVIEWER")
        if verb == "reject":
            q.add_argument("--why", required=True)
    q = msub.add_parser("list", help="what a marketplace lists")
    q.add_argument("--from", dest="base", default="")
    q.add_argument("--kind", choices=market.KINDS, default=None,
                   help="only routines, or only indriya templates")
    q.add_argument("--json", action="store_true", dest="json_out")
    q = msub.add_parser("get", help="fetch a listed routine (or indriya template), if "
                                    "its signature is by a reviewer you trust")
    q.add_argument("name")
    q.add_argument("--from", dest="base", default="")
    q.add_argument("--json", action="store_true", dest="json_out")
    q = msub.add_parser("reviewers", help="who a marketplace says may approve, with "
                                          "their keys (to compare, not to trust from)")
    q.add_argument("--from", dest="base", default="")
    q = msub.add_parser("trust", help="trust a reviewer's signatures")
    q.add_argument("name")
    q.add_argument("key", help="their public key line, or a .pub file")
    q = msub.add_parser("revoke", help="take back your review of one version, signed "
                                       "with your key")
    q.add_argument("name")
    q.add_argument("--version", required=True)
    q.add_argument("--why", required=True)
    q.add_argument("--from", dest="base", default="")
    q.add_argument("--key", required=True, help="your private SSH key (~/.ssh/id_ed25519)")
    q.add_argument("--as", dest="reviewer", required=True, metavar="REVIEWER")
    q = msub.add_parser("check", help="reviews taken back, by reviewers you trust: "
                                      "pause what they name")
    q.add_argument("--from", dest="base", default="",
                   help="one marketplace (default: every one you fetched from)")
    q = msub.add_parser("revoked", help="the reviews taken back that this Vidhi believed "
                                        "(Prahari asks, for its readings)")
    q.add_argument("--json", action="store_true", dest="json_out")
    q = msub.add_parser("reviewer", help="(a marketplace's own) let someone approve")
    q.add_argument("name")
    q.add_argument("key", help="their public key line, or a .pub file")
    q.add_argument("--dir", required=True)
    q = msub.add_parser("serve", help="run a marketplace by itself (only /market/)")
    q.add_argument("--dir", default=None,
                   help="where it keeps what it lists (default $VIDHI_MARKET_DIR, or "
                        "~/.vidhi-market)")
    q.add_argument("--host", default="127.0.0.1")
    q.add_argument("--port", type=int, default=8788)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state = state_dir(args.state)
    try:
        if args.command == "market":
            return _market(args, state)
        if args.command == "mcp":
            return _mcp(args, state)
        if args.command == "serve":
            return _serve(args, state)
        if args.command == "keeps":
            # before the store is opened: asking where never makes the file
            from vidhi.keeps import report as keeps
            said = keeps(state)
            if args.json_out:
                print(json.dumps(said))
            else:
                for place in said["keeps"]:
                    print(f"{place['id']}  {place['path']}  ({place['what']})")
            return 0
        store = Store.at(state)
        if getattr(args, "as_actor", None):
            args.as_actor = routines.person(store, args.as_actor)
        return COMMANDS[args.command](args, state, store)
    except (rt.RoutineError, RunError, market.MarketError) as exc:
        if getattr(args, "json_out", False):
            print(json.dumps({"error": str(exc)}))
        print(f"error: {exc}", file=sys.stderr)
        return 1


# -- commands -----------------------------------------------------------------------


def _status(args, state, store) -> int:
    data = report(state, store)
    if args.json_out:
        print(json.dumps(data))
        return 0
    print(f"vidhi {data['version']}  state: {data['state']}")
    print(f"serving: {data['url'] or 'no (vidhi serve)'}")
    routines_said = ", ".join(f"{n} {k}" for k, n in data["routines"].items()) or "none"
    print(f"routines: {routines_said}; runs going: {data['runs']['running']}, "
          f"queued: {data['runs']['queued']}, waiting: {data['runs']['waiting']}; "
          f"questions open: {data['questions']}")
    return 0


def _templates(args, state, store) -> int:
    found, broken = catalog.templates(state)
    if args.json_out:
        print(json.dumps({"templates": [t.card() for t in found], "broken": broken}))
        return 0
    for one in found:
        card = one.card()
        print(f"{card['name']}  ({card['source']}"
              + (f", signed by {card['signed_by']}" if card["signed_by"] else "") + ")")
        print(f"    {card['title']}: {card['cost']}")
        for spec in card["inputs"]:
            default = f" (default {spec['default']})" if "default" in spec else ""
            print(f"    --input {spec['name']}=...  {spec['label']}{default}")
    for line in broken:
        print(f"broken: {line}", file=sys.stderr)
    return 0


def _install(args, state, store) -> int:
    path = Path(args.what).expanduser()
    signed_by, source = "", "local"
    if path.suffix == ".toml" and path.is_file():
        text = path.read_text()
    else:
        found = catalog.template(state, args.what)
        text = found.text
        source = {"vidhi": "catalog"}.get(found.source, found.source)
        if found.source == "market":
            signed_by = market.check_installable(state, Path(found.path), text)
    made = routines.install(store, args.as_actor, text, inputs=_inputs(args.input),
                            runner=args.runner, agent=args.agent, source=source,
                            signed_by=signed_by, replace=args.replace)
    card = installed_card(made)
    if args.json_out:
        print(json.dumps(card))
        return 0
    print(f"installed {made.name} for {made.owner}: {card['title']} ({card['cost']})")
    for line in card["touches"]:
        print(f"  {line}")
    return 0


def _list(args, state, store) -> int:
    found = store.routines(None if args.all else args.as_actor)
    cards = [installed_card(r, store) for r in found]
    if args.json_out:
        print(json.dumps(cards))
        return 0
    if not cards:
        print("no routines (vidhi templates, then vidhi install NAME)")
    for n, card in enumerate(cards, start=1):
        owner = f" [{card['owner']}]" if args.all else ""
        print(f"{n}. {card['name']}{owner}  {card['state']}  {card.get('title')} "
              f"-- {card.get('cost')}")
        if card.get("broken"):
            print(f"    broken: {card['broken']}")
        if card.get("taken_back"):
            back = card["taken_back"]
            print(f"    review taken back by {back['reviewer']} (version {back['version']}): "
                  f"{back['why'] or 'no reason given'}")
        if card["inputs"]:
            print("    inputs: " + ", ".join(f"{k}={v}" for k, v in card["inputs"].items()))
    return 0


def _show(args, state, store) -> int:
    installed = routines.find(store, args.as_actor, args.name)
    if args.toml:
        print(installed.toml, end="")
        return 0
    card = installed_card(installed)
    if args.json_out:
        print(json.dumps({**card, "toml": installed.toml}))
        return 0
    print(f"{card['name']}: {card.get('title')}  ({card['state']}, {card.get('cost')})")
    if card.get("about"):
        print(f"  {card['about']}")
    for n, wave in enumerate(card.get("waves") or [], start=1):
        print(f"  {n}. {' + '.join(wave)}")
    for line in card.get("touches") or []:
        print(f"  - {line}")
    return 0


def _check(args, state, store) -> int:
    from vidhi.http import check
    said = check(Path(args.file).expanduser().read_text())
    if args.json_out:
        print(json.dumps(said))
        return 0 if said["ok"] else 1
    if not said["ok"]:
        print(f"error: {said['error']}", file=sys.stderr)
        return 1
    print(f"{said['routine']['name']}: reads, {said['cost']}")
    for n, wave in enumerate(said["waves"], start=1):
        print(f"  {n}. {' + '.join(wave)}" + ("   (side by side)" if len(wave) > 1 else ""))
    for line in said["touches"]:
        print(f"  - {line}")
    return 0


def _save(args, state, store) -> int:
    saved, said = routines.save(store, args.as_actor, args.name,
                                Path(args.file).expanduser().read_text())
    print(f"saved {saved.name}")
    for line in said:
        print(f"  {line}")
    return 0


def _set_inputs(args, state, store) -> int:
    changed = routines.set_inputs(store, args.as_actor, args.name, _inputs(args.pairs))
    print(f"{changed.name}: " + ", ".join(f"{k}={v}" for k, v in changed.inputs.items()))
    return 0


def _starts(args, state, store) -> int:
    work = state / "work"
    try:
        if args.at or args.on or args.rm:
            if not args.name:
                raise starters.StarterError("name the routine")
            if args.rm:
                by, _, ident = args.rm.partition(":")
                starters.remove(store, args.as_actor, args.name, by, ident, work)
                said = {"removed": ident}
            elif args.at:
                made = starters.add_schedule(store, args.as_actor, args.name, args.at, work,
                                             _inputs(args.input))
                said = {"made": made.get("id"), "by": "samay",
                        "sentence": made.get("sentence", "")}
            else:
                made = starters.add_watch(store, args.as_actor, args.name, args.on,
                                          args.when, work, _inputs(args.input))
                said = {"made": made.get("id"), "by": "prahari",
                        "sentence": made.get("sentence", "")}
            if args.json_out:
                print(json.dumps(said))
            else:
                print(f"removed {said['removed']}" if "removed" in said
                      else f"made {said['by']} {said['made']}: {said['sentence']}")
            return 0
    except starters.StarterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    found = starters.starts_all(store, args.as_actor, work)
    if args.name:
        routines.find(store, args.as_actor, args.name)
        found = {args.name: found.get(args.name, [])}
    if args.json_out:
        print(json.dumps(found))
        return 0
    for name, items in found.items():
        print(f"{name}:")
        for item in items or []:
            print(f"  {item['by']}:{item['id']}  {item['state']}  {item['words']}")
        if not items:
            print("  only when asked (a chat, the page, vidhi run)")
    return 0


def _start(args, state, store) -> int:
    runner = make_runner(state, store)
    run = runner.start(args.as_actor, args.name, _inputs(args.input), started_by=args.by,
                       found=args.found)
    if args.command == "start":
        if args.json_out:
            print(json.dumps(describe(store, run)))
        else:
            print(f"queued run {run.id} of {run.routine}"
                  + ("" if serving(state) else " (vidhi serve is not running: it waits "
                                                "for it)"))
        return 0
    if serving(state) is None:
        run = runner.go(run.id) or run
    elif not args.no_wait:
        run = _follow(store, run.id, quiet=args.json_out)
    if args.json_out:
        print(json.dumps(describe(store, run)))
        return 0
    _print_run(store, run)
    return 0 if run.state in ("done", "waiting", "queued", "running") else 1


def _follow(store: Store, run_id: str, *, quiet: bool):
    seen: dict[str, str] = {}
    end = time.monotonic() + FOLLOW_LIMIT
    while time.monotonic() < end:
        run = store.run(run_id)
        for row in store.steps(run_id):
            if seen.get(row.step_id) != row.state and not quiet:
                if row.state not in ("pending",):
                    print(f"  {row.step_id}: {row.state}", flush=True)
            seen[row.step_id] = row.state
        if run is None or run.state in ("done", "failed", "stopped", "waiting"):
            return run
        time.sleep(1.0)
    return store.run(run_id)


def _print_run(store: Store, run) -> None:
    full = describe(store, run)
    print(f"run {run.id} of {run.routine}: {run.state}"
          + (f" -- {run.detail}" if run.detail else ""))
    for step in full["steps"]:
        log = step["detail"] if "\n" in step["detail"] else ""   # a repeat's passes
        said = ": ".join(x for x in (step["why"], "" if log else step["detail"]) if x)
        print(f"  {step['state']:<8} {step['title']}" + (f"  ({said})" if said else ""))
        for line in log.splitlines():
            print(f"           {line}")
        if step["result"] and step["state"] in ("done", "failed"):
            shown = " ".join(step["result"].split())
            print(f"           {shown[:200]}{'…' if len(shown) > 200 else ''}")
    for question in full["questions"]:
        if not question["answer"]:
            print(f"  asks you: {question['text']}")
            print(f"    {_how_to_answer(question)}")


def _runs(args, state, store) -> int:
    name = None
    owner = None if args.all else args.as_actor
    if args.name:
        name = routines.find(store, args.as_actor, args.name).name
    found = store.runs(owner=owner, routine=name, limit=args.limit)
    if args.json_out:
        print(json.dumps([describe(store, r) for r in found]))
        return 0
    if not found:
        print("no runs yet")
    for run in found:
        steps = store.steps(run.id)
        done = sum(1 for s in steps if s.state == "done")
        print(f"{run.id}  {run.created_at}  {run.routine:<18} {run.state:<8} "
              f"{done}/{len(steps)} steps  by {run.started_by}"
              + (f"  -- {run.detail}" if run.detail else ""))
    return 0


def _steps(args, state, store) -> int:
    run = store.run(args.run)
    if run is None:
        raise RunError(f"no run {args.run}")
    if args.json_out:
        print(json.dumps(describe(store, run)))
        return 0
    _print_run(store, run)
    return 0


def _questions(args, state, store) -> int:
    found = store.questions(None if args.all else args.as_actor)
    if args.json_out:
        print(json.dumps([q.as_dict() for q in found]))
        return 0
    if not found:
        print("no questions waiting")
    for question in found:
        run = store.run(question.run_id)
        print(f"{question.code}  {run.routine if run else '?'}: {question.text}")
        print(f"    by {question.until}: {_how_to_answer(question.as_dict())}")
    return 0


def _how_to_answer(question: dict) -> str:
    code = question["code"]
    if question.get("kind") == "choice":
        return f"vidhi answer {code} " + " | ".join(
            f"{n} ({c})" for n, c in enumerate(question.get("choices") or [], 1))
    if question.get("kind") == "words":
        from vidhi.runner import expected
        typed, between = expected(question.get("expects") or "")
        return (f"vidhi answer {code} {rt.typed_example(typed, between)}"
                + (f"   ({rt.typed_wants(typed, between)})" if typed != "words" else ""))
    return f"vidhi answer {code} yes   (or no)"


def _answer(args, state, store) -> int:
    runner = make_runner(state, store)
    question, run = runner.answer(args.code, " ".join(args.word), via=args.via,
                                  owner=None if args.any else args.as_actor)
    if run is not None and serving(state) is None and run.state == "queued":
        run = runner.go(run.id) or run
    if args.json_out:
        print(json.dumps({"question": question.as_dict(),
                          "run": describe(store, run) if run else None}))
        return 0
    print(f"{question.code}: {question.answer}")
    if run is not None:
        _print_run(store, run)
    return 0


def _stop(args, state, store) -> int:
    run = make_runner(state, store).stop(args.run, owner=args.as_actor)
    if args.json_out:
        print(json.dumps(describe(store, run)))
        return 0
    print(f"stopped run {run.id} of {run.routine}")
    return 0


def _routine_state(args, state, store) -> int:
    verb = {"rm": "remove"}.get(args.command, args.command)
    changed = getattr(routines, verb)(store, args.as_actor, args.name)
    print(f"{ {'pause': 'paused', 'resume': 'resumed', 'remove': 'removed'}[verb]} "
          f"{changed.name}")
    return 0


COMMANDS = {"status": _status, "templates": _templates, "install": _install,
            "list": _list, "show": _show, "check": _check, "save": _save,
            "inputs": _set_inputs, "starts": _starts, "run": _start, "start": _start, "runs": _runs,
            "steps": _steps, "questions": _questions, "answer": _answer, "stop": _stop,
            "pause": _routine_state, "resume": _routine_state, "rm": _routine_state}


# -- long-running --------------------------------------------------------------------


def _serve(args, state) -> int:
    from vidhi.http import Api, VidhiServer, serve_token

    held = hold(state)
    if held is None:
        print(f"error: vidhi is already running for {state}", file=sys.stderr)
        return 2
    store = Store.at(state)
    runner = make_runner(state, store, page="")
    shop = market.Market(Path(args.market).expanduser()) if args.market else None
    try:
        server = VidhiServer(Api(store, runner, state), serve_token(state), host=args.host,
                             port=args.port, public_url=args.public_url, shop=shop)
    except (OSError, ValueError) as exc:
        print(f"error: cannot serve on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2
    runner.page = server.url
    clock = Clock(runner, take_backs=lambda: market.check(state, store, runner))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    server.start()
    recovered = runner.recover()
    (state / "serve.json").write_text(json.dumps(
        {"pid": os.getpid(), "url": server.url,
         "market": (server.url + "market/") if shop else None,
         "dvara": runner.roads.dvara.url if runner.roads.dvara else None,
         "owner_as": runner.roads.dvara.actor if runner.roads.dvara else ""}))
    print(f"vidhi serving routines from {state}")
    print(f"page: {server.page_url}", flush=True)
    if shop:
        print(f"market: {server.url}market/  (kept in {shop.root})", flush=True)
    if recovered:
        print(f"picked up again: {', '.join(recovered)}", flush=True)
    worker = threading.Thread(target=clock.loop, name="vidhi-clock", daemon=True)
    worker.start()
    try:
        stop.wait()
    finally:
        clock.stop()
        server.stop()
        (state / "serve.json").unlink(missing_ok=True)
        held.close()
    print("stopped")
    return 0


def _mcp(args, state) -> int:
    from vidhi import mcp

    store = Store.at(state)
    runner = make_runner(state, store)
    mcp.serve(mcp.Tools(store, runner, state, args.person, agent=args.agent,
                        road=args.runner))
    return 0


def _key_line(raw: str) -> str:
    path = Path(raw).expanduser()
    return path.read_text().strip() if path.is_file() else raw


def _market(args, state) -> int:
    verb = args.verb
    if verb == "publish":
        said = market.publish(args.base, Path(args.file).expanduser().read_text(),
                              args.publisher, args.note)
        print(f"sent: {said['name']} version {said['version']}, id {said['id']} -- "
              f"{said['status']}")
    elif verb == "queue":
        waiting = market.queue(args.base)
        if not waiting:
            print("nothing waits for review")
        for item in waiting:
            print(f"{item['id']}  {item['name']} v{item['version']}  by "
                  f"{item['publisher']}  {item['submitted_at']}")
    elif verb == "show":
        item = market.show(args.base, args.id)
        print(f"{item['name']} v{item['version']} by {item['publisher']}"
              + (f": {item['note']}" if item.get("note") else ""))
        print("review notes:")
        for line in item["notes"]:
            print(f"  - {line}")
        print("\n" + item["toml"])
    elif verb == "approve":
        said = market.approve(args.base, args.id, Path(args.key), args.reviewer)
        print(f"{said['name']} v{said['version']}: {said['status']}, signed by "
              f"{said['reviewer']}")
    elif verb == "reject":
        said = market.reject(args.base, args.id, args.why, Path(args.key), args.reviewer)
        print(f"{said['name']} v{said['version']}: {said['status']} ({said['why']})")
    elif verb == "list":
        listed = [i for i in market.index(args.base)
                  if args.kind is None or i.get("kind", "routine") == args.kind]
        if args.json_out:
            print(json.dumps(listed))
            return 0
        if not listed:
            print("nothing listed yet")
        for item in listed:
            kind = "" if item.get("kind", "routine") == "routine" else " (indriya)"
            print(f"{item['name']} v{item['version']}{kind}  by {item['publisher']}, "
                  f"reviewed by {item['reviewer']}: {item['title']} -- {item.get('cost')}")
    elif verb == "revoke":
        said = market.revoke(args.base, args.name, args.version, args.why, Path(args.key),
                             args.reviewer)
        print(f"{said['name']} v{said['version']}: review {said['status']} by "
              f"{said['reviewer']} ({said['why']}); it is no longer listed, and each Vidhi "
              "that trusts you pauses it when it next checks")
    elif verb == "check":
        store = Store.at(state)
        done, ignored = market.check(state, store, make_runner(state, store), args.base)
        for line in done:
            print(line)
        for line in ignored:
            print(f"set aside: {line}")
        if not done:
            print("no new reviews taken back" + ("" if market.markets_used(state) or args.base
                                                 else " (no marketplace used yet)"))
    elif verb == "revoked":
        kept = Store.at(state).revoked()
        if args.json_out:
            print(json.dumps(kept))
            return 0
        if not kept:
            print("no reviews taken back (vidhi market check reads them)")
        for one in kept:
            print(f"{one['name']} v{one['version']}: taken back by {one['reviewer']} -- "
                  f"{one['why'] or 'no reason given'}  ({one['sha256'][:12]})")
    elif verb == "get":
        path, signer = market.get(args.base, args.name, state)
        text = path.read_text()
        kind = market.kind_of(text)
        if args.json_out:
            print(json.dumps({"name": path.stem, "kind": kind, "signed_by": signer,
                              "path": str(path), "toml": text}))
            return 0
        print(f"fetched {path.stem}, signed by {signer} (whom you trust); install it with: "
              + (f"prahari indriya install {path.stem} --from-market" if kind == "indriya"
                 else f"vidhi install {path.stem}"))
    elif verb == "reviewers":
        found = market.reviewers(args.base)
        if not found:
            print("this marketplace lists no reviewers")
        for one in found:
            print(f"{one['name']}: {one['key']}")
        if found:
            print("compare each key with what that reviewer published elsewhere before:\n"
                  "  vidhi market trust NAME 'KEY'")
    elif verb == "trust":
        path = market.trust(state, args.name, _key_line(args.key))
        print(f"trusting {args.name}'s signatures ({path})")
    elif verb == "reviewer":
        root = Path(args.dir).expanduser()
        market.Market(root)
        market.trust(root, args.name, _key_line(args.key))
        print(f"{args.name} may approve routines in {root}")
    elif verb == "serve":
        return _market_serve(args)
    return 0


def _market_serve(args) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse

    from vidhi.http import MAX_BODY, market_answer

    from vidhi.keeps import market_dir
    shop = market.Market(Path(args.dir).expanduser() if args.dir else market_dir())

    class Handler(BaseHTTPRequestHandler):
        server_version = "vidhi-market"

        def log_message(self, *a):
            pass

        def _go(self, method):
            url = urlparse(self.path)
            body = {}
            if method == "POST":
                size = int(self.headers.get("Content-Length") or 0)
                if size > MAX_BODY:
                    return self._out(413, {"detail": "request too large"})
                try:
                    body = json.loads(self.rfile.read(size) or b"{}")
                except json.JSONDecodeError:
                    return self._out(400, {"detail": "the body is not JSON"})
                if not isinstance(body, dict):
                    return self._out(400, {"detail": "the body is a JSON object"})
            if url.path == "/":
                self.send_response(302)
                self.send_header("Location", "/market/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if not (url.path == "/market" or url.path.startswith("/market/")):
                return self._out(404, {"detail": "not found"})
            self._send(*market_answer(self, shop, method, url.path, body))

        def _out(self, status, data):
            self._send(status, json.dumps(data).encode(), "application/json")

        def _send(self, status, raw, kind):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"vidhi market on http://{args.host}:{args.port}/market/  (kept in {shop.root})",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
