"""Read-only local HTTP adapter; runtime tokens never enter argv or output."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .config import ROOT

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ReaderError(Exception):
    def __init__(self,code: str,message: str):
        self.code,self.message = code,message
        super().__init__(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def default_runtime_file() -> Path:
    data = Path(os.environ.get("FOOTBALL_ASSISTANT_DATA_DIR",ROOT / "local-data"))
    return Path(os.environ.get("FOOTBALL_ASSISTANT_RUNTIME_FILE",data / "runtime.json")).expanduser().resolve()


def runtime_address(runtime: dict) -> str:
    value = runtime.get("base_url")
    try:
        url = urlsplit(value)
        valid = (url.scheme=="http" and url.hostname in ("127.0.0.1","::1") and url.port is not None
                 and not url.username and not url.password and url.path in ("", "/")
                 and not url.query and not url.fragment)
    except (ValueError,TypeError,AttributeError):
        valid = False
    if not valid:
        raise ReaderError("unsafe_runtime","Runtime must use a literal loopback HTTP address and port.")
    return value.rstrip("/")


class ReaderClient:
    def __init__(self,runtime_file: Path | None = None,*,timeout: float = 3):
        self.runtime_file = runtime_file or default_runtime_file()
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}),NoRedirect())
        self._verified = None

    def _runtime(self):
        try:
            runtime = json.loads(self.runtime_file.read_text(encoding="utf-8"))
            base = runtime_address(runtime)
            token = runtime["token"]
            if not isinstance(token,str) or not token or len(token)>4096 or any(ord(c)<33 or ord(c)>126 for c in token):
                raise ValueError("Invalid token")
            return runtime,base,token
        except ReaderError:
            raise
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            raise ReaderError("runtime_unavailable","Cannot read a valid local runtime file; start or reconnect the reader service.") from None

    def _fetch(self,base,path,token=None):
        headers = {"Accept":"application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer "+token
        request = Request(base+path,headers=headers,method="GET")
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES+1)
                if len(raw)>MAX_RESPONSE_BYTES:
                    raise ReaderError("response_too_large","Response exceeds the reader byte limit; use a smaller page.")
                payload = json.loads(raw)
                if not isinstance(payload,dict):
                    raise ValueError("Not an object")
                return payload
        except HTTPError as error:
            # Never echo error URLs, headers, response bodies or credentials.
            raise ReaderError("http_"+str(error.code),"Local service returned HTTP "+str(error.code)+".") from None
        except (URLError,TimeoutError,OSError):
            raise ReaderError("disconnected","Local service is unavailable; retry after it reconnects.") from None
        except (ValueError,TypeError):
            raise ReaderError("invalid_response","Local service did not return a JSON object.") from None

    def get(self,path: str,**query):
        allowed = ("/v1/reader/status","/v1/reader/snapshot","/v1/status","/v1/monitoring/fields",
                   "/v1/monitoring","/v1/events","/v1/interfaces/native-observers")
        if path not in allowed and not (path.startswith("/v1/events/") and path.removeprefix("/v1/events/").isdigit()):
            raise ReaderError("unsupported","Reader only supports its fixed read-only API commands.")
        for attempt in range(2):
            runtime,base,token = self._runtime()  # Re-read on every poll and after 401/token rotation.
            identity = (base,runtime.get("pid"),runtime.get("started_at"))
            if self._verified != identity:
                health = self._fetch(base,"/health")
                if health.get("service")!="football-assistant" or health.get("status")!="ok":
                    raise ReaderError("wrong_service","Loopback listener is not a compatible FootballAssistant service.")
                self._verified = identity
            try:
                return self._fetch(base,path+("?"+urlencode({k:v for k,v in query.items() if v is not None}) if query else ""),token)
            except ReaderError as error:
                if error.code=="http_401" and attempt==0:
                    self._verified = None
                    continue
                if error.code=="disconnected":
                    self._verified = None
                raise

    def status(self):
        try:
            return self.get("/v1/reader/status")
        except ReaderError as error:
            if error.code!="http_404":raise
        # The running pre-reader backend is reusable without restart or a model call.
        old = self.get("/v1/status")
        return {"service":"football-assistant","reader_api":"legacy","source_status":old["source_status"],
                "latest_event_cursor":self.get("/v1/events",after=0,limit=1)["latest_cursor"],
                "native_records":{"state":"awaiting_decoded_native_records","payload_decoded":False,
                                  "field_values_known":False,"scope":"headers_are_diagnostics_only"}}

    def snapshot(self,after=0,limit=100,event_id=None,*,raw_ui=False):
        try:
            page = self.get("/v1/reader/snapshot",after=after,limit=limit,event_id=event_id)
        except ReaderError as error:
            if error.code!="http_404":raise
            data = self.get("/v1/monitoring/fields")
            fields = data.get("fields",[])
            source = data.get("source_status") or self.get("/v1/status").get("source_status",{})
            current = source.get("event_id")
            if event_id is not None and current!=event_id:
                raise ReaderError("snapshot_changed","Snapshot changed; restart paging at zero.") from None
            cursor = after+len(fields[after:after+limit])
            page = {"reader_api":"legacy","source_status":source,"observation":None,"snapshot_event_id":current,
                    "facts":fields[after:after+limit],"facts_total":len(fields),"next_cursor":cursor,"has_more":cursor<len(fields),
                    "partial":True,"semantic_scope":"raw_adapter_observation",
                    "limitations":["Legacy API does not expose complete envelope status; each field retains its source and capture metadata.",
                                   "UI text may include hidden or cached elements and is incomplete."],
                    "native_records":{"state":"awaiting_decoded_native_records","payload_decoded":False,"field_values_known":False}}
        if raw_ui:
            page = {**page,"facts":[fact for fact in page["facts"] if fact.get("entity_kind") in ("ui_element","ui_text")],
                    "filter":"raw_ui_only","pagination_scope":"all_source_facts"}
        return page
