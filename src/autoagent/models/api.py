from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["api", "gui_pc_web", "gui_android"]
SampleStatus = Literal[
    "queued", "running", "done", "failed", "timeout", "extraction_failed", "cancelled"
]
BatchStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in_sec: int


class Sample(BaseModel):
    id: str
    prompts: list[str] = Field(min_length=1)
    mode: Mode
    target_profile: str
    new_session: bool = True
    timeout_sec: int | None = None
    retry: int = 2
    dry_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    callback_url: str | None = None


class SampleResult(BaseModel):
    id: str
    status: SampleStatus
    prompts_sent: list[str] = Field(default_factory=list)
    responses: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    attempt_count: int = 0
    mode: Mode
    target_profile: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    logs_dir: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class BatchCreateJSON(BaseModel):
    name: str
    mode: Mode
    concurrency: int = 1
    target_profile_default: str | None = None
    samples: list[Sample]

    @model_validator(mode="after")
    def _modes_match(self) -> "BatchCreateJSON":
        for s in self.samples:
            if s.mode != self.mode:
                raise ValueError(f"sample {s.id} mode={s.mode} differs from batch mode={self.mode}")
        return self


class BatchCreatedResponse(BaseModel):
    batch_id: str


class BatchSummary(BaseModel):
    batch_id: str
    name: str
    mode: Mode
    status: BatchStatus = "queued"
    total: int
    done: int
    failed: int
    avg_duration_ms: int | None = None
    total_duration_ms: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class BatchDetail(BatchSummary):
    concurrency: int = 1
    target_profile_default: str | None = None
    samples: list[SampleResult] = Field(default_factory=list)
    seq: int = 0


class AsyncTestResponse(BaseModel):
    task_id: str
    status: Literal["queued"] = "queued"


class ScreenshotInfo(BaseModel):
    name: str
    label: str
    taken_at: datetime
    is_sensitive: bool | None = None


class DeviceInfo(BaseModel):
    serial: str
    label: str | None = None
    model: str | None = None
    android_version: str | None = None
    online: bool
    enabled: bool
    last_seen_at: datetime | None = None


class DeviceLabelUpdate(BaseModel):
    label: str | None = None


class VLMConfig(BaseModel):
    base_url: str
    model: str
    api_key_env: str = "VLM_API_KEY"
    extra_headers: dict[str, str] = Field(default_factory=dict)


class DefaultsConfig(BaseModel):
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    retry: int = 2
    concurrency: int = 1
    verbose_logs: bool = True
