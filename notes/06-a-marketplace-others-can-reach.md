# 06 — A marketplace others can reach

The marketplace in [04](04-a-marketplace-with-review.md) ran where it was
started. A marketplace only one computer can reach shares nothing. This
note is what changed so it can stand on the internet: what it serves,
who it counts, what it shows, and what it now carries besides routines.

Continues [04](04-a-marketplace-with-review.md).

## Alone, on its own port

**ONLY `/market/`.** `vidhi market serve` answers `/market/...` and
nothing else: none of anybody's routines, runs, questions or API. `/`
sends a browser to `/market/`. So it can be put on the internet by
itself, the way Prahari's inlet is: `deploy/public-market-tailscale.sh`
checks it answers on 127.0.0.1, signs the computer in to Tailscale and
serves it through Funnel on port 10000 (443 is a Setu catalog's, 8443
Prahari's inlet). No domain, no router port, Tailscale's certificate.
Where it keeps things: `~/.vidhi-market` (`$VIDHI_MARKET_DIR`), and
`vidhi keeps` names that folder for a house backup when there is one.
Its reviewers, its queue and its signed listings can't be made again.

With Sarathi: `market_port = 8787` under `[vidhi]` runs it (its own
container, `sarathi-vidhi-market`, published on 127.0.0.1 only), and
`market_url` is the address the house's Vidhi fetches from. With a
`market_port` and no `market_url`, the house fetches from its own.

## Who a publish is counted against

At most ten publishes an hour from one address. Behind Funnel every
request comes from 127.0.0.1, so one person would use up everyone's ten.
**THE FORWARDED ADDRESS IS TAKEN ONLY FROM THIS COMPUTER.** A request
whose peer is 127.0.0.1 (the proxy) is counted against the first address
in its `X-Forwarded-For`. A request straight from outside is counted
against its own peer, whatever header it sends, so nobody can spend
somebody else's ten by naming them.

**A FULL QUEUE STOPS, IT DOESN'T FILL A DISK.** A hundred things waiting
for review is the most. Past that, publishing says to try later.

## A page for somebody who found the address

`GET /market/` is a plain page: what is listed (title, kind, who
published it, who reviewed it, what it touches, the one command that
fetches it), how to fetch one, and how to publish. The reviewers are
there with their public keys (also `GET /market/reviewers`, and `vidhi
market reviewers`).

**THE KEYS ARE SHOWN, NOT TRUSTED FROM HERE.** A person trusts a
reviewer with `vidhi market trust NAME KEY`, their own act, after
comparing the key with what the reviewer published somewhere they
already trust. A key trusted because the marketplace showed it would let
a broken-into marketplace sign for itself. The page says so, beside the
keys.

Vidhi's own page has a **Marketplace** section once `VIDHI_MARKET` is
set: what it lists, the reviewers this person trusts, and **Get it**
(`POST /api/market/get`), which fetches the file and checks its
signature against that list. A routine then appears under **Ready to
install**.

## Readings travel the same road

A file that starts `kind = "indriya"` is an **indriya template**: a
reading for Prahari with blanks (Prahari's notes/11). It is published,
queued, reviewed, signed and checked exactly like a routine; one name is
one kind of thing, so a routine can't be listed under a reading's name.
Its review notes say what a reviewer needs: the one tool it calls, how
often, every address it reaches, and in capitals a tool that isn't a
plain read.

**THE SHAPE IS CHECKED HERE; THE MEANING IN PRAHARI.** Vidhi knows
nothing of Prahari's code, so the marketplace checks that a template is
one call (or a pushed value), a pick, how often (5 minutes at the
least), and blanks that are numbers or words, and refuses any other key.
Prahari reads it fully when it's installed.

**FETCHED APART.** `vidhi market get` keeps an indriya template under
`~/.vidhi/market/indriyas/`, never with the routines: it isn't one, and
Vidhi's own templates list doesn't show it. `prahari indriya install
NAME --from-market` asks `vidhi market get NAME --json`, so the signature
is checked in one place, against the person's own list, and the reading
it makes says who signed it.

## Live receipt

A scratch marketplace (`vidhi market serve --port 8771`), a reviewer
`rita` with a key made for it, and Prahari's `coin-price` template copied
as `eth-price`:

```
$ vidhi market publish eth-price.toml --to $VIDHI_MARKET --as pat --note "ether in USD"
sent: eth-price version 1, id edd7e5cb533e -- waiting for review
$ vidhi market show edd7e5cb533e
eth-price v1 by pat: ether in USD
review notes:
  - an indriya template (a reading for Prahari); no model
  - reaches: api.coinbase.com
  - touches: calls web_fetch every 15m, with no model: {"url": "https://api.coinbase.com/v2/prices/{{inputs.coin}}-{{inputs.currency}}/spot"}
  - touches: with your own accounts, as you
$ vidhi market approve edd7e5cb533e --key rita --as rita
eth-price v1: listed, signed by rita
$ vidhi market reviewers
rita: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMAAVM1OTBo2kBNOm66DO6gOq1HeRe43TthUVqUkprto
```

Installing it in a scratch Prahari, before and after trusting `rita`:

```
$ prahari indriya install eth-price --from-market
error: no reviewers are trusted yet (.../vidhi/reviewers): vidhi market trust NAME 'ssh-ed25519 AAAA...'
$ vidhi market trust rita rita.pub
$ prahari indriya install eth-price --from-market
added indriya eth-price from eth-price (signed by rita): reads the coin's price every 15 minutes: looks at api.coinbase.com/v2/prices (with web_fetch)
$ prahari indriya get eth-price --max-age 5m
15101def  active  eth-price: 2,121.89 (just now)
          check: web_fetch {"url": "https://api.coinbase.com/v2/prices/ETH-USD/spot"}
          made Mon 9 Nov 15:35 (by cli: template eth-price v1, signed by rita), for local
```

`curl /market/` gave the page, with *Ether's price · indriya · no model ·
by pat, reviewed by rita*, what it calls, and `prahari indriya install
eth-price --from-market`.

Not run: Funnel itself. The script is the same steps as Prahari's inlet
script, which has run on this house, but this one hasn't been run.

## Not here

* ~~**Revoking a listing.**~~ The reviewer who signed it signs a
  take-back; each Vidhi that trusts them pauses that exact text:
  [08](08-a-review-taken-back.md).
* **Ratings, downloads, comments.** The page lists; it doesn't rank.
* **Reviewers chosen by the marketplace for you.** You trust whom you
  trust.
