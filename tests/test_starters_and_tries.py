"""What starts a routine, a step tried alone, and the owner's one name.

BIAS: against a try that does something -- a question asked, a message
sent, a run or a row kept, a call given a grant; against a starter list
that shows someone else's schedule, or a Remove that reaches a schedule
this routine doesn't own; against the owner's chat not seeing the
routines installed on the page (Dvara's name for them is not ``local``);
and against a failed read that doesn't say which readings there are.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from vidhi import catalog, mcp, routines, starters
from vidhi.roads import Done, Dvara, Roads, Who
from vidhi.runner import Runner

FAKE = '''
import json, sys
argv = sys.argv[1:]
open(sys.argv[0] + ".log", "a").write(json.dumps(argv) + "\\n")
if argv[:1] == ["list"] and "samay" in sys.argv[0]:
    print(json.dumps([
        {"id": "s1", "owner": "owner", "prompt": "cold-night", "runner": "vidhi",
         "state": "active", "when_text": "at 20:00", "sentence": "every day at 20:00"},
        {"id": "s2", "owner": "asha", "prompt": "cold-night", "runner": "vidhi",
         "state": "active", "when_text": "at 06:00", "sentence": "asha's"},
        {"id": "s3", "owner": "local", "prompt": "the night's tests", "runner": "tests",
         "state": "active", "when_text": "at 03:00", "sentence": "tests"}]))
elif argv[:1] == ["list"]:
    print(json.dumps([{"id": "w1", "owner": "local", "routine": "cold-night",
                       "name": "Cold night: outside-temp below 35", "state": "active",
                       "sentence": "senses outside-temp"}]))
elif argv[:1] == ["add"]:
    print(json.dumps({"id": "new1", "sentence": "made"}))
elif argv[:1] == ["rm"]:
    print(json.dumps({"removed": argv[1]}))
'''


def _fakes(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    made = {}
    for name in ("samay", "prahari"):
        script = tmp_path / f"fake-{name}.py"
        script.write_text(FAKE)
        monkeypatch.setenv(f"VIDHI_{name.upper()}", f"{sys.executable} {script}")
        made[name] = script
    return made


def _log(script: Path) -> list[list[str]]:
    path = Path(str(script) + ".log")
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def cold(store):
    return routines.install(store, "local", catalog.template(Path("/nonexistent"),
                                                              "cold-night").text)


# -- the owner's one name -----------------------------------------------------------------

def test_dvaras_name_for_the_owner_is_the_computers_person(store, monkeypatch):
    monkeypatch.setenv("VIDHI_DVARA_ACTOR", "owner")
    assert routines.person(store, "owner") == "local"
    assert routines.person(store, "asha") == "asha"
    assert routines.person(store, "") == "local"


def test_the_name_is_read_from_what_serve_wrote_in_any_container(store, state):
    (state / "serve.json").write_text(json.dumps({"owner_as": "owner"}))
    assert routines.person(store, "owner") == "local"


def test_the_owners_chat_sees_and_runs_the_routines_installed_on_the_page(
        store, roads, state, cold, monkeypatch):
    monkeypatch.setenv("VIDHI_DVARA_ACTOR", "owner")
    tools = mcp.Tools(store, Runner(store, roads), state, "owner")
    listed = json.loads(tools.call("list_routines", {}))
    assert [r["name"] for r in listed] == ["cold-night"]
    run = Runner(store, roads).start("owner", "cold-night", started_by="samay:s1")
    assert run.owner == "local"


# -- a step tried alone ----------------------------------------------------------------------

def test_a_tried_check_uses_what_the_last_run_gave(store, roads, runner, cold):
    roads.answers["read:outside-temp"] = Done(True, "31", "")
    run = runner.start("local", "cold-night")
    runner.go(run.id)
    out = runner.try_step("local", cold.toml, "cold")
    assert out["ok"] and out["text"] == "yes" and out["said"] == "31 is below 35"
    assert out["from_run"] == run.id and out["missing"] == []


def test_a_tried_question_or_message_is_written_out_never_sent(store, roads, runner, cold):
    runs_before = len(store.runs(limit=100))
    asked = runner.try_step("local", cold.toml, "go", results={"temp": "31", "cold": "yes"})
    told = runner.try_step("local", cold.toml, "send")
    assert asked["text"].startswith("It's 31 now, below 35.") and "not sent" in asked["said"]
    assert "cover the plants" in told["text"] and "not sent" in told["said"]
    assert roads.told == [] and store.questions("local") == []
    assert len(store.runs(limit=100)) == runs_before


def test_a_tried_call_has_no_grant_and_an_ask_with_tools_is_not_tried(store, roads, runner):
    text = ('name = "tt"\ntitle = "T"\n[[steps]]\nid = "c"\ncall = "web_fetch"\n'
            'args = { url = "https://a.example" }\n[[steps]]\nid = "a"\nask = "go"\n'
            'tools = true\n')
    runner.try_step("local", text, "c")
    assert [c for c in roads.calls if c[0] == "web_fetch"][0][-1] is False
    out = runner.try_step("local", text, "a")
    assert not out["ok"] and "only by a real run" in out["said"]
    assert not [c for c in roads.calls if c[0] == "ask"]


def test_a_read_that_finds_no_reading_names_the_ones_there_are(tmp_path):
    script = tmp_path / "p.py"
    script.write_text('import json, sys\nargv = sys.argv[1:]\n'
                      'if argv[:2] == ["indriya", "list"]:\n'
                      '    print(json.dumps([{"name": "outside-temp"}]))\n'
                      'else:\n    print("error: no indriya outdoor", file=sys.stderr)\n'
                      '    sys.exit(2)\n')
    roads = Roads(tmp_path / "work", prahari=[sys.executable, str(script)])
    done = roads.read(Who("local"), "outdoor")
    assert not done.ok and "yours are: outside-temp" in done.detail


# -- what starts it ---------------------------------------------------------------------------

def test_the_starters_listed_are_this_persons_and_this_routines_only(
        store, state, cold, tmp_path, monkeypatch):
    _fakes(tmp_path, monkeypatch)
    monkeypatch.setenv("VIDHI_DVARA_ACTOR", "owner")
    found = starters.starts(store, "local", "cold-night", state / "work")
    assert [(x["by"], x["id"]) for x in found] == [("samay", "s1"), ("prahari", "w1")]


def test_a_starter_is_made_by_samays_and_prahari_own_commands(
        store, state, cold, tmp_path, monkeypatch):
    fakes = _fakes(tmp_path, monkeypatch)
    monkeypatch.setenv("VIDHI_DVARA_ACTOR", "owner")
    starters.add_schedule(store, "local", "cold-night", "at 20:00", state / "work")
    starters.add_watch(store, "local", "cold-night", "outside-temp", "below 35",
                       state / "work")
    said = _log(fakes["samay"])[-1]
    assert said[:6] == ["add", "cold-night", "--runner", "vidhi", "--when", "at 20:00"]
    assert "--as=owner" in said
    watched = _log(fakes["prahari"])[-1]
    assert watched[watched.index("--sense") + 1] == "outside-temp"
    assert watched[watched.index("--routine") + 1] == "cold-night"
    assert watched[1].startswith("Cold night warning: ") and "--as=owner" in watched


def test_a_remove_reaches_only_this_routines_own_starter(
        store, state, cold, tmp_path, monkeypatch):
    fakes = _fakes(tmp_path, monkeypatch)
    with pytest.raises(starters.StarterError):
        starters.remove(store, "local", "cold-night", "samay", "s3", state / "work")
    assert not [a for a in _log(fakes["samay"]) if a[:1] == ["rm"]]
    starters.remove(store, "local", "cold-night", "prahari", "w1", state / "work")
    assert _log(fakes["prahari"])[-1] == ["rm", "w1", "--json"]


def test_a_time_that_says_nothing_is_refused_before_samay_is_asked(store, state, cold):
    with pytest.raises(starters.StarterError, match="say a time"):
        starters.add_schedule(store, "local", "cold-night", " ", state / "work")


def test_the_agent_hears_what_starts_each_routine_and_its_blanks(
        store, roads, state, cold, tmp_path, monkeypatch):
    _fakes(tmp_path, monkeypatch)
    listed = json.loads(mcp.Tools(store, Runner(store, roads), state, "local")
                        .call("list_routines", {}))[0]
    assert "Prahari: Cold night: outside-temp below 35 (active)" in listed["started_by"]
    assert {"name": "reading", "kind": "indriya",
            "label": "Which reading (one Prahari keeps)"} in listed["blanks"]


def test_with_no_samay_or_prahari_nothing_starts_it_and_nothing_breaks(store, state, cold):
    assert starters.starts(store, "local", "cold-night", state / "work") == []


def test_an_account_blank_is_offered_only_the_computers_own_setu(tmp_path):
    dvara = Dvara(url="http://d.example", token="t", actor="owner")
    roads = Roads(tmp_path / "work", dvara=dvara)
    assert roads.accounts("asha") == []
