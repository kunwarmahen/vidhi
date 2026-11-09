"""The tools an agent uses to run a person's routines.

    vidhi mcp --for mahen [--agent NAME] [--runner direct|dvara]

An MCP server on stdin/stdout -- newline-delimited JSON-RPC, by hand,
like Prahari's and Samay's -- with seven tools:

    list_routines       read    this person's routines: what each does, in
                                words, its inputs, its last run
    list_templates      read    routines ready to install, with their blanks
    routine_runs        read    how the last runs went, step by step, and any
                                question waiting for the person
    run_routine         write   start one now, maybe with other inputs for once
    install_template    write   install a template, its blanks filled
    set_routine_inputs  write   change what a routine's blanks are filled with
    stop_run            write   stop a run that is going or waiting

THE PERSON DRAWS THE GRAPH; THE AGENT ONLY PICKS AND FILLS. No tool here
writes a step. Writing a graph is where a small local model goes wrong;
picking "morning-brief" and filling ``latitude = 51.5`` is where it goes
right. A routine is drawn on Vidhi's page, or written as TOML, by a
person.

NO TOOL ANSWERS A ROUTINE'S QUESTION. A ``person`` step asks the person,
in their chat, with its buttons (or a box for words). If the agent could answer it, the
question would be asking the agent. So there is no such tool.

THE FOUR WRITES ARE ASKED ABOUT. The reads say ``readOnlyHint: true``
and the writes do not, so a harness that honours the hint (Yantra does)
puts each one in front of the person with a card in words: what the
routine touches and what a run costs.

ONE PERSON PER SERVER. ``--for`` is the harness's; the model has no
argument with which to name anyone else's routines.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from vidhi import __version__, catalog, market, routines
from vidhi import routine as rt
from vidhi.runner import RunError, Runner, describe, installed_card
from vidhi.status import serving
from vidhi.store import Store

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
READ = {"readOnlyHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False}

_NAME = {"type": "string", "description": "The routine's name (morning-brief), as "
                                          "list_routines gives it."}
_INPUTS = {"type": "object", "description": (
    "Values for the routine's inputs, by their names, as list_routines or "
    "list_templates gives them: {\"latitude\": 51.5, \"unit\": \"celsius\"}. Fill only "
    "what the person said; leave the rest to its default.")}

TOOLS = [
    {"name": "list_routines", "annotations": READ,
     "description": ("This person's routines (steps they set up once: a morning brief, "
                     "a price check that asks before acting): what each does in words, "
                     "its inputs, and how its last run went. Read this before running one."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_templates", "annotations": READ,
     "description": ("Routines ready to install, each with the blanks it needs filled "
                     "(inputs) and what it touches. Offer one when the person asks for "
                     "something a template already does."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "routine_runs", "annotations": READ,
     "description": ("How a routine's recent runs went, step by step, and any question a "
                     "run is waiting on the person to answer."),
     "inputSchema": {"type": "object", "properties": {
         "name": {**_NAME, "description": "Only this routine's runs (leave out for all)."},
         "limit": {"type": "integer", "description": "How many, newest first (5)."}}}},
    {"name": "run_routine", "annotations": WRITE,
     "description": ("Start one of this person's routines now. It runs by itself, step by "
                     "step; a step that asks the person puts its question in their chat. "
                     "inputs changes its blanks for this run only."),
     "inputSchema": {"type": "object", "required": ["name"], "properties": {
         "name": _NAME, "inputs": _INPUTS}}},
    {"name": "install_template", "annotations": WRITE,
     "description": ("Install a template (list_templates) for this person, its blanks "
                     "filled from what they said. Ask for any blank with no default that "
                     "they haven't given; never guess an account or a place."),
     "inputSchema": {"type": "object", "required": ["template"], "properties": {
         "template": {"type": "string", "description": "The template's name."},
         "inputs": _INPUTS}}},
    {"name": "set_routine_inputs", "annotations": WRITE,
     "description": "Change what one of this person's routines fills its blanks with.",
     "inputSchema": {"type": "object", "required": ["name", "inputs"], "properties": {
         "name": _NAME, "inputs": _INPUTS}}},
    {"name": "stop_run", "annotations": WRITE,
     "description": "Stop one of this person's runs that is going or waiting.",
     "inputSchema": {"type": "object", "required": ["run"], "properties": {
         "run": {"type": "string", "description": "The run's id (routine_runs)."}}}},
]


class ToolFailed(Exception):
    pass


class Tools:
    def __init__(self, store: Store, runner: Runner, state: Path, person: str, *,
                 agent: str = "", road: str = "direct") -> None:
        self.store = store
        self.runner = runner
        self.state = Path(state)
        self.person = person
        self.agent = agent
        self.road = road

    def call(self, name: str, args: dict) -> str:
        if not isinstance(args, dict):
            raise ToolFailed("arguments is an object")
        try:
            method = getattr(self, "_" + name)
        except AttributeError:
            raise ToolFailed(f"no tool {name}") from None
        try:
            return method(args)
        except (rt.RoutineError, RunError, market.MarketError) as exc:
            raise ToolFailed(str(exc)) from None

    def _list_routines(self, args: dict) -> str:
        mine = self.store.routines(self.person)
        if not mine:
            return ("No routines yet. list_templates shows ready ones; a new kind is drawn "
                    "on Vidhi's page by the person.")
        out = []
        for n, installed in enumerate(mine, start=1):
            card = installed_card(installed)
            last = self.store.runs(owner=self.person, routine=installed.name, limit=1)
            out.append({"n": n, "name": installed.name, "title": card.get("title"),
                        "about": card.get("about"), "state": installed.state,
                        "inputs": installed.inputs, "cost": card.get("cost"),
                        "touches": card.get("touches"),
                        "last_run": ({"state": last[0].state, "at": last[0].created_at,
                                      "detail": last[0].detail} if last else None)})
        return json.dumps(out, indent=1)

    def _list_templates(self, args: dict) -> str:
        found, _ = catalog.templates(self.state)
        mine = {r.name for r in self.store.routines(self.person)}
        return json.dumps([{**t.card(), "installed": t.routine.name in mine}
                           for t in found], indent=1)

    def _routine_runs(self, args: dict) -> str:
        name = str(args.get("name") or "").strip() or None
        if name:
            name = routines.find(self.store, self.person, name).name
        runs = self.store.runs(owner=self.person, routine=name,
                               limit=max(1, min(int(args.get("limit") or 5), 20)))
        if not runs:
            return "No runs yet."
        out = []
        for run in runs:
            full = describe(self.store, run)
            out.append({"run": run.id, "routine": run.routine, "state": run.state,
                        "started_by": run.started_by, "at": run.created_at,
                        "detail": run.detail,
                        "steps": [{"step": s["title"], "state": s["state"],
                                   "why": s["why"] or s["detail"],
                                   "gave": (s["result"] or "")[:300]}
                                  for s in full["steps"]],
                        "waiting_on_person": [q["text"] for q in full["questions"]
                                              if not q["answer"]]})
        return json.dumps(out, indent=1)

    def _run_routine(self, args: dict) -> str:
        installed = routines.find(self.store, self.person, str(args.get("name") or ""))
        run = self.runner.start(self.person, installed.name, args.get("inputs") or {},
                                started_by="agent")
        said = (f"Started {installed.name} (run {run.id}). It runs by itself; what it "
                "finds comes to the person on their channels, and any question it has, "
                "with buttons. routine_runs shows how it went.")
        if serving(self.state) is None:
            said += (" Note: Vidhi is not running on this machine (vidhi serve), so the "
                     "run waits until it is -- tell the person.")
        return said

    def _install_template(self, args: dict) -> str:
        found = catalog.template(self.state, str(args.get("template") or ""))
        signed_by, source = "", "catalog" if found.source == "vidhi" else found.source
        if found.source == "market":
            signed_by = market.check_installable(self.state, Path(found.path), found.text)
        made = routines.install(self.store, self.person, found.text,
                                inputs=args.get("inputs") or {}, runner=self.road,
                                agent=self.agent, source=source, signed_by=signed_by)
        card = installed_card(made)
        return (f"Installed {made.name}: {card.get('title')}. Inputs: "
                f"{json.dumps(made.inputs)}. It {'; '.join(card.get('touches') or [])}. "
                f"Cost: {card.get('cost')}. Start it with run_routine, or ask for it on a "
                "schedule (Samay) or when something happens (Prahari).")

    def _set_routine_inputs(self, args: dict) -> str:
        changed = routines.set_inputs(self.store, self.person, str(args.get("name") or ""),
                                      args.get("inputs") or {})
        return f"{changed.name} now runs with {json.dumps(changed.inputs)}."

    def _stop_run(self, args: dict) -> str:
        run = self.runner.stop(str(args.get("run") or "").strip(), owner=self.person)
        return f"Stopped run {run.id} of {run.routine}."


def answer(tools: Tools, message: dict) -> dict | None:
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return _ok(ident, {
            "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "vidhi", "version": __version__},
            "instructions": ("This person's routines: run one they ask for, install a "
                             "template with its blanks filled. Never write steps.")})
    if method == "ping":
        return _ok(ident, {})
    if method == "tools/list":
        return _ok(ident, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            text = tools.call(str(params.get("name")), params.get("arguments") or {})
            return _ok(ident, {"content": [{"type": "text", "text": text}],
                               "isError": False})
        except ToolFailed as exc:
            return _ok(ident, {"content": [{"type": "text", "text": str(exc)}],
                               "isError": True})
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": f"no method {method!r}"}}


def _ok(ident: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(tools: Tools, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "not JSON"}}
        else:
            reply = answer(tools, message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
