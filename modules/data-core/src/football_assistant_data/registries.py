"""Passive runtime registry diagnostics. No reflection, invocation or Agent calls."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import EVENT_PAGE_BYTE_BUDGET, ObservationConflict, _date, _digest, _json


class RegistrySource(BaseModel):
    model_config=ConfigDict(extra="forbid")
    adapter_id: str=Field(min_length=1,max_length=128)
    session_id: str=Field(min_length=1,max_length=128)
    game_build: str=Field(min_length=1,max_length=128)
    bundle_version: str | None=Field(default=None,max_length=128)
    metadata_sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    game_assembly_sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    synthetic: bool

    @model_validator(mode="after")
    def aware_capture(self):
        if self.captured_at.tzinfo is None:raise ValueError("Capture timestamp needs a timezone")
        return self


class RegistryCounts(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id_count: int | None=Field(default=None,strict=True,ge=0,le=2147483647)
    name_hash_count: int | None=Field(default=None,strict=True,ge=0,le=2147483647)


class ReportedEnumeration(BaseModel):
    model_config=ConfigDict(extra="forbid")
    enumeration_id: str | None=Field(default=None,min_length=1,max_length=128)
    dictionary_version: int | None=Field(default=None,strict=True,ge=-2147483648,le=2147483647)
    expected_entries: int | None=Field(default=None,strict=True,ge=0,le=2147483647)
    observed_unique_entries: int=Field(strict=True,ge=0,le=2147483647)
    complete: bool


class RegistryProbe(BaseModel):
    model_config=ConfigDict(extra="forbid")
    probe_id: str=Field(pattern=r"^registry:.{1,240}$")
    kind: Literal["runtime_registry"]
    status: Literal["available","needs_context","unsupported","error","not_probed"]
    context_ref: str=Field(min_length=1,max_length=512)
    reason: str=Field(min_length=1,max_length=1024)
    values: RegistryCounts
    enumeration: ReportedEnumeration
    entries: list[dict]=Field(default_factory=list,max_length=0)

    @model_validator(mode="after")
    def explicit_counts(self):
        if self.values.id_count is not None and self.enumeration.expected_entries is not None and self.values.id_count!=self.enumeration.expected_entries:
            raise ValueError("Expected entries differ from the reported actual ID count")
        if self.enumeration.enumeration_id is None and (self.enumeration.complete or self.enumeration.observed_unique_entries):
            raise ValueError("Enumeration results need an enumeration ID")
        return self


class ProbeRequest(RegistrySource):
    probes: list[RegistryProbe]=Field(min_length=1,max_length=100)

    @model_validator(mode="after")
    def unique_probes(self):
        if len({probe.probe_id for probe in self.probes})!=len(self.probes):raise ValueError("Duplicate probe IDs in one request")
        return self


class RegistryEntry(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id: int=Field(strict=True,ge=0,le=4294967295)
    name: str | None=Field(default=None,max_length=1024)
    owner: str | None=Field(default=None,max_length=1024)
    display_name: str | None=Field(default=None,max_length=2048)
    value_type: str | None=Field(default=None,max_length=512)


class RegistryBatch(RegistrySource):
    registry_id: str=Field(min_length=1,max_length=240)
    enumeration_id: str=Field(min_length=1,max_length=128)
    dictionary_version: int | None=Field(default=None,strict=True,ge=-2147483648,le=2147483647)
    expected_count: int | None=Field(default=None,strict=True,ge=0,le=2147483647)
    complete: bool=False
    entries: list[RegistryEntry]=Field(max_length=100)

    @model_validator(mode="after")
    def explicit_completion(self):
        if len({entry.id for entry in self.entries})!=len(self.entries):raise ValueError("Duplicate uint IDs in batch")
        if self.complete and self.expected_count is None:raise ValueError("Unknown expected count cannot be complete")
        if self.expected_count is not None and len(self.entries)>self.expected_count:raise ValueError("Batch exceeds expected count")
        return self


class RegistryStore:
    """Shares the Data Core connection/lock so diagnostics and events commit together."""
    def __init__(self,observations):
        self._observations=observations
        self._db=observations._db
        self._lock=observations._lock
        self._clock=observations._clock
        with self._lock:
            self._db.executescript("""
            CREATE TABLE IF NOT EXISTS registry_enumerations (
                enumeration_key TEXT PRIMARY KEY,identity TEXT NOT NULL,registry_id TEXT NOT NULL,enumeration_id TEXT NOT NULL,
                expected_count INTEGER,dictionary_version INTEGER,registered_count INTEGER NOT NULL DEFAULT 0,complete INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS registry_enumeration_scope ON registry_enumerations(registry_id,enumeration_id,json_extract(identity,'$.adapter_id'),json_extract(identity,'$.session_id'),json_extract(identity,'$.synthetic'));
            CREATE TABLE IF NOT EXISTS registry_entries (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,enumeration_key TEXT NOT NULL,entry_id INTEGER NOT NULL,record TEXT NOT NULL,
                UNIQUE(enumeration_key,entry_id)
            );
            CREATE INDEX IF NOT EXISTS registry_entries_cursor ON registry_entries(enumeration_key,seq);
            CREATE TABLE IF NOT EXISTS registry_probes (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,probe_key TEXT UNIQUE NOT NULL,registry_id TEXT NOT NULL,session_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,state_digest TEXT NOT NULL,record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS registry_probe_sessions ON registry_probes(session_id,seq);
            CREATE TABLE IF NOT EXISTS registry_probe_history (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT,probe_key TEXT NOT NULL,created_at TEXT NOT NULL,record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS registry_probe_history_key ON registry_probe_history(probe_key,cursor);
            """)

    @staticmethod
    def source_identity(header):
        return {key:header.get(key) for key in ("adapter_id","session_id","game_build","bundle_version","metadata_sha256","game_assembly_sha256","synthetic")}

    def enumeration_key(self,header,registry_id,enumeration_id):
        return _digest([self.source_identity(header),registry_id,enumeration_id])

    def _enumeration(self,header,registry_id,enumeration_id):
        row=self._db.execute("SELECT * FROM registry_enumerations WHERE registry_id=? AND enumeration_id=? AND json_extract(identity,'$.adapter_id')=? AND json_extract(identity,'$.session_id')=? AND json_extract(identity,'$.synthetic')=?",(registry_id,enumeration_id,header["adapter_id"],header["session_id"],int(header["synthetic"]))).fetchone()
        if row and self.source_identity(json.loads(row["identity"]))!=self.source_identity(header):raise ObservationConflict("Enumeration source/build/hash context changed; start a new enumeration ID")
        return row

    def _declare_probe_epoch(self,header,probe,now):
        reported=probe["enumeration"]
        if reported["enumeration_id"] is None:return
        registry_id=probe["probe_id"].removeprefix("registry:")
        previous=self._enumeration(header,registry_id,reported["enumeration_id"])
        if previous:
            if previous["expected_count"]!=reported["expected_entries"] or previous["dictionary_version"]!=reported.get("dictionary_version"):
                raise ObservationConflict("Probe epoch expected count or version changed; start a new enumeration ID")
        else:
            key=self.enumeration_key(header,registry_id,reported["enumeration_id"])
            self._db.execute("INSERT INTO registry_enumerations VALUES (?,?,?,?,?,?,0,0,?,?)",(key,_json(header),registry_id,reported["enumeration_id"],reported["expected_entries"],reported.get("dictionary_version"),now,now))

    def _resolve(self,header,probe):
        registry_id=probe["probe_id"].removeprefix("registry:")
        reported=probe["enumeration"]
        key=None if reported["enumeration_id"] is None else self.enumeration_key(header,registry_id,reported["enumeration_id"])
        row=None if key is None else self._enumeration(header,registry_id,reported["enumeration_id"])
        if row:
            if reported["expected_entries"] is not None and reported["expected_entries"]!=row["expected_count"]:raise ObservationConflict("Probe expected count differs from registered enumeration")
            if reported.get("dictionary_version") is not None and reported["dictionary_version"]!=row["dictionary_version"]:raise ObservationConflict("Probe dictionary version differs from registered enumeration")
        if reported["complete"] and not (row and row["complete"]):raise ObservationConflict("A probe cannot declare an unregistered enumeration complete")
        expected=row["expected_count"] if row else reported["expected_entries"]
        observed=row["registered_count"] if row else 0
        complete=bool(row and row["complete"])
        enumeration={"enumeration_id":reported["enumeration_id"],"enumeration_key":key,"dictionary_version":row["dictionary_version"] if row else reported.get("dictionary_version"),"expected_entries":expected,"observed_unique_entries":observed,"complete":complete,"known_empty":complete and expected==0,"registration_state":"complete" if complete else "partial" if observed else "declared" if row else "not_registered","completeness_scope":"uint_id_inventory_only"}
        return {"probe_id":probe["probe_id"],"registry_id":registry_id,"kind":probe["kind"],"status":probe["status"],"context_ref":probe["context_ref"],"reason":probe["reason"],"values":probe["values"],"known_count_fields":[key for key,value in probe["values"].items() if value is not None],"enumeration":enumeration,"reported_enumeration":reported,"field_values_known":False,"entries":[]}

    def _view(self,row):
        saved=json.loads(row["record"])
        return {"cursor":row["seq"],"probe_key":row["probe_key"],"source":saved["source"],"captured_at":row["captured_at"],"last_seen_at":row["last_seen_at"],**self._resolve(saved["source"],saved["probe"])}

    def record_probes(self,body):
        header={key:value for key,value in body.items() if key!="probes"}
        now=self._clock().isoformat()
        changed=0
        results=[]
        with self._lock,self._db:
            for probe in body["probes"]:
                key=_digest([self.source_identity(header),probe["probe_id"]])
                previous=self._db.execute("SELECT * FROM registry_probes WHERE probe_key=?",(key,)).fetchone()
                if previous and _date(header["captured_at"])<_date(previous["captured_at"]):
                    self._db.execute("UPDATE registry_probes SET last_seen_at=? WHERE probe_key=?",(now,key))
                    updated=self._db.execute("SELECT * FROM registry_probes WHERE probe_key=?",(key,)).fetchone()
                    results.append({**self._view(updated),"ignored_out_of_order":True})
                    continue
                self._declare_probe_epoch(header,probe,now)
                resolved=self._resolve(header,probe)
                state={key:value for key,value in resolved.items() if key!="reported_enumeration"}
                digest=_digest(state)
                self._db.execute("INSERT INTO registry_probes(probe_key,registry_id,session_id,captured_at,last_seen_at,state_digest,record) VALUES (?,?,?,?,?,?,?) ON CONFLICT(probe_key) DO UPDATE SET captured_at=excluded.captured_at,last_seen_at=excluded.last_seen_at,state_digest=excluded.state_digest,record=excluded.record",(key,resolved["registry_id"],header["session_id"],header["captured_at"],now,digest,_json({"source":header,"probe":probe})))
                row=self._db.execute("SELECT * FROM registry_probes WHERE probe_key=?",(key,)).fetchone()
                view=self._view(row)
                if previous is None or previous["state_digest"]!=digest:
                    changed+=1
                    self._db.execute("INSERT INTO registry_probe_history(probe_key,created_at,record) VALUES (?,?,?)",(key,now,_json(view)))
                    self._observations._emit("registry_probe_changed",None,None,header["synthetic"],{"semantic_level":"runtime_registry_diagnostic","probe_key":key,"registry_id":resolved["registry_id"],"session_id":header["session_id"],"status":resolved["status"],"observed_unique_entries":resolved["enumeration"]["observed_unique_entries"],"complete":resolved["enumeration"]["complete"]})
                results.append(view)
        return {"accepted":True,"changed_count":changed,"results":results}

    def _page(self,rows,after,key,item_builder):
        items=[]
        more=False
        for row in rows:
            item=item_builder(row)
            candidate={key:items+[item],"next_cursor":item["cursor"],"has_more":False,"response_byte_budget":EVENT_PAGE_BYTE_BUDGET}
            if len(_json(candidate).encode())>EVENT_PAGE_BYTE_BUDGET:
                more=True
                break
            items.append(item)
        return {key:items,"next_cursor":items[-1]["cursor"] if items else after,"has_more":more,"response_byte_budget":EVENT_PAGE_BYTE_BUDGET}

    def probes(self,after=0,limit=100,session_id=None):
        with self._lock:
            sql="SELECT * FROM registry_probes WHERE seq>?"
            params=[after]
            if session_id:
                sql+=" AND session_id=?"
                params.append(session_id)
            rows=self._db.execute(sql+" ORDER BY seq LIMIT ?",(*params,limit+1)).fetchall()
            result=self._page(rows[:limit],after,"probes",self._view)
            result["has_more"]=result["has_more"] or len(rows)>limit
            return result

    def history(self,probe_key,after=0,limit=100):
        with self._lock:
            rows=self._db.execute("SELECT * FROM registry_probe_history WHERE probe_key=? AND cursor>? ORDER BY cursor LIMIT ?",(probe_key,after,limit+1)).fetchall()
            result=self._page(rows[:limit],after,"history",lambda row:{**json.loads(row["record"]),"cursor":row["cursor"],"created_at":row["created_at"]})
            result["has_more"]=result["has_more"] or len(rows)>limit
            return result

    def summary(self,session_id=None,synthetic=None):
        with self._lock:
            if session_id is None:
                latest=self._db.execute("SELECT session_id FROM registry_probes"+(" WHERE json_extract(record,'$.source.synthetic')=?" if synthetic is not None else "")+" ORDER BY last_seen_at DESC LIMIT 1",(int(synthetic),) if synthetic is not None else ()).fetchone()
                session_id=latest[0] if latest else None
            rows=[] if session_id is None else self._db.execute("SELECT * FROM registry_probes WHERE session_id=?"+(" AND json_extract(record,'$.source.synthetic')=?" if synthetic is not None else "")+" ORDER BY seq",(session_id,int(synthetic)) if synthetic is not None else (session_id,)).fetchall()
            counts={}
            for row in rows:
                status=json.loads(row["record"])["probe"]["status"]
                counts[status]=counts.get(status,0)+1
            views=[self._view(row) for row in rows[:20]]
            return {"session_id":session_id,"registry_count":len(rows),"status_counts":counts,"probes":[{"probe_key":view["probe_key"],"registry_id":view["registry_id"],"synthetic":view["source"]["synthetic"],"adapter_id":view["source"]["adapter_id"],"game_build":view["source"]["game_build"],"status":view["status"],"values":view["values"],"enumeration":view["enumeration"],"last_seen_at":view["last_seen_at"]} for view in views],"truncated":len(rows)>20,"field_values_known":False,"automatic_model_calls":False}

    @staticmethod
    def _enumeration_view(row):
        return {"enumeration_key":row["enumeration_key"],"registry_id":row["registry_id"],"enumeration_id":row["enumeration_id"],"source":json.loads(row["identity"]),"expected_count":row["expected_count"],"dictionary_version":row["dictionary_version"],"observed_unique_entries":row["registered_count"],"complete":bool(row["complete"]),"known_empty":bool(row["complete"]) and row["expected_count"]==0,"first_seen_at":row["first_seen_at"],"last_seen_at":row["last_seen_at"],"field_values_known":False,"completeness_scope":"uint_id_inventory_only"}

    def register_batch(self,body):
        header={key:body[key] for key in RegistrySource.model_fields}
        key=self.enumeration_key(header,body["registry_id"],body["enumeration_id"])
        now=self._clock().isoformat()
        with self._lock,self._db:
            previous=self._enumeration(header,body["registry_id"],body["enumeration_id"])
            if previous is None:
                # Diagnostics accepted by the first probe-only release may predate
                # descriptor creation. Pin their published epoch before first data.
                for probe_row in self._db.execute("SELECT record,last_seen_at FROM registry_probes WHERE registry_id=? AND session_id=?",(body["registry_id"],header["session_id"])).fetchall():
                    saved=json.loads(probe_row["record"])
                    source=saved["source"]
                    if source["adapter_id"]==header["adapter_id"] and source["synthetic"]==header["synthetic"] and saved["probe"]["enumeration"]["enumeration_id"]==body["enumeration_id"]:
                        self._declare_probe_epoch(source,saved["probe"],probe_row["last_seen_at"])
                previous=self._enumeration(header,body["registry_id"],body["enumeration_id"])
            if previous and (previous["expected_count"]!=body["expected_count"] or previous["dictionary_version"]!=body["dictionary_version"]):raise ObservationConflict("Enumeration expected count or dictionary version changed; start a new enumeration ID")
            if previous is None:
                self._db.execute("INSERT INTO registry_enumerations VALUES (?,?,?,?,?,?,0,0,?,?)",(key,_json(header),body["registry_id"],body["enumeration_id"],body["expected_count"],body["dictionary_version"],now,now))
            count=previous["registered_count"] if previous else 0
            existing={}
            ids=[entry["id"] for entry in body["entries"]]
            if ids:
                placeholders=",".join("?" for _ in ids)
                existing={row["entry_id"]:json.loads(row["record"]) for row in self._db.execute(f"SELECT entry_id,record FROM registry_entries WHERE enumeration_key=? AND entry_id IN ({placeholders})",(key,*ids)).fetchall()}
            inserted=0
            enriched=0
            for entry in body["entries"]:
                old=existing.get(entry["id"])
                if old is None:
                    record={"entry":entry,"captured_at":header["captured_at"],"enriched_at":None}
                    count+=1
                    inserted+=1
                    self._db.execute("INSERT INTO registry_entries(enumeration_key,entry_id,record) VALUES (?,?,?)",(key,entry["id"],_json(record)))
                else:
                    merged=dict(old["entry"])
                    changed=False
                    for field,value in entry.items():
                        if value is None:continue
                        if merged.get(field) is not None and merged[field]!=value:raise ObservationConflict("Known registry entry metadata changed inside one enumeration")
                        if merged.get(field) is None:
                            merged[field]=value
                            changed=True
                    if changed:
                        enriched+=1
                        self._db.execute("UPDATE registry_entries SET record=? WHERE enumeration_key=? AND entry_id=?",(_json({**old,"entry":merged,"enriched_at":header["captured_at"]}),key,entry["id"]))
            expected=body["expected_count"]
            if expected is not None and count>expected:raise ObservationConflict("Registered unique entries exceed expected count")
            if body["complete"] and count!=expected:raise ObservationConflict("Enumeration cannot be complete before all expected unique IDs are registered")
            complete=bool(previous and previous["complete"]) or bool(body["complete"])
            self._db.execute("UPDATE registry_enumerations SET registered_count=?,complete=?,last_seen_at=? WHERE enumeration_key=?",(count,int(complete),now,key))
            row=self._db.execute("SELECT * FROM registry_enumerations WHERE enumeration_key=?",(key,)).fetchone()
            if complete and not (previous and previous["complete"]):
                self._observations._emit("registry_enumeration_completed",None,None,header["synthetic"],{"semantic_level":"runtime_registry_inventory","enumeration_key":key,"registry_id":body["registry_id"],"session_id":header["session_id"],"observed_unique_entries":count,"known_empty":expected==0,"field_values_known":False})
            return {"accepted":True,"inserted_count":inserted,"enriched_count":enriched,**self._enumeration_view(row)}

    def enumeration(self,enumeration_key):
        with self._lock:
            row=self._db.execute("SELECT * FROM registry_enumerations WHERE enumeration_key=?",(enumeration_key,)).fetchone()
            return self._enumeration_view(row) if row else None

    def entries(self,enumeration_key,after=0,limit=100):
        with self._lock:
            enumeration=self.enumeration(enumeration_key)
            if enumeration is None:raise KeyError("Registry enumeration does not exist")
            rows=self._db.execute("SELECT seq,record FROM registry_entries WHERE enumeration_key=? AND seq>? ORDER BY seq LIMIT ?",(enumeration_key,after,limit+1)).fetchall()
            def item(row):
                saved=json.loads(row["record"])
                return {"cursor":row["seq"],**saved["entry"],"captured_at":saved["captured_at"],"enriched_at":saved["enriched_at"],"known_metadata_fields":[key for key,value in saved["entry"].items() if value is not None],"field_values_known":False}
            result=self._page(rows[:limit],after,"entries",item)
            result["has_more"]=result["has_more"] or len(rows)>limit
            result["enumeration"]=enumeration
            # The source/enum header is included in the final byte budget too.
            while len(_json(result).encode())>EVENT_PAGE_BYTE_BUDGET:
                result["entries"].pop()
                result["has_more"]=True
                result["next_cursor"]=result["entries"][-1]["cursor"] if result["entries"] else after
            return result
