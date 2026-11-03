import sqlite3
from contextlib import closing
import pytest
from football_assistant_agent.storage import CompanionStore, ARCHIVE_SAVE_ID


def test_character_and_save_isolation(tmp_path):
    store = CompanionStore(tmp_path / 'memory.db')
    a = dict(save_id='save-a', character_id='official.eckera')
    b = dict(save_id='save-a', character_id='custom.other')
    c = dict(save_id='save-b', character_id='official.eckera')
    store.append_turn('chat', 'hello', 'world', **a)
    memory = store.add_memory('private', **a)
    assert len(store.recent_messages('chat', **a)) == 2
    assert store.memories(**a)[0]['content'] == 'private'
    for scope in (b, c, {}):
        assert store.recent_messages('chat', **scope) == []
        assert store.memories(**scope) == []
        assert not store.delete_memory(memory['id'], **scope)
    assert store.delete_memory(memory['id'], **a)
    with pytest.raises(ValueError):
        store.memories(save_id='save-a')
    store.close()


def test_legacy_migration_backup_archive_idempotence(tmp_path):
    path = tmp_path / 'memory.db'
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO messages VALUES (1,'old','user','old hello','2020');
        INSERT INTO memories VALUES ('old','old memory','user_explicit','2020');
        """)
    store = CompanionStore(path)
    assert store.recent_messages('old')[0]['content'] == 'old hello'
    assert store.memories()[0]['content'] == 'old memory'
    assert store.memories(save_id='new-save', character_id='official.eckera') == []
    assert store.memories(save_id=ARCHIVE_SAVE_ID, character_id='official.eckera')[0]['id'] == 'old'
    store.close()
    backup = path.with_name('memory.db.pre-character-v1.bak')
    before = backup.read_bytes()
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('SELECT content FROM memories').fetchone()[0] == 'old memory'
    store = CompanionStore(path)
    assert len(store.memories()) == 1
    assert backup.read_bytes() == before
    store.close()


def test_archive_assignment_is_explicit_move_and_idempotent(tmp_path):
    store = CompanionStore(tmp_path / 'memory.db')
    store.add_memory('old')
    store.append_turn('old', 'question', 'answer')
    assert store.legacy_archive_counts() == {'messages': 2, 'memories': 1}
    assert store.assign_legacy_archive('verified') == {'messages': 2, 'memories': 1}
    assert store.legacy_archive_counts() == {'messages': 0, 'memories': 0}
    assert store.assign_legacy_archive('other') == {'messages': 0, 'memories': 0}
    assert len(store.memories(save_id='verified', character_id='official.eckera')) == 1
    assert store.memories(save_id='other', character_id='official.eckera') == []
    store.close()


def test_migration_closes_all_auxiliary_sqlite_handles_before_return(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE messages (id INTEGER PRIMARY KEY,conversation_id TEXT,role TEXT,content TEXT,created_at TEXT); CREATE TABLE memories (id TEXT PRIMARY KEY,content TEXT,source TEXT,created_at TEXT);")
    original_connect = sqlite3.connect
    connections = []

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            super().close()
            self.closed = True

    def connect(*args, **kwargs):
        kwargs['factory'] = TrackedConnection
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', connect)
    store = CompanionStore(path)
    assert len(connections) >= 2
    assert all(connection.closed for connection in connections if connection is not store._db)
    assert not list(tmp_path.glob('*.tmp'))
    store.close()
    assert all(connection.closed for connection in connections)

    # Exercise validation of an existing completed backup on an unmigrated source.
    backup = path.with_name(path.name + '.pre-character-v1.bak')
    path.unlink()
    path.write_bytes(backup.read_bytes())
    connections.clear()
    store = CompanionStore(path)
    assert len(connections) >= 2
    assert all(connection.closed for connection in connections if connection is not store._db)
    store.close()
