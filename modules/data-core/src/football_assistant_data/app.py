"""One loopback process, with separate observation and companion storage owners."""
from __future__ import annotations

import json
import asyncio
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
from .windows_discovery_import import IMPORT_ROUTE, MAX_IMPORT_BYTES, empty_snapshot, parse_import
from .config import Settings
from .display_profile import MAX_FACTS, project_display_profile
from .storage import ObservationConflict, ObservationStore, private_directory, utc_now
from .monitoring import CatalogRequest, HeartbeatRequest
from .registries import ProbeRequest, RegistryBatch, RegistryStore
from .native_observers import NativeObserverReport, NativeObserverStore


class CaptureProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile: Literal["schedule", "tactics", "current_page_attributes", "next_match"]


class CharacterContext(BaseModel):
    """Authenticated main-process context; never accepts resource paths or URLs."""
    model_config = ConfigDict(extra="forbid", strict=True)
    save_id: str = Field(min_length=1, max_length=512)
    character_id: str = Field(min_length=1, max_length=96, pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
    persona: str | None = Field(default=None, min_length=1, max_length=16384)

    @field_validator("save_id", "persona")
    @classmethod
    def bounded_text(cls, value: str | None, info):
        if value is None:
            return value
        maximum = 512 if info.field_name == "save_id" else 16384
        if not value.strip() or "\x00" in value or len(value.encode("utf-8")) > maximum:
            raise ValueError("Invalid character context text")
        return value

    @field_validator("character_id")
    @classmethod
    def normalize_builtin(cls, value: str):
        return "official.eckera" if value == "builtin.eckera" else value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    character_context: CharacterContext | None = None

    @field_validator("character_context")
    @classmethod
    def selected_persona(cls, value):
        if value is not None and value.character_id != "official.eckera" and value.persona is None:
            raise ValueError("Selected character requires persona text")
        return value

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class BusinessAdviceRequest(ChatRequest):
    capability: Literal["player_info", "transfer_analysis", "tactical_analysis", "schedule_analysis"]


class CalendarAdviceRequest(ChatRequest):
    club_uid: int = Field(ge=1, le=4294967294)
    start: str = Field(min_length=10, max_length=10)
    end: str = Field(min_length=10, max_length=10)


class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=2000)
    character_context: CharacterContext | None = None

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
        # This authenticated endpoint enforces its dedicated streaming cap itself.
        # Never preempt authentication or clear its snapshot for an unauthorized body.
        if scope.get("method") == "POST" and scope.get("path") == IMPORT_ROUTE:
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
        app.state.windows_discovery = empty_snapshot()
        app.state.windows_discovery_generation = 0
        from .ui_capture_control import UiCaptureController
        app.state.ui_capture_control = UiCaptureController(settings.bridge_private_root)
        finite_task = None
        finite_source = None
        finite_stopping = False
        if settings.windows_finite_registration is not None:
            from .windows_finite_observations import WindowsFiniteSource
            finite_source = WindowsFiniteSource(observations, settings.bridge_private_root, settings.windows_finite_registration)
            async def poll_finite():
                while not finite_stopping and not finite_source.closed:
                    try:
                        await asyncio.to_thread(finite_source.poll)
                    except Exception:
                        finite_source.invalidate('finite_observer_failed')
                        break
                    await asyncio.sleep(0.5)
            finite_task = asyncio.create_task(poll_finite())
        app.state.windows_finite_source = finite_source
        companion = None
        if enable_agent:
            companion = CompanionStore(settings.data_dir / "companion.sqlite")
            app.state.companion = companion
            app.state.agent = AgentService(settings,companion)
        _write_runtime(settings)
        try:
            yield
        finally:
            if finite_task is not None:
                finite_stopping = True
                await finite_task  # Let a bounded file read finish before closing SQLite.
                finite_source.invalidate('backend_shutdown')
            app.state.business_snapshots.invalidate()
            app.state.windows_discovery = empty_snapshot()
            observations.close()
            if companion is not None:
                app.state.agent.close()
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

    @app.get("/v1/reader/match", dependencies=[Depends(authorized)])
    def match_snapshot():
        from .match_snapshot import read_match_snapshot
        configured = os.environ.get("FOOTBALL_ASSISTANT_MATCH_FILE")
        if not configured or not Path(configured).is_absolute():
            return {"status": "unavailable", "reason": "match_file_not_configured", "snapshot": None}
        return read_match_snapshot(Path(configured))

    @app.get("/v1/reader/offseason", dependencies=[Depends(authorized)])
    async def offseason_snapshot(club_uid: int = Query(default=0, ge=0, le=4294967294), person_uid: int = Query(default=0, ge=0, le=2147483647), start: str | None = Query(default=None, max_length=10), end: str | None = Query(default=None, max_length=10)):
        from .offseason_snapshot import read_offseason, unavailable, valid_range
        if not valid_range(start, end, club_uid):
            raise HTTPException(status_code=422, detail="invalid calendar range")
        configured = os.environ.get("FOOTBALL_ASSISTANT_OFFSEASON_EXE")
        if not configured:
            return unavailable("producer_not_configured")
        if start is None:
            return await read_offseason(Path(configured), club_uid, person_uid)
        return await read_offseason(Path(configured), club_uid, person_uid, start, end)

    @app.get("/v1/status",dependencies=[Depends(authorized)])
    async def status():
        if not enable_agent:
            return {"source_status":app.state.observations.source_status(),"mode":"reader","agent_enabled":False}
        return {"source_status":app.state.observations.source_status(),"modelConfigured":settings.model_configured,"modelStatus":"unconfigured" if not settings.model_configured else "error" if app.state.agent.last_error else "ready","memory":app.state.agent.counts()}

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

    @app.get("/v1/reader/windows-discovery", dependencies=[Depends(authorized)])
    async def windows_discovery_snapshot():
        return app.state.windows_discovery

    @app.delete("/v1/reader/windows-discovery", dependencies=[Depends(authorized)])
    async def clear_windows_discovery():
        app.state.windows_discovery_generation += 1
        app.state.windows_discovery = empty_snapshot()
        return app.state.windows_discovery

    @app.post(IMPORT_ROUTE, dependencies=[Depends(authorized)])
    async def import_windows_discovery(request: Request):
        # Clear before parsing: malformed/new evidence can never preserve an older display.
        app.state.windows_discovery_generation += 1
        generation = app.state.windows_discovery_generation
        app.state.windows_discovery = empty_snapshot()
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_IMPORT_BYTES:
                raise HTTPException(413, detail={"code": "request_too_large"})
            raw.extend(chunk)
        try:
            snapshot = parse_import(bytes(raw), utc_now())
        except ValueError:
            raise HTTPException(422, detail={"code": "invalid_windows_discovery_import"}) from None
        if generation != app.state.windows_discovery_generation:
            raise HTTPException(409, detail={"code": "superseded_windows_discovery_import"})
        app.state.windows_discovery = snapshot
        return snapshot

    @app.get("/v1/reader/profile",dependencies=[Depends(authorized)])
    async def reader_profile():
        return project_display_profile(app.state.observations.reader_snapshot(0,MAX_FACTS))

    @app.post("/v1/reader/capture-profile", dependencies=[Depends(authorized)])
    async def request_capture_profile(request: Request):
        from .ui_capture_control import _unique
        from starlette.concurrency import run_in_threadpool
        try:
            raw = await request.body()
            if len(raw) > 2048:
                raise ValueError('request_too_large')
            body = CaptureProfileRequest.model_validate(json.loads(raw, object_pairs_hook=_unique))
        except (ValueError, TypeError):
            raise HTTPException(422, detail={'code': 'invalid_capture_profile'}) from None
        return await run_in_threadpool(app.state.ui_capture_control.access,
            app.state.observations.reader_snapshot(0, MAX_FACTS), body.profile)

    @app.get("/v1/reader/capture-profile", dependencies=[Depends(authorized)])
    def capture_profile_status():
        return app.state.ui_capture_control.access(app.state.observations.reader_snapshot(0, MAX_FACTS))

    @app.get("/v1/reader/schedule",dependencies=[Depends(authorized)])
    async def reader_schedule():
        # Read-only preview; no model configuration, budget or provider access.
        from football_assistant_agent.ui_advice import prepare_ui_advice
        prepared = prepare_ui_advice('schedule_analysis', app.state.observations.reader_snapshot(0, MAX_FACTS))
        projection = prepared['schedule_projection']
        return dict(status=projection['status'] if projection else 'unavailable',
                    source='ui', partial=True, production_ready=False,
                    kind=('next_match' if projection and projection.get('kind') == 'next_match' else 'schedule'),
                    schedule_complete=False, schedule_projection=projection, provenance=prepared['provenance'],
                    reasons=prepared['reasons'])

    @app.get("/v1/reader/tactics",dependencies=[Depends(authorized)])
    async def reader_tactics():
        # Authenticated, model-free local preview; provenance never goes to a provider.
        from football_assistant_agent.ui_advice import prepare_ui_advice
        prepared = prepare_ui_advice('tactical_analysis', app.state.observations.reader_snapshot(0, MAX_FACTS))
        projection = prepared['tactics_projection']
        return dict(status=projection['status'] if projection else 'unavailable',
                    source='ui', partial=True, production_ready=False,
                    tactics_projection=projection, provenance=prepared['provenance'],
                    reasons=prepared['reasons'])

    @app.get("/v1/reader/current-page-attributes",dependencies=[Depends(authorized)])
    async def reader_current_page_attributes():
        # No player binding, model configuration, budget or provider access.
        from football_assistant_agent.ui_advice import prepare_current_page_attributes
        return prepare_current_page_attributes(app.state.observations.reader_snapshot(0, MAX_FACTS))

    @app.get("/v1/reader/ui-change-preview",dependencies=[Depends(authorized)])
    async def reader_ui_change_preview():
        # Stateless UI fingerprints only; not persisted as football/game events.
        from football_assistant_agent.ui_advice import prepare_ui_change_preview
        return prepare_ui_change_preview(app.state.observations.reader_snapshot(0, MAX_FACTS))

    @app.post("/v1/observations",dependencies=[Depends(authorized)])
    async def observation(body: dict):
        from .windows_finite_observations import ADAPTER_ID as WINDOWS_FINITE_ADAPTER
        if isinstance(body.get('source'), dict) and body['source'].get('adapter_id') == WINDOWS_FINITE_ADAPTER:
            raise HTTPException(422, detail={'code': 'local_producer_only'})
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
        from .windows_finite_observations import ADAPTER_ID as WINDOWS_FINITE_ADAPTER
        stream = app.state.observations.fields(body.stream_id).get('source_status', {})
        if stream.get('adapter_id') == WINDOWS_FINITE_ADAPTER:
            raise HTTPException(422, detail={'code': 'local_producer_only'})
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
        @app.get("/v1/agent/persona", dependencies=[Depends(authorized)])
        def persona_metadata():
            from football_assistant_agent.persona import load_persona
            persona = load_persona(settings)
            app.state.agent.persona = persona
            return persona.metadata()

        @app.post("/v1/agent/business-advice",dependencies=[Depends(authorized)])
        async def business_advice(body: BusinessAdviceRequest):
            # Only the server-owned channel supplies data. Request bodies cannot
            # override provenance, readiness or provide their own snapshot.
            snapshot = app.state.business_snapshots.read()["snapshot"]
            try:
                return await app.state.agent.business_advice(body.message,body.conversation_id,body.capability,snapshot, **({"character_context": body.character_context.model_dump(exclude_none=True)} if body.character_context else {}))
            except ModelBudgetExceeded as error:
                raise HTTPException(429,detail={"code":"model_request_limit","message":str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503,detail={"code":"model_not_configured","message":str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502,detail={"code":"model_unavailable","message":str(error)}) from None

        @app.post("/v1/agent/calendar-advice", dependencies=[Depends(authorized)])
        async def calendar_advice(body: CalendarAdviceRequest):
            from .offseason_snapshot import read_offseason, valid_range, unavailable
            if not valid_range(body.start, body.end, body.club_uid):
                raise HTTPException(422, detail="invalid calendar range")
            configured = os.environ.get("FOOTBALL_ASSISTANT_OFFSEASON_EXE")
            envelope = await read_offseason(Path(configured), body.club_uid, 0, body.start, body.end) if configured else unavailable("producer_not_configured")
            try:
                return await app.state.agent.calendar_advice(body.message, body.conversation_id, envelope, body.club_uid, body.start, body.end, **({"character_context": body.character_context.model_dump(exclude_none=True)} if body.character_context else {}))
            except ModelBudgetExceeded as error:
                raise HTTPException(429, detail={"code": "model_request_limit", "message": str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503, detail={"code": "model_not_configured", "message": str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502, detail={"code": "model_unavailable", "message": str(error)}) from None

        @app.post("/v1/agent/auto-calendar-advice", dependencies=[Depends(authorized)])
        async def auto_calendar_advice(body: ChatRequest):
            from .offseason_snapshot import read_offseason
            from .calendar_selection import choose_calendar_scope
            configured = os.environ.get("FOOTBALL_ASSISTANT_OFFSEASON_EXE")
            if not configured:
                return {"status": "unavailable", "conversation_id": body.conversation_id, "reply": "当前无法读取球队候选和游戏日期。"}
            executable = Path(configured)
            initial = await read_offseason(executable, 0, 0)
            scope = choose_calendar_scope(initial, body.message)
            if scope is None:
                return {"status": "unavailable", "conversation_id": body.conversation_id, "reply": "未能唯一确认所问球队候选或当前游戏日期，请明确球队名称或俱乐部 UID。"}
            envelope = await read_offseason(executable, scope["club_uid"], 0, scope["start"], scope["end"])
            verified = choose_calendar_scope(envelope, body.message)
            if verified is None or any(verified[key] != scope[key] for key in ("manager_uid", "club_uid", "start", "end")):
                return {"status": "unavailable", "conversation_id": body.conversation_id, "reply": "球队候选或游戏日期在读取期间发生变化，请重试。"}
            try:
                result = await app.state.agent.calendar_advice(body.message, body.conversation_id, envelope, scope["club_uid"], scope["start"], scope["end"], **({"character_context": body.character_context.model_dump(exclude_none=True)} if body.character_context else {}))
                if result.get("status") == "partial":
                    result["reply"] = "按经理关联球队候选读取，尚未确认当前执教身份。\n" + result["reply"]
                    result["selection"] = {key: scope[key] for key in ("club_uid", "club_name", "selection", "start", "end")}
                return result
            except ModelBudgetExceeded as error:
                raise HTTPException(429, detail={"code": "model_request_limit", "message": str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503, detail={"code": "model_not_configured", "message": str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502, detail={"code": "model_unavailable", "message": str(error)}) from None

        @app.post("/v1/agent/ui-advice",dependencies=[Depends(authorized)])
        async def ui_advice(body: BusinessAdviceRequest):
            # Only the server-owned channel supplies data. Request bodies cannot
            # override provenance, readiness or provide their own snapshot.
            snapshot = app.state.observations.reader_snapshot(0, MAX_FACTS)
            try:
                return await app.state.agent.ui_advice(body.message,body.conversation_id,body.capability,snapshot,
                    refresh=lambda: app.state.observations.reader_snapshot(0, MAX_FACTS),
                    **({"character_context": body.character_context.model_dump(exclude_none=True)} if body.character_context else {}))
            except ModelBudgetExceeded as error:
                raise HTTPException(429,detail={"code":"model_request_limit","message":str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503,detail={"code":"model_not_configured","message":str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502,detail={"code":"model_unavailable","message":str(error)}) from None

        @app.post("/v1/chat",dependencies=[Depends(authorized)])
        async def chat(body: ChatRequest):
            try:
                return await app.state.agent.chat(body.message,body.conversation_id, **({"character_context": body.character_context.model_dump(exclude_none=True)} if body.character_context else {}))
            except ModelBudgetExceeded as error:
                raise HTTPException(429,detail={"code":"model_request_limit","message":str(error)}) from None
            except ModelNotConfigured as error:
                raise HTTPException(503,detail={"code":"model_not_configured","message":str(error)}) from None
            except ModelUnavailable as error:
                raise HTTPException(502,detail={"code":"model_unavailable","message":str(error)}) from None

        @app.get("/v1/characters/legacy-archive", dependencies=[Depends(authorized)])
        async def legacy_character_archive(request: Request):
            if request.query_params:
                raise HTTPException(422, detail={"code": "archive_scope_fixed", "message": "The legacy archive does not accept scope parameters."})
            return app.state.companion.legacy_archive()

        def memory_scope(save_id=None, character_id=None):
            try:
                supplied = None if save_id is None and character_id is None else CharacterContext(save_id=save_id, character_id=character_id).model_dump(exclude_none=True)
                context = app.state.agent.character_context(supplied)
                return {key: context[key] for key in ("save_id", "character_id")}
            except (ValueError, TypeError):
                raise HTTPException(422, detail={"code": "invalid_character_scope", "message": "Both save_id and character_id are required."}) from None

        @app.get("/v1/memories",dependencies=[Depends(authorized)])
        async def memories(save_id: str | None = Query(default=None, max_length=512), character_id: str | None = Query(default=None, max_length=96)):
            scope = memory_scope(save_id, character_id)
            return {"memories":app.state.agent.store_for_context(scope).memories(**scope), "character_context":scope}

        @app.post("/v1/memories",dependencies=[Depends(authorized)],status_code=201)
        async def create_memory(body: MemoryRequest):
            scope = memory_scope(body.character_context.save_id, body.character_context.character_id) if body.character_context else memory_scope()
            return {**app.state.agent.store_for_context(scope).add_memory(body.content, **scope), "character_context":scope}

        @app.delete("/v1/memories/{memory_id}",dependencies=[Depends(authorized)])
        async def delete_memory(memory_id: UUID, save_id: str | None = Query(default=None, max_length=512), character_id: str | None = Query(default=None, max_length=96)):
            scope = memory_scope(save_id, character_id)
            if not app.state.agent.store_for_context(scope).delete_memory(str(memory_id), **scope):
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
