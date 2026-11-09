"""Vidhi's page, its JSON API, and (with ``--market``) a marketplace --
served by ``vidhi serve``.

    GET    /api/status
    GET    /api/routines                       every installed routine, each a card
    GET    /api/routines/OWNER/NAME            one, with its TOML
    POST   /api/routines      {toml | routine | template, inputs, owner, runner, agent,
                              replace}
    PUT    /api/routines/OWNER/NAME   {toml | routine}   save it (the canvas)
    POST   /api/routines/OWNER/NAME/inputs     {inputs}
    POST   /api/routines/OWNER/NAME/run        {inputs}: queued, 202 at once
    POST   /api/routines/OWNER/NAME/pause | /resume
    DELETE /api/routines/OWNER/NAME
    POST   /api/check         {toml | routine}: read and checked, nothing kept (the canvas
                              asks on every change: what's wrong, the waves, the
                              words of what it touches)
    GET    /api/templates                      what can be installed
    GET    /api/templates/NAME                 one, to read before installing: its exact
                                               text, its steps, what to look at closer
    POST   /api/templates     {toml}           keep one as this computer's own
    GET    /api/runs?owner=&routine=&limit=    newest first
    GET    /api/runs/ID                        one, each step and what it gave
    POST   /api/runs/ID/stop
    GET    /api/questions                      what runs are waiting to hear
    POST   /api/questions/CODE   {answer}      yes or no, a choice, or a few words
    GET    /api/market                         what the marketplace (VIDHI_MARKET) lists
    POST   /api/market/get       {name}        fetch one, its signature checked
                                               against the reviewers trusted here

    GET/POST /market/...        the marketplace's own (market.py), no token:
                                its rules are signatures, not a page's token

A TOKEN, ALWAYS, as Prahari's page has: any web page you visit can send
a request to 127.0.0.1, so every ``/api`` call carries ``Authorization:
Bearer``. The page is a static file with no data in it; its link carries
the token after ``#``, which a browser never sends anywhere.

THE PAGE IS THE COMPUTER'S. Like Prahari's page, it shows every person's
routines and runs, each with whose it is: it is opened at the computer,
by its owner. A person in the house sees their own through Dvara
(``/routines``) and their agent.

THE CANVAS SENDS ITS OWN SHAPE. What the canvas draws is the routine as
a table (``routine``: the TOML's own keys); the server writes it as TOML
(``routine.dump``) and reads it back, so a routine drawn and a routine
typed are kept, checked and signed the same way.

Standard library only.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from vidhi import catalog, market, routines
from vidhi import routine as rt
from vidhi.runner import RunError, Runner, describe, installed_card
from vidhi.status import report
from vidhi.store import Store

MAX_BODY = 128 * 1024
DEFAULT_PORT = 8786
LOCAL = "local"


def serve_token(state: Path) -> str:
    """``$VIDHI_TOKEN``, or the one kept in the state folder (made once)."""
    configured = os.environ.get("VIDHI_TOKEN", "").strip()
    if configured:
        if len(configured) < 16:
            raise ValueError("VIDHI_TOKEN must be at least 16 characters")
        return configured
    path = Path(state) / "serve.token"
    try:
        kept = path.read_text().strip()
        if len(kept) >= 16:
            return kept
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(token + "\n")
    return token


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Api:
    """What each endpoint does, apart from HTTP."""

    def __init__(self, store: Store, runner: Runner, state: Path) -> None:
        self.store = store
        self.runner = runner
        self.state = Path(state)

    def handle(self, method: str, path: str, query: dict, body: dict) -> tuple[int, dict]:
        parts = [p for p in path.split("/") if p][1:]
        try:
            return self._route(method, parts, query, body)
        except (rt.RoutineError, RunError, market.MarketError) as exc:
            message = str(exc)
            raise ApiError(404 if " has no " in message or message.startswith("no ")
                           else 400, message) from None

    def _route(self, method, parts, query, body) -> tuple[int, dict | list]:
        if parts == ["status"] and method == "GET":
            return 200, report(self.state, self.store)
        if parts == ["check"] and method == "POST":
            return 200, check(self._text(body))
        if parts == ["templates"]:
            if method == "GET":
                found, broken = catalog.templates(self.state)
                return 200, {"templates": [t.card() for t in found], "broken": broken}
            if method == "POST":
                path = catalog.save_mine(self.state, self._text(body))
                return 201, {"saved": str(path)}
        if len(parts) == 2 and parts[0] == "templates" and method == "GET":
            return 200, look_inside(self.state, parts[1])
        if parts == ["routines"]:
            if method == "GET":
                return 200, [installed_card(r) for r in self.store.routines()]
            if method == "POST":
                return 201, installed_card(self._install(body))
        if len(parts) >= 3 and parts[0] == "routines":
            owner, name, rest = parts[1], parts[2], parts[3:]
            return self._one(method, owner, name, rest, body)
        if parts == ["runs"] and method == "GET":
            runs = self.store.runs(owner=_q(query, "owner"), routine=_q(query, "routine"),
                                   limit=int(_q(query, "limit") or 30))
            return 200, [describe(self.store, r) for r in runs]
        if len(parts) >= 2 and parts[0] == "runs":
            run = self.store.run(parts[1])
            if run is None:
                raise ApiError(404, f"no run {parts[1]}")
            if len(parts) == 2 and method == "GET":
                return 200, describe(self.store, run)
            if parts[2:] == ["stop"] and method == "POST":
                return 200, describe(self.store, self.runner.stop(run.id))
        if parts == ["questions"] and method == "GET":
            return 200, [q.as_dict() for q in self.store.questions()]
        if parts == ["market"] and method == "GET":
            base = os.environ.get("VIDHI_MARKET", "").strip()
            if not base:
                return 200, {"market": None, "listed": [], "trusted": _trusted(self.state),
                             "detail": "no marketplace set: VIDHI_MARKET (Sarathi's "
                                       "[vidhi] market)"}
            return 200, {"market": base, "listed": market.index(base),
                         "trusted": _trusted(self.state)}
        if parts == ["market", "get"] and method == "POST":
            name = str(body.get("name") or "").strip()
            path, signer = market.get("", name, self.state)
            kind = market.kind_of(path.read_text())
            return 200, {"name": path.stem, "kind": kind, "signed_by": signer,
                         "next": (f"prahari indriya install {path.stem} --from-market"
                                  if kind == "indriya" else "install it from Ready "
                                  "routines")}
        if len(parts) == 2 and parts[0] == "questions" and method == "POST":
            question, run = self.runner.answer(parts[1], str(body.get("answer") or ""),
                                               via="Vidhi's page")
            return 200, {"question": question.as_dict(),
                         "run": describe(self.store, run) if run else None}
        raise ApiError(404, "not found")

    @staticmethod
    def _text(body: dict) -> str:
        """The routine a request carries: its TOML, or the canvas's own
        shape (``routine``), written as TOML here so both are kept alike."""
        drawn = body.get("routine")
        if isinstance(drawn, dict):
            return rt.dump(drawn)
        return str(body.get("toml") or "")

    def _install(self, body: dict):
        owner = str(body.get("owner") or LOCAL)
        text = self._text(body)
        source, signed_by = "local", ""
        if body.get("template"):
            found = catalog.template(self.state, str(body["template"]))
            text, source = found.text, found.source
            if source == "market":
                signed_by = market.check_installable(self.state, Path(found.path), text)
                source = "market"
            elif source == "vidhi":
                source = "catalog"
        return routines.install(
            self.store, owner, text, inputs=body.get("inputs") or {},
            runner=str(body.get("runner") or "direct"), agent=str(body.get("agent") or ""),
            source=source, signed_by=signed_by, replace=bool(body.get("replace")))

    def _one(self, method, owner, name, rest, body) -> tuple[int, dict]:
        if not rest:
            if method == "GET":
                card = installed_card(routines.find(self.store, owner, name))
                return 200, card
            if method == "PUT":
                saved, said = routines.save(self.store, owner, name, self._text(body))
                return 200, {**installed_card(saved), "said": said}
            if method == "DELETE":
                gone = routines.remove(self.store, owner, name)
                return 200, {"removed": gone.name}
        verb = rest[0] if len(rest) == 1 else ""
        if method == "POST" and verb == "run":
            run = self.runner.start(owner, name, body.get("inputs") or {},
                                    started_by=str(body.get("by") or "page"))
            return 202, describe(self.store, run)
        if method == "POST" and verb == "inputs":
            return 200, installed_card(routines.set_inputs(self.store, owner, name,
                                                           body.get("inputs") or {}))
        if method == "POST" and verb in ("pause", "resume"):
            changed = getattr(routines, verb)(self.store, owner, name)
            return 200, installed_card(changed)
        raise ApiError(404, "not found")


def look_inside(state: Path, name: str) -> dict:
    """A template as it would be installed, for reading before a yes: its
    exact text, its steps as drawn, and what deserves a second look. Nothing
    is installed or run. A marketplace template's signature is checked
    again now, against the reviewers this person trusts."""
    found = catalog.template(state, name)
    routine = found.routine
    signed = ""
    if found.source == "market":
        try:
            signed = "signed by " + market.check_installable(state, Path(found.path),
                                                             found.text)
        except market.MarketError as exc:
            signed = f"NOT INSTALLABLE: {exc}"
    return {"name": routine.name, "toml": found.text, "routine": routine.as_dict(),
            "source": found.source, "signed": signed, "waves": routine.order(),
            "cost": rt.cost(routine), "touches": rt.touches(routine),
            "look_closer": market.look_closer(routine), "reaches": market.reaches(routine),
            "accounts": rt.needs_accounts(routine), "steps": len(routine.steps)}


def check(text: str) -> dict:
    """A routine read and checked, for the canvas: what's wrong, or what it is."""
    try:
        routine = rt.parse(text)
    except rt.RoutineError as exc:
        return {"ok": False, "error": str(exc), "toml": text}
    return {"ok": True, "routine": routine.as_dict(), "toml": text, "waves": routine.order(),
            "touches": rt.touches(routine), "cost": rt.cost(routine),
            "kinds": {s.id: s.kind for s in routine.steps},
            "waits": {s.id: sorted(s.waits_for()) for s in routine.steps}}


def _trusted(state: Path) -> list[str]:
    """The reviewers this person trusts, by name."""
    path = market.trusted_file(state)
    lines = path.read_text().splitlines() if path.is_file() else []
    return [ln.split()[0] for ln in lines if ln.strip()]


def market_peer(handler) -> str:
    """Who a publish is counted against: the peer -- or, ONLY for a request
    that came from this computer (Tailscale Funnel's proxy), the first
    address in its X-Forwarded-For. A request straight from the internet
    can't name somebody else's address."""
    peer = handler.client_address[0]
    if peer in ("127.0.0.1", "::1"):
        forwarded = (handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return peer


def market_answer(handler, shop: market.Market, method: str, path: str,
                  body: dict) -> tuple[int, bytes, str]:
    """A ``/market/`` request: the page, or the JSON route."""
    if method == "GET" and path in ("/market", "/market/"):
        base = os.environ.get("VIDHI_MARKET_PUBLIC_URL", "").strip() or \
            f"http://{handler.headers.get('Host') or 'localhost'}"
        return 200, market.page(shop, base.rstrip("/")), "text/html; charset=utf-8"
    status, data = market_route(shop, method, path, body, market_peer(handler))
    return status, json.dumps(data).encode(), "application/json"


def _q(query: dict, key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None


def page() -> bytes:
    return files("vidhi").joinpath("static/index.html").read_bytes()


def favicon() -> bytes:
    return files("vidhi").joinpath("static/favicon.svg").read_bytes()


def public_address(raw: str | None) -> str | None:
    raw = (raw if raw is not None else os.environ.get("VIDHI_PUBLIC_URL", "")).strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"the page's public address must look like http://host:port/ "
                         f"-- got {raw!r}")
    return raw.rstrip("/") + "/"


class VidhiServer:
    def __init__(self, api: Api, token: str, *, host: str = "127.0.0.1",
                 port: int = DEFAULT_PORT, public_url: str | None = None,
                 shop: market.Market | None = None) -> None:
        self.api = api
        self.token = token
        self.shop = shop
        self.public_url = public_address(public_url)
        self.httpd = ThreadingHTTPServer((host, port), _handler(self))
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self.public_url:
            return self.public_url
        host, port = self.httpd.server_address[:2]
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{port}/"

    @property
    def page_url(self) -> str:
        return f"{self.url}#token={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        name="vidhi-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join()


def market_route(shop: market.Market, method: str, path: str, body: dict,
                 address: str) -> tuple[int, dict | list]:
    parts = [p for p in path.split("/") if p][1:]
    try:
        if parts == ["index"] and method == "GET":
            return 200, shop.index()
        if parts == ["reviewers"] and method == "GET":
            return 200, shop.reviewers()
        if len(parts) == 2 and parts[0] == "routines" and method == "GET":
            return 200, shop.listed(parts[1])
        if parts == ["publish"] and method == "POST":
            return 202, shop.publish(str(body.get("toml") or ""),
                                     str(body.get("publisher") or ""),
                                     str(body.get("note") or ""), address=address)
        if parts == ["queue"] and method == "GET":
            return 200, shop.queue()
        if len(parts) == 2 and parts[0] == "queue" and method == "GET":
            return 200, shop.queued(parts[1])
        if len(parts) == 2 and parts[0] == "review" and method == "POST":
            return 200, shop.review(parts[1], str(body.get("decision") or ""),
                                    str(body.get("reviewer") or ""),
                                    str(body.get("signature") or ""),
                                    str(body.get("why") or ""))
    except (market.MarketError, rt.RoutineError) as exc:
        message = str(exc)
        return (404 if message.startswith("no ") else 400), {"detail": message}
    return 404, {"detail": "not found"}


def _handler(server: VidhiServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "vidhi"

        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _body(self) -> dict | None:
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BODY:
                self._json(413, {"detail": "request too large"})
                return None
            raw = self.rfile.read(size) if size else b""
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"detail": "the body is not JSON"})
                return None
            if not isinstance(body, dict):
                self._json(400, {"detail": "the body is a JSON object"})
                return None
            return body

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(200, page(), "text/html; charset=utf-8")
            if method == "GET" and url.path == "/favicon.svg":
                return self._send(200, favicon(), "image/svg+xml")
            if url.path == "/market" or url.path.startswith("/market/"):
                if server.shop is None:
                    return self._json(404, {"detail": "no marketplace here"})
                body = self._body() if method == "POST" else {}
                if body is None:
                    return None
                return self._send(*market_answer(self, server.shop, method, url.path,
                                                 body))
            if not url.path.startswith("/api/"):
                return self._json(404, {"detail": "not found"})
            offered = self.headers.get("Authorization", "")
            offered = offered[7:].strip() if offered.startswith("Bearer ") else ""
            if not offered or not hmac.compare_digest(offered.encode(),
                                                      server.token.encode()):
                return self._json(401, {"detail": "missing or wrong token"})
            body = self._body() if method in ("POST", "PUT") else {}
            if body is None:
                return None
            try:
                status, data = server.api.handle(method, url.path, parse_qs(url.query),
                                                 body)
            except ApiError as exc:
                return self._json(exc.status, {"detail": exc.detail})
            except Exception as exc:
                return self._json(500, {"detail": f"{type(exc).__name__}: {exc}"})
            self._json(status, data)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler
