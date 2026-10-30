"""Bounded SQLite history, independent of Qt and the display server."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

MAX_ITEM_BYTES = 8 * 1024 * 1024
MAX_HISTORY_BYTES = 64 * 1024 * 1024
DEFAULT_LIMIT = 200
MAX_PINS = 50


@dataclass(frozen=True)
class Entry:
    id: int
    kind: str
    text: str
    size: int
    created_ns: int
    updated_ns: int
    pinned: bool


class HistoryStore:
    def __init__(
        self, path: Path, *, limit: int = DEFAULT_LIMIT,
        max_bytes: int = MAX_HISTORY_BYTES,
    ) -> None:
        if limit < 1 or max_bytes < 1:
            raise ValueError("History limits must be positive")
        self.path = Path(path)
        self.limit = limit
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                digest TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK(kind IN ('text', 'image')),
                text TEXT NOT NULL DEFAULT '',
                payload BLOB NOT NULL,
                size INTEGER NOT NULL,
                created_ns INTEGER NOT NULL,
                updated_ns INTEGER NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS entries_order
                ON entries(pinned DESC, updated_ns DESC, id DESC);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        if os.name == "posix":
            self.path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def add(self, kind: str, payload: bytes) -> int | None:
        if kind not in {"text", "image"}:
            raise ValueError("Unsupported clipboard type")
        if not payload or len(payload) > min(MAX_ITEM_BYTES, self.max_bytes):
            return None
        text = payload.decode("utf-8") if kind == "text" else ""
        if kind == "text" and not text.strip():
            return None
        digest = hashlib.sha256(kind.encode() + b"\0" + payload).hexdigest()
        now = time.time_ns()
        with self.db:
            existing = self.db.execute(
                "SELECT id FROM entries WHERE digest=?", (digest,)
            ).fetchone()
            if existing:
                self.db.execute(
                    "UPDATE entries SET updated_ns=? WHERE id=?", (now, existing["id"])
                )
                return existing["id"]
            # Pinned entries are never evicted. Reject an item that cannot fit.
            pinned = self.db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS size "
                "FROM entries WHERE pinned=1"
            ).fetchone()
            if pinned["n"] >= self.limit or pinned["size"] + len(payload) > self.max_bytes:
                return None
            cursor = self.db.execute(
                "INSERT INTO entries(digest,kind,text,payload,size,created_ns,updated_ns) "
                "VALUES(?,?,?,?,?,?,?)",
                (digest, kind, text, payload, len(payload), now, now),
            )
            self._prune()
            return cursor.lastrowid

    def _prune(self) -> None:
        totals = self.db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS size FROM entries"
        ).fetchone()
        count, size = totals["n"], totals["size"]
        if count <= self.limit and size <= self.max_bytes:
            return
        oldest = self.db.execute(
            "SELECT id,size FROM entries WHERE pinned=0 ORDER BY updated_ns,id"
        ).fetchall()
        for row in oldest:
            if count <= self.limit and size <= self.max_bytes:
                break
            self.db.execute("DELETE FROM entries WHERE id=?", (row["id"],))
            count -= 1
            size -= row["size"]

    def entries(self, query: str = "") -> list[Entry]:
        rows = self.db.execute(
            "SELECT id,kind,text,size,created_ns,updated_ns,pinned FROM entries "
            "ORDER BY pinned DESC,updated_ns DESC,id DESC"
        ).fetchall()
        needle = query.casefold().strip()
        return [
            Entry(**{**dict(row), "pinned": bool(row["pinned"])})
            for row in rows
            if not needle or needle in row["text"].casefold()
            or (row["kind"] == "image" and needle in "图片 image png")
        ]

    def payload(self, entry_id: int) -> bytes | None:
        row = self.db.execute("SELECT payload FROM entries WHERE id=?", (entry_id,)).fetchone()
        return bytes(row["payload"]) if row else None

    def touch(self, entry_id: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE entries SET updated_ns=? WHERE id=?", (time.time_ns(), entry_id)
            )

    def pin(self, entry_id: int, pinned: bool) -> bool:
        with self.db:
            row = self.db.execute("SELECT pinned FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                return False
            count = self.db.execute("SELECT COUNT(*) FROM entries WHERE pinned=1").fetchone()[0]
            if pinned and not row["pinned"] and count >= min(MAX_PINS, self.limit):
                return False
            self.db.execute("UPDATE entries SET pinned=? WHERE id=?", (int(pinned), entry_id))
            return True

    def delete(self, entry_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM entries WHERE id=?", (entry_id,))

    def clear(self, *, include_pinned: bool = False) -> None:
        with self.db:
            self.db.execute("DELETE FROM entries" + ("" if include_pinned else " WHERE pinned=0"))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (ValueError, TypeError):
            return default

    def set_setting(self, key: str, value) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
