# 03 — Started by anything

A routine is useful at a time (*every morning*), when something happens
(*when the porch gets cold*), when a person asks (*do my morning brief*),
or at a button. Each of those already has a home: Samay keeps the times,
Prahari the watching, Dvara the chats, an agent the asking. None of them
should grow a second engine for steps.

Continues [01](01-a-routine-drawn-once.md) and [02](02-a-run-that-asks.md).

## Starting is adding a row

`vidhi start NAME --as PERSON --by WHO` checks the routine (installed,
not paused, its inputs filled, fewer than five runs of it open), copies
it into a new run, and writes that run as *queued*. That is all it does.
`vidhi serve` finds queued runs every two seconds and runs them.

**THE QUEUE IS THE TABLE.** A trigger needs no address, no token and no
running server to reach: only Vidhi's state folder. Sarathi mounts
`~/.vidhi` in every container, so Samay's, Prahari's and Dvara's each
start a run by running `vidhi start` where they are.

**AS ITS PERSON.** `--as` is the trigger's own person: a schedule's
owner, a watch's owner, the person in the chat. A routine installed for
somebody in the house runs as them, through Dvara, with their accounts.

**WHO STARTED IT IS SAID.** `--by` goes on the run (*samay:0a769de1*,
*prahari:6e04d8ad*, *dvara:telegram*, *agent*, *page*), so a run on the
page says where it came from.

## The triggers

| From | What |
|---|---|
| Samay | `--runner vidhi`, the routine's name as the prompt; the agent's `create_schedule` takes `routine`. The run is NOTHING NEW when it started (Vidhi tells the person what the routine finds), failed with Vidhi's words when it didn't |
| Prahari | a watch's `routine` (instead of `then`); the agent's `create_watch` and `update_watch` take it. What the watch saw goes in as the routine's `found` input, when it has one: the value itself (`58`), or the new items. A watch either asks the agent or starts a routine, never both |
| Dvara | `/routines run N` |
| an agent | `run_routine`, after the person's yes on a card that lists everything the routine touches |
| the page | **Run now**, with this run's inputs |

## Live receipt

A scratch Prahari, a pushed reading `porch-temp`, and a watch on it:

```
$ prahari add "Porch is cold" --sense porch-temp --when 'below 60' --routine coat-check
$ prahari indriya push porch-temp 64
6e04d8ad  learned    64
$ prahari indriya push porch-temp 58
6e04d8ad  fired      58  then: routine
$ prahari list
6e04d8ad  active  Porch is cold
          then: starts the routine coat-check (Vidhi)

$ vidhi runs --limit 1
5ca4159f  coat-check  done  2/5 steps  by prahari:6e04d8ad
inputs: {'found': '58', 'line': 60}
```

A scratch Samay:

```
$ samay add coat-check --runner vidhi --when "at 07:00"
$ samay run-now 0a769de1
Mon 9 Nov 11:39  quiet   NOTHING NEW
Started the routine coat-check (run 60833e71); Vidhi tells you what it finds.

$ vidhi runs --limit 1
60833e71  coat-check  done  2/5 steps  by samay:0a769de1
```

And Yantra with `qwen3.8:latest` and Vidhi's tools, asked only *"do my
morning thing"*: it read the routines, called `run_routine` for
`morning-brief`, and said the run was queued because Vidhi's server
wasn't running on that computer. The card it asked behind showed every
call the brief makes, its cost, and the inputs it would run with
(Yantra's notes/155).

## Not here

* ~~**Inputs per trigger.**~~ A schedule or a watch keeps its own
  values (`samay add ... --input city=Cary`, `prahari add ... --routine
  NAME --input room=porch`, or `routine_inputs` from the agent), given
  to each run over the installed ones. Whether the routine has that
  blank is Vidhi's to say when the run starts: a schedule with a blank
  it doesn't have fails, in Vidhi's words.
* **A trigger that waits for the run.** Starting returns at once; what
  the routine finds is the routine's to say.
