---
name: desk-keeper
description: How a Desk's keeper works, the one session per Desk that writes its cards, sorts its notes and pushes its owner. Load it if you are a Desk's keeper (a project's orchestrator, or the session named "keeper" in .claude/desk.json), before your first message to the owner and again after a compaction, together with the desk skill; also when handing a Desk to a new keeper.
---

# Keeping a Desk

You keep one Desk: the page named in this project's `.claude/desk.json`. The owner talks
mostly to you. You turn other sessions' reports and the owner's notes into cards, keep the
page true, and push the owner for what needs them. The rules are the `desk` skill; load it
with this one (its `reference.md` holds the detail, read when you need it).
`S=<the desk skill's directory>/desk.py`.

## At the start (and after a handoff)

1. **The plugin's clone at `~/.claude/desk`.** The rule-reload check and `/desk:update`
   follow the plugin through it; `cloud-setup.sh` keeps it in a cloud session. If it's
   missing, `git clone https://github.com/bagrat/claude-plugin-desk ~/.claude/desk`.
2. **Watch the page:** ArtifactComments `watch`, `url` the Desk's page. Its buttons and note
   box wake you through that watch; check it registered (`watch` with no url lists them).
3. Mark the rules as read: `python3 $S loaded`.

## Before every message to the owner

Every time, in this order, a one-line message too (never reuse an earlier turn's dump: the
owner may have cleared news since):

1. Read the rows and notes fresh (ArtifactData `list`, `collection` `tasks`, then `inbox`,
   the same new `out_dir: <scratch>/rows-<HHMM>`); paste each result into that collection's
   `_versions.txt`, an empty inbox's too (`prep` stops without `inbox/`).
2. `python3 $S sessions <dir>`: check each session it lists with `get_session`, one by one,
   and write what you saw to `<scratch>/sessions.json`.
3. **Sort the Inbox** (rule 15): for each note `inbox` lists, fold it into its task's card,
   make a new card, or act on it and post news; move its images onto the card; then `sorted`.
   A note that is feedback on Desk itself (not this project) goes the `feedback` skill's way.
4. Make this turn's changes in one call: write them as a plan (moves, dependsOn items, image
   swaps, ranks, pushed marks, sorted notes) and run `python3 $S apply <dir> <plan.json>`; send
   its `writes` as one ArtifactData `batch` and delete its `delete_assets`. (`move`, `images`,
   `rank`, `dep`, `pushed` and `sorted` still do one at a time.)
5. `python3 $S prep <dir> --sessions <scratch>/sessions.json --message <scratch>/draft.md`,
   the draft written first when it asks the owner anything: each question in it must be a
   Waiting card's ask, never a card's note (rule 1). When it stops with "the rules
   changed", re-read each file it lists, republish the page if it says the page changed (on a
   refusal that hands back the live page, merge onto it and publish again until it goes
   through), run `loaded`, and run `prep` again. When it stops with "rows read N min ago",
   read the rows and notes again into a new directory (the writes you sent are on the page) and
   run `prep` on that. When it stops with "Desk has an update", run `/desk:update` at once
   (don't ask the owner), then `prep` again. Fix every problem it prints: a
   blocked child gets a push to the owner at once, with its session link and the exact thing
   to approve; new waiting cards get one push naming them, then `pushed`.
6. End the message with a horizontal rule and the footer line `prep` printed, as is.

## Reviews the owner isn't ready for

When the owner puts a review off with no date ("not now", "later", "when I ask"), hold it
(`move <id> held`, rule 10) rather than snoozing it again and again; never push about a held
card. When they ask for it ("let's do the review", its name), `move <id> waiting` it, then send
its images into the chat as files with SendUserFile (`display: "render"`, each with its caption;
download them from the page's asset store with Artifact `read`, `url` the page, `path` the
image id), fold by fold in the card's order, with the card's ask and recommendation, so they
can review on the phone without opening the page.

## New Desk rules

When the Desk orchestrator says a fix merged, or `prep` says Desk has an update, run
`/desk:update` (the `update` skill) at once, without asking the owner.

## Sessions

- **Substantial work gets its own session.** Spawn it and track it rather than doing it,
  with `permission_mode: "auto"` and `mcp__claude-code-remote__send_message` in
  `extra_allowed_tools`, or its reports arrive held.
- **Only you push the owner.** A child pushes them only when it absolutely needs them and
  can't go through you.
- **Times in the owner's zone** (`desk.json`'s `timezone`), on cards, in pushes and in the
  chat: `desk.py when` turns "tomorrow 9:00" into the stored UTC and a stored time back. No
  `timezone` yet: ask the owner for theirs, add it, commit, and republish the page.
- **Their answers relayed**: quote their exact words and where they said them; an answer
  settles only the question asked.

## Handing off

When your context is nearly full or the owner asks:

1. **Back up the Desk first.** Read tasks, inbox and settings fresh into one new directory
   (ArtifactData `list` each, the same `out_dir: <scratch>/handoff-<HHMM>`), then
   `python3 $S backup <dir> --out <file>`. Keep the file in the private place the project
   names for its notes (or your scratch, when it names none), never in the plugin's repo nor any repo that may be public
   (`backup` refuses a git repo unless you pass `--private-repo`, which you do only for a repo
   you know is private). Name the file in the handoff notes. If a write goes wrong mid-handoff,
   `python3 $S restore <file> --rows <a fresh read>` prints the writes that put it back; send
   them with ArtifactData `batch`.
2. Write the live state (waiting cards, live sessions and what each waits on, anything
   mid-flight) where this project keeps such notes, spawn the new keeper with this project's
   repo as its source, update `keeper` in `.claude/desk.json`, move your scheduled tasks to it
   (recreate each, then delete the old), tell every live child its new parent, hand over the
   page's watch, then archive yourself. A backup in your scratch goes with you; the new keeper
   can restore only from the project's private place.
