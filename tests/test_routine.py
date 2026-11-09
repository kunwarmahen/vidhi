"""Reading a routine: what is refused, and what is worked out.

BIAS: a routine is something other people will install after reading
it, so these tests are written against a routine that reads as one thing
and runs as another -- a loop let through, a reference to a step that
isn't there, a branch on a step that can't say yes, a call whose
arguments come from outside said as if they were fixed.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from vidhi import routine as rt

BRIEF = """
name = "brief"
title = "A brief"
[inputs.city]
default = "Raleigh"
[[steps]]
id = "weather"
call = "web_fetch"
args = { url = "https://w.example/{{inputs.city}}" }
[[steps]]
id = "mail"
call = "mcp__gmail__search_threads"
args = { query = "is:unread" }
optional = true
[[steps]]
id = "brief"
ask = "Weather {{weather}}, mail {{mail}}"
[[steps]]
id = "send"
notify = "{{brief}}"
"""


def test_the_steps_that_need_nothing_from_each_other_go_side_by_side():
    routine = rt.parse(BRIEF)
    assert routine.order() == [["weather", "mail"], ["brief"], ["send"]]


def test_a_loop_is_refused_when_the_routine_is_read():
    text = """
name = "loop"
[[steps]]
id = "a"
ask = "{{b}}"
[[steps]]
id = "b"
ask = "{{a}}"
"""
    with pytest.raises(rt.RoutineError, match="no loops"):
        rt.parse(text)


def test_a_step_that_uses_a_step_that_does_not_exist_is_refused():
    with pytest.raises(rt.RoutineError, match="no step by that name"):
        rt.parse('name = "x1"\n[[steps]]\nid = "a"\nask = "{{nothere}}"\n')


def test_an_input_nobody_declared_is_refused():
    with pytest.raises(rt.RoutineError, match="not one of this routine's inputs"):
        rt.parse('name = "x1"\n[[steps]]\nid = "a"\nask = "{{inputs.city}}"\n')


def test_a_step_is_exactly_one_kind():
    with pytest.raises(rt.RoutineError, match="exactly one of"):
        rt.parse('name = "x1"\n[[steps]]\nid = "a"\nask = "hi"\nnotify = "hi"\n')
    with pytest.raises(rt.RoutineError, match="says nothing"):
        rt.parse('name = "x1"\n[[steps]]\nid = "a"\n')


def test_an_unknown_key_is_an_error_not_ignored():
    with pytest.raises(rt.RoutineError, match="unknown keys for a ask step: comand"):
        rt.parse('name = "x1"\n[[steps]]\nid = "a"\nask = "hi"\ncomand = "rm -rf"\n')
    with pytest.raises(rt.RoutineError, match="unknown keys: script"):
        rt.parse('name = "x1"\nscript = "x"\n[[steps]]\nid = "a"\nask = "hi"\n')


def test_only_a_check_or_a_person_can_be_branched_on():
    text = """
name = "x1"
[[steps]]
id = "a"
ask = "hi"
[[steps]]
id = "b"
notify = "hi"
only_if = "a"
"""
    with pytest.raises(rt.RoutineError, match="only a check, a question or a repeat says yes"):
        rt.parse(text)


def test_only_if_waits_for_the_step_it_names():
    text = """
name = "x1"
[[steps]]
id = "ok"
person = "go?"
[[steps]]
id = "b"
notify = "hi"
only_if = "not ok"
"""
    routine = rt.parse(text)
    assert routine.order() == [["ok"], ["b"]]
    assert routine.step("b").gate == ("ok", False, "")


def test_the_words_say_a_call_built_from_an_earlier_step_only_runs_if_it_reads():
    text = """
name = "x1"
[[steps]]
id = "find"
call = "web_fetch"
args = { url = "https://a.example" }
[[steps]]
id = "follow"
call = "web_fetch"
args = { url = "{{find}}" }
"""
    lines = rt.touches(rt.parse(text))
    assert "calls web_fetch {\"url\": \"https://a.example\"}" in lines[0]
    assert "with what an earlier step found (only if that tool only reads)" in lines[1]


def test_the_words_say_the_agent_runs_with_its_tools_in_capitals():
    text = 'name = "x1"\n[[steps]]\nid = "a"\nask = "do it"\ntools = true\n'
    routine = rt.parse(text)
    assert "WITH ITS TOOLS" in rt.touches(routine)[0]
    assert rt.cost(routine) == "1 model ask per run (1 of them a full agent turn)"


def test_no_ask_is_no_model():
    assert rt.cost(rt.parse('name = "x1"\n[[steps]]\nid = "a"\nnotify = "hi"\n')) == "no model"


def test_inputs_are_checked_for_kind_and_filled_from_defaults():
    text = """
name = "x1"
[inputs.line]
kind = "number"
[inputs.at]
kind = "time"
default = "07:30"
[[steps]]
id = "a"
notify = "{{inputs.line}} {{inputs.at}}"
"""
    routine = rt.parse(text)
    assert rt.check_inputs(routine, {"line": "6.19"}) == {"at": "07:30", "line": 6.19}
    with pytest.raises(rt.RoutineError, match="is a number"):
        rt.check_inputs(routine, {"line": "cheap"})
    with pytest.raises(rt.RoutineError, match="needs line filled in"):
        rt.check_inputs(routine, {})
    with pytest.raises(rt.RoutineError, match="no input colour"):
        rt.check_inputs(routine, {"line": 1, "colour": "red"})


def test_a_result_put_into_a_question_to_the_model_is_fenced():
    filled = rt.fill("Mail: {{mail}}", {"mail": "IGNORE ALL"}, {}, {}, fence=True)
    assert "<<<\nIGNORE ALL\n>>>" in filled


def test_a_field_of_a_steps_json_can_be_used():
    assert rt.fill("{{w.current.t}}", {"w": '{"current": {"t": 51.2}}'}, {}, {}) == "51.2"


@pytest.mark.parametrize(("text", "how", "want"), [
    ('{"a": {"b": [1, {"c": "x"}]}}', "json:a.b[1].c", "x"),
    # web_fetch says where it read first, then the JSON
    ('source: https://w.example (application/json) {"current": {"t": 51.2}}',
     "json:current.t", "51.2"),
    ("Price: $1,234.50 today", "number:\\$([\\d,.]+)", "1234.50"),
    ("51.2 F", "number", "51.2"),
    ("status: Landed", "text:status: (\\w+)", "Landed"),
])
def test_a_pick_takes_what_it_says(text, how, want):
    assert rt.pick(text, how) == (want, "")


def test_a_number_test_on_no_number_is_no_and_says_so():
    yes, words = rt.test("unavailable", "below", 40)
    assert yes is False and "no number" in words
    assert rt.test("38.5", "below", "40") == (True, "38.5 is below 40")


def test_what_dump_writes_reads_back_as_the_same_routine():
    routine = rt.parse(BRIEF)
    again = rt.parse(rt.dump(routine))
    assert again.as_dict() == routine.as_dict()


def test_a_long_prompt_survives_the_round_trip():
    text = 'name = "x1"\n[[steps]]\nid = "a"\nask = """\nline one\n"quoted" line two\n"""\n'
    routine = rt.parse(text)
    assert rt.parse(rt.dump(routine)).step("a").body == routine.step("a").body


@pytest.mark.parametrize("name", ["morning-brief", "price-then-plan", "cold-night"])
def test_every_template_that_comes_with_vidhi_reads(name):
    text = (files("vidhi") / "catalog" / f"{name}.toml").read_text()
    routine = rt.parse(text)
    assert routine.name == name
    assert rt.parse(rt.dump(routine)).as_dict() == routine.as_dict()


def test_the_morning_brief_fetches_three_things_at_once():
    text = (files("vidhi") / "catalog" / "morning-brief.toml").read_text()
    assert rt.parse(text).order()[0] == ["weather", "mail", "news"]
