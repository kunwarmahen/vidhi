"""A reviewer takes back a review; each Vidhi that trusts them stops it.

BIAS: against a take-back that is easier to forge than the review was --
one by a reviewer who didn't sign that version, one a broken-into server
made up, one an installer believes from a key it never trusted -- and
against one that is too loose: a routine with the same name but other
words paused, or the taken-back text still installable or resumable by
some other road. These use the real ``ssh-keygen``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vidhi import market, routines
from vidhi.http import Api, VidhiServer
from vidhi import routine as rt
from vidhi.runner import Runner, installed_card

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None,
                                reason="needs ssh-keygen")

V1 = 'name = "hello"\ntitle = "Hello"\nversion = "1"\n' \
     '[[steps]]\nid = "n"\nnotify = "hello"\n'
V2 = V1.replace('version = "1"', 'version = "2"').replace('notify = "hello"',
                                                         'notify = "hello again"')


def _key(folder: Path, name: str) -> tuple[Path, str]:
    key = folder / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
                   check=True)
    return key, (folder / f"{name}.pub").read_text().strip()


@pytest.fixture
def keys(tmp_path):
    folder = tmp_path / "keys"
    folder.mkdir()
    return {name: _key(folder, name) for name in ("rita", "sam", "mallory")}


@pytest.fixture
def shop(tmp_path, keys):
    root = tmp_path / "market"
    found = market.Market(root)
    market.trust(root, "rita", keys["rita"][1])
    market.trust(root, "sam", keys["sam"][1])
    return found


@pytest.fixture
def served(shop, store, roads, state):
    server = VidhiServer(Api(store, Runner(store, roads), state), "t" * 24, port=0, shop=shop)
    server.start()
    yield server.url.rstrip("/")
    server.stop()


def _listed(served, keys, text, reviewer="rita"):
    queued = market.publish(served, text, "pat")
    return market.approve(served, queued["id"], keys[reviewer][0], reviewer)


def test_only_the_reviewer_who_signed_a_version_can_take_it_back(served, keys):
    _listed(served, keys, V1)
    with pytest.raises(market.MarketError, match="only they can take it back"):
        market.revoke(served, "hello", "1", "I disagree", keys["sam"][0], "sam")
    with pytest.raises(market.MarketError, match="nobody on the trusted reviewers"):
        market.revoke(served, "hello", "1", "spam", keys["mallory"][0], "mallory")
    with pytest.raises(market.MarketError, match="says why"):
        market.revoke(served, "hello", "1", "  ", keys["rita"][0], "rita")
    said = market.revoke(served, "hello", "1", "it mails too often", keys["rita"][0], "rita")
    assert said["status"] == "taken back" and said["reviewer"] == "rita"
    with pytest.raises(market.MarketError, match="already taken back"):
        market.revoke(served, "hello", "1", "again", keys["rita"][0], "rita")


def test_a_taken_back_version_is_not_listed_and_an_older_one_comes_back(served, keys):
    _listed(served, keys, V1)
    _listed(served, keys, V2)
    assert [i["version"] for i in market.index(served)] == ["2"]
    market.revoke(served, "hello", "2", "v2 was wrong", keys["rita"][0], "rita")
    assert [i["version"] for i in market.index(served)] == ["1"]
    market.revoke(served, "hello", "1", "so was v1", keys["rita"][0], "rita")
    assert market.index(served) == []
    with pytest.raises(market.MarketError, match="no routine hello is listed"):
        market.get(served, "hello", Path("/nonexistent"))


def test_the_installer_pauses_the_exact_text_and_tells_its_owner(
        served, keys, state, store, roads):
    _listed(served, keys, V1)
    market.trust(state, "rita", keys["rita"][1])
    market.get(served, "hello", state)
    routines.install(store, "ana", V1, source="market", signed_by="rita")
    # the same name in other words is somebody's own routine, not the reviewed one
    routines.install(store, "ben", V1.replace('notify = "hello"', 'notify = "hi"'))
    runner = Runner(store, roads)
    open_run = runner.start("ana", "hello")
    market.revoke(served, "hello", "1", "it mails too often", keys["rita"][0], "rita")

    done, ignored = market.check(state, store, runner)
    assert ignored == []
    assert done == ["ana: hello: paused. rita took back their review of version 1: it mails "
                    "too often (stopped 1 open run)", "taken back: hello v1 by rita"]
    assert store.routine("ana", "hello").state == "paused"
    assert store.routine("ben", "hello").state == "active"
    assert store.run(open_run.id).state == "stopped"
    assert roads.told[-1][0] == "ana" and "rita took back their review" in roads.told[-1][1]
    card = installed_card(store.routine("ana", "hello"), store)
    assert card["taken_back"]["why"] == "it mails too often"
    # said once: a second check finds nothing new
    assert market.check(state, store, runner) == ([], [])


def test_the_taken_back_text_cannot_come_back_by_any_road(served, keys, state, store, roads):
    _listed(served, keys, V1)
    market.trust(state, "rita", keys["rita"][1])
    routines.install(store, "ana", V1)
    market.revoke(served, "hello", "1", "bad", keys["rita"][0], "rita")
    market.check(state, store, Runner(store, roads), served)
    with pytest.raises(rt.RoutineError, match="rita took back their review"):
        routines.resume(store, "ana", "hello")
    with pytest.raises(rt.RoutineError, match="not installed or resumed here"):
        routines.install(store, "ben", V1)
    # mended, it is another text: the person's own
    mine = V1.replace('notify = "hello"', 'notify = "hi"')
    mended, _ = routines.save(store, "ana", "hello", mine)
    assert routines.resume(store, "ana", mended.name).state == "active"


def test_a_take_back_by_a_reviewer_this_person_never_trusted_is_set_aside(
        served, keys, state, store, roads):
    _listed(served, keys, V1, reviewer="sam")
    market.trust(state, "rita", keys["rita"][1])          # rita, not sam
    routines.install(store, "ana", V1)
    market.revoke(served, "hello", "1", "bad", keys["sam"][0], "sam")
    done, ignored = market.check(state, store, Runner(store, roads), served)
    assert done == [] and "nobody on the trusted reviewers" in ignored[0]
    assert store.routine("ana", "hello").state == "active"


def test_a_take_back_a_broken_into_server_made_up_is_set_aside(
        served, keys, shop, state, store, roads):
    _listed(served, keys, V1)
    market.trust(state, "rita", keys["rita"][1])
    routines.install(store, "ana", V1)
    # the server writes a take-back nobody signed for this text
    folder = shop.root / "listed" / "hello" / "1"
    forged = market.sign("revoke hello 1 0000: bad\n", keys["rita"][0],
                         market.REVOKE_NAMESPACE)
    (folder / "revoked.json").write_text(json.dumps(
        {"name": "hello", "version": "1", "sha256": market.sha256(V1), "reviewer": "rita",
         "why": "bad", "signature": forged}))
    done, ignored = market.check(state, store, Runner(store, roads), served)
    assert done == [] and "does not match" in ignored[0]
    assert store.routine("ana", "hello").state == "active"


def test_a_trust_list_written_before_take_backs_still_believes_them(
        served, keys, state, store, roads):
    _listed(served, keys, V1)
    path = market.trust(state, "rita", keys["rita"][1])
    path.write_text(path.read_text().replace(",vidhi-revoke", ""))   # an older file
    routines.install(store, "ana", V1)
    market.revoke(served, "hello", "1", "bad", keys["rita"][0], "rita")
    done, _ = market.check(state, store, Runner(store, roads), served)
    assert store.routine("ana", "hello").state == "paused" and done
