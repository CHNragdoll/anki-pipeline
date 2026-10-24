"""Independent, local web-study progress; never accesses an Anki collection.

Each operation opens its own storage connection. Queue selection and mutations share
one transaction, and revisions survive undo/restore without reusing an old token.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from fsrs import Card, Rating, Scheduler, State

from .study_progress_storage import StorageError


UTC = timezone.utc
BEIJING = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 1
BACKUP_VERSION = 2
DEFAULT_PREFERENCES = {
    "theme": "light", "fontSize": 18, "lineHeight": 1.8, "fontFamily": "system",
    "cardWidth": 1120, "wordSize": 48, "phoneticSize": 24,
    "showIntervals": True, "showRatingHints": True, "showQueueCounts": True, "showTimer": True,
    "showPosition": True, "showPhonetics": True, "showSources": True,
    "showFrequency": True, "showTags": True, "showEtymology": True, "showForms": True,
    "showExamples": True, "showCountdown": True,
    "spaceAction": "flip", "autoplay": "off", "autoplayBack": "off",
    "ukSource": "keep", "usSource": "keep", "audioVolume": 100, "audioRate": 1, "audioBalance": True,
    "lookup": "eudic", "selectionLookup": False,
    "newOrder": "original", "newPosition": "after", "reviewOrder": "due",
    "learningSteps": "1,10", "relearningSteps": "10",
}
LEGACY_PREFERENCE_KEYS = {"theme", "fontSize", "lineHeight", "showIntervals", "spaceAction",
    "autoplay", "ukSource", "usSource", "lookup", "selectionLookup"}
BACKUP_FORMAT = "independent-web-study"
RATINGS = ((1, "重来"), (2, "困难"), (3, "良好"), (4, "简单"))
DEFAULT_SETTINGS = {"newPerDay": 20, "reviewPerDay": 200, "desiredRetention": 0.9}
# These identities cross browser JSON.parse / JSON.stringify boundaries. SQLite's
# larger signed integer range is deliberately not exposed through the web API.
MAX_SAFE_INTEGER = 2**53 - 1


class StudyError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _integer(value, name, minimum=0, maximum=MAX_SAFE_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise StudyError(400, f"{name} 必须是 {minimum}–{maximum} 之间的整数")
    return value


def _number(value, name, minimum, maximum):
    if type(value) not in (int, float) or not minimum <= value <= maximum or not math.isfinite(value):
        raise StudyError(400, f"{name} 超出允许范围")
    return float(value)


def _timestamp(value, name):
    if not isinstance(value, str) or len(value) > 64:
        raise StudyError(400, f"{name} 必须是带时区的日期")
    try:
        date = datetime.fromisoformat(value)
        if date.tzinfo is None or date.utcoffset() is None:
            raise ValueError("timezone required")
        return date.astimezone(UTC)
    except (ValueError, OverflowError):
        raise StudyError(400, f"{name} 必须是带时区的有效日期") from None


def _fields(value, names, name):
    if not isinstance(value, dict) or set(value) != set(names):
        raise StudyError(400, f"{name} 字段不完整或含有未知字段")


def _settings(value):
    _fields(value, DEFAULT_SETTINGS, "settings")
    return {
        "newPerDay": _integer(value["newPerDay"], "newPerDay", maximum=10000),
        "reviewPerDay": _integer(value["reviewPerDay"], "reviewPerDay", maximum=10000),
        "desiredRetention": _number(value["desiredRetention"], "desiredRetention", .70, .99),
    }


def _display_interval(seconds):
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:g} 分钟"
    if seconds < 86400:
        return f"{seconds / 3600:g} 小时"
    return f"{seconds / 86400:g} 天"


class StudyStore:
    """Study API with catalog-only identities and independent progress state."""

    def __init__(self, db_path, books, now=None, *, storage=None):
        if storage is not None and db_path is not None:
            raise ValueError("provide a SQLite path or an explicit storage, not both")
        self._storage = storage
        self.db_path = Path(db_path).expanduser().resolve() if storage is None else None
        self.books = books
        self._now = now or (lambda: datetime.now(UTC))
        self._cards = {}
        self._decks = {}
        self._numeric_ids = {}
        numeric_seen = set()
        if not isinstance(books, dict) or not books:
            raise ValueError("books must be a nonempty catalog")
        for book_id, book in books.items():
            cards = {str(card["id"]): card for card in book["cards"]}
            if len(cards) != len(book["cards"]):
                raise ValueError("duplicate card ids in catalog")
            self._cards[book_id] = cards
            self._decks[book_id] = {str(deck["id"]): deck for deck in book["decks"]}
            for card_id in cards:
                numeric = int.from_bytes(hashlib.sha256(f"{book_id}\0{card_id}".encode()).digest()[:8], "big") & MAX_SAFE_INTEGER
                if numeric in numeric_seen:
                    raise ValueError("scheduler identity collision")
                numeric_seen.add(numeric)
                self._numeric_ids[book_id, card_id] = numeric
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    def _clock(self):
        date = self._now()
        if not isinstance(date, datetime) or date.tzinfo is None or date.utcoffset() is None:
            raise ValueError("now must return an aware datetime")
        return date.astimezone(UTC)

    def _connect(self):
        if self._storage is not None:
            return self._storage.connect()
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self, write=False):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        if self._storage is not None:
            # A normal PG constructor validates only: DDL and initial rows are
            # separate explicit operations, never a side effect of connecting.
            self._storage.validate()
            return
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise StudyError(500, "学习数据库版本不受支持，请保留原文件")
            if version == 1 and not connection.execute("SELECT 1 FROM sqlite_master WHERE name='card_controls'").fetchone():
                self._automatic_backup(self._clock(), reason="upgrade")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS card_controls (
                    book TEXT NOT NULL, card_id TEXT NOT NULL, flag INTEGER NOT NULL DEFAULT 0,
                    suspended INTEGER NOT NULL DEFAULT 0, buried_until TEXT, note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(book,card_id), FOREIGN KEY(book,card_id) REFERENCES cards(book,card_id));
                CREATE TABLE IF NOT EXISTS card_actions (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    book TEXT PRIMARY KEY, new_per_day INTEGER NOT NULL,
                    review_per_day INTEGER NOT NULL, desired_retention REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cards (
                    book TEXT NOT NULL, card_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    scheduler_json TEXT, introduced_at TEXT, PRIMARY KEY(book, card_id));
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT NOT NULL, card_id TEXT NOT NULL,
                    answered_at TEXT NOT NULL, day TEXT NOT NULL, rating INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL, phase TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0,
                    before_json TEXT, after_json TEXT NOT NULL, before_introduced_at TEXT,
                    revision_after INTEGER NOT NULL,
                    FOREIGN KEY(book, card_id) REFERENCES cards(book, card_id));
                CREATE INDEX IF NOT EXISTS reviews_book_day ON reviews(book, day, undone);
                CREATE TABLE IF NOT EXISTS undo (book TEXT PRIMARY KEY, review_id INTEGER);
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, review_id INTEGER NOT NULL,
                    FOREIGN KEY(review_id) REFERENCES reviews(id));
            """)
            connection.execute("BEGIN IMMEDIATE")
            self._initialize_rows(connection)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
            self.db_path.chmod(0o600)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_rows(self, connection):
        connection.execute("INSERT OR IGNORE INTO metadata VALUES ('revision', 0)")
        for book_id in self.books:
            connection.execute("INSERT OR IGNORE INTO settings VALUES (?,20,200,.9)", (book_id,))
            connection.execute("INSERT OR IGNORE INTO undo VALUES (?,NULL)", (book_id,))
            existing = {row[0] for row in connection.execute("SELECT card_id FROM cards WHERE book=?", (book_id,))}
            for card_id in self._cards[book_id]:
                if card_id not in existing:
                    revision = self._revision(connection)
                    connection.execute("INSERT INTO cards VALUES (?,?,?,NULL,NULL)", (book_id, card_id, revision))

    def initialize_catalog(self):
        """Explicitly add missing catalog identities without resetting any row."""
        with self._transaction(write=True) as connection:
            self._initialize_rows(connection)

    @staticmethod
    def _revision(connection):
        row = connection.execute("UPDATE metadata SET value=value+1 WHERE key='revision' AND value<? RETURNING value", (MAX_SAFE_INTEGER,)).fetchone()
        if row is None:
            raise StudyError(500, "学习版本编号已达到上限")
        return row[0]

    def _identity(self, source):
        if not isinstance(source, dict):
            raise StudyError(400, "请求必须是 JSON 对象")
        book = source.get("book")
        if not isinstance(book, str) or book not in self.books:
            raise StudyError(404, "词书不存在")
        deck = source.get("deck", "all")
        if not isinstance(deck, str) or (deck != "all" and deck not in self._decks[book]):
            raise StudyError(400, "单元不存在")
        return book, deck

    @staticmethod
    def _read_settings(connection, book):
        row = connection.execute("SELECT * FROM settings WHERE book=?", (book,)).fetchone()
        return {"newPerDay": row["new_per_day"], "reviewPerDay": row["review_per_day"], "desiredRetention": row["desired_retention"]}

    def _filtered_ids(self, book, deck):
        if deck == "all":
            return set(self._cards[book])
        deck_data = self._decks[book][deck]
        if "cardIds" in deck_data:
            return {str(card_id) for card_id in deck_data["cardIds"]}
        return {card_id for card_id, card in self._cards[book].items() if str(card.get("deckId")) == deck}

    def _queue(self, connection, book, deck, now):
        settings = self._read_settings(connection, book)
        prefs = self._preferences(connection)
        day = now.astimezone(BEIJING).date().isoformat()
        counts = connection.execute("""SELECT COUNT(*) AS total,
            COALESCE(SUM(phase='new'),0) AS new_used,
            COALESCE(SUM(phase='review'),0) AS review_used
            FROM reviews WHERE book=? AND day=? AND undone=0""", (book, day)).fetchone()
        new_remaining = max(0, settings["newPerDay"] - counts["new_used"])
        review_remaining = max(0, settings["reviewPerDay"] - counts["review_used"])
        states = {row["card_id"]: row for row in connection.execute("SELECT * FROM cards WHERE book=?", (book,))}
        allowed = self._filtered_ids(book, deck)
        controls = self._controls(connection, book)
        allowed -= {key for key, value in controls.items() if value["suspended"] or (value["buriedUntil"] and value["buriedUntil"] > day)}
        new, learning, reviews, future = [], [], [], []
        for order, card_id in enumerate(self._cards[book]):
            if card_id not in allowed:
                continue
            row = states[card_id]
            if row["scheduler_json"] is None:
                new.append(row)
                continue
            card = Card.from_dict(json.loads(row["scheduler_json"]))
            is_learning = card.state in (State.Learning, State.Relearning)
            if card.due <= now:
                (learning if is_learning else reviews).append((card.due, order, row))
            elif is_learning or review_remaining:
                future.append(card.due)
        learning.sort(key=lambda entry: entry[:2])
        reviews.sort(key=lambda entry: entry[1] if prefs["reviewOrder"] == "original" else entry[:2])
        if prefs["newOrder"] == "alphabetical":
            new.sort(key=lambda row: self._cards[book][row["card_id"]].get("word", "").casefold())
        elif prefs["newOrder"] == "random":
            new.sort(key=lambda row: hashlib.sha256(f"{book}:{day}:{row['card_id']}".encode()).digest())
        due_cards = [entry[2] for entry in reviews[:review_remaining]]
        new_cards = new[:new_remaining]
        if prefs["newPosition"] == "before":
            rest = new_cards + due_cards
        elif prefs["newPosition"] == "mixed":
            rest = []
            for index in range(max(len(due_cards), len(new_cards))):
                first, second = (new_cards, due_cards) if (counts["new_used"] + counts["review_used"]) % 2 else (due_cards, new_cards)
                if index < len(first): rest.append(first[index])
                if index < len(second): rest.append(second[index])
        else:
            rest = due_cards + new_cards
        # Intraday learning always remains ahead of either optional order.
        eligible = [entry[2] for entry in learning] + rest
        quota_blocked = bool((new and not new_remaining) or (reviews and not review_remaining))
        return {
            "settings": settings, "states": states, "eligible": eligible,
            "counts": {"new": min(len(new), new_remaining), "due": min(len(reviews), review_remaining),
                       "learning": len(learning), "todayReviews": counts["total"]},
            "nextDue": min(future).isoformat() if future else None,
            "finishedReason": None if eligible else ("waiting" if future else "daily-limit" if quota_blocked else "no-due"),
            "newRemaining": new_remaining,
        }

    def _card(self, row, book, settings, now, preferences=None):
        source = self._cards[book][row["card_id"]]
        if row["scheduler_json"] is None:
            card = Card(card_id=self._numeric_ids[book, row["card_id"]], due=now)
            phase = "new"
        else:
            card = Card.from_dict(json.loads(row["scheduler_json"]))
            phase = "review" if card.state == State.Review else "learning"
        scheduler = self._scheduler(settings, preferences or DEFAULT_PREFERENCES)
        intervals = []
        for rating, label in RATINGS:
            reviewed, _ = scheduler.review_card(card, Rating(rating), review_datetime=now)
            seconds = int((reviewed.due - now).total_seconds())
            intervals.append({"rating": rating, "label": label, "seconds": seconds, "display": _display_interval(seconds)})
        return {"id": row["card_id"], "word": source.get("word", ""), "meta": source.get("meta", ""),
                "previewUrl": source["previewUrl"], "revision": row["revision"], "phase": phase, "intervals": intervals}

    def _session(self, connection, book, deck, now):
        queue = self._queue(connection, book, deck, now)
        undo = connection.execute("SELECT review_id FROM undo WHERE book=?", (book,)).fetchone()[0]
        return {
            "book": {"id": book, "name": self.books[book]["name"]}, "deck": deck,
            "counts": queue["counts"], "settings": queue["settings"],
            "card": dict(self._card(queue["eligible"][0], book, queue["settings"], now, self._preferences(connection)), controls=self._controls(connection, book).get(queue["eligible"][0]["card_id"], self._default_controls())) if queue["eligible"] else None,
            "preferences": self._preferences(connection),
            "nextDue": queue["nextDue"], "canUndo": undo is not None, "finishedReason": queue["finishedReason"],
        }

    def dispatch(self, method, path, query, body):
        endpoints = {
            "/api/study/overview": "GET", "/api/study/session": "GET", "/api/study/answer": "POST",
            "/api/study/undo": "POST", "/api/study/settings": "POST", "/api/study/stats": "GET",
            "/api/study/backup": "GET", "/api/study/restore": "POST",
            "/api/study/browse": "GET", "/api/study/card": "GET", "/api/study/card-action": "POST",
            "/api/study/preferences": "POST",
        }
        if path not in endpoints:
            raise StudyError(404, "学习接口不存在")
        if method != endpoints[path]:
            raise StudyError(405, "此接口不支持该请求方法")
        now = self._clock()
        try:
            if path == "/api/study/restore":
                if not isinstance(body, dict) or set(body) != {"backup"}:
                    raise StudyError(400, "恢复请求必须包含完整 backup 对象")
                validated = self._validate_backup(body["backup"])
                return self._restore(validated, now)
            with self._transaction(write=method == "POST") as connection:
                if path == "/api/study/overview":
                    result = []
                    for book_id, book in self.books.items():
                        queue = self._queue(connection, book_id, "all", now)
                        row = {"id": book_id, "name": book["name"], "cardCount": len(self._cards[book_id]),
                               "previewPath": book["previewPath"], "decks": book["decks"],
                               "counts": queue["counts"], "settings": queue["settings"]}
                        if "scope" in book:
                            row["scope"] = copy.deepcopy(book["scope"])
                        result.append(row)
                    return {"books": result, "algorithm": "FSRS", "independent": True, "preferences": self._preferences(connection)}
                if path == "/api/study/backup":
                    return self._backup(connection, now)
                if path == "/api/study/preferences":
                    prefs = self._validate_preferences(body.get("preferences"))
                    before = self._preferences(connection)
                    if any(before[k] != prefs[k] for k in ("newOrder", "newPosition", "reviewOrder", "learningSteps", "relearningSteps")):
                        # Other tabs must reload their queue and interval prediction.
                        connection.execute("UPDATE cards SET revision=?", (self._revision(connection),))
                    connection.execute("INSERT INTO preferences VALUES (1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", (_json(prefs),))
                    return {"preferences": prefs}
                book, deck = self._identity(body if method == "POST" else query or {})
                if path == "/api/study/browse":
                    return self._browse(connection, book, deck, query, now)
                if path == "/api/study/card":
                    return self._card_info(connection, book, query.get("cardId"), now)
                if path == "/api/study/card-action":
                    return self._card_action(connection, book, deck, body, now)
                if path == "/api/study/answer":
                    return self._answer(connection, book, deck, body, now)
                if path == "/api/study/undo":
                    return self._undo(connection, book, deck, now)
                if path == "/api/study/settings":
                    settings = _settings({name: body.get(name) for name in DEFAULT_SETTINGS})
                    connection.execute("UPDATE settings SET new_per_day=?,review_per_day=?,desired_retention=? WHERE book=?",
                                       (settings["newPerDay"], settings["reviewPerDay"], settings["desiredRetention"], book))
                    return self._session(connection, book, "all", now)
                if path == "/api/study/stats":
                    return self._stats(connection, book, now)
                return self._session(connection, book, deck, now)
        except (sqlite3.Error, OSError, StorageError) as error:
            raise StudyError(500, "学习数据库操作失败；本次变更已回滚") from error

    def _answer(self, connection, book, deck, body, now):
        card_id = body.get("cardId")
        if not isinstance(card_id, str) or card_id not in self._cards[book]:
            raise StudyError(400, "卡片不属于此词书")
        revision = _integer(body.get("revision"), "revision", minimum=1)
        rating = _integer(body.get("rating"), "rating", minimum=1, maximum=4)
        duration = _integer(body.get("durationMs", 0), "durationMs", maximum=86400000)
        request_id = body.get("requestId")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128 or any(ord(character) < 32 for character in request_id):
            raise StudyError(400, "requestId 必须是 1–128 字符的请求标识")
        payload = {"book": book, "deck": deck, "cardId": card_id, "revision": revision,
                   "rating": rating, "durationMs": duration}
        payload_hash = hashlib.sha256(_json(payload).encode()).hexdigest()
        previous = connection.execute("""SELECT requests.payload_hash,reviews.undone FROM requests
            JOIN reviews ON reviews.id=requests.review_id WHERE request_id=?""", (request_id,)).fetchone()
        if previous is not None:
            if previous["payload_hash"] != payload_hash or previous["undone"]:
                raise StudyError(409, "该请求标识已使用或评分已撤销，请刷新学习卡片")
            return self._session(connection, book, deck, now)
        queue = self._queue(connection, book, deck, now)
        if not queue["eligible"] or queue["eligible"][0]["card_id"] != card_id:
            raise StudyError(409, "此卡片当前不可评分，请刷新学习队列")
        row = queue["eligible"][0]
        if row["revision"] != revision:
            raise StudyError(409, "卡片已在其他页面更新，请刷新后评分")
        if row["scheduler_json"] is None:
            card = Card(card_id=self._numeric_ids[book, card_id], due=now)
            phase = "new"
        else:
            card = Card.from_dict(json.loads(row["scheduler_json"]))
            phase = "review" if card.state == State.Review else "learning"
        scheduler = self._scheduler(queue["settings"], self._preferences(connection))
        reviewed, _ = scheduler.review_card(card, Rating(rating), review_datetime=now, review_duration=duration)
        after_json = _json(reviewed.to_dict())
        next_revision = self._revision(connection)
        introduced = row["introduced_at"] or now.isoformat()
        connection.execute("UPDATE cards SET scheduler_json=?,introduced_at=?,revision=? WHERE book=? AND card_id=?",
                           (after_json, introduced, next_revision, book, card_id))
        cursor = connection.execute("""INSERT INTO reviews (book,card_id,answered_at,day,rating,duration_ms,
            phase,before_json,after_json,before_introduced_at,revision_after) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (book, card_id, now.isoformat(), now.astimezone(BEIJING).date().isoformat(), rating, duration,
             phase, row["scheduler_json"], after_json, row["introduced_at"], next_revision))
        review_id = cursor.lastrowid
        if review_id > MAX_SAFE_INTEGER:
            raise StudyError(500, "评分记录编号已达到浏览器安全整数上限")
        connection.execute("UPDATE undo SET review_id=? WHERE book=?", (review_id, book))
        connection.execute("INSERT INTO requests VALUES (?,?,?)", (request_id, payload_hash, review_id))
        return self._session(connection, book, deck, now)

    def _undo(self, connection, book, deck, now):
        review_id = connection.execute("SELECT review_id FROM undo WHERE book=?", (book,)).fetchone()[0]
        if review_id is None:
            raise StudyError(409, "没有可撤销的上一次评分")
        row = connection.execute("SELECT * FROM reviews WHERE id=? AND book=? AND undone=0", (review_id, book)).fetchone()
        if row is None:
            raise StudyError(409, "上一次评分已撤销")
        revision = self._revision(connection)
        connection.execute("UPDATE cards SET scheduler_json=?,introduced_at=?,revision=? WHERE book=? AND card_id=?",
                           (row["before_json"], row["before_introduced_at"], revision, book, row["card_id"]))
        connection.execute("UPDATE reviews SET undone=1 WHERE id=?", (review_id,))
        connection.execute("UPDATE undo SET review_id=NULL WHERE book=?", (book,))
        return self._session(connection, book, deck, now)

    def _stats(self, connection, book, now):
        queue = self._queue(connection, book, "all", now)
        total, studied = connection.execute("SELECT COUNT(*),COUNT(DISTINCT card_id) FROM reviews WHERE book=? AND undone=0", (book,)).fetchone()
        ratings = dict(connection.execute("SELECT rating,COUNT(*) FROM reviews WHERE book=? AND undone=0 GROUP BY rating", (book,)).fetchall())
        days = [{"date": row[0], "count": row[1]} for row in connection.execute("SELECT day,COUNT(*) FROM reviews WHERE book=? AND undone=0 GROUP BY day ORDER BY day", (book,))]
        today = now.astimezone(BEIJING).date()
        controls = self._controls(connection, book)
        distribution = {"new": 0, "learning": 0, "review": 0, "buried": 0, "suspended": 0, "flagged": 0}
        day = today.isoformat()
        for card_id, row in queue["states"].items():
            control = controls.get(card_id, self._default_controls())
            distribution["flagged"] += bool(control["flag"])
            distribution["suspended"] += control["suspended"]
            distribution["buried"] += bool(control["buriedUntil"] and control["buriedUntil"] > day)
            phase = "new" if row["scheduler_json"] is None else "review" if Card.from_dict(json.loads(row["scheduler_json"])).state == State.Review else "learning"
            distribution[phase] += 1
        time_total, time_today = connection.execute("SELECT COALESCE(SUM(duration_ms),0),COALESCE(SUM(CASE WHEN day=? THEN duration_ms ELSE 0 END),0) FROM reviews WHERE book=? AND undone=0", (day,book)).fetchone()
        forecast = {(today + timedelta(days=offset)).isoformat(): 0 for offset in range(31)}
        for row in queue["states"].values():
            if controls.get(row["card_id"], {}).get("suspended"):
                continue
            if row["scheduler_json"] is not None:
                due = Card.from_dict(json.loads(row["scheduler_json"])).due.astimezone(BEIJING).date()
                buried = controls.get(row["card_id"], {}).get("buriedUntil")
                if buried and buried > due.isoformat():
                    due = datetime.fromisoformat(buried).date()
                date = max(today, due).isoformat()
                if date in forecast:
                    forecast[date] += 1
        return {
            "summary": {"today": queue["counts"]["todayReviews"], "totalReviews": total, "studied": studied,
                        "newRemaining": queue["newRemaining"], "due": queue["counts"]["due"], "learning": queue["counts"]["learning"], "totalTimeMs": time_total, "todayTimeMs": time_today,
                        "averageTimeMs": round(time_total/total) if total else 0},
            "distribution": distribution,
            "ratings": [{"rating": rating, "label": label, "count": ratings.get(rating, 0)} for rating, label in RATINGS],
            "days": days, "forecast": [{"date": date, "count": count} for date, count in forecast.items()],
        }

    def _backup(self, connection, now):
        books = []
        for book in self.books:
            cards = {row["card_id"]: row for row in connection.execute("SELECT * FROM cards WHERE book=?", (book,))}
            controls = self._controls(connection, book)
            reviews = []
            for row in connection.execute("SELECT * FROM reviews WHERE book=? ORDER BY id", (book,)):
                reviews.append({
                    "id": row["id"], "cardId": row["card_id"], "answeredAt": row["answered_at"], "day": row["day"],
                    "rating": row["rating"], "durationMs": row["duration_ms"], "phase": row["phase"], "undone": bool(row["undone"]),
                    "beforeScheduler": json.loads(row["before_json"]) if row["before_json"] is not None else None,
                    "afterScheduler": json.loads(row["after_json"]), "beforeIntroducedAt": row["before_introduced_at"],
                    "revisionAfter": row["revision_after"],
                })
            books.append({
                "id": book, "settings": self._read_settings(connection, book),
                "cards": [{"id": card_id, "revision": cards[card_id]["revision"], "introducedAt": cards[card_id]["introduced_at"],
                           "controls": controls.get(card_id, self._default_controls()), "scheduler": json.loads(cards[card_id]["scheduler_json"])
                           if cards[card_id]["scheduler_json"] is not None else None} for card_id in self._cards[book]],
                "reviews": reviews, "undoReviewId": connection.execute("SELECT review_id FROM undo WHERE book=?", (book,)).fetchone()[0],
            })
        return {"format": BACKUP_FORMAT, "schemaVersion": BACKUP_VERSION, "preferences": self._preferences(connection), "algorithm": "FSRS",
                "schedulerVersion": "6.3.2", "exportedAt": now.isoformat(), "books": books}

    def _validate_scheduler(self, value, book, card_id, nullable=False, multi_step=False):
        if value is None and nullable:
            return None
        _fields(value, ("card_id", "state", "step", "stability", "difficulty", "due", "last_review"), "scheduler")
        if _integer(value["card_id"], "scheduler.card_id") != self._numeric_ids[book, card_id]:
            raise StudyError(400, "调度器卡片身份与词书不一致")
        state = _integer(value["state"], "scheduler.state", minimum=1, maximum=3)
        if state == State.Review.value:
            if value["step"] is not None:
                raise StudyError(400, "复习卡片不能包含学习步骤")
        else:
            _integer(value["step"], "scheduler.step", maximum=5 if multi_step else (1 if state == State.Learning.value else 0))
        stability = _number(value["stability"], "scheduler.stability", 1e-12, 1e12)
        difficulty = _number(value["difficulty"], "scheduler.difficulty", 1, 10)
        due = _timestamp(value["due"], "scheduler.due")
        last_review = _timestamp(value["last_review"], "scheduler.last_review")
        if due < last_review:
            raise StudyError(400, "到期时间早于上次评分")
        normalized = dict(value, stability=stability, difficulty=difficulty,
                          due=due.isoformat(), last_review=last_review.isoformat())
        # Exercise all four paths before replacing anything, including overflow.
        try:
            scheduler = Scheduler(enable_fuzzing=False, learning_steps=tuple(timedelta(minutes=n) for n in range(1,7)), relearning_steps=tuple(timedelta(minutes=n) for n in range(1,7))) if multi_step else Scheduler(enable_fuzzing=False)
            card = Card.from_dict(normalized)
            for rating in Rating:
                scheduler.review_card(card, rating, review_datetime=due)
        except (ValueError, OverflowError, AssertionError, TypeError, ZeroDivisionError):
            raise StudyError(400, "调度器状态无法安全恢复") from None
        return normalized

    def _validate_legacy_backup(self, value, multi_step=False):
        _fields(value, ("format", "schemaVersion", "algorithm", "schedulerVersion", "exportedAt", "books"), "backup")
        if (value["format"] != BACKUP_FORMAT or type(value["schemaVersion"]) is not int or
                value["schemaVersion"] != SCHEMA_VERSION or value["algorithm"] != "FSRS" or value["schedulerVersion"] != "6.3.2"):
            raise StudyError(400, "此进度备份格式或版本不受支持")
        _timestamp(value["exportedAt"], "exportedAt")
        if not isinstance(value["books"], list) or len(value["books"]) != len(self.books):
            raise StudyError(400, "备份必须包含全部词书")
        seen_books, seen_reviews, normalized_books = set(), set(), []
        for source in value["books"]:
            _fields(source, ("id", "settings", "cards", "reviews", "undoReviewId"), "book")
            book = source["id"]
            if not isinstance(book, str) or book not in self.books or book in seen_books:
                raise StudyError(400, "备份包含未知或重复词书")
            seen_books.add(book)
            settings = _settings(source["settings"])
            if not isinstance(source["cards"], list) or len(source["cards"]) != len(self._cards[book]):
                raise StudyError(400, "备份卡片集合与词书不一致")
            cards = {}
            for card in source["cards"]:
                _fields(card, ("id", "revision", "introducedAt", "scheduler"), "card")
                card_id = card["id"]
                if not isinstance(card_id, str) or card_id not in self._cards[book] or card_id in cards:
                    raise StudyError(400, "备份包含未知或重复卡片")
                revision = _integer(card["revision"], "revision", minimum=1,
                                    maximum=MAX_SAFE_INTEGER - sum(len(cards) for cards in self._cards.values()))
                scheduler = self._validate_scheduler(card["scheduler"], book, card_id, nullable=True, multi_step=multi_step)
                introduced = _timestamp(card["introducedAt"], "introducedAt").isoformat() if card["introducedAt"] is not None else None
                if (scheduler is None) != (introduced is None) or (scheduler and introduced > scheduler["last_review"]):
                    raise StudyError(400, "卡片开始学习时间与调度器不一致")
                cards[card_id] = dict(card, revision=revision, scheduler=scheduler, introducedAt=introduced)
            if not isinstance(source["reviews"], list):
                raise StudyError(400, "reviews 必须是评分记录列表")
            reviews, active, previous_id = [], {}, 0
            for review in source["reviews"]:
                _fields(review, ("id", "cardId", "answeredAt", "day", "rating", "durationMs", "phase", "undone",
                                 "beforeScheduler", "afterScheduler", "beforeIntroducedAt", "revisionAfter"), "review")
                review_id = _integer(review["id"], "review.id", minimum=1, maximum=MAX_SAFE_INTEGER - 1)
                if review_id in seen_reviews or review_id <= previous_id:
                    raise StudyError(400, "评分记录标识重复或顺序错误")
                seen_reviews.add(review_id)
                previous_id = review_id
                card_id = review["cardId"]
                if not isinstance(card_id, str) or card_id not in cards:
                    raise StudyError(400, "评分记录包含未知卡片")
                answered = _timestamp(review["answeredAt"], "answeredAt")
                if review["day"] != answered.astimezone(BEIJING).date().isoformat():
                    raise StudyError(400, "评分日期与北京时间不一致")
                _integer(review["rating"], "rating", minimum=1, maximum=4)
                _integer(review["durationMs"], "durationMs", maximum=86400000)
                _integer(review["revisionAfter"], "revisionAfter", minimum=1)
                if review["phase"] not in ("new", "learning", "review") or type(review["undone"]) is not bool:
                    raise StudyError(400, "评分阶段或撤销标记不正确")
                before = self._validate_scheduler(review["beforeScheduler"], book, card_id, nullable=True, multi_step=multi_step)
                after = self._validate_scheduler(review["afterScheduler"], book, card_id, multi_step=multi_step)
                introduced = _timestamp(review["beforeIntroducedAt"], "beforeIntroducedAt").isoformat() if review["beforeIntroducedAt"] is not None else None
                expected_phase = "new" if before is None else "review" if before["state"] == State.Review.value else "learning"
                if review["phase"] != expected_phase or (before is None) != (introduced is None) or after["last_review"] != answered.isoformat():
                    raise StudyError(400, "评分记录与调度器不一致")
                if before and (_timestamp(before["due"], "due") > answered or introduced > before["last_review"]):
                    raise StudyError(400, "评分记录提前复习或开始时间无效")
                normalized = dict(review, answeredAt=answered.isoformat(), beforeScheduler=before,
                                  afterScheduler=after, beforeIntroducedAt=introduced)
                reviews.append(normalized)
                if not review["undone"]:
                    chain = active.setdefault(card_id, [])
                    if chain:
                        if before != chain[-1]["afterScheduler"] or introduced != chain[0]["answeredAt"]:
                            raise StudyError(400, "评分历史无法与卡片进度对账")
                    elif before is not None:
                        raise StudyError(400, "评分历史缺少首次学习记录")
                    chain.append(normalized)
            for card_id, card in cards.items():
                chain = active.get(card_id)
                if chain:
                    if card["scheduler"] != chain[-1]["afterScheduler"] or card["introducedAt"] != chain[0]["answeredAt"]:
                        raise StudyError(400, "卡片状态与最后一次有效评分不一致")
                elif card["scheduler"] is not None:
                    raise StudyError(400, "已学习卡片缺少有效评分历史")
            undo_id = source["undoReviewId"]
            if undo_id is not None:
                _integer(undo_id, "undoReviewId", minimum=1)
                if not reviews or reviews[-1]["id"] != undo_id or reviews[-1]["undone"]:
                    raise StudyError(400, "可撤销评分必须是本书最后一次有效操作")
            normalized_books.append({"id": book, "settings": settings, "cards": list(cards.values()),
                                     "reviews": reviews, "undoReviewId": undo_id})
        return normalized_books

    def _automatic_backup(self, now, reason="restore", connection=None):
        if self._storage is not None:
            if connection is None:
                raise StorageError("PG automatic backup requires the current locked transaction")
            return self._storage.automatic_backup(connection, now, reason)
        directory = self.db_path.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        basename = f"progress-before-{reason}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}.sqlite3"
        destination = directory / basename
        temporary = destination.with_suffix(".tmp")
        source = self._connect()
        backup = sqlite3.connect(temporary)
        try:
            source.backup(backup)
            backup.close()
            temporary.chmod(0o600)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            temporary.replace(destination)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            backup.close()
            temporary.unlink(missing_ok=True)
            raise
        finally:
            source.close()
        return basename

    def _restore(self, validated, now):
        books, controls, preferences = validated
        with self._transaction(write=True) as connection:
            # Another read connection snapshots the committed pre-restore state;
            # BEGIN IMMEDIATE prevents an intervening writer before replacement.
            automatic = self._automatic_backup(now, connection=connection)
            maximum = max(card["revision"] for book in books for card in book["cards"])
            connection.execute("UPDATE metadata SET value=MAX(value,?) WHERE key='revision'", (maximum,))
            connection.execute("DELETE FROM card_controls")
            connection.execute("DELETE FROM card_actions")
            connection.execute("DELETE FROM preferences")
            connection.execute("INSERT INTO preferences VALUES (1,?)", (_json(preferences),))
            connection.execute("DELETE FROM requests")
            connection.execute("DELETE FROM reviews")
            connection.execute("DELETE FROM undo")
            connection.execute("DELETE FROM cards")
            connection.execute("DELETE FROM settings")
            for book in books:
                book_id, settings = book["id"], book["settings"]
                connection.execute("INSERT INTO settings VALUES (?,?,?,?)",
                                   (book_id, settings["newPerDay"], settings["reviewPerDay"], settings["desiredRetention"]))
                for card in book["cards"]:
                    connection.execute("INSERT INTO cards VALUES (?,?,?,?,?)",
                                       (book_id, card["id"], self._revision(connection),
                                        _json(card["scheduler"]) if card["scheduler"] is not None else None, card["introducedAt"]))
                for card_id, control in controls.get(book_id, {}).items():
                    connection.execute("INSERT INTO card_controls VALUES (?,?,?,?,?,?)", (book_id,card_id,control["flag"],int(control["suspended"]),control["buriedUntil"],control["note"]))
                for review in book["reviews"]:
                    connection.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (review["id"], book_id, review["cardId"], review["answeredAt"], review["day"], review["rating"],
                         review["durationMs"], review["phase"], int(review["undone"]),
                         _json(review["beforeScheduler"]) if review["beforeScheduler"] is not None else None,
                         _json(review["afterScheduler"]), review["beforeIntroducedAt"], review["revisionAfter"]))
                connection.execute("INSERT INTO undo VALUES (?,?)", (book_id, book["undoReviewId"]))
            return {"restored": True, "books": len(books), "cards": sum(len(book["cards"]) for book in books), "automaticBackup": automatic}

    @staticmethod
    def _default_controls():
        return {"flag": 0, "suspended": False, "buriedUntil": None, "note": ""}

    def _controls(self, connection, book):
        return {row["card_id"]: {"flag": row["flag"], "suspended": bool(row["suspended"]),
                "buriedUntil": row["buried_until"], "note": row["note"]}
                for row in connection.execute("SELECT * FROM card_controls WHERE book=?", (book,))}

    @staticmethod
    def _steps(value):
        if not isinstance(value, str) or len(value) > 80:
            raise StudyError(400, "学习步骤请用逗号分隔的分钟数填写")
        try:
            steps = [float(part.strip()) for part in value.split(",")]
        except ValueError:
            raise StudyError(400, "学习步骤请用逗号分隔的分钟数填写")
        if not 1 <= len(steps) <= 6 or any(not math.isfinite(n) or not 0.1 <= n <= 1440 for n in steps):
            raise StudyError(400, "学习步骤须为 1–6 项，每项 0.1–1440 分钟")
        if steps != sorted(steps) or len(set(steps)) != len(steps):
            raise StudyError(400, "学习步骤须按分钟数递增，不能重复")
        return tuple(timedelta(minutes=n) for n in steps)

    @classmethod
    def _scheduler(cls, settings, prefs):
        return Scheduler(desired_retention=settings["desiredRetention"], enable_fuzzing=False,
            learning_steps=cls._steps(prefs["learningSteps"]), relearning_steps=cls._steps(prefs["relearningSteps"]))

    @classmethod
    def _validate_preferences(cls, value):
        if not isinstance(value, dict) or not LEGACY_PREFERENCE_KEYS <= set(value) or set(value) - set(DEFAULT_PREFERENCES):
            raise StudyError(400, "preferences 字段不完整或含有未知字段")
        value = dict(DEFAULT_PREFERENCES, **value)
        for key, choices in {"theme": ("light", "dark", "system"), "spaceAction": ("flip", "good"),
            "autoplay": ("off", "uk", "us"), "autoplayBack": ("off", "uk", "us"),
            "ukSource": ("keep", "cambridge", "oxford"), "usSource": ("keep", "oxford", "webster"),
            "lookup": ("eudic", "oxford", "cambridge", "webster", "off"), "fontFamily": ("system", "serif"),
            "newOrder": ("original", "alphabetical", "random"), "newPosition": ("after", "before", "mixed"),
            "reviewOrder": ("due", "original")}.items():
            if value[key] not in choices: raise StudyError(400, f"{key} 的设置不受支持")
        for key, limits in {"fontSize": (14,28), "wordSize": (24,96), "phoneticSize": (14,40),
            "cardWidth": (720,1440), "audioVolume": (0,100)}.items():
            _integer(value[key], key, minimum=limits[0], maximum=limits[1])
        _number(value["lineHeight"], "lineHeight", 1.4, 2.4)
        _number(value["audioRate"], "audioRate", .5, 1.5)
        for key, default in DEFAULT_PREFERENCES.items():
            if type(default) is bool and type(value[key]) is not bool: raise StudyError(400, f"{key} 须为布尔值")
        cls._steps(value["learningSteps"]); cls._steps(value["relearningSteps"])
        return value

    def _preferences(self, connection):
        row = connection.execute("SELECT value FROM preferences WHERE id=1").fetchone()
        return dict(DEFAULT_PREFERENCES, **json.loads(row[0])) if row else dict(DEFAULT_PREFERENCES)

    def _card_info(self, connection, book, card_id, now):
        if not isinstance(card_id, str) or card_id not in self._cards[book]:
            raise StudyError(404, "卡片不属于此词书")
        row = connection.execute("SELECT * FROM cards WHERE book=? AND card_id=?", (book,card_id)).fetchone()
        control = self._controls(connection, book).get(card_id, self._default_controls())
        data = self._card(row, book, self._read_settings(connection,book), now, self._preferences(connection))
        scheduler = json.loads(row["scheduler_json"]) if row["scheduler_json"] else None
        history = [{"answeredAt": r["answered_at"], "rating": r["rating"], "durationMs": r["duration_ms"],
                    "undone": bool(r["undone"]), "nextDue": json.loads(r["after_json"])["due"]}
                   for r in connection.execute("SELECT * FROM reviews WHERE book=? AND card_id=? ORDER BY id DESC LIMIT 100", (book,card_id))]
        return dict(data, controls=control, introducedAt=row["introduced_at"], due=scheduler["due"] if scheduler else None,
                    stability=scheduler["stability"] if scheduler else None,
                    difficulty=scheduler["difficulty"] if scheduler else None, history=history,
                    historyCount=connection.execute("SELECT COUNT(*) FROM reviews WHERE book=? AND card_id=?",(book,card_id)).fetchone()[0],
                    effectiveReviews=connection.execute("SELECT COUNT(*) FROM reviews WHERE book=? AND card_id=? AND undone=0",(book,card_id)).fetchone()[0])

    def _browse(self, connection, book, deck, query, now):
        search = query.get("search", "").strip().casefold()
        if len(search) > 200:
            raise StudyError(400, "搜索内容不能超过 200 字符")
        filter_name = query.get("filter", "all")
        if filter_name not in ("all", "new", "learning", "review", "due", "flagged", "buried", "suspended", "notes"):
            raise StudyError(400, "筛选条件不受支持")
        try:
            offset = int(query.get("offset", 0))
        except (ValueError, TypeError):
            raise StudyError(400, "分页位置无效") from None
        _integer(offset, "offset", maximum=1000000)
        allowed = self._filtered_ids(book, deck)
        controls = self._controls(connection, book)
        rows = {r["card_id"]: r for r in connection.execute("SELECT * FROM cards WHERE book=?", (book,))}
        day = now.astimezone(BEIJING).date().isoformat()
        matches = []
        for card_id, source in self._cards[book].items():
            if card_id not in allowed:
                continue
            control = controls.get(card_id, self._default_controls())
            if search and search not in " ".join(str(source.get(k,"")) for k in ("word","meaning","search","meta")).casefold() and search not in control["note"].casefold():
                continue
            row = rows[card_id]
            scheduled = Card.from_dict(json.loads(row["scheduler_json"])) if row["scheduler_json"] else None
            phase = "new" if scheduled is None else "review" if scheduled.state == State.Review else "learning"
            buried = bool(control["buriedUntil"] and control["buriedUntil"] > day)
            due = bool(scheduled and scheduled.due <= now and not buried and not control["suspended"])
            checks = {"all": True, "new":phase=="new", "learning":phase=="learning", "review":phase=="review", "due":due,
                      "flagged": bool(control["flag"]), "buried":buried, "suspended":control["suspended"], "notes":bool(control["note"])}
            if checks[filter_name]:
                matches.append({"id":card_id, "word":source.get("word", ""), "meta":source.get("meta", ""),
                    "phase":phase, "due":scheduled.due.isoformat() if scheduled else None,
                    "revision":row["revision"], "controls":control, "buried":buried})
        return {"book":book, "deck":deck, "total":len(matches), "offset":offset, "limit":50, "cards":matches[offset:offset+50]}

    def _card_action(self, connection, book, deck, body, now):
        action = body.get("action")
        if action not in ("flag", "note", "bury", "unbury", "suspend", "unsuspend", "unburyAll"):
            raise StudyError(400, "卡片操作不受支持")
        request_id = body.get("requestId")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128 or any(ord(c)<32 for c in request_id):
            raise StudyError(400, "卡片操作须有有效请求标识")
        payload_hash = hashlib.sha256(_json(body).encode()).hexdigest()
        previous = connection.execute("SELECT payload_hash FROM card_actions WHERE request_id=?", (request_id,)).fetchone()
        if previous:
            if previous[0] != payload_hash:
                raise StudyError(409, "此操作标识已使用，请刷新")
            return {"session":self._session(connection,book,deck,now), "card":self._card_info(connection,book,body["cardId"],now) if action!="unburyAll" else None}
        if action == "unburyAll":
            today = now.astimezone(BEIJING).date().isoformat()
            allowed = self._filtered_ids(book,deck)
            ids = [r[0] for r in connection.execute("SELECT card_id FROM card_controls WHERE book=? AND buried_until>?",(book,today)) if r[0] in allowed]
            for card_id in ids:
                connection.execute("UPDATE card_controls SET buried_until=NULL WHERE book=? AND card_id=?",(book,card_id))
                connection.execute("UPDATE cards SET revision=? WHERE book=? AND card_id=?",(self._revision(connection),book,card_id))
        else:
            card_id = body.get("cardId")
            if not isinstance(card_id,str) or card_id not in self._filtered_ids(book,deck):
                raise StudyError(400, "卡片不属于此学习范围")
            row = connection.execute("SELECT revision FROM cards WHERE book=? AND card_id=?",(book,card_id)).fetchone()
            if _integer(body.get("revision"),"revision",minimum=1) != row[0]:
                raise StudyError(409, "卡片已在其他页面更新，请重新读取")
            control = self._controls(connection,book).get(card_id,self._default_controls())
            if action == "flag":
                control["flag"] = _integer(body.get("value"),"flag",maximum=7)
            elif action == "note":
                note = body.get("value")
                if not isinstance(note,str) or len(note)>10000 or '\x00' in note:
                    raise StudyError(400,"学习笔记限 10000 字符")
                control["note"] = note
            elif action == "bury":
                control["buriedUntil"] = (now.astimezone(BEIJING).date()+timedelta(days=1)).isoformat()
            elif action == "unbury":
                control["buriedUntil"] = None
            elif action in ("suspend","unsuspend"):
                control["suspended"] = action == "suspend"
            connection.execute("INSERT INTO card_controls VALUES (?,?,?,?,?,?) ON CONFLICT(book,card_id) DO UPDATE SET flag=excluded.flag,suspended=excluded.suspended,buried_until=excluded.buried_until,note=excluded.note",(book,card_id,control["flag"],int(control["suspended"]),control["buriedUntil"],control["note"]))
            connection.execute("UPDATE cards SET revision=? WHERE book=? AND card_id=?",(self._revision(connection),book,card_id))
        connection.execute("INSERT INTO card_actions VALUES (?,?)",(request_id,payload_hash))
        return {"session":self._session(connection,book,deck,now), "card":self._card_info(connection,book,body["cardId"],now) if action!="unburyAll" else None}

    def _validate_backup(self, value):
        if not isinstance(value,dict):
            raise StudyError(400,"备份必须是完整对象")
        legacy = copy.deepcopy(value)
        controls, prefs = {}, dict(DEFAULT_PREFERENCES)
        version = value.get("schemaVersion")
        if type(version) is int and version == BACKUP_VERSION:
            _fields(value,("format","schemaVersion","algorithm","schedulerVersion","exportedAt","books","preferences"),"backup")
            prefs = self._validate_preferences(legacy.pop("preferences"))
            legacy["schemaVersion"] = SCHEMA_VERSION
            if not isinstance(legacy["books"],list):
                raise StudyError(400,"备份词书无效")
            for book in legacy["books"]:
                if not isinstance(book,dict) or not isinstance(book.get("cards"),list):
                    raise StudyError(400,"备份卡片无效")
                if not isinstance(book.get("id"),str):
                    raise StudyError(400,"备份词书身份无效")
                controls[book["id"]] = {}
                for card in book["cards"]:
                    if not isinstance(card,dict):
                        raise StudyError(400,"备份卡片无效")
                    if not isinstance(card.get("id"),str):
                        raise StudyError(400,"备份卡片身份无效")
                    control = card.pop("controls",None)
                    _fields(control,("flag","suspended","buriedUntil","note"),"controls")
                    _integer(control["flag"],"flag",maximum=7)
                    if type(control["suspended"]) is not bool or not isinstance(control["note"],str) or len(control["note"])>10000 or '\x00' in control["note"]:
                        raise StudyError(400,"卡片设置或笔记无效")
                    if control["buriedUntil"] is not None:
                        try:
                            if datetime.fromisoformat(control["buriedUntil"]).date().isoformat() != control["buriedUntil"]:
                                raise ValueError()
                        except (ValueError,TypeError):
                            raise StudyError(400,"暂缓日期无效") from None
                    # IDs are validated by the original complete history reconciliation below.
                    controls[book["id"]][card.get("id")] = control
        return self._validate_legacy_backup(legacy, multi_step=version == BACKUP_VERSION), controls, prefs
