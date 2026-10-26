# Desk

A Claude Code plugin: **one Desk per project**, a private claude.ai page that keeps you
informed and holds what needs you, kept by one Claude session (the project's *keeper*).

- **News**: what you should know but needn't answer. Seen clears it.
- **Waiting**: what needs you, one card at a time, each with everything needed to decide, an
  ask and a recommendation. 👍 goes with the recommendation, ⏭ brings it back tomorrow, 💬 says
  it in the chat.
- **In progress** and **Coming up**: what sessions are working on, and what's held for later.
- **The Inbox**: drop a note from the page (type or dictate, add a screenshot) or with
  `/desk:note` in any session; the keeper turns it into a card. A strip shows notes being sorted.
- **Its own look**: 15 Nord-like themes and any icon, so you see at a glance which Desk you're on.

Each Desk lives on the account its project lives on, and nothing of one Desk reaches another.

## Install

On a computer, in Claude Code:

```
/plugin marketplace add bagrat/claude-plugin-marketplace
/plugin install desk@bagrat
```

In a cloud session (claude.ai/code), plugins from a repo's settings or added in the app aren't
installed. Put this line in the cloud environment's setup script (the environment menu in a
session's title bar, then Edit, then Setup script), and every new session has Desk:

```
curl -fsSL https://raw.githubusercontent.com/bagrat/claude-plugin-desk/main/cloud-setup.sh | sh
```

A keeper also attaches this repo and registers it (its skills load from `.claude/skills/`):
the rule-reload check follows a git clone, and the installed copy isn't one.

Then, in the project's keeper session: `/desk:setup`.

## What's in it

| Path | What |
| --- | --- |
| `skills/desk/` | The rules (`SKILL.md`) and `desk.py`, the bookkeeping script, with its tests. |
| `skills/desk-keeper/` | What a keeper does before every message. |
| `skills/note`, `look`, `setup`, `feedback` | `/desk:note`, `/desk:look`, `/desk:setup`, `/desk:feedback`. |
| `skills/desk-fixer/` | The fixer: one session per issue on this repo, started by a routine. |
| `page/desk.html` | The page template, and `page/tests/` its Playwright tests. |
| `.claude/skills/` | Links to `skills/`, so a cloud session that registers this repo loads them. |
| `cloud-setup.sh` | Installs the plugin from a cloud environment's setup script. |

## Tests

```
python3 -m unittest discover -s skills/desk
for t in page/tests/{news,deps,desk}.mjs; do NODE_PATH=$(npm root -g) node $t; done
```

## Feedback

`/desk:feedback` in any session drafts an issue here that describes behavior only, never a
Desk's content, and shows it to you before anything goes public, then gives you a prefilled link to submit yourself. A new issue starts a fixer session.

MIT licensed.
