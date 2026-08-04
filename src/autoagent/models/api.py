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
    # Opt-in multi-turn-across-requests support for gui_android/agent_android:
    # when set, DevicePool pins this caller-chosen id to whichever device
    # new_session=True lands on, and new_session=False requests with the
    # same session_id are forced onto that exact device instead of "any
    # free device in the profile's pool" — so a conversation split across
    # separate /tests/sync or /v1/chat/completions calls stays on one
    # physical device. None (the default) leaves device selection entirely
    # unaffected — see devices/pool.py.
    session_id: str | None = None
    # Signals "this conversation is over" instead of sending another turn:
    # frees session_id's device reservation immediately (rather than
    # waiting out the inactivity TTL) and skips execution entirely — the
    # scheduler never resolves a profile, acquires a device, or runs the
    # prompts. `prompts` is still required by the schema but is ignored
    # when this is set; send whatever placeholder is convenient. No-op
    # (still succeeds) if session_id is unset or already released/expired.
    end_session: bool = False


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
    # Copied verbatim from the originating Sample.session_id so a multi-turn
    # conversation split across separate requests (see Sample.session_id)
    # can be reconstructed later by querying every Sample row that shares
    # one — None for samples that never set it (the overwhelming majority).
    session_id: str | None = None
    # Copied verbatim from the originating Sample.new_session — without
    # this, SampleDetail's "New session" field always read the request-only
    # Sample.new_session (never populated on a result) and displayed False
    # unconditionally regardless of what was actually submitted.
    new_session: bool = False


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
    # Distinct target profiles + device serials used across the batch's
    # samples, for at-a-glance display. Aggregated in one query per page.
    profiles: list[str] = Field(default_factory=list)
    devices: list[str] = Field(default_factory=list)
    # The sole sample's session_id when total == 1, same conditions as
    # preview_prompt — lets the Batches list flag a batch as one turn of a
    # multi-turn conversation and link to the reconstructed thread.
    session_id: str | None = None
    # True when the sole sample (total == 1) is a Sample.end_session=true
    # no-op — it released a device-session pin and never sent a real turn,
    # so it's not a real conversation/response, just conversation-teardown
    # bookkeeping. Lets the Batches list tag it distinctly instead of it
    # looking like an ordinary (empty-response) batch.
    is_end_session: bool = False
    # True when total == 1 and this batch's avg_duration_ms is far (see
    # storage/batches.py::ANOMALY_HIGH_RATIO/ANOMALY_LOW_RATIO) from its
    # profile's historical average across every sample ever run under it —
    # lets the Batches list highlight a suspiciously slow/fast run.
    is_duration_anomaly: bool = False


class BatchDetail(BatchSummary):
    concurrency: int = 1
    target_profile_default: str | None = None
    samples: list[SampleResult] = Field(default_factory=list)
    seq: int = 0


class SessionTurn(BaseModel):
    """One turn of a session_id-linked multi-turn conversation.

    Reconstructed by querying every Sample row that shares one session_id
    (see storage/samples.py::list_samples_by_session_id) — such a
    conversation is typically a sequence of separate single-sample batches,
    not one batch, so this deliberately isn't scoped to a batch_id.
    """

    batch_id: str
    sample_id: str
    status: SampleStatus
    prompt: str | None = None
    response: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


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


class DeviceSessionInfo(BaseModel):
    """One active multi-turn Sample.session_id -> device pin (DevicePool)."""

    session_id: str
    serial: str
    # Remaining seconds until the pin self-heals via TTL if never released
    # explicitly. Computed from a monotonic clock at read time, not an
    # absolute timestamp (monotonic has no fixed epoch to serialize).
    expires_in_sec: int


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
    # 0 = no archive (batches deleted directly). Positive = before a batch
    # is pruned, zip its results + logs + a DB snapshot into
    # data/archive/<batch>.zip; the archives themselves are deleted after
    # this many days (should be >= log_retention_days to be useful).
    archive_retention_days: int = 0
    # Self-update: when true, the /system/update endpoints can git-pull
    # origin/main and restart the service in place. This is RCE-by-design
    # (whoever controls the remote controls the box), so it stays opt-in.
    self_update_enabled: bool = False
    # 0 disables. Positive = a background task periodically zips the SQLite
    # DB (via sqlite's online backup API, safe under WAL) + data/profiles
    # into data/backups/<timestamp>.zip, keeping backups for this many
    # days. Deliberately narrow scope: results JSONL/logs/archived batches
    # already have their own retention+archive story (log_retention_days /
    # archive_retention_days above) — this covers just the small, critical,
    # hard-to-regenerate core (queryable DB state + hand-authored profile
    # YAML).
    backup_retention_days: int = 14
    # How often the backup job runs, independent of backup_retention_days.
    backup_interval_hours: int = 24


class DingTalkNotificationConfig(BaseModel):
    """DingTalk custom-robot config + active rule thresholds."""

    enabled: bool = False
    webhook_url: str = ""
    # Optional HMAC secret. When set, requests are signed per DingTalk spec.
    secret: str = ""
    # Rule 1: alert when a single device produces N consecutive empty
    # responses (status=done, responses[0] is empty/whitespace).
    empty_response_threshold: int = 3
    # When Rule 1 fires, also auto-run the profile's init playbook on that
    # device to reset it — same mechanics as same_response_auto_reinit
    # below, but its own independent opt-in: an empty-response streak and a
    # same-response streak aren't the same kind of anomaly, so a user may
    # only trust auto-recovery for one of them. Off by default.
    empty_response_auto_reinit: bool = False
    # Rule 2: when the SAME response repeats N times on (device, profile),
    # ask the global VLM "is this still a normal chat page?". VLM says no
    # → alert. VLM says yes → whitelist that response so it never trips
    # again for this (device, profile) pair. Requires /config/vlm to be
    # configured; auto-skipped otherwise.
    same_response_enabled: bool = False
    same_response_threshold: int = 3
    # When Rule 2 fires an abnormal-page alert, also auto-run the profile's
    # init playbook on that device to reset it. The init waits for the
    # in-flight sample to finish (it shares the scheduler's device lock)
    # then reinitializes before the next sample runs. Off by default.
    same_response_auto_reinit: bool = False
    # Rule 3: after each gui_android sample finishes (done/failed/timeout/
    # extraction_failed — unlike rules 1/2, this checks failures too, since
    # an ANR is a plausible *cause* of a timeout), check the device's
    # ActivityManager log for an ANR (Application Not Responding) in the
    # profile's package since the last check. Unlike rules 1/2's separate
    # opt-in *_auto_reinit flags, enabling this rule at all is the consent —
    # a hit always triggers the profile's init playbook immediately, no
    # extra toggle, since an ANR'd app can't be recovered by anything short
    # of a restart. Off by default like rule 2.
    anr_check_enabled: bool = False
    # Periodic anomaly digest: every N hours, DingTalk a summary of anomalies
    # created since the last digest. 0 = off. Reuses enabled/webhook_url/secret.
    digest_interval_hours: int = 0
    # Optional @-mentions on alert (mobile numbers / "all").
    at_mobiles: list[str] = Field(default_factory=list)
    at_all: bool = False
    # Base URL of this AutoAgent deployment (e.g. https://autoagent.example.com),
    # used to turn the "涉及 sample" references in alerts into clickable links
    # to that sample's detail page (which has the screenshots). DingTalk custom
    # -robot webhooks can't embed authenticated images directly — the client
    # fetches image URLs itself with no way to carry a token — so we link out
    # to the already-authenticated web UI instead. Empty = plain text refs,
    # same as before.
    app_base_url: str = ""


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


class AnomalyRecord(BaseModel):
    id: int
    type: str
    batch_id: str
    sample_id: str
    target_profile: str
    device_serial: str | None = None
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    created_at: datetime | None = None


class AnomalyListResponse(BaseModel):
    items: list[AnomalyRecord]
    total: int


class ProfileHealth(BaseModel):
    name: str
    platform: str
    status: str  # green | yellow | red | nodata
    success_rate: float | None = None
    total_runs: int = 0
    avg_duration_ms: float | None = None
    unacked_anomalies: int = 0
    devices_online: int | None = None
    devices_total: int | None = None
    # Bound device serials (android/agent_android only; empty otherwise) — lets
    # the dashboard open the profile's device-screen grid scoped to this pool.
    serials: list[str] = Field(default_factory=list)


class DailyPoint(BaseModel):
    date: str  # YYYY-MM-DD
    success_rate: float | None = None
    avg_duration_ms: float | None = None
    sample_count: int = 0
