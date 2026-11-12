"""The roads, with a stand-in ``yantra`` and ``prahari`` that print what the
real ones print.

BIAS: against a step doing more than the person agreed to -- a call
without its word-for-word grant, a call built from an earlier step
carrying a grant it was never shown, a no-tools question that still has
tools, Prahari asked as the wrong person.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from vidhi.roads import Dvara, Roads, Who, grant_for

FAKE = '''
import json, sys
argv = sys.argv[1:]
open(sys.argv[0] + ".log", "a").write(json.dumps(argv) + "\\n")
if "--call" in argv:
    tool = argv[argv.index("--call") + 1]
    print(json.dumps({"format": "yantra.call.v1", "ok": True, "text": "called " + tool}))
elif "--prompt" in argv:
    print(json.dumps({"format": "yantra.run.v1", "ok": True, "text": "  written  ",
                      "cost_usd": 0.002}))
elif argv[:2] == ["indriya", "list"]:
    print(json.dumps([{"name": "outside-temp", "thing": "the outside temperature",
                       "value": 58.5, "age": "4 min ago", "state": "active"},
                      {"name": "porch", "value": None}]))
elif argv[:2] == ["indriya", "get"]:
    print(json.dumps({"name": argv[2], "value": 38.5, "age": "4 min ago"}))
'''


def _fake(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake.py"
    script.write_text(FAKE)
    return [sys.executable, str(script)]


def _log(tmp_path: Path) -> list[list[str]]:
    return [json.loads(line) for line in (tmp_path / "fake.py.log").read_text().splitlines()]


def test_a_call_carries_the_grant_for_exactly_its_arguments(tmp_path):
    roads = Roads(tmp_path / "work", yantra=_fake(tmp_path))
    done = roads.call(Who("local", run_id="r1"), "web_fetch",
                      {"url": "https://a.example/x"}, granted=True)
    assert done.ok and done.text == "called web_fetch"
    argv = _log(tmp_path)[0]
    assert argv[argv.index("--allow-tools") + 1] == 'web_fetch(url=https://a.example/x)'


def test_a_call_built_from_an_earlier_step_gets_no_grant(tmp_path):
    roads = Roads(tmp_path / "work", yantra=_fake(tmp_path))
    roads.call(Who("local", run_id="r1"), "web_fetch", {"url": "x"}, granted=False)
    assert "--allow-tools" not in _log(tmp_path)[0]


def test_a_question_with_no_tools_has_none(tmp_path):
    roads = Roads(tmp_path / "work", yantra=_fake(tmp_path))
    done = roads.ask(Who("local", run_id="r1"), "write it", tools=False)
    assert done.ok and done.text == "written" and done.cost_usd == 0.002
    argv = _log(tmp_path)[0]
    for flag in ("--no-setu", "--no-prahari", "--no-skills"):
        assert flag in argv
    assert argv[argv.index("--memory") + 1] == "off"


def test_a_reading_is_asked_for_as_the_person(tmp_path):
    roads = Roads(tmp_path / "work", prahari=_fake(tmp_path))
    done = roads.read(Who("asha"), "outside-temp", "5m")
    assert done.ok and done.text == "38.5" and done.detail == "read 4 min ago"
    assert _log(tmp_path)[0][-2:] == ["--as=asha", "--max-age=5m"]


def test_a_reading_at_the_computer_is_asked_as_dvaras_name_for_it(tmp_path):
    # the owner's readings are kept under Dvara's name for them ("owner"),
    # which Prahari in Vidhi's container is not told: say it with --as
    dvara = Dvara(url="http://dvara.example", token="t", actor="owner")
    roads = Roads(tmp_path / "work", dvara=dvara, prahari=_fake(tmp_path))
    assert roads.read(Who("local"), "outside-temp").ok
    assert _log(tmp_path)[0][-1] == "--as=owner"


def test_a_reading_at_the_computer_with_no_dvara_names_nobody(tmp_path):
    roads = Roads(tmp_path / "work", prahari=_fake(tmp_path))
    assert roads.read(Who("local"), "outside-temp").ok
    assert not any(a.startswith("--as") for a in _log(tmp_path)[0])


def test_the_readings_offered_are_the_owners_own(tmp_path):
    dvara = Dvara(url="http://dvara.example", token="t", actor="owner")
    roads = Roads(tmp_path / "work", dvara=dvara, prahari=_fake(tmp_path))
    found = roads.readings("local")
    assert [r["name"] for r in found] == ["outside-temp", "porch"]
    assert found[0]["value"] == "58.5" and found[1]["value"] == ""
    assert _log(tmp_path)[0] == ["indriya", "list", "--json", "--as=owner"]


def test_with_no_prahari_no_readings_are_offered(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDHI_PRAHARI", str(tmp_path / "nothing-here"))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert Roads(tmp_path / "work").readings("local") == []


def test_with_no_dvara_a_message_is_kept_on_the_run(tmp_path):
    done = Roads(tmp_path / "work").tell(Who("local"), "hi")
    assert done.ok and done.text == "nowhere" and "no Dvara" in done.detail


def test_the_dvara_road_without_a_dvara_says_so(tmp_path):
    done = Roads(tmp_path / "work").call(Who("asha", runner="dvara", agent="a"), "t", {},
                                         granted=True)
    assert not done.ok and "has no Dvara" in done.detail


def test_a_grant_quotes_what_needs_quoting():
    assert grant_for("t", {"q": "a b", "n": 3}) == 't(q="a b", n=3)'
