"""Metadata registration models do not grant permission to invoke game members."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

AccessStatus = Literal["unknown","not_probed","needs_context","verified_readable","blocked","unsupported","error"]


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid",strict=True)
    stream_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["connected","disconnected"] = "connected"
    detail: str = Field(default="",max_length=256)


class InterfaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface_id: str = Field(min_length=1,max_length=1024)
    assembly: str = Field(min_length=1,max_length=256)
    namespace: str = Field(max_length=1024)
    type: str = Field(min_length=1,max_length=2048)
    member_kind: Literal["field","property","method","type","event","native_export"]
    name: str = Field(min_length=1,max_length=1024)
    signature: str = Field(max_length=8192)
    visibility: str = Field(max_length=64)
    is_static: bool | None
    access_status: AccessStatus
    reason: str = Field(max_length=1024)
    side_effect_policy: Literal["read_only","unknown","do_not_invoke"]
    declaring_token: str | int | None
    parameters: list[dict] = Field(default_factory=list,max_length=256)
    field_paths: list[str] = Field(default_factory=list,max_length=30)
    verification: str = Field(default="",max_length=1024)
    last_verified_at: datetime | None = None

    @model_validator(mode="after")
    def verification_is_evidence(self):
        if self.access_status=="verified_readable":
            if not self.verification.strip() or self.last_verified_at is None:
                raise ValueError("Verified readability needs explicit runtime evidence and timestamp")
            if self.side_effect_policy!="read_only":
                raise ValueError("A do-not-invoke or unknown member cannot be marked verified readable")
        if self.last_verified_at is not None and self.last_verified_at.tzinfo is None:
            raise ValueError("Verification timestamps need a timezone")
        return self


class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_id: str = Field(min_length=1,max_length=256)
    catalog_version: str = Field(min_length=1,max_length=128)
    inventory_kind: Literal["managed_metadata","native_exports"] = "managed_metadata"
    native_module: str | None = Field(default=None,max_length=1024)
    native_module_sha256: str | None = Field(default=None,pattern=r"^[0-9a-f]{64}$")
    adapter_id: str = Field(min_length=1,max_length=128)
    game_build: str = Field(min_length=1,max_length=128)
    bundle_version: str | None = Field(default=None,max_length=128)
    session_id: str | None = Field(default=None,max_length=128)
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_version: int = Field(ge=1,le=1000)
    captured_at: datetime
    synthetic: bool
    total_expected: int = Field(ge=0,le=2_000_000)
    complete: bool = False
    records: list[InterfaceRecord] = Field(max_length=100)

    @model_validator(mode="after")
    def safe_metadata(self):
        if self.captured_at.tzinfo is None:raise ValueError("Capture timestamp needs a timezone")
        if self.inventory_kind=="native_exports":
            if not self.native_module or not self.native_module_sha256:raise ValueError("Native inventory needs module provenance")
            if any(record.member_kind!="native_export" or record.access_status!="not_probed" or record.side_effect_policy!="do_not_invoke" or record.is_static is not None for record in self.records):
                raise ValueError("Native exports are inventory only, not managed or invoked members")
        elif any(record.member_kind=="native_export" for record in self.records):raise ValueError("Native exports need a separate native catalog")
        if len({record.interface_id for record in self.records})!=len(self.records):raise ValueError("Duplicate interface IDs in batch")
        if any(record.access_status=="verified_readable" for record in self.records) and not self.session_id:
            raise ValueError("Runtime verification must identify the game session")
        try:json.dumps(self.model_dump(mode="json"),allow_nan=False)
        except (ValueError,TypeError):raise ValueError("Metadata must contain finite JSON values") from None
        return self
