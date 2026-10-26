---
name: setup
description: Set up a new Desk for a project, or move an existing tasks page onto Desk in place. Use when the owner asks for a Desk for this project, or runs /desk:setup.
argument-hint: [title] [theme] [icon]
---

# Setting up a Desk

Asked: $ARGUMENTS

A Desk lives on the account this session runs on: work's on the work account, a personal
project's on the personal one. Never set up one project's Desk on another's account, and never
put two projects on one Desk.

1. **Ask what's missing**, one question at a time, each with your recommendation: the title
   ("<project> Desk"), the theme (`desk.py look --list`), the icon (an emoji, a letter or an
   image), their time zone (an IANA name like `Europe/Berlin`; recommend the one their messages
   or the repo point to, else ask). Who keeps it: this session, unless the owner names another.
2. **Write `.claude/desk.json`** in the project's repo: `{"title", "keeper": "<this session's
   id>", "timezone", "look": {"theme", "icon"}}` (no `page` yet). Commit it as the repo does.
3. **The page:** `python3 <the desk skill's directory>/desk.py page --out <scratch>/desk.html`
   and publish it with the Artifact tool, `capabilities: {db: {}, user: {}, assets: {},
   comments: {}}`, `icon: "inbox"`. **Moving an existing page in place:** publish to its `url`
   instead (its rows, assets and comments stay) and omit `capabilities` if it already has
   those four. Expect refusals when another session or context published it last: the first
   often comes with the diff, the next as identical content resent. Each time it hands back
   the live page, merge onto it and publish again until it goes through.
4. Put the page's link in `desk.json` as `page`, commit, and set the look row
   (`desk.py look …`, ArtifactData `set`, collection `settings`, doc `look`).
5. Become its keeper: load `desk-keeper` and do its start steps (the page's watch first).
6. Tell the owner the link, in one line, and that `/desk:note` from any session in this repo
   reaches it.
