# 01 — A routine, drawn once

Some things a person wants done are more than one step and less than a
conversation. *Every morning: the weather, my unread mail and the
headlines, written into one short brief.* An agent can do that when
asked, but asked every morning it does it differently every morning: it
picks its own tools, in its own order, and spends a model call deciding
what a person already decided once. A Samay schedule repeats the asking,
not the steps.

A **routine** is the steps themselves, written down once. Vidhi keeps it,
runs it, and remembers where each run got to.

## Steps are things that already exist

A step is one of seven, and each is done by a program that already does
it:

| Step | Done by |
|---|---|
| `call` | `yantra --call`: one tool, no model (as a Prahari look) |
| `ask` | `yantra --prompt`: the model, with no tools unless `tools = true` |
| `read` | `prahari indriya get --as PERSON`: a reading Prahari keeps, as that person may see it (a run at the computer reads as Dvara's name for the owner, which is whose readings they are) |
| `check` | Vidhi: a test on a value, the words a Prahari watch uses |
| `person` | a question to the person, through Dvara: yes/no ([02](02-a-run-that-asks.md)), choices or a few words ([05](05-a-repeat-a-join-and-other-answers.md)) |
| `wait` | Vidhi's clock |
| `notify` | Dvara's `/notify`: the person's own channels |
| `repeat` | Vidhi's clock: some steps again, a set number of times at most ([05](05-a-repeat-a-join-and-other-answers.md)) |

Results flow on: `{{weather}}` in a step is what `weather` gave.

**WHAT RUNS SIDE BY SIDE IS WORKED OUT, NOT WRITTEN.** A step waits for
the steps it uses, the ones it names in `after`, and the one its
`only_if` names. Everything else starts the moment it can. The morning
brief's three fetches go together, and the step that writes the brief
starts when the slowest is in. Nobody writes "parallel" anywhere: the
routine says what each step needs, and the order follows.

**NO LOOPS, AND NO CODE.** A step that waits on itself, or on one that
waits on it, is refused when the routine is read. There is no step that
runs a program. That is a limit, and it is the point: a routine someone
else wrote can be read in full before it is installed. Every call, every
address, every question to the model is in the file, and `touches()`
says each in words. A loop or a script would be the one part a reader
couldn't check. (A `repeat` is the one way round, and it states its cap
and its stop line where a reader sees them:
[05](05-a-repeat-a-join-and-other-answers.md).)

**A BRANCH IS A STEP THAT SAYS YES OR NO.** `check` and `person` give
`yes` or `no`; `only_if = "go"` runs a step only on yes, `only_if = "not
go"` only on no. A step that uses a skipped step is skipped too, so a
branch not taken never runs half of itself, and each skip says why
(*"only if cheap said yes; it said no"*, *"go was skipped"*).

**A CALL'S ARGUMENTS ARE THE PERSON'S YES.** Installing a routine is
saying yes to its calls, as accepting a watch is. Each call runs with a
grant that fixes exactly its arguments. A call built from an earlier
step's result (`url = "{{find}}"`) can't have been seen before it runs,
so it gets no grant and runs only if its tool only reads. The words say
so before anyone installs it.

**TEXT FROM OUTSIDE IS FENCED.** A step's result put into an `ask` goes
in between `<<<` and `>>>`, and the prompt begins by saying those parts
came from outside and are to be read, never obeyed.

**A FAILED STEP STOPS THE RUN**, and the person is told which and why,
unless it's `optional`: then it gives nothing and the run goes on. The
morning brief's mail and headlines are optional, so a mail account that
won't answer doesn't cost the weather.

## Drawn, not typed

The page has a canvas. Each step is a box with its kind's colour; a line
shows what a step uses, a dotted line an `after`, a dashed one *if yes* or
*if no*. Dragging from a box's right dot onto another makes the second
wait for the first. A side panel edits the step clicked; with none
clicked, the routine's own name, words and inputs.

**THE PAGE CHECKS AS YOU DRAW.** Every change is sent to `/api/check`,
which reads the routine as Vidhi will and answers with what's wrong, or
the order it will run in (*1. weather + mail + news → 2. brief → 3.
send*) and what it touches. Saving is the same check, kept.

**THE CANVAS SENDS ITS OWN SHAPE; THE SERVER WRITES THE TOML.** A routine
drawn and a routine typed are kept, checked and signed the same way.
**TOML** shows the file, and a file pasted there is drawn.

## Live receipt

The morning brief, installed with its defaults, run with nothing else
started: the real `yantra` with `qwen3.8:latest`, the open-meteo
forecast, Gmail through Setu, NPR's feed.

```
$ vidhi run morning-brief
run 376559f9 of morning-brief: done
  done     Today's weather
  done     Unread mail             No threads match 'is:unread newer_than:1d'.
  done     Headlines
  done     Write the brief
  done     Send it to me  (this Vidhi has no Dvara to tell anyone through …; kept on the run)

weather 16:13:34 → 16:13:49
mail    16:13:34 → 16:13:48
news    16:13:34 → 16:13:49
brief   16:13:49 → 16:14:23

70° / 44°, clear, 0% rain — light jacket for the cool morning, otherwise easy.
Russell Brand sentenced to over 10 years for rape and sexual assault.
Supreme Court to hear a case that could reshape legal accountability for federal officers.
U.N. climate talks (COP31) open in Antalya, Turkey, with delegates frustrated over …
```

The three fetches started in the same second. The brief started the
second the last of them ended.

The first routine written by hand, a JSON pick on the forecast, failed:
*"the pick (json:current.temperature_2m) found nothing: the answer is
not JSON"*. `web_fetch` begins its answer with `source: URL
(application/json)` and then the JSON. Prahari had met that already; a
pick now finds the JSON after a tool's first line, as Prahari's does.

On the canvas, a new routine got a `call` step, a line dragged from it
onto the `notify` step, **Arrange**, **Save**, and the saved TOML had
`after = ["fetch"]` on the notify step and an `at` on each.

## Not here

* ~~**Loops.**~~ A bounded `repeat`: its cap and its stop line on its
  face ([05](05-a-repeat-a-join-and-other-answers.md)).
* ~~**A join after a branch.**~~ `after_any`, with `{{any}}` the result
  of the branch that ran ([05](05-a-repeat-a-join-and-other-answers.md)).
* **A call's grant for an argument from an earlier step.** It runs only
  if its tool reads.
