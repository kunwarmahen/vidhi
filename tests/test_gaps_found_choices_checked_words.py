"""A repeat whose wait grows, choices a step found, typed answers checked.

BIAS: each loosens something a routine said on its face, so the tests
are written against the ways that goes wrong: a gap list that slips
under the five-minute floor or waits the wrong length on a pass; found
lines that become a branch nobody could read beforehand, an empty list
that leaves the person a question with no buttons, a button that cuts the
answer short; a typed number or time that is let through wrong, or a
wrong answer that closes the question instead of asking again.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from vidhi import routine as rt
from vidhi import routines
from vidhi.roads import Done
from vidhi.runner import RunError, Runner
from vidhi.store import now_utc

GROWING = """
name = "warm"
[[steps]]
id = "temp"
read = "guestroom-temp"
[[steps]]
id = "warm"
check = "{{temp}}"
above = 68
[[steps]]
id = "again"
repeat = ["temp", "warm"]
until = "warm"
times = 4
every = ["15m", "30m", "1h"]
"""

FLIGHTS = """
name = "flights"
[[steps]]
id = "found"
call = "web_fetch"
args = { url = "https://example.com/flights" }
[[steps]]
id = "pick"
person = "Which flight?"
choices_from = "found"
within = "1h"
[[steps]]
id = "book"
notify = "Booking {{pick}}"
"""

NUMBER = """
name = "setpoint"
[[steps]]
id = "temp"
person = "What temperature?"
typed = "number"
between = [60, 80]
[[steps]]
id = "hot"
check = "{{temp}}"
above = 72
[[steps]]
id = "said"
notify = "Set to {{temp}}"
"""

TIME = """
name = "wake"
[[steps]]
id = "when"
person = "Wake you at?"
typed = "time"
[[steps]]
id = "said"
notify = "Alarm {{when}}"
"""


def _clocked(store, roads):
    now = [now_utc()]
    return Runner(store, roads, now=lambda: now[0]), now


def _rows(store, run_id):
    return {s.step_id: s for s in store.steps(run_id)}


# -- a growing gap --------------------------------------------------------------------


def test_every_gap_in_the_list_keeps_the_five_minute_floor():
    with pytest.raises(rt.RoutineError, match="5 minutes at the least"):
        rt.parse(GROWING.replace('"30m"', '"2m"'))
    with pytest.raises(rt.RoutineError, match="one length"):
        rt.parse(GROWING.replace('["15m", "30m", "1h"]', "[]"))


def test_a_growing_gap_says_every_wait_before_anybody_says_yes():
    lines = rt.touches(rt.parse(GROWING))
    assert ("again: does temp, warm again, waiting 15m, then 30m, then 1h between passes "
            "(1h after that), until warm says yes, 4 times at the most") in lines


def test_a_growing_gap_written_back_reads_the_same():
    routine = rt.parse(GROWING)
    assert rt.parse(rt.dump(routine)).as_dict() == routine.as_dict()


def test_each_pass_waits_its_own_gap_and_the_last_is_kept(store, roads):
    runner, now = _clocked(store, roads)
    routines.install(store, "local", GROWING)
    roads.answers["read:guestroom-temp"] = Done(True, "60")
    run = runner.go(runner.start("local", "warm").id)
    for gap in (15, 30, 60):
        now[0] += timedelta(minutes=gap - 1)
        assert runner.wake() == [], f"woke before {gap}m"
        now[0] += timedelta(minutes=1, seconds=1)
        assert runner.wake() == [run.id]
        run = runner.go(run.id)
    assert run.state == "done"
    again = _rows(store, run.id)["again"]
    assert again.result == "no" and again.passes == 4


# -- choices a step found --------------------------------------------------------------


def test_nothing_can_branch_on_a_choice_found_while_it_runs():
    text = FLIGHTS + '[[steps]]\nid = "x"\nnotify = "y"\nonly_if = "pick is AA 101"\n'
    with pytest.raises(rt.RoutineError, match="found when it runs"):
        rt.parse(text)
    with pytest.raises(rt.RoutineError, match="no step by that name"):
        rt.parse(FLIGHTS.replace('choices_from = "found"', 'choices_from = "nope"'))
    with pytest.raises(rt.RoutineError, match="not choices and choices_from"):
        rt.parse(FLIGHTS.replace('within = "1h"', 'within = "1h"\nchoices = ["a", "b"]'))


def test_a_found_choice_waits_for_the_step_that_finds_it():
    routine = rt.parse(FLIGHTS)
    assert routine.order() == [["found"], ["pick"], ["book"]]
    assert ("pick: asks you \"Which flight?\", choosing one of what found found (its first "
            "3 lines), and waits up to 1h (no answer is no choice)") in rt.touches(routine)


def test_found_lines_become_buttons_and_the_answer_is_the_whole_line(store, runner, roads):
    routines.install(store, "local", FLIGHTS)
    long = "AA 101 Raleigh 07:05 to Boston 09:20, $212, one stop in Philadelphia"
    roads.answers["web_fetch"] = Done(True, f"- {long}\n\n- DL 7 08:00 $199\nDL 7 08:00 $199\n"
                                            "UA 3 10:00 $250\nB6 9 noon $180\n")
    run = runner.go(runner.start("local", "flights").id)
    question = store.questions()[0]
    assert question.kind == "choice"
    assert question.choices == [long, "DL 7 08:00 $199", "UA 3 10:00 $250"]
    labels = [t["label"] for t in roads.told[0][2]]
    assert labels[0] == long[:rt.CHOICE_LEN - 1] + "…" and labels[1] == "DL 7 08:00 $199"
    assert "found 4; the first 3 were offered" in _rows(store, run.id)["pick"].detail
    runner.answer(question.code, "1", via="telegram")
    runner.go(run.id)
    assert roads.told[-1][1] == f"Booking {long}"


def test_nothing_found_means_nobody_is_asked(store, runner, roads):
    routines.install(store, "local", FLIGHTS)
    roads.answers["web_fetch"] = Done(True, "\n  \n")
    run = runner.go(runner.start("local", "flights").id)
    assert run.state == "done" and store.questions("local", open_only=False) == []
    pick = _rows(store, run.id)["pick"]
    assert pick.result == "" and "found nothing to choose from" in pick.why


# -- typed answers, checked --------------------------------------------------------------


def test_a_range_is_only_for_a_typed_number():
    with pytest.raises(rt.RoutineError, match="between is for typed"):
        rt.parse(TIME.replace('typed = "time"', 'typed = "time"\nbetween = [1, 2]'))
    with pytest.raises(rt.RoutineError, match="low first"):
        rt.parse(NUMBER.replace("[60, 80]", "[80, 60]"))
    with pytest.raises(rt.RoutineError, match="typed is true"):
        rt.parse(TIME.replace('"time"', '"date"'))


def test_a_typed_number_still_cannot_be_branched_on_but_a_check_can_test_it():
    with pytest.raises(rt.RoutineError, match="not branch on them"):
        rt.parse(NUMBER + '[[steps]]\nid = "x"\nnotify = "y"\nonly_if = "temp"\n')
    assert rt.parse(NUMBER).step("hot").uses() == {"temp"}


def test_a_wrong_number_is_refused_and_the_question_stays_open(store, runner, roads):
    routines.install(store, "local", NUMBER)
    run = runner.go(runner.start("local", "setpoint").id)
    question = store.questions()[0]
    text = roads.told[0][1]
    assert f"Answer with a number from 60 to 80: /routines say {question.code} 70" in text
    with pytest.raises(RunError, match="a number from 60 to 80, not 'warm'; "
                                       f"{question.code} is still waiting"):
        runner.answer(question.code, "warm", via="telegram")
    with pytest.raises(RunError, match="95 is not"):
        runner.answer(question.code, "95", via="telegram")
    assert store.question(question.code).answer == ""
    answered, _ = runner.answer(question.code, "74°", via="telegram")
    assert answered.answer == "74"
    run = runner.go(run.id)
    rows = _rows(store, run.id)
    assert rows["hot"].result == "yes" and roads.told[-1][1] == "Set to 74"


@pytest.mark.parametrize("typed, kept", [("7:30", "07:30"), ("07:30", "07:30"),
                                         ("7:30pm", "19:30"), ("7 pm", "19:00"),
                                         ("12am", "00:00"), ("23:05", "23:05")])
def test_a_typed_time_is_kept_as_a_clock_time(typed, kept):
    assert rt.typed_answer("time", [], typed) == kept


@pytest.mark.parametrize("typed", ["7", "25:00", "tomorrow", "13pm", "7:61"])
def test_a_typed_time_that_is_not_one_is_refused(typed):
    with pytest.raises(rt.RoutineError, match="a time of day"):
        rt.typed_answer("time", [], typed)


def test_a_typed_time_goes_on_as_the_clock_time(store, runner, roads):
    routines.install(store, "local", TIME)
    run = runner.go(runner.start("local", "wake").id)
    code = store.questions()[0].code
    assert store.questions()[0].expects == "time"
    runner.answer(code, "6:45 am", via="page")
    runner.go(run.id)
    assert roads.told[-1][1] == "Alarm 06:45"
