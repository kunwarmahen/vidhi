# 02 — A run that stops and asks

*"Look up the price; if it's under my line, ask me before you make a
plan."* The asking is the routine's whole point, and a person may answer
in a minute or after lunch. A run that held a process, a connection or a
thread open for that would be lost to the first restart, and would cost
a slot for hours.

Continues [01](01-a-routine-drawn-once.md).

## A run is rows, not a process

Every step's result is written the moment it is known. A `person` step
writes its question, sends it, marks itself *waiting*, and the run stops
there: the steps that don't need the answer carry on, and then the run is
**waiting**, with the question's deadline as the time to look again.
Nothing is held open.

**AN ANSWER PUTS THE RUN BACK IN THE QUEUE.** `vidhi answer`, the page's
**Yes**, or `/routines yes CODE` in a chat writes the answer and marks the
run *queued*. Within a tick `vidhi serve` takes it and carries on from
the step that asked, with `yes` as its result.

**SILENCE IS NO.** A question nobody answered by its `within` (a day,
unless the routine says) is taken as no, and the step says so (*"nobody
answered in time, so it is no"*). A routine that was going to send
something on a yes doesn't send it because somebody was asleep.

**AN ANSWER COUNTS ONCE, AND ONLY FROM ITS PERSON.** The code is short
enough to type on a phone (six letters, no 0/O or 1/I), and it's
answered only for the person it was put to. A second answer is refused
with what the first one said.

**A RUN KEEPS ITS OWN COPY OF THE ROUTINE.** A routine mended while one of
its runs waits changes the next run, never that one.

**ONE WORKER PER RUN, AND A DEAD ONE IS NOTICED.** A run is taken by one
process (a row update only one can win), which writes a heartbeat while
it works. A run whose heartbeat is half an hour old is put back in the
queue, and the step it was half way through is done again, said on that
step (*"started again: Vidhi stopped part way through it"*).

## The question, with two buttons

The question goes to the person through Dvara's `/notify`, carrying
`taps`: words a channel draws as buttons, which a press sends as if typed.

```
Coat check asks: It's 61.8°F outside. Want a line on what to wear?

Answer: /routines yes F9SEKQ   or   /routines no F9SEKQ
(No answer by Mon 12:38 is no.)
                                        [ Yes ]  [ No ]
```

Telegram draws the two buttons side by side, and Sarathi's home page
draws them under the notice. A channel that draws none still has the
words. Dvara takes a tap only if it's a slash word, so a button can't say
anything to the agent in the person's name (Dvara's `routines.py`).

## Live receipt

`coat-check` (the README's example), `vidhi serve` running on a scratch
state with the real `yantra` and `qwen3.8:latest`. At 61.8 °F and a line
of 60 it didn't ask:

```
  done     Cold?  (61.8 is not below 60)
  skipped  Ask me  (only if cold said yes; it said no)
  skipped  What to wear  (go was skipped)
```

With `--input line=70` for that run only:

```
run dd7788e5 of coat-check: waiting -- waiting for your answer (go)
  done     Cold?  (61.8 is below 70)
  waiting  Ask me  (asked you (F9SEKQ))
```

The page showed it under **Waiting for you**, with Yes and No. **Yes** was
pressed in a browser; the clock took the run back up:

```
run dd7788e5 of coat-check: done
  done     Ask me  (you said yes (Vidhi's page))
  done     What to wear
           A long-sleeve shirt with a light jacket or hoodie should keep you
           comfortably cool without getting too warm.
  done     Tell me
```

No Dvara was running for this test, so the message stayed on the run
(*nowhere*). The buttons on Telegram and the home page are tested in
Dvara and Sarathi. On the house's own Telegram bot, from an iPhone,
Yes, a choice and typed words all answered a real run (Dvara's
notes/83); the home page and ntfy haven't been pressed for real yet.

## Not here

* ~~**An answer other than yes or no.**~~ Choices as buttons, or a few
  typed words ([05](05-a-repeat-a-join-and-other-answers.md)).
* ~~**ntfy's buttons.**~~ Drawn on the notification, each with a mark
  over the person and its exact words, never a key (Dvara's push.py and
  notes/83).
