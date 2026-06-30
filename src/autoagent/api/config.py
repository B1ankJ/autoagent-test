from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.executors.llm_checker import check_llm_api
from autoagent.models.api import (
    DefaultsConfig,
    DingTalkNotificationConfig,
    VLMConfig,
    WhitelistEntry,
)
from autoagent.notifications import whitelist as wl
from autoagent.notifications.dingtalk import send_markdown
from autoagent.storage.configs import get_config, put_config

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_user)])


class _LLMTestRequest(BaseModel):
    base_url: str
    model: str
    api_key: str


@router.post("/vlm/test")
async def test_vlm_connectivity(body: _LLMTestRequest) -> dict:
    return asdict(await check_llm_api(body.base_url, body.model, body.api_key))


@router.get("/vlm", response_model=VLMConfig | None)
async def get_vlm() -> VLMConfig | None:
    v = await get_config("vlm")
    if v is None:
        return None
    return VLMConfig.model_validate(v)


@router.put("/vlm", response_model=VLMConfig)
async def put_vlm(body: VLMConfig) -> VLMConfig:
    triple = [body.base_url, body.model, body.api_key]
    if any(value is not None for value in triple):
        if not all(value is not None for value in triple):
            raise HTTPException(
                status_code=422,
                detail={"error": "vlm_config_incomplete"},
            )
        check = await check_llm_api(body.base_url, body.model, body.api_key)
        if not check.ok:
            raise HTTPException(status_code=400, detail=asdict(check))
    await put_config("vlm", body.model_dump())
    return body


@router.get("/defaults", response_model=DefaultsConfig)
async def get_defaults() -> DefaultsConfig:
    v = await get_config("defaults")
    return DefaultsConfig.model_validate(v) if v else DefaultsConfig()


@router.put("/defaults", response_model=DefaultsConfig)
async def put_defaults(body: DefaultsConfig) -> DefaultsConfig:
    await put_config("defaults", body.model_dump())
    return body


@router.get("/notifications", response_model=DingTalkNotificationConfig)
async def get_notifications() -> DingTalkNotificationConfig:
    v = await get_config("notifications")
    return (
        DingTalkNotificationConfig.model_validate(v) if v else DingTalkNotificationConfig()
    )


@router.put("/notifications", response_model=DingTalkNotificationConfig)
async def put_notifications(body: DingTalkNotificationConfig) -> DingTalkNotificationConfig:
    if body.enabled and not body.webhook_url.strip():
        raise HTTPException(
            status_code=422,
            detail="webhook_url is required when enabled=true",
        )
    if body.empty_response_threshold < 1:
        raise HTTPException(
            status_code=422,
            detail="empty_response_threshold must be ≥ 1",
        )
    await put_config("notifications", body.model_dump())
    return body


@router.get("/notifications/whitelist", response_model=list[WhitelistEntry])
async def list_whitelist() -> list[WhitelistEntry]:
    raw = await wl.load_all()
    out: list[WhitelistEntry] = []
    for entry in raw:
        try:
            out.append(WhitelistEntry.model_validate(entry))
        except Exception:  # noqa: BLE001
            continue
    return out


class _WhitelistRemove(BaseModel):
    target_profile: str
    response: str


@router.post("/notifications/whitelist/remove")
async def remove_whitelist(body: _WhitelistRemove) -> dict:
    removed = await wl.remove(body.target_profile, body.response)
    if not removed:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"ok": True}


@router.post("/notifications/test")
async def test_notifications(body: DingTalkNotificationConfig) -> dict:
    """Send a test DingTalk message using the supplied (unsaved) config."""
    if not body.webhook_url.strip():
        raise HTTPException(status_code=422, detail="webhook_url is required")
    sr = await send_markdown(
        webhook_url=body.webhook_url.strip(),
        secret=body.secret.strip() or None,
        title="[AutoAgent] 通知配置测试",
        text=(
            "### ✅ 测试通知\n\n"
            "这条消息来自 AutoAgent 通知配置页面。如果你收到了它,说明 webhook "
            "和签名都对了。"
        ),
        at_mobiles=list(body.at_mobiles),
        at_all=body.at_all,
    )
    return asdict(sr)
