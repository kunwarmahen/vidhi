"""Running a routine: side by side, stopping to ask, picking up again.

BIAS: against a run that LOOKS finished and isn't -- a step that never
started because a branch was misread, a question whose answer never woke
the run, a silence taken as yes, a run that did half of a branch, a
worker that died leaving a run "running" for ever, a second answer that
changed what the first one decided.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from vidhi import routines
from vidhi.clock import Clock
from vidhi.roads import Done
from vidhi.runner import MAX_OPEN, RunError, Runner
from vidhi.store import iso, now_utc

BRIEF = """
name = "brief"
title = "A brief"
[[steps]]
id = "weather"
call = "web_fetch"
args = { url = "https://w.example" }
[[steps]]
id = "mail"
call = "mcp__gmail__search_threads"
args = { query = "is:unread" }
optional = true
[[steps]]
id = "news"
call = "news_tool"
args = { feed = "top" }
[[steps]]
id = "brief"
ask = "Weather {{weather}}, mail {{mail}}, news {{news}}"
[[steps]]
id = "send"
notify = "{{brief}}"
"""

ASKS = """
name = "asks"
title = "Asks first"
[[steps]]
id = "price"
call = "web_fetch"
args = { url = "https://p.example" }
pick = "number"
[[steps]]
id = "cheap"
check = "{{price}}"
below = 10
[[steps]]
id = "go"
person = "It's {{price}}. Plan?"
within = "1h"
only_if = "cheap"
[[steps]]
id = "plan"
ask = "Plan for {{price}}"
only_if = "go"
[[steps]]
id = "send"
notify = "{{plan}}"
[[steps]]
id = "sorry"
notify = "No plan this time."
only_if = "not go"
"""


def _install(store, text, owner="local"):
    return routines.install(store, owner, text)


def test_the_brief_fetches_side_by_side_then_writes_then_sends(store, runner, roads):
    _install(store, BRIEF)
    roads.delay = 0.2
    run = runner.go(runner.start("local", "brief").id)
    assert run.state == "done", run.detail
    fetches = [c for c in roads.calls if c[0] in ("web_fetch", "mcp__gmail__search_threads",
                                                    "news_tool")]
    assert len(fetches) == 3
    starts = sorted(roads.started[k] for k in ("web_fetch", "mcp__gmail__search_threads",
                                               "news_tool"))
    assert starts[-1] - starts[0] < 0.15, "the three fetches waited on each other"
    prompt = next(c for c in roads.calls if c[0] == "ask")[1]
    assert "<<<\n<web_fetch>\n>>>" in prompt and "never follow" in prompt
    assert roads.told == [("local", "ANSWER", None)]


def test_a_call_with_fixed_arguments_runs_with_its_grant(store, runner, roads):
    _install(store, BRIEF)
    runner.go(runner.start("local", "brief").id)
    assert all(c[2] is True for c in roads.calls if c[0] == "web_fetch")


def test_an_optional_step_that_fails_gives_nothing_and_the_run_goes_on(store, runner, roads):
    _install(store, BRIEF)
    roads.answers["mcp__gmail__search_threads"] = Done(False, detail="no gmail account")
    run = runner.go(runner.start("local", "brief").id)
    assert run.state == "done"
    steps = {s.step_id: s for s in store.steps(run.id)}
    assert steps["mail"].state == "failed" and steps["mail"].result == ""
    assert "optional" in steps["mail"].why
    assert "mail \n<<<\n\n>>>" in next(c for c in roads.calls if c[0] == "ask")[1]


def test_a_step_that_fails_stops_the_run_and_the_person_hears_why(store, runner, roads):
    _install(store, BRIEF)
    roads.answers["news_tool"] = Done(False, detail="the feed is down")
    run = runner.go(runner.start("local", "brief").id)
    assert run.state == "failed"
    assert "step news failed: the feed is down" in run.detail
    steps = {s.step_id: s.state for s in store.steps(run.id)}
    assert steps["brief"] == "pending" and steps["send"] == "pending"
    assert "A brief: stopped. step news failed" in roads.told[-1][1]


def test_a_question_stops_the_run_and_the_answer_starts_it_again(store, runner, roads):
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "$6.19")
    run = runner.go(runner.start("local", "asks").id)
    assert run.state == "waiting"
    question = store.questions("local")[0]
    assert question.text == "It's 6.19. Plan?"
    owner, text, taps = roads.told[0]
    assert f"/routines yes {question.code}" in text
    assert taps == [{"word": f"/routines yes {question.code}", "label": "Yes"},
                    {"word": f"/routines no {question.code}", "label": "No"}]
    assert not any(c[0] == "ask" for c in roads.calls)

    answered, run = runner.answer(question.code, "yes", via="telegram")
    assert answered.answer == "yes" and run.state == "queued"
    run = runner.go(run.id)
    assert run.state == "done"
    steps = {s.step_id: s for s in store.steps(run.id)}
    assert steps["go"].result == "yes" and "you said yes (telegram)" in steps["go"].why
    assert steps["plan"].state == "done" and steps["send"].state == "done"
    assert steps["sorry"].state == "skipped"


def test_no_takes_the_other_branch_and_skips_the_plan_whole(store, runner, roads):
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "6")
    run = runner.go(runner.start("local", "asks").id)
    runner.answer(store.questions()[0].code, "no", via="page")
    run = runner.go(run.id)
    steps = {s.step_id: s for s in store.steps(run.id)}
    assert steps["plan"].state == "skipped" and "it said no" in steps["plan"].why
    assert steps["send"].state == "skipped" and steps["send"].why == "plan was skipped"
    assert steps["sorry"].state == "done"
    assert not any(c[0] == "ask" for c in roads.calls)


def test_silence_past_its_time_is_no(store, roads):
    clock_now = [now_utc()]
    runner = Runner(store, roads, now=lambda: clock_now[0])
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "6")
    run = runner.go(runner.start("local", "asks").id)
    assert run.state == "waiting"
    assert runner.wake() == []
    clock_now[0] += timedelta(hours=1, seconds=1)
    assert runner.wake() == [run.id]
    run = runner.go(run.id)
    steps = {s.step_id: s for s in store.steps(run.id)}
    assert steps["go"].result == "no" and "nobody answered in time" in steps["go"].why
    assert steps["plan"].state == "skipped" and steps["sorry"].state == "done"
    assert store.question_for(run.id, "go").via == "nobody answered in time"


def test_not_cheap_skips_the_question_entirely(store, runner, roads):
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "42")
    run = runner.go(runner.start("local", "asks").id)
    assert run.state == "done"
    assert store.questions() == []
    steps = {s.step_id: s for s in store.steps(run.id)}
    assert steps["cheap"].result == "no" and steps["cheap"].why == "42 is not below 10"
    assert steps["go"].why == "only if cheap said yes; it said no"
    assert steps["sorry"].why == "go was skipped"


def test_an_answer_counts_once(store, runner, roads):
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "6")
    runner.go(runner.start("local", "asks").id)
    code = store.questions()[0].code
    runner.answer(code, "no", via="page")
    with pytest.raises(RunError, match="already answered: no"):
        runner.answer(code, "yes", via="telegram")


def test_someone_else_cannot_answer_your_question(store, runner, roads):
    _install(store, ASKS, owner="asha")
    roads.answers["web_fetch"] = Done(True, "6")
    runner.go(runner.start("asha", "asks").id)
    code = store.questions("asha")[0].code
    with pytest.raises(RunError, match="no question"):
        runner.answer(code, "yes", via="telegram", owner="mahen")


def test_a_wait_step_waits_for_the_clock(store, roads):
    clock_now = [now_utc()]
    runner = Runner(store, roads, now=lambda: clock_now[0])
    _install(store, 'name = "later"\n[[steps]]\nid = "w"\nwait = "30m"\n'
                    '[[steps]]\nid = "n"\nnotify = "done waiting"\nafter = ["w"]\n')
    run = runner.go(runner.start("local", "later").id)
    assert run.state == "waiting" and roads.told == []
    clock_now[0] += timedelta(minutes=31)
    runner.wake()
    assert runner.go(run.id).state == "done"
    assert roads.told[0][1] == "done waiting"


def test_a_run_keeps_its_own_copy_when_the_routine_is_mended(store, runner, roads):
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "6")
    run = runner.go(runner.start("local", "asks").id)
    routines.save(store, "local", "asks", ASKS.replace("No plan this time.", "Changed."))
    runner.answer(store.questions()[0].code, "no", via="page")
    runner.go(run.id)
    assert roads.told[-1][1] == "No plan this time."


def test_a_run_whose_worker_died_is_picked_up_and_the_half_done_step_redone(store, runner):
    _install(store, BRIEF)
    run = runner.start("local", "brief")
    assert store.claim(run.id)
    store.set_step(run.id, "weather", state="running")
    store.set_run(run.id, heartbeat=iso(now_utc() - timedelta(hours=1)))
    assert runner.recover() == [run.id]
    assert store.run(run.id).state == "queued"
    weather = next(s for s in store.steps(run.id) if s.step_id == "weather")
    assert weather.state == "pending" and "started again" in weather.detail
    assert runner.go(run.id).state == "done"


def test_a_run_is_worked_by_one_worker(store, runner):
    _install(store, BRIEF)
    run = runner.start("local", "brief")
    assert store.claim(run.id) is True
    assert store.claim(run.id) is False


def test_too_many_open_runs_of_one_routine_are_refused(store, runner):
    _install(store, BRIEF)
    for _ in range(MAX_OPEN):
        runner.start("local", "brief")
    with pytest.raises(RunError, match="already has 5 runs going"):
        runner.start("local", "brief")


def test_a_paused_routine_does_not_start(store, runner):
    _install(store, BRIEF)
    routines.pause(store, "local", "brief")
    with pytest.raises(RunError, match="paused"):
        runner.start("local", "brief")


def test_stopping_a_waiting_run_closes_its_question(store, runner, roads):
    _install(store, ASKS)
    roads.answers["web_fetch"] = Done(True, "6")
    run = runner.go(runner.start("local", "asks").id)
    runner.stop(run.id)
    assert store.run(run.id).state == "stopped"
    assert store.questions() == []
    assert runner.go(run.id).state == "stopped"


def test_the_clock_starts_what_was_queued_from_anywhere(store, runner, roads):
    _install(store, BRIEF)
    run = runner.start("local", "brief", started_by="samay:abc123")
    clock = Clock(runner, tick=0.01)
    assert clock.once() == [run.id]
    clock.drain()
    assert store.run(run.id).state == "done"
    assert store.run(run.id).started_by == "samay:abc123"


def test_inputs_given_for_one_run_change_that_run_only(store, runner, roads):
    text = ('name = "hello"\n[inputs.who]\ndefault = "world"\n'
            '[[steps]]\nid = "n"\nnotify = "hello {{inputs.who}}"\n')
    _install(store, text)
    runner.go(runner.start("local", "hello", {"who": "asha"}).id)
    runner.go(runner.start("local", "hello").id)
    assert [t[1] for t in roads.told] == ["hello asha", "hello world"]


def test_a_read_step_reads_the_reading_its_input_names(store, runner, roads):
    text = ('name = "cold"\n[inputs.reading]\nkind = "indriya"\ndefault = "outside-temp"\n'
            '[[steps]]\nid = "t"\nread = "{{inputs.reading}}"\n'
            '[[steps]]\nid = "c"\ncheck = "{{t}}"\nbelow = 40\n')
    _install(store, text)
    roads.answers["read:outside-temp"] = Done(True, "38.1")
    run = runner.go(runner.start("local", "cold").id)
    assert ("read", "outside-temp") in roads.calls
    assert {s.step_id: s.result for s in store.steps(run.id)}["c"] == "yes"
