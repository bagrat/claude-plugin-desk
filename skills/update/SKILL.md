---
name: update
description: Bring this Desk up to the plugin's latest rules and page. Use when the Desk orchestrator says a fix merged, when the owner asks to update Desk, or runs /desk:update. Keeper only.
---

# Updating Desk

You must be this Desk's keeper (rule 11). `S=<the desk skill's directory>/desk.py`.

1. `python3 $S update`: it pulls the plugin's clone at `~/.claude/desk` (cloning it there if
   it's missing) and names each rule file that changed since you loaded them, in that clone,
   the project's and each `watch` clone. Exit 0 with "Desk is current": skip to step 4.
2. Re-read each file it names; load each changed skill again. When it says the page changed,
   republish the Desk in place: `python3 $S page --out <scratch>/desk.html`, then Artifact
   publish to the Desk's `url` (the cards, notes and look stay in its database). On a refusal
   that hands back the live page, merge onto it and publish again until it goes through.
3. `python3 $S loaded`.
4. Tell the owner in one line what changed (or that Desk was already current).
