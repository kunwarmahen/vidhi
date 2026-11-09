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



def test_a_fetched_template_read_before_install_says_its_signature(served, keys, state):
    import json
    import urllib.request

    queued = market.publish(served, ROUTINE, "pat")
    market.approve(served, queued["id"], keys["rita"][0], "rita")
    market.trust(state, "rita", keys["rita"][1])
    path, _ = market.get(served, "hello", state)

    def look():
        request = urllib.request.Request(served + "/api/templates/hello",
                                         headers={"Authorization": "Bearer " + "t" * 24})
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    assert look()["signed"] == "signed by rita"
    path.write_text(ROUTINE.replace('notify = "hello"', 'notify = "changed"'))
    assert look()["signed"].startswith("NOT INSTALLABLE")


# -- an indriya template, the public road, and the reviewers' keys ------------------
# BIAS: a marketplace on the internet, so against a reading template that
# smuggles in more than one call, an indriya template fetched as if it were
# a routine, an address that lies its way past the publish limit, a queue
# that fills a disk, and a reviewer's key trusted because the server said so.

TEMP = '''kind = "indriya"
name = "outside-temp"
title = "Outside temperature"
version = "1"
thing = "the outside temperature"
every = "15m"
[inputs.latitude]
kind = "number"
[inputs.longitude]
kind = "number"
[check]
tool = "web_fetch"
args = { url = "URL" }
pick = "json:current.temperature_2m"
'''.replace("URL", "https://api.open-meteo.com/v1/forecast?latitude={{inputs.latitude}}"
                    "&longitude={{inputs.longitude}}&current=temperature_2m")


def test_an_indriya_template_is_read_as_one_call_with_blanks():
    item = market.read_item(TEMP)
    assert item["kind"] == "indriya" and item["cost"] == "no model"
    assert item["touches"][0].startswith("calls web_fetch every 15m, with no model")
    notes = market.review_notes(TEMP)
    assert "reaches: api.open-meteo.com" in notes


def test_an_indriya_template_with_more_than_its_shape_is_refused():
    with pytest.raises(market.MarketError, match="unknown keys"):
        market.read_item(TEMP + '[[steps]]\nid = "x"\nnotify = "hi"\n')
    with pytest.raises(market.MarketError, match="not one of this template's inputs"):
        market.read_item(TEMP.replace("{{inputs.longitude}}", "{{inputs.city}}"))
    with pytest.raises(market.MarketError, match="5 minutes at the least"):
        market.read_item(TEMP.replace('every = "15m"', 'every = "1m"'))
    with pytest.raises(market.MarketError, match="kind is routine or indriya"):
        market.read_item(TEMP.replace('kind = "indriya"', 'kind = "script"'))


def test_an_indriya_template_is_fetched_apart_from_the_routines(served, keys, state):
    queued = market.publish(served, TEMP, "pat")
    market.approve(served, queued["id"], keys["rita"][0], "rita")
    assert [(i["name"], i["kind"]) for i in market.index(served)] == [("outside-temp",
                                                                       "indriya")]
    market.trust(state, "rita", keys["rita"][1])
    path, signer = market.get(served, "outside-temp", state)
    assert path.parent.name == "indriyas" and signer == "rita"
    found, _ = catalog.templates(state)
    assert "outside-temp" not in [t.routine.name for t in found]


def test_one_name_is_one_kind_of_thing(served, keys):
    first = market.publish(served, TEMP, "pat")
    market.approve(served, first["id"], keys["rita"][0], "rita")
    routine = ROUTINE.replace('name = "hello"', 'name = "outside-temp"')
    second = market.publish(served, routine, "pat")
    with pytest.raises(market.MarketError, match="already listed as an indriya"):
        market.approve(served, second["id"], keys["rita"][0], "rita")


def test_the_reviewers_keys_are_shown_with_how_to_trust_them(served, keys):
    found = market.reviewers(served)
    assert [r["name"] for r in found] == ["rita"]
    assert found[0]["key"] == " ".join(keys["rita"][1].split()[:2])
    assert found[0]["trust"].startswith("vidhi market trust rita 'ssh-ed25519 ")


def test_the_marketplace_has_a_page_for_someone_who_found_its_address(served, keys):
    import urllib.request

    queued = market.publish(served, TEMP, "pat")
    market.approve(served, queued["id"], keys["rita"][0], "rita")
    with urllib.request.urlopen(served + "/market/") as response:
        html = response.read().decode()
        assert response.headers["Content-Type"].startswith("text/html")
    assert "Outside temperature" in html and "prahari indriya install outside-temp" in html
    assert "vidhi market trust rita" in html


def test_a_forwarded_address_counts_only_from_this_computers_proxy():
    from vidhi.http import market_peer

    class Seen:
        def __init__(self, peer, forwarded):
            self.client_address = (peer, 1)
            self.headers = {"X-Forwarded-For": forwarded}
    assert market_peer(Seen("127.0.0.1", "9.9.9.9, 10.0.0.1")) == "9.9.9.9"
    assert market_peer(Seen("8.8.8.8", "9.9.9.9")) == "8.8.8.8"


def test_a_full_queue_stops_publishing_instead_of_filling_the_disk(shop, monkeypatch):
    monkeypatch.setattr(market, "MAX_QUEUE", 2)
    shop.publish(ROUTINE, "pat", address="a")
    shop.publish(ROUTINE, "pat", address="b")
    with pytest.raises(market.MarketError, match="already wait for review"):
        shop.publish(ROUTINE, "pat", address="c")
