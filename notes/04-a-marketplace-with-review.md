# 04 — A marketplace, with review

A good routine is worth sharing: someone's morning brief, someone's
price-then-plan for a shop. Sharing one is also handing somebody steps
that will run with their accounts. A list anyone could add to and anyone
could install from would be exactly the wrong thing.

Continues [01](01-a-routine-drawn-once.md).

## Anyone publishes; nothing published is installable

`vidhi market publish FILE --to URL --as NAME` sends a routine. The
marketplace reads it (it must parse: no loops, no unknown keys) and
keeps it in a **queue**, where nobody can install it. At most ten an hour
from one address.

**A REVIEWER READS IT.** `vidhi market show ID` prints the routine and
review notes worked out from it: how many steps, what a run costs, every
address it reaches, every call built from an earlier step, any step that
runs the agent with its tools, every line of `touches()`. A routine is
only steps from [01](01-a-routine-drawn-once.md), with no code, so that
is all of it.

**APPROVING IS SIGNING, ON THE REVIEWER'S COMPUTER.** `vidhi market
approve ID --key ~/.ssh/id_ed25519 --as rita` fetches the queued text,
signs its exact bytes with `ssh-keygen -Y sign` (namespace
`vidhi-routine`), and sends only the signature. The private key never
leaves that computer. The marketplace lists the routine only if the
signature verifies against its own reviewers file (OpenSSH's
allowed_signers form) as the reviewer named. A rejection is signed too
(namespace `vidhi-reject`), so nobody but a reviewer can empty the queue.

**THE INSTALLER CHECKS AGAIN, AGAINST THEIR OWN LIST.** `vidhi market get
NAME` verifies the signature against `~/.vidhi/reviewers`: the reviewers
*this person* trusts (`vidhi market trust NAME KEY`), not the
marketplace's. A marketplace that was broken into can stop listing a
routine; it can't make one installable here. `vidhi install` checks once
more, so a fetched file changed on disk afterwards is refused.

**A MENDED ROUTINE IS NO LONGER SIGNED.** Changed on the canvas, an
installed routine from a marketplace is yours, and says so.

**THE SAME VERSION IS LISTED ONCE.** A new one needs a new `version`, so
what was reviewed stays what is installed under that number.

No new dependency: `ssh-keygen` is OpenSSH's, already on any Linux
computer (Sarathi's image adds `openssh-client`).

## Live receipt

A scratch marketplace (`vidhi market serve --dir … --port 8788`), a key
made for the test, and `coat-check` from [02](02-a-run-that-asks.md):

```
$ vidhi market reviewer rita rita.pub --dir shop
$ vidhi market publish coat-check.toml --to $U --as pat --note "asks before it says what to wear"
sent: coat-check version 1, id f2a97ef1ce8d -- waiting for review
$ vidhi market list --from $U
nothing listed yet
$ vidhi market show f2a97ef1ce8d --from $U
review notes:
  - 5 steps; 1 model ask per run
  - reaches: api.open-meteo.com
  - touches: Ask me: asks you "It's [temp]°F outside. Want a line on what to wear?" …
$ vidhi market approve f2a97ef1ce8d --from $U --key keys/rita --as rita
coat-check v1: listed, signed by rita

$ vidhi --state fresh market get coat-check --from $U
error: no reviewers are trusted yet (…/fresh/reviewers): vidhi market trust NAME 'ssh-ed25519 AAAA...'
$ vidhi --state fresh market trust rita keys/rita.pub
$ vidhi --state fresh market get coat-check --from $U
fetched coat-check, signed by rita (whom you trust); install it with: vidhi install coat-check
$ vidhi --state fresh install coat-check
installed coat-check for local: Coat check (1 model ask per run)

$ sed -i 's#api.open-meteo.com#evil.example#' fresh/market/coat-check.toml
$ vidhi --state fresh install coat-check --replace
error: its signature does not match it: it was changed after it was signed, or signed for something else
```

The tests run the same with real keys made per test: a signature by
someone not trusted, a reviewer's name that isn't the key's, a rejection
by someone who isn't a reviewer, a flood from one address
(`tests/test_market.py`).

## Not here

* **A public address for the marketplace.** It runs where it's started;
  putting it on the internet is the same choice as Prahari's public
  inlet.
* **Revoking a signature.** Removing a reviewer from your own list stops
  new installs signed by them; routines already installed stay.
