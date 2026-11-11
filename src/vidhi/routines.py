"""Installing, mending, pausing and removing routines -- one place for all.

The CLI, the page, the agent's tools and a chat through Dvara all come
here, so the rules hold however a routine arrives:

* A routine is read and checked (routine.py) before it is kept; a
  routine with a loop, a step using one that doesn't exist, or an input
  nobody filled is refused with why.
* INSTALLING IS FILLING THE BLANKS. A template's inputs (a city, a
  price line, which account) are filled when it is installed, and kept
  beside it; a run may change them for once.
* ONE NAME, ONE ROUTINE, PER PERSON. Installing a name a person already
  has is refused unless it says ``replace``: a template installed twice
  by a chat that misheard would otherwise quietly overwrite the first.
* A MEND KEEPS ITS NAME. The canvas saves the routine it opened; a
  changed ``name`` would be a new routine, so it is refused there.
* A CAP PER PERSON: ``MAX_ROUTINES``.
* A REVIEW TAKEN BACK HOLDS EVERYWHERE. A text whose reviewer took their
  review back (market.py's take-backs, kept by its sha256) is refused
  here however it arrives -- a file, a template, the page, a chat -- and
  a paused one that is that text can't be resumed. A mended copy is
  another text: the person's own, unreviewed, and theirs to run.
"""

from __future__ import annotations

import hashlib
from typing import Any

from vidhi import routine as rt
from vidhi.store import Installed, Store

MAX_ROUTINES = 50
RUNNERS = ("direct", "dvara")


def install(store: Store, owner: str, text: str, *, inputs: dict | None = None,
            runner: str = "direct", agent: str = "", source: str = "local",
            signed_by: str = "", replace: bool = False) -> Installed:
    routine = rt.parse(text)
    _not_taken_back(store, text)
    if runner not in RUNNERS:
        raise rt.RoutineError(f"runner is {' or '.join(RUNNERS)}")
    existing = store.routine(owner, routine.name)
    if existing is not None and not replace:
        raise rt.RoutineError(f"{owner} already has a routine called {routine.name}; "
                              "replace it (--replace), or rename the new one")
    if existing is None and len(store.routines(owner)) >= MAX_ROUTINES:
        raise rt.RoutineError(f"{owner} has {MAX_ROUTINES} routines, the most; remove one")
    filled = rt.check_inputs(routine, inputs or {})
    return store.install(Installed(
        owner=owner, name=routine.name, toml=text, inputs=filled, runner=runner,
        agent=agent, source=source, signed_by=signed_by,
        installed_at=existing.installed_at if existing else ""))


def save(store: Store, owner: str, name: str, text: str) -> tuple[Installed, list[str]]:
    """A mended routine (the canvas, or ``vidhi edit``): the same name, its
    inputs kept where they still fit. Returns it, and what changed about
    the inputs, in words."""
    current = find(store, owner, name)
    routine = rt.parse(text)
    if routine.name != current.name:
        raise rt.RoutineError(f"this routine is {current.name}; a new name ({routine.name})"
                              " is a new routine: install it as one")
    said: list[str] = []
    known = {i.name for i in routine.inputs}
    kept = {k: v for k, v in current.inputs.items() if k in known}
    dropped = sorted(set(current.inputs) - known)
    if dropped:
        said.append("inputs no longer used: " + ", ".join(dropped))
    try:
        kept = rt.check_inputs(routine, kept)
    except rt.RoutineError as exc:
        said.append(f"before it can run: {exc}")
        kept = {**rt.defaults(routine), **kept}
    store.set_routine(owner, current.name, toml=text, inputs=kept, source="local",
                      signed_by="")
    if current.signed_by:
        said.append(f"it was signed by {current.signed_by}; mended here, it no longer is")
    return find(store, owner, current.name), said


def set_inputs(store: Store, owner: str, name: str, inputs: dict[str, Any]) -> Installed:
    current = find(store, owner, name)
    routine = rt.parse(current.toml)
    filled = rt.check_inputs(routine, {**current.inputs, **inputs})
    store.set_routine(owner, current.name, inputs=filled)
    return find(store, owner, current.name)


def set_road(store: Store, owner: str, name: str, *, runner: str | None = None,
             agent: str | None = None) -> Installed:
    current = find(store, owner, name)
    values: dict[str, Any] = {}
    if runner is not None:
        if runner not in RUNNERS:
            raise rt.RoutineError(f"runner is {' or '.join(RUNNERS)}")
        values["runner"] = runner
    if agent is not None:
        values["agent"] = agent
    if values:
        store.set_routine(owner, current.name, **values)
    return find(store, owner, current.name)


def pause(store: Store, owner: str, name: str) -> Installed:
    current = find(store, owner, name)
    store.set_routine(owner, current.name, state="paused")
    return find(store, owner, current.name)


def resume(store: Store, owner: str, name: str) -> Installed:
    current = find(store, owner, name)
    _not_taken_back(store, current.toml)
    store.set_routine(owner, current.name, state="active")
    return find(store, owner, current.name)


def remove(store: Store, owner: str, name: str) -> Installed:
    current = find(store, owner, name)
    store.uninstall(owner, current.name)
    return current


def taken_back(store: Store, text: str) -> dict | None:
    """The take-back that names this exact text, if a trusted reviewer made one."""
    return store.revoked_for(hashlib.sha256(text.encode()).hexdigest())


def _not_taken_back(store: Store, text: str) -> None:
    found = taken_back(store, text)
    if found:
        raise rt.RoutineError(
            f"{found['reviewer']} took back their review of {found['name']} version "
            f"{found['version']}: {found['why'] or 'no reason given'}. That exact text is "
            "not installed or resumed here; mend it (vidhi edit) to make it your own, or "
            "install a newer reviewed version")


def find(store: Store, owner: str, wanted: str) -> Installed:
    """By name, or by its number on the person's list (1 is the first)."""
    wanted = str(wanted or "").strip()
    mine = store.routines(owner)
    if wanted.isdigit() and 0 < int(wanted) <= len(mine):
        return mine[int(wanted) - 1]
    for installed in mine:
        if installed.name == wanted:
            return installed
    raise rt.RoutineError(f"{owner} has no routine {wanted!r}"
                          + (f" (they have: {', '.join(r.name for r in mine)})" if mine
                             else " (none installed: vidhi templates, then vidhi install)"))
