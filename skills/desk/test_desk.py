"""Tests for desk.py. Run: python3 -m unittest discover -s skills/desk (or pytest)."""

import io
import os
import json
import re
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import desk as tasks  # noqa: E402

NOW = "2026-10-25T12:00:00Z"
A = "a" * 32
B = "b" * 32
C = "c" * 32
S1 = "https://claude.ai/code/session_01AAAA"
S2 = "https://claude.ai/code/session_01BBBB"


# Rule 3: enough context that a card can be decided from scratch.
FULL = "The background, the options and their trade-offs, and where it stands. " * 5


def waiting(**kw):
    row = {"state": "waiting", "kind": "decide", "title": "T", "context": FULL, "ask": "Which?",
           "recommend": "This one.", "pushedAt": "2026-10-25T11:00:00Z", "rank": 1}
    row.update(kw)
    return row


def working(**kw):
    row = {"state": "working", "kind": "do", "title": "W", "sessions": [{"label": "s", "url": S1}],
           "workingSince": "2026-10-25T11:00:00Z"}
    row.update(kw)
    return row


PAGE = "https://claude.ai/artifact/DESKTEST"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cfg = self.root / "desk.json"
        cfg.write_text(json.dumps({"title": "Test Desk", "page": PAGE, "timezone": "UTC"}))
        self._env = os.environ.get("DESK_CONFIG")
        os.environ["DESK_CONFIG"] = str(cfg)
        tasks.load_config()
        self.dir = self.root / "dump" / "tasks"
        self.dir.mkdir(parents=True)
        (self.root / "dump" / "inbox").mkdir()

    def tearDown(self):
        if self._env is None:
            os.environ.pop("DESK_CONFIG", None)
        else:
            os.environ["DESK_CONFIG"] = self._env
        self.tmp.cleanup()

    def put(self, rid, data, version=None):
        body = data if version is None else {"id": rid, "data": data, "version": version}
        (self.dir / f"{rid}.json").write_text(json.dumps(body))

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tasks.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def problems(self, sessions=None):
        rows = tasks.load_rows(self.root / "dump")
        return tasks.check(rows, tasks.parse_time(NOW), sessions)

    def msgs(self, rid, sessions=None):
        return [m for r, m in self.problems(sessions) if r == rid]

    def row(self, rid):
        raw = json.loads((self.dir / f"{rid}.json").read_text())
        return raw.get("data", raw) if "version" in raw else raw


class Loading(Base):
    def test_bare_and_wrapped_rows(self):
        self.put("bare", waiting())
        self.put("wrapped", waiting(), version=7)
        rows = {r.id: r for r in tasks.load_rows(self.root / "dump")}
        self.assertEqual(rows["bare"].version, None)
        self.assertEqual(rows["wrapped"].version, 7)
        self.assertEqual(rows["wrapped"].get("ask"), "Which?")

    def test_versions_from_the_pasted_list_result(self):
        self.put("search-box", waiting())
        self.put("intel", waiting())
        (self.root / "dump" / "_versions.txt").write_text(
            '15 documents from collection "tasks" saved as JSON files under "/x/tasks":\n'
            '- "intel"  1395 bytes  version 7  "/x/tasks/intel.json"\n'
            '- "search-box"  6056 bytes  version 25  "/x/tasks/search-box.json"\n')
        rows = {r.id: r.version for r in tasks.load_rows(self.root / "dump")}
        self.assertEqual(rows, {"intel": 7, "search-box": 25})
        code, out, _ = self.run_cli("move", self.dir, "intel", "working", "--note", "x")
        self.assertEqual(json.loads(out)[0]["if_version"], 7)
        # Spent: the next write to it isn't pinned to the old version; the others keep theirs.
        rows = {r.id: r.version for r in tasks.load_rows(self.root / "dump")}
        self.assertEqual(rows, {"intel": None, "search-box": 25})

    def test_accepts_the_tasks_dir_itself(self):
        self.put("x", waiting())
        self.assertEqual(len(tasks.load_rows(self.dir)), 1)


class Footer(Base):
    def test_counts_waiting_minus_snoozed_and_working(self):
        self.put("a", waiting())
        self.put("b", waiting(snoozeUntil="2026-10-26T05:00:00Z"))
        self.put("c", waiting(snoozeUntil="2026-10-25T05:00:00Z"))  # past: counts again
        self.put("d", working())
        self.put("e", {"state": "scheduled", "title": "r"})
        code, out, _ = self.run_cli("footer", self.root / "dump", "--now", NOW)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[● 2 ··· ◌ 1](https://claude.ai/artifact/DESKTEST#waiting)")


class Order(Base):
    def test_wrapups_then_discussed_then_rank(self):
        self.put("low", waiting(rank=1))
        self.put("mid", waiting(rank=2))
        self.put("wrap", waiting(kind="close", rank=9))
        self.put("talked", waiting(rank=8, activeAt="2026-10-25T11:00:00Z"))
        self.put("talked-later", waiting(rank=7, activeAt="2026-10-25T11:30:00Z"))
        self.put("old-talk", waiting(rank=3, activeAt="2026-10-25T08:00:00Z"))  # over 3 h ago
        self.put("later", waiting(rank=0, snoozeUntil="2026-10-26T05:00:00Z"))
        deck = [r.id for r in tasks.ordered(tasks.load_rows(self.dir), tasks.parse_time(NOW))]
        self.assertEqual(deck, ["wrap", "talked-later", "talked", "low", "mid", "old-talk"])

    def test_rank_puts_a_card_where_the_keeper_says_and_never_reorders_the_rest(self):
        # Rule 7: the keeper's priority is the order; no formula moves a card it ranked.
        self.put("review", waiting(kind="review", blocks="x", rank=3))
        self.put("check", waiting(kind="check", rank=1))
        self.put("decide", waiting(kind="decide", rank=2))
        self.put("customer", waiting(kind="decide", rank=11))
        self.put("held", waiting(kind="review", rank=1, heldAt="2026-10-01T09:00:00Z"))
        code, out, _ = self.run_cli("rank", self.dir)
        self.assertEqual((code, json.loads(out)), (0, []))  # nothing to reorder on its own
        code, out, err = self.run_cli("rank", self.dir, "customer", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual({e["doc_id"] for e in json.loads(out)}, {"customer", "check", "decide", "review"})
        ranks = {r: self.row(r)["rank"] for r in ("customer", "check", "decide", "review", "held")}
        self.assertEqual(ranks, {"customer": 1, "check": 2, "decide": 3, "review": 4, "held": 1})
        deck = [r.id for r in tasks.ordered(tasks.load_rows(self.dir), tasks.parse_time(NOW))]
        self.assertEqual(deck, ["customer", "check", "decide", "review"])

    def test_rank_moves_a_card_down_and_leaves_unranked_cards_alone(self):
        self.put("a", waiting(rank=1))
        self.put("b", waiting(rank=2))
        self.put("c", waiting(rank=3))
        new = waiting(); new.pop("rank")
        self.put("new", new)
        self.assertTrue(any("no priority yet" in m for m in self.msgs("new")))
        code, out, err = self.run_cli("rank", self.dir)
        self.assertIn("new: no priority yet", err)
        self.run_cli("rank", self.dir, "a", "3")
        self.assertEqual([self.row(r)["rank"] for r in "abc"], [3, 1, 2])
        self.assertNotIn("rank", self.row("new"))
        self.run_cli("rank", self.dir, "new", "2")
        self.assertEqual([self.row(r)["rank"] for r in ("b", "new", "c", "a")], [1, 2, 3, 4])
        self.assertEqual(self.msgs("new"), [])

    def test_rank_refuses_a_card_not_in_the_deck(self):
        self.put("w", working())
        self.put("h", waiting(heldAt="2026-10-01T09:00:00Z"))
        for rid in ("w", "h"):
            code, _, err = self.run_cli("rank", self.dir, rid, "1")
            self.assertEqual(code, 2, rid)
        code, _, err = self.run_cli("rank", self.dir, "h")
        self.assertEqual(code, 2)


class OwnerZone(Base):
    """Times the owner reads, and times written from what the owner said, are in desk.json's timezone."""

    def zone(self, tz):
        cfg = self.root / "desk.json"
        cfg.write_text(json.dumps({"title": "Test Desk", "page": PAGE, **({"timezone": tz} if tz else {})}))
        tasks.load_config()

    def test_when_reads_the_owners_words_in_their_zone(self):
        self.zone("America/New_York")
        code, out, _ = self.run_cli("when", "tomorrow 9:00", "--now", NOW)  # 08:00 in New York
        self.assertEqual(code, 0)
        self.assertEqual(out.split()[0], "2026-10-26T13:00:00Z")  # EDT, UTC-4
        self.assertIn("Mon 26 Oct 09:00 EDT", out)
        self.assertEqual(self.run_cli("when", "2026-11-02 9:00", "--now", NOW)[1].split()[0], "2026-11-02T14:00:00Z")  # EST
        self.assertEqual(self.run_cli("when", "today 17:30", "--now", NOW)[1].split()[0], "2026-10-25T21:30:00Z")
        # Late at night in New York it is already the next day in UTC; "tomorrow" is New York's.
        self.assertEqual(self.run_cli("when", "tomorrow 9:00", "--now", "2026-10-26T02:00:00Z")[1].split()[0], "2026-10-26T13:00:00Z")

    def test_when_shows_a_stored_time_in_the_owners_zone(self):
        self.zone("Asia/Tokyo")
        code, out, _ = self.run_cli("when", "2026-10-26T00:00:00Z")
        self.assertEqual(out.strip(), "2026-10-26T00:00:00Z  Mon 26 Oct 09:00 JST")
        with self.assertRaises(SystemExit):
            self.run_cli("when", "next week sometime")

    def test_order_shows_snoozes_in_the_owners_zone(self):
        self.zone("Asia/Tokyo")
        self.put("later", waiting(snoozeUntil="2026-10-26T00:00:00Z"))
        out = self.run_cli("order", self.dir, "--now", NOW)[1]
        self.assertIn("(back Mon 26 Oct 09:00 JST)", out)

    def test_no_zone_is_utc_and_prep_says_so(self):
        self.zone(None)
        self.assertEqual(self.run_cli("when", "tomorrow 9:00", "--now", NOW)[1].split()[0], "2026-10-26T09:00:00Z")
        self.put("a", waiting())
        code, out, err = self.run_cli("prep", self.dir, "--now", NOW, "--no-fetch-rules")
        self.assertIn("no timezone", err)
        self.zone("Asia/Tokyo")
        self.assertNotIn("no timezone", self.run_cli("prep", self.dir, "--now", NOW, "--no-fetch-rules")[2])

    def test_unknown_zone_is_refused(self):
        self.zone("Mars/Olympus")
        with self.assertRaises(SystemExit) as e:
            self.run_cli("when", "tomorrow 9:00")
        self.assertIn("Mars/Olympus", str(e.exception.code))


class Checks(Base):
    def test_clean_rows_pass(self):
        self.put("a", waiting())
        self.put("b", working())
        self.assertEqual(self.problems({"session_01AAAA": "working"}), [])
        code, out, _ = self.run_cli("check", self.dir, "--now", NOW)
        self.assertEqual((code, out), (0, ""))

    def test_waiting_with_stale_answer(self):
        self.put("a", waiting(answer="Go", answeredAt=NOW, quick="go"))
        self.assertTrue(any("answer, answeredAt, quick" in m for m in self.msgs("a")))

    def test_waiting_snoozed_quick_later_is_fine(self):
        self.put("a", waiting(quick="later", quickAt=NOW, snoozeUntil="2026-10-26T05:00:00Z"))
        self.assertEqual(self.msgs("a"), [])

    def test_waiting_needs_ask_and_recommend(self):
        self.put("a", waiting(ask="", recommend=None))
        m = self.msgs("a")
        self.assertTrue(any("no ask" in x for x in m))
        self.assertTrue(any("no recommend" in x for x in m))

    def test_working_without_session(self):
        self.put("a", working(sessions=[]))
        self.assertTrue(any("no session" in m for m in self.msgs("a")))

    def test_working_with_no_working_session(self):
        self.put("a", working(sessions=[{"url": S1}, {"url": S2}]))
        m = self.msgs("a", {"session_01AAAA": "completed", "session_01BBBB": "review_ready"})
        self.assertTrue(any("no session is" in x for x in m))
        self.assertEqual(self.msgs("a", {"session_01AAAA": "completed", "session_01BBBB": "working"}), [])

    def test_card_closes_at_the_end_of_its_step(self):
        # 4c: every session behind it completed: the step is over, the card closes this turn.
        self.put("a", working())
        msgs = [m for _, m in self.problems({"session_01AAAA": "completed"})]
        self.assertTrue(any("step is over" in m for m in msgs), msgs)
        msgs = [m for _, m in self.problems({"session_01AAAA": "idle"})]
        self.assertFalse(any("step is over" in m for m in msgs), msgs)
        self.assertTrue(any("working but no session is" in m for m in msgs), msgs)

    def test_a_row_past_8_kb_is_flagged_and_warned_on_write(self):
        self.put("a", waiting(details=[{"title": "Long", "text": "x" * 9000}]))
        self.assertTrue(any("past 8 KB" in m for _, m in self.problems()))
        self.put("b", working(context="y" * 8000))
        self.assertFalse(any(rid == "b" and "KB" in m for rid, m in self.problems()))
        code, out, err = self.run_cli("move", self.dir, "b", "working", "--now", NOW, "--note", "z" * 500)
        self.assertEqual(code, 0, err)
        self.assertIn("past 8 KB", err)

    def test_working_session_not_checked_or_blocked(self):
        self.put("a", working())
        self.assertTrue(any("not checked" in m for m in self.msgs("a", {})))
        self.assertTrue(any("blocked" in m for m in self.msgs("a", {"session_01AAAA": "blocked"})))

    def test_sessions_file_shapes(self):
        f = self.root / "s.json"
        f.write_text(json.dumps({"session_01AAAA": {"status_bucket": "SESSION_STATUS_BUCKET_WORKING"},
                                S2: "idle", "session_01CCCC": "SESSION_STATUS_BUCKET_REVIEW_READY"}))
        self.assertEqual(tasks.load_sessions(f), {"session_01AAAA": "working", "session_01BBBB": "idle",
                                                  "session_01CCCC": "review_ready"})

    def test_working_too_long(self):
        self.put("a", working(workingSince="2026-10-24T10:00:00Z", updatedAt="2026-10-24T11:00:00Z"))
        self.assertTrue(any("untouched for 25 h" in m for m in self.msgs("a")))

    def test_points_at_the_chat(self):
        self.put("a", waiting(context="The rest is in the chat above."))
        self.put("b", waiting(details=[{"title": "x", "text": "See the chat for the boards."}]))
        self.put("c", waiting(context='Never write "see the chat" on a card. ' + FULL))  # a quote, not a pointer
        self.assertTrue(any("points at the chat" in m for m in self.msgs("a")))
        self.assertTrue(any("details[0] points at the chat" in m for m in self.msgs("b")))
        self.assertEqual(self.msgs("c"), [])

    def test_question_to_owner_in_a_note_or_fold(self):
        # Issue 25: a question parked in an in-progress card's note never reaches Waiting.
        self.put("a", working(note="Two questions for you: (1) Do X? Recommended: yes. (2) Do Y? Recommended: yes."))
        self.put("b", {"state": "scheduled", "kind": "do", "title": "L", "when": "the release",
                       "details": [{"title": "Open", "text": "Your call: ship it Friday or Monday?"}]})
        self.put("c", working(context="Should we keep the old flag, or drop it?"))
        self.put("d", working(note="Tests pass; waiting on CI."))
        self.put("e", working(details=[{"title": "Settled so far", "text": "Ship Friday? Recommended: yes. Answer: yes."}]))
        self.put("f", working(note='Never write "your call" in a note.'))
        s = {"session_01AAAA": "working"}
        self.assertTrue(any("note asks the owner" in m and "move a waiting" in m for m in self.msgs("a", s)))
        self.assertTrue(any("details[0] asks the owner" in m for m in self.msgs("b", s)))
        self.assertTrue(any("context asks the owner" in m for m in self.msgs("c", s)))
        for rid in "def":
            self.assertEqual(self.msgs(rid, s), [], rid)

    def test_negated_or_settled_phrase_is_no_question(self):
        # Issue 29: a mention of the owner with no open question isn't one.
        quiet = [
            {"note": "Done; nothing waits on you"},
            {"note": "No question for you here."},
            {"note": "This isn't your call: the tests decide."},
            {"note": "None of it is waiting on you."},
            {"details": [{"title": "The plan (your call, 2026-01-01)", "text": "Ship it Friday."}]},
            {"note": "Picked Friday; it was your call."},
            {"note": "You decided on Friday; you chose the short name."},
        ]
        loud = [
            {"note": "Friday or Monday: your call?"},
            {"note": "You decide: Friday or Monday."},
            {"note": "Nothing is blocked. Your call: Friday or Monday."},
            {"note": "Done. Should we ship it Friday?"},
            {"note": "Not done yet; waits on you for the key."},
        ]
        s = {"session_01AAAA": "working"}
        for i, f in enumerate(quiet):
            self.put(f"q{i}", working(**f))
        for i, f in enumerate(loud):
            self.put(f"l{i}", working(**f))
        for i, f in enumerate(quiet):
            self.assertEqual(self.msgs(f"q{i}", s), [], f)
        for i, f in enumerate(loud):
            self.assertTrue(any("asks the owner" in m for m in self.msgs(f"l{i}", s)), f)

    def test_prep_message_flags_questions_on_no_card(self):
        self.put("a", waiting(ask="Merge the price box change now?", recommend="Yes, merge it."))
        draft = self.root / "draft.md"
        draft.write_text("Done with the menu.\n\n1. Merge the price box change now?\n"
                         "2. Rename the export button to Download?\nRecommended: rename it, it reads clearer.\n")
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules", "--message", draft)
        self.assertEqual(code, 1, out)
        self.assertIn("Rename the export button", out)
        self.assertNotIn("“Merge the price box", out)
        self.assertIn("rename it, it reads clearer", out)
        self.assertNotIn("check: ok", out)
        draft.write_text("All set: the menu shipped.\n")
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules", "--message", draft)
        self.assertEqual(code, 0, out)
        self.assertIn("check: ok", out)

    def test_same_handle_twice(self):
        self.put("a", waiting(handle="Price box"))
        self.put("b", working(handle="price box"))
        self.assertTrue(any("same task as b" in m for m in self.msgs("a")))

    def test_same_session_and_pr(self):
        pr = {"label": "PR", "url": "https://github.com/example/app/pull/89"}
        self.put("a", waiting(sessions=[{"url": S1}], links=[pr]))
        self.put("b", working(links=[pr]))
        self.put("c", waiting(sessions=[{"url": S2}], links=[pr], handle="other"))
        self.assertTrue(any("same task as b" in m for m in self.msgs("a")))
        self.assertFalse(any("same task" in m for m in self.msgs("c")))

    def test_shared_session_alone_is_fine(self):
        self.put("a", waiting(sessions=[{"url": S1}]))
        self.put("b", waiting(sessions=[{"url": S1}]))
        self.assertEqual(self.problems(), [])

    def test_wrapup_while_task_open(self):
        self.put("wrap", waiting(kind="close", handle="cleanup"))
        self.put("open", working(handle="cleanup"))
        self.assertTrue(any("wrap-up while open" in m for m in self.msgs("wrap")))

    def test_done_row_should_be_deleted(self):
        self.put("a", {"state": "done", "kind": "close"})
        self.assertTrue(any("delete the row" in m for m in self.msgs("a")))

    def test_images_top_and_folds(self):
        self.put("a", waiting(images=[{"id": A}], details=[{"title": "1", "text": "", "images": [{"id": B}]}]))
        self.assertTrue(any("both on top and in folds" in m for m in self.msgs("a")))

    def test_images_on_superseded_fold(self):
        self.put("a", waiting(details=[{"title": "Direction 2 (superseded)", "text": "", "images": [{"id": B}]}]))
        self.assertTrue(any("superseded fold" in m for m in self.msgs("a")))

    def test_mentions_newer_image_file(self):
        self.put("a", waiting(images=[{"id": A, "caption": "x", "file": "board-v2.png"}],
                              links=[{"label": "img", "url": "https://github.com/x/y/blob/b/board-v3.png"}]))
        self.assertTrue(any("board-v3.png, newer than the v2" in m for m in self.msgs("a")))

    def test_mentions_image_no_image_holds(self):
        self.put("a", waiting(images=[{"id": A, "file": "card-A.png"}], context="Redrawn: card-B.png."))
        self.assertTrue(any("card-b.png, which no image" in m for m in self.msgs("a")))

    def test_check_exit_code_and_prep(self):
        self.put("a", waiting(ask=""))
        code, out, _ = self.run_cli("check", self.dir, "--now", NOW)
        self.assertEqual(code, 1)
        self.assertIn("a: waiting with no ask", out)
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertEqual(code, 1)
        self.assertIn("Waiting:", out)
        self.assertIn("[● 1 ··· ◌ 0]", out)


class Move(Base):
    def test_back_to_waiting_clears_the_answer(self):
        self.put("a", working(ask="Old?", recommend="Old.", answer="Go", answeredAt=NOW, quick="go",
                              quickAt=NOW, answerSent=True, note="building", snoozeUntil="2026-10-20T05:00:00Z",
                              details=[{"title": "Settled so far", "text": "old"}, {"title": "B", "text": "b"}]),
                 version=4)
        code, out, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--ask", "New?",
                                      "--recommend", "Yes.", "--settled", "- You picked 1.")
        self.assertEqual(code, 0, err)
        entry, = json.loads(out)
        self.assertEqual(entry["if_version"], 4)
        self.assertEqual(entry["op"], "update")
        patch = json.loads(Path(entry["file_path"]).read_text())
        for k in ("answer", "answeredAt", "quick", "quickAt", "answerSent", "workingSince", "note", "snoozeUntil"):
            self.assertEqual(patch[k], {"__delete__": True}, k)
        self.assertEqual(patch["state"], "waiting")
        self.assertEqual(patch["ask"], "New?")
        self.assertEqual([f["title"] for f in patch["details"]], ["Settled so far", "B"])
        self.assertEqual(patch["details"][0]["text"], "- You picked 1.")
        # Applied locally, so the next check and footer see it; the version is spent.
        raw = json.loads((self.dir / "a.json").read_text())
        self.assertIsNone(raw["version"])
        self.assertNotIn("answer", raw["data"])
        # Newly waiting: what's left is its push (rule 13) and the keeper's priority for it (rule 7).
        push, rank = sorted(self.msgs("a"), key=lambda m: "rule 7" in m)
        self.assertIn("rule 13", push)
        self.assertIn("rank $R a N", rank)

    def test_waiting_after_an_answer_needs_a_new_ask(self):
        self.put("a", working(ask="Old?", recommend="Old.", answer="Go"))
        code, _, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW)
        self.assertEqual(code, 2)
        self.assertIn("--ask", err)

    def test_waiting_needs_recommend(self):
        self.put("a", working())
        code, _, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--ask", "Q?")
        self.assertEqual(code, 2)
        self.assertIn("recommend", err)

    def test_to_working(self):
        self.put("a", waiting())
        code, out, err = self.run_cli("move", self.dir, "a", "working", "--now", NOW, "--note", "On it.",
                                      "--session", f"Build={S2}", "--active", "--if-version", "3")
        self.assertEqual(code, 0, err)
        entry, = json.loads(out)
        self.assertEqual(entry["if_version"], 3)
        patch = json.loads(Path(entry["file_path"]).read_text())
        self.assertEqual(patch["state"], "working")
        self.assertEqual(patch["workingSince"], NOW)
        self.assertEqual(patch["activeAt"], NOW)
        self.assertEqual(patch["sessions"][0], {"label": "Build", "url": S2})
        self.assertIn("no version known", self.run_cli("move", self.dir, "a", "working")[2])

    def test_working_keeps_working_since(self):
        self.put("a", working(), version=1)
        _, out, _ = self.run_cli("move", self.dir, "a", "working", "--now", NOW, "--note", "x")
        patch = json.loads(Path(json.loads(out)[0]["file_path"]).read_text())
        self.assertNotIn("workingSince", patch)

    def test_done_deletes(self):
        self.put("a", waiting(kind="close"), version=9)
        code, out, _ = self.run_cli("move", self.dir, "a", "done")
        self.assertEqual(json.loads(out), [{"op": "delete", "collection": "tasks", "doc_id": "a", "if_version": 9}])
        self.assertFalse((self.dir / "a.json").exists())


class Numbers(Base):
    """A card's number is its place in the order (rule 1), not a stored id: 0.2.9's `num` goes."""

    def test_move_to_waiting_gives_no_number(self):
        self.put("c", working())
        code, out, err = self.run_cli("move", self.dir, "c", "waiting", "--now", NOW, "--ask", "Q?", "--recommend", "R.")
        self.assertEqual(code, 0, err)
        self.assertNotIn("num", json.loads(Path(json.loads(out)[0]["file_path"]).read_text()))
        self.assertNotIn("num", self.row("c"))

    def test_leftover_num_and_rank_by_hand_are_flagged_and_dropped(self):
        self.put("a", waiting(num=3, rankByHand=True))
        self.put("n", {"state": "news", "title": "Shipped", "num": 4})
        self.assertTrue(any("carries num, rankByHand" in m for m in self.msgs("a")))
        self.assertTrue(any("carries num" in m for m in self.msgs("n")))
        code, out, _ = self.run_cli("rank", self.dir)
        self.assertEqual(code, 0)
        patches = {e["doc_id"]: json.loads(Path(e["file_path"]).read_text()) for e in json.loads(out)}
        self.assertEqual(patches["a"], {"num": {"__delete__": True}, "rankByHand": {"__delete__": True}})
        self.assertEqual(patches["n"], {"num": {"__delete__": True}})
        self.assertEqual(self.msgs("a") + self.msgs("n"), [])

    def test_order_shows_places_not_numbers(self):
        self.put("b", waiting(num=12, rank=2, handle="ship-date", title="Pick the ship date"))
        self.put("a", waiting(num=13, rank=1, handle="logo", title="Pick the logo"))
        _, out, _ = self.run_cli("order", self.dir, "--now", NOW)
        self.assertIn("1. logo [decide]", out)
        self.assertIn("2. ship-date [decide]", out)
        self.assertNotIn("#", out)


class FullContext(Base):
    """Rule 3: a waiting card holds everything; a thin one, with no folds, is flagged."""

    def test_thin_card_is_flagged(self):
        self.put("thin", waiting(context="Pick one."))
        self.put("bare", waiting(context=None))
        self.put("folded", waiting(context="Short.", details=[{"title": "The options", "text": "…"}]))
        self.put("full", waiting())
        self.put("step", waiting(kind="step", context="", links=[{"label": "Form", "url": "https://example.test/f"}]))
        self.assertTrue(any("thin card" in m for m in self.msgs("thin")))
        self.assertTrue(any("thin card" in m for m in self.msgs("bare")))
        for rid in ("folded", "full", "step"):
            self.assertEqual(self.msgs(rid), [], rid)


class Steps(Base):
    """Rule 10: a step only the owner can do off the page (kind step): its link is the main button."""
    LINK = "https://example.test/form"

    def test_do_card_needs_its_link(self):
        self.put("a", waiting(kind="step", ask="Submit the form.", recommend=None))
        m, = self.msgs("a")
        self.assertIn("link", m)
        self.assertIn("rule 10", m)

    def test_do_card_with_link_needs_no_recommendation(self):
        self.put("a", waiting(kind="step", ask="Submit the form.", recommend=None,
                              links=[{"label": "Open the form", "url": self.LINK}]))
        self.assertEqual(self.msgs("a"), [])

    def test_move_waiting_as_a_step(self):
        self.put("a", working(), version=2)
        code, out, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--kind", "step",
                                      "--ask", "Submit the form.", "--link", f"Open the form={self.LINK}")
        self.assertEqual(code, 0, err)
        patch = json.loads(Path(json.loads(out)[0]["file_path"]).read_text())
        self.assertEqual(patch["kind"], "step")
        self.assertEqual(patch["links"][0], {"label": "Open the form", "url": self.LINK})

    def test_link_goes_first_once(self):
        self.put("a", working(links=[{"label": "Docs", "url": "https://example.test/docs"},
                                     {"label": "Old", "url": self.LINK}]))
        _, out, _ = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--kind", "step",
                                 "--ask", "Submit it.", "--link", f"Open the form={self.LINK}")
        patch = json.loads(Path(json.loads(out)[0]["file_path"]).read_text())
        self.assertEqual([l["url"] for l in patch["links"]], [self.LINK, "https://example.test/docs"])

    def test_a_do_card_is_still_work(self):
        self.put("a", working())
        code, _, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--ask", "Q?", "--recommend", "Yes.")
        self.assertEqual(code, 0, err)

    def test_move_refuses_a_step_without_a_link(self):
        self.put("a", working())
        code, _, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--kind", "step",
                                    "--ask", "Submit the form.")
        self.assertEqual(code, 2)
        self.assertIn("--link", err)


class Pushes(Base):
    """Rule 13: a new waiting card gets a push."""

    def test_new_waiting_card_needs_a_push(self):
        self.put("a", waiting(pushedAt=None))
        self.assertTrue(any("not pushed" in m and "rule 13" in m for m in self.msgs("a")))
        self.put("b", working())
        self.assertEqual(self.msgs("b", {"session_01AAAA": "working"}), [])

    def test_snoozed_card_needs_none_until_it_is_back(self):
        self.put("a", waiting(pushedAt=None, snoozeUntil="2026-10-26T05:00:00Z", quick="later"))
        self.assertEqual(self.msgs("a"), [])
        # Back from the snooze: the push before it doesn't count.
        self.put("b", waiting(pushedAt="2026-10-24T09:00:00Z", snoozeUntil="2026-10-25T05:00:00Z", quick="later"))
        self.assertTrue(any("rule 13" in m for m in self.msgs("b")))
        self.put("c", waiting(pushedAt="2026-10-25T05:01:00Z", snoozeUntil="2026-10-25T05:00:00Z", quick="later"))
        self.assertEqual(self.msgs("c"), [])

    def test_pushed_marks_the_cards(self):
        self.put("a", waiting(pushedAt=None), version=2)
        self.put("b", waiting(pushedAt=None), version=5)
        code, out, err = self.run_cli("pushed", self.dir, "a", "b", "--now", NOW)
        self.assertEqual(code, 0, err)
        entries = json.loads(out)
        self.assertEqual([(e["doc_id"], e["if_version"]) for e in entries], [("a", 2), ("b", 5)])
        for e in entries:
            self.assertEqual(json.loads(Path(e["file_path"]).read_text()), {"pushedAt": NOW})
        self.assertEqual(self.problems(), [])

    def test_a_new_question_needs_a_new_push(self):
        self.put("a", waiting(answer="Go", answeredAt=NOW, quick="go"))
        code, out, err = self.run_cli("move", self.dir, "a", "waiting", "--now", NOW, "--ask", "Next?")
        self.assertEqual(code, 0, err)
        patch = json.loads(Path(json.loads(out)[0]["file_path"]).read_text())
        self.assertEqual(patch["pushedAt"], {"__delete__": True})


class Apply(Base):
    """One call for a turn's writes (4a): one batch, each row written once, pinned to its read."""

    def plan(self, plan):
        f = self.root / "plan.json"
        f.write_text(json.dumps(plan))
        return self.run_cli("apply", self.dir, f, "--now", NOW)

    def test_moves_images_ranks_and_pushes_in_one_batch(self):
        self.put("a", working(), version=3)
        self.put("b", waiting(rank=1), version=4)
        self.put("c", waiting(dependsOn=[{"item": "a's work", "card": "a", "state": "building"}], rank=2), version=5)
        (self.root / "dump" / "inbox" / "n-1.json").write_text(json.dumps({"text": "x", "from": "page", "at": NOW}))
        code, out, err = self.plan({
            "moves": [{"id": "a", "to": "waiting", "ask": "Ship it?", "recommend": "Yes.", "context": FULL}],
            "images": [{"id": "a", "top": True, "images": [{"id": A, "caption": "the screen"}]}],
            "rank": [{"id": "a", "place": 1}],
            "pushed": ["a"],
            "sorted": ["n-1"]})
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        by = {(w["collection"], w["doc_id"]): w for w in res["writes"]}
        # Each row once, pinned to the version it was read at.
        self.assertEqual(len(res["writes"]), len(by))
        self.assertEqual(by[("tasks", "a")]["if_version"], 3)
        self.assertEqual(by[("tasks", "b")]["if_version"], 4)
        self.assertEqual(by[("tasks", "c")]["if_version"], 5)
        self.assertEqual(by[("inbox", "n-1")]["op"], "delete")
        a = json.loads(Path(by[("tasks", "a")]["file_path"]).read_text())
        self.assertEqual((a["state"], a["rank"], a["pushedAt"], a["images"][0]["id"]), ("waiting", 1, NOW, A))
        self.assertNotIn("workingSince", tasks.load_rows(self.dir)[0].data)
        c = json.loads(Path(by[("tasks", "c")]["file_path"]).read_text())
        self.assertEqual(c["dependsOn"][0]["state"], "open")
        self.assertEqual(c["rank"], 3)
        self.assertEqual(self.problems(), [])

    def test_a_refused_step_writes_nothing(self):
        self.put("a", working(), version=3)
        self.put("b", waiting(), version=4)
        before = (self.dir / "a.json").read_text()
        code, out, err = self.plan({"pushed": ["b"], "moves": [{"id": "a", "to": "waiting"}]})
        self.assertEqual(code, 2)
        self.assertIn("move a", err)
        self.assertEqual(out, "")
        self.assertEqual((self.dir / "a.json").read_text(), before)
        self.assertFalse((self.root / "dump" / "patches").exists())

    def test_done_is_a_delete_and_unknown_keys_are_refused(self):
        self.put("a", working(), version=3)
        code, out, err = self.plan({"moves": [{"id": "a", "to": "done"}], "pushed": ["a"]})
        self.assertEqual(code, 2)
        self.assertIn("no row 'a'", err)
        code, out, err = self.plan({"moves": [{"id": "a", "to": "done"}]})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["writes"], [{"op": "delete", "collection": "tasks", "doc_id": "a", "if_version": 3}])
        code, out, err = self.plan({"move": []})
        self.assertEqual(code, 2)
        self.assertIn("unknown plan keys", err)

    def test_swapped_images_are_named_for_deletion(self):
        self.put("a", waiting(images=[{"id": A, "caption": "old"}]), version=1)
        code, out, err = self.plan({"images": [{"id": "a", "top": True, "images": [{"id": B, "caption": "new"}]}]})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["delete_assets"], [A])


class Unchanged(Base):
    """prep describes only the rows changed since the last prep (4a)."""

    def prep(self, *more):
        return self.run_cli("prep", self.dir, "--now", NOW, "--no-rules", *more)

    def test_second_prep_names_unchanged_rows_only(self):
        self.put("a", waiting(handle="alpha", title="Alpha card"))
        self.put("w", working(handle="busy", title="Busy card"))
        code, out, _ = self.prep()
        self.assertIn("Alpha card", out)
        self.assertIn("Busy card", out)
        code, out, _ = self.prep()
        self.assertIn("1. alpha (unchanged)", out)
        self.assertNotIn("Busy card", out)
        self.assertIn("(+1 unchanged)", out)
        self.put("a", waiting(handle="alpha", title="Alpha card, new ask", ask="Now which?"))
        code, out, _ = self.prep()
        self.assertIn("Alpha card, new ask", out)
        code, out, _ = self.prep("--full")
        self.assertIn("Busy card", out)


class Held(Base):
    """A review held until the owner asks: on the page under Later, no push, no rank, no count."""

    def test_move_held_parks_it(self):
        self.put("r", waiting(kind="review", rank=1, activeAt=NOW, snoozeUntil="2026-10-26T05:00:00Z"), version=3)
        code, out, err = self.run_cli("move", self.dir, "r", "held", "--now", NOW)
        self.assertEqual(code, 0, err)
        entry, = json.loads(out)
        self.assertEqual(entry["if_version"], 3)
        patch = json.loads(Path(entry["file_path"]).read_text())
        self.assertEqual(patch["state"], "waiting")
        self.assertEqual(patch["heldAt"], NOW)
        self.assertEqual(patch["snoozeUntil"], {"__delete__": True})
        self.assertEqual(patch["activeAt"], {"__delete__": True})

    def test_held_needs_an_ask(self):
        self.put("r", working())
        code, _, err = self.run_cli("move", self.dir, "r", "held", "--now", NOW)
        self.assertEqual(code, 2)
        self.assertIn("ask", err)

    def test_held_is_out_of_the_deck_the_count_and_the_ranks(self):
        self.put("a", waiting(rank=2))
        self.put("r", waiting(kind="review", rank=1, heldAt="2026-10-01T09:00:00Z"))
        rows, now = tasks.load_rows(self.dir), tasks.parse_time(NOW)
        self.assertEqual([r.id for r in tasks.ordered(rows, now)], ["a"])
        self.assertEqual(tasks.counts(rows, now), (1, 0))
        self.assertEqual(tasks.placed(rows, "a", 1), {"a": 1})
        _, out, _ = self.run_cli("order", self.dir, "--now", NOW)
        self.assertIn("Later:", out)
        self.assertIn("review when you ask", out)

    def test_held_for_weeks_is_never_flagged(self):
        self.put("r", waiting(kind="review", pushedAt=None, heldAt="2026-09-01T09:00:00Z",
                              updatedAt="2026-09-01T09:00:00Z"))
        self.assertEqual(self.msgs("r"), [])

    def test_back_when_asked_needs_no_push(self):
        self.put("r", waiting(kind="review", pushedAt=None, heldAt="2026-10-01T09:00:00Z"))
        code, out, err = self.run_cli("move", self.dir, "r", "waiting", "--now", NOW)
        self.assertEqual(code, 0, err)
        patch = json.loads(Path(json.loads(out)[0]["file_path"]).read_text())
        self.assertEqual(patch["heldAt"], {"__delete__": True})
        self.assertEqual(patch["activeAt"], NOW)
        self.assertEqual(patch["pushedAt"], NOW)
        self.assertEqual(self.msgs("r"), [])
        rows = tasks.load_rows(self.dir)
        self.assertEqual([r.id for r in tasks.ordered(rows, tasks.parse_time(NOW))], ["r"])

    def test_other_moves_drop_the_hold(self):
        for to, extra in (("working", ["--session", S1]), ("news", [])):
            self.put("r", waiting(kind="review", heldAt="2026-10-01T09:00:00Z"))
            _, out, err = self.run_cli("move", self.dir, "r", to, "--now", NOW, *extra)
            patch = json.loads(Path(json.loads(out)[0]["file_path"]).read_text())
            self.assertEqual(patch["heldAt"], {"__delete__": True}, to)


def news(**kw):
    row = {"state": "news", "title": "v0.9 is out", "context": "The release is published.",
           "since": "2026-10-25T09:00:00Z", "updatedAt": "2026-10-25T11:00:00Z"}
    row.update(kw)
    return row


class News(Base):
    """Rule 14: news items, cleared by Seen; wrap-ups are news now."""

    def test_footer_shows_news_only_when_there_is_some(self):
        self.put("a", waiting())
        self.put("b", working())
        _, out, _ = self.run_cli("footer", self.dir, "--now", NOW)
        self.assertEqual(out.strip(), "[● 1 ··· ◌ 1](https://claude.ai/artifact/DESKTEST#waiting)")
        self.put("n1", news())
        self.put("n2", news())
        _, out, _ = self.run_cli("footer", self.dir, "--now", NOW)
        self.assertEqual(out.strip(), "[✦ 2 ··· ● 1 ··· ◌ 1](https://claude.ai/artifact/DESKTEST#news)")

    def test_a_stale_dump_is_refused(self):
        # #21: Seen deleted the news row after the dump was read; the old dump must not count it.
        self.put("a", waiting())
        self.put("n1", news())
        old = time.time() - 5 * 60
        for f in self.dir.glob("*.json"):
            os.utime(f, (old, old))
        code, out, err = self.run_cli("footer", self.dir, "--now", NOW)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("rows read 5 min ago: read them fresh", err)
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertEqual(code, 1)
        self.assertIn("rows read 5 min ago: read them fresh", out)
        self.assertNotIn("✦", out)
        # A row left over from an older read into the same directory is stale too.
        self.put("b", working())
        self.assertEqual(self.run_cli("footer", self.dir, "--now", NOW)[0], 1)
        # Written fresh: counted.
        for f in self.dir.glob("*.json"):
            os.utime(f)
        code, out, _ = self.run_cli("footer", self.dir, "--now", NOW)
        self.assertEqual(code, 0)
        self.assertIn("[✦ 1 ··· ● 1 ··· ◌ 1]", out)
        os.utime(self.dir / "a.json", (old, old))
        self.assertEqual(self.run_cli("footer", self.dir, "--now", NOW, "--max-age", 10)[0], 0)

    def test_a_stale_note_stops_prep_too(self):
        self.put("a", waiting())
        d = self.root / "dump" / "inbox"
        (d / "n-1.json").write_text(json.dumps({"text": "x", "from": "page", "at": NOW}))
        old = time.time() - 3 * 60
        os.utime(d / "n-1.json", (old, old))
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertEqual(code, 1)
        self.assertIn("rows read 3 min ago", out)

    def test_order_and_prep_list_news_first(self):
        self.put("a", waiting(title="A card"))
        self.put("old", news(title="Older news", updatedAt="2026-10-25T08:00:00Z"))
        self.put("new", news(title="Newer news"))
        _, out, _ = self.run_cli("order", self.dir, "--now", NOW)
        self.assertTrue(out.startswith("News:\n  - new: Newer news\n  - old: Older news\nWaiting:"), out)
        _, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertLess(out.index("News:"), out.index("Waiting:"))
        self.assertIn("[✦ 2 ··· ● 1 ··· ◌ 0]", out)
        # No news: no News heading.
        (self.dir / "old.json").unlink()
        (self.dir / "new.json").unlink()
        _, out, _ = self.run_cli("order", self.dir, "--now", NOW)
        self.assertNotIn("News:", out)

    def test_clean_news_passes_and_never_needs_a_push(self):
        self.put("n", news(links=[{"label": "Release", "url": "https://github.com/example/app/releases/tag/v0.9"}]))
        self.assertEqual(self.problems(), [])
        self.assertFalse(tasks.needs_push(tasks.load_rows(self.dir)[0], tasks.parse_time(NOW)))

    def test_news_with_an_ask_or_answer_is_flagged(self):
        self.put("n", news(ask="Try it?", answer="Go", quick="go"))
        m = self.msgs("n")
        self.assertTrue(any("news but carries ask, answer, quick" in x for x in m), m)

    def test_news_is_checked_for_chat_pointers(self):
        self.put("n", news(context="The rest is in the chat above."))
        self.assertTrue(any("points at the chat" in m for m in self.msgs("n")))

    def test_a_remaining_wrapup_is_flagged(self):
        self.put("wrap", waiting(kind="close"))
        self.assertTrue(any("make it news" in m for m in self.msgs("wrap")))
        self.put("gone", {"state": "done", "kind": "close"})
        self.assertFalse(any("make it news" in m for m in self.msgs("gone")))

    def test_move_to_news(self):
        self.put("w", waiting(kind="close", rank=2, blocks="x", answer="Go", answeredAt=NOW, quick="go", quickAt=NOW,
                              answerSent=True, ifNone="y", activeAt=NOW, note="n",
                              details=[{"title": "Recap", "text": "Built and merged."}]), version=4)
        code, out, err = self.run_cli("move", self.dir, "w", "news", "--now", NOW, "--context", "Merged: the price box.")
        self.assertEqual(code, 0, err)
        entries = json.loads(out)
        self.assertEqual((entries[0]["doc_id"], entries[0]["if_version"]), ("w", 4))
        patch = json.loads(Path(entries[0]["file_path"]).read_text())
        self.assertEqual(patch["state"], "news")
        self.assertEqual(patch["updatedAt"], NOW)
        self.assertEqual(patch["context"], "Merged: the price box.")
        for k in ("ask", "recommend", "ifNone", "answer", "answeredAt", "quick", "quickAt", "answerSent",
                  "pushedAt", "rank", "blocks", "kind", "activeAt", "note"):
            self.assertEqual(patch[k], {"__delete__": True}, k)
        self.assertNotIn("details", patch)  # the recap fold stays
        self.assertEqual(self.problems(), [])  # applied locally: clean news

    def test_move_to_news_refuses_an_ask(self):
        self.put("w", working())
        code, _, err = self.run_cli("move", self.dir, "w", "news", "--ask", "Try it?")
        self.assertEqual(code, 2)
        self.assertIn("a question is a Waiting card", err)

    def test_news_counts_as_done_for_dependents(self):
        self.put("land", working())
        self.put("launch", waiting(dependsOn=[{"item": "the landing", "card": "land", "state": "building"},
                                              {"item": "mail", "state": "open"}]))
        code, out, err = self.run_cli("move", self.dir, "land", "news", "--now", NOW)
        self.assertEqual(code, 0, err)
        self.assertEqual([e["doc_id"] for e in json.loads(out)], ["land", "launch"])
        self.assertEqual(self.row("launch")["dependsOn"][0]["state"], "done")
        self.assertEqual(self.msgs("launch"), [])  # in step with a news card

    def test_done_row_from_seen_is_flagged(self):
        self.put("n", news(state="done", doneAt=NOW, doneBy="page"))
        self.assertTrue(any("delete the row" in m for m in self.msgs("n")))


class Images(Base):
    def test_fold_images_and_superseded(self):
        self.put("a", waiting(images=[{"id": A}, {"id": B}],
                              details=[{"title": "One", "text": "1"}, {"title": "Two", "text": "2"}]), version=2)
        code, out, err = self.run_cli("images", self.dir, "a", "--fold", "2", "--image", f"{C}=Two, phone",
                                      "--image", f"{B}=Two, laptop", "--drop-top")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["delete_assets"], [A])  # B moved into the fold, so it stays
        patch = json.loads(Path(res["write"]["file_path"]).read_text())
        self.assertEqual(patch["images"], {"__delete__": True})
        self.assertEqual(patch["details"][1]["images"], [{"id": C, "caption": "Two, phone"},
                                                         {"id": B, "caption": "Two, laptop"}])
        self.assertNotIn("images", patch["details"][0])

    def test_fold_by_title_and_top(self):
        self.put("a", waiting(images=[{"id": A}], details=[{"title": "Board 1", "text": ""}]))
        _, out, _ = self.run_cli("images", self.dir, "a", "--top", "--image", f"{B}=new")
        self.assertEqual(json.loads(out)["delete_assets"], [A])
        _, out, _ = self.run_cli("images", self.dir, "a", "--fold", "board", "--image", f"{C}=b1")
        res = json.loads(out)
        self.assertEqual(res["delete_assets"], [])

    def test_bad_input_refused(self):
        self.put("a", waiting(details=[{"title": "x", "text": ""}]))
        self.assertEqual(self.run_cli("images", self.dir, "a", "--fold", "5", "--image", f"{A}=x")[0], 2)
        self.assertEqual(self.run_cli("images", self.dir, "a", "--top", "--image", "nothex=x")[0], 2)


def deps(*items):
    return [dict(zip(("item", "state", "card"), i)) if len(i) == 3 else {"item": i[0], "state": i[1]} for i in items]


class Links(Base):
    """dependsOn: a card that waits on others lists them, and they stay in step."""

    def launch(self, *items, version=None):
        self.put("launch", waiting(dependsOn=deps(*items)), version=version)

    def test_in_step_passes(self):
        self.put("land", working())
        self.put("test", waiting(handle="hand test"))
        self.launch(("the landing", "building", "land"), ("hand test", "open", "test"), ("repo topics", "done"),
                    ("mail", "open"))
        self.assertEqual(self.msgs("launch"), [])

    def test_gone_card_flags_its_item(self):
        self.launch(("the landing", "building", "land"), ("mail", "open"))
        m = self.msgs("launch")
        self.assertEqual(len(m), 1)
        self.assertIn("“the landing” is done (card land is gone), the card says building; refresh it", m[0])
        self.assertIn('dep <rows> launch "the landing" done', m[0])

    def test_state_disagreeing_with_its_card(self):
        self.put("land", waiting())
        self.put("test", working())
        self.put("ok", {"state": "done", "kind": "close"})
        self.launch(("the landing", "building", "land"), ("hand test", "open", "test"), ("closed", "open", "ok"),
                    ("mail", "open"))
        m = " | ".join(self.msgs("launch"))
        self.assertIn("“the landing” is open (card land is waiting)", m)
        self.assertIn("“hand test” is building (card test is working)", m)
        self.assertIn("“closed” is done (card ok is done)", m)

    def test_all_done_asks_or_closes(self):
        self.launch(("a", "done"), ("b", "done", "gone"))
        self.assertEqual(self.msgs("launch"), ["everything in dependsOn is done: nothing left blocking it: ask or close"])
        self.put("empty", waiting(dependsOn=[]))
        self.assertEqual(self.msgs("empty"), [])

    def test_bad_items(self):
        self.put("x", waiting(dependsOn=[{"state": "open"}, {"item": "y", "state": "waiting"},
                                         {"item": "self", "state": "open", "card": "x"}, {"item": "z", "state": "open"}]))
        m = " | ".join(self.msgs("x"))
        self.assertIn("dependsOn[0] has no item", m)
        self.assertIn("state 'waiting', not done, building or open", m)
        self.assertIn("links the card itself", m)
        self.put("y", waiting(dependsOn="nope"))
        self.assertEqual(self.msgs("y"), ["dependsOn is not a list"])

    def test_done_prints_the_dependents(self):
        self.put("land", working(), version=5)
        self.put("other", waiting(dependsOn=deps(("mail", "open"))), version=2)
        self.put("cut", waiting(dependsOn=deps(("the landing", "done", "land"))), version=4)  # already right
        self.launch(("the landing", "building", "land"), ("mail", "open"), version=8)
        code, out, err = self.run_cli("move", self.dir, "land", "done", "--now", NOW)
        self.assertEqual(code, 0, err)
        entries = json.loads(out)
        self.assertEqual(entries[0], {"op": "delete", "collection": "tasks", "doc_id": "land", "if_version": 5})
        self.assertEqual([(e["doc_id"], e["if_version"]) for e in entries[1:]], [("launch", 8)])
        self.assertIn("launch depends on land", err)
        patch = json.loads(Path(entries[1]["file_path"]).read_text())
        self.assertEqual(patch["dependsOn"], deps(("the landing", "done", "land"), ("mail", "open")))
        self.assertEqual(patch["updatedAt"], NOW)
        self.assertEqual(self.msgs("launch"), [])  # applied locally, and in step

    def test_other_moves_carry_their_state(self):
        self.put("land", waiting())
        self.launch(("the landing", "open", "land"))
        _, out, _ = self.run_cli("move", self.dir, "land", "working", "--now", NOW)
        entries = json.loads(out)
        self.assertEqual([e["doc_id"] for e in entries], ["land", "launch"])
        self.assertEqual(self.row("launch")["dependsOn"][0]["state"], "building")
        _, out, _ = self.run_cli("move", self.dir, "land", "working", "--now", NOW)
        self.assertEqual(len(json.loads(out)), 1)  # nothing changed for launch
        self.run_cli("move", self.dir, "land", "waiting", "--now", NOW)
        self.assertEqual(self.row("launch")["dependsOn"][0]["state"], "open")

    def test_dep_by_hand(self):
        self.launch(("repo topics", "open"), ("the landing", "building", "search-box"), ("mail for team@", "open"),
                    version=3)
        code, out, err = self.run_cli("dep", self.dir, "launch", "repo topics", "done", "--now", NOW)
        self.assertEqual(code, 0, err)
        entry = json.loads(out)
        self.assertEqual((entry["doc_id"], entry["if_version"]), ("launch", 3))
        patch = json.loads(Path(entry["file_path"]).read_text())
        self.assertEqual(patch["dependsOn"][0], {"item": "repo topics", "state": "done"})
        self.assertEqual(patch["updatedAt"], NOW)
        # By its card id, or a unique prefix of its text.
        self.run_cli("dep", self.dir, "launch", "search-box", "done")
        self.run_cli("dep", self.dir, "launch", "Mail", "done")
        self.assertEqual([d["state"] for d in self.row("launch")["dependsOn"]], ["done", "done", "done"])

    def test_dep_add_and_refusals(self):
        self.launch(("mail for team@", "open"), ("mail for ops@", "open"))
        self.assertIn("matches 2 items", self.run_cli("dep", self.dir, "launch", "mail", "done")[2])
        self.assertIn("--add", self.run_cli("dep", self.dir, "launch", "X post", "done")[2])
        with self.assertRaises(SystemExit):  # not a dependsOn state
            self.run_cli("dep", self.dir, "launch", "mail for team@", "waiting")
        code, _, err = self.run_cli("dep", self.dir, "launch", "hand test", "open", "--card", "hand-test", "--add")
        self.assertEqual(code, 0)
        self.assertIn("no card 'hand-test'", err)
        self.assertEqual(self.row("launch")["dependsOn"][-1], {"item": "hand test", "card": "hand-test", "state": "open"})


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class RuleReload(Base):
    """prep stops when a clone's HEAD changed a rule file since it was loaded."""

    def setUp(self):
        super().setUp()
        self.origin = self.root / "origin.git"
        sh(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.seed = self.root / "seed"
        sh(self.root, "clone", "-q", str(self.origin), str(self.seed))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            sh(self.seed, "config", k, v)
        self.commit(self.seed, {"CLAUDE.md": "rules", "memory/MEMORY.md": "m", ".claude/skills/x/SKILL.md": "s",
                                "README.md": "r"})
        self.clone = self.root / "clone"
        sh(self.root, "clone", "-q", str(self.origin), str(self.clone))
        self.state = self.root / "state" / "loaded.json"
        self.put("a", waiting())

    def tearDown(self):
        while tasks.BACKGROUND:  # let the background fetches finish before the clones go
            tasks.BACKGROUND.pop().wait(timeout=30)
        super().tearDown()

    def commit(self, repo, files):
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text)
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "c")
        sh(repo, "push", "-q", "origin", "HEAD:main")

    def prep(self):
        return self.run_cli("prep", self.dir, "--now", NOW, "--repo", self.clone, "--state", self.state)

    def test_nothing_changed_runs_on(self):
        code, out, err = self.prep()
        self.assertEqual(code, 0, out)
        self.assertIn("[● 1", out)
        self.assertIn("nothing marked loaded; taking HEAD", err)

    def test_a_changed_rule_stops_it(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.commit(self.seed, {"CLAUDE.md": "new rules", ".claude/skills/x/SKILL.md": "s2", "README.md": "r2"})
        sh(self.clone, "pull", "-q", "origin", "main")
        code, out, _ = self.prep()
        self.assertEqual(code, 1)
        self.assertIn("Stop: the rules changed", out)
        self.assertIn(".claude/skills/x/SKILL.md, CLAUDE.md", out)
        self.assertNotIn("README.md", out)
        self.assertNotIn("◌", out)  # no footer
        # Re-read: marked loaded, it runs on.
        code, out, err = self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(self.state.read_text()), {str(self.clone.resolve()): sh(self.clone, "rev-parse", "HEAD")})
        self.assertEqual(self.prep()[0], 0)

    def test_memory_changes_count_other_files_dont(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.commit(self.seed, {"README.md": "r3", "memory/archive.md": "old"})
        sh(self.clone, "pull", "-q", "origin", "main")
        self.assertEqual(self.prep()[0], 0)
        self.commit(self.seed, {"memory/MEMORY.md": "m2"})
        sh(self.clone, "pull", "-q", "origin", "main")
        code, out, _ = self.prep()
        self.assertEqual(code, 1)
        self.assertIn("memory/MEMORY.md", out)

    def test_marking_without_pulling_warns(self):
        self.commit(self.seed, {"CLAUDE.md": "newer"})
        sh(self.clone, "fetch", "-q", "origin", "main")
        code, _, err = self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.assertEqual(code, 1)
        self.assertIn("behind origin/main on CLAUDE.md", err)

    def test_prep_never_fetches(self):
        # The reload check judges by the clone's HEAD alone (the plugin's clone, not watched here,
        # gets no background fetch): a change upstream waits for a pull.
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        sh(self.clone, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        code, out, err = self.prep()
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("[● 1", out)
        sh(self.clone, "remote", "set-url", "origin", str(self.origin))
        self.commit(self.seed, {"CLAUDE.md": "newer"})
        self.assertEqual(self.prep()[0], 0)
        self.assertNotEqual(sh(self.clone, "rev-parse", "origin/main"), sh(self.seed, "rev-parse", "HEAD"))

    def prep_plugin(self):
        return self.run_cli("prep", self.dir, "--now", NOW, "--repo", self.clone, "--plugin", self.clone,
                            "--state", self.state)

    def test_prep_notices_an_update_in_the_background(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.commit(self.seed, {"skills/desk/SKILL.md": "new rules"})
        # The first prep starts the fetch and runs on: it never waits for it.
        ahead, proc = tasks.update_check(self.clone, self.state)
        self.assertIsNone(ahead)
        self.assertIsNotNone(proc)
        proc.wait(timeout=30)
        self.assertEqual(sh(self.clone, "rev-parse", "origin/main"), sh(self.seed, "rev-parse", "HEAD"))
        self.assertNotEqual(sh(self.clone, "rev-parse", "HEAD"), sh(self.seed, "rev-parse", "HEAD"))
        # The next one sees the fetched main ahead of what was loaded: it stops, no deck, no footer.
        code, out, _ = self.prep_plugin()
        self.assertEqual(code, 1, out)
        self.assertIn("Desk has an update", out)
        self.assertIn("/desk:update", out)
        self.assertNotIn("[●", out)
        # /desk:update pulls it; once loaded, prep runs on.
        self.update()
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.assertEqual(self.prep_plugin()[0], 0)

    def test_an_update_that_misses_the_rules_doesnt_stop_it(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.commit(self.seed, {"README.md": "r2"})
        sh(self.clone, "fetch", "-q", "origin", "main")
        self.assertEqual(self.prep_plugin()[0], 0)

    def test_fetches_at_most_every_six_hours(self):
        t = 1_000_000.0
        _, proc = tasks.update_check(self.clone, self.state, now=t)
        proc.wait(timeout=30)
        stamps = json.loads(tasks.fetched_path(self.state).read_text())
        self.assertEqual(stamps, {str(self.clone.resolve()): t})
        self.assertIsNone(tasks.update_check(self.clone, self.state, now=t + 5 * 3600)[1])
        _, proc = tasks.update_check(self.clone, self.state, now=t + 6 * 3600)
        self.assertIsNotNone(proc)
        proc.wait(timeout=30)

    def test_offline_or_missing_clone_never_fails_or_slows_prep(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        sh(self.clone, "remote", "set-url", "origin", "https://127.0.0.1:9/nowhere.git")
        start = time.monotonic()
        code, out, err = self.prep_plugin()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("[● 1", out)
        self.assertEqual(tasks.update_check(self.root / "missing", self.state), (None, None))
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--repo", self.clone,
                                    "--plugin", self.root / "missing", "--state", self.state)
        self.assertEqual(code, 0, out)

    def test_a_pull_made_elsewhere_still_stops_it(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        self.commit(self.seed, {".claude/skills/x/SKILL.md": "s2"})
        sh(self.clone, "pull", "-q", "origin", "main")
        code, out, _ = self.prep()
        self.assertEqual(code, 1)
        self.assertIn("Stop: the rules changed", out)
        self.assertIn("/desk:update", out)

    def update(self, home=None):
        home = home or self.clone
        return self.run_cli("update", "--home", home, "--url", self.origin, "--repo", self.clone, "--state", self.state)

    def test_update_pulls_and_names_what_changed(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        before = sh(self.clone, "rev-parse", "HEAD")
        self.commit(self.seed, {"skills/desk/SKILL.md": "r2", "page/desk.html": "<p>", "README.md": "r2"})
        code, out, _ = self.update()
        self.assertEqual(code, 1, out)
        self.assertEqual(sh(self.clone, "rev-parse", "HEAD"), sh(self.seed, "rev-parse", "HEAD"))
        self.assertIn(f"{before[:7]} -> {sh(self.seed, 'rev-parse', 'HEAD')[:7]}", out)
        self.assertIn("page/desk.html, skills/desk/SKILL.md", out)
        self.assertNotIn("README.md", out)
        self.assertIn("republish the Desk in place", out)
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        code, out, _ = self.update()
        self.assertEqual(code, 0, out)
        self.assertIn("Desk is current at", out)
        self.assertEqual(self.prep()[0], 0)

    def test_update_clones_when_missing(self):
        home = self.root / "home" / ".claude" / "desk"
        code, out, _ = self.run_cli("update", "--home", home, "--url", self.origin, "--repo", home,
                                    "--state", self.state)
        self.assertEqual(sh(home, "rev-parse", "HEAD"), sh(self.seed, "rev-parse", "HEAD"))
        self.assertIn(f"cloned {home}", out)

    def test_update_offline_warns(self):
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        sh(self.clone, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        code, out, err = self.update()
        self.assertEqual(code, 0, out)
        self.assertIn("pull failed", err)

    def test_default_repos(self):
        self.assertEqual(tasks.rule_repos([self.clone]), [self.clone])
        # Run from a copy that isn't a clone (a plugin install): ~/.claude/desk is the plugin's clone.
        saved = tasks.PLUGIN_REPO, tasks.PLUGIN_HOME
        try:
            tasks.PLUGIN_REPO, tasks.PLUGIN_HOME = self.root / "installed", self.clone
            self.assertEqual(tasks.plugin_clone(), self.clone)
            self.assertIn(self.clone.resolve(), [r.resolve() for r in tasks.rule_repos()])
            tasks.PLUGIN_HOME = self.root / "missing"
            self.assertIsNone(tasks.plugin_clone())
            tasks.PLUGIN_REPO = self.clone
            self.assertEqual(tasks.plugin_clone(), self.clone)
        finally:
            tasks.PLUGIN_REPO, tasks.PLUGIN_HOME = saved


class DeskTests(Base):
    """The Desk's own parts: config, Inbox, look, page, feedback."""

    def note_dir(self):
        d = self.root / "dump" / "inbox"
        d.mkdir(exist_ok=True)
        return d

    def test_config_found_up_from_cwd(self):
        proj = self.root / "proj"
        (proj / ".claude").mkdir(parents=True)
        (proj / "sub").mkdir()
        (proj / ".claude" / "desk.json").write_text(json.dumps({"page": "https://claude.ai/artifact/X/"}))
        self.assertEqual(tasks.find_config(proj / "sub"), proj / ".claude" / "desk.json")
        tasks.load_config(proj / ".claude" / "desk.json")
        self.assertEqual(tasks.PAGE, "https://claude.ai/artifact/X")

    def test_footer_without_desk_says_so(self):
        os.environ.pop("DESK_CONFIG")
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.put("a", waiting())
            with self.assertRaises(SystemExit) as e:
                self.run_cli("footer", self.dir)
            self.assertIn("no Desk configured", str(e.exception.code))
        finally:
            os.chdir(cwd)

    def test_prep_stops_when_the_notes_were_not_read(self):
        self.put("a", waiting())
        (self.root / "dump" / "inbox").rmdir()
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertEqual(code, 1)
        self.assertIn("no inbox in this dump", out)
        self.assertNotIn("[●", out)

    def test_inbox_says_when_the_page_could_not_wake_the_keeper(self):
        (self.note_dir() / "n-1.json").write_text(json.dumps({"text": "x", "from": "page", "at": NOW, "sendErr": "send_no_session"}))
        code, out, _ = self.run_cli("inbox", self.root / "dump")
        self.assertIn("the page couldn't wake you: send_no_session", out)

    def test_note_writes_a_row_and_its_entry(self):
        code, out, _ = self.run_cli("note", "--text", " The swipe skips a card ", "--from", "chat",
                                    "--out", self.root / "notes", "--now", NOW)
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["page"], PAGE)
        w = res["write"]
        self.assertEqual((w["op"], w["collection"]), ("set", "inbox"))
        self.assertTrue(w["doc_id"].startswith("n-20261025120000-"))
        row = json.loads(Path(w["file_path"]).read_text())
        self.assertEqual(row, {"text": "The swipe skips a card", "from": "chat", "at": NOW})

    def test_prep_stops_on_unsorted_notes_and_sorted_clears_them(self):
        self.put("a", waiting())
        (self.note_dir() / "n-1.json").write_text(json.dumps({"text": "fix the dashes", "from": "page", "at": NOW}))
        (self.root / "dump" / "inbox" / "_versions.json").write_text(json.dumps({"n-1": 3}))
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertEqual(code, 1)
        self.assertIn("inbox n-1: sort this note", out)
        self.assertIn("[● 1", out)
        code, out, _ = self.run_cli("sorted", self.root / "dump", "n-1")
        self.assertEqual(json.loads(out), [{"op": "delete", "collection": "inbox", "doc_id": "n-1", "if_version": 3}])
        code, out, _ = self.run_cli("prep", self.dir, "--now", NOW, "--no-rules")
        self.assertEqual(code, 0, out)
        self.assertIn("check: ok", out)

    def test_backup_and_restore_round_trip(self):
        self.put("a", waiting(title="Pick a font"), version=4)
        self.put("b", working())
        (self.note_dir() / "n-1.json").write_text(json.dumps({"text": "fix the dashes", "from": "page", "at": NOW}))
        (self.root / "dump" / "settings").mkdir()
        (self.root / "dump" / "settings" / "look.json").write_text(json.dumps({"theme": "moss", "icon": {"emoji": "📦"}}))
        f = self.root / "scratch" / "desk-backup.json"
        code, out, _ = self.run_cli("backup", self.root / "dump", "--out", f, "--now", NOW)
        self.assertEqual(code, 0)
        b = json.loads(f.read_text())
        self.assertEqual((b["page"], b["at"]), (PAGE, NOW))
        self.assertEqual(b["collections"]["tasks"]["a"]["title"], "Pick a font")
        self.assertEqual(b["collections"]["inbox"]["n-1"]["text"], "fix the dashes")
        self.assertEqual(b["collections"]["settings"]["look"]["theme"], "moss")
        # A write went wrong: a card lost its title, a stray card appeared. Restore puts it back.
        self.put("a", waiting(title="oops"), version=5)
        self.put("c", working(title="stray"), version=2)
        (self.note_dir() / "n-2.json").write_text(json.dumps({"text": "new", "from": "page", "at": NOW}))
        out_dir = self.root / "restore"
        code, out, _ = self.run_cli("restore", f, "--out", out_dir, "--rows", self.root / "dump")
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["page"], PAGE)
        sets = {(e["collection"], e["doc_id"]): e for e in res["writes"] if e["op"] == "set"}
        self.assertEqual(set(sets), {("tasks", "a"), ("tasks", "b"), ("inbox", "n-1"), ("settings", "look")})
        for (coll, rid), e in sets.items():
            self.assertEqual(json.loads(Path(e["file_path"]).read_text()), b["collections"][coll][rid])
            self.assertTrue(Path(e["file_path"]).is_relative_to(out_dir))
        dels = [(e["collection"], e["doc_id"]) for e in res["writes"] if e["op"] == "delete"]
        self.assertEqual(dels, [("tasks", "c")])  # n-2 came in since: the owner's, it stays
        self.assertIn({"op": "delete", "collection": "tasks", "doc_id": "c", "if_version": 2}, res["writes"])
        self.assertTrue((self.dir / "c.json").exists())

    def test_backup_stays_out_of_repos(self):
        self.put("a", waiting())
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        with self.assertRaises(SystemExit) as e:
            self.run_cli("backup", self.root / "dump", "--out", repo / "backup.json")
        self.assertIn("inside a git repo", str(e.exception.code))
        self.assertFalse((repo / "backup.json").exists())
        code, _, _ = self.run_cli("backup", self.root / "dump", "--out", repo / "backup.json", "--private-repo")
        self.assertEqual(code, 0)

    def test_look(self):
        code, out, _ = self.run_cli("look", "--theme", "Lagoon", "--emoji", "💼", "--out", self.root)
        e = json.loads(out)
        self.assertEqual((e["collection"], e["doc_id"], e["op"]), ("settings", "look", "set"))
        self.assertEqual(json.loads(Path(e["file_path"]).read_text()), {"theme": "lagoon", "icon": {"emoji": "💼"}})
        cur = self.root / "cur.json"
        cur.write_text(json.dumps({"id": "look", "data": {"theme": "plum", "icon": {"emoji": "🗂️"}}, "version": 2}))
        code, out, _ = self.run_cli("look", "--image", A, "--current", cur, "--out", self.root)
        self.assertEqual(json.loads(Path(json.loads(out)["file_path"]).read_text()), {"theme": "plum", "icon": {"image": A}})
        with self.assertRaises(SystemExit):
            self.run_cli("look", "--theme", "teal", "--out", self.root)
        with self.assertRaises(SystemExit):
            self.run_cli("look", "--image", "not-an-id", "--out", self.root)

    def test_look_never_writes_into_the_cwd(self):
        repo = self.root / "repo"
        repo.mkdir()
        old = os.getcwd()
        os.chdir(repo)
        try:
            code, out, _ = self.run_cli("look", "--theme", "plum", "--emoji", "🗂️")
            self.assertEqual(code, 0)
            self.assertEqual(list(repo.iterdir()), [])
            f = Path(json.loads(out)["file_path"])
            self.assertEqual(json.loads(f.read_text())["theme"], "plum")
            # Given the row as read, it writes beside the rows, like the patches.
            dump = self.root / "look" / "settings"
            dump.mkdir(parents=True)
            (dump / "look.json").write_text(json.dumps({"id": "look", "data": {"theme": "plum"}, "version": 1}))
            code, out, _ = self.run_cli("look", "--letter", "D", "--current", dump / "look.json")
            self.assertEqual(Path(json.loads(out)["file_path"]), (self.root / "look" / "patches" / "look.json").resolve())
            self.assertEqual(list(repo.iterdir()), [])
        finally:
            os.chdir(old)

    def test_themes_match_the_page(self):
        html = (tasks.PLUGIN_REPO / "page" / "desk.html").read_text()
        m = re.search(r"const THEMES = \{(.*?)\n\};", html, re.S)
        self.assertIsNotNone(m, "page/desk.html has no THEMES")
        names = tuple(re.findall(r"^\s*(\w+): \{", m.group(1), re.M))
        self.assertEqual(names, tasks.THEMES)

    def test_page_renders_this_desk(self):
        tpl = self.root / "t.html"
        tpl.write_text("<title>{{DESK_TITLE}}</title><html data-desk-theme=\"{{DESK_THEME}}\">"
                       "<script>const KEEPER=\"{{DESK_KEEPER}}\", ICON={{DESK_ICON}}, TZ=\"{{DESK_TIMEZONE}}\";</script>")
        cfg = self.root / "d2.json"
        cfg.write_text(json.dumps({"title": "A <b> Desk", "page": PAGE, "keeper": "session_01X", "timezone": "Europe/Berlin",
                                   "look": {"theme": "plum", "icon": {"emoji": "🗂️"}}}))
        out = self.root / "p.html"
        code, msg, _ = self.run_cli("--desk", cfg, "page", "--out", out, "--template", tpl)
        html = out.read_text()
        self.assertIn("<title>A &lt;b> Desk</title>", html)
        self.assertIn('data-desk-theme="plum"', html)
        self.assertIn('KEEPER="https://claude.ai/code/session_01X"', html)
        self.assertIn('ICON={"emoji": "🗂️"}', html)
        self.assertIn('TZ="Europe/Berlin"', html)
        self.assertIn(PAGE, msg)
        self.assertIn("refused", msg)

    def test_skills_expect_refusals_on_republish(self):
        # Issue #8: an in-place republish of a page last published elsewhere is refused (twice) first.
        skills = tasks.PLUGIN_REPO / "skills"
        for f in ("setup/SKILL.md", "desk/SKILL.md", "desk-keeper/SKILL.md"):
            text = " ".join((skills / f).read_text().split())
            self.assertIn("publish again until it goes through", text, f)

    def test_core_skill_is_short_and_the_reference_has_the_rest(self):
        # 4b: what a turn needs stays in SKILL.md; the rest is read on demand from reference.md.
        here = tasks.PLUGIN_REPO / "skills" / "desk"
        core, ref = (here / "SKILL.md").read_text(), (here / "reference.md").read_text()
        self.assertLess(len(core.splitlines()), 120)
        self.assertIn("reference.md", core)
        for n in range(1, 18):
            self.assertRegex(core, rf"(?m)^{n}\. \*\*", f"rule {n} in the core")
            self.assertRegex(ref, rf"(?m)^{n}\. \*\*", f"rule {n} in the reference")
        # Every command is documented in the reference.
        for name in re.findall(r'sub\.add_parser\("([\w-]+)"|cmd\("([\w-]+)", cmd_', (here / "desk.py").read_text()):
            name = next(x for x in name if x)
            self.assertIn(f"$S {name}", ref, name)

    def test_real_template_renders(self):
        out = self.root / "p.html"
        self.assertEqual(self.run_cli("page", "--out", out)[0], 0)
        html = out.read_text()
        self.assertIn("<title>Test Desk</title>", html[:8000])
        self.assertNotIn("{{", html)

    def test_scrub_flags_content(self):
        self.put("launch-date", waiting(title="Pick the launch date", links=[{"label": "Plan", "url": "https://example.com/plan"}]))
        (self.note_dir() / "n-1.json").write_text(json.dumps({"text": "the acme logo is wrong", "from": "page", "at": NOW}))
        draft = self.root / "draft.md"
        draft.write_text("On the card \"Pick the launch date\" (launch-date) the swipe skipped; see "
                         "https://example.com/plan and https://github.com/bagrat/claude-plugin-desk/issues/1; "
                         "also: the acme logo is wrong. Mail a@b.co, session_01ABC.")
        code, out, _ = self.run_cli("scrub", draft, "--rows", self.root / "dump")
        self.assertEqual(code, 1)
        for bit in ("a card's title: Pick the launch date", "a card id: launch-date", "a note: the acme logo",
                    "outside the plugin's repos: https://example.com/plan", "an address: a@b.co", "a session id"):
            self.assertIn(bit, out)
        self.assertNotIn("claude-plugin-desk/issues/1", out)
        draft.write_text("A waiting card with two folds: swiping left on the last card skips the first.")
        self.assertEqual(self.run_cli("scrub", draft, "--rows", self.root / "dump")[0], 0)

    def test_issue_url(self):
        body = self.root / "b.md"
        body.write_text("Steps: swipe left & right")
        code, out, _ = self.run_cli("issue-url", "--title", "Swipe skips", "--body", body)
        self.assertEqual(out.strip(), "https://github.com/bagrat/claude-plugin-desk/issues/new?title=Swipe%20skips"
                                      "&body=Steps%3A%20swipe%20left%20%26%20right&labels=feedback")
        body.write_text("see https://intranet.example/x")
        with self.assertRaises(SystemExit):
            self.run_cli("issue-url", "--title", "t", "--body", body)


class CloudSetup(unittest.TestCase):
    """cloud-setup.sh: installs the plugin in a cloud session's setup script, and never fails it."""

    SCRIPT = Path(__file__).resolve().parents[2] / "cloud-setup.sh"

    def run_script(self, claude_body, url=None, home=None):
        with tempfile.TemporaryDirectory() as d:
            self.home = Path(home or Path(d) / "home")
            log = Path(d) / "log"
            if claude_body is not None:
                fake = Path(d) / "claude"
                fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n{claude_body}\n')
                fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{d}:/usr/bin:/bin", HOME=str(self.home),
                       DESK_REPO_URL=url or str(Path(d) / "nowhere.git"))
            p = subprocess.run(["sh", str(self.SCRIPT)], env=env, capture_output=True, text=True)
            if url:
                self.head = sh(self.home / ".claude" / "desk", "rev-parse", "HEAD")
            return p.returncode, log.read_text().splitlines() if log.exists() else []

    def test_keeps_a_clone_at_a_fixed_place(self):
        with tempfile.TemporaryDirectory() as d:
            origin, seed = Path(d) / "origin.git", Path(d) / "seed"
            sh(d, "init", "-q", "--bare", "-b", "main", str(origin))
            sh(d, "clone", "-q", str(origin), str(seed))
            for k, v in (("user.email", "t@t"), ("user.name", "t")):
                sh(seed, "config", k, v)
            (seed / "f").write_text("1")
            sh(seed, "add", "-A")
            sh(seed, "commit", "-qm", "c")
            sh(seed, "push", "-q", "origin", "HEAD:main")
            home = Path(d) / "home"
            code, calls = self.run_script("exit 0", str(origin), home)  # cloned
            self.assertEqual((code, len(calls)), (0, 3))
            self.assertEqual(self.head, sh(seed, "rev-parse", "HEAD"))
            (seed / "f").write_text("2")
            sh(seed, "commit", "-qam", "c2")
            sh(seed, "push", "-q", "origin", "HEAD:main")
            self.assertEqual(self.run_script("exit 0", str(origin), home)[0], 0)  # pulled
            self.assertEqual(self.head, sh(seed, "rev-parse", "HEAD"))

    def test_installs_from_the_marketplace(self):
        code, calls = self.run_script("exit 0")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["plugin marketplace add bagrat/claude-plugin-marketplace",
                                 "plugin install desk@bagrat", "plugin update desk@bagrat"])

    def test_never_fails_the_setup(self):
        self.assertEqual(self.run_script("exit 1"), (0, ["plugin marketplace add bagrat/claude-plugin-marketplace",
                                                         "plugin install desk@bagrat", "plugin update desk@bagrat"]))
        self.assertEqual(self.run_script(None), (0, []))


if __name__ == "__main__":
    unittest.main()
