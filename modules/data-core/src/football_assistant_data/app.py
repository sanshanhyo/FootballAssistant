"""One loopback process, with separate observation and companion storage owners."""
from __future__ import annotations

import json
import os
import secrets
import socket
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Literal
from pathlib import Path
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Path as ApiPath, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from football_assistant_contracts.validation import validate_observation
from .business_store import BusinessSnapshotStore
from .config import Settings
from .display_profile import MAX_FACTS, project_display_profile
from .storage import ObservationConflict, ObservationStore, private_directory, utc_now
from .monitoring import CatalogRequest, HeartbeatRequest
from .registries import ProbeRequest, RegistryBatch, RegistryStore
from .native_observers import NativeObserverReport, NativeObserverStore


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class BusinessAdviceRequest(ChatRequest):
    capability: Literal["player_info", "transfer_analysis", "tactical_analysis", "schedule_analysis"]


class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("memory must not be blank")
        return value.strip()


class BodyLimitMiddleware:
    """Cap real bytes even if Content-Length is absent or dishonest."""
    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                response = JSONResponse(status_code=413, content={"detail":{"code":"request_too_large","message":"请求超过大小限制。"}})
                return await response(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0
        async def replay():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()
        await self.app(scope, replay, send)


def _write_runtime(settings: Settings) -> None:
    private_directory(settings.runtime_file.parent)
    payload = {"base_url":f"http://127.0.0.1:{settings.port}","token":settings.token,"pid":os.getpid(),"started_at":utc_now()}
    descriptor, temporary = tempfile.mkstemp(prefix=".runtime-", dir=settings.runtime_file.parent)
    try:
        with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
            json.dump(payload,stream)
        os.replace(temporary,settings.runtime_file)
        if os.name != "nt":
            settings.runtime_file.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def create_app(settings: Settings | None = None, *, enable_agent: bool = True) -> FastAPI:
    settings = settings or Settings.from_env(reader_only=not enable_agent)
    # Reader imports never import PydanticAI, OpenAI or companion storage.
    if enable_agent:
        from football_assistant_agent.service import AgentService, ModelBudgetExceeded, ModelNotConfigured, ModelUnavailable
        from football_assistant_agent.storage import CompanionStore

    @asynccontextmanager
    async def lifespan(app):
        private_directory(settings.data_dir)
        observations = ObservationStore(settings.data_dir / "observations.sqlite", settings.stale_seconds,runtime_stale_seconds=settings.runtime_stale_seconds,runtime_disconnect_seconds=settings.runtime_disconnect_seconds)
        app.state.registries = RegistryStore(observations)
        app.state.native_observers = NativeObserverStore(observations,app.state.registries)
        app.state.observations = observations
        app.state.business_snapshots = BusinessSnapshotStore()
        companion = None
        if enable_agent:
            companion = CompanionStore(settings.data_dir / "companion.sqlite")
            app.state.companion = companion
            app.state.agent = AgentService(settings,companion)
        _write_runtime(settings)
        try:
            yield
        finally:
            app.state.business_snapshots.invalidate()
            observations.close()
            if companion is not None:
                companion.close()
            try:
                runtime = json.loads(settings.runtime_file.read_text())
                if runtime.get("pid") == os.getpid() and secrets.compare_digest(runtime.get("token",""),settings.token):
                    settings.runtime_file.unlink(missing_ok=True)
            except (OSError,ValueError,TypeError):
                pass

    app = FastAPI(title="FootballAssistant local backend", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1","localhost"])
    app.add_middleware(BodyLimitMiddleware,max_bytes=settings.max_request_bytes)
    auth = HTTPBearer(auto_error=False)

    async def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(auth)):
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode("utf-8"),settings.token.encode("utf-8")):
            raise HTTPException(401,detail={"code":"unauthorized","message":"需要有效的本机访问令牌。"},headers={"WWW-Authenticate":"Bearer"})

    @app.get("/health")
    async def health():
        return {"status":"ok","service":"football-assistant","version":"0.1.0","reader_api":1,"agent_enabled":enable_agent}

    @app.get("/v1/status",dependencies=[Depends(authorized)])
    async def status():
        if not enable_agent:
            return {"source_status":app.state.observations.source_status(),"mode":"reader","agent_enabled":False}
        return {"source_status":app.state.observations.source_status(),"modelConfigured":settings.model_configured,"modelStatus":"unconfigured" if not settings.model_configured else "error" if app.state.agent.last_error else "ready","memory":app.state.companion.counts()}

    if enable_agent:
        @app.get("/v1/companion/state",dependencies=[Depends(authorized)])
        async def companion_state():
            state = "model_unconfigured" if not settings.model_configured else "model_error" if app.state.agent.last_error else "ready"
            return {"state":"idle","mood":"neutral","status":state,"source_status":app.state.observations.source_status()}

    @app.get("/v1/reader/status",dependencies=[Depends(authorized)])
    async def reader_status():
        return {"service":"football-assistant","reader_api":1,"agent_enabled":enable_agent,
                "source_status":app.state.observations.source_status(),
                "latest_event_cursor":app.state.observations.events(0,1)["latest_cursor"],
                "native_records":{"state":"awaiting_decoded_native_records","payload_decoded":False,
                                  "field_values_known":False,"scope":"headers_are_diagnostics_only"}}

    @app.get("/v1/reader/snapshot",dependencies=[Depends(authorized)])
    async def reader_snapshot(after: int = Query(default=0,ge=0,le=2000),
                              limit: int = Query(default=100,ge=1,le=MAX_FACTS),
                              event_id: str | None = Query(default=None,max_length=128)):
        try:
            return app.state.observations.reader_snapshot(after,limit,event_id=event_id)
        except ObservationConflict:
            raise HTTPException(409,detail={"code":"snapshot_changed","message":"Snapshot changed; restart paging at zero."}) from None

    @app.get("/v1/reader/business/status",dependencies=[Depends(authorized)])
    async def business_reader_status():
        return app.state.business_snapshots.status()

    @app.get("/v1/reader/business/snapshot",dependencies=[Depends(authorized)])
    async def business_reader_snapshot():
        return app.state.business_snapshots.read()

    @app.get("/v1/reader/profile",dependencies=[Depends(authorized)])
    async def reader_profile():
        return project_display_profile(app.state.observations.reader_snapshot(0,MAX_FACTS))

    @app.get("/v1/reader/schedule",dependencies=[Depends(authorized)])
    async def reader_schedule():
        # Read-only preview; no model configuration, budget or provider access.
        from football_assistant_agent.ui_advice import prepare_ui_advice
        prepared = prepare_ui_advice('schedule_analysis', app.state.observations.reader_snapshot(0, MAX_FACTS))
        projection = prepared['schedule_projection']
        return dict(status=projection['status'] if projection else 'unavailable',
                    source='ui', partial=True, production_ready=False,
                    schedule_projection=projection, provenance=prepared['provenance'],
                    reasons=prepared['reasons'])

    @app.post("/v1/observations",dependencies=[Depends(authorized)])
    async def observation(body: dict):
        try:
            validate_observation(body)
        except ValueError as error:
            raise HTTPException(422,detail={"code":"invalid_observation","message":str(error)}) from None
        try:
            result = app.state.observations.ingest(body)
        except ObservationConflict as error:
            raise HTTPException(409,detail={"code":"observation_conflict","message":str(error)}) from None
        return {"accepted":True,**result,"event_id":body["event_id"],"source_status":app.state.observations.source_status()}

    @app.get("/v1/monitoring",dependencies=[Depends(authorized)])
    async def monitoring():
        source=app.state.observations.source_status()
        game=source.get("game") or {}
        return app.state.observations.monitoring(registry_summary=app.state.registries.summary(game.get("session_id"),source.get("synthetic")),native_observer_summary=app.state.native_observers.summary(game.get("session_id") if source.get("source")=="runtime" else None,game.get("build"),source.get("synthetic"),source.get("connection_state")))

    @app.get("/v1/monitoring/fields",dependencies=[Depends(authorized)])
    async def fields(stream_id: str | None = Query(default=None,max_length=64)):
        return app.state.observations.fields(stream_id)

    @app.post("/v1/monitoring/heartbeat",dependencies=[Depends(authorized)])
    async def heartbeat(body: HeartbeatRequest):
        try:return app.state.observations.heartbeat(body.stream_id,body.state,body.detail)
        except KeyError:raise HTTPException(404,detail={"code":"stream_not_found","message":"Source stream does not exist"}) from None

    @app.get("/v1/events",dependencies=[Depends(authorized)])
    async def events(after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=100,ge=1,le=200)):
        return app.state.observations.events(after,limit)

    @app.get("/v1/events/{cursor}",dependencies=[Depends(authorized)])
    async def event_detail(cursor: int = ApiPath(ge=1,le=9223372036854775807)):
        event=app.state.observations.event_detail(cursor)
        if event is None:raise HTTPException(404,detail={"code":"event_not_found","message":"Event does not exist"})
        return event

    @app.post("/v1/interfaces/catalog",dependencies=[Depends(authorized)])
    async def register_catalog(body: CatalogRequest):
        try:return app.state.observations.register_catalog(body.model_dump(mode="json"))
        except ObservationConflict as error:raise HTTPException(409,detail={"code":"catalog_conflict","message":str(error)}) from None

    @app.post("/v1/interfaces/native-observers",dependencies=[Depends(authorized)])
    async def record_native_observer(body: Any = Body(...)):
        try:report=NativeObserverReport.model_validate(body)
        except ValidationError:
            # Private install reports contain runtime addresses. Reject extra
            # pointer fields without FastAPI's normal input-value echo.
            raise HTTPException(422,detail={"code":"invalid_native_diagnostic","message":"Native diagnostics must follow the sanitized pointer-free contract"}) from None
        try:return app.state.native_observers.record(report.model_dump(mode="json"))
        except ObservationConflict as error:raise HTTPException(409,detail={"code":"native_diagnostic_conflict","message":str(error)}) from None

    @app.get("/v1/interfaces/native-observers",dependencies=[Depends(authorized)])
    async def native_observers(after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=20,ge=1,le=100),session_id: str | None = Query(default=None,max_length=128)):
        return app.state.native_observers.latest(after,limit,session_id)

    @app.get("/v1/interfaces/native-observers/history",dependencies=[Depends(authorized)])
    async def native_observer_history(observer_key: str = Query(pattern=r"^[0-9a-f]{64}$"),after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=20,ge=1,le=100)):
        return app.state.native_observers.history(observer_key,after,limit)

    @app.post("/v1/interfaces/probes",dependencies=[Depends(authorized)])
    async def record_probes(body: ProbeRequest):
        try:return app.state.registries.record_probes(body.model_dump(mode="json"))
        except ObservationConflict as error:raise HTTPException(409,detail={"code":"registry_probe_conflict","message":str(error)}) from None

    @app.get("/v1/interfaces/probes",dependencies=[Depends(authorized)])
    async def registry_probes(after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=100,ge=1,le=100),session_id: str | None = Query(default=None,max_length=128)):
        return app.state.registries.probes(after,limit,session_id)

    @app.get("/v1/interfaces/probes/history",dependencies=[Depends(authorized)])
    async def registry_probe_history(probe_key: str = Query(pattern=r"^[0-9a-f]{64}$"),after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=100,ge=1,le=100)):
        return app.state.registries.history(probe_key,after,limit)

    @app.post("/v1/interfaces/registries/batches",dependencies=[Depends(authorized)])
    async def register_registry_batch(body: RegistryBatch):
        try:return app.state.registries.register_batch(body.model_dump(mode="json"))
        except ObservationConflict as error:raise HTTPException(409,detail={"code":"registry_enumeration_conflict","message":str(error)}) from None

    @app.get("/v1/interfaces/registries/{enumeration_key}",dependencies=[Depends(authorized)])
    async def registry_enumeration(enumeration_key: str = ApiPath(pattern=r"^[0-9a-f]{64}$")):
        result=app.state.registries.enumeration(enumeration_key)
        if result is None:raise HTTPException(404,detail={"code":"registry_enumeration_not_found","message":"Registry enumeration does not exist"})
        return result

    @app.get("/v1/interfaces/registries/{enumeration_key}/entries",dependencies=[Depends(authorized)])
    async def registry_entries(enumeration_key: str = ApiPath(pattern=r"^[0-9a-f]{64}$"),after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=100,ge=1,le=100)):
        try:return app.state.registries.entries(enumeration_key,after,limit)
        except KeyError:raise HTTPException(404,detail={"code":"registry_enumeration_not_found","message":"Registry enumeration does not exist"}) from None

    @app.get("/v1/interfaces/catalogs",dependencies=[Depends(authorized)])
    async def catalogs():
        return app.state.observations.catalogs()

    @app.get("/v1/interfaces",dependencies=[Depends(authorized)])
    async def interfaces(catalog_id: str = Query(min_length=1,max_length=256),after: int = Query(default=0,ge=0,le=9223372036854775807),limit: int = Query(default=100,ge=1,le=200),access_status: str | None = Query(default=None,max_length=64)):
        return app.state.observations.interfaces(catalog_id,after,limit,access_status)

    if enable_agent:
        @app.post("/v1/agent/business-advice",dependencies=[Depends(authorized)])
        async def business_advice(body: BusinessAdviceRequest):
            # Only the server-owned channel supplies data. Request bodies cannot
            # override provenance, readiness or provide their own snapshot.
            snapshot = app.state.business_snapshots.read()["snapshot"]
            try:
                return await app.state.agent.business_advice(body.message,body.conversation_id,body.capability,snapshot)
            except ModelBudgetExceeded as error:
                raise HTTPException(429,detail={"code":"model_request_limit","message":str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503,detail={"code":"model_not_configured","message":str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502,detail={"code":"model_unavailable","message":str(error)}) from None

        @app.post("/v1/agent/ui-advice",dependencies=[Depends(authorized)])
        async def ui_advice(body: BusinessAdviceRequest):
            # Only the server-owned channel supplies data. Request bodies cannot
            # override provenance, readiness or provide their own snapshot.
            snapshot = app.state.observations.reader_snapshot(0, MAX_FACTS)
            try:
                return await app.state.agent.ui_advice(body.message,body.conversation_id,body.capability,snapshot,
                    refresh=lambda: app.state.observations.reader_snapshot(0, MAX_FACTS))
            except ModelBudgetExceeded as error:
                raise HTTPException(429,detail={"code":"model_request_limit","message":str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503,detail={"code":"model_not_configured","message":str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502,detail={"code":"model_unavailable","message":str(error)}) from None

        @app.post("/v1/chat",dependencies=[Depends(authorized)])
        async def chat(body: ChatRequest):
            try:
                return await app.state.agent.chat(body.message,body.conversation_id)
            except ModelBudgetExceeded as error:
                raise HTTPException(429,detail={"code":"model_request_limit","message":str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503,detail={"code":"model_not_configured","message":str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502,detail={"code":"model_unavailable","message":str(error)}) from None

        @app.get("/v1/memories",dependencies=[Depends(authorized)])
        async def memories():
            return {"memories":app.state.companion.memories()}

        @app.post("/v1/memories",dependencies=[Depends(authorized)],status_code=201)
        async def create_memory(body: MemoryRequest):
            return app.state.companion.add_memory(body.content)

        @app.delete("/v1/memories/{memory_id}",dependencies=[Depends(authorized)])
        async def delete_memory(memory_id: UUID):
            if not app.state.companion.delete_memory(str(memory_id)):
                raise HTTPException(404,detail={"code":"memory_not_found","message":"记忆不存在。"})
            return {"deleted":True}

    return app


def serve(settings: Settings, *, enable_agent: bool = True):
    from .server_lock import writer_guard
    with writer_guard(settings):
        _serve(settings,enable_agent=enable_agent)


def _serve(settings: Settings, *, enable_agent: bool):
    # Bind before lifespan writes runtime.json: a second launch must not replace
    # the running service's credential file before discovering the port is busy.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        if os.name == "nt" and hasattr(socket,"SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        elif os.name != "nt":
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:
            listener.bind(("127.0.0.1",settings.port))
        except OSError:
            raise SystemExit("Backend port is unavailable; use the running instance or choose another port.") from None
        listener.listen(128)
        listener.setblocking(False)
        server = uvicorn.Server(uvicorn.Config(create_app(settings,enable_agent=enable_agent),host="127.0.0.1",port=settings.port,access_log=False))
        server.run(sockets=[listener])


def main():
    serve(Settings.from_env())
