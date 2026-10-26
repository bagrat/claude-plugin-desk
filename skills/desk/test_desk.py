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


def waiting(**kw):
    row = {"state": "waiting", "kind": "decide", "title": "T", "ask": "Which?", "recommend": "This one.",
           "pushedAt": "2026-10-25T11:00:00Z"}
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
        cfg.write_text(json.dumps({"title": "Test Desk", "page": PAGE}))
        self._env = os.environ.get("DESK_CONFIG")
        os.environ["DESK_CONFIG"] = str(cfg)
        tasks.load_config()
        self.dir = self.root / "dump" / "tasks"
        self.dir.mkdir(parents=True)

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

    def test_rank_blocking_then_kind_and_hand_rank_kept(self):
        self.put("check", waiting(kind="check", blocks="x", rank=1))
        self.put("review", waiting(kind="review", blocks="x", rank=5))
        self.put("decide", waiting(kind="decide", blocks="x", rank=2))
        self.put("free-review", waiting(kind="review", rank=3))
        self.put("bumped", waiting(kind="info", rank=0.5, rankByHand=True))
        ranks = tasks.reranked(tasks.load_rows(self.dir))
        self.assertEqual(ranks, {"review": 1, "decide": 2, "check": 3, "free-review": 4})
        code, out, _ = self.run_cli("rank", self.dir)
        entries = json.loads(out)
        self.assertEqual({e["doc_id"] for e in entries}, {"review", "check", "free-review"})  # decide stays 2
        self.assertEqual(self.row("review")["rank"], 1)


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
        self.put("c", waiting(context='Never write "see the chat" on a card.'))  # a quote, not a pointer
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
        # Newly waiting: the only thing left is its push (rule 13).
        m, = self.msgs("a")
        self.assertIn("rule 13", m)

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
        d.mkdir()
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
        # prep judges by the clone's HEAD alone: no network, so a change upstream waits for a pull.
        self.run_cli("loaded", "--repo", self.clone, "--state", self.state)
        sh(self.clone, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        code, out, err = self.prep()
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("[● 1", out)
        sh(self.clone, "remote", "set-url", "origin", str(self.origin))
        self.commit(self.seed, {"CLAUDE.md": "newer"})
        self.assertEqual(self.prep()[0], 0)
        self.assertNotEqual(sh(self.clone, "rev-parse", "origin/main"), sh(self.seed, "rev-parse", "HEAD"))

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
                       "<script>const KEEPER=\"{{DESK_KEEPER}}\", ICON={{DESK_ICON}};</script>")
        cfg = self.root / "d2.json"
        cfg.write_text(json.dumps({"title": "A <b> Desk", "page": PAGE, "keeper": "session_01X",
                                   "look": {"theme": "plum", "icon": {"emoji": "🗂️"}}}))
        out = self.root / "p.html"
        code, msg, _ = self.run_cli("--desk", cfg, "page", "--out", out, "--template", tpl)
        html = out.read_text()
        self.assertIn("<title>A &lt;b> Desk</title>", html)
        self.assertIn('data-desk-theme="plum"', html)
        self.assertIn('KEEPER="https://claude.ai/code/session_01X"', html)
        self.assertIn('ICON={"emoji": "🗂️"}', html)
        self.assertIn(PAGE, msg)
        self.assertIn("refused", msg)

    def test_skills_expect_refusals_on_republish(self):
        # Issue #8: an in-place republish of a page last published elsewhere is refused (twice) first.
        skills = tasks.PLUGIN_REPO / "skills"
        for f in ("setup/SKILL.md", "desk/SKILL.md", "desk-keeper/SKILL.md"):
            text = " ".join((skills / f).read_text().split())
            self.assertIn("publish again until it goes through", text, f)

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
