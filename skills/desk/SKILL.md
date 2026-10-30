---
name: desk
description: A Desk, the page that keeps its owner informed and holds what needs them (news, what waits on them, what's in progress, their notes), and desk.py, its bookkeeping script. Load it before reading or writing any of a Desk's cards or notes, and before every message to the owner if you are that Desk's keeper; it holds the 17 rules, the row fields, and the commands that check the cards, count the footer, order them by your priority, and write the patches.
---

# A Desk

A Desk is a private claude.ai page, one per project: **News**, **Waiting** (what needs the
owner, one card at a time), **In progress**, **Coming up** (Later) and the **Inbox** (their
notes being sorted). Which Desk: the project's `.claude/desk.json` (`title`, `page`, `keeper`,
`timezone`, `watch`, `look`). Only the keeper writes its cards.

This is the core: what a turn needs. **`reference.md`** (beside this file) has the rest, to read
when you need it: every command and flag, what each move drops, the rule-reload and update
checks, the rules in full with their dates, the row fields and the card markup.

## A turn: read, run, write

`S=<this skill's directory>/desk.py`; `$R` a new directory per read.

1. **Read** tasks and inbox fresh: ArtifactData `list`, `collection: "tasks"`, then `"inbox"`,
   the same `out_dir: <scratch>/rows-<HHMM>`; paste each list result as is into
   `$R/tasks/_versions.txt` and `$R/inbox/_versions.txt` (an empty inbox's too).
2. **Run** `python3 $S apply $R plan.json` with the turn's moves, dependsOn items, image swaps,
   ranks, pushed marks and sorted notes; it prints `{"writes", "delete_assets"}`.
3. **Write** `writes` as one ArtifactData `batch`; delete each of `delete_assets` from the page's
   asset store. A pinned write that fails means someone changed the row: read again and redo.
4. **`python3 $S prep $R --sessions sessions.json [--message draft.md]`** before every message:
   the rule-reload and update checks, the checks, the notes to sort, the deck, the footer. It
   describes only rows changed since the last `prep`. Exit 1: there's work before the message.
   When it says the rules changed, re-read what it names, republish the page if it says so (on
   a refusal that hands back the live page, merge and publish again until it goes through),
   and run `loaded`. When it says Desk has an update, run `/desk:update` at once.

The plan: `{"moves": [{"id", "to": news|working|waiting|held|done, "ask", "recommend",
"ifnone", "context", "note", "kind", "link", "settled", "session", "active"}], "deps": [{"id",
"item", "state", "card"?, "add"?}], "images": [{"id", "top": true | "fold", "images": [{"id",
"caption"}]}], "rank": [{"id", "place"}], "pushed": [id], "sorted": [note-id]}`. One row is
written once; a refused step writes nothing.

Often too: `sessions $R` (the sessions to check, one `get_session` each), `when "tomorrow
9:00"` (the owner's time to stored UTC and back), `footer $R`, `order $R`, `inbox $R`, `note`,
`spawn` (a child session's arguments, rule 11). The one-at-a-time commands (`move`, `rank`,
`images`, `dep`, `pushed`, `sorted`) and the rest are in the reference.

## The 17 rules, short

Each in full, with its date, in `reference.md`.

1. **States.** Waiting while a question to the owner is open on it; In progress while a session
   works and nothing waits on them; Later when held for an event or a date. Every question put
   to them lands on a Waiting card's ask in the same turn, never in a note. A card's number is
   its place, never an id: name cards by title.
2. **One card per task.** Read every waiting and in-progress card first; a new question goes
   into its task's card. `dependsOn` lists what a card waits on.
3. **A card holds everything**: ask and recommendation, then context, then folds. The owner
   decides from the card alone (a review: problem, fix, verdict, findings; a decision: the
   request in full, options, trade-offs; a check: what to try and what right looks like).
   A row past 8 KB is flagged: trim it.
4. **Images** go on the card in the same turn, uploaded to the page's assets, looked at first,
   beside their fold's text. A session with an image sends the keeper its asset id.
5. **Answers.** A card back with a new question drops the old answer; what's settled goes in a
   "Settled so far" fold. Never ask what's answered or ruled: `prep --message` flags it (desk.json's
   `rulings` files too).
6. **Order.** News first. Waiting: the card under discussion (3 h), then your priority.
7. **Priority is yours**: `rank` each new waiting card the turn it lands.
8. **The footer**: every message ends with a rule and the line `prep` printed, as is.
9. **Finished tasks** close at the end of their step, that turn: news with a recap, a `check` card for
   what to try by hand, or deleted. No Done list.
10. **The buttons.** 👍 go with the recommended, ⏭ tomorrow 9:00, 💬 the chat; a `step` (done
    off the page) has its link as the main button and 👍 reads Done. Held cards wait under
    Later until asked for. News has Seen and Add a note. Several questions on one card are a
    numbered list in its ask: the page gives each a Yes / No, and "All as recommended".
11. **One writer.** Only the keeper writes cards and pushes the owner; others report to it, or
    drop a note in the Inbox. Routines run as their own short sessions and leave their results
    there (`note --routine NAME`, a watch with `--only-new`), exempt from rule 1. A child
    session comes from `spawn` only: it refuses a second session on a live task and sets every
    default (repo, branch, auto mode, `send_message`, the model).
12. **Before every message**: rows and notes read fresh, sessions checked, only changed cards
    written. That's `prep`.
13. **A push for every new waiting card**, one push for all of them, then `pushed`.
14. **News**: what the owner should know but needn't answer. Never routine progress, never an
    ask, never a push.
15. **The Inbox**: sort every note before the next message (into a card, a new card, or news),
    then `sorted`.
16. **The look**: each Desk's theme and icon, in `settings/look`; `/desk:look` changes it.
17. **Feedback on Desk itself** is a behavior-only issue on the plugin's repo, scrubbed, shown
    to the owner, filed by them (`/desk:feedback`).

## How it reaches you

The page's buttons and note tab save to the database and post a "sent to Claude" comment that
wakes the keeper through its watch (ArtifactComments `watch`). On a wake: read the thread, act,
reply in one line, resolve it, update the row. A `[Desk note] … (inbox <id>)` wake: sort that
note from its row. A `[Desk] N answers, sent together:` wake carries one line per card
(`task <id>`) and maybe dictated words (`inbox <id>`): handle them all in that one turn.
