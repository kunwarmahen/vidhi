"""What starts a routine: Samay's schedules and Prahari's watches.

A routine runs when something starts it -- a time (Samay), a watch that
fired (Prahari), a chat, a button. Vidhi keeps none of those itself: a
schedule is Samay's and a watch is Prahari's, kept and run by them. This
module only ASKS THEM, with their own commands, the way a step does:

    samay list --json      the schedules whose runner is vidhi and whose
                           prompt is this routine's name
    prahari list --json    the watches whose routine is this one
    samay add NAME --runner vidhi --when WHEN [--input K=V]
    prahari add WORDS --sense READING --when TEST --routine NAME
    samay rm ID / prahari rm ID

SO A STARTER MADE HERE IS AN ORDINARY ONE. It shows on Samay's or
Prahari's page, is changed or paused there like any other, and starts
the routine the way theirs always have (``vidhi start --by samay:ID``).
Nothing here can make a schedule or a watch the person couldn't make on
those pages.

ONE PERSON, ONE NAME. A starter filed under Dvara's name for the owner
starts the owner's ``local`` routines (routines.person), so the list
says what really starts each one, however it was made.

A WATCH ON A READING NEEDS NO MODEL. "When outside-temp drops below 35"
is a watch that senses the reading Prahari already keeps: no call of its
own, no agent, decided on every new reading.
"""

from __future__ import annotations

import json
from pathlib import Path

from vidhi import routine as rt
from vidhi import routines
from vidhi.roads import RunnerMissing, _run, find
from vidhi.store import Store

LIMIT = 30


class StarterError(ValueError):
    """A schedule or a watch that couldn't be made or removed, in words."""


def _command(program: str) -> list[str]:
    try:
        return find(program, f"VIDHI_{program.upper()}")
    except RunnerMissing as exc:
        raise StarterError(str(exc)) from None


def _ask(argv: list[str], work: Path) -> tuple[object, str]:
    """(the JSON it printed last, or None; what it said when it failed)."""
    work.mkdir(parents=True, exist_ok=True)
    out, err, timed_out = _run(argv, cwd=work, limit=LIMIT)
    if timed_out:
        return None, f"{Path(argv[0]).name} took too long to answer"
    for line in reversed(out.strip().splitlines()):
        try:
            return json.loads(line), ""
        except json.JSONDecodeError:
            continue
    said = " ".join((err or out).split()).removeprefix("error: ")
    return None, said or f"{Path(argv[0]).name} said nothing"


def starts_all(store: Store, owner: str, work: Path) -> dict[str, list[dict]]:
    """Every schedule and watch that starts one of this person's
    routines, by routine: one ask of Samay and one of Prahari for all of
    them. A program that isn't here gives none."""
    owner = routines.person(store, owner)
    found: dict[str, list[dict]] = {}
    for program in ("samay", "prahari"):
        try:
            data, _said = _ask([*_command(program), "list", "--json"], work)
        except StarterError:
            continue
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            if routines.person(store, str(item.get("owner") or "")) != owner:
                continue
            if program == "samay":
                name = str(item.get("prompt") or "").strip()
                if item.get("runner") != "vidhi" or not name:
                    continue
                words = f"Samay: {item.get('when_text') or ''}".strip()
                inputs = item.get("inputs") or {}
            else:
                name = str(item.get("routine") or "").strip()
                if not name:
                    continue
                words = f"Prahari: {item.get('name') or ''}".strip()
                inputs = item.get("routine_inputs") or {}
            found.setdefault(name, []).append({
                "by": program, "id": str(item.get("id") or ""),
                "state": str(item.get("state") or ""), "words": words,
                "sentence": str(item.get("sentence") or ""), "inputs": inputs})
    return found


def starts(store: Store, owner: str, name: str, work: Path) -> list[dict]:
    """The schedules and watches that start this one routine."""
    return starts_all(store, owner, work).get(name, [])


def _as(store: Store, owner: str) -> list[str]:
    """``--as`` for a starter: Dvara's name for the owner when there is one,
    so the watch can sense the owner's readings and the schedule is
    theirs; nobody for the computer with no Dvara."""
    owner = routines.person(store, owner)
    if owner == routines.LOCAL:
        alias = routines.owner_alias(store)
        return [f"--as={alias}"] if alias else []
    return [f"--as={owner}"]


def add_schedule(store: Store, owner: str, name: str, when: str, work: Path,
                 inputs: dict | None = None) -> dict:
    when = str(when or "").strip()
    if not when:
        raise StarterError("when: say a time, like 'at 20:00' or 'at 07:30 on mon-fri'")
    routines.find(store, routines.person(store, owner), name)
    argv = [*_command("samay"), "add", name, "--runner", "vidhi", "--when", when,
            *_as(store, owner), "--json"]
    for key, value in (inputs or {}).items():
        argv.append(f"--input={key}={value}")
    data, said = _ask(argv, work)
    if not isinstance(data, dict) or not data.get("id"):
        raise StarterError(f"Samay didn't make it: {said}")
    return data


def add_watch(store: Store, owner: str, name: str, reading: str, test: str,
              work: Path, inputs: dict | None = None, words: str = "") -> dict:
    reading, test = str(reading or "").strip(), str(test or "").strip()
    if not reading:
        raise StarterError("reading: which of your readings to watch")
    if not test:
        raise StarterError("when: a test on the reading, like 'below 35'")
    installed = routines.find(store, routines.person(store, owner), name)
    try:
        named = rt.parse(installed.toml).title or installed.name
    except rt.RoutineError:
        named = installed.name
    title = words.strip() or f"{named}: {reading} {test}"
    argv = [*_command("prahari"), "add", title, "--sense", reading, "--when", test,
            "--routine", name, "--asked", f"start the routine {name} when {reading} is {test}",
            *_as(store, owner), "--json"]
    for key, value in (inputs or {}).items():
        argv.append(f"--input={key}={value}")
    data, said = _ask(argv, work)
    if not isinstance(data, dict) or not data.get("id"):
        raise StarterError(f"Prahari didn't make it: {said}")
    return data


def remove(store: Store, owner: str, name: str, by: str, ident: str, work: Path) -> None:
    """Remove one of this routine's own starters (only one that is)."""
    if by not in ("samay", "prahari"):
        raise StarterError("by is samay or prahari")
    if not any(s["by"] == by and s["id"] == ident for s in starts(store, owner, name, work)):
        raise StarterError(f"no {by} {ident} starts {name}")
    data, said = _ask([*_command(by), "rm", ident, "--json"], work)
    if not isinstance(data, dict) or data.get("removed") != ident:
        raise StarterError(f"{by} didn't remove it: {said}")


_PAGES: dict[str, str] = {}


def pages(work: Path) -> dict[str, str]:
    """Samay's and Prahari's page addresses (``status --json``), asked once."""
    if not _PAGES:
        for program in ("samay", "prahari"):
            try:
                data, _said = _ask([*_command(program), "status", "--json"], work)
            except StarterError:
                data = None
            url = data.get("url") if isinstance(data, dict) else None
            _PAGES[program] = str(url or "")
    return dict(_PAGES)

