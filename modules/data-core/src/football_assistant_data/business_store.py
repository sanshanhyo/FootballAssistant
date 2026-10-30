"""Process-local native business channel; never projects UI or save observations.

Only a future in-process producer may open a session and publish validated records.
There is deliberately no HTTP ingestion endpoint or producer-verification override.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from .business_snapshot import BusinessSnapshot, assess_business_snapshot


class BusinessSessionConflict(ValueError):
    """A detached/replaced producer attempted to publish data."""


class BusinessSnapshotConflict(ValueError):
    """A publication would replace current data with a replay or older capture."""


class BusinessSnapshotStore:
    def __init__(self):
        self._lock = RLock()
        self._session_id = None
        self._session_token = None
        self._snapshot = None

    def start_session(self, session_id: str) -> str:
        """Invalidate previous records, including an ABA return to the same ID."""
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            raise ValueError('invalid session identity')
        with self._lock:
            self._session_id = session_id
            self._session_token = uuid4().hex
            self._snapshot = None
            return self._session_token

    def invalidate(self) -> None:
        with self._lock:
            self._session_id = self._session_token = self._snapshot = None

    def publish(self, payload: BusinessSnapshot | dict, *, session_token: str) -> None:
        # Revalidate even model instances and copy nested values: callers cannot
        # mutate the stored snapshot after publication or use model_construct.
        data = payload.model_dump(mode='python') if isinstance(payload, BusinessSnapshot) else payload
        snapshot = BusinessSnapshot.model_validate(data)
        with self._lock:
            if (self._session_token is None or session_token != self._session_token
                    or snapshot.source.session_id != self._session_id):
                raise BusinessSessionConflict('business session changed or is unavailable')
            previous = self._snapshot
            if previous is not None:
                if snapshot.snapshot_id == previous.snapshot_id:
                    if snapshot == previous:
                        return  # Exact retry never refreshes capture/observation time.
                    raise BusinessSnapshotConflict('snapshot identity was reused with different data')
                old, new = previous.source, snapshot.source
                if (new.captured_at < old.captured_at
                        or old.observed_at is not None and
                        (new.observed_at is None or new.observed_at < old.observed_at)
                        or new.captured_at == old.captured_at and new.observed_at == old.observed_at):
                    raise BusinessSnapshotConflict('business snapshot does not advance current capture')
            self._snapshot = snapshot.model_copy(deep=True)

    def read(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            snapshot = self._snapshot
            assessment = assess_business_snapshot(snapshot, now=now)
            if self._session_token is None:
                assessment['reasons'].append('no_active_business_session')
            # Do not expose obsolete values as current. The source metadata and
            # reasons still explain the missing snapshot without UI fallback.
            expired = any(reason in assessment['reasons'] for reason in
                          ('observation_time_unknown', 'observation_not_fresh', 'capture_not_fresh'))
            return {**assessment, 'snapshot': snapshot.model_dump(mode='json')
                    if snapshot is not None and not expired else None}

    def status(self, *, now: datetime | None = None) -> dict:
        result = self.read(now=now)
        result.pop('snapshot')
        return result
