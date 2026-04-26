from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    new_session: bool = False
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
    llm_responses: list[str] = Field(default_factory=list)
    llm_errors: list[str | None] = Field(default_factory=list)
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
    adb_keyboard_installed: bool | None = None
    adb_keyboard_enabled: bool | None = None
    online: bool
    enabled: bool
    last_seen_at: datetime | None = None


class DeviceLabelUpdate(BaseModel):
    label: str | None = None


class VLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)


class DefaultsConfig(BaseModel):
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    retry: int = 2
    concurrency: int = 1
    verbose_logs: bool = True


class ProfileBuilderSessionCreate(BaseModel):
    platform: Literal["android"]
    device_serial: str
    name: str


class ProfileBuilderCaptureArtifact(BaseModel):
    step: str
    package: str
    activity: str | None = None
    xml_artifact: str
    screenshot_artifact: str
    active: bool = True
    captured_at: datetime | None = None


class ProfileBuilderSessionView(BaseModel):
    id: str
    platform: Literal["android"]
    device_serial: str
    name: str
    status: Literal["draft", "ready", "validated"]
    steps: list[str]
    artifact_dir: str
    artifacts: list[str] = Field(default_factory=list)
    captures: list[ProfileBuilderCaptureArtifact] = Field(default_factory=list)


class ProfileBuilderRuntimeScreen(BaseModel):
    step: str
    label: str
    path: str
    taken_at: datetime


class ProfileBuilderRuntimeCapture(BaseModel):
    step: str
    status: Literal["pending", "running", "done", "failed"]
    screenshot: str | None = None
    updated_at: datetime | None = None


class ProfileBuilderRuntimeConnectivity(BaseModel):
    status: Literal["idle", "running", "done", "failed"] = "idle"
    result_status: SampleStatus | None = None
    result_summary: str | None = None
    screens: list[ProfileBuilderRuntimeScreen] = Field(default_factory=list)


class ProfileBuilderRuntimeView(BaseModel):
    session_id: str
    session_status: Literal["draft", "ready", "validating", "validated", "failed"]
    current_step: str
    step_state: Literal["idle", "running", "done", "failed"]
    last_error: str | None = None
    builder_adb_keyboard_active: bool = False
    builder_previous_ime: str | None = None
    captures: list[ProfileBuilderRuntimeCapture] = Field(default_factory=list)
    connectivity: ProfileBuilderRuntimeConnectivity = Field(
        default_factory=ProfileBuilderRuntimeConnectivity
    )
    recent_screens: list[ProfileBuilderRuntimeScreen] = Field(default_factory=list)


class ProfileBuilderTapPoint(BaseModel):
    x: int
    y: int


class ProfileBuilderNewSessionRecommendation(BaseModel):
    point: ProfileBuilderTapPoint | None = None
    reason: str | None = None
    status: Literal["idle", "ready", "failed"] = "idle"


class ProfileBuilderNewSessionStep(BaseModel):
    step_index: int
    xml_artifact: str | None = None
    screenshot_artifact: str | None = None
    recommended_tap: ProfileBuilderNewSessionRecommendation = Field(
        default_factory=ProfileBuilderNewSessionRecommendation
    )
    confirmed_tap: ProfileBuilderTapPoint | None = None
    source: Literal["recommended", "manual"] | None = None


class ProfileBuilderNewSessionConfigRequest(BaseModel):
    strategy: Literal["disabled", "guided_tap_sequence"]
    step_count: int = Field(default=0, ge=0, le=3)


class ProfileBuilderNewSessionConfirmRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    source: Literal["recommended", "manual"]


class ProfileBuilderDraftResponse(BaseModel):
    session: ProfileBuilderSessionView
    candidates: dict[str, Any] = Field(default_factory=dict)
    review_items: list[dict[str, Any]] = Field(default_factory=list)
    draft_profile_yaml: str
    draft_mode: Literal["rule", "smart"]
    requires_manual_review: bool = True
    applied_review_choices: dict[str, Any] = Field(default_factory=dict)
    pending_review_fields: list[str] = Field(default_factory=list)
    auto_review_source: Literal["manual", "llm"] = "manual"
    new_session_strategy: Literal["disabled", "guided_tap_sequence"] = "disabled"
    new_session_steps: list[ProfileBuilderNewSessionStep] = Field(default_factory=list)
