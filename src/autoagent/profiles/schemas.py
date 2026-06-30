from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

# ---- shared fragments ----


class Locator(BaseModel):
    type: Literal["resource_id", "text", "xpath", "class", "last_child_with_class"]
    value: str


class ActionStep(BaseModel):
    action: str
    # free-form kwargs; platform-specific validation happens at runtime
    model_config = {"extra": "allow"}


class DomStable(BaseModel):
    type: Literal["dom_stable"]
    stable_sec: float = 2
    max_wait_sec: float = 120


class UiTreeStable(BaseModel):
    type: Literal["ui_tree_stable"]
    stable_sec: float = 2
    max_wait_sec: float = 180


class PixelStable(BaseModel):
    type: Literal["pixel_stable"]
    stable_sec: float = 3
    max_wait_sec: float = 180


class SendButtonReenable(BaseModel):
    type: Literal["send_button_reenable"]


class FixedDelay(BaseModel):
    """Just sleep `wait_sec` after sending; no completion polling.

    Use when the target has bounded response time and any stability heuristic
    would either flap on animations (typing cursor, status-bar clock) or cost
    more than it saves. `max_wait_sec` is kept so callers that consult it for
    fallback dumps / outer timeouts have a value to read.
    """

    type: Literal["fixed_delay"]
    wait_sec: float = 8.0
    max_wait_sec: float = 60.0


CompleteDetection = Annotated[
    DomStable | UiTreeStable | PixelStable | SendButtonReenable | FixedDelay,
    Field(discriminator="type"),
]


_DEFAULT_FIXED_DELAY = FixedDelay(type="fixed_delay")


# ---- API profile ----


class ApiConfig(BaseModel):
    base_url: str
    model: str
    api_key: str
    extra_headers: dict[str, str] = Field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int | None = None


class ApiProfile(BaseModel):
    name: str
    platform: Literal["api"]
    api: ApiConfig
    multi_turn_mode: Literal["history", "single"] = "history"


# ---- Web profile ----


class WebReadyCheck(BaseModel):
    type: Literal["dom_selector"]
    selector: str
    timeout_sec: float = 5


class WebSendMethodKeyboard(BaseModel):
    type: Literal["keyboard"]
    key: str = "Enter"


class WebSendMethodClick(BaseModel):
    type: Literal["click_button"]
    selector: str


WebSendMethod = Annotated[
    WebSendMethodKeyboard | WebSendMethodClick,
    Field(discriminator="type"),
]


class WebBrowserConfig(BaseModel):
    headless: bool = False
    user_data_dir: str | None = None
    channel: str = "chromium"  # "chromium" = bundled, "chrome" = system Chrome


class WebProfile(BaseModel):
    name: str
    platform: Literal["web"]
    url: str
    browser: WebBrowserConfig = Field(default_factory=WebBrowserConfig)
    ready_check: WebReadyCheck
    recovery_path: list[ActionStep]
    input_selector: str
    send_method: WebSendMethod
    response_container_selector: str
    new_session_action: list[ActionStep] = Field(default_factory=list)
    complete_detection: CompleteDetection
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None

    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


# ---- Android profile ----


class CopyButtonVLMConfig(BaseModel):
    """VLM-based copy-button locator.

    Used when the response is rendered inside a WebView/browser whose DOM is
    not exposed to uiautomator. The current screenshot is sent to a vision
    LLM which returns the pixel coordinates of the copy button; we tap and
    read the clipboard. No XML dump is needed in this path.
    """

    # Reject unknown keys so a misindented sibling (e.g. response_vlm nested
    # under copy_button_vlm by mistake) fails loudly at save time instead of
    # being silently dropped.
    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str
    api_key: str
    prompt: str | None = None
    timeout_sec: float = 60.0
    # Cached coordinates to try before invoking the VLM. Most pages render the
    # copy button at a stable position, so tapping it directly is zero-cost.
    # Accepts either a single [x, y] or a list of [x, y] candidates that are
    # tried in order; the first whose tap yields non-empty clipboard wins.
    # All candidates miss → fall through to the VLM loop.
    default_coords: list[tuple[int, int]] | None = None
    # If the VLM loop also exhausts its retries, optionally fall through to
    # the profile's `method` (ui_tree_only / ocr_only / ui_tree_then_ocr)
    # instead of recording an empty response. Off by default because the
    # typical copy_button_vlm target (H5 / WebView) has no useful UI tree
    # for ui_tree extraction to read.
    fallback_to_method: bool = False
    # Sleep this long after the VLM gives up and before the fallback runs.
    # Useful when the page is still settling after the failed taps and the
    # immediate XML dump would catch a transient state.
    retry_wait_sec: float = 0.0

    @field_validator("default_coords", mode="before")
    @classmethod
    def _normalize_default_coords(cls, value: object) -> object:
        # Accept legacy `[x, y]` single-coord YAMLs by wrapping into a list.
        if isinstance(value, (list, tuple)) and len(value) == 2 \
                and all(isinstance(part, (int, float)) for part in value):
            return [list(value)]
        return value


class ResponseVLMConfig(BaseModel):
    """Send the post-completion screenshot to a vision LLM and ask it to
    transcribe the latest assistant reply.

    Useful when the UI tree is empty / meaningless (WebView, canvas-drawn
    chat UIs) AND `copy_button_vlm` can't find a working copy button — the
    VLM just reads the bubble directly. Slower and less reliable than a
    clipboard copy but doesn't depend on locating any interactive element.
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str
    api_key: str
    # What to ask the VLM to locate. The default works for typical chat UIs;
    # override for unusual layouts (sidebars, kanban, multi-pane).
    response_hint: str = "屏幕中最新一条 AI 助手的回复气泡"
    timeout_sec: float = 60.0
    max_attempts: int = 2
    retry_backoff_sec: float = 1.0
    # On full failure, optionally descend further down the extraction chain
    # (copy_button_text → method). Off by default so a bad VLM response
    # doesn't get silently masked by unrelated UI-tree text.
    fallback_to_method: bool = False
    # Sleep this long after the VLM gives up and before the next step in
    # the chain runs, so the page can settle.
    retry_wait_sec: float = 0.0


class AndroidResponseExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["ui_tree_only", "ocr_only", "ui_tree_then_ocr"]
    response_container_locator: Locator
    scroll_container_locator: Locator
    latest_bubble_match: Locator
    copy_button_text: str | None = None
    copy_button_vlm: CopyButtonVLMConfig | None = None
    # VLM that reads the screenshot directly and returns the response text.
    # Tried after copy_button_vlm in the priority chain:
    #   copy_button_vlm → response_vlm → copy_button_text → method
    response_vlm: ResponseVLMConfig | None = None


class AndroidProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    platform: Literal["android"]
    package: str
    activity: str | None = None
    # Legacy single-device binding. When set without `serials`, only this
    # device is acceptable (preserves the old "one profile, one phone"
    # behavior). Combined with `serials` if both are populated.
    serial: str | None = None
    # Optional device pool. When non-empty, the scheduler may acquire any
    # online device whose serial is in this list. Lets one profile fan out
    # across N phones for higher throughput.
    serials: list[str] = Field(default_factory=list)
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    input_method: Literal["auto", "adb_keyboard", "u2_send_keys"] = "auto"
    input_locator: Locator | None = None
    send_button_locator: Locator | None = None
    response_extraction: AndroidResponseExtraction
    new_session_action: list[ActionStep] = Field(default_factory=list)
    input_focus_action: list[ActionStep] = Field(default_factory=list)
    send_action: list[ActionStep] = Field(default_factory=list)
    # Runs after complete_detection succeeds and before response_extraction.
    # Use for fixed taps that reveal the full reply (e.g. a "scroll to bottom"
    # arrow). Empty (default) ⇒ no-op, downstream behaviour unchanged.
    pre_extract_action: list[ActionStep] = Field(default_factory=list)
    # Optional. Omitted ⇒ FixedDelay(wait_sec=8) — sleeps a fixed window after
    # send and starts extraction; suitable when the target has bounded latency
    # and stability heuristics would flap on animations.
    complete_detection: CompleteDetection = Field(default_factory=lambda: _DEFAULT_FIXED_DELAY)
    new_session_wait_sec: float = 3.0
    post_send_wait_sec: float = 10.0

    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


# ---- Agent PC profile ----


class CopyExtraction(BaseModel):
    """Clipboard-based response extraction for chat UIs that expose a copy button.

    When `enabled`, after the main agent loop finishes the executor runs a small
    sub-loop with `task` (instructing the model to click the copy button), then
    reads the clipboard as the response text. Falls back to VLM screenshot
    extraction if the clipboard stays empty and `fallback_to_vlm` is true.
    """

    enabled: bool = True
    task: str
    wait_ms: int = 300
    fallback_to_vlm: bool = True
    max_steps: int = 5


class AgentPcProfile(BaseModel):
    name: str
    platform: Literal["agent_pc"]
    base_url: str
    model: str
    api_key: str
    task_template: str
    new_session_task_template: str | None = None
    response_hint: str
    max_steps: int = 20
    pre_task_wait_ms: int = 0
    pre_extract_wait_ms: int = 0
    copy_extraction: CopyExtraction | None = None


# ---- Agent Android profile ----


class AgentAndroidProfile(BaseModel):
    name: str
    platform: Literal["agent_android"]
    # Legacy single-device binding (see AndroidProfile for semantics).
    serial: str | None = None
    serials: list[str] = Field(default_factory=list)
    base_url: str
    model: str
    api_key: str
    task_template: str
    new_session_task_template: str | None = None
    response_hint: str
    max_steps: int = 30


# ---- Union + parser ----

Profile = Annotated[
    ApiProfile | WebProfile | AndroidProfile | AgentPcProfile | AgentAndroidProfile,
    Field(discriminator="platform"),
]

_profile_adapter: TypeAdapter[Profile] = TypeAdapter(Profile)


def parse_profile(data: dict[str, Any]) -> Profile:
    return _profile_adapter.validate_python(data)
