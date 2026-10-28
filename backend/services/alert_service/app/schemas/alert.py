from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CanonicalSeverity = Literal["INFO", "WARNING", "HIGH", "CRITICAL"]
AlertStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]


class ProducerAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    source_event_id: str = Field(min_length=1, max_length=200)
    source_event_type: str = Field(min_length=1, max_length=100)
    source_event_version: int = Field(ge=1)
    category: str | None = Field(default=None, max_length=64)
    occurred_at: datetime
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    severity: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    deduplication_key: str | None = Field(default=None, max_length=512)
    source_status: str | None = Field(default=None, max_length=64)
    resource_refs: dict[str, Any] = Field(default_factory=dict)
    domain_data: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    @field_validator("resource_refs", "domain_data", "evidence_refs")
    @classmethod
    def metadata_is_safe(cls, value):
        prohibited = ("password", "token", "api_key", "authorization", "embedding", "face", "frame_bytes",
                      "signed_url", "credential", "secret")
        def walk(item, depth=0):
            if depth > 8:
                raise ValueError("metadata nesting exceeds 8 levels")
            if isinstance(item, dict):
                for key, child in item.items():
                    lowered = str(key).lower()
                    if any(term in lowered for term in prohibited):
                        raise ValueError("metadata contains a prohibited sensitive field")
                    walk(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    walk(child, depth + 1)
            elif isinstance(item, str):
                lowered = item.lower()
                if "://" in lowered and any(term in lowered for term in ("@", "token=", "key=", "signature=")):
                    raise ValueError("metadata must not contain credential-bearing URLs")
                if lowered.startswith("data:image/"):
                    raise ValueError("metadata must not contain inline image data")
        walk(value)
        return value

    @field_validator("source_event_id", "source_event_type", "title", "summary")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("source_event_id")
    @classmethod
    def safe_source_id(cls, value: str) -> str:
        lowered = value.lower()
        if any(secret in lowered for secret in ("password=", "token=", "api_key=", "rtsp://")):
            raise ValueError("source_event_id must not contain credentials")
        return value

    @model_validator(mode="after")
    def timestamps_are_ordered(self):
        dates = [v for v in (self.occurred_at, self.first_seen_at, self.last_seen_at) if v]
        if any(v.tzinfo is None or v.utcoffset() is None for v in dates):
            raise ValueError("timestamps must include a timezone")
        if self.first_seen_at and self.last_seen_at and self.first_seen_at > self.last_seen_at:
            raise ValueError("first_seen_at must be before last_seen_at")
        return self


class LifecycleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


def canonical_severity(use_case: str, value: str) -> str:
    key = value.strip().lower()
    if use_case == "branch_exterior":
        mapped = {"info": "INFO", "low": "WARNING", "medium": "WARNING",
                  "high": "HIGH", "critical": "CRITICAL"}.get(key)
    else:
        mapped = {"info": "INFO", "warning": "WARNING", "high": "HIGH", "critical": "CRITICAL"}.get(key)
    if not mapped:
        raise ValueError(f"unsupported severity for {use_case}")
    return mapped
