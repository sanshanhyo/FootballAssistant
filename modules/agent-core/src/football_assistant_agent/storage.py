"""Single service owns the companion database; explicit user memories only."""
from __future__ import annotations

from contextlib import closing

import os
from pathlib import Path
import sqlite3
import threading
import re
import json
from datetime import datetime, timezone
from uuid import uuid4


DEFAULT_CHARACTER_ID = "official.eckera"
ARCHIVE_SAVE_ID = "legacy:unassigned"


def character_scope(save_id: str | None, character_id: str | None) -> tuple[str, str]:
    # Legacy callers keep access to their archive, never to a newly selected save.
    if save_id is None and character_id is None:
        return ARCHIVE_SAVE_ID, DEFAULT_CHARACTER_ID
    if not isinstance(save_id, str) or not save_id.strip() or len(save_id.encode()) > 512:
        raise ValueError("Explicit save_id is required")
    if character_id == "builtin.eckera":
        character_id = DEFAULT_CHARACTER_ID
    if not isinstance(character_id, str) or len(character_id) > 96 or not re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+", character_id):
        raise ValueError("Explicit character_id is required")
    return save_id, character_id


class CompanionStore:
    def __init__(self, path: Path | None):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(":memory:" if path is None else path, check_same_thread=False)
        self._db.execute("PRAGMA busy_timeout = 5000")
        if path is None:
            self._db.execute("PRAGMA temp_store = MEMORY")
        existing = self._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'").fetchone()
        if existing and path is not None and "save_id" not in {row[1] for row in self._db.execute("PRAGMA table_info(messages)")}:
            # SQLite backup includes committed WAL data. Never overwrite the first backup.
            backup_path = path.with_name(path.name + ".pre-character-v1.bak")
            if backup_path.exists():
                if backup_path.is_symlink() or not backup_path.is_file():
                    raise ValueError("Unsafe character migration backup")
                with closing(sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)) as backup:
                    if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Invalid character migration backup")
            else:
                temporary = backup_path.with_name(backup_path.name + f".{uuid4()}.tmp")
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                try:
                    with closing(sqlite3.connect(temporary)) as backup:
                        self._db.backup(backup)
                    # Publish a complete backup without replacing an existing one.
                    try:
                        os.link(temporary, backup_path)
                    except FileExistsError:
                        pass
                finally:
                    temporary.unlink(missing_ok=True)
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
        # A transaction makes the schema migration repeatable after interruption.
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            for table in ("messages", "memories"):
                columns = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
                if "save_id" not in columns:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN save_id TEXT NOT NULL DEFAULT 'legacy:unassigned'")
                if "character_id" not in columns:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN character_id TEXT NOT NULL DEFAULT 'official.eckera'")
            self._db.execute("CREATE INDEX IF NOT EXISTS messages_character_scope ON messages(save_id,character_id,conversation_id,id)")
            self._db.execute("CREATE INDEX IF NOT EXISTS memories_character_scope ON memories(save_id,character_id,created_at)")
            self._db.execute("CREATE TABLE IF NOT EXISTS character_migrations (name TEXT PRIMARY KEY, completed_at TEXT NOT NULL)")
            self._db.execute("INSERT OR IGNORE INTO character_migrations VALUES ('scope-v1',?)", (datetime.now(timezone.utc).isoformat(),))
        if path is not None and os.name != "nt":
            path.chmod(0o600)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def recent_messages(self, conversation_id: str, limit: int = 20, *, save_id: str | None = None, character_id: str | None = None) -> list[dict]:
        scope = character_scope(save_id, character_id)
        with self._lock:
            rows = self._db.execute("SELECT role,content FROM messages WHERE save_id=? AND character_id=? AND conversation_id=? ORDER BY id DESC LIMIT ?", (*scope, conversation_id, limit)).fetchall()
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    def append_turn(self, conversation_id: str, message: str, reply: str, *, save_id: str | None = None, character_id: str | None = None) -> None:
        scope = character_scope(save_id, character_id)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db:
            self._db.executemany("INSERT INTO messages(conversation_id,role,content,created_at,save_id,character_id) VALUES (?,?,?,?,?,?)", [(conversation_id,"user",message,now,*scope),(conversation_id,"assistant",reply,now,*scope)])

    def add_memory(self, content: str, *, save_id: str | None = None, character_id: str | None = None) -> dict:
        scope = character_scope(save_id, character_id)
        memory = {"id": str(uuid4()), "content": content, "source": "user_explicit", "created_at": datetime.now(timezone.utc).isoformat()}
        with self._lock, self._db:
            self._db.execute("INSERT INTO memories(id,content,source,created_at,save_id,character_id) VALUES (:id,:content,:source,:created_at,:save_id,:character_id)", {**memory, "save_id": scope[0], "character_id": scope[1]})
        return memory

    def memories(self, limit: int = 30, *, save_id: str | None = None, character_id: str | None = None) -> list[dict]:
        scope = character_scope(save_id, character_id)
        with self._lock:
            rows = self._db.execute("SELECT id,content,source,created_at FROM memories WHERE save_id=? AND character_id=? ORDER BY created_at DESC LIMIT ?", (*scope, limit)).fetchall()
        return [dict(zip(("id","content","source","created_at"),row)) for row in reversed(rows)]

    def delete_memory(self, memory_id: str, *, save_id: str | None = None, character_id: str | None = None) -> bool:
        scope = character_scope(save_id, character_id)
        with self._lock, self._db:
            return self._db.execute("DELETE FROM memories WHERE id=? AND save_id=? AND character_id=?", (memory_id, *scope)).rowcount == 1

    def legacy_archive_counts(self) -> dict:
        with self._lock:
            return {table: self._db.execute(f"SELECT COUNT(*) FROM {table} WHERE save_id=?", (ARCHIVE_SAVE_ID,)).fetchone()[0] for table in ("messages", "memories")}

    def legacy_archive(self) -> dict:
        """Bounded read-only preview of unassigned, pre-character Eckera records.

        Never copies archive text into active scope. Text clipping is explicit;
        original rows and the migration backup remain untouched.
        """
        result = {"messages": [], "memories": [], "readOnly": True, "counts": {}, "truncated": {}}
        columns = {
            "messages": ("id", "conversation_id", "role", "content", "created_at", "content_truncated"),
            "memories": ("id", "content", "source", "created_at", "content_truncated"),
        }
        queries = {
            "messages": "SELECT id,substr(conversation_id,1,128),role,substr(content,1,12000),substr(created_at,1,64),length(content)>12000 FROM messages WHERE save_id=? AND character_id=? ORDER BY id DESC LIMIT 500",
            "memories": "SELECT substr(id,1,64),substr(content,1,2000),substr(source,1,64),substr(created_at,1,64),length(content)>2000 FROM memories WHERE save_id=? AND character_id=? ORDER BY created_at DESC,id DESC LIMIT 200",
        }
        with self._lock:
            for table, query in queries.items():
                args = (ARCHIVE_SAVE_ID, DEFAULT_CHARACTER_ID)
                count = self._db.execute(f"SELECT COUNT(*) FROM {table} WHERE save_id=? AND character_id=?", args).fetchone()[0]
                result["counts"][table] = count
                remaining = 1_000_000
                clipped = False
                entries = []
                for row in self._db.execute(query, args):
                    entry = dict(zip(columns[table], row))
                    entry["content_truncated"] = bool(entry["content_truncated"])
                    size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) + 1
                    if size > remaining:
                        break
                    remaining -= size
                    clipped = clipped or entry["content_truncated"]
                    entries.append(entry)
                result[table] = list(reversed(entries))
                result["truncated"][table] = clipped or len(entries) < count
        return result

    def assign_legacy_archive(self, verified_save_id: str) -> dict:
        """Explicit verified single-save mapping only; never called automatically.

        Moves, rather than duplicates, unassigned Eckera records. The original database
        backup remains available. Repeating the assignment moves zero records.
        """
        scope = character_scope(verified_save_id, DEFAULT_CHARACTER_ID)
        if scope[0] == ARCHIVE_SAVE_ID:
            raise ValueError("Choose a verified game save")
        with self._lock, self._db:
            return {table: self._db.execute(f"UPDATE {table} SET save_id=? WHERE save_id=? AND character_id=?", (scope[0], ARCHIVE_SAVE_ID, DEFAULT_CHARACTER_ID)).rowcount for table in ("messages", "memories")}

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
