"""Passive, pointer-free native-dispatch diagnostics. This module cannot install hooks."""
from __future__ import annotations

from datetime import timedelta
import json
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .registries import RegistrySource
from .storage import ObservationConflict, _date, _digest, _json

MAX_U64=18446744073709551615
ANCHOR="game_plugin__fm__gameplugin__i_plugin_data_receiver_send_data_response_set_func_ptr"
COUNTERS=("invocation_count","enqueued_count","drained_count","overflow_dropped","contention_dropped","stopped_invocations","in_flight","queue_size","queue_capacity")
CUMULATIVE=COUNTERS[:6]


def _u64(value: str) -> str:
    if int(value)>MAX_U64:raise ValueError("Unsigned 64-bit decimal value is out of range")
    return value


U64Text=Annotated[str,Field(strict=True,pattern=r"^(0|[1-9][0-9]{0,19})$"),AfterValidator(_u64)]


class DispatchTarget(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind: Literal["dispatch_thunk"]
    anchor_export: Literal[ANCHOR]
    anchor_offset_bytes: Literal[12]
    dispatch_rva: Literal["0x16c24"]


class NativeInstallReport(BaseModel):
    model_config=ConfigDict(extra="forbid")
    abi_version: Literal[1] | None=None
    struct_size: int | None=Field(default=None,strict=True,ge=0,le=4096)
    result: int | None=Field(default=None,strict=True,ge=-2147483648,le=2147483647)
    install_state: int | None=Field(default=None,strict=True,ge=0,le=4294967295)
    checks: int | None=Field(default=None,strict=True,ge=0,le=4294967295)
    prepare_result: int | None=Field(default=None,strict=True,ge=-2147483648,le=2147483647)
    commit_result: int | None=Field(default=None,strict=True,ge=-2147483648,le=2147483647)


class NativeHeaderRecord(BaseModel):
    model_config=ConfigDict(extra="forbid")
    call_sequence: U64Text
    native_thread_id: U64Text | None
    keys_count: U64Text | None
    payload_count: U64Text | None
    flags: int=Field(strict=True,ge=0,le=4294967295)
    age_seconds: float | None=Field(default=None,ge=0,allow_inf_nan=False)

    @model_validator(mode="after")
    def known_header_flags(self):
        if bool(self.flags & 1)!=(self.keys_count is not None):raise ValueError("Keys count known flag disagrees with nullable count")
        if bool(self.flags & 2)!=(self.payload_count is not None):raise ValueError("Payload count known flag disagrees with nullable count")
        if self.flags & 32 and self.native_thread_id is not None:raise ValueError("Unknown native thread ID must be null")
        return self


class NativeObserverReport(RegistrySource):
    game_plugin_sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    observer_sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    sample_id: str=Field(min_length=1,max_length=128)
    status: Literal["available","not_probed","unsupported","error"]
    reason: str=Field(default="",max_length=1024)
    abi_version: Literal[1]
    target: DispatchTarget
    installed: bool | None=Field(default=None,strict=True)
    capture_enabled: bool | None=Field(default=None,strict=True)
    install_state: int | None=Field(default=None,strict=True,ge=0,le=4294967295)
    invocation_count: U64Text | None=None
    enqueued_count: U64Text | None=None
    drained_count: U64Text | None=None
    overflow_dropped: U64Text | None=None
    contention_dropped: U64Text | None=None
    stopped_invocations: U64Text | None=None
    in_flight: U64Text | None=None
    queue_size: U64Text | None=None
    queue_capacity: U64Text | None=None
    records_total: U64Text | None=None
    latest_header_age_seconds: float | None=Field(default=None,ge=0,allow_inf_nan=False)
    records: list[NativeHeaderRecord]=Field(default_factory=list,max_length=16)
    install_report: NativeInstallReport | None=None
    completeness: Literal["bounded_header_observation_only"]="bounded_header_observation_only"
    payload_data_read: Literal[False]=False
    field_values_known: Literal[False]=False
    complete: Literal[False]=False

    @model_validator(mode="after")
    def bounded_projection(self):
        if len({record.call_sequence for record in self.records})!=len(self.records):raise ValueError("Duplicate native header sequence in a poll")
        if self.records_total is not None and int(self.records_total)<len(self.records):raise ValueError("Included records exceed the poll's actual header count")
        if self.latest_header_age_seconds is not None and self.records_total=="0":raise ValueError("An empty poll has no new native header timestamp")
        return self


class NativeObserverStore:
    def __init__(self,observations,registries):
        self._observations=observations
        self._db=observations._db
        self._lock=observations._lock
        self._clock=observations._clock
        self._monotonic=observations._monotonic
        self._page=registries._page
        self._seen_ticks={}
        with self._lock:
            self._db.executescript("""
            CREATE TABLE IF NOT EXISTS native_observers (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,observer_key TEXT UNIQUE NOT NULL,session_id TEXT NOT NULL,game_build TEXT NOT NULL,synthetic INTEGER NOT NULL,
                captured_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,snapshot_digest TEXT NOT NULL,state_digest TEXT NOT NULL,record TEXT NOT NULL,
                last_callback_at TEXT,last_callback_basis TEXT,callback_observed INTEGER
            );
            CREATE INDEX IF NOT EXISTS native_observer_sessions ON native_observers(session_id,game_build,synthetic,seq);
            CREATE TABLE IF NOT EXISTS native_observer_samples (
                observer_key TEXT NOT NULL,sample_id TEXT NOT NULL,captured_at TEXT NOT NULL,received_at TEXT NOT NULL,body_digest TEXT NOT NULL,
                PRIMARY KEY(observer_key,sample_id)
            );
            CREATE TABLE IF NOT EXISTS native_observer_history (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT,observer_key TEXT NOT NULL,created_at TEXT NOT NULL,record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS native_history_key ON native_observer_history(observer_key,cursor);
            """)

    @staticmethod
    def key(body):
        return _digest([{key:body.get(key) for key in (*RegistrySource.model_fields,"game_plugin_sha256","observer_sha256","abi_version") if key!="captured_at"},body["target"]])

    @staticmethod
    def _callback_evidence(body):
        invocation=body["invocation_count"]
        total=body["records_total"]
        if body["records"] or total is not None and int(total)>0 or invocation is not None and int(invocation)>0:return True
        return False if invocation=="0" and total=="0" else None

    @staticmethod
    def _gaps(body):
        values=[body[key] for key in ("overflow_dropped","contention_dropped","stopped_invocations")]
        if any(value is not None and int(value)>0 for value in values):return True
        return False if all(value=="0" for value in values) else None

    def _view(self,row):
        saved=json.loads(row["record"])
        body=saved["report"]
        total=body["records_total"]
        return {"cursor":row["seq"],"observer_key":row["observer_key"],"captured_at":row["captured_at"],"last_seen_at":row["last_seen_at"],"last_callback_at":row["last_callback_at"],"last_callback_basis":row["last_callback_basis"],"last_callback_scope":"last_observed_native_header_approximation","callback_observed":None if row["callback_observed"] is None else bool(row["callback_observed"]),"observed_callback_count":body["invocation_count"],"captured_header_count":body["enqueued_count"],"report":body,"records_included":len(body["records"]),"records_projection_complete":total is not None and int(total)==len(body["records"]),"records_truncated":total is not None and int(total)>len(body["records"]),"observation_gaps":self._gaps(body),"counter_regressions":saved.get("counter_regressions",[]),"counter_consistency":"approximate_concurrent_snapshot","count_units":{"keys_count":"uint64_elements","payload_count":"bytes"},"field_values_known":False,"payload_decoded":False,"original_callback_success_known":False,"setter_export_readability_inferred":False,"lossless_capture_claimed":False,"complete":False}

    def record(self,body):
        key=self.key(body)
        digest=_digest(body)
        now=self._clock().isoformat()
        with self._lock,self._db:
            duplicate=self._db.execute("SELECT body_digest FROM native_observer_samples WHERE observer_key=? AND sample_id=?",(key,body["sample_id"])).fetchone()
            previous=self._db.execute("SELECT * FROM native_observers WHERE observer_key=?",(key,)).fetchone()
            if duplicate:
                if duplicate["body_digest"]!=digest:raise ObservationConflict("Native sample ID was reused for different diagnostics")
                self._seen_ticks[key]=self._monotonic()
                self._db.execute("UPDATE native_observers SET last_seen_at=? WHERE observer_key=?",(now,key))
                row=self._db.execute("SELECT * FROM native_observers WHERE observer_key=?",(key,)).fetchone()
                return {"accepted":True,"duplicate":True,"changed":False,**self._view(row)}
            self._db.execute("INSERT INTO native_observer_samples VALUES (?,?,?,?,?)",(key,body["sample_id"],body["captured_at"],now,digest))
            self._seen_ticks[key]=self._monotonic()
            if previous and _date(body["captured_at"])<_date(previous["captured_at"]):
                self._db.execute("UPDATE native_observers SET last_seen_at=? WHERE observer_key=?",(now,key))
                row=self._db.execute("SELECT * FROM native_observers WHERE observer_key=?",(key,)).fetchone()
                return {"accepted":True,"duplicate":False,"changed":False,"ignored_out_of_order":True,**self._view(row)}
            callback_at=previous["last_callback_at"] if previous else None
            basis=previous["last_callback_basis"] if previous else None
            age=body["latest_header_age_seconds"]
            new_basis="source_capture_minus_native_header_age"
            if age is None:
                ages=[record["age_seconds"] for record in body["records"] if record["age_seconds"] is not None]
                age=min(ages) if ages else None
                new_basis="source_capture_minus_included_header_age"
            if age is not None:
                try:candidate=_date(body["captured_at"])-timedelta(seconds=age)
                except OverflowError:candidate=None
                if candidate is not None and (callback_at is None or candidate>=_date(callback_at)):
                    callback_at=candidate.isoformat()
                    basis=new_basis
            observed=self._callback_evidence(body)
            if previous and previous["callback_observed"]==1:observed=True
            old_report=json.loads(previous["record"])["report"] if previous else None
            regressions=[name for name in CUMULATIVE if old_report and body[name] is not None and old_report[name] is not None and int(body[name])<int(old_report[name])]
            snapshot={key:value for key,value in body.items() if key not in ("captured_at","sample_id","latest_header_age_seconds")}
            snapshot["records"]=[{key:value for key,value in record.items() if key!="age_seconds"} for record in body["records"]]
            snapshot_digest=_digest(snapshot)
            state={"status":body["status"],"installed":body["installed"],"capture_enabled":body["capture_enabled"],"install_state":body["install_state"],"callback_observed":observed,"observation_gaps":self._gaps(body),"counter_regressions":regressions,"reason":body["reason"]}
            state_digest=_digest(state)
            self._db.execute("INSERT INTO native_observers(observer_key,session_id,game_build,synthetic,captured_at,last_seen_at,snapshot_digest,state_digest,record,last_callback_at,last_callback_basis,callback_observed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(observer_key) DO UPDATE SET captured_at=excluded.captured_at,last_seen_at=excluded.last_seen_at,snapshot_digest=excluded.snapshot_digest,state_digest=excluded.state_digest,record=excluded.record,last_callback_at=excluded.last_callback_at,last_callback_basis=excluded.last_callback_basis,callback_observed=excluded.callback_observed",(key,body["session_id"],body["game_build"],int(body["synthetic"]),body["captured_at"],now,snapshot_digest,state_digest,_json({"report":body,"counter_regressions":regressions}),callback_at,basis,None if observed is None else int(observed)))
            row=self._db.execute("SELECT * FROM native_observers WHERE observer_key=?",(key,)).fetchone()
            view=self._view(row)
            changed=previous is None or previous["snapshot_digest"]!=snapshot_digest or previous["state_digest"]!=state_digest
            if changed:self._db.execute("INSERT INTO native_observer_history(observer_key,created_at,record) VALUES (?,?,?)",(key,now,_json(view)))
            if previous is None or previous["state_digest"]!=state_digest:
                self._observations._emit("native_observer_state_changed",None,None,body["synthetic"],{"semantic_level":"native_dispatch_header_diagnostic","observer_key":key,"session_id":body["session_id"],"target_kind":"dispatch_thunk","anchor_offset_bytes":12,**{name:value for name,value in state.items() if name!="reason"},"field_values_known":False,"payload_decoded":False})
            return {"accepted":True,"duplicate":False,"changed":changed,**view}

    def latest(self,after=0,limit=20,session_id=None):
        with self._lock:
            sql="SELECT * FROM native_observers WHERE seq>?"
            params=[after]
            if session_id:sql+=" AND session_id=?";params.append(session_id)
            rows=self._db.execute(sql+" ORDER BY seq LIMIT ?",(*params,limit+1)).fetchall()
            result=self._page(rows[:limit],after,"native_observers",self._view)
            result["has_more"]=result["has_more"] or len(rows)>limit
            return result

    def history(self,observer_key,after=0,limit=20):
        with self._lock:
            rows=self._db.execute("SELECT * FROM native_observer_history WHERE observer_key=? AND cursor>? ORDER BY cursor LIMIT ?",(observer_key,after,limit+1)).fetchall()
            result=self._page(rows[:limit],after,"history",lambda row:{**json.loads(row["record"]),"cursor":row["cursor"],"recorded_at":row["created_at"]})
            result["has_more"]=result["has_more"] or len(rows)>limit
            return result

    def summary(self,session_id,game_build,synthetic,runtime_connection):
        empty={"has_report":False,"state":"unknown","active_session_id":session_id,"installed":None,"capture_enabled":None,"observed_callback_count":None,"captured_header_count":None,"callback_observed":None,"last_seen_at":None,"last_callback_at":None,"field_values_known":False,"payload_decoded":False,"complete":False,"runtime_connection_state":runtime_connection}
        if not session_id or synthetic is None:return empty
        with self._lock:
            row=self._db.execute("SELECT * FROM native_observers WHERE session_id=? AND game_build=? AND synthetic=? ORDER BY last_seen_at DESC LIMIT 1",(session_id,game_build,int(synthetic))).fetchone()
            if row is None:return empty
            view=self._view(row)
            body=view["report"]
            seen=self._seen_ticks.get(row["observer_key"])
            elapsed=None if seen is None else max(0,self._monotonic()-seen)
            connection="disconnected" if elapsed is None or elapsed>=self._observations.runtime_disconnect_seconds else "stale" if elapsed>=self._observations.runtime_stale_seconds else "connected"
            age=(self._clock()-_date(row["captured_at"])).total_seconds()
            fresh=body["status"]=="available" and connection=="connected" and -60<=age<=self._observations.runtime_stale_seconds and runtime_connection=="connected"
            state=body["status"] if body["status"]!="available" else "stale_report" if not fresh else "unknown" if body["installed"] is None else "committed_capture_not_started" if body["installed"] is False and body["install_state"]==3 else "not_installed" if not body["installed"] else "capture_disabled" if body["capture_enabled"] is False else "capture_state_unknown" if body["capture_enabled"] is None else "observed_callbacks" if view["callback_observed"] is True else "waiting_callbacks" if view["callback_observed"] is False else "callback_count_unknown"
            return {**empty,"has_report":True,"observer_key":row["observer_key"],"state":state,"report_connection_state":connection,"capture_age_seconds":age,"installed":body["installed"] if fresh else None,"capture_enabled":body["capture_enabled"] if fresh else None,"reported_installed":body["installed"],"reported_capture_enabled":body["capture_enabled"],"reported_install_state":body["install_state"],"reported_hook_committed":None if body["install_state"] is None else body["install_state"]==3,"observed_callback_count":view["observed_callback_count"],"captured_header_count":view["captured_header_count"],"callback_observed":view["callback_observed"],"last_seen_at":row["last_seen_at"],"last_callback_at":row["last_callback_at"],"last_callback_basis":row["last_callback_basis"],"last_callback_scope":view["last_callback_scope"],"observation_gaps":view["observation_gaps"],"counter_consistency":view["counter_consistency"],"target_label":"SendDataResponse dispatch thunk (anchor + 12 bytes)","setter_export_readability_inferred":False,"lossless_capture_claimed":False,"counter_values":{name:body[name] for name in COUNTERS},"count_units":view["count_units"]}
