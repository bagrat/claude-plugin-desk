#!/usr/bin/env python3
"""A Desk's bookkeeping: checks, footer, order, rank, moves, card links, image swaps, the
Inbox, the look, and the page itself.

The script never talks to the page. The keeper dumps the rows with ArtifactData (list with
out_dir), runs this on the files, and sends back the patches it writes. A row file is either
the bare row or {"id", "data", "version"}. Which Desk: the nearest `.claude/desk.json` up
from the working directory, or `--desk FILE`, or $DESK_CONFIG. See SKILL.md.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

# The Desk this run works on, from its desk.json (load_config); PAGE is its link.
PAGE = None
CONFIG = {}
CONFIG_PATH = None
COLLECTION = "tasks"
INBOX = "inbox"
SETTINGS = "settings"
PLUGIN_REPO = Path(__file__).resolve().parents[2]
# The plugin's clone at a fixed place: cloud-setup.sh keeps it, `update` pulls it, and a
# copy of desk.py that isn't in a clone (a plugin install) follows the rules through it.
PLUGIN_HOME = Path(os.environ.get("DESK_HOME") or Path.home() / ".claude" / "desk")
PLUGIN_URL = "https://github.com/bagrat/claude-plugin-desk"
PLUGIN_ISSUES = "https://github.com/bagrat/claude-plugin-desk/issues/new"
# The themes the page carries (page/desk.html, THEMES); a test keeps the two lists equal.
THEMES = ("frost", "moss", "ember", "berry", "plum", "sand", "mauve", "rose", "fern", "wave",
          "lagoon", "night", "neon", "rust", "lime")
DELETE = {"__delete__": True}
ANSWER_FIELDS = ("answer", "answeredAt", "quick", "quickAt", "answerSent")
STATES = {"news", "waiting", "working", "scheduled", "done"}
KINDS = {"decide", "review", "check", "do", "info", "close"}
# A card's dependsOn items: a linked card's state, as its item should read it.
DEP_STATES = ("done", "building", "open")
# A news item is a finished task: done, for the cards that wait on it.
DEP_OF_STATE = {"working": "building", "waiting": "open", "scheduled": "open", "done": "done", "news": "done"}
# Rule 14: a news row is something to know, never something to answer.
NEWS_DROPS = ("ask", "recommend", "ifNone") + ANSWER_FIELDS + ("workingSince", "snoozeUntil", "pushedAt", "activeAt",
                                                              "rank", "rankByHand", "blocks", "kind", "note")
# Rule 7: blocking or time-sensitive first, then reviews, then decisions, then checks by hand.
KIND_ORDER = {"review": 0, "decide": 1, "do": 2, "check": 3, "info": 4, "close": 5}
ACTIVE_HOURS = 3
# Rule 13: when the keeper last pushed the owner about a waiting card.
PUSHED = "pushedAt"
CHAT = re.compile(
    r"see (the|our|my|this) (chat|thread|message)"
    r"|(in|from) the chat (above|earlier|before)"
    r"|chat above|earlier in (the|this) chat|above in (the|this) chat"
    r"|(details|more|everything|the rest|the full \w+) (is |are )?in the chat"
    r"|as (i|we) (said|discussed|mentioned)( above| earlier)?",
    re.I,
)
SUPERSEDED = re.compile(r"\b(superseded|replaced|dropped|withdrawn|obsolete|no longer)\b|^\s*(old|was)\b|~~", re.I)
IMAGE_FILE = re.compile(r"[\w.-]+\.(?:png|jpe?g|webp|gif)\b", re.I)
SESSION = re.compile(r"session_[A-Za-z0-9]+")
PR = re.compile(r"github\.com/[\w.-]+/[\w.-]+/pull/\d+")


# ---------------------------------------------------------------- the Desk

def find_config(start=None):
    """The nearest .claude/desk.json at or above start (default: the working directory)."""
    d = Path(start or Path.cwd()).resolve()
    for base in (d, *d.parents):
        f = base / ".claude" / "desk.json"
        if f.is_file():
            return f
    return None


def load_config(path=None):
    """Set PAGE, CONFIG and CONFIG_PATH from a desk.json: {"title", "page", "keeper"?,
    "watch"?: [clone paths], "look"?: {"theme", "icon"}}. Returns the config ({} if none)."""
    global PAGE, CONFIG, CONFIG_PATH
    f = Path(path) if path else (Path(os.environ["DESK_CONFIG"]) if os.environ.get("DESK_CONFIG") else find_config())
    if not f:
        PAGE, CONFIG, CONFIG_PATH = None, {}, None
        return CONFIG
    try:
        cfg = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"can't read {f}: {e}")
    PAGE, CONFIG, CONFIG_PATH = (cfg.get("page") or "").rstrip("/") or None, cfg, f.resolve()
    return cfg


# ---------------------------------------------------------------- rows

class Row:
    def __init__(self, path, rid, data, version, wrapped):
        self.path, self.id, self.data, self.version, self.wrapped = path, rid, data, version, wrapped

    def get(self, k, d=None):
        return self.data.get(k, d)

    def save(self):
        if self.wrapped:
            body = {"id": self.id, "data": self.data, "version": self.version}
        else:
            body = self.data
        self.path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")


def load_row(path):
    path = Path(path)
    raw = json.loads(path.read_text())
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict) and set(raw) <= {"id", "data", "version"}:
        return Row(path, raw.get("id") or path.stem, raw["data"], raw.get("version"), True)
    return Row(path, path.stem, raw, None, False)


def rows_dir(d):
    d = Path(d)
    # ArtifactData writes <out_dir>/tasks/<id>.json; accept either directory.
    if (d / COLLECTION).is_dir():
        d = d / COLLECTION
    return d


def load_rows(d):
    d = rows_dir(d)
    if not d.is_dir():
        sys.exit(f"no rows directory at {d}")
    rows = [load_row(p) for p in sorted(d.glob("*.json")) if not p.name.startswith("_")]
    versions = load_versions(d)
    for r in rows:
        if r.version is None and not r.wrapped and r.id in versions:
            r.version = versions[r.id]
    return rows


LISTED = re.compile(r'"([A-Za-z0-9_\-.~:@+]+)"\s+\d+ bytes\s+version (\d+)')


def load_versions(d):
    """Versions of bare rows: _versions.json ({id: version}), or _versions.txt, the
    ArtifactData list result pasted as is (- "id"  123 bytes  version 7 ...)."""
    for base in (d, d.parent):
        j, t = base / "_versions.json", base / "_versions.txt"
        if j.exists():
            return {k: int(v) for k, v in json.loads(j.read_text()).items()}
        if t.exists():
            return {k: int(v) for k, v in LISTED.findall(t.read_text())}
    return {}


def find(rows, rid):
    for r in rows:
        if r.id == rid:
            return r
    sys.exit(f"no row {rid!r}")


# ---------------------------------------------------------------- time

def parse_time(s):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def iso(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_arg(s):
    return parse_time(s) if s else datetime.now(timezone.utc)


# ---------------------------------------------------------------- counting and order

def snoozed(r, now):
    t = parse_time(r.get("snoozeUntil"))
    return bool(t and t > now)


def needs_push(r, now):
    """Rule 13: a card waiting on the owner (not snoozed) that no push has announced yet.
    A card back from a snooze needs a fresh one."""
    if r.get("state") != "waiting" or snoozed(r, now):
        return False
    pushed = parse_time(r.get(PUSHED))
    if pushed is None:
        return True
    back = parse_time(r.get("snoozeUntil"))
    return back is not None and pushed < back <= now


def by_state(rows, state):
    return [r for r in rows if r.get("state") == state]


def counts(rows, now):
    waiting = by_state(rows, "waiting")
    return len([r for r in waiting if not snoozed(r, now)]), len(by_state(rows, "working"))


def news(rows):
    """Rule 14: the News tab, newest first."""
    return sorted(by_state(rows, "news"), key=lambda r: str(r.get("updatedAt") or r.get("since") or ""), reverse=True)


def footer(rows, now):
    """Rule 8: ✦ news (only when there is some), ☝︎ waiting, ∙•● working."""
    if not PAGE:
        sys.exit("no Desk configured: no .claude/desk.json with a page (run /desk:setup, or pass --desk)")
    n, m = counts(rows, now)
    k = len(by_state(rows, "news"))
    if k:
        return f"[✦ {k} · ☝︎ {n} · ∙•● {m}]({PAGE}#news)"
    return f"[☝︎ {n} · ∙•● {m}]({PAGE}#waiting)"


def rank_of(r):
    v = r.get("rank")
    return v if isinstance(v, (int, float)) else 99


def ordered(rows, now):
    """The waiting deck as the page shows it (rule 6), snoozed cards left out."""
    shown = [r for r in by_state(rows, "waiting") if not snoozed(r, now)]

    def recent(r):
        t = parse_time(r.get("activeAt"))
        return t if t and now - t < timedelta(hours=ACTIVE_HOURS) else None

    def key(r):
        a = recent(r)
        tier = 0 if r.get("kind") == "close" else 1 if a else 2
        return (tier, -(a.timestamp() if a else 0), rank_of(r))

    return sorted(shown, key=key)


def rank_key(r):
    # Rule 7: blocking first, then by kind; the old rank breaks ties, so order holds.
    return (0 if r.get("blocks") else 1, KIND_ORDER.get(r.get("kind"), 9), rank_of(r))


def reranked(rows):
    """New ranks for waiting cards: 1..n by rule 7; a row with rankByHand keeps its rank."""
    waiting = by_state(rows, "waiting")
    auto = sorted([r for r in waiting if not r.get("rankByHand")], key=rank_key)
    return {r.id: i + 1 for i, r in enumerate(auto)}


# ---------------------------------------------------------------- checks

def texts(r):
    d = r.data
    for k in ("title", "context", "ask", "recommend", "ifNone", "note", "blocks"):
        if isinstance(d.get(k), str):
            yield k, d[k]
    for i, f in enumerate(d.get("details") or []):
        yield f"details[{i}]", f"{f.get('title', '')}\n{f.get('text', '')}"
    for im in all_images(r):
        yield "images", im.get("caption", "")


def all_images(r):
    out = list(r.get("images") or [])
    for f in r.get("details") or []:
        out += f.get("images") or []
    return out


def session_ids(r):
    out = []
    for s in r.get("sessions") or []:
        m = SESSION.search(s.get("url", "") if isinstance(s, dict) else str(s))
        if m and m.group(0) not in out:
            out.append(m.group(0))
    return out


def prs(r):
    found = set()
    for l in r.get("links") or []:
        found |= set(PR.findall(l.get("url", "")))
    for _, t in texts(r):
        found |= set(PR.findall(t))
    return found


def load_sessions(path):
    if not path:
        return None
    raw = json.loads(Path(path).read_text())
    out = {}
    for k, v in raw.items():
        m = SESSION.search(k)
        k = m.group(0) if m else k
        v = (v.get("status_bucket") or v.get("status")) if isinstance(v, dict) else v
        # get_session says SESSION_STATUS_BUCKET_WORKING; "working" is the same.
        out[k] = re.sub(r"^SESSION_STATUS_BUCKET_", "", str(v)).lower()
    return out


def version_tag(name):
    """foo-v3.png -> ("foo", 3); names without a version give None."""
    m = re.match(r"(.*?)[-_.]?v(\d+)\.\w+$", name, re.I)
    return (m.group(1).lower(), int(m.group(2))) if m else None


def quoted(text, m):
    """A match inside quotes is a mention of the phrase, not a pointer at the chat."""
    return m.start() > 0 and text[m.start() - 1] in "\"“'‘"


def check(rows, now, sessions=None, stale_hours=12):
    """Problems, each (row id, message). Rules 1-5, 9, 12, 13 and 14."""
    out = []
    say = lambda r, msg: out.append((r.id, msg))
    open_rows = [r for r in rows if r.get("state") in ("waiting", "working")]

    for r in rows:
        st, kind = r.get("state"), r.get("kind")
        if st not in STATES:
            say(r, f"unknown state {st!r}")
        if st == "done":
            say(r, "state done: delete the row (no Done list, rule 9; Seen on a news item sets it when it can't delete)")
        if st in ("waiting", "working") and kind not in KINDS:
            say(r, f"unknown kind {kind!r}")
        # Wrap-ups are news now (rule 9).
        if kind == "close" and st != "done":
            say(r, f"a wrap-up (kind close): make it news: move {r.id} news (rule 9)")

        if st == "news":
            carried = [k for k in ("ask", "recommend", "ifNone") + ANSWER_FIELDS if k in r.data]
            if carried:
                say(r, f"news but carries {', '.join(carried)}: news is never a question; "
                       f"a question is a Waiting card (move {r.id} news drops them, rule 14)")
            if not str(r.get("title") or "").strip():
                say(r, "news with no title (rule 14)")

        if st == "waiting":
            stale = [k for k in ("answer", "answeredAt", "answerSent") if k in r.data]
            if r.get("quick") not in (None, "later"):
                stale.append("quick")
            if stale:
                say(r, f"waiting but still carries {', '.join(stale)}: move it to waiting again (rule 5)")
            for k in ("ask", "recommend"):
                if not str(r.get(k) or "").strip():
                    say(r, f"waiting with no {k} (rule 3)")
            if needs_push(r, now):
                say(r, "waiting and not pushed yet: push the owner (one push for all new ones), then `pushed` (rule 13)")

        if st == "working":
            ids = session_ids(r)
            if not ids:
                say(r, "working with no session behind it (rule 1)")
            elif sessions is not None:
                unseen = [s for s in ids if s not in sessions]
                if unseen:
                    say(r, f"sessions not checked: {', '.join(unseen)} (rule 12)")
                buckets = {s: sessions[s] for s in ids if s in sessions}
                if any(b == "blocked" for b in buckets.values()):
                    blocked = [s for s, b in buckets.items() if b == "blocked"]
                    say(r, f"session blocked: {', '.join(blocked)}: push the owner with what to approve")
                if buckets and not unseen and not any(b == "working" for b in buckets.values()):
                    shown = ", ".join(f"{s} {b}" for s, b in buckets.items())
                    say(r, f"working but no session is ({shown}): waiting if the owner is next, Later (scheduled, with when) if it's held for a release or a date, or close it; still working only while a session waits on its own CI (rule 1)")
            last = max([t for t in (parse_time(r.get("workingSince")), parse_time(r.get("updatedAt"))) if t], default=None)
            if last and now - last > timedelta(hours=stale_hours):
                say(r, f"working and untouched for {int((now - last).total_seconds() // 3600)} h")

        if st in ("waiting", "working", "news"):
            for field, t in texts(r):
                m = next((m for m in CHAT.finditer(t) if not quoted(t, m)), None)
                if m:
                    say(r, f"{field} points at the chat (“{m.group(0)}”): put it on the card (rule 3)")
            details = r.get("details") or []
            for i, f in enumerate(details):
                if f.get("images") and SUPERSEDED.search(f.get("title", "")):
                    say(r, f"images on a superseded fold, details[{i}] “{f.get('title')}”")
            fold_ids = {im.get("id") for f in details for im in f.get("images") or []}
            top_ids = {im.get("id") for im in r.get("images") or []}
            if fold_ids and top_ids:
                say(r, "images both on top and in folds: with folds, they go in the folds only (rule 4)")
            out.extend((r.id, m) for m in image_files_problems(r))
            if st != "news":
                out.extend((r.id, m) for m in deps_problems(r, rows))

    # One card per task (rule 2), and a wrap-up only once nothing else is open on it (rule 9).
    for i, a in enumerate(open_rows):
        for b in open_rows[i + 1:]:
            ha, hb = str(a.get("handle") or "").strip().lower(), str(b.get("handle") or "").strip().lower()
            shared_pr = prs(a) & prs(b)
            same = (ha and ha == hb) or (shared_pr and set(session_ids(a)) & set(session_ids(b)))
            if same:
                why = f"handle “{a.get('handle')}”" if ha and ha == hb else f"session and {sorted(shared_pr)[0]}"
                out.append((a.id, f"same task as {b.id} ({why}): one card per task (rule 2)"))
            if (ha and ha == hb) or shared_pr:
                for c, o in ((a, b), (b, a)):
                    if c.get("kind") == "close":
                        out.append((c.id, f"a wrap-up while {o.id} on the same task is open (rule 9)"))
    return out


def dep_state_of(card):
    """What an item linked to this card should read: done once the card is gone."""
    return "done" if card is None else DEP_OF_STATE.get(card.get("state"), "open")


def deps_problems(r, rows):
    """A card's dependsOn: each item well formed, each linked one in step with its card."""
    deps = r.get("dependsOn")
    if deps is None:
        return []
    if not isinstance(deps, list):
        return ["dependsOn is not a list"]
    by_id = {x.id: x for x in rows}
    out = []
    for i, d in enumerate(deps):
        if not isinstance(d, dict) or not str(d.get("item") or "").strip():
            out.append(f"dependsOn[{i}] has no item")
            continue
        item, st, cid = d["item"], d.get("state"), d.get("card")
        if st not in DEP_STATES:
            out.append(f"dependsOn “{item}”: state {st!r}, not done, building or open")
            continue
        if cid is None:
            continue
        if cid == r.id:
            out.append(f"dependsOn “{item}” links the card itself")
            continue
        want = dep_state_of(by_id.get(cid))
        if want != st:
            now = "gone" if cid not in by_id else by_id[cid].get("state")
            out.append(f"“{item}” is {want} (card {cid} is {now}), the card says {st}; refresh it: "
                       f"dep <rows> {r.id} \"{item}\" {want} (rule 2)")
    if deps and all(isinstance(d, dict) and d.get("state") == "done" for d in deps):
        out.append("everything in dependsOn is done: nothing left blocking it: ask or close")
    return out


def image_files_problems(r):
    """Best effort: image files the card mentions (text or links) that no image holds."""
    held = {str(im.get("file", "")).lower() for im in all_images(r) if im.get("file")}
    held |= {m.lower() for im in all_images(r) for m in IMAGE_FILE.findall(im.get("caption", ""))}
    mentioned = set()
    for l in r.get("links") or []:
        mentioned |= {m.lower() for m in IMAGE_FILE.findall(l.get("url", "") + " " + l.get("label", ""))}
    for f, t in texts(r):
        if f != "images":
            mentioned |= {m.lower() for m in IMAGE_FILE.findall(t)}
    out = []
    held_v = {}
    for h in held:
        v = version_tag(Path(h).name)
        if v:
            held_v[v[0]] = max(held_v.get(v[0], 0), v[1])
    for m in sorted(mentioned):
        name = Path(m).name
        v = version_tag(name)
        if v and v[0] in held_v and v[1] > held_v[v[0]]:
            out.append(f"mentions {name}, newer than the v{held_v[v[0]]} its images hold (rule 4)")
        elif held and name not in {Path(h).name for h in held} and not (v and v[0] in held_v):
            out.append(f"mentions {name}, which no image on the card holds (rule 4)")
    return out


# ---------------------------------------------------------------- rule reload

# What a session holds in its head: when a clone's HEAD changed one of these after it read
# them, it must re-read before its next message (2026-10-25). The plugin's own clone counts
# too: its skills, commands and page are rules, and a new page means the keeper republishes
# its Desk. prep never fetches (2026-10-26): `update` pulls the plugin, and any pull counts.
RULE_PATHS = ("CLAUDE.md", "memory/MEMORY.md", ".claude/skills", ".claude/desk.json",
              "skills", "page/desk.html")
PAGE_PATH = "page/desk.html"
LOADED = Path(os.environ.get("DESK_LOADED") or Path.home() / ".cache" / "desk" / "loaded.json")
PULL_SECONDS = 60


def git(repo, *args, timeout=PULL_SECONDS):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["git failed"])[-1])
    return r.stdout.strip()


def git_root(path):
    try:
        return Path(git(path, "rev-parse", "--show-toplevel"))
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None


def plugin_clone():
    """The plugin's clone: the one this script runs from, else ~/.claude/desk, else None."""
    for c in (PLUGIN_REPO, PLUGIN_HOME):
        if (Path(c) / ".git").exists():
            return Path(c)
    return None


def rule_repos(given=None):
    """The project's clone (where desk.json sits), the plugin's clone (plugin_clone), and the
    clones desk.json names under "watch" that exist here."""
    if given:
        return [Path(g) for g in given]
    cands = []
    if CONFIG_PATH:
        cands.append(git_root(CONFIG_PATH.parent))
    cands.append(plugin_clone())
    cands += [Path(w) for w in CONFIG.get("watch") or [] if (Path(w) / ".git").exists()]
    out, seen = [], set()
    for c in cands:
        if c and c.resolve() not in seen:
            seen.add(c.resolve())
            out.append(c)
    return out


def load_loaded(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def reload_check(repos, state_path):
    """(stale, warnings): stale is [(repo, files, loaded, head)] for each repo whose HEAD
    changed a rule file since it was loaded. No network: it only reads the clones."""
    loaded, stale, warns = load_loaded(state_path), [], []
    for repo in repos:
        key = str(Path(repo).resolve())
        try:
            head = git(repo, "rev-parse", "HEAD")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            warns.append(f"{repo}: no HEAD, not checked ({e})")
            continue
        # Nothing recorded yet: what's checked out is what the session read at start.
        base = loaded.get(key) or head
        if not loaded.get(key):
            warns.append(f"{repo}: nothing marked loaded; taking HEAD {base[:7]} (run `loaded` after reading)")
        if base == head:
            continue
        try:
            files = git(repo, "diff", "--name-only", base, head, "--", *RULE_PATHS).split()
        except (RuntimeError, OSError):
            files = list(RULE_PATHS)  # the loaded commit is unknown here: reload them all
        if files:
            stale.append((repo, files, base, head))
    return stale, warns


def mark_loaded(repos, state_path):
    """Record each clone's HEAD as read. Returns warnings for clones left behind origin/main."""
    state, warns = load_loaded(state_path), []
    for repo in repos:
        head = git(repo, "rev-parse", "HEAD")
        state[str(Path(repo).resolve())] = head
        try:
            behind = git(repo, "diff", "--name-only", head, "origin/main", "--", *RULE_PATHS).split()
        except (RuntimeError, OSError):
            behind = []
        if behind:
            warns.append(f"{repo}: HEAD is behind origin/main on {', '.join(behind)}: pull, re-read, mark again")
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(state, indent=2) + "\n")
    return state, warns


def pull_plugin(home, url=PLUGIN_URL):
    """Clone the plugin to home, or pull it there. Returns (before, after, warnings)."""
    home = Path(home)
    try:
        if not (home / ".git").exists():
            home.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "clone", "--quiet", str(url), str(home)],
                               capture_output=True, text=True, timeout=PULL_SECONDS)
            if r.returncode:
                raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or ["git clone failed"])[-1])
            return None, git(home, "rev-parse", "HEAD"), []
        before = git(home, "rev-parse", "HEAD")
        git(home, "pull", "--quiet", "--ff-only", "origin", "main")
        return before, git(home, "rev-parse", "HEAD"), []
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        head = git(home, "rev-parse", "HEAD") if (home / ".git").exists() else None
        return head, head, [f"{home}: pull failed, judged on what's there ({e})"]


def print_stale(stale):
    """What to re-read, and whether the page must be republished."""
    for repo, files, base, head in stale:
        print(f"  {repo} ({base[:7]} -> {head[:7]}): {', '.join(files)}")
    if any(PAGE_PATH in files for _, files, _, _ in stale):
        print(f"The page changed too: republish the Desk in place "
              f"(python3 {Path(__file__).name} page --out <file>, then Artifact publish to its url).")


# ---------------------------------------------------------------- patches

def write_patch(rows_d, row, patch, if_version, out_dir=None):
    """Save the patch file, apply it locally, and return the batch entry to send."""
    pd = Path(out_dir) if out_dir else rows_dir(rows_d).parent / "patches"
    pd.mkdir(parents=True, exist_ok=True)
    pf = pd / f"{row.id}.json"
    pf.write_text(json.dumps(patch, ensure_ascii=False, indent=2) + "\n")
    version = if_version if if_version is not None else row.version
    for k, v in patch.items():
        if v == DELETE:
            row.data.pop(k, None)
        else:
            row.data[k] = v
    # Once written, the server's version moves on; the write's result names the new one.
    row.version = None
    row.save()
    spend_version(row)
    entry = {"op": "update", "collection": COLLECTION, "doc_id": row.id, "file_path": str(pf.resolve())}
    if version is not None:
        entry["if_version"] = version
    return entry


def spend_version(row):
    """Forget a written bare row's version, so a second write must be pinned anew."""
    d = row.path.parent
    for base in (d, d.parent):
        j, t = base / "_versions.json", base / "_versions.txt"
        if j.exists() or t.exists():
            v = load_versions(d)
            v.pop(row.id, None)
            if t.exists():
                t.unlink()
            j.write_text(json.dumps(v, indent=2) + "\n")
            return


def delete_entry(row, if_version):
    version = if_version if if_version is not None else row.version
    entry = {"op": "delete", "collection": COLLECTION, "doc_id": row.id}
    if version is not None:
        entry["if_version"] = version
    row.path.unlink()
    spend_version(row)
    return entry


def dependents(rows, cid, state):
    """Patches for the cards whose dependsOn links cid, its items set to state.
    Each is (row, patch); a card whose items already read state gets none."""
    out = []
    for r in rows:
        deps = r.get("dependsOn")
        if r.id == cid or not isinstance(deps, list):
            continue
        hit = [d for d in deps if isinstance(d, dict) and d.get("card") == cid]
        if not hit or all(d.get("state") == state for d in hit):
            continue
        new = [dict(d, state=state) if isinstance(d, dict) and d.get("card") == cid else d for d in deps]
        out.append((r, {"dependsOn": new}))
    return out


def find_dep(deps, item):
    """The index of an item: by its card id, its text, or a unique prefix of it."""
    key = item.strip().lower()
    for how in (lambda d: str(d.get("card") or "").lower() == key,
                lambda d: str(d.get("item") or "").strip().lower() == key,
                lambda d: str(d.get("item") or "").strip().lower().startswith(key)):
        hits = [i for i, d in enumerate(deps) if isinstance(d, dict) and how(d)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"“{item}” matches {len(hits)} items: give more of it")
    return None


def set_dep(row, item, state, card=None, add=False):
    """The patch setting one dependsOn item's state (and its card), or adding it."""
    if state not in DEP_STATES:
        raise ValueError(f"state {state!r}: done, building or open")
    deps = json.loads(json.dumps(row.get("dependsOn") or []))
    i = find_dep(deps, item)
    if i is None:
        if not add:
            raise ValueError(f"{row.id} has no item “{item}” (add it with --add)")
        deps.append({"item": item, **({"card": card} if card else {}), "state": state})
    else:
        deps[i]["state"] = state
        if card:
            deps[i]["card"] = card
    return {"dependsOn": deps}


def settled_fold(details, text):
    details = [f for f in (details or []) if f.get("title") != "Settled so far"]
    return [{"title": "Settled so far", "text": text}] + details


def move(row, to, now, note=None, ask=None, recommend=None, ifnone=None, settled=None,
         session=None, active=False, context=None):
    """The patch for a move (rules 1, 5, 9, 14). None for done: the row is deleted."""
    if to == "done":
        return None
    d = row.data
    patch = {"state": to, "updatedAt": iso(now)}
    if context is not None:
        patch["context"] = context
    if to == "news":
        # Rule 14: something to know, cleared by Seen; nothing to answer, rank or push.
        if any(v is not None for v in (ask, recommend, ifnone)):
            raise ValueError("news has no ask: a question is a Waiting card (rule 14)")
        for k in NEWS_DROPS:
            if k in d:
                patch[k] = DELETE
        return patch
    if active:
        patch["activeAt"] = iso(now)
    if note is not None:
        patch["note"] = note
    if session:
        label, _, url = session.partition("=") if "=" in session else ("Session", "", session)
        have = [s for s in d.get("sessions") or [] if s.get("url") != url]
        patch["sessions"] = [{"label": label, "url": url}] + have
    if to == "working":
        if d.get("state") != "working" or not d.get("workingSince"):
            patch["workingSince"] = iso(now)
        if ask is not None:
            patch["ask"] = ask
    if to == "waiting":
        # Rule 5: the old answer leaves when the card waits on the owner again.
        for k in ANSWER_FIELDS + ("workingSince", "snoozeUntil", PUSHED):
            if k in d:
                patch[k] = DELETE
        if note is None and "note" in d:
            patch["note"] = DELETE
        for k, v in (("ask", ask), ("recommend", recommend), ("ifNone", ifnone)):
            if v is not None:
                patch[k] = v
        missing = [k for k in ("ask", "recommend") if not str(patch.get(k, d.get(k)) or "").strip()]
        if missing:
            raise ValueError(f"a waiting card needs {' and '.join(missing)} (rule 3)")
        if d.get("answer") and ask is None:
            raise ValueError("its ask was answered: give the new question with --ask (rules 1, 5)")
    if settled is not None:
        patch["details"] = settled_fold(d.get("details"), settled)
    return patch


def parse_images(specs, json_file):
    out = []
    if json_file:
        out += json.loads(Path(json_file).read_text())
    for s in specs or []:
        iid, _, cap = s.partition("=")
        out.append({"id": iid.strip(), "caption": cap.strip()})
    for im in out:
        if not re.fullmatch(r"[0-9a-f]{32}", str(im.get("id", ""))):
            raise ValueError(f"not an asset id: {im.get('id')!r}")
    return out


def fold_index(details, fold):
    if re.fullmatch(r"\d+", fold):
        i = int(fold) - 1
        if not 0 <= i < len(details):
            raise ValueError(f"fold {fold}: the card has {len(details)} folds (numbered from 1)")
        return i
    hits = [i for i, f in enumerate(details) if f.get("title", "").lower().startswith(fold.lower())]
    if len(hits) != 1:
        raise ValueError(f"fold {fold!r} matches {len(hits)} folds")
    return hits[0]


def set_images(row, images, fold=None, drop_top=False):
    """The patch setting a card's or a fold's images, and the asset ids now unused."""
    d = row.data
    before = {im.get("id") for im in all_images(row)}
    patch = {}
    details = json.loads(json.dumps(d.get("details") or []))
    top = list(d.get("images") or [])
    if fold is None:
        top = images
        patch["images"] = images
    else:
        i = fold_index(details, fold)
        details[i]["images"] = images
        patch["details"] = details
        if drop_top:
            top = []
            patch["images"] = DELETE
    after = {im.get("id") for im in top} | {im.get("id") for f in details for im in f.get("images") or []}
    return patch, sorted(before - after)


# ---------------------------------------------------------------- the Inbox (rule 15)

def inbox_dir(d):
    """Where the notes were dumped: <out_dir>/inbox beside <out_dir>/tasks."""
    d = Path(d)
    for c in (d / INBOX, rows_dir(d).parent / INBOX):
        if c.is_dir():
            return c
    return None


def load_inbox(d):
    i = inbox_dir(d)
    if not i:
        return []
    notes = [load_row(p) for p in sorted(i.glob("*.json")) if not p.name.startswith("_")]
    versions = load_versions(i)
    for n in notes:
        if n.version is None and n.id in versions:
            n.version = versions[n.id]
    return sorted(notes, key=lambda n: str(n.get("at") or ""))


def note_id(text, at):
    return "n-" + at.strftime("%Y%m%d%H%M%S") + "-" + hashlib.sha1(text.encode()).hexdigest()[:4]


def new_note(text, origin, now, images=None):
    row = {"text": text.strip(), "from": origin, "at": iso(now)}
    if images:
        row["images"] = images
    return row


def entry_for(collection, doc_id, file_path, op="set", if_version=None):
    e = {"op": op, "collection": collection, "doc_id": doc_id, "file_path": str(Path(file_path).resolve())}
    if if_version is not None:
        e["if_version"] = if_version
    return e


# ---------------------------------------------------------------- the look (rule 16)

def look_doc(theme=None, emoji=None, image=None, letter=None, current=None):
    """The settings/look row: {"theme", "icon": {"emoji"} | {"image": asset id} | {"letter"}}."""
    doc = dict(current or {})
    if theme:
        if theme.lower() not in THEMES:
            sys.exit(f"unknown theme {theme!r}: one of {', '.join(THEMES)}")
        doc["theme"] = theme.lower()
    if emoji or image or letter:
        if image and not re.fullmatch(r"[0-9a-f]{32}", image):
            sys.exit("an image icon is the asset id the upload returned (32 hex characters)")
        doc["icon"] = {"emoji": emoji} if emoji else {"image": image} if image else {"letter": letter[:2]}
    return doc


# ---------------------------------------------------------------- the page

def render_page(template, cfg):
    """The template with this Desk's title, keeper link and first look filled in."""
    title = cfg.get("title") or "Desk"
    look = cfg.get("look") or {}
    theme = (look.get("theme") or "frost").lower()
    if theme not in THEMES:
        sys.exit(f"desk.json look.theme {theme!r} is not one of {', '.join(THEMES)}")
    keeper = cfg.get("keeper") or ""
    if keeper and not keeper.startswith("https://"):
        keeper = "https://claude.ai/code/" + keeper
    html = template
    for k, v in (("DESK_TITLE", title), ("DESK_THEME", theme), ("DESK_KEEPER", keeper),
                 ("DESK_ICON", json.dumps(look.get("icon") or {}, ensure_ascii=False))):
        html = html.replace("{{" + k + "}}", v.replace("<", "&lt;") if k != "DESK_ICON" else v.replace("<", "\\u003c"))
    left = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if left:
        sys.exit(f"the template has unknown placeholders: {', '.join(sorted(set(left)))}")
    return html


# ---------------------------------------------------------------- feedback (rule 17)

URL = re.compile(r"https?://[^\s)\]>\"']+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
REPO = re.compile(r"\b[\w.-]+/[\w.-]+\b")
OWN = ("https://github.com/bagrat/claude-plugin-desk", "https://github.com/bagrat/claude-plugin-marketplace")


def leaks(text, rows, notes=()):
    """What in a feedback draft could come from a Desk's content: its cards' titles, handles,
    ids, links and sessions, its notes, any URL or address outside the plugin's own repos.
    Each is (what, why). Best effort: the owner still reads the draft before it's public."""
    out, low = [], text.lower()
    def hit(s, why):
        s = str(s or "").strip()
        if len(s) >= 4 and s.lower() in low and (s, why) not in out:
            out.append((s, why))
    for r in list(rows) + list(notes):
        d = r.data
        hit(r.id, "a card id")
        for k in ("title", "handle", "text"):
            hit(d.get(k), f"a card's {k}" if k != "text" else "a note")
        for l in (d.get("links") or []) + (d.get("sessions") or []):
            hit(l.get("url"), "a card's link")
            hit(l.get("label"), "a card's link label")
        for im in all_images(r):
            hit(im.get("file"), "an image file")
    if CONFIG.get("title"):
        hit(CONFIG["title"], "this Desk's name")
    for u in URL.findall(text):
        if not u.startswith(OWN):
            out.append((u, "a link outside the plugin's repos"))
    for e in EMAIL.findall(text):
        out.append((e, "an address"))
    for m in SESSION.findall(text):
        out.append((m, "a session id"))
    return out


def issue_url(title, body):
    return f"{PLUGIN_ISSUES}?title={quote(title)}&body={quote(body)}&labels=feedback"


# ---------------------------------------------------------------- commands

def cmd_check(a):
    rows, now = load_rows(a.rows), now_arg(a.now)
    problems = check(rows, now, load_sessions(a.sessions), a.stale_hours)
    for rid, msg in problems:
        print(f"{rid}: {msg}")
    return 1 if problems else 0


def short(text, n=90):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def cmd_inbox(a):
    notes = load_inbox(a.rows)
    for n in notes:
        bits = [n.get("at") or "?", n.get("from") or "?"]
        if n.get("images"):
            bits.append(f"{len(n.get('images'))} image(s)")
        print(f"{n.id} [{', '.join(bits)}]\n  {n.get('text', '')}")
    if not notes:
        print("inbox: empty")
    return 0


def cmd_sorted(a):
    """Rule 15: a note leaves the Inbox once its card holds it."""
    notes = {n.id: n for n in load_inbox(a.rows)}
    out = []
    for nid in a.ids:
        n = notes.get(nid) or sys.exit(f"no note {nid!r} in the inbox dump")
        e = {"op": "delete", "collection": INBOX, "doc_id": n.id}
        if n.version is not None:
            e["if_version"] = n.version
        n.path.unlink()
        out.append(e)
    print(json.dumps(out, indent=2))
    return 0


def cmd_note(a):
    """A raw note for the Inbox, from any session on the Desk's account (/desk:note)."""
    if not PAGE:
        sys.exit("no Desk configured here: no .claude/desk.json (pass --desk, or run /desk:setup)")
    text = a.text if a.text is not None else sys.stdin.read()
    if not text.strip():
        sys.exit("an empty note")
    now = now_arg(a.now)
    nid = note_id(text, now)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{nid}.json"
    f.write_text(json.dumps(new_note(text, a.origin, now, parse_images(a.image, a.json) if (a.image or a.json) else None),
                            ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"page": PAGE, "keeper": CONFIG.get("keeper"), "write": entry_for(INBOX, nid, f)}, indent=2))
    return 0


def cmd_look(a):
    """Rule 16: the Desk's theme and icon, kept in its settings/look row."""
    cur = json.loads(Path(a.current).read_text()) if a.current else None
    if cur and isinstance(cur.get("data"), dict):
        cur = cur["data"]
    if a.list:
        print("\n".join(THEMES))
        return 0
    doc = look_doc(a.theme, a.emoji, a.image, a.letter, cur)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "look.json"
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(entry_for(SETTINGS, "look", f), indent=2))
    return 0


def cmd_page(a):
    """The page to publish: the template with this Desk's title, keeper and first look."""
    tpl = Path(a.template) if a.template else (plugin_clone() or PLUGIN_REPO) / PAGE_PATH
    html = render_page(tpl.read_text(), CONFIG)
    Path(a.out).write_text(html)
    print(f"wrote {a.out} for {CONFIG.get('title') or 'Desk'}"
          + (f": publish it to {PAGE}; when a publish is refused and hands back the live page, merge"
             " onto it and publish again until it goes through (the first switch is often refused twice)" if PAGE else ": publish it as a new artifact, then put its url in desk.json"))
    return 0


def cmd_scrub(a):
    """Rule 17: what in a feedback draft might carry the Desk's content. Exit 1 on any."""
    text = Path(a.draft).read_text()
    rows = load_rows(a.rows) if a.rows else []
    notes = load_inbox(a.rows) if a.rows else []
    found = leaks(text, rows, notes)
    for what, why in found:
        print(f"leak? {why}: {what}")
    if not found:
        print("scrub: nothing found (still read it before it goes public)")
    return 1 if found else 0


def cmd_issue_url(a):
    body = Path(a.body).read_text()
    found = leaks(a.title + "\n" + body, load_rows(a.rows) if a.rows else [], load_inbox(a.rows) if a.rows else [])
    if found and not a.force:
        for what, why in found:
            print(f"leak? {why}: {what}", file=sys.stderr)
        sys.exit("not making a link: scrub the draft first (or --force once the owner has read it)")
    u = issue_url(a.title, body)
    if len(u) > 8000:
        print("warning: the link is long; GitHub may cut it. Shorten the body.", file=sys.stderr)
    print(u)
    return 0


def cmd_footer(a):
    print(footer(load_rows(a.rows), now_arg(a.now)))
    return 0


def describe(r):
    bits = [r.get("kind") or "?"]
    if r.get("blocks"):
        bits.append("blocks " + r.get("blocks"))
    return f"{r.get('handle') or r.id} [{', '.join(bits)}] {r.get('title', '')}"


def cmd_order(a):
    rows, now = load_rows(a.rows), now_arg(a.now)
    deck = ordered(rows, now)
    items = news(rows)
    if items:
        print("News:")
        for r in items:
            print(f"  - {r.get('handle') or r.id}: {r.get('title', '')}")
    print("Waiting:")
    for i, r in enumerate(deck, 1):
        print(f"  {i}. {describe(r)}")
    later = [r for r in by_state(rows, "waiting") if snoozed(r, now)]
    if later:
        print("Later:")
        for r in later:
            print(f"  - {describe(r)} (back {r.get('snoozeUntil')})")
    print("In progress:")
    for r in sorted(by_state(rows, "working"), key=lambda r: str(r.get("workingSince") or r.get("updatedAt") or ""), reverse=True):
        print(f"  - {describe(r)}")
    return 0


def cmd_sessions(a):
    seen = []
    for r in load_rows(a.rows):
        if r.get("state") in ("waiting", "working"):
            for s in session_ids(r):
                if s not in seen:
                    seen.append(s)
                    print(f"{s}\t{r.id}")
    return 0


def cmd_rank(a):
    rows = load_rows(a.rows)
    entries = []
    for rid, rank in reranked(rows).items():
        r = find(rows, rid)
        if r.get("rank") != rank:
            entries.append(write_patch(a.rows, r, {"rank": rank}, None, a.out))
    print(json.dumps(entries, indent=2))
    return 0


def cmd_move(a):
    rows, now = load_rows(a.rows), now_arg(a.now)
    r = find(rows, a.id)
    try:
        patch = move(r, a.to, now, a.note, a.ask, a.recommend, a.ifnone, a.settled, a.session, a.active, a.context)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if patch is None:
        entries = [delete_entry(r, a.if_version)]
    else:
        if a.to == "waiting" and r.get("answer") and a.settled is None:
            print(f"note: the old answer leaves: “{r.get('answer')}”. Keep what it settled with --settled.", file=sys.stderr)
        entries = [write_patch(a.rows, r, patch, a.if_version, a.out)]
        if "if_version" not in entries[0]:
            print("note: no version known; add if_version from the list result (or --if-version).", file=sys.stderr)
    # The cards waiting on this one: their item follows its state (done once it's deleted).
    for d, dp in dependents(rows, r.id, DEP_OF_STATE[a.to]):
        dp["updatedAt"] = iso(now)
        print(f"note: {d.id} depends on {r.id}: its item set to {DEP_OF_STATE[a.to]}.", file=sys.stderr)
        entries.append(write_patch(a.rows, d, dp, None, a.out))
    print(json.dumps(entries, indent=2))
    return 0


def cmd_pushed(a):
    """Rule 13: after the push, mark each card it announced."""
    rows, now = load_rows(a.rows), now_arg(a.now)
    entries = [write_patch(a.rows, find(rows, rid), {PUSHED: iso(now)}, None, a.out) for rid in a.ids]
    print(json.dumps(entries, indent=2))
    return 0


def cmd_dep(a):
    rows, now = load_rows(a.rows), now_arg(a.now)
    r = find(rows, a.id)
    if a.card and not any(x.id == a.card for x in rows):
        print(f"note: no card {a.card!r} in the rows: its item reads done.", file=sys.stderr)
    try:
        patch = set_dep(r, a.item, a.state, a.card, a.add)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    patch["updatedAt"] = iso(now)
    print(json.dumps(write_patch(a.rows, r, patch, a.if_version, a.out), indent=2))
    return 0


def cmd_images(a):
    rows = load_rows(a.rows)
    r = find(rows, a.id)
    try:
        images = parse_images(a.image, a.json)
        patch, gone = set_images(r, images, None if a.top else a.fold, a.drop_top)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    entry = write_patch(a.rows, r, patch, a.if_version, a.out)
    print(json.dumps({"write": entry, "delete_assets": gone}, indent=2))
    return 0


def cmd_prep(a):
    """Rule 12, before every message: the rules still current, the checks, the deck, the footer."""
    if not a.no_rules:
        stale, warns = reload_check(rule_repos(a.repo), a.state)
        for w in warns:
            print(f"warning: {w}", file=sys.stderr)
        if stale:
            print("Stop: the rules changed since you loaded them. Reload before this message:")
            print_stale(stale)
            print(f"Then re-read each file above (load the changed skills again) and run: "
                  f"python3 {Path(__file__).name} loaded. (/desk:update does all of it.)")
            return 1
    code = cmd_check(a)
    notes = load_inbox(a.rows)
    for n in notes:
        print(f"inbox {n.id}: sort this note into a card, then `sorted` (rule 15): {short(n.get('text'))}")
    code = code or (1 if notes else 0)
    if code == 0:
        print("check: ok")
    cmd_order(a)
    print()
    cmd_footer(a)
    return code


def cmd_loaded(a):
    state, warns = mark_loaded(rule_repos(a.repo), a.state)
    for w in warns:
        print(f"warning: {w}", file=sys.stderr)
    for repo, sha in state.items():
        print(f"loaded {repo} at {sha[:7]}")
    return 1 if warns else 0


def cmd_update(a):
    """/desk:update: pull the plugin's clone, then name what to re-read (exit 1 when any)."""
    before, after, warns = pull_plugin(a.home, a.url)
    repos = rule_repos(a.repo)
    if Path(a.home).resolve() not in {Path(r).resolve() for r in repos} and (Path(a.home) / ".git").exists():
        repos.append(Path(a.home))
    stale, more = reload_check(repos, a.state)
    for w in warns + more:
        print(f"warning: {w}", file=sys.stderr)
    if before is None and after:
        print(f"cloned {a.home} at {after[:7]}")
    elif after and before != after:
        print(f"pulled {a.home}: {before[:7]} -> {after[:7]}")
    if not stale:
        print(f"Desk is current at {(after or '?')[:7]}: nothing to re-read.")
        return 0
    print("Re-read these (load the changed skills again):")
    print_stale(stale)
    print(f"Then run: python3 {Path(__file__).name} loaded, and tell the owner in one line what changed.")
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="desk.py", description=__doc__.split("\n")[0])
    p.add_argument("--desk", help="the Desk's desk.json (default: the nearest .claude/desk.json, or $DESK_CONFIG)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def rules_args(s):
        s.add_argument("--state", default=str(LOADED), help="where the loaded commits are kept")
        s.add_argument("--repo", action="append", help="a clone to watch (default: the project's, the plugin's, and desk.json's watch)")

    s = sub.add_parser("loaded", help="mark the rules reloaded: after pulling and re-reading them")
    rules_args(s)
    s.set_defaults(fn=cmd_loaded)
    s = sub.add_parser("update", help="/desk:update: pull the plugin's clone, then name what to re-read")
    rules_args(s)
    s.add_argument("--home", default=str(PLUGIN_HOME), help="the plugin's clone (default: ~/.claude/desk)")
    s.add_argument("--url", default=PLUGIN_URL, help="where to clone it from when it's missing")
    s.set_defaults(fn=cmd_update)

    def cmd(name, fn, help):
        s = sub.add_parser(name, help=help)
        s.add_argument("rows", help="the rows directory (ArtifactData out_dir, or its tasks/)")
        s.add_argument("--now", help="ISO time to judge by (default: now)")
        s.set_defaults(fn=fn)
        return s

    for name, fn, help in (("check", cmd_check, "print problems; exit 1 if any"),
                           ("prep", cmd_prep, "check, order and footer: run before every message")):
        s = cmd(name, fn, help)
        s.add_argument("--sessions", help="JSON: session_id -> status_bucket, as seen")
        s.add_argument("--stale-hours", type=float, default=12)
        if name == "prep":
            rules_args(s)
            s.add_argument("--no-rules", "--no-fetch-rules", dest="no_rules", action="store_true",
                           help="skip the rule-reload check")
    cmd("footer", cmd_footer, "the footer line")
    cmd("order", cmd_order, "the order the page shows")
    cmd("sessions", cmd_sessions, "the sessions behind open cards, to check one by one")
    s = cmd("rank", cmd_rank, "re-rank waiting cards (rule 7); writes patches")
    s.add_argument("--out", help="where patch files go (default: <rows>/../patches)")

    s = cmd("move", cmd_move, "move a card; writes a patch")
    s.add_argument("id")
    s.add_argument("to", choices=["news", "working", "waiting", "done"])
    s.add_argument("--context", help="set the one-line context (a news item's summary)")
    s.add_argument("--note")
    s.add_argument("--ask")
    s.add_argument("--recommend")
    s.add_argument("--ifnone")
    s.add_argument("--settled", help="the text of the “Settled so far” fold, put at the top")
    s.add_argument("--session", help="add a session: 'Label=https://claude.ai/code/session_…'")
    s.add_argument("--active", action="store_true", help="set activeAt: the card under discussion")
    s.add_argument("--if-version", type=int)
    s.add_argument("--out")

    s = cmd("pushed", cmd_pushed, "mark waiting cards as announced by a push (rule 13); writes patches")
    s.add_argument("ids", nargs="+")
    s.add_argument("--out")

    s = cmd("dep", cmd_dep, "set one dependsOn item's state by hand; writes a patch")
    s.add_argument("id", help="the card that waits")
    s.add_argument("item", help="the item: its text, a unique prefix of it, or its card id")
    s.add_argument("state", choices=DEP_STATES)
    s.add_argument("--card", help="link the item to this card")
    s.add_argument("--add", action="store_true", help="add the item when the card has none by that name")
    s.add_argument("--if-version", type=int)
    s.add_argument("--out")

    s = cmd("images", cmd_images, "set a card's or a fold's images; writes a patch")
    s.add_argument("id")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--top", action="store_true", help="the top carousel (cards without folds)")
    g.add_argument("--fold", help="fold number from 1, or a title prefix")
    s.add_argument("--image", action="append", help="ID=caption, newest first; repeat")
    s.add_argument("--json", help="a JSON list of {id, caption, file?}")
    s.add_argument("--drop-top", action="store_true", help="with --fold: clear the top images")
    s.add_argument("--if-version", type=int)
    s.add_argument("--out")

    cmd("inbox", cmd_inbox, "the notes waiting to be sorted (rule 15)")
    s = cmd("sorted", cmd_sorted, "the deletes for notes now on cards (rule 15)")
    s.add_argument("ids", nargs="+")

    s = sub.add_parser("note", help="a note for this Desk's Inbox; writes the row file, prints the write")
    s.add_argument("--text", help="the note (default: read from stdin)")
    s.add_argument("--from", dest="origin", required=True, help="where it came from: a session link, a repo, 'chat'")
    s.add_argument("--image", action="append", help="ID=caption: an image already uploaded to the page")
    s.add_argument("--json", help="a JSON list of {id, caption}")
    s.add_argument("--out", required=True, help="the directory for the row file")
    s.add_argument("--now")
    s.set_defaults(fn=cmd_note)

    s = sub.add_parser("look", help="the Desk's theme and icon (rule 16); writes settings/look")
    s.add_argument("--theme", help="one of: " + ", ".join(THEMES))
    g = s.add_mutually_exclusive_group()
    g.add_argument("--emoji")
    g.add_argument("--image", help="the asset id of an icon uploaded to the page")
    g.add_argument("--letter", help="one or two letters on the accent")
    s.add_argument("--current", help="the settings/look row as read, to change only what's given")
    s.add_argument("--list", action="store_true", help="list the themes")
    s.add_argument("--out", default=".", help="the directory for look.json")
    s.set_defaults(fn=cmd_look)

    s = sub.add_parser("page", help="the page to publish, for this Desk")
    s.add_argument("--out", required=True)
    s.add_argument("--template", help="default: the plugin's page/desk.html")
    s.set_defaults(fn=cmd_page)

    s = sub.add_parser("scrub", help="flag what in a feedback draft might carry the Desk's content (rule 17)")
    s.add_argument("draft")
    s.add_argument("--rows", help="the rows dump, to check against its cards and notes")
    s.set_defaults(fn=cmd_scrub)

    s = sub.add_parser("issue-url", help="a prefilled new-issue link on the plugin's repo (rule 17)")
    s.add_argument("--title", required=True)
    s.add_argument("--body", required=True, help="a file with the body")
    s.add_argument("--rows")
    s.add_argument("--force", action="store_true", help="make it despite flags, once the owner has read it")
    s.set_defaults(fn=cmd_issue_url)

    a = p.parse_args(argv)
    load_config(a.desk)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
