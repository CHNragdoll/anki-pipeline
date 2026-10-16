"""Behavior checks use only temporary progress databases, never native Anki."""
from __future__ import annotations

import copy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from fsrs import Card, Rating, Scheduler, State

from anki_pipeline import study_progress as backend
StudyStore, StudyError = backend.StudyStore, backend.StudyError


def catalog():
    return {
        book: {
            "id": book, "name": book.title(), "previewPath": f"/{book}/index.html",
            "cards": [
                {"id": f"{book}-{i}", "word": f"word-{i}", "meta": f"Unit {1 if i < 3 else 2}",
                 "deckId": "u1" if i < 3 else "u2", "previewUrl": f"/{book}/{i}.html"}
                for i in range(1, 5)
            ],
            "decks": [
                {"id": "u1", "name": "Unit 1", "cardIds": [f"{book}-1", f"{book}-2"]},
                {"id": "u2", "name": "Unit 2", "cardIds": [f"{book}-3", f"{book}-4"]},
            ],
        } for book in ("liu", "redbook")
    }


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "progress.sqlite3"
        self.clock = Clock()
        self.books = catalog()
        self.store = StudyStore(self.db, self.books, now=self.clock)
        self.sequence = 0

    def session(self, book="redbook", deck="all"):
        return self.store.dispatch("GET", "/api/study/session", {"book": book, "deck": deck}, None)

    def answer(self, rating=3, book="redbook", deck="all", card=None, request_id=None):
        self.sequence += 1
        current = card or self.session(book, deck)["card"]
        body = {"book": book, "deck": deck, "cardId": current["id"],
                "revision": current["revision"], "rating": rating,
                "requestId": request_id or f"request-{self.sequence}", "durationMs": 1234}
        return self.store.dispatch("POST", "/api/study/answer", {}, body), body

    def settings(self, book="redbook", **changes):
        settings = {"book": book, "newPerDay": 20, "reviewPerDay": 200, "desiredRetention": .9}
        settings.update(changes)
        return self.store.dispatch("POST", "/api/study/settings", {}, settings)

    def backup(self):
        return self.store.dispatch("GET", "/api/study/backup", {}, None)

    def restore(self, backup):
        return self.store.dispatch("POST", "/api/study/restore", {}, {"backup": backup})

    def stats(self, book="redbook"):
        return self.store.dispatch("GET", "/api/study/stats", {"book": book}, None)

    def assert_error(self, status, callback):
        with self.assertRaises(StudyError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)
        self.assertTrue(caught.exception.message)

    def test_initial_session_and_public_overview(self):
        session = self.session()
        self.assertEqual(session["card"]["id"], "redbook-1")
        self.assertEqual(session["card"]["phase"], "new")
        self.assertEqual(session["card"]["meta"], "Unit 1")
        self.assertEqual(session["counts"], {"new": 4, "due": 0, "learning": 0, "todayReviews": 0})
        self.assertFalse(session["canUndo"])
        overview = self.store.dispatch("GET", "/api/study/overview", {}, None)
        self.assertEqual(overview["algorithm"], "FSRS")
        self.assertTrue(overview["independent"])
        self.assertEqual([book["cardCount"] for book in overview["books"]], [4, 4])

    def test_four_ratings_use_real_fsrs_due_and_preview(self):
        scheduler = Scheduler(enable_fuzzing=False)
        for rating in range(1, 5):
            with self.subTest(rating=rating), tempfile.TemporaryDirectory() as directory:
                store = StudyStore(Path(directory) / "progress.sqlite3", self.books, now=self.clock)
                session = store.dispatch("GET", "/api/study/session", {"book": "redbook"}, None)
                expected, _ = scheduler.review_card(Card(card_id=5, due=self.clock()), Rating(rating), self.clock())
                preview = session["card"]["intervals"][rating - 1]
                self.assertEqual(preview["seconds"], int((expected.due - self.clock()).total_seconds()))
                body = {"book": "redbook", "deck": "all", "cardId": session["card"]["id"],
                        "revision": session["card"]["revision"], "rating": rating,
                        "requestId": "rating-test", "durationMs": 0}
                store.dispatch("POST", "/api/study/answer", {}, body)
                saved = store.dispatch("GET", "/api/study/backup", {}, None)["books"][1]["cards"][0]["scheduler"]
                self.assertEqual(saved["due"], expected.due.isoformat())
                self.assertEqual(saved["state"], expected.state.value)
                self.assertEqual(saved["stability"], expected.stability)

    def test_due_learning_precedes_csv_new_and_future_waits(self):
        self.answer(1)
        self.assertEqual(self.session()["card"]["id"], "redbook-2")
        self.clock.advance(seconds=59)
        self.assertEqual(self.session()["card"]["id"], "redbook-2")
        self.clock.advance(seconds=1)
        self.assertEqual(self.session()["card"]["id"], "redbook-1")
        self.assertEqual(self.session()["card"]["phase"], "learning")

    def test_waiting_learning_is_never_rescheduled_early(self):
        self.settings(newPerDay=1)
        result, _ = self.answer(3)
        self.assertIsNone(result["card"])
        self.assertEqual(result["finishedReason"], "waiting")
        self.assertEqual(result["nextDue"], (self.clock() + timedelta(minutes=10)).isoformat())
        snapshot = self.backup()
        self.clock.advance(minutes=9)
        self.assertIsNone(self.session()["card"])
        self.assertEqual(self.backup()["books"], snapshot["books"])
        self.clock.advance(minutes=1)
        self.assertEqual(self.session()["card"]["phase"], "learning")

    def test_due_review_precedes_csv_new_and_relearning_steps(self):
        self.answer(4)
        self.clock.advance(days=20)
        session = self.session()
        self.assertEqual(session["card"]["id"], "redbook-1")
        self.assertEqual(session["card"]["phase"], "review")
        self.answer(1)
        stored = self.backup()["books"][1]["cards"][0]["scheduler"]
        self.assertEqual(stored["state"], State.Relearning.value)
        self.assertEqual(stored["due"], (self.clock() + timedelta(minutes=10)).isoformat())
        self.clock.advance(minutes=10)
        self.assertEqual(self.session()["card"]["phase"], "learning")

    def test_due_learning_precedes_due_review(self):
        self.answer(4)
        self.clock.advance(days=20)
        self.answer(3, deck="u2")
        self.clock.advance(minutes=10)
        self.assertEqual(self.session()["counts"]["due"], 1)
        self.assertEqual(self.session()["counts"]["learning"], 1)
        self.assertEqual(self.session()["card"]["id"], "redbook-3")

    def test_progress_persists_and_books_are_isolated(self):
        self.answer(4)
        self.store = StudyStore(self.db, self.books, now=self.clock)
        self.assertEqual(self.session()["card"]["id"], "redbook-2")
        self.assertEqual(self.session("liu")["card"]["id"], "liu-1")
        self.assertEqual(self.stats()["summary"]["totalReviews"], 1)
        self.assertEqual(self.stats("liu")["summary"]["totalReviews"], 0)

    def test_new_limit_is_whole_book_and_beijing_day(self):
        self.clock.value = datetime(2026, 10, 4, 15, 59, tzinfo=timezone.utc)
        self.settings(newPerDay=1)
        self.answer(4, deck="u1")
        self.assertIsNone(self.session(deck="u2")["card"])
        self.assertEqual(self.session(deck="u2")["finishedReason"], "daily-limit")
        self.assertEqual(self.stats()["summary"]["newRemaining"], 0)
        self.clock.advance(minutes=1)
        self.assertEqual(self.session(deck="u2")["card"]["id"], "redbook-3")
        self.assertEqual(self.stats()["summary"]["today"], 0)

    def test_review_limit_does_not_block_due_learning(self):
        self.settings(newPerDay=4, reviewPerDay=1)
        self.answer(4)
        self.answer(4)
        self.clock.advance(days=20)
        self.answer(1)
        self.settings(newPerDay=0, reviewPerDay=1)
        self.assertIsNone(self.session()["card"])
        self.clock.advance(minutes=10)
        self.assertEqual(self.session()["card"]["id"], "redbook-1")
        self.assertEqual(self.session()["counts"]["due"], 0)
        self.answer(3)
        self.assertEqual(self.stats()["summary"]["today"], 2)

    def test_stale_card_and_nonqueue_card_cannot_be_scored(self):
        old = self.session()["card"]
        self.answer(4)
        self.assert_error(409, lambda: self.answer(4, card=old))
        wrong = {"id": "redbook-4", "revision": self.backup()["books"][1]["cards"][3]["revision"]}
        self.assert_error(409, lambda: self.answer(4, card=wrong))
        self.assertEqual(self.stats()["summary"]["totalReviews"], 1)

    def test_network_retry_is_idempotent_and_id_reuse_rejected(self):
        response, body = self.answer(3, request_id="same-request")
        retry = self.store.dispatch("POST", "/api/study/answer", {}, body)
        self.assertEqual(retry, response)
        self.assertEqual(self.stats()["summary"]["totalReviews"], 1)
        changed = dict(body, rating=1)
        self.assert_error(409, lambda: self.store.dispatch("POST", "/api/study/answer", {}, changed))

    def test_concurrent_retry_and_stale_double_click(self):
        card = self.session()["card"]
        body = {"book": "redbook", "deck": "all", "cardId": card["id"], "revision": card["revision"],
                "rating": 3, "requestId": "parallel-retry", "durationMs": 500}
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.store.dispatch("POST", "/api/study/answer", {}, body), range(4)))
        self.assertTrue(all(response == responses[0] for response in responses))
        self.assertEqual(self.stats()["summary"]["totalReviews"], 1)
        self.assert_error(409, lambda: self.store.dispatch("POST", "/api/study/answer", {}, dict(body, requestId="double-click")))

    def test_concurrent_distinct_clicks_commit_exactly_once(self):
        card = self.session()["card"]
        body = {"book": "redbook", "deck": "all", "cardId": card["id"], "revision": card["revision"],
                "rating": 4, "requestId": "click", "durationMs": 500}
        def click(number):
            try:
                self.store.dispatch("POST", "/api/study/answer", {}, dict(body, requestId=f"click-{number}"))
                return 200
            except StudyError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(click, range(4)))
        self.assertEqual(sorted(statuses), [200, 409, 409, 409])
        self.assertEqual(self.stats()["summary"]["totalReviews"], 1)

    def test_undo_once_restores_scheduler_counts_and_fresh_revision(self):
        original = self.session()["card"]
        self.settings(newPerDay=1)
        _, body = self.answer(3)
        result = self.store.dispatch("POST", "/api/study/undo", {}, {"book": "redbook", "deck": "all"})
        self.assertEqual(result["card"]["id"], original["id"])
        self.assertGreater(result["card"]["revision"], original["revision"])
        self.assertEqual(result["counts"]["todayReviews"], 0)
        self.assertEqual(self.stats()["summary"]["newRemaining"], 1)
        self.assertEqual(self.stats()["summary"]["totalReviews"], 0)
        self.assertFalse(result["canUndo"])
        self.assert_error(409, lambda: self.store.dispatch("POST", "/api/study/undo", {}, {"book": "redbook"}))
        self.assert_error(409, lambda: self.store.dispatch("POST", "/api/study/answer", {}, body))
        self.assert_error(409, lambda: self.answer(1, card=original))

    def test_undo_review_restores_daily_review_allowance(self):
        self.answer(4)
        self.clock.advance(days=20)
        self.settings(newPerDay=0, reviewPerDay=1)
        before = self.backup()["books"][1]["cards"][0]["scheduler"]
        self.answer(3)
        self.store.dispatch("POST", "/api/study/undo", {}, {"book": "redbook"})
        self.assertEqual(self.backup()["books"][1]["cards"][0]["scheduler"], before)
        self.assertEqual(self.session()["counts"]["due"], 1)

    def test_backup_restore_replaces_all_progress_and_rejects_old_tabs(self):
        original = self.session()["card"]
        empty = self.backup()
        self.answer(4)
        self.answer(3, book="liu")
        restored = self.restore(empty)
        self.assertEqual(restored["cards"], 8)
        self.assertEqual(restored["books"], 2)
        automatic = self.db.parent / "backups" / restored["automaticBackup"]
        self.assertTrue(automatic.is_file())
        with closing(sqlite3.connect(automatic)) as connection, connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM reviews WHERE undone=0").fetchone()[0], 2)
        self.assertEqual(self.stats()["summary"]["totalReviews"], 0)
        self.assertEqual(self.stats("liu")["summary"]["totalReviews"], 0)
        self.assertGreater(self.session()["card"]["revision"], original["revision"])
        self.assert_error(409, lambda: self.answer(4, card=original))

    def test_backup_survives_actual_javascript_json_roundtrip(self):
        self.answer(3)
        self.answer(4, book="liu")
        snapshot = self.backup()
        serialized = subprocess.run(
            ["node", "-e", "let input=''; process.stdin.setEncoding('utf8'); process.stdin.on('data',s=>input+=s); process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(input))));"],
            input=backend._json(snapshot), text=True, capture_output=True, check=True,
        ).stdout
        roundtrip = json.loads(serialized)
        self.assertEqual(roundtrip, snapshot)
        self.assertTrue(self.restore(roundtrip)["restored"])
        self.assertEqual(self.stats()["summary"]["totalReviews"], 1)
        self.assertEqual(self.stats("liu")["summary"]["totalReviews"], 1)

    def test_public_integer_boundaries_and_counter_exhaustion_are_safe(self):
        limit = 2**53 - 1
        self.assertEqual(backend._integer(limit, "safe"), limit)
        self.assert_error(400, lambda: backend._integer(limit + 1, "unsafe"))
        self.answer(3)
        def check_integers(value):
            if type(value) is int:
                self.assertLessEqual(abs(value), limit)
            elif isinstance(value, dict):
                for item in value.values():
                    check_integers(item)
            elif isinstance(value, list):
                for item in value:
                    check_integers(item)
        check_integers(self.backup())
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE metadata SET value=? WHERE key='revision'", (limit,))
        snapshot = self.backup()
        self.assert_error(500, lambda: self.answer(4))
        self.assertEqual(self.backup()["books"], snapshot["books"])

    def test_restore_roundtrip_preserves_scheduler_history_and_undo(self):
        self.answer(3)
        exported = self.backup()
        self.answer(4)
        self.restore(exported)
        roundtrip = self.backup()
        self.assertEqual(roundtrip["books"][1]["cards"][0]["scheduler"], exported["books"][1]["cards"][0]["scheduler"])
        self.assertEqual(roundtrip["books"][1]["reviews"], exported["books"][1]["reviews"])
        self.assertTrue(self.session()["canUndo"])
        self.store.dispatch("POST", "/api/study/undo", {}, {"book": "redbook"})
        self.assertEqual(self.stats()["summary"]["today"], 0)

    def test_restore_rejects_unknown_schema_book_card_and_nonfinite_without_writes(self):
        self.answer(3)
        snapshot = self.backup()
        for mutator in (
            lambda value: value.update(schemaVersion=99),
            lambda value: value["books"][0].update(id="unknown"),
            lambda value: value["books"][1]["cards"][0].update(id="unknown"),
            lambda value: value["books"][1]["cards"][0]["scheduler"].update(stability=float("nan")),
            lambda value: value["books"][1]["cards"][0]["scheduler"].update(difficulty=11),
            lambda value: value["books"][1]["cards"][0]["scheduler"].update(step=40),
            lambda value: value["books"][1]["cards"][0]["scheduler"].update(stability=10**1000),
            lambda value: value["books"][1]["cards"][0].update(revision=2**63 - 1),
            lambda value: value["books"][1]["cards"][0]["scheduler"].update(due="2026-10-04T02:00:00"),
            lambda value: value["books"][1]["cards"].pop(),
        ):
            bad = copy.deepcopy(snapshot)
            mutator(bad)
            self.assert_error(400, lambda: self.restore(bad))
            self.assertEqual(self.backup()["books"], snapshot["books"])
        self.assertFalse((self.db.parent / "backups").exists())

    def test_restore_database_failure_rolls_back_after_backup(self):
        self.answer(3)
        snapshot = self.backup()
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("CREATE TRIGGER restore_fault BEFORE INSERT ON cards BEGIN SELECT RAISE(ABORT, 'test restore fault'); END")
        self.assert_error(500, lambda: self.restore(snapshot))
        self.assertEqual(self.backup()["books"], snapshot["books"])
        self.assertEqual(len(list((self.db.parent / "backups").glob("*.sqlite3"))), 1)

    def test_stats_ratings_days_forecast_and_undo_exclude_reverted_answers(self):
        self.answer(4)
        self.answer(3)
        self.store.dispatch("POST", "/api/study/undo", {}, {"book": "redbook"})
        stats = self.stats()
        self.assertEqual(stats["summary"]["today"], 1)
        self.assertEqual(stats["summary"]["studied"], 1)
        self.assertEqual([value["count"] for value in stats["ratings"]], [0, 0, 0, 1])
        self.assertEqual(stats["days"], [{"date": "2026-10-04", "count": 1}])
        self.assertEqual(sum(day["count"] for day in stats["forecast"]), 1)

    def test_input_validation_and_unknown_endpoints(self):
        self.assert_error(404, lambda: self.session("unknown"))
        self.assert_error(400, lambda: self.session(deck="unknown"))
        self.assert_error(400, lambda: self.settings(newPerDay=True))
        self.assert_error(400, lambda: self.settings(desiredRetention=float("nan")))
        self.assert_error(400, lambda: self.settings(desiredRetention=10**1000))
        self.assert_error(400, lambda: self.answer(True))
        self.assert_error(404, lambda: self.store.dispatch("GET", "/api/study/missing", {}, None))
        self.assert_error(405, lambda: self.store.dispatch("GET", "/api/study/answer", {}, None))


if __name__ == "__main__":
    unittest.main()
