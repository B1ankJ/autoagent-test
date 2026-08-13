import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.executors.llm_checker import check_llm_api
from autoagent.maintenance.backup import (
    delete_backup,
    list_backups,
    resolve_backup_path,
    run_backup,
)
from autoagent.maintenance.batch_retention import prune_old_batches
from autoagent.maintenance.cleanup import run_cleanup
from autoagent.models.api import (
    DefaultsConfig,
    DingTalkNotificationConfig,
    VLMConfig,
    WhitelistEntry,
)
from autoagent.notifications import blacklist as bl
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


async def _current_retention() -> tuple[int, int]:
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    return cfg.log_retention_days, cfg.archive_retention_days


@router.get("/logs/preview")
async def preview_logs_cleanup(days: int | None = None) -> dict:
    """Report what cleanup would delete without touching disk / DB."""
    settings = get_settings()
    saved_days, archive_days = await _current_retention()
    retention = days if days is not None else saved_days
    if retention <= 0:
        return {
            "files_deleted": 0,
            "dirs_deleted": 0,
            "bytes_freed": 0,
            "batches_pruned": 0,
            "batches_archived": 0,
            "retention_days": 0,
        }
    report = await asyncio.to_thread(
        run_cleanup,
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=retention,
        dry_run=True,
    )
    batch_report = await prune_old_batches(
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=retention,
        archive_retention_days=archive_days,
        dry_run=True,
    )
    return {
        "files_deleted": report.files_deleted,
        "dirs_deleted": report.dirs_deleted,
        "bytes_freed": report.bytes_freed,
        "batches_pruned": batch_report.batches,
        "batches_archived": batch_report.archived,
        "retention_days": retention,
    }


@router.post("/logs/cleanup")
async def run_logs_cleanup(days: int | None = None) -> dict:
    settings = get_settings()
    saved_days, archive_days = await _current_retention()
    retention = days if days is not None else saved_days
    if retention <= 0:
        raise HTTPException(
            status_code=400, detail="log_retention_days is 0 (disabled); pass ?days=N to force"
        )
    batch_report = await prune_old_batches(
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=retention,
        archive_retention_days=archive_days,
        dry_run=False,
    )
    report = await asyncio.to_thread(
        run_cleanup,
        logs_root=settings.logs_root,
        data_root=settings.data_root,
        retention_days=retention,
        dry_run=False,
    )
    return {
        "files_deleted": report.files_deleted,
        "dirs_deleted": report.dirs_deleted,
        "bytes_freed": report.bytes_freed,
        "batches_pruned": batch_report.batches,
        "batches_archived": batch_report.archived,
        "retention_days": retention,
    }


@router.get("/backup/list")
async def get_backup_list() -> list[dict]:
    return list_backups(get_settings().data_root)


@router.post("/backup/run")
async def run_backup_now() -> dict:
    """Write a backup now regardless of whether the scheduled job is enabled.

    Pruning still respects the saved backup_retention_days (0 = keep
    forever) — manually triggering a backup shouldn't surprise-delete old
    ones a user deliberately chose to keep.
    """
    v = await get_config("defaults")
    cfg = DefaultsConfig.model_validate(v) if v else DefaultsConfig()
    report = await run_backup(
        data_root=get_settings().data_root,
        retention_days=cfg.backup_retention_days,
        max_count=cfg.backup_max_count,
    )
    return {
        "path": report.path,
        "bytes_written": report.bytes_written,
        "pruned": report.pruned,
    }


@router.get("/backup/download/{name}")
async def download_backup(name: str) -> FileResponse:
    path = resolve_backup_path(get_settings().data_root, name)
    if path is None:
        raise HTTPException(status_code=404, detail="backup not found")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.delete("/backup/{name}")
async def delete_backup_route(name: str) -> dict:
    ok = delete_backup(get_settings().data_root, name)
    if not ok:
        raise HTTPException(status_code=404, detail="backup not found")
    return {"deleted": True}


class _ResponseListAdd(BaseModel):
    target_profile: str
    response: str


class _ResponseListRemove(BaseModel):
    target_profile: str
    response: str


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


@router.post("/notifications/whitelist/add")
async def add_whitelist(body: _ResponseListAdd) -> dict:
    await wl.add(body.target_profile, body.response)
    return {"ok": True}


@router.post("/notifications/whitelist/remove")
async def remove_whitelist(body: _ResponseListRemove) -> dict:
    removed = await wl.remove(body.target_profile, body.response)
    if not removed:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"ok": True}


@router.get("/notifications/blacklist", response_model=list[WhitelistEntry])
async def list_blacklist() -> list[WhitelistEntry]:
    raw = await bl.load_all()
    out: list[WhitelistEntry] = []
    for entry in raw:
        try:
            out.append(WhitelistEntry.model_validate(entry))
        except Exception:  # noqa: BLE001
            continue
    return out


@router.post("/notifications/blacklist/add")
async def add_blacklist(body: _ResponseListAdd) -> dict:
    await bl.add(body.target_profile, body.response)
    return {"ok": True}


@router.post("/notifications/blacklist/remove")
async def remove_blacklist(body: _ResponseListRemove) -> dict:
    removed = await bl.remove(body.target_profile, body.response)
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
