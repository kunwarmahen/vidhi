# 07 — A growing wait, a found choice, a checked answer

Three things [05](05-a-repeat-a-join-and-other-answers.md) left out, each
because it loosened something a routine said on its face. Each is in
now, written so a reviewer still reads what it will do before it runs.

Continues [05](05-a-repeat-a-join-and-other-answers.md).

## A repeat whose wait grows

"Look again in 15 minutes, then 30, then every hour" was one `every`,
the same each pass. Now `every` can be a list, one wait a pass:

```toml
[[steps]]
id = "again"
repeat = ["temp", "warm"]
until = "warm"
times = 4
every = ["15m", "30m", "1h"]
```

**EVERY WAIT IS WRITTEN, AND EVERY WAIT KEEPS THE FLOOR.** The list is
the whole schedule: there is no "double it each time", which would read
as one number and run as many. Each wait in it is 5 minutes at the least
and 7 days at the most, like a single `every`; the list is 20 long at
most. When the passes outrun the list, the last wait is kept. What the
reviewer reads (`touches`):

```
again: does temp, warm again, waiting 15m, then 30m, then 1h between passes (1h after that), until warm says yes, 4 times at the most
```

On the canvas: *Every*, with the waits separated by commas.

## Choices a step found

"Which of these three flights?" can't be written as `choices`: the
flights are what a step finds when the routine runs. `choices_from`
names that step:

```toml
[[steps]]
id = "ideas"
ask = "Suggest three quick weeknight dinners. One per line, just the dish and how long it takes, nothing else."

[[steps]]
id = "pick"
person = "Which one tonight?"
choices_from = "ideas"
```

The step's lines are the choices: blank lines dropped, a leading `-` or
`*` taken off, the same line once, the first three. Each is a button,
cut to 24 letters on the button; **the answer is the whole line**, so
`{{pick}}` in a later step is *Black bean quesadillas with salsa – 15
min*, not the button's first words. When the step found more than
three, the run says so on the question's row ("found 4; the first 3
were offered").

**NOTHING CAN BRANCH ON A FOUND CHOICE.** `only_if = "pick is ..."` is
refused when the routine is read: nobody can read the choices before it
runs, so nobody could check what a branch on them would do. A later step
can use the pick; a `check` can test it (`contains = "chicken"`), and
that check is written where a reviewer sees it.

**WHAT WAS FOUND IS STILL TEXT FROM OUTSIDE.** The person picks among
lines a tool or the model wrote, so the person is the filter. After
that, the pick is a step's result like any other: fenced in an `ask`,
and a call built from it gets no grant, so it runs only if its tool
only reads.

**NOTHING FOUND, NOBODY ASKED.** A step that found no lines leaves the
question unasked and gives nothing ("ideas found nothing to choose
from, so nobody was asked"). A question with no buttons would wait a
day for an answer nobody could give.

On the canvas: *I answer with* → *one of the lines a step found*, and
the step's id.

## A typed answer that is checked

`typed = true` takes any few words. Now it can say what the words must
be:

```toml
[[steps]]
id = "people"
person = "How many people are eating?"
typed = "number"
between = [1, 8]
```

* `typed = "number"`: a number, `74`, `74°`, `-3.5`. With `between =
  [low, high]` (both included), one in that range. Kept as the number
  alone (`74° ` is `74`).
* `typed = "time"`: a time of day, `7:30`, `07:30`, `7:30pm`, `7 pm`.
  Kept as `07:30` / `19:30`, so a later step reads one shape.

**A WRONG ANSWER ASKS AGAIN; IT DOESN'T CLOSE THE QUESTION.** The answer
is refused with what it must be, on whatever road it came (a chat, the
page, the terminal), and the question stays open with its code: "the
answer is a number from 1 to 8, not 'about four'; Y9VVFR is still
waiting for it". The question's own message says the same up front,
with an example from inside the range: *Answer with a number from 1 to
8: /routines say Y9VVFR 4*. Vidhi's page puts it in the box (*a number
from 1 to 8*).

**STILL NOT A BRANCH.** A checked number is still typed: `only_if` on it
is refused, as on any typed answer. A `check` after it (`above = 72`) is
the branch, written where it can be read. And silence is still no
answer: nobody typed, so later steps get nothing.

On the canvas: *I answer with* → *a typed number* (and *From, to*) or *a
typed time of day*.

## Live receipt

A scratch Vidhi, the real `yantra` with `qwen3.8:latest` (`VIDHI_YANTRA=
"yantra --provider ollama --model qwen3.8:latest"`), and the `dinner`
routine above with the `people` step:

```
$ vidhi install dinner.toml
installed dinner for local: Dinner tonight (1 model ask per run)
  ideas: asks the model, with no tools
  pick: asks you "Which one tonight?", choosing one of what ideas found (its first 3 lines), and waits up to 1d (no answer is no choice)
  people: asks you "How many people are eating?", as a number from 1 to 8, and waits up to 1d (no answer is no words)
  said: tells you, on your channels
$ vidhi run dinner
run 68e73a29 of dinner: waiting -- waiting for your answer (pick), your answer (people)
  done     ideas
           Garlic butter shrimp with pasta – 20 min Sheet-pan chicken thighs with roasted potatoes – 40 min Black bean quesadillas with salsa – 15 min
  waiting  pick  (asked you (J7WLV8))
  waiting  people  (asked you (Y9VVFR))
  asks you: Which one tonight?
    vidhi answer J7WLV8 1 (Garlic butter shrimp with pasta – 20 min) | 2 (Sheet-pan chicken thighs with roasted potatoes – 40 min) | 3 (Black bean quesadillas with salsa – 15 min)
$ vidhi answer Y9VVFR "about four"
error: the answer is a number from 1 to 8, not 'about four'; Y9VVFR is still waiting for it
$ vidhi answer Y9VVFR 12
error: the answer is a number from 1 to 8; 12 is not; Y9VVFR is still waiting for it
$ vidhi answer Y9VVFR 3
Y9VVFR: 3
$ vidhi answer J7WLV8 3
J7WLV8: Black bean quesadillas with salsa – 15 min
run 68e73a29 of dinner: done
  done     pick  (you said "Black bean quesadillas with salsa – 15 min" (the terminal))
  done     people  (you said "3" (the terminal))
  done     said  (this Vidhi has no Dvara to tell anyone through (VIDHI_DVARA_URL); kept on the run)
```

The model's three lines became the three choices, whole; the two wrong
numbers left the question open. (The run shows a result on one line;
the model wrote three.) The run found one thing to fix: `vidhi
questions` still said *vidhi answer Y9VVFR your words* for a number. It
now says *vidhi answer Y9VVFR 4 (a number from 1 to 8)*.

`cooling`: a check that never says yes, `repeat` three times with `every
= ["5m", "10m"]`, under `vidhi serve`:

```
$ vidhi install cooling.toml
installed cooling for local: Wait for the oven to cool (no model)
  again: does cool again, waiting 5m, then 10m between passes (10m after that), until cool says yes, 3 times at the most
$ vidhi start cooling          # vidhi serve picks it up
...
$ vidhi steps da4fd143
run da4fd143 of cooling: done
  done     cool  (it does not say '99:99')
           no
  done     again  (cool still said no after 3 passes (it does not say '99:99'))
           pass 1 (21:29): cool said no -- it does not say '99:99'
           pass 2 (21:34): cool said no -- it does not say '99:99'
           pass 3 (21:44): cool said no -- it does not say '99:99'
           no
```

Five minutes, then ten, from the clock in `vidhi serve`, with nothing
held open between.

## Not here

* **A choice among more than three found lines.** Three buttons fit a
  phone's notification; a longer list is a reason to narrow the step
  that finds it.
* **A typed date, or an amount of money with its currency.** A number
  and a time of day cover the thermostat and the alarm; a date would
  need a calendar's rules, and a `check` can test words.
* **A wait that depends on what a pass found** ("look sooner when it's
  close"). The waits are written, so they can be read.
