#!/bin/sh
# Desk in a cloud session: put this line in the cloud environment's setup script
# (the environment menu in a session's title bar, then Edit, then Setup script):
#
#   curl -fsSL https://raw.githubusercontent.com/bagrat/claude-plugin-desk/main/cloud-setup.sh | sh
#
# It runs before Claude Code starts, so /desk:note, /desk:feedback and the rest load in that
# session. Cloud sessions don't install plugins from a repo's .claude/settings.json, and the
# ones added in the app stay on the computer. A keeper still attaches this repo as a git clone:
# the installed copy isn't one, so the rule-reload check can't follow it.
#
# Never fails the setup: a session without Desk is better than no session.

if ! command -v claude >/dev/null 2>&1; then
  echo "desk: claude not found, skipping" >&2
  exit 0
fi

claude plugin marketplace add bagrat/claude-plugin-marketplace || true
claude plugin install desk@bagrat || true
claude plugin update desk@bagrat || true
exit 0
