"""A routine: steps a person drew once, written down as TOML.

A routine is a small graph. Each step is ONE thing that already exists in
this family of programs, so Vidhi grows no engine of its own:

    call     one tool, no model         (``yantra --call``, as a Prahari look)
    ask      a question to the model    (``yantra --prompt``, as a Samay run)
    read     a reading Prahari keeps    (``prahari indriya get``)
    check    a test on a value          (below, above, contains, ... as a watch's)
    person   a question put to the person (in their chat; the run waits for it):
             yes or no, one of up to three choices, or a few typed words
    wait     a pause                    ("30m", or until "07:30")
    notify   a message to the person    (Dvara's channels)
    repeat   some of the steps again    (at most N times, a wait between)

and results flow from one step into later ones: ``{{weather}}`` in a step
is what the step ``weather`` gave. ``{{inputs.city}}`` is an input the
person filled when they installed it, and ``{{run.date}}``,
``{{run.time}}`` and ``{{run.person}}`` are the run's own.

WHAT CAN RUN SIDE BY SIDE IS WORKED OUT, NOT WRITTEN. A step waits for
the steps it uses (``{{weather}}``), the ones it names in ``after``, and
the one its ``only_if`` names. Everything else runs at the same time:
the morning brief's weather, calendar and mail are three calls at once,
and the step that writes the brief starts when all three are in.

NO OPEN-ENDED LOOPS, AND NO CODE. A step that waits on itself, or on a
step that waits on it, is refused when the routine is read. There is no
step that runs a program or a script. A routine someone else wrote can
then be read and understood before it is installed: what it calls, what
it asks the model, what it tells you. That is what makes sharing one
safe to review.

A REPEAT SAYS ITS LIMIT ON ITS FACE. "Until the room is warm" is a
``repeat`` step: the steps it names (its group) are done again, ``every``
apart (5 minutes at the least), until its ``until`` step -- a check, or
a yes/no question, inside the group -- says yes, and ``times`` times at
the most (20). A reviewer reads the cap and the stop line the way they
read a call's address; there is no repeat without both. The repeat
itself then says yes (it got there) or no (it ran out), so a later step
can branch on it. A step outside the group that uses one inside it waits
for the repeat to finish, so it never sees a half-done pass. One group
per step, and no repeat inside another.

TWO BRANCHES CAN JOIN AGAIN. A step that uses a skipped step is skipped
too, so "carry on whichever way it went" can't name both branches'
results. ``after_any = ["plan", "sorry"]`` waits for all of them to be
finished and runs if ANY one of them ran; ``{{any}}`` in it is that
one's result (the first of the list that ran). It is skipped only when
every one of them was.

A BRANCH IS A STEP THAT SAYS YES OR NO. ``check``, ``person`` and
``repeat`` give ``yes`` or ``no``. A later step with ``only_if = "go"``
runs only when ``go`` said yes (``only_if = "not go"``: only when it said
no), and is skipped otherwise. A step that uses a skipped step is skipped
too, so a branch not taken never runs half of itself.

A QUESTION CAN OFFER CHOICES, OR TAKE WORDS. ``choices = ["Heat",
"Cool", "Leave it"]`` (two or three, drawn as buttons) makes the answer
one of them, and ``only_if = "mode is Heat"`` branches on it. ``typed =
true`` takes a few words the person types (``/routines say CODE ...``),
given to later steps as ``{{mode}}`` -- and, like every step's result,
fenced as text from outside when it goes into an ``ask``. Silence is
still no: no choice and no words, and a step gated on a choice is
skipped.

A CALL'S ARGUMENTS ARE THE PERSON'S YES. Installing a routine is saying
yes to the calls in it, as accepting a watch is (Prahari): each ``call``
runs with a grant fixing exactly its arguments. A call whose arguments
come from an EARLIER STEP (``{{mail}}`` in a URL) can't have been seen
before it runs, so it gets no grant: it runs only if its tool only
reads, and is refused otherwise. ``touches()`` says each of these in
words, before anybody says yes.

TEXT FROM OUTSIDE IS MARKED. A step's result put into an ``ask`` is
fenced (``<<<`` ... ``>>>``) and the model is told to read it and never
obey it: a mail that says "ignore your instructions" is a mail, not an
instruction.

Standard library only (``tomllib`` reads; ``dump`` writes the same shape
back, for the canvas).
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from typing import Any

#: What a step can be: exactly one of these keys.
KINDS = ("call", "ask", "read", "check", "person", "wait", "notify", "repeat")
#: What a check may test, in the words a Prahari watch uses.
TESTS = ("below", "above", "at_most", "at_least", "equals", "contains", "lacks", "matches")
#: The kinds of input a routine may ask for when it is installed.
INPUT_KINDS = ("text", "number", "time", "yesno", "account", "channel", "indriya")
#: Keys each step may carry besides its kind.
COMMON = {"id", "title", "after", "after_any", "only_if", "optional", "at"}
EXTRA = {"call": {"args", "pick"}, "ask": {"tools"}, "read": {"max_age"},
         "check": set(TESTS), "person": {"within", "choices", "typed"},
         "wait": {"until"}, "notify": set(), "repeat": {"until", "times", "every"}}
TOP = {"name", "title", "about", "version", "author", "inputs", "needs", "steps", "agent"}

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
STEP_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
REF_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_-]*)(?:\.([a-z0-9_.-]+))?\s*\}\}")
DURATION_RE = re.compile(r"^\s*(\d{1,4})\s*(s|sec|m|min|h|hr|hour|hours|d|day|days)\s*$",
                         re.IGNORECASE)
#: A value that is one input and nothing else: "{{inputs.line}}".
INPUT_ONLY_RE = re.compile(r"^\s*\{\{\s*inputs\.[a-z][a-z0-9_-]*\s*\}\}\s*$")
CLOCK_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
#: Roots a reference may start with that are not steps. ``any`` is the
#: result of whichever ``after_any`` step ran.
ROOTS = ("inputs", "run", "any")
#: Roots that are fixed before a run starts (``any`` is a step's result).
FIXED = ("inputs", "run")
RUN_KEYS = ("date", "time", "person", "routine", "id")

MAX_STEPS = 40
MAX_TEXT = 8000
#: How long a person may be waited on, at the most (and by default).
MAX_WITHIN, DEFAULT_WITHIN = 7 * 86400, 86400
MAX_WAIT = 7 * 86400
#: A repeat: how many passes at the most, how far apart at the least.
MAX_TIMES, MIN_EVERY, DEFAULT_EVERY = 20, 5 * 60, "15m"
#: Steps one repeat may name.
MAX_GROUP = 10
#: A question's choices: how many, how long each; a typed answer's length.
MAX_CHOICES, CHOICE_LEN, MAX_TYPED = 3, 24, 300


class RoutineError(ValueError):
    """A routine that can't be read or can't run, said in words."""


@dataclass
class Input:
    name: str
    kind: str = "text"
    label: str = ""
    default: Any = None
    #: For an account: which service ("gmail").
    service: str = ""

    def as_dict(self) -> dict:
        out = {"name": self.name, "kind": self.kind, "label": self.label or self.name}
        if self.default is not None:
            out["default"] = self.default
        if self.service:
            out["service"] = self.service
        return out


@dataclass
class Step:
    id: str
    kind: str
    #: The kind's own value: the tool, the prompt, the indriya, the value
    #: to check, the question, how long, the message.
    body: Any
    title: str = ""
    args: dict = field(default_factory=dict)
    pick: str = ""
    tools: bool = False
    max_age: str = ""
    test: tuple[str, Any] | None = None
    within: int = DEFAULT_WITHIN
    until: str = ""
    after: list[str] = field(default_factory=list)
    #: Runs when ANY of these ran (all finished, at least one not skipped).
    after_any: list[str] = field(default_factory=list)
    only_if: str = ""
    optional: bool = False
    at: list[float] = field(default_factory=list)
    #: A person step's choices (buttons), or a typed answer.
    choices: list[str] = field(default_factory=list)
    typed: bool = False
    #: A repeat's cap and its gap (``until`` names its stop step).
    times: int = 0
    every: str = ""
    #: Repeats this step waits for because it uses a step inside one (not
    #: written back: it is worked out from the routine).
    implied: set[str] = field(default_factory=set)

    @property
    def gate(self) -> tuple[str, bool, str] | None:
        """(the step, whether it must have said yes, the choice it must
        have made -- "" for a yes/no), or None."""
        if not self.only_if:
            return None
        words = self.only_if.split()
        if len(words) == 2 and words[0] == "not":
            return words[1], False, ""
        if len(words) >= 3 and words[1] == "is":
            return words[0], True, " ".join(words[2:])
        return words[0], True, ""

    @property
    def answers(self) -> str:
        """What a person step takes: yesno, choice, or words."""
        return "choice" if self.choices else "words" if self.typed else "yesno"

    def texts(self) -> list[str]:
        """Every string this step will fill in before it runs."""
        found: list[str] = []
        _strings(self.body, found)
        _strings(self.args, found)
        if self.test:
            _strings(self.test[1], found)
        return found

    def uses(self) -> set[str]:
        """The steps whose results this one puts into itself."""
        return {m.group(1) for t in self.texts() for m in REF_RE.finditer(t)
                if m.group(1) not in ROOTS}

    def waits_for(self) -> set[str]:
        """Every step that must be finished before this one starts."""
        out = self.uses() | set(self.after) | set(self.after_any) | self.implied
        if self.kind == "repeat":
            out |= set(self.body)
        if self.gate:
            out.add(self.gate[0])
        return out

    def as_dict(self) -> dict:
        """The step as the canvas and ``dump`` take it: TOML's own keys."""
        out: dict[str, Any] = {"id": self.id}
        if self.title:
            out["title"] = self.title
        if self.kind == "check":
            out["check"] = self.body
            if self.test:
                out[self.test[0]] = self.test[1]
        else:
            out[self.kind] = self.body
        if self.args:
            out["args"] = self.args
        if self.pick:
            out["pick"] = self.pick
        if self.tools:
            out["tools"] = True
        if self.max_age:
            out["max_age"] = self.max_age
        if self.kind == "person" and self.within != DEFAULT_WITHIN:
            out["within"] = _duration_words(self.within)
        if self.choices:
            out["choices"] = list(self.choices)
        if self.typed:
            out["typed"] = True
        if self.until:
            out["until"] = self.until
        if self.times:
            out["times"] = self.times
        if self.every:
            out["every"] = self.every
        if self.after:
            out["after"] = list(self.after)
        if self.after_any:
            out["after_any"] = list(self.after_any)
        if self.only_if:
            out["only_if"] = self.only_if
        if self.optional:
            out["optional"] = True
        if self.at:
            out["at"] = [round(float(v)) for v in self.at[:2]]
        return out


@dataclass
class Routine:
    name: str
    title: str
    steps: list[Step]
    about: str = ""
    version: str = "1"
    author: str = ""
    inputs: list[Input] = field(default_factory=list)
    needs: dict = field(default_factory=dict)
    #: The agent a ``tools = true`` ask runs as (a package name or folder).
    agent: str = ""

    def step(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise RoutineError(f"no step {step_id!r} in {self.name}")

    def input(self, name: str) -> Input | None:
        return next((i for i in self.inputs if i.name == name), None)

    def group_of(self, step_id: str) -> Step | None:
        """The repeat whose group this step is in, if one is."""
        return next((s for s in self.steps if s.kind == "repeat" and step_id in s.body),
                    None)

    def order(self) -> list[list[str]]:
        """The steps in waves: each wave's steps may run side by side."""
        waits = {s.id: s.waits_for() for s in self.steps}
        done: set[str] = set()
        waves: list[list[str]] = []
        while len(done) < len(self.steps):
            wave = [s.id for s in self.steps if s.id not in done and waits[s.id] <= done]
            if not wave:
                stuck = sorted(set(waits) - done)
                raise RoutineError("these steps wait on each other, and a routine has no "
                                   f"loops: {', '.join(stuck)}")
            waves.append(wave)
            done.update(wave)
        return waves

    def as_dict(self) -> dict:
        out: dict[str, Any] = {"name": self.name, "title": self.title}
        if self.about:
            out["about"] = self.about
        out["version"] = self.version
        if self.author:
            out["author"] = self.author
        if self.agent:
            out["agent"] = self.agent
        if self.inputs:
            out["inputs"] = {i.name: {k: v for k, v in i.as_dict().items() if k != "name"}
                             for i in self.inputs}
        if self.needs:
            out["needs"] = self.needs
        out["steps"] = [s.as_dict() for s in self.steps]
        return out


# -- reading ------------------------------------------------------------------------


def parse(text: str) -> Routine:
    """A routine from its TOML, checked; ``RoutineError`` says what's wrong."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RoutineError(f"not TOML: {exc}") from None
    return from_dict(data)


def from_dict(data: dict) -> Routine:
    if not isinstance(data, dict):
        raise RoutineError("a routine is a table")
    unknown = sorted(set(data) - TOP)
    if unknown:
        raise RoutineError(f"unknown keys: {', '.join(unknown)} (known: "
                           f"{', '.join(sorted(TOP))})")
    name = str(data.get("name") or "").strip()
    if not NAME_RE.match(name):
        raise RoutineError(f"name {name!r} must be one short lowercase word: letters, "
                           "digits and dashes, 2-40 of them (morning-brief)")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RoutineError("a routine needs at least one [[steps]]")
    if len(raw_steps) > MAX_STEPS:
        raise RoutineError(f"{len(raw_steps)} steps; {MAX_STEPS} at the most")
    inputs = _inputs(data.get("inputs") or {})
    steps = [_step(raw, n) for n, raw in enumerate(raw_steps, start=1)]
    seen: set[str] = set()
    for step in steps:
        if step.id in seen:
            raise RoutineError(f"two steps are called {step.id!r}")
        if step.id in ROOTS:
            raise RoutineError(f"a step can't be called {step.id!r}: that word is kept "
                               "for {{inputs.NAME}}, {{run.date}} and {{any}}")
        seen.add(step.id)
    needs = data.get("needs") or {}
    if not isinstance(needs, dict):
        raise RoutineError("needs is a table: setu = [\"gmail\"], phone = true")
    routine = Routine(
        name=name, title=str(data.get("title") or name).strip()[:120], steps=steps,
        about=str(data.get("about") or "").strip()[:2000],
        version=str(data.get("version") or "1").strip()[:20],
        author=str(data.get("author") or "").strip()[:80], inputs=inputs, needs=needs,
        agent=str(data.get("agent") or "").strip())
    _check_refs(routine)
    _check_groups(routine)
    routine.order()          # refuses a loop
    return routine


def _inputs(raw: Any) -> list[Input]:
    if not isinstance(raw, dict):
        raise RoutineError("inputs is a table of tables: [inputs.city] kind = \"text\"")
    out = []
    for name, spec in raw.items():
        if not STEP_RE.match(name):
            raise RoutineError(f"input {name!r}: one lowercase word")
        spec = spec if isinstance(spec, dict) else {"default": spec}
        kind = str(spec.get("kind") or "text")
        if kind not in INPUT_KINDS:
            raise RoutineError(f"input {name}: kind {kind!r} is not one of "
                               f"{', '.join(INPUT_KINDS)}")
        out.append(Input(name=name, kind=kind, label=str(spec.get("label") or ""),
                         default=spec.get("default"), service=str(spec.get("service") or "")))
    return out


def _step(raw: Any, n: int) -> Step:
    if not isinstance(raw, dict):
        raise RoutineError(f"step {n} is not a table")
    step_id = str(raw.get("id") or "").strip()
    where = f"step {step_id or n}"
    if not STEP_RE.match(step_id):
        raise RoutineError(f"{where}: id must be one lowercase word (weather, brief)")
    kinds = [k for k in KINDS if k in raw]
    if len(kinds) != 1:
        raise RoutineError(f"{where}: says {' and '.join(kinds) if kinds else 'nothing'}; "
                           f"a step is exactly one of {', '.join(KINDS)}")
    kind = kinds[0]
    allowed = COMMON | EXTRA[kind] | {kind}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise RoutineError(f"{where}: unknown keys for a {kind} step: {', '.join(unknown)}")
    body = raw[kind]
    step = Step(id=step_id, kind=kind, body=body, title=str(raw.get("title") or "")[:80],
                optional=bool(raw.get("optional")))
    after = raw.get("after") or []
    if isinstance(after, str):
        after = [after]
    if not isinstance(after, list) or not all(isinstance(a, str) for a in after):
        raise RoutineError(f"{where}: after is a list of step ids")
    step.after = [a.strip() for a in after]
    after_any = raw.get("after_any") or []
    if (not isinstance(after_any, list) or not all(isinstance(a, str) for a in after_any)
            or (after_any and len(after_any) < 2)):
        raise RoutineError(f"{where}: after_any is a list of two or more step ids "
                           "(the branches it joins)")
    step.after_any = [a.strip() for a in after_any]
    only_if = str(raw.get("only_if") or "").strip()
    if only_if:
        words = only_if.split()
        if not (len(words) == 1 or (len(words) == 2 and words[0] == "not")
                or (len(words) >= 3 and words[1] == "is")):
            raise RoutineError(f"{where}: only_if is a step's id, \"not\" and one, or "
                               "\"STEP is CHOICE\"")
        step.only_if = " ".join(words)
    at = raw.get("at")
    if at is not None:
        if (not isinstance(at, list) or len(at) != 2
                or not all(isinstance(v, (int, float)) for v in at)):
            raise RoutineError(f"{where}: at is where the canvas draws it, [x, y]")
        step.at = [float(at[0]), float(at[1])]
    _kind_fields(step, raw, where)
    return step


def _kind_fields(step: Step, raw: dict, where: str) -> None:
    body = step.body
    if step.kind == "call":
        if not isinstance(body, str) or not body.strip() or " " in body.strip():
            raise RoutineError(f"{where}: call is a tool's exact name (web_fetch)")
        step.body = body.strip()
        args = raw.get("args") or {}
        if not isinstance(args, dict):
            raise RoutineError(f"{where}: args is a table: args = {{ url = \"...\" }}")
        step.args = args
        pick = str(raw.get("pick") or "").strip()
        _check_pick(pick, where)
        step.pick = pick
    elif step.kind in ("ask", "notify", "person"):
        if not isinstance(body, str) or not body.strip():
            raise RoutineError(f"{where}: {step.kind} is words")
        if len(body) > MAX_TEXT:
            raise RoutineError(f"{where}: {len(body)} characters; {MAX_TEXT} at the most")
        step.body = body.strip()
        if step.kind == "ask":
            step.tools = bool(raw.get("tools"))
        if step.kind == "person":
            within = raw.get("within")
            step.within = duration(within, where) if within is not None else DEFAULT_WITHIN
            if step.within > MAX_WITHIN:
                raise RoutineError(f"{where}: within is 7 days at the most")
            _answers(step, raw, where)
    elif step.kind == "read":
        if not isinstance(body, str) or not (NAME_RE.match(body.strip())
                                             or INPUT_ONLY_RE.match(body)):
            raise RoutineError(f"{where}: read is an indriya's name (outside-temp), or "
                               "an input that names one")
        step.body = body.strip()
        max_age = str(raw.get("max_age") or "").strip()
        if max_age:
            duration(max_age, where)
        step.max_age = max_age
    elif step.kind == "check":
        if not isinstance(body, str) or not body.strip():
            raise RoutineError(f"{where}: check is the value to test (\"{{{{temp}}}}\")")
        tests = [t for t in TESTS if t in raw]
        if len(tests) != 1:
            raise RoutineError(f"{where}: a check has exactly one test, one of "
                               f"{', '.join(TESTS)}")
        test = tests[0]
        value = raw[test]
        if test in ("below", "above", "at_most", "at_least") and (
                isinstance(value, bool) or not isinstance(value, (int, float))) and not (
                isinstance(value, str) and INPUT_ONLY_RE.match(value)):
            raise RoutineError(f"{where}: {test} is a number, or an input that is one "
                               "(\"{{inputs.line}}\")")
        if test == "matches":
            try:
                re.compile(str(value))
            except re.error as exc:
                raise RoutineError(f"{where}: matches is not a pattern: {exc}") from None
        step.test = (test, value)
    elif step.kind == "repeat":
        _repeat(step, raw, where)
    elif step.kind == "wait":
        until = str(raw.get("until") or "").strip()
        if body in ("", None) and until:
            step.body = ""
        else:
            seconds = duration(body, where)
            if seconds > MAX_WAIT:
                raise RoutineError(f"{where}: a wait is 7 days at the most")
            step.body = str(body).strip()
        if until:
            if not CLOCK_RE.match(until):
                raise RoutineError(f"{where}: until is a time of day, 07:30")
            step.until = until


def _answers(step: Step, raw: dict, where: str) -> None:
    """A person step's choices, or its typed answer."""
    choices = raw.get("choices")
    typed = raw.get("typed")
    if typed is not None and not isinstance(typed, bool):
        raise RoutineError(f"{where}: typed is true or false")
    if choices is not None:
        if typed:
            raise RoutineError(f"{where}: a question takes choices OR typed words, not both")
        if (not isinstance(choices, list) or not 2 <= len(choices) <= MAX_CHOICES
                or not all(isinstance(c, str) and c.strip() for c in choices)):
            raise RoutineError(f"{where}: choices is a list of two or three short words "
                               "(buttons)")
        cleaned = [" ".join(c.split()) for c in choices]
        for choice in cleaned:
            if len(choice) > CHOICE_LEN:
                raise RoutineError(f"{where}: choice {choice!r} is longer than "
                                   f"{CHOICE_LEN} characters (it is a button)")
            if choice.lower() in ("yes", "no", "not") or choice.isdigit():
                raise RoutineError(f"{where}: a choice can't be {choice!r} (for yes or no, "
                                   "leave choices out)")
        if len({c.lower() for c in cleaned}) != len(cleaned):
            raise RoutineError(f"{where}: two choices say the same")
        step.choices = cleaned
    step.typed = bool(typed)


def _repeat(step: Step, raw: dict, where: str) -> None:
    """A repeat's group, stop step, cap and gap, each said."""
    group = step.body
    if isinstance(group, str):
        group = [group]
    if (not isinstance(group, list) or not group
            or not all(isinstance(g, str) and g.strip() for g in group)):
        raise RoutineError(f"{where}: repeat is a list of the steps to do again "
                           "([\"temp\", \"warm\"])")
    if len(group) > MAX_GROUP:
        raise RoutineError(f"{where}: a repeat names {MAX_GROUP} steps at the most")
    step.body = [g.strip() for g in group]
    until = str(raw.get("until") or "").strip()
    if not until:
        raise RoutineError(f"{where}: a repeat says when to stop: until = \"STEP\" (a "
                           "check in its group that says yes when it's done)")
    step.until = until
    times = raw.get("times")
    if isinstance(times, bool) or not isinstance(times, int) or not 1 <= times <= MAX_TIMES:
        raise RoutineError(f"{where}: a repeat says how many times at the most: times = "
                           f"N, 1 to {MAX_TIMES}")
    step.times = times
    every = str(raw.get("every") or DEFAULT_EVERY).strip()
    if duration(every, where) < MIN_EVERY:
        raise RoutineError(f"{where}: every is 5 minutes at the least (a repeat that "
                           "looks more often is a watch's job)")
    if duration(every, where) > MAX_WAIT:
        raise RoutineError(f"{where}: every is 7 days at the most")
    step.every = every if raw.get("every") is not None else ""


def _check_pick(pick: str, where: str) -> None:
    if not pick or pick == "number":
        return
    head, _, rest = pick.partition(":")
    if head == "json" and rest:
        return
    if head in ("number", "text") and rest:
        try:
            re.compile(rest)
        except re.error as exc:
            raise RoutineError(f"{where}: pick's pattern: {exc}") from None
        return
    raise RoutineError(f"{where}: pick is \"json:a.b[0]\", \"number\", \"number:PATTERN\", "
                       f"or \"text:PATTERN\" (not {pick!r})")


def _check_refs(routine: Routine) -> None:
    ids = {s.id for s in routine.steps}
    for step in routine.steps:
        for text in step.texts():
            for match in REF_RE.finditer(text):
                root, rest = match.group(1), match.group(2) or ""
                if root == "any":
                    if not step.after_any:
                        raise RoutineError(f"step {step.id}: {{{{any}}}} is the result of "
                                           "whichever after_any step ran, and this step "
                                           "has no after_any")
                elif root == "inputs":
                    if not rest or routine.input(rest) is None:
                        raise RoutineError(f"step {step.id}: {{{{inputs.{rest}}}}} is not "
                                           "one of this routine's inputs")
                elif root == "run":
                    if rest not in RUN_KEYS:
                        raise RoutineError(f"step {step.id}: {{{{run.{rest}}}}}: a run "
                                           f"has {', '.join(RUN_KEYS)}")
                elif root not in ids:
                    raise RoutineError(f"step {step.id} uses {{{{{root}}}}}, and there is "
                                       "no step by that name")
                elif root == step.id:
                    raise RoutineError(f"step {step.id} uses its own result")
        for other in [*step.after, *step.after_any]:
            if other not in ids:
                raise RoutineError(f"step {step.id}: after {other!r}, no step by that name")
            if other == step.id:
                raise RoutineError(f"step {step.id} waits for itself")
        gate = step.gate
        if gate:
            gated = routine.step(gate[0]) if gate[0] in ids else None
            if gated is None:
                raise RoutineError(f"step {step.id}: only_if {gate[0]!r}, no step by that "
                                   "name")
            if gated.kind not in ("check", "person", "repeat"):
                raise RoutineError(f"step {step.id}: only_if names {gate[0]}, a "
                                   f"{gated.kind} step; only a check, a question or a "
                                   "repeat says yes or no")
            if gated.typed:
                raise RoutineError(f"step {step.id}: only_if names {gate[0]}, which takes "
                                   "typed words; a step can use them ({{" + gate[0]
                                   + "}}), not branch on them")
            if gate[2] and not gated.choices:
                raise RoutineError(f"step {step.id}: only_if \"{gate[0]} is ...\" needs "
                                   f"{gate[0]} to offer choices")
            if gated.choices:
                if not gate[2]:
                    raise RoutineError(f"step {step.id}: {gate[0]} offers choices; say "
                                       f"which: only_if = \"{gate[0]} is "
                                       f"{gated.choices[0]}\"")
                if gate[2].lower() not in {c.lower() for c in gated.choices}:
                    raise RoutineError(f"step {step.id}: {gate[2]!r} is not one of "
                                       f"{gate[0]}'s choices ({', '.join(gated.choices)})")


def _check_groups(routine: Routine) -> None:
    """Each repeat's group: there, not itself, not another repeat, in one
    group only, its stop step inside it and able to say yes. Then each
    step outside a group that uses one inside it waits for the repeat."""
    ids = {s.id for s in routine.steps}
    owner: dict[str, str] = {}
    for step in routine.steps:
        if step.kind != "repeat":
            continue
        where = f"step {step.id}"
        for member in step.body:
            if member not in ids:
                raise RoutineError(f"{where}: repeats {member!r}, no step by that name")
            if member == step.id:
                raise RoutineError(f"{where}: a repeat can't repeat itself")
            if routine.step(member).kind == "repeat":
                raise RoutineError(f"{where}: {member} is a repeat; one can't sit inside "
                                   "another")
            if member in owner:
                raise RoutineError(f"{where}: {member} is already repeated by "
                                   f"{owner[member]}; a step is in one repeat at most")
            owner[member] = step.id
        if step.until not in step.body:
            raise RoutineError(f"{where}: until {step.until!r} must be one of the steps it "
                               "repeats")
        stop = routine.step(step.until)
        if not (stop.kind == "check" or (stop.kind == "person" and stop.answers == "yesno")):
            raise RoutineError(f"{where}: until names {stop.id}, a {stop.kind} step; it "
                               "stops on a check, or a yes/no question, that says yes")
    for step in routine.steps:
        if step.kind == "repeat":
            continue
        needs = step.uses() | set(step.after) | set(step.after_any)
        if step.gate:
            needs.add(step.gate[0])
        mine = owner.get(step.id)
        step.implied = {owner[n] for n in needs if n in owner and owner[n] != mine}


def duration(value: Any, where: str = "") -> int:
    """Seconds, from "30m", "2h", "1d" (or a bare number of seconds)."""
    if isinstance(value, bool):
        raise RoutineError(f"{where}: {value!r} is not a length of time")
    if isinstance(value, (int, float)):
        return int(value)
    match = DURATION_RE.match(str(value or ""))
    if not match:
        raise RoutineError(f"{where}: {value!r} is not a length of time (30m, 2h, 1d)")
    n, unit = int(match.group(1)), match.group(2).lower()[0]
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _duration_words(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)


# -- filling in ---------------------------------------------------------------------


def fill(value: Any, results: dict[str, str], inputs: dict[str, Any],
         run: dict[str, str], *, fence: bool = False) -> Any:
    """``value`` with every ``{{...}}`` filled in. ``fence``: a step's
    result goes in marked as text from outside (for an ask)."""
    if isinstance(value, dict):
        return {k: fill(v, results, inputs, run, fence=fence) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, results, inputs, run, fence=fence) for v in value]
    if not isinstance(value, str):
        return value

    def one(match: re.Match) -> str:
        root, rest = match.group(1), match.group(2) or ""
        if root == "inputs":
            got = inputs.get(rest)
            return "" if got is None else str(got)
        if root == "run":
            return str(run.get(rest) or "")
        got = str(results.get(root) or "")
        if rest and rest != "value":
            got = _pick_path(got, rest)
        return f"\n<<<\n{got}\n>>>\n" if fence else got

    return REF_RE.sub(one, value)


def uses_results(value: Any) -> bool:
    """Whether a value takes anything from an earlier step (``{{any}}``
    included: it is one)."""
    found: list[str] = []
    _strings(value, found)
    return any(m.group(1) not in FIXED for t in found for m in REF_RE.finditer(t))


_NO_JSON = object()


def json_of(text: str):
    """The JSON in a tool's answer, or ``_NO_JSON``. A tool may say a line
    first (Yantra's ``web_fetch`` starts ``source: URL (application/json)``)
    and its JSON after; as Prahari's pick does, the JSON is found there."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for opener in ("{", "["):
        start = text.find(opener)
        if start > 0:
            try:
                return decoder.raw_decode(text[start:])[0]
            except json.JSONDecodeError:
                continue
    return _NO_JSON


def _pick_path(text: str, path: str) -> str:
    """``{{weather.current.temperature_2m}}``: a field of a step's JSON."""
    data = json_of(text)
    if data is _NO_JSON:
        return ""
    got = json_path(data, path)
    if got is None:
        return ""
    return got if isinstance(got, str) else json.dumps(got)


def json_path(data: Any, path: str) -> Any:
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(data, list) or index >= len(data):
                return None
            data = data[index]
        else:
            if isinstance(data, list) and part.isdigit():
                index = int(part)
                data = data[index] if index < len(data) else None
            elif isinstance(data, dict):
                data = data.get(part)
            else:
                return None
        if data is None:
            return None
    return data


NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")


def pick(text: str, how: str) -> tuple[str, str]:
    """(what the pick found, why it found nothing). ``how`` empty: all."""
    if not how:
        return text, ""
    head, _, rest = how.partition(":")
    if head == "json":
        data = json_of(text)
        if data is _NO_JSON:
            return "", "the answer has no JSON in it"
        got = json_path(data, rest)
        if got is None:
            return "", f"nothing at {rest}"
        return (got if isinstance(got, str) else json.dumps(got)), ""
    if head == "number":
        if rest:
            match = re.search(rest, text)
            if not match:
                return "", "the pattern found nothing"
            found = match.group(1) if match.groups() else match.group(0)
        else:
            found = text
        number = NUMBER_RE.search(found)
        if not number:
            return "", "no number in it"
        return number.group(0).replace(",", ""), ""
    match = re.search(rest, text, re.DOTALL)
    if not match:
        return "", "the pattern found nothing"
    return (match.group(1) if match.groups() else match.group(0)), ""


def number(text: Any) -> float | None:
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = NUMBER_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def test(value: str, how: str, against: Any) -> tuple[bool, str]:
    """(yes, in words). A number test on no number is no, and says so."""
    if how in ("below", "above", "at_most", "at_least"):
        got = number(value)
        if got is None:
            return False, f"{value!r} has no number in it, so no"
        line = float(against)
        yes = {"below": got < line, "above": got > line, "at_most": got <= line,
               "at_least": got >= line}[how]
        word = {"below": "below", "above": "above", "at_most": "at most",
                "at_least": "at least"}[how]
        return yes, f"{_n(got)} is {'' if yes else 'not '}{word} {_n(line)}"
    text = str(value or "")
    if how == "equals":
        yes = text.strip().lower() == str(against).strip().lower()
        return yes, f"{text!r} {'is' if yes else 'is not'} {against!r}"
    if how == "contains":
        yes = str(against).lower() in text.lower()
        return yes, f"it {'says' if yes else 'does not say'} {against!r}"
    if how == "lacks":
        yes = str(against).lower() not in text.lower()
        return yes, f"it {'does not say' if yes else 'says'} {against!r}"
    yes = re.search(str(against), text) is not None
    return yes, f"it {'matches' if yes else 'does not match'} {against!r}"


def _n(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


# -- in words -----------------------------------------------------------------------


def touches(routine: Routine, inputs: dict[str, Any] | None = None) -> list[str]:
    """What it touches, one line each, before anybody says yes: every call
    (and whether it was seen, or comes from an earlier step), every
    question to the model, every reading, who is asked and told."""
    inputs = {**{i.name: f"[{i.name}]" for i in routine.inputs}, **defaults(routine),
              **{k: v for k, v in (inputs or {}).items() if v not in ("", None)}}
    #: what each step will have given, said as its name
    later = {s.id: f"[{s.id}]" for s in routine.steps}
    lines: list[str] = []
    for step in routine.steps:
        name = step.title or step.id
        if step.kind == "call":
            args = fill(step.args, later, inputs, {})
            if uses_results(step.args):
                lines.append(f"{name}: calls {step.body} with what an earlier step "
                             "found (only if that tool only reads)")
            else:
                lines.append(f"{name}: calls {step.body} {json.dumps(args)[:200]}")
        elif step.kind == "ask":
            lines.append(f"{name}: asks the model"
                         + (" as your agent, WITH ITS TOOLS (each one as your rules "
                            "say)" if step.tools else ", with no tools"))
        elif step.kind == "read":
            lines.append(f"{name}: reads Prahari's reading "
                         f"{fill(step.body, later, inputs, {})}")
        elif step.kind == "person":
            takes = ("" if step.answers == "yesno" else
                     f", choosing {' / '.join(step.choices)}" if step.choices else
                     ", in a few typed words")
            silence = {"yesno": "no answer is no", "choice": "no answer is no choice",
                       "words": "no answer is no words"}[step.answers]
            lines.append(f"{name}: asks you \"{fill(step.body, later, inputs, {})[:120]}\""
                         f"{takes}, and waits up to {_duration_words(step.within)} "
                         f"({silence})")
        elif step.kind == "repeat":
            lines.append(f"{name}: does {', '.join(step.body)} again, every "
                         f"{step.every or DEFAULT_EVERY}, until {step.until} says yes, "
                         f"{step.times} times at the most")
        elif step.kind == "notify":
            lines.append(f"{name}: tells you, on your channels")
        elif step.kind == "wait":
            lines.append(f"{name}: waits "
                         + (f"until {step.until}" if step.until else str(step.body)))
    accounts = needs_accounts(routine)
    if accounts:
        lines.append("uses your accounts: " + ", ".join(accounts))
    if routine.needs.get("phone"):
        lines.append("uses your phone")
    return lines


def needs_accounts(routine: Routine) -> list[str]:
    raw = routine.needs.get("setu") or []
    return [str(a) for a in raw] if isinstance(raw, list) else [str(raw)]


def cost(routine: Routine) -> str:
    """"no model", or how many times a run asks one."""
    asks = [s for s in routine.steps if s.kind == "ask"]
    if not asks:
        return "no model"

    def passes(step: Step) -> int:
        group = routine.group_of(step.id)
        return group.times if group else 1

    count = sum(passes(s) for s in asks)
    turns = sum(passes(s) for s in asks if s.tools)
    repeated = any(routine.group_of(s.id) for s in asks)
    said = (f"{'up to ' if repeated else ''}{count} model ask{'s' if count != 1 else ''} "
            "per run")
    if turns:
        said += f" ({turns} of them a full agent turn)"
    return said


def defaults(routine: Routine) -> dict[str, Any]:
    return {i.name: i.default for i in routine.inputs if i.default is not None}


def check_inputs(routine: Routine, given: dict[str, Any]) -> dict[str, Any]:
    """The inputs a run goes with: given over defaults, each of the right
    kind, none missing, none unknown."""
    if not isinstance(given, dict):
        raise RoutineError("inputs is an object: {\"city\": \"Raleigh\"}")
    unknown = sorted(set(given) - {i.name for i in routine.inputs})
    if unknown:
        raise RoutineError(f"{routine.name} has no input {', '.join(unknown)} (it has: "
                           f"{', '.join(i.name for i in routine.inputs) or 'none'})")
    out = defaults(routine)
    for spec in routine.inputs:
        if spec.name not in given:
            continue
        value = given[spec.name]
        if spec.kind == "number":
            got = number(value)
            if got is None:
                raise RoutineError(f"input {spec.name} is a number, not {value!r}")
            value = int(got) if got == int(got) else got
        elif spec.kind == "yesno":
            value = "yes" if str(value).strip().lower() in ("yes", "true", "1", "y") \
                else "no"
        elif spec.kind == "time":
            if not CLOCK_RE.match(str(value).strip()):
                raise RoutineError(f"input {spec.name} is a time of day, 07:30")
            value = str(value).strip()
        else:
            value = str(value).strip()[:500]
        out[spec.name] = value
    missing = [i.name for i in routine.inputs if out.get(i.name) in (None, "")]
    if missing:
        raise RoutineError(f"{routine.name} needs {', '.join(missing)} filled in")
    return out


# -- writing it back ----------------------------------------------------------------


def dump(routine: Routine | dict) -> str:
    """The routine as TOML, in the order a person reads it."""
    data = routine.as_dict() if isinstance(routine, Routine) else routine
    lines: list[str] = []
    for key in ("name", "title", "about", "version", "author", "agent"):
        if key in data and data[key] not in ("", None):
            lines.append(f"{key} = {_value(data[key])}")
    for name, spec in (data.get("inputs") or {}).items():
        lines += ["", f"[inputs.{name}]"]
        lines += [f"{k} = {_value(v)}" for k, v in spec.items()]
    if data.get("needs"):
        lines += ["", "[needs]"]
        lines += [f"{k} = {_value(v)}" for k, v in data["needs"].items()]
    for step in data.get("steps") or []:
        lines += ["", "[[steps]]"]
        lines += [f"{k} = {_value(v)}" for k, v in step.items()]
    return "\n".join(lines) + "\n"


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        if "\n" in value:
            body = value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
            return f'"""\n{body}"""'
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    if value is None:
        return '""'
    raise RoutineError(f"can't write {type(value).__name__} in TOML")


def _key(key: str) -> str:
    return key if re.match(r"^[A-Za-z0-9_-]+$", key) else json.dumps(key)
