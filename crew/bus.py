"""Append-only SQLite message bus — the single source of truth for a run.

messages is never UPDATEd or DELETEd (replayability + the GUI seam).
Read-tracking lives in a separate cursors table so append-only holds.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    thread_id TEXT NOT NULL DEFAULT 'main',
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cursors (
    agent TEXT PRIMARY KEY,
    last_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS agent_state (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Msg:
    id: int
    run_id: str
    ts: str
    sender: str
    recipient: str
    thread_id: str
    kind: str
    subject: str
    body: str

    def to_prompt(self) -> str:
        """Deterministic serialization for agent prompts.

        Sorted keys, no timestamp — a byte-stable prefix is what makes
        prompt caching (the crew's cost model) work.
        """
        payload = {
            "body": self.body,
            "id": self.id,
            "kind": self.kind,
            "recipient": self.recipient,
            "run_id": self.run_id,
            "sender": self.sender,
            "subject": self.subject,
            "thread_id": self.thread_id,
        }
        return json.dumps(payload, sort_keys=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Bus:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- messages (append-only) -------------------------------------------

    def append(
        self,
        *,
        run_id: str,
        sender: str,
        recipient: str,
        kind: str,
        subject: str,
        body: str,
        thread_id: str = "main",
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages (run_id, ts, sender, recipient, thread_id, kind, subject, body)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, _now(), sender, recipient, thread_id, kind, subject, body),
        )
        return cur.lastrowid

    def _rows_to_msgs(self, rows) -> list[Msg]:
        return [Msg(*row) for row in rows]

    def messages(
        self, run_id: str, *, kind: str | None = None, recipient: str | None = None
    ) -> list[Msg]:
        sql = (
            "SELECT id, run_id, ts, sender, recipient, thread_id, kind, subject, body"
            " FROM messages WHERE run_id = ?"
        )
        params: list[object] = [run_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if recipient is not None:
            sql += " AND recipient = ?"
            params.append(recipient)
        sql += " ORDER BY id"
        return self._rows_to_msgs(self._conn.execute(sql, params))

    def unread_for(self, run_id: str, agent: str) -> list[Msg]:
        rows = self._conn.execute(
            "SELECT id, run_id, ts, sender, recipient, thread_id, kind, subject, body"
            " FROM messages WHERE run_id = ? AND recipient = ?"
            " AND id > COALESCE((SELECT last_id FROM cursors WHERE agent = ?), 0)"
            " ORDER BY id",
            (run_id, agent, agent),
        )
        return self._rows_to_msgs(rows)

    def advance_cursor(self, agent: str, last_id: int) -> None:
        self._conn.execute(
            "INSERT INTO cursors (agent, last_id) VALUES (?, ?)"
            " ON CONFLICT(agent) DO UPDATE SET last_id = excluded.last_id",
            (agent, last_id),
        )

    def has_duplicate(
        self, run_id: str, sender: str, recipient: str, kind: str, body: str
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE run_id = ? AND sender = ? AND recipient = ?"
            " AND kind = ? AND body = ? LIMIT 1",
            (run_id, sender, recipient, kind, body),
        ).fetchone()
        return row is not None

    def count_kind(self, run_id: str, kind: str) -> int:
        (n,) = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE run_id = ? AND kind = ?", (run_id, kind)
        ).fetchone()
        return n

    # -- agent state (mutable by design; the GUI's "what is X doing") ------

    def set_status(self, agent: str, status: str) -> None:
        self._conn.execute(
            "INSERT INTO agent_state (name, status, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET status = excluded.status,"
            " updated_at = excluded.updated_at",
            (agent, status, _now()),
        )

    def get_status(self, agent: str) -> str:
        row = self._conn.execute(
            "SELECT status FROM agent_state WHERE name = ?", (agent,)
        ).fetchone()
        return row[0] if row else "idle"
