"""Single writer for source streams, receipts, low-level changes and coverage.

Transport liveness uses monotonic time, independently from producer capture time.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


EVENT_PAGE_BYTE_BUDGET = 512 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":path.chmod(0o700)


def _json(value) -> str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z","+00:00"))


class ObservationConflict(ValueError):
    pass


class ObservationStore:
    def __init__(self,path: Path,stale_seconds: int = 300, *, runtime_stale_seconds: float = 10,runtime_disconnect_seconds: float = 30,clock=None,monotonic=None):
        private_directory(path.parent)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path,check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS observations (seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,received_at TEXT NOT NULL,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_streams (
            stream_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,adapter_id TEXT NOT NULL,game_build TEXT,session_id TEXT,synthetic INTEGER NOT NULL,
            last_seen_at TEXT NOT NULL,connection_state TEXT NOT NULL,latest_capture_at TEXT NOT NULL,
            latest_envelope TEXT NOT NULL,latest_snapshot TEXT,latest_payload_hash TEXT,last_content_seq INTEGER,
            captures INTEGER NOT NULL DEFAULT 0,unchanged_captures INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS observation_receipts (
            event_id TEXT PRIMARY KEY,stream_id TEXT NOT NULL,received_at TEXT NOT NULL,captured_at TEXT NOT NULL,
            envelope_digest TEXT NOT NULL,observation_seq INTEGER,metadata TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS receipts_stream_capture ON observation_receipts(stream_id,captured_at);
        CREATE TABLE IF NOT EXISTS change_events (
            cursor INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,stream_id TEXT,kind TEXT NOT NULL,
            source_event_id TEXT,synthetic INTEGER NOT NULL,details TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS interface_catalogs (catalog_id TEXT PRIMARY KEY,metadata TEXT NOT NULL,complete INTEGER NOT NULL DEFAULT 0,registered_count INTEGER NOT NULL DEFAULT 0,coverage TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS registered_interfaces (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,catalog_id TEXT NOT NULL,interface_id TEXT NOT NULL,record TEXT NOT NULL,access_status TEXT NOT NULL,
            UNIQUE(catalog_id,interface_id)
        );
        CREATE INDEX IF NOT EXISTS interfaces_catalog_cursor ON registered_interfaces(catalog_id,seq);
        CREATE INDEX IF NOT EXISTS interfaces_status_cursor ON registered_interfaces(catalog_id,access_status,seq);
        """)
        self.stale_seconds = stale_seconds
        self.runtime_stale_seconds = runtime_stale_seconds
        self.runtime_disconnect_seconds = runtime_disconnect_seconds
        if not 0 < runtime_stale_seconds < runtime_disconnect_seconds:
            raise ValueError("Runtime stale threshold must be positive and less than disconnect threshold")
        self._clock = clock or (lambda:datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._seen_ticks: dict[str,float] = {}
        # Existing capture timestamps are history, never proof of a live connection
        # after a backend restart. Rehydrate old observations once without events.
        with self._db:
            restarting = self._db.execute("SELECT * FROM source_streams WHERE source_kind='runtime' AND connection_state!='disconnected'").fetchall()
            self._db.execute("UPDATE source_streams SET connection_state='disconnected' WHERE source_kind='runtime'")
            for stream in restarting:self._emit("source_disconnected",stream["stream_id"],None,stream["synthetic"],{"reason":"backend_restart","last_seen_at":stream["last_seen_at"]})
            if self._db.execute("SELECT COUNT(*) FROM source_streams").fetchone()[0] == 0:
                for row in self._db.execute("SELECT seq,received_at,body FROM observations ORDER BY seq").fetchall():
                    self._ingest(json.loads(row["body"]),row["received_at"],historical=True,existing_seq=row["seq"])
        if os.name != "nt":path.chmod(0o600)

    def close(self):
        with self._lock:self._db.close()

    @staticmethod
    def stream_id(body: dict) -> str:
        return _digest([body["source"]["kind"],body["source"]["adapter_id"],body["game"].get("session_id"),body["game"].get("build"),body["synthetic"]])

    def _emit(self,kind,stream_id,source_event_id,synthetic,details):
        self._db.execute("INSERT INTO change_events(created_at,stream_id,kind,source_event_id,synthetic,details) VALUES (?,?,?,?,?,?)",(self._clock().isoformat(),stream_id,kind,source_event_id,int(synthetic),_json(details)))

    def _touch(self,stream_id: str,now: str, *, disconnected=False,detail=""):
        row = self._db.execute("SELECT * FROM source_streams WHERE stream_id=?",(stream_id,)).fetchone()
        if row is None:raise KeyError("Unknown source stream")
        if row["source_kind"] != "runtime":return
        next_state = "disconnected" if disconnected else "connected"
        if disconnected:self._seen_ticks.pop(stream_id,None)
        else:self._seen_ticks[stream_id] = self._monotonic()
        self._db.execute("UPDATE source_streams SET last_seen_at=?,connection_state=? WHERE stream_id=?",(now,next_state,stream_id))
        if row["connection_state"] != next_state:
            self._emit("source_"+next_state,stream_id,None,row["synthetic"],{"previous_state":row["connection_state"],"last_seen_at":now,"reason":detail or "capture_received"})

    def _refresh(self):
        tick = self._monotonic()
        rows = self._db.execute("SELECT * FROM source_streams WHERE source_kind='runtime'").fetchall()
        for row in rows:
            seen = self._seen_ticks.get(row["stream_id"])
            elapsed = None if seen is None else max(0,tick-seen)
            state = "disconnected" if elapsed is None or elapsed>=self.runtime_disconnect_seconds else "stale" if elapsed>=self.runtime_stale_seconds else "connected"
            if state != row["connection_state"]:
                self._db.execute("UPDATE source_streams SET connection_state=? WHERE stream_id=?",(state,row["stream_id"]))
                self._emit("source_"+state,row["stream_id"],None,row["synthetic"],{"previous_state":row["connection_state"],"last_seen_at":row["last_seen_at"],"elapsed_seconds":elapsed,"reason":"heartbeat_timeout"})

    @staticmethod
    def _payload_hash(body):
        payload = dict(body["payload"])
        if "facts" in payload:payload["facts"] = sorted(payload["facts"],key=_json)
        return _digest(payload)

    @staticmethod
    def _raw_facts(body):
        if body is None:return []
        return sorted([{key:fact[key] for key in ("entity_kind","entity_id","field","value","unit") if key in fact} for fact in body["payload"].get("facts",[])],key=_json)

    def _changes(self,previous,current):
        before,after = self._raw_facts(previous),self._raw_facts(current)
        if before == after:return
        # Diff raw observations only. Positions/paths do not establish a football
        # entity, and a changed label is never promoted to a goal/transfer event.
        old = Counter(_json(fact) for fact in before)
        new = Counter(_json(fact) for fact in after)
        removed = [json.loads(key) for key in sorted((old-new).elements())]
        added = [json.loads(key) for key in sorted((new-old).elements())]
        ui = any(fact["entity_kind"] in ("ui_element","ui_text") and fact["field"] in ("text","visible_text","screen_text","ui_tree_text","raw_ui_text") for fact in removed+added)
        self._emit("ui_text_changed" if ui else "raw_fields_changed",self.stream_id(current),current["event_id"],current["synthetic"],{"semantic_level":"raw_observation","added":added[:30],"removed":removed[:30],"added_count":len(added),"removed_count":len(removed),"truncated":len(added)>30 or len(removed)>30,"identity_scope":"source_session_snapshot_paths_only"})

    def _ingest(self,body,now, *, historical=False,existing_seq=None):
        stream_id = self.stream_id(body)
        digest = _digest(body)
        receipt = self._db.execute("SELECT * FROM observation_receipts WHERE event_id=?",(body["event_id"],)).fetchone()
        if receipt:
            if receipt["envelope_digest"] != digest:raise ObservationConflict("Event ID already belongs to a different observation")
            if not historical:self._touch(stream_id,now)
            return {"stream_id":stream_id,"duplicate":True,"content_unchanged":True,"ignored_out_of_order":False}
        row = self._db.execute("SELECT * FROM source_streams WHERE stream_id=?",(stream_id,)).fetchone()
        payload_hash = self._payload_hash(body)
        unchanged = bool(row and row["latest_payload_hash"] == payload_hash)
        older = bool(row and _date(body["captured_at"]) < _date(row["latest_capture_at"]))
        content_seq = row["last_content_seq"] if unchanged else existing_seq
        if not unchanged and content_seq is None:
            cursor = self._db.execute("INSERT INTO observations(event_id,received_at,body) VALUES (?,?,?)",(body["event_id"],now,_json(body)))
            content_seq = cursor.lastrowid
        metadata = {key:value for key,value in body.items() if key!="payload"}
        self._db.execute("INSERT INTO observation_receipts VALUES (?,?,?,?,?,?,?)",(body["event_id"],stream_id,now,body["captured_at"],digest,content_seq,_json(metadata)))
        is_snapshot = body["payload"]["kind"] == "fact_snapshot"
        if row is None:
            state = "disconnected" if body["source"]["kind"]=="runtime" else "snapshot"
            self._db.execute("INSERT INTO source_streams VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(stream_id,body["source"]["kind"],body["source"]["adapter_id"],body["game"]["build"],body["game"]["session_id"],int(body["synthetic"]),now,state,body["captured_at"],_json(body),_json(body) if is_snapshot else None,payload_hash,content_seq,1,0))
        else:
            self._db.execute("UPDATE source_streams SET last_seen_at=?,captures=captures+1,unchanged_captures=unchanged_captures+? WHERE stream_id=?",(now,int(unchanged),stream_id))
            if not older:
                self._db.execute("UPDATE source_streams SET latest_capture_at=?,latest_envelope=?,latest_payload_hash=?,last_content_seq=?,latest_snapshot=COALESCE(?,latest_snapshot) WHERE stream_id=?",(body["captured_at"],_json(body),payload_hash,content_seq,_json(body) if is_snapshot else None,stream_id))
        if not historical:
            self._touch(stream_id,now)
            if not older:
                previous = json.loads(row["latest_snapshot"]) if row and row["latest_snapshot"] else None
                if is_snapshot:
                    if previous is None:self._emit("snapshot_received",stream_id,body["event_id"],body["synthetic"],{"facts_count":len(body["payload"]["facts"]),"semantic_level":"raw_observation"})
                    else:self._changes(previous,body)
                elif not unchanged:self._emit("capabilities_changed",stream_id,body["event_id"],body["synthetic"],body["payload"])
        return {"stream_id":stream_id,"duplicate":False,"content_unchanged":unchanged,"ignored_out_of_order":older}

    def ingest(self,body):
        with self._lock,self._db:
            self._refresh()
            return self._ingest(body,self._clock().isoformat())

    def insert(self,body) -> bool:
        return not self.ingest(body)["duplicate"]

    def heartbeat(self,stream_id,state,detail=""):
        with self._lock,self._db:
            self._refresh()
            self._touch(stream_id,self._clock().isoformat(),disconnected=state=="disconnected",detail=detail or "explicit_heartbeat")
            return self._stream_status(self._db.execute("SELECT * FROM source_streams WHERE stream_id=?",(stream_id,)).fetchone())

    def _stream_status(self,row):
        latest = json.loads(row["latest_envelope"])
        snapshot = json.loads(row["latest_snapshot"]) if row["latest_snapshot"] else None
        body = snapshot or latest
        observed_age = None if body["observed_at"] is None else (self._clock()-_date(body["observed_at"])).total_seconds()
        capture_age = (self._clock()-_date(body["captured_at"])).total_seconds()
        threshold = self.runtime_stale_seconds if row["source_kind"]=="runtime" else self.stale_seconds
        fresh = observed_age is not None and -60<=observed_age<=threshold and -60<=capture_age<=threshold
        if row["source_kind"]=="runtime" and row["connection_state"]!="connected":fresh=False
        data_state = "unavailable" if latest["status"] not in ("available","partial") else "unknown" if observed_age is None else "fresh" if fresh else "stale"
        availability = "synthetic" if row["synthetic"] else "available" if data_state=="fresh" else "unavailable" if data_state=="unavailable" else "stale"
        seen_tick = self._seen_ticks.get(row["stream_id"])
        return {"stream_id":row["stream_id"],"availability":availability,"source":row["source_kind"],"last_captured_at":body["captured_at"],"observed_at":body["observed_at"],"last_seen_at":row["last_seen_at"],"connection_state":row["connection_state"],"last_seen_age_seconds":None if seen_tick is None else max(0,self._monotonic()-seen_tick),"capture_age_seconds":capture_age,"observation_age_seconds":observed_age,"data_freshness":data_state,"synthetic":bool(row["synthetic"]),"game":body["game"],"facts_count":len(body["payload"].get("facts",[])),"event_id":body["event_id"],"last_message_event_id":latest["event_id"],"source_freshness":body["source"]["freshness"],"adapter_id":row["adapter_id"],"captures":row["captures"],"unchanged_captures":row["unchanged_captures"]}

    def _selected(self):
        rows = self._db.execute("SELECT * FROM source_streams").fetchall()
        if not rows:return None,"no_data"
        def priority(row):
            active = row["source_kind"]=="runtime" and row["connection_state"] in ("connected","stale")
            snapshot = json.loads(row["latest_snapshot"]) if row["latest_snapshot"] else None
            usable_save = row["source_kind"]=="save" and snapshot is not None and snapshot["status"] in ("available","partial")
            return (not bool(row["synthetic"]),4 if active else 3 if usable_save else 2 if snapshot else 1,row["last_seen_at"] if active else row["latest_capture_at"])
        row = max(rows,key=priority)
        reason = "synthetic_only" if row["synthetic"] else "runtime_active" if row["source_kind"]=="runtime" and row["connection_state"] in ("connected","stale") else "save_fallback" if row["source_kind"]=="save" else "runtime_offline"
        return row,reason

    def latest(self):
        with self._lock,self._db:
            self._refresh()
            row,_ = self._selected()
            return json.loads(row["latest_snapshot"] or row["latest_envelope"]) if row else None

    def reader_snapshot(self,after=0,limit=100,*,event_id=None):
        """Page the selected source without merging saves, sessions or diagnostics."""
        with self._lock,self._db:
            self._refresh()
            row,reason = self._selected()
            body = json.loads(row["latest_snapshot"] or row["latest_envelope"]) if row else None
            if event_id is not None and (body is None or body["event_id"] != event_id):
                raise ObservationConflict("Snapshot changed")
            facts = body["payload"].get("facts",[]) if body else []
            items = facts[after:after+limit]
            cursor = after+len(items)
            metadata = {key:value for key,value in body.items() if key!="payload"} if body else None
            payload_metadata = {key:value for key,value in body["payload"].items() if key!="facts"} if body else None
            raw_ui = any(fact["entity_kind"] in ("ui_element","ui_text") for fact in facts)
            return {"reader_api":1,"source_status":{**self._stream_status(row),"selection_reason":reason} if row else self.source_status(),
                    "observation":metadata,"payload_metadata":payload_metadata,"facts":items,
                    "snapshot_event_id":body["event_id"] if body else None,
                    "facts_total":len(facts),"next_cursor":cursor,"has_more":cursor<len(facts),
                    "partial":body is None or body["payload"]["kind"]!="fact_snapshot" or body["status"]!="available" or raw_ui,
                    "semantic_scope":"raw_ui_observation" if raw_ui else "adapter_observation",
                    "limitations":["UI text may contain hidden or cached elements; positions do not establish football entity identity."] if raw_ui else [],
                    "native_records":{"state":"awaiting_decoded_native_records","payload_decoded":False,"field_values_known":False}}

    def source_status(self):
        with self._lock,self._db:
            self._refresh()
            row,reason = self._selected()
            if row is None:return {"availability":"not_connected","source":None,"last_captured_at":None,"observed_at":None,"synthetic":None,"game":None,"facts_count":0,"event_id":None,"connection_state":"not_connected","last_seen_at":None,"selection_reason":reason}
            return {**self._stream_status(row),"selection_reason":reason}

    def context(self):
        with self._lock,self._db:
            self._refresh()
            row,reason = self._selected()
            if row is None:return {"source_status":self.source_status(),"facts":[]}
            body = json.loads(row["latest_snapshot"] or row["latest_envelope"])
            return {"source_status":{**self._stream_status(row),"selection_reason":reason},"facts":body["payload"].get("facts",[])}

    @staticmethod
    def _event_item(row):
        return {"cursor":row["cursor"],"created_at":row["created_at"],"stream_id":row["stream_id"],"kind":row["kind"],"source_event_id":row["source_event_id"],"synthetic":bool(row["synthetic"]),"details":json.loads(row["details"]),"details_truncated":False}

    @staticmethod
    def _summary_event(item):
        details=item["details"]
        reference=f"/v1/events/{item['cursor']}"
        summary={"summary_only":True,"reason":"event_exceeds_response_byte_budget","original_event_ref":reference,"original_details_bytes":len(_json(details).encode("utf-8")),"original_details_sha256":_digest(details)}
        for key in ("semantic_level","added_count","removed_count","facts_count","identity_scope"):
            value=details.get(key) if isinstance(details,dict) else None
            if isinstance(value,(int,bool)) or isinstance(value,str) and len(value)<=128:summary[key]=value
        return {**item,"details":summary,"details_truncated":True,"original_event_ref":reference}

    def event_detail(self,cursor):
        with self._lock:
            row=self._db.execute("SELECT * FROM change_events WHERE cursor=?",(cursor,)).fetchone()
            return self._event_item(row) if row else None

    def events(self,after=0,limit=100,*,byte_budget=EVENT_PAGE_BYTE_BUDGET):
        # The byte limit includes the final envelope and UTF-8 expansion. A single
        # over-budget event becomes an explicit summary, retaining its full DB row.
        budget=max(2048,min(EVENT_PAGE_BYTE_BUDGET,byte_budget))
        with self._lock,self._db:
            self._refresh()
            latest=self._db.execute("SELECT COALESCE(MAX(cursor),0) FROM change_events").fetchone()[0]
            def page(items):
                cursor=items[-1]["cursor"] if items else after
                return {"events":items,"next_cursor":cursor,"latest_cursor":latest,"has_more":cursor<latest,"cursor_reset_required":after>latest,"response_byte_budget":budget}
            items=[]
            rows=self._db.execute("SELECT * FROM change_events WHERE cursor>? ORDER BY cursor LIMIT ?",(after,limit))
            for row in rows:
                item=self._event_item(row)
                candidate=page(items+[item])
                if len(_json(candidate).encode("utf-8"))<=budget:
                    items.append(item)
                    continue
                if items:break
                item=self._summary_event(item)
                candidate=page([item])
                if len(_json(candidate).encode("utf-8"))>budget:
                    raise ValueError("Event metadata exceeds the bounded polling protocol")
                items.append(item)
                break
            return page(items)

    def fields(self,stream_id=None):
        with self._lock,self._db:
            self._refresh()
            row = self._db.execute("SELECT * FROM source_streams WHERE stream_id=?",(stream_id,)).fetchone() if stream_id else self._selected()[0]
            if row is None:return {"stream_id":stream_id,"fields":[]}
            body = json.loads(row["latest_snapshot"] or row["latest_envelope"])
            return {"stream_id":row["stream_id"],"source_status":self._stream_status(row),"fields":[{**fact,"source":body["source"],"game":body["game"],"source_event_id":body["event_id"],"captured_at":body["captured_at"],"readability":"value_observed" if fact["value"] is not None else "null_observed"} for fact in body["payload"].get("facts",[])]}

    def register_catalog(self,body):
        catalog_id = body["catalog_id"]
        metadata = {key:value for key,value in body.items() if key not in ("records","complete")}
        with self._lock,self._db:
            previous = self._db.execute("SELECT * FROM interface_catalogs WHERE catalog_id=?",(catalog_id,)).fetchone()
            if previous:
                previous_meta = json.loads(previous["metadata"])
                for key in ("metadata_sha256","metadata_version","game_build","catalog_version","synthetic","total_expected","inventory_kind","native_module","native_module_sha256"):
                    if previous_meta.get(key,"managed_metadata" if key=="inventory_kind" else None)!=metadata.get(key,"managed_metadata" if key=="inventory_kind" else None):raise ObservationConflict("Catalog identity conflicts with registered metadata")
            count = previous["registered_count"] if previous else 0
            counts = json.loads(previous["coverage"]) if previous else {}
            ids = [record["interface_id"] for record in body["records"]]
            old_records = {}
            if ids:
                placeholders = ",".join("?" for _ in ids)
                old_records = {row["interface_id"]:json.loads(row["record"]) for row in self._db.execute(f"SELECT interface_id,record FROM registered_interfaces WHERE catalog_id=? AND interface_id IN ({placeholders})",(catalog_id,*ids)).fetchall()}
            self._db.execute("INSERT INTO interface_catalogs(catalog_id,metadata) VALUES (?,?) ON CONFLICT(catalog_id) DO UPDATE SET metadata=excluded.metadata",(catalog_id,_json(metadata)))
            for incoming in body["records"]:
                record = dict(incoming)
                old = old_records.get(record["interface_id"])
                # Re-registering a static inventory does not erase a measured probe.
                if old and record["access_status"]=="not_probed" and old["access_status"]!="not_probed":
                    for key in ("access_status","reason","verification","last_verified_at","verification_session_id","side_effect_policy","field_paths"):
                        if key in old:record[key]=old[key]
                if record["access_status"]=="verified_readable" and incoming["access_status"]=="verified_readable":record["verification_session_id"]=body["session_id"]
                if old:counts[old["access_status"]]=max(0,counts.get(old["access_status"],0)-1)
                else:count+=1
                counts[record["access_status"]]=counts.get(record["access_status"],0)+1
                self._db.execute("INSERT INTO registered_interfaces(catalog_id,interface_id,record,access_status) VALUES (?,?,?,?) ON CONFLICT(catalog_id,interface_id) DO UPDATE SET record=excluded.record,access_status=excluded.access_status",(catalog_id,record["interface_id"],_json(record),record["access_status"]))
            if count>body["total_expected"]:raise ObservationConflict("Registered inventory exceeds total_expected")
            complete = bool(previous and previous["complete"]) or bool(body["complete"] and count==body["total_expected"])
            if body["complete"] and count!=body["total_expected"]:raise ObservationConflict("Catalog is incomplete: unique count does not equal total_expected")
            self._db.execute("UPDATE interface_catalogs SET complete=?,registered_count=?,coverage=? WHERE catalog_id=?",(int(complete),count,_json(counts),catalog_id))
            if complete and not (previous and previous["complete"]):self._emit("interface_catalog_registered",None,None,body["synthetic"],{"catalog_id":catalog_id,"registered_count":count,"semantic_level":"metadata_inventory","runtime_readability_implied":False})
            return {"accepted":True,"catalog_id":catalog_id,"registered_count":count,"total_expected":body["total_expected"],"complete":complete}

    def catalogs(self):
        with self._lock:
            result=[]
            for row in self._db.execute("SELECT * FROM interface_catalogs ORDER BY catalog_id").fetchall():
                counts=json.loads(row["coverage"])
                metadata=json.loads(row["metadata"])
                result.append({**metadata,"inventory_kind":metadata.get("inventory_kind","managed_metadata"),"native_module":metadata.get("native_module"),"native_module_sha256":metadata.get("native_module_sha256"),"complete":bool(row["complete"]),"inventory_complete":bool(row["complete"]),"registered_count":row["registered_count"],"coverage":counts,"runtime_verified_coverage":{"verified_readable":counts.get("verified_readable",0),"scope":"last_explicit_probe_only","continuous_monitoring_implied":False}})
            return {"catalogs":result}

    def interfaces(self,catalog_id,after=0,limit=100,access_status=None):
        with self._lock:
            sql="SELECT seq,record FROM registered_interfaces WHERE catalog_id=? AND seq>?"
            params=[catalog_id,after]
            if access_status:
                sql+=" AND access_status=?"
                params.append(access_status)
            rows=self._db.execute(sql+" ORDER BY seq LIMIT ?",(*params,limit)).fetchall()
            return {"catalog_id":catalog_id,"interfaces":[{"cursor":row["seq"],**json.loads(row["record"])} for row in rows],"next_cursor":rows[-1]["seq"] if rows else after}

    def monitoring(self,registry_summary=None,native_observer_summary=None):
        with self._lock,self._db:
            self._refresh()
            rows=self._db.execute("SELECT * FROM source_streams ORDER BY last_seen_at DESC").fetchall()
            catalogs=self.catalogs()["catalogs"]
            result={"source_status":self.source_status(),"streams":[self._stream_status(row) for row in rows[:100]],"streams_total":len(rows),"streams_truncated":len(rows)>100,"coverage":{"catalogs":catalogs[:20],"catalogs_total":len(catalogs),"catalogs_truncated":len(catalogs)>20},"recent_changes":[],"latest_event_cursor":self._db.execute("SELECT COALESCE(MAX(cursor),0) FROM change_events").fetchone()[0],"automatic_model_calls":False,"runtime_stale_after_seconds":self.runtime_stale_seconds,"runtime_disconnect_after_seconds":self.runtime_disconnect_seconds,"response_byte_budget":EVENT_PAGE_BYTE_BUDGET}
            if registry_summary is not None:result["registry_summary"]=registry_summary
            if native_observer_summary is not None:result["native_observer_summary"]=native_observer_summary
            # Leave room for the event-page envelope even with long source labels.
            while len(_json(result).encode("utf-8"))>EVENT_PAGE_BYTE_BUDGET-4096:
                if result["streams"]:
                    result["streams"].pop()
                    result["streams_truncated"]=True
                elif result["coverage"]["catalogs"]:
                    result["coverage"]["catalogs"].pop()
                    result["coverage"]["catalogs_truncated"]=True
                else:raise ValueError("Monitoring source metadata exceeds polling budget")
            recent=self._db.execute("SELECT cursor FROM change_events ORDER BY cursor DESC LIMIT 10").fetchall()
            after=recent[-1][0]-1 if recent else 0
            result["recent_changes_after"]=after
            result["recent_changes_ref"]=f"/v1/events?after={after}&limit=10"
            available=EVENT_PAGE_BYTE_BUDGET-len(_json(result).encode("utf-8"))-128
            event_page=self.events(after,10,byte_budget=available)
            result["recent_changes"]=event_page["events"]
            result["recent_changes_next_cursor"]=event_page["next_cursor"]
            result["recent_changes_has_more"]=event_page["has_more"]
            # This is the actual final serialized response budget, not a count or
            # Python-character approximation. Dedicated event polling retains all.
            while len(_json(result).encode("utf-8"))>EVENT_PAGE_BYTE_BUDGET:
                result["recent_changes"].pop()
                result["recent_changes_has_more"]=True
                result["recent_changes_next_cursor"]=result["recent_changes"][-1]["cursor"] if result["recent_changes"] else after
            return result
