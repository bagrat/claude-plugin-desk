---
name: desk
description: A Desk, the page that keeps its owner informed and holds what needs them (news, what waits on them, what's in progress, their notes), and desk.py, its bookkeeping script. Load it before reading or writing any of a Desk's cards or notes, and before every message to the owner if you are that Desk's keeper; it holds the 17 rules, the row fields, and the commands that check the cards, count the footer, order and re-rank them, and write the patches.
---

# A Desk

A Desk is a private claude.ai page, one per project, on the account the project lives on. It
shows its owner **News** (what to know), **Waiting** (what needs them, one card at a time,
with one-tap answers), **In progress**, **Coming up**, and the **Inbox** (their notes being
sorted). Each card carries everything needed to decide from scratch. Capabilities: db, user,
assets, comments. Its template is `page/desk.html` in this plugin.

Which Desk you're on comes from the project's `.claude/desk.json`:

```json
{"title": "shroom Desk", "page": "https://claude.ai/artifact/…", "keeper": "session_…",
 "watch": ["/home/user/other-clone"], "look": {"theme": "frost", "icon": {"emoji": "🍄"}}}
```

`page` is the Desk's link; `keeper` the session that keeps it; `watch` other clones whose rules
the keeper must reload when they change; `look` what the page is made with (the live look is
the page's `settings/look` row, rule 16). Only the keeper writes its cards (rule 11).

## The script does the mechanics, you write the words

`desk.py` (beside this file; Python 3, stdlib only) works on the rows as files. It can't call
the Artifact tools, so you do the I/O:

1. **Read** the rows and the notes fresh into one new directory: ArtifactData `list`,
   `collection: "tasks"`, then `collection: "inbox"`, both with the same
   `out_dir: <scratch>/rows-<time>`. Paste each result as is into
   `<that directory>/tasks/_versions.txt` and `inbox/_versions.txt`, and every entry the
   script prints is pinned.
2. **Run** the script on that directory (`$R`, or `$R/tasks`).
3. **Write** what it prints: each entry is `{op, collection, doc_id, file_path, if_version}`;
   send one with ArtifactData `update` / `set` / `delete`, several with `batch`
   (`writes: [...]`). A pinned write that fails means someone changed the row: read it again
   and redo. The script applies each patch to its local file too.

`S=<this skill's directory>/desk.py`. It finds `.claude/desk.json` up from the working
directory; `--desk FILE` (before the command) or `$DESK_CONFIG` names another.

| Command | What |
| --- | --- |
| `python3 $S sessions $R` | The sessions behind open cards, one per line, to check one by one (`get_session`). |
| `python3 $S prep $R --sessions sessions.json [--message draft.md]` | **Before every message.** The rule-reload check, the checks, the notes to sort, the deck in the page's order, the footer. With `--message`, each numbered question or "Recommended:" line in the draft that no Waiting card holds. Exit 1 when anything is left to do. Refuses rows read more than 2 minutes ago (`--max-age MIN`). |
| `python3 $S loaded` | Mark the rules reloaded, after you've re-read what `prep` or `update` named. |
| `python3 $S update` | `/desk:update`: pull the plugin's clone at `~/.claude/desk` (clone it if missing) and name what changed since you loaded it. Exit 1 when there's something to re-read. |
| `python3 $S check $R [--sessions …] [--stale-hours 12]` | The checks alone. |
| `python3 $S footer $R` | The footer line, exactly; refuses a dump older than 2 minutes, like `prep`. |
| `python3 $S order $R` | News, then the waiting deck as the page shows it, then Later and In progress. |
| `python3 $S rank $R` | Re-rank waiting cards by rule 7. |
| `python3 $S move $R <id> news\|working\|waiting\|done [--context …] [--ask … --recommend … --ifnone …] [--note …] [--settled "…"] [--session "Label=url"] [--active] [--if-version N]` | The patch for a move. |
| `python3 $S pushed $R <id> […]` | After the push for new waiting cards (rule 13): sets each card's `pushedAt`. |
| `python3 $S dep $R <id> "<item>" done\|building\|open [--card ID] [--add]` | One `dependsOn` item by hand. |
| `python3 $S images $R <id> --top\|--fold N [--image ID=caption …] [--json f] [--drop-top]` | A card's or a fold's images, plus `delete_assets`: ids no longer used on the card. |
| `python3 $S inbox $R` | The notes waiting to be sorted (rule 15). |
| `python3 $S sorted $R <note-id> […]` | The deletes for notes now held by cards. |
| `python3 $S note --text "…" --from <where> --out DIR [--image ID=caption]` | A note for this Desk's Inbox (what `/desk:note` runs). |
| `python3 $S look [--theme T] [--emoji E \| --image ASSET \| --letter L] [--current row.json] [--list]` | The `settings/look` row (rule 16). |
| `python3 $S page --out FILE` | The page to publish for this Desk: the template with its title, keeper and look. |
| `python3 $S scrub DRAFT [--rows $R]` | What in a feedback draft might carry the Desk's content (rule 17). |
| `python3 $S issue-url --title T --body FILE [--rows $R]` | A prefilled new-issue link on the plugin's repo; refuses while `scrub` flags anything. |

`sessions.json` is what you saw: `{"session_…": "<status_bucket>"}`. `--now ISO` judges at
another time.

What the script does by itself:

- `move … waiting` drops the answer fields, `workingSince`, `snoozeUntil`, `pushedAt` (so it
  gets its push) and, unless you give `--note`, `note`. It refuses without an ask and a
  recommendation, and without a new `--ask` when the old one was answered. `--settled` puts a
  "Settled so far" fold at the top.
- `move … working` sets `workingSince`; `--session` adds a session first in `sessions`.
- `move … news` drops the ask, recommendation, answers and what only a deck card uses, keeps
  the folds and images, and refuses an `--ask`.
- `move … done` prints a delete. Every move also prints the cards whose `dependsOn` links the
  moved one, each set to its new state; send them together in one `batch`.
- `images` replaces the whole `details` array for a fold. Delete each id in `delete_assets`
  from the page's asset store (Artifact `delete`, `url`, `path: <id>`).

**The rule-reload check.** `prep` first compares the HEAD of the project's clone (where
`desk.json` sits), of the plugin's clone and of each `watch` clone with what you last loaded;
it never fetches, so it costs no time. The plugin's clone is the one `desk.py` runs from, or
`~/.claude/desk` when it runs from a copy that isn't a clone (a plugin install). When a
pull changed `CLAUDE.md`, `memory/MEMORY.md`, `.claude/skills/`, `.claude/desk.json`,
`skills/` or `page/desk.html` since then, it stops: exit 1, no deck, no footer. Re-read each
file (load a changed skill again) and run `loaded`. When the page template changed, republish
the Desk in place too: `page --out <file>`, then Artifact publish with the Desk's `url` (the
cards, notes and look live in its database and stay). If the publish is refused and hands
back the live page (often twice on the first switch), merge onto it and publish again until it
goes through.

**Updating.** New Desk rules arrive by `/desk:update` (the `update` skill): it pulls
`~/.claude/desk` and does the above in one go. The keeper runs it when the Desk orchestrator
says a fix merged; the owner can run it any time.

What `check` flags is in the script's messages; each line is `<id>: <problem>` and names the
rule. A failing check is work before the message, not a note in it. When a flag is wrong (a
judgment the script can't see), say why to yourself and move on; don't bend the card to quiet
it.

## The 17 rules

1. **States.** Waiting whenever a question to the owner is open on it, even while a session
   keeps working on other parts: the question is its ask. When they answer, it goes back to In
   progress. In progress while a session (or you) is working on it and nothing waits on them;
   a session waiting on its own CI counts. Later (scheduled, with its `when`) once the work is
   done and only held for an event that isn't theirs (a release, another PR), or parked until
   a date. A card's ask is always the one question waiting on them now; on a walkthrough, the
   current step. **Every question put to them in the chat lands on a card in the same turn**,
   as a Waiting card's ask: never in an In-progress or Later card's `note`, `context` or folds
   (`check` flags those; `prep --message <draft>` flags a question in the draft no card holds).
2. **One card per task.** Before adding or changing a card, read every waiting and in-progress
   card. A new question about a task goes into its card, never a second card. A card a newer
   step makes pointless is reworked or deleted. A card that waits on others lists them in
   `dependsOn` (linked by `card` when the item is a card).
3. **A card holds everything.** A short summary on top, the longer parts in folds (`details`);
   never "see the chat": the owner swipes cards and can't find things back in the chat. Every
   waiting card has an ask and a recommendation.
4. **Images, with folds.** New images go on the card in the same turn, uploaded to the page's
   asset store (Artifact publish, `asset: true`, the page's url), superseded ones replaced and
   deleted. A link alone isn't enough. A card split into folds carries each fold's images beside
   its text (`details[i].images`). **Look at every image before it goes on a card**; a tall
   board is split only between rows or frames, never through one.
5. **Answers.** When a card comes back with a new question, the old answer leaves it, and
   what's settled goes in a "Settled so far" fold at the top (`move … waiting --settled`).
6. **Order.** News has its own tab, first. In Waiting: the card being discussed, for 3 hours
   after it was last discussed (`--active`), latest first; then by rank. Snoozed cards wait
   under Later.
7. **Rank.** Blocking or time-sensitive first, then reviews, then decisions, then checks by
   hand. A card can be bumped by hand: the rank you want and `rankByHand: true`.
8. **The footer.** Every message to the owner ends with a horizontal rule, then one link:
   `[✦ K ··· ● N ··· ◌ M](<page>#news)`, K news, N waiting minus snoozed, M working, counted from
   the rows read fresh (`footer`), never from memory. Without news: `[● N ··· ◌ M](<page>#waiting)`.
9. **Finished tasks.** No Done list. A finished task with something to tell becomes news with
   its recap (`move … news --context …`). Anything to try by hand stays a Waiting card (kind
   `check`). Otherwise the card closes on their answer (`move … done`).
10. **The buttons.** On a Waiting card: 👍 go with the recommended (to In progress), ⏭ back
    tomorrow at 9:00, 💬 say it in the chat. On news, one button, **Seen**, which deletes the row
    (where it can't, it sets `done` and you delete it); it wakes no one.
11. **One writer.** Only the keeper writes cards; other sessions report to it. The one write
    anyone else makes is a note into the Inbox (rule 15).
12. **Before every message.** Rows and notes read fresh, only the sessions behind cards checked,
    only changed cards written, by small edits. That's `prep`. Fresh means for this message, a
    one-line one too: the owner's Seen deletes rows meanwhile. `prep` and `footer` refuse a dump
    whose oldest row or note was written more than 2 minutes ago ("rows read N min ago").
13. **A push for every new waiting card.** As soon as a card lands in Waiting (new, a new
    question, or back from a snooze), push the owner in the same turn: one push for all the new
    ones, each named by its title, the most urgent first. Then `pushed`.
14. **News.** What the owner should know but needn't answer: a release published, something they
    asked for merged, a decision live, a session finished with nothing left, a failure fixed, a
    scheduled job's result worth seeing. Never routine progress. Added in the same turn the
    chat would have said it. A title, a one-line `context`, maybe links, folds and images; never
    an ask; never pushes. It stays until Seen.
15. **The Inbox.** The owner drops notes from the page's note tab (the pencil, last in the bar,
    owner only; 2026-10-26), from `/desk:note` in any session on the account, or in the keeper's
    chat. Notes wait in the `inbox` collection and show above the cards as a strip ("2 notes
    being sorted"), only while some wait. The keeper sorts every one before its next message
    (`prep` stops on them): folds it into its task's card, makes a new card (Waiting if it needs
    a decision, In progress if work starts), or does it at once and posts news; then deletes the
    note (`sorted`). A note's images move onto its card.
16. **The look.** Each Desk has its own theme and icon so the owner sees at a glance which one
    they're on. The page reads its `settings/look` row (`{"theme", "icon": {"emoji"} |
    {"image": asset id} | {"letter"}}`) live; `desk.json`'s `look` is what it's made with. 15
    themes: frost, moss, ember, berry, plum, sand (Nord's own accents), mauve, rose, fern, wave,
    lagoon, night, neon, rust, lime. Change it with `/desk:look`.
17. **Feedback on Desk itself.** A fix or a feature for the Desk (not for the project) goes to
    the plugin's repo as an issue that describes **behavior only**: no card text, titles, names,
    links, repos or note text; placeholders ("a waiting card with two folds") instead. Draft it,
    `scrub` it, show the owner the draft, and only then hand them `issue-url`'s link to submit
    from their own GitHub; never file it from a session. `/desk:feedback` does this.

## How it reaches you

The page's buttons and its note tab save to the database and post a "sent to Claude" comment,
which wakes whichever session **watches** the page (ArtifactComments `watch`): the keeper holds
that watch. On a wake: read the thread, act, reply in one line, resolve it, update the row.

## Row fields

**tasks**: state (news | waiting | working | scheduled; `done` only from the page), rank,
rankByHand, kind (decide | review | check | do | info), handle, title, context, details
`[{title, text, images?}]`, images `[{id, caption, file?}]` (served at `/_blob/<id>`), ask,
recommend, ifNone, blocks, links `[{label, url}]`, sessions `[{label, url}]`, since, updatedAt,
activeAt, snoozeUntil, pushedAt, answer, answeredAt, quick, quickAt, answerSent, workingSince,
note, dependsOn `[{item, card?, state}]` (done | building | open); scheduled rows also `when`.

**inbox**: text, from (`page`, a session link, `chat`), at, images? `[{id, caption}]`.

**settings/look**: theme, icon.

Writes need `if_version`; `str_replace` only on string fields; `{"__delete__": true}` removes a
field (not inside arrays).
