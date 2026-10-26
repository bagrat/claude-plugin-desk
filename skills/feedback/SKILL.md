---
name: feedback
description: Report a bug in, or ask for a change to, Desk itself (the page, its rules, its commands), as a behavior-only issue on the plugin's public repo. Use when the owner says something about how their Desk works should change, or runs /desk:feedback, from any project or account.
argument-hint: <what's wrong or wanted>
---

# Feedback on Desk itself

Asked: $ARGUMENTS

The plugin's repo is **public**. The issue says how Desk behaves and how it should, never what
is on the Desk (rule 17). Projects can be an employer's: nothing of theirs leaves their account.

1. **Gather what happened**, from this session and the Desk: which rule, command or screen;
   what it did; what the owner expected; the plugin's version (`git -C <plugin clone> rev-parse
   --short HEAD`, or the installed version). Ask one question if the ask is unclear.
2. **Write the draft** to `<scratch>/feedback.md`: a title, then *What happens*, *What should
   happen*, *Steps* (with made-up placeholders: "a waiting card with two folds", "a note with
   an image"), *Version*. No card text, titles, names, links, repos, note text or screenshots
   of a real Desk; a screenshot only of a test page with made-up rows.
3. **Scrub it:** `python3 <the desk skill's directory>/desk.py scrub <scratch>/feedback.md
   --rows <a fresh rows dump, when you can read the Desk>`. Rewrite every flag away.
4. **Show the owner the draft** and wait for their yes. Nothing goes public before it.
5. **Hand over the link, never file it yourself.** An issue opened through a session's GitHub
   access doesn't start the fixer (the routine skips events made by its own app), so even with
   access to `bagrat/claude-plugin-desk` you do not create the issue. Run `desk.py issue-url
   --title "…" --body <scratch>/feedback.md --rows <dump>` and give the owner the link to open
   and submit from their own GitHub.
6. One line back: the prefilled link. Submitting it starts a fixer, and
   the Desk orchestrator tells every keeper when the fix is in.
