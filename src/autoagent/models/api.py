from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Mode = Literal["api", "gui_pc_web", "gui_android", "agent_pc", "agent_android"]
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
    # First prompt of the sole sample when total == 1, truncated to ~160 chars
    # so the Batches list can preview it without opening detail. Always None
    # when total != 1 — for multi-sample batches the preview wouldn't be
    # representative.
    preview_prompt: str | None = None
    # First response of the sole sample, same conditions as preview_prompt.
    # Empty string is meaningful: it means the run finished but produced no
    # text (typical when copy_button_vlm exhausts retries with no fallback).
    # The frontend uses this to flag "响应为空" anomalies on the list.
    preview_response: str | None = None


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
    # 0 disables. Positive = delete artifacts under logs_root and
    # data/profile_builder older than this many days. A background task
    # runs it every 24h + endpoints allow manual trigger / preview.
    log_retention_days: int = 7


class DingTalkNotificationConfig(BaseModel):
    """DingTalk custom-robot config + active rule thresholds."""

    enabled: bool = False
    webhook_url: str = ""
    # Optional HMAC secret. When set, requests are signed per DingTalk spec.
    secret: str = ""
    # Rule 1: alert when a single device produces N consecutive empty
    # responses (status=done, responses[0] is empty/whitespace).
    empty_response_threshold: int = 3
    # Rule 2: when the SAME response repeats N times on (device, profile),
    # ask the global VLM "is this still a normal chat page?". VLM says no
    # → alert. VLM says yes → whitelist that response so it never trips
    # again for this (device, profile) pair. Requires /config/vlm to be
    # configured; auto-skipped otherwise.
    same_response_enabled: bool = False
    same_response_threshold: int = 3
    # Optional @-mentions on alert (mobile numbers / "all").
    at_mobiles: list[str] = Field(default_factory=list)
    at_all: bool = False


class WhitelistEntry(BaseModel):
    target_profile: str
    response: str
    # Truncated for display; the comparison still uses the full response.
    response_excerpt: str
    added_at: datetime


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
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class ProfileBuilderNewSessionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: ProfileBuilderTapPoint | None = None
    reason: str | None = None
    status: Literal["idle", "ready", "unavailable", "failed"] = "idle"
    error: str | None = None


class ProfileBuilderNewSessionStep(BaseModel):
    step_index: int = Field(ge=0)
    xml_artifact: str | None = None
    screenshot_artifact: str | None = None
    recommendation_error: str | None = None
    recommended_tap: ProfileBuilderNewSessionRecommendation = Field(
        default_factory=ProfileBuilderNewSessionRecommendation
    )
    confirmed_tap: ProfileBuilderTapPoint | None = None
    source: Literal["recommended", "manual"] | None = None

    @model_validator(mode="after")
    def _confirmed_tap_and_source_match(self) -> "ProfileBuilderNewSessionStep":
        if self.source is not None and self.confirmed_tap is None:
            raise ValueError("source requires confirmed_tap")
        if self.confirmed_tap is not None and self.source is None:
            raise ValueError("confirmed_tap requires source")
        return self


class ProfileBuilderNewSessionConfigRequest(BaseModel):
    strategy: Literal["disabled", "guided_tap_sequence"]
    step_count: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def _strategy_matches_step_count(self) -> "ProfileBuilderNewSessionConfigRequest":
        if self.strategy == "disabled" and self.step_count != 0:
            raise ValueError("disabled strategy requires step_count=0")
        if self.strategy == "guided_tap_sequence" and self.step_count <= 0:
            raise ValueError("guided_tap_sequence requires step_count>0")
        return self


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

    @model_validator(mode="after")
    def _strategy_matches_steps(self) -> "ProfileBuilderDraftResponse":
        if self.new_session_strategy == "disabled" and self.new_session_steps:
            raise ValueError("disabled strategy requires no new_session_steps")
        if self.new_session_strategy == "guided_tap_sequence" and not self.new_session_steps:
            raise ValueError("guided_tap_sequence requires new_session_steps")
        return self
