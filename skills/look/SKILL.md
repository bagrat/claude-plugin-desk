---
name: look
description: Change a Desk's theme or its icon (top left). Use when the owner asks to change their Desk's colors, theme, icon or logo, or to use a company logo, or runs /desk:look. Keeper only.
argument-hint: [theme] [icon: emoji, image or letter]
---

# The Desk's look

Asked: $ARGUMENTS

You must be this Desk's keeper (rule 11). `S=<the desk skill's directory>/desk.py`.

1. Read the current look: ArtifactData `get`, `collection: "settings"`, `doc_id: "look"`,
   `out_dir: <scratch>/look` (missing is fine: then the page uses what it was made with).
2. **A theme:** one of `python3 $S look --list`. When the owner names a color or a mood,
   pick the closest and say which.
3. **An icon:** an emoji, one or two letters, or an image. For an image (a logo):
   - find it: a repo this session has, a site this session's network reaches, or one the
     owner sends; never take one from a place the owner didn't point to or the project
     doesn't own;
   - make it square and small: about 128×128 PNG or a clean SVG, transparent ground,
     the mark only (crop words off a wide logo unless the owner wants them); look at it;
   - upload it to the Desk's page (Artifact publish, `url` the page, `asset: true`) and use
     the id it returns.
4. `python3 $S look [--theme T] [--emoji E | --image ID | --letter L] --current
   <scratch>/look/settings/look.json --out <scratch>/look`, then ArtifactData `set` with the
   printed entry (`if_version` from step 1 when the row existed).
5. The page changes at once. If the owner wants it to stick as what the page is made with,
   also update `look` in `.claude/desk.json`. Delete a replaced image from the asset store.
