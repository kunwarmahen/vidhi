# What starts it, and a step tried alone

A routine on the canvas said what its steps were, never what they had
done. The cold-night warning's boxes read *The temperature now*, *Below
the line?*, *Ask me first*, *Send it*. Whether the last run had read 31
or 58, said yes or no, or stopped at the question, was in the run list
below, in other words. And nothing on its card said what starts it.
The routine's own words said *"a good one to start from a schedule in
the evening"*, which meant going to Samay's page and typing its name as
the prompt with the right runner.

## A box says what it gave

**THE LAST RUN IS DRAWN ON THE CANVAS.** Each box carries a line under
its title: *✓ 31* on the read, *✓ yes* on the check, *… waiting* on the
question, *– skipped* or *✗ failed* when it was. The run's time and the
full result are in the box's tooltip. A drawing that only says what was
meant hides the one thing you open it to find out.

**A STEP CAN BE TRIED ALONE, AND A TRY SENDS NOTHING.** *Try this step*
(`POST /api/try`, `runner.try_step`) does the one step now:

| Step | A try |
|---|---|
| read | reads the reading, as a run would |
| check | checks it, on what earlier steps gave |
| call | runs with no grant: only a tool that just reads gets through |
| ask | the model, with no tools; one with `tools = true` isn't tried (a real run asks first, as your rules say) |
| ask me | the question written out in full, with its choices: **never asked** |
| tell me | the message written out: **never sent** |
| wait | when it would wake |

What earlier steps gave comes from the routine's last run, or from what
was tried a moment ago on the page, so `{{temp}}` in the check means
what it meant then. Nothing is kept: no run, no question, no row. The
box shows *tried: yes* until the canvas is closed.

**`{{…}}` IS SAID IN WORDS.** Under every field holding one, the page
writes it out: *Reads as: «The temperature now» (31)*, *«Cold means
below» (35)*. A check against a reading says its unit (*in °F, the unit
of outside-temp*), and so does the number blank on the card (*Cold means
below (°F)*), taken from the reading's own words.

**AN ACCOUNT IS PICKED TOO.** An `account` blank (the morning brief's
Gmail) is a drop-down of this computer's Setu connections for that
service, as a reading's blank is of Prahari's readings
([01](01-a-routine-drawn-once.md)). It is only the computer's own:
someone else in the house keeps their accounts in their own Setu, which
this Vidhi can't read, so for them it stays a box to type in. Every
reading drop-down ends with *+ Make a new reading on Prahari's page…*.
The `channel` kind gets no drop-down: no step uses it, and a choice that
changes nothing would be worse than none.

**A READ THAT FINDS NOTHING SAYS WHAT THERE IS.** *there is no reading
'outdoor'; yours are: outside-temp. Pick one under the routine's
Inputs*, instead of Prahari's *no indriya outdoor*.

## What starts it

**VIDHI ASKS; SAMAY AND PRAHARI KEEP.** The card's *What starts it*
lists every Samay schedule and Prahari watch that starts this routine,
asked of them (`samay list --json`, `prahari list --json`: one ask each
for all the routines). Under it:

* **At a time**: *at 20:00*, *at 07:30 on mon-fri*. This is `samay add
  NAME --runner vidhi --when ...`.
* **When a reading crosses a line**: a reading, *below* or *above*, a
  number. This is `prahari add --sense READING --when "below 35"
  --routine NAME`: a watch with no model, decided on every new reading.
  The fields start from the routine's own check (*outside-temp below
  35*).

A starter made here is an ordinary schedule or watch. It is on Samay's
or Prahari's page, changed or paused there like any other, and starts
the routine the way theirs always did (`vidhi start --by samay:ID`).
Nothing here makes one the person couldn't make on those pages. Remove
reaches only a starter of this routine: the house's nightly tests
schedule, asked to be removed through *cold-night*, is refused (*no
samay 3e02c5cd starts cold-night*).

`vidhi starts [NAME] [--at WHEN | --on READING --when TEST | --rm
BY:ID]` does the same from the terminal, and the agent's
`list_routines` now says, for each routine, its blanks with their kinds
and what starts it (*Samay: at 20:00 (active)*, or *only when asked*).

## The owner has one name

What is installed on Vidhi's page is filed under `local`. The owner's
agent through Dvara asks as Dvara's name for them, `owner`. Until now
the two were different people here: the owner's chat saw none of the
routines on the page, and a schedule it made for one failed with
*owner has no routine cold-night*.

**DVARA'S NAME FOR THE OWNER IS READ AS `local`** (`routines.person`):
in the agent's tools, in `vidhi start` and every `--as`, so the owner's
chat lists, runs and fills the page's routines, and a schedule or a
watch filed under `owner` starts them. The name is `$VIDHI_DVARA_ACTOR`,
or what `vidhi serve` wrote in `serve.json`, which Samay's, Prahari's
and Dvara's containers all read from the folder they share. Someone
else in the house keeps their own name and their own routines.

A starter made on the page is filed under that name too (`--as=owner`),
so a watch can sense the owner's readings, which are kept under it.

## Live receipt

A scratch Samay, Prahari and Vidhi (their own folders, never the
house's), the cold-night warning installed:

```
$ vidhi starts cold-night --at "at 20:00"
made samay 0a0d1da6: every day at 20:00 -- next: Thu 12 Nov 20:00, Fri 13 Nov 20:00, Sat 14 Nov 20:00 (America/New_York)
$ vidhi starts cold-night --on outside-temp --when "below 35"
made prahari 5bfbc4e7: senses indriya 5af6261e; tells you when the outside temperature in °F is below 35 (once each time it becomes true)
$ vidhi starts cold-night
cold-night:
  samay:0a0d1da6  active  Samay: at 20:00
  prahari:5bfbc4e7  active  Prahari: Cold night warning: outside-temp below 35
$ prahari indriya push outside-temp 31
5bfbc4e7  Wed 11 Nov 22:07  fired      31  then: routine
              why: The outside temperature in °F is 31, so it is below 35, and it did not last time
$ vidhi runs
c1f14a14  2026-11-12T03:07:19+00:00  cold-night         queued   0/4 steps  by prahari:5bfbc4e7
```

On the page, after that run: the boxes read *✓ 31*, *✓ yes*, *…
waiting*. *Try this step* on the check gave *yes — 31 is below 35*; on
*Ask me first* it gave *Would say: It's 31 now, below 35. Send "It's
going to be a cold night: cover the plants and bring the cat in."? —
not sent*. The card's number blank read *Cold means below (°F)*. A
schedule typed as *whenever* came back *Samay didn't make it: cannot
read 'whenever'; start with every, at, once or cron*.

## Not here

* **A starter changed from Vidhi's card.** Remove and make a new one, or
  change it on Samay's or Prahari's page, which already do it in place.
* **A tried step kept.** A try is gone when the canvas closes; a run is
  what keeps.
