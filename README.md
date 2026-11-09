# Vidhi

**Routines you draw once, which a schedule, a watch, a button or a chat
can start.**

*Vidhi* (विधि) is "a procedure, a rite done step by step". A routine is a
few steps you set up once: *every morning, fetch the weather, my unread
mail and the headlines at the same time, have the model write one short
brief from them, and send it to me*. Or: *look up a price; if it's under
my line, ask me whether to make a plan; on my yes, write the plan.*

Vidhi is a sibling of [Yantra](../yantra) (the agent), Samay (the clock),
Prahari (the watch) and Dvara (the door to your chats). It does no work
itself. Each step is done by a program that already does that one thing:
a tool call is `yantra --call`, a question to the model is `yantra
--prompt`, a reading is Prahari's, and a message to you goes out through
Dvara. Vidhi keeps the steps in order, runs the ones that can go side by
side at the same time, and remembers where each run got to.

## In plain words

* **You draw a routine on Vidhi's page.** Each step is a box: *call a
  tool*, *ask the model*, *read a reading*, *check a value*, *ask me*,
  *wait*, *tell me*. Drag from one box's right dot onto another, and the
  second waits for the first. Steps that don't wait on each other run at
  the same time. The page says, as you draw, what's wrong, the order it
  will run in, and in words what it touches.
* **Or install a ready one.** Vidhi comes with a morning brief, a
  *price, then a plan*, and a cold-night warning. Installing one is
  filling its blanks: your city, your price line, which mail account.
* **Read it before you install it.** **Look inside** opens a ready
  routine on the same canvas, exactly as its author drew it, with
  nothing you can change. *Before you install* says where it came from
  (and checks a marketplace signature again), every address it reaches,
  the accounts it uses, and, in red capitals, anything worth a second
  look: a step that runs your agent with its tools, a call built from an
  earlier step's answer, a tool that isn't a plain read. **TOML** shows
  the exact file that would be kept.
* **A routine can stop and ask you.** An *ask me* step puts a yes/no
  question in your chat, with two buttons. The run waits, for a minute
  or a day, with nothing held open. When you press **Yes**, on your
  phone or the page, it carries on from there. No answer in time is no.
* **Anything can start one.** **Run now** on the page; `/routines run 1`
  in a chat; *"do my morning brief"* to your agent; a Samay schedule
  (*every day at 7:00*); a Prahari watch (*when the porch gets below
  60*), which hands over what it saw.
* **Your agent can run and install routines, never write one.** It
  picks one by name and fills blanks, which a small local model does
  well. Drawing the steps is yours.
* **Routines can be shared, safely.** Anyone can publish a routine to a
  marketplace. Nobody can install it until a reviewer has read it and
  signed it with their own key, and your Vidhi checks that signature
  against the reviewers *you* trust.

## Try it

```bash
uv sync
uv run vidhi templates                   # what can be installed
uv run vidhi install morning-brief --input latitude=51.5 --input longitude=-0.12 \
    --input unit=celsius
uv run vidhi run morning-brief           # runs here, and shows each step
uv run vidhi serve                       # the page (its link has the token)
```

With Sarathi, Vidhi is already running in the house: its card is on
Sarathi's home page, and `/routines` works in every chat.

A run of the morning brief with a local model (`qwen3.8:latest`), the
real weather, Gmail and NPR:

```
run 376559f9 of morning-brief: done
  done     Today's weather
  done     Unread mail
           No threads match 'is:unread newer_than:1d'.
  done     Headlines
  done     Write the brief
           70° / 44°, clear, 0% rain — light jacket for the cool morning, otherwise easy.
           Russell Brand sentenced to over 10 years for rape and sexual assault.
           Supreme Court to hear a case that could reshape legal accountability …
  done     Send it to me
```

The three fetches started in the same second; the brief waited only for
the slowest. Forty-nine seconds in all, most of it the model.

## A routine, written down

What the canvas draws is kept as a small TOML file, and an advanced user
can write one by hand. `vidhi check FILE` reads one and says what it
would do.

```toml
name = "coat-check"
title = "Coat check"

[inputs.line]
kind = "number"
label = "Cold means below"
default = 60

[[steps]]
id = "temp"
call = "web_fetch"
args = { url = "https://api.open-meteo.com/v1/forecast?latitude=35.78&longitude=-78.64&current=temperature_2m&temperature_unit=fahrenheit" }
pick = "json:current.temperature_2m"

[[steps]]
id = "cold"
check = "{{temp}}"
below = "{{inputs.line}}"

[[steps]]
id = "go"
person = "It's {{temp}}°F outside. Want a line on what to wear?"
within = "1h"
only_if = "cold"

[[steps]]
id = "wear"
ask = "It is {{temp}}°F outside. In one sentence, what should I wear?"
only_if = "go"

[[steps]]
id = "send"
notify = "{{wear}}"
```

| Step | What it does | It gives |
|---|---|---|
| `call = "TOOL"`, `args`, `pick` | one tool call, no model | what it said, or what `pick` took from it (`json:a.b`, `number`, `number:PATTERN`, `text:PATTERN`) |
| `ask = "..."` | a question to the model, no tools; `tools = true` makes it a full agent turn | the model's answer |
| `read = "NAME"` | a reading Prahari keeps (an indriya); `max_age = "5m"` reads it again if older | its value |
| `check = "{{x}}"` and one of `below`, `above`, `at_most`, `at_least`, `equals`, `contains`, `lacks`, `matches` | a test, no model | `yes` or `no` |
| `person = "..."`, `within = "2h"` | a yes/no question to you; the run waits | `yes`, or `no` (also when nobody answers in time) |
| `wait = "30m"` or `until = "07:30"` | a pause | nothing |
| `notify = "..."` | a message on your channels | where it went |

Every step may also have `title`, `after = ["id"]` (wait for a step it
doesn't use), `only_if = "go"` or `only_if = "not go"` (only when a
`check` or `person` step said yes, or no), and `optional = true` (if it
fails, it gives nothing and the run goes on).

`{{temp}}` is what the step `temp` gave; `{{temp.current.temperature_2m}}`
a field of its JSON. `{{inputs.line}}` is an input, filled when the
routine was installed (kinds: text, number, time, yesno, account,
channel, indriya). `{{run.date}}`, `{{run.time}}` and `{{run.person}}` are
the run's own.

**The rules a routine is held to**, each against a way it goes wrong
([notes/01](notes/01-a-routine-drawn-once.md)):

* **No loops and no code.** A routine that waits on itself is refused
  when it's read, and there is no step that runs a program. Everything a
  routine does is in the file, in words.
* **A call's arguments are your yes.** Each call runs with a grant fixing
  exactly its arguments, as a Prahari look does. A call whose arguments
  come from an earlier step can't have been seen, so it runs only if its
  tool only reads.
* **Text from outside is marked.** A step's result put into an `ask` is
  fenced, and the model is told to read it and never obey it.
* **A step that fails stops the run**, and you hear which and why,
  unless it's `optional`.
* **Five runs of one routine at once, at most**, so a watch firing in a
  loop can't start a hundred.

## When a routine asks you

```
$ vidhi run coat-check --input line=70
run dd7788e5 of coat-check: waiting -- waiting for your answer (go)
  done     Temperature now         61.8
  done     Cold?  (61.8 is below 70)
  waiting  Ask me  (asked you (F9SEKQ))
```

The question goes to your chat through Dvara, with **Yes** and **No**
buttons that send `/routines yes F9SEKQ` as if you'd typed it. It's also
on Vidhi's page under **Waiting for you**, and `vidhi answer F9SEKQ yes`
at a terminal. The run is rows on disk, not a process, so it can wait
for hours and survives a restart. An answer counts once, only from the
person it was put to. [notes/02](notes/02-a-run-that-asks.md).

## What starts a routine

| From | How |
|---|---|
| Vidhi's page | **Run now** on its card, with this run's inputs |
| a chat (Dvara) | `/routines` lists them; `/routines run 1` starts one; `/routines 1` says how it went |
| your agent | *"do my morning brief"*: `run_routine`, after your yes on a card that lists everything it touches |
| Samay | a schedule with `--runner vidhi` and the routine's name as its prompt (`samay add morning-brief --runner vidhi --when "at 07:00"`), or `routine` on the agent's `create_schedule` |
| Prahari | a watch with `--routine NAME` (or `routine` on `create_watch`): when it fires, the routine starts with what it saw as `{{inputs.found}}` |
| a program | `vidhi start NAME --as PERSON --by WHO` only adds the run; `vidhi serve` runs it |

Starting is only adding a row to Vidhi's state folder. Samay's, Prahari's
and Dvara's containers all mount that folder, so a trigger needs no
address and no token. [notes/03](notes/03-started-by-anything.md).

## Sharing: the marketplace

```bash
vidhi market publish my-routine.toml --to URL --as pat     # anyone; it waits for review
vidhi market show ID --from URL                           # a reviewer reads its notes
vidhi market approve ID --from URL --key ~/.ssh/id_ed25519 --as rita
vidhi market trust rita ~/rita.pub                          # once, on your computer
vidhi market get my-routine --from URL                      # checked against YOUR list
vidhi install my-routine
```

**Signed on the reviewer's own computer.** `ssh-keygen -Y sign` signs
the routine's exact bytes, and the private key never reaches the
marketplace. **Checked against the reviewers you trust.** A broken-into
server can't make a routine installable on your computer, and a routine
changed after it was signed is refused. The marketplace is `vidhi market
serve --dir DIR`, or `vidhi serve --market DIR` on the page's own port.
[notes/04](notes/04-a-marketplace-with-review.md).

## Where things are

* `~/.vidhi/vidhi.sqlite`: routines, runs, each step's result,
  questions (`$VIDHI_STATE` moves the folder).
* `~/.vidhi/catalog/`: your own templates (**Save as template** on the
  canvas); `~/.vidhi/market/`: ones fetched from a marketplace, each with
  its signature; `~/.vidhi/reviewers`: the reviewers you trust.
* `VIDHI_YANTRA`, `VIDHI_YANTRA_HOME`: the Yantra that does the calls and
  questions, and where it runs. `VIDHI_PRAHARI`: the Prahari for
  readings. `VIDHI_DVARA_URL`, `VIDHI_DVARA_TOKEN`, `VIDHI_DVARA_ACTOR`:
  the door, for messages and the Dvara road. Sarathi sets them all.

## The source

```
src/vidhi/
  routine.py   the format: reading, checking, waves, filling in, words
               (notes/01)
  store.py     one SQLite file: routines, runs, steps, questions
  runner.py    a run worked forward, side by side; stopping to ask,
               picked up again; one worker per run (notes/02)
  roads.py     who does each step: yantra, Dvara as the person, prahari
  clock.py     what `vidhi serve` keeps: queued runs started, waits woken
               (notes/03)
  routines.py  installing, mending, pausing: one place for every door
  catalog.py   templates: yours, a marketplace's, Vidhi's own
  market.py    publish, review, sign, fetch, check (notes/04)
  http.py      the page's API, and the marketplace's routes
  mcp.py       seven tools for an agent; none writes a step
  status.py    `vidhi status --json`, for the family
  keeps.py     `vidhi keeps --json`: the state folder, for a house backup
  cli.py       `vidhi`
  static/      the page and its canvas
  catalog/     morning-brief, price-then-plan, cold-night
```

`uv run pytest` runs the tests (85); `uv run ruff check src tests` the
lint. No dependencies: the standard library, plus OpenSSH's `ssh-keygen`
for signatures.
