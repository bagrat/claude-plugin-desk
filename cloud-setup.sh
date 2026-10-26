#!/bin/sh
# Desk in a cloud session: put this line in the cloud environment's setup script
# (the environment menu in a session's title bar, then Edit, then Setup script):
#
#   curl -fsSL https://raw.githubusercontent.com/bagrat/claude-plugin-desk/main/cloud-setup.sh | sh
#
# It runs before Claude Code starts, so /desk:note, /desk:feedback and the rest load in that
# session. Cloud sessions don't install plugins from a repo's .claude/settings.json, and the
# ones added in the app stay on the computer. It also keeps one clone of the plugin at
# ~/.claude/desk: the installed copy isn't a clone, and /desk:update and the rule-reload
# check follow the plugin through that one.
#
# Never fails the setup: a session without Desk is better than no session.

DESK_HOME="$HOME/.claude/desk"
DESK_REPO_URL="${DESK_REPO_URL:-https://github.com/bagrat/claude-plugin-desk}"

if command -v git >/dev/null 2>&1; then
  if [ -d "$DESK_HOME/.git" ]; then
    git -C "$DESK_HOME" pull --quiet --ff-only origin main || true
  else
    mkdir -p "$(dirname "$DESK_HOME")" && git clone --quiet "$DESK_REPO_URL" "$DESK_HOME" || true
  fi
else
  echo "desk: git not found, no clone at $DESK_HOME" >&2
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "desk: claude not found, skipping" >&2
  exit 0
fi

claude plugin marketplace add bagrat/claude-plugin-marketplace || true
claude plugin install desk@bagrat || true
claude plugin update desk@bagrat || true
exit 0
