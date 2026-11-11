# 08 — A review taken back

A reviewer signs a routine in [04](04-a-marketplace-with-review.md), and
from then on it is installable by everyone who trusts them. Reviewers
are people: one will sign something and then find it mails a stranger
every hour. Until now a signature couldn't be taken back; a newer
version could only sit beside it. This note is how a reviewer takes a
review back, and how each Vidhi that trusted them acts on it without
trusting the marketplace to tell the truth.

Continues [04](04-a-marketplace-with-review.md) and
[06](06-a-marketplace-others-can-reach.md).

## The reviewer signs the take-back

```
vidhi market revoke hello --version 1 --why "it says hello too often" --key ~/.ssh/vidhi-review --as rita
```

Vidhi fetches that version's exact text, and the reviewer's own computer
signs one line, `revoke hello 1 SHA256: it says hello too often`, in its
own namespace (`vidhi-revoke`), with the same key that signed the
review. The private key never leaves that computer, as with approving.

**ONLY WHO SIGNED IT CAN TAKE IT BACK.** The marketplace takes a
take-back only from the reviewer whose signature listed that version.
Another reviewer can disagree (publish a newer version, say why
elsewhere); they can't unsign somebody else's review. And a take-back
says why: the people whose routine stops deserve the reason.

**THE MARKETPLACE STOPS LISTING IT.** A taken-back version is gone from
`/market/index` and the page; when an older version is still signed,
that one is listed again. The signed take-back is kept at
`/market/revoked`, for everybody who fetched the version already.

## Each Vidhi checks it itself

```
vidhi market check            # every marketplace this Vidhi fetched from
```

and `vidhi serve` does the same every six hours, by itself.

**BELIEVED ONLY FROM A REVIEWER YOU TRUST.** A take-back is checked
against `~/.vidhi/reviewers`, the same list `vidhi market get` checks
reviews against. A broken-into marketplace could otherwise pause
everybody's routines with a line it wrote. A take-back signed by
somebody you never trusted, or one whose signature doesn't match its
words, is set aside and said ("set aside: hello v1: its signature is by
nobody on the trusted reviewers' list").

**THE EXACT TEXT, BY ITS HASH.** A take-back names the sha256 of the
text that was reviewed, not just a name. A routine with the same name
and one line changed isn't the one reviewed, and it isn't touched: a
person who mended a routine owns what they mended.

**WHAT IT DOES HERE.** A believed take-back is kept (`revoked` in
Vidhi's store), and then:

* every installed routine whose text it is goes to **paused**, its open
  runs are stopped, and its owner is told on their channels who took the
  review back and why;
* that text is refused by `vidhi install`, whatever road it comes by
  (a file, a template fetched earlier, the page, a chat), and a paused
  routine that is that text can't be resumed;
* `vidhi list` and Vidhi's page say it under the routine's name: *review
  taken back by rita (version 1): it says hello too often*;
* `vidhi market revoked --json` lists every take-back believed here, an
  indriya template's too: Prahari asks for it every hour and pauses a
  reading made from that exact text (Prahari's notes/11).

Mending it (`vidhi edit`, the canvas) makes another text, the person's
own, unreviewed, and theirs to resume.

A trust file written before take-backs (its reviewers allowed to sign
reviews and rejections only) is brought up to date when it is next
read: the same people, one more thing they may sign.

## The first reviewers, and going public

Who reviews is the marketplace owner's call, and each person's call
again when they trust someone. To make someone a reviewer of a
marketplace you run:

1. **They make a key of their own**, on their own computer, only for
   reviewing: `ssh-keygen -t ed25519 -C NAME -f ~/.ssh/vidhi-review`.
   The private half (`vidhi-review`) never leaves that computer.
2. **They send you the public half**, `~/.ssh/vidhi-review.pub`: one line
   starting `ssh-ed25519`. Anyone may see it.
3. **You add them**: `vidhi market reviewer NAME vidhi-review.pub --dir
   ~/.vidhi-market`. They can now approve, reject and take back.
4. **They publish the same line somewhere people already trust** (their
   GitHub profile, a page of theirs), so a person can compare it with
   the marketplace page's copy before `vidhi market trust NAME KEY`.

Putting the marketplace on the internet is
`deploy/public-market-tailscale.sh`; Sarathi's tutorial goes through it
step by step.

## Live receipt

A scratch marketplace (`vidhi market serve --port 8792`), reviewers
`rita` and `sam` with keys made for it, a person's scratch Vidhi that
trusts only `rita`:

```
$ vidhi market publish hello.toml --as pat
sent: hello version 1, id a89a1450c1b9 -- waiting for review
$ vidhi market approve a89a1450c1b9 --key keys/rita --as rita
hello v1: listed, signed by rita
$ vidhi market trust rita keys/rita.pub
$ vidhi market get hello
fetched hello, signed by rita (whom you trust); install it with: vidhi install hello
$ vidhi install hello
$ vidhi start hello
queued run 198e0c58 of hello (vidhi serve is not running: it waits for it)
$ vidhi market revoke hello --version 1 --why "it says hello too often" --key keys/sam --as sam
error: the marketplace said 400: hello version 1 was reviewed by rita; only they can take it back (you can publish a newer version, or tell people why)
$ vidhi market revoke hello --version 1 --why "it says hello too often" --key keys/rita --as rita
hello v1: review taken back by rita (it says hello too often); it is no longer listed, and each Vidhi that trusts you pauses it when it next checks
$ vidhi market list
nothing listed yet
$ vidhi market check
local: hello: paused. rita took back their review of version 1: it says hello too often (stopped 1 open run)
taken back: hello v1 by rita
$ vidhi list
1. hello  paused  Say hello -- no model
    review taken back by rita (version 1): it says hello too often
$ vidhi resume hello
error: rita took back their review of hello version 1: it says hello too often. That exact text is not installed or resumed here; mend it (vidhi edit) to make it your own, or install a newer reviewed version
$ vidhi install hello --replace
error: rita took back their review of hello version 1: ...
$ vidhi market check
no new reviews taken back
```

## Not here

* **Taking back a review on a routine somebody mended.** The hash is the
  reviewed text; a mended copy is the person's own.
* **A take-back that expires, or one taken back again.** A reviewer who
  changes their mind again reviews a new version.
* ~~**Pausing a reading made from a taken-back indriya template.**~~
  Every believed take-back is kept, a template's too; `vidhi market
  revoked --json` lists them, and Prahari's clock pauses a reading made
  from a text on that list within the hour (Prahari's notes/11).
* **Telling people who never fetched it.** They never had it; the
  marketplace stops listing it, which is enough.
