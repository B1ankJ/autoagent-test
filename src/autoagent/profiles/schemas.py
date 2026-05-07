from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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


CompleteDetection = Annotated[
    DomStable | UiTreeStable | PixelStable | SendButtonReenable,
    Field(discriminator="type"),
]


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


class AndroidReadyCheckTree(BaseModel):
    type: Literal["ui_tree_contains"]
    text: str | list[str]
    timeout_sec: float = 5


class AndroidResponseExtraction(BaseModel):
    method: Literal["ui_tree_only", "ocr_only", "ui_tree_then_ocr"]
    response_container_locator: Locator
    scroll_container_locator: Locator
    latest_bubble_match: Locator


class AndroidProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    platform: Literal["android"]
    package: str
    activity: str | None = None
    serial: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    input_method: Literal["auto", "adb_keyboard", "u2_send_keys"] = "auto"
    input_locator: Locator
    send_button_locator: Locator
    response_extraction: AndroidResponseExtraction
    new_session_action: list[ActionStep] = Field(default_factory=list)
    input_focus_action: list[ActionStep] = Field(default_factory=list)
    send_action: list[ActionStep] = Field(default_factory=list)
    complete_detection: CompleteDetection
    new_session_wait_sec: float = 3.0
    post_send_wait_sec: float = 10.0

    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


# ---- Agent PC profile ----


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


# ---- Agent Android profile ----


class AgentAndroidProfile(BaseModel):
    name: str
    platform: Literal["agent_android"]
    serial: str | None = None
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
