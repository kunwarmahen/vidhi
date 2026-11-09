"""The marketplace: anyone publishes, a reviewer signs, an installer checks.

BIAS: against a routine becoming installable without a trusted person's
signature on its exact bytes -- a server that lists what nobody signed, a
signature carried over to a changed routine, a reviewer the installer
never trusted, a rejection by someone who isn't a reviewer. These use the
real ``ssh-keygen``, with keys made for the test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vidhi import catalog, market, routines
from vidhi.http import Api, VidhiServer
from vidhi.runner import Runner

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None,
                                reason="needs ssh-keygen")

ROUTINE = 'name = "hello"\ntitle = "Hello"\nversion = "1"\n' \
          '[[steps]]\nid = "n"\nnotify = "hello"\n'


def _key(folder: Path, name: str) -> tuple[Path, str]:
    key = folder / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
                   check=True)
    return key, (folder / f"{name}.pub").read_text().strip()


@pytest.fixture
def keys(tmp_path):
    folder = tmp_path / "keys"
    folder.mkdir()
    return {name: _key(folder, name) for name in ("rita", "mallory")}


@pytest.fixture
def shop(tmp_path, keys):
    root = tmp_path / "market"
    found = market.Market(root)
    market.trust(root, "rita", keys["rita"][1])
    return found


@pytest.fixture
def served(shop, store, roads, state):
    server = VidhiServer(Api(store, Runner(store, roads), state), "t" * 24, port=0, shop=shop)
    server.start()
    yield server.url.rstrip("/")
    server.stop()


def test_a_signature_verifies_against_the_trusted_list(tmp_path, keys):
    allowed = market.trust(tmp_path, "rita", keys["rita"][1])
    signature = market.sign(ROUTINE, keys["rita"][0])
    assert market.verify(ROUTINE, signature, allowed) == "rita"


def test_a_changed_routine_does_not_carry_its_signature(tmp_path, keys):
    allowed = market.trust(tmp_path, "rita", keys["rita"][1])
    signature = market.sign(ROUTINE, keys["rita"][0])
    with pytest.raises(market.MarketError, match="does not match"):
        market.verify(ROUTINE.replace("hello", "send money"), signature, allowed)


def test_a_signature_by_someone_not_trusted_is_refused(tmp_path, keys):
    allowed = market.trust(tmp_path, "rita", keys["rita"][1])
    signature = market.sign(ROUTINE, keys["mallory"][0])
    with pytest.raises(market.MarketError, match="nobody on the trusted reviewers"):
        market.verify(ROUTINE, signature, allowed)


def test_anyone_may_publish_and_nothing_published_is_listed(served):
    said = market.publish(served, ROUTINE, "pat")
    assert said["status"] == "waiting for review"
    assert market.index(served) == []
    assert [q["name"] for q in market.queue(served)] == ["hello"]
    notes = market.show(served, said["id"])["notes"]
    assert any("no model" in n for n in notes)


def test_a_routine_that_does_not_read_is_not_even_queued(served):
    with pytest.raises(market.MarketError):
        market.publish(served, 'name = "x"\n', "pat")


def test_a_reviewer_signs_here_and_it_is_listed(served, keys):
    queued = market.publish(served, ROUTINE, "pat")
    said = market.approve(served, queued["id"], keys["rita"][0], "rita")
    assert said["status"] == "listed" and said["reviewer"] == "rita"
    assert [i["name"] for i in market.index(served)] == ["hello"]
    assert market.queue(served) == []


def test_someone_who_is_not_a_reviewer_cannot_approve(served, keys):
    queued = market.publish(served, ROUTINE, "pat")
    with pytest.raises(market.MarketError, match="nobody on the trusted reviewers"):
        market.approve(served, queued["id"], keys["mallory"][0], "mallory")
    assert market.index(served) == []


def test_a_reviewers_name_must_match_the_key_that_signed(served, keys, shop):
    market.trust(shop.root, "mallory", keys["mallory"][1])
    queued = market.publish(served, ROUTINE, "pat")
    with pytest.raises(market.MarketError, match="signed by mallory, not rita"):
        market.approve(served, queued["id"], keys["mallory"][0], "rita")


def test_a_rejection_is_signed_too(served, keys):
    queued = market.publish(served, ROUTINE, "pat")
    with pytest.raises(market.MarketError):
        market.reject(served, queued["id"], "spam", keys["mallory"][0], "mallory")
    said = market.reject(served, queued["id"], "it calls a shop", keys["rita"][0], "rita")
    assert said["status"] == "rejected" and market.queue(served) == []


def test_fetching_checks_against_the_installers_own_trust_not_the_servers(
        served, keys, state, store):
    queued = market.publish(served, ROUTINE, "pat")
    market.approve(served, queued["id"], keys["rita"][0], "rita")
    with pytest.raises(market.MarketError, match="no reviewers are trusted yet"):
        market.get(served, "hello", state)
    market.trust(state, "rita", keys["rita"][1])
    path, signer = market.get(served, "hello", state)
    assert signer == "rita"
    found = catalog.template(state, "hello")
    assert found.source == "market" and found.signed_by == "rita"
    assert market.check_installable(state, path, found.text) == "rita"


def test_a_fetched_routine_changed_on_disk_is_not_installable(served, keys, state):
    queued = market.publish(served, ROUTINE, "pat")
    market.approve(served, queued["id"], keys["rita"][0], "rita")
    market.trust(state, "rita", keys["rita"][1])
    path, _ = market.get(served, "hello", state)
    path.write_text(ROUTINE.replace('notify = "hello"', 'notify = "changed"'))
    found = catalog.template(state, "hello")
    with pytest.raises(market.MarketError, match="does not match"):
        market.check_installable(state, path, found.text)


def test_the_same_version_is_not_listed_twice(served, keys):
    first = market.publish(served, ROUTINE, "pat")
    market.approve(served, first["id"], keys["rita"][0], "rita")
    second = market.publish(served, ROUTINE, "pat")
    with pytest.raises(market.MarketError, match="already listed"):
        market.approve(served, second["id"], keys["rita"][0], "rita")


def test_installing_a_market_template_through_the_page_checks_the_signature(
        served, keys, state, store):
    import json
    import urllib.request

    queued = market.publish(served, ROUTINE, "pat")
    market.approve(served, queued["id"], keys["rita"][0], "rita")
    market.trust(state, "rita", keys["rita"][1])
    market.get(served, "hello", state)
    request = urllib.request.Request(
        served + "/api/routines", data=json.dumps({"template": "hello"}).encode(),
        method="POST", headers={"Authorization": "Bearer " + "t" * 24,
                                "Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        card = json.loads(response.read())
    assert card["source"] == "market" and card["signed_by"] == "rita"
    assert routines.find(store, "local", "hello").signed_by == "rita"


def test_one_address_may_not_flood_the_queue(shop):
    for n in range(market.PUBLISH_PER_HOUR):
        shop.publish(ROUTINE.replace('"1"', f'"{n}"'), "pat", address="1.2.3.4")
    with pytest.raises(market.MarketError, match="an hour"):
        shop.publish(ROUTINE, "pat", address="1.2.3.4")
    assert shop.publish(ROUTINE, "pat", address="5.6.7.8")["status"]

