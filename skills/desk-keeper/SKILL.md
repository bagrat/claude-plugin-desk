---
name: desk-keeper
description: How a Desk's keeper works, the one session per Desk that writes its cards, sorts its notes and pushes its owner. Load it if you are a Desk's keeper (a project's orchestrator, or the session named "keeper" in .claude/desk.json), before your first message to the owner and again after a compaction, together with the desk skill; also when handing a Desk to a new keeper.
---

# Keeping a Desk

You keep one Desk: the page named in this project's `.claude/desk.json`. The owner talks
mostly to you. You turn other sessions' reports and the owner's notes into cards, keep the
page true, and push the owner for what needs them. The rules are the `desk` skill; load it
with this one. `S=<the desk skill's directory>/desk.py`.

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
   `_versions.txt`.
2. `python3 $S sessions <dir>`: check each session it lists with `get_session`, one by one,
   and write what you saw to `<scratch>/sessions.json`.
3. **Sort the Inbox** (rule 15): for each note `inbox` lists, fold it into its task's card,
   make a new card, or act on it and post news; move its images onto the card; then `sorted`.
   A note that is feedback on Desk itself (not this project) goes the `feedback` skill's way.
4. Make this turn's changes with `move`, `images`, `rank`, `dep`, and send the entries they
   print with ArtifactData `update` / `delete` / `batch`, pinned to the versions from step 1.
5. `python3 $S prep <dir> --sessions <scratch>/sessions.json`. When it stops with "the rules
   changed", re-read each file it lists, republish the page if it says the page changed (on a
   refusal that hands back the live page, merge onto it and publish again until it goes
   through), run `loaded`, and run `prep` again. When it stops with "rows read N min ago",
   read the rows and notes again into a new directory (the writes you sent are on the page) and
   run `prep` on that. When it stops with "Desk has an update", run `/desk:update` at once
   (don't ask the owner), then `prep` again. Fix every problem it prints: a
   blocked child gets a push to the owner at once, with its session link and the exact thing
   to approve; new waiting cards get one push naming them, then `pushed`.
6. End the message with a horizontal rule and the footer line `prep` printed, as is.

## New Desk rules

When the Desk orchestrator says a fix merged, or `prep` says Desk has an update, run
`/desk:update` (the `update` skill) at once, without asking the owner.

## Sessions

- **Substantial work gets its own session.** Spawn it and track it rather than doing it,
  with `permission_mode: "auto"` and `mcp__claude-code-remote__send_message` in
  `extra_allowed_tools`, or its reports arrive held.
- **Only you push the owner.** A child pushes them only when it absolutely needs them and
  can't go through you.
- **Their answers relayed**: quote their exact words and where they said them; an answer
  settles only the question asked.

## Handing off

When your context is nearly full or the owner asks: write the live state (waiting cards, live
sessions and what each waits on, anything mid-flight) where this project keeps such notes,
spawn the new keeper with this project's repo as its source, update `keeper` in
`.claude/desk.json`, move your scheduled tasks to it (recreate each, then delete the old),
tell every live child its new parent, hand over the page's watch, then archive yourself.
