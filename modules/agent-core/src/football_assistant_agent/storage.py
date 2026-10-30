"""Single service owns the companion database; explicit user memories only."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone
from uuid import uuid4


class CompanionStore:
    def __init__(self, path: Path):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS model_request_counts (budget_id TEXT PRIMARY KEY, count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        self._db.commit()
        if os.name != "nt":
            path.chmod(0o600)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def recent_messages(self, conversation_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?", (conversation_id, limit)).fetchall()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    def append_turn(self, conversation_id: str, message: str, reply: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db:
            self._db.executemany("INSERT INTO messages(conversation_id,role,content,created_at) VALUES (?,?,?,?)", [(conversation_id,"user",message,now),(conversation_id,"assistant",reply,now)])

    def add_memory(self, content: str) -> dict:
        memory = {"id": str(uuid4()), "content": content, "source": "user_explicit", "created_at": datetime.now(timezone.utc).isoformat()}
        with self._lock, self._db:
            self._db.execute("INSERT INTO memories(id,content,source,created_at) VALUES (:id,:content,:source,:created_at)", memory)
        return memory

    def memories(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id,content,source,created_at FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(("id","content","source","created_at"),row)) for row in reversed(rows)]

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM memories WHERE id=?", (memory_id,)).rowcount == 1

    def counts(self) -> dict:
        with self._lock:
            return {"messages": self._db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], "memories": self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]}

    def reserve_model_request(self, budget_id: str, limit: int) -> bool:
        if limit <= 0:
            return True
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO model_request_counts(budget_id,count) VALUES (?,0)",(budget_id,))
            used = self._db.execute("SELECT count FROM model_request_counts WHERE budget_id=?",(budget_id,)).fetchone()[0]
            if used >= limit:
                return False
            self._db.execute("UPDATE model_request_counts SET count=count+1 WHERE budget_id=?",(budget_id,))
            return True
