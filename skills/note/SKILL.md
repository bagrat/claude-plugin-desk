---
name: note
description: Drop a note onto this project's Desk Inbox, for its keeper to turn into a card. Use when the owner says "note …", "/desk:note …", or asks to put an observation or a change request on their Desk from any session.
argument-hint: <the note>
---

# A note for the Desk

The note is: $ARGUMENTS

1. **Which Desk:** this repo's `.claude/desk.json` (desk.py finds it up from the working
   directory). If there is none, say so in one line and ask which project's Desk it's for;
   never guess one, and never put a note on a Desk of another account.
2. **Keep their words.** The note's text is what the owner said, lightly tidied, never
   rewritten into a card. Add one line of context only if the note means nothing without it
   (e.g. "while looking at <file>"); a screenshot they shared goes with it: upload it to the
   page first (Artifact publish, `asset: true`, the Desk's `url`) and pass `--image ID=caption`.
3. **Write it:** `python3 <the desk skill's directory>/desk.py note --text "<note>" --from
   "<this session's link, or the repo>" --out <scratch>/note`, then send the printed `write`
   with ArtifactData `set` (its `file_path`, no `if_version`: it's new) to the printed `page`.
4. **Wake the keeper:** when `keeper` is printed and `send_message` is available, send it one
   line: "New note on the Inbox: <the note's first line>". Otherwise the keeper finds it at
   its next message.
5. Tell the owner in one line that it's on the Desk's Inbox.
