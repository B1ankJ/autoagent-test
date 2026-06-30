"""Notification rules. Currently:

  - empty_response_streak: when N samples in a row from the same device
    return an empty response, fire a DingTalk alert. Useful for catching
    "device wedged / automation lost the page" without a human watching.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from autoagent.models.api import SampleResult
from autoagent.notifications.dingtalk import send_markdown
from autoagent.storage.configs import get_config

_log = logging.getLogger(__name__)

# Per-device counter of consecutive empty responses. Process-local — resets
# on restart. That's fine: the rule is a "noisy alert" not an audit trail.
_streak: dict[str, int] = {}
_lock = asyncio.Lock()

_CONFIG_KEY = "notifications"


async def _load_config() -> dict[str, Any] | None:
    return await get_config(_CONFIG_KEY)


def _is_terminal_done(result: SampleResult) -> bool:
    return result.status == "done"


def _has_empty_response(result: SampleResult) -> bool:
    """True when the sample finished cleanly but produced no usable text."""
    if not result.responses:
        return True
    return all((not isinstance(r, str)) or not r.strip() for r in result.responses)


def _device_serial_of(result: SampleResult) -> str | None:
    s = result.metadata.get("device_serial") if result.metadata else None
    return s if isinstance(s, str) and s else None


async def on_sample_result(result: SampleResult, batch_id: str) -> None:
    """Hook called by the scheduler after each sample is persisted.

    Cheap and best-effort — any exception is swallowed; this must never
    affect batch progress.
    """
    try:
        if not _is_terminal_done(result):
            # Only count "done with no text", not failed/timeout/cancelled —
            # those have their own visible status and are not what this rule
            # is trying to surface.
            return
        serial = _device_serial_of(result)
        if not serial:
            return

        config = await _load_config()
        if not config or not config.get("enabled"):
            return
        webhook = (config.get("webhook_url") or "").strip()
        if not webhook:
            return
        threshold = int(config.get("empty_response_threshold") or 3)
        if threshold < 1:
            return

        empty = _has_empty_response(result)
        async with _lock:
            if empty:
                _streak[serial] = _streak.get(serial, 0) + 1
                count = _streak[serial]
            else:
                _streak[serial] = 0
                count = 0
            should_fire = empty and count >= threshold
            if should_fire:
                # Reset so the next streak has to build up again instead of
                # firing on every subsequent empty response.
                _streak[serial] = 0

        if should_fire:
            await _fire_empty_streak_alert(
                config=config,
                serial=serial,
                count=count,
                batch_id=batch_id,
                result=result,
            )
    except Exception:  # noqa: BLE001
        _log.exception("notification rule failed for sample %s", result.id)


async def _fire_empty_streak_alert(
    *,
    config: dict[str, Any],
    serial: str,
    count: int,
    batch_id: str,
    result: SampleResult,
) -> None:
    prompt_excerpt = ""
    if result.prompts_sent:
        first = result.prompts_sent[0] if isinstance(result.prompts_sent[0], str) else ""
        prompt_excerpt = (first[:120] + ("…" if len(first) > 120 else "")).replace("\n", " ")
    text = (
        f"### ⚠️ 设备连续 {count} 次响应为空\n\n"
        f"- **设备**: `{serial}`\n"
        f"- **Profile**: `{result.target_profile}`\n"
        f"- **最新 batch**: `{batch_id}`\n"
        f"- **最新 sample**: `{result.id}`\n"
        f"- **最新 prompt**: {prompt_excerpt or '_(空)_'}\n\n"
        "可能是设备卡死 / 自动化点到了奇怪的页面,需要人工介入排查。"
    )
    sr = await send_markdown(
        webhook_url=str(config["webhook_url"]).strip(),
        secret=(str(config.get("secret")).strip() or None) if config.get("secret") else None,
        title=f"[AutoAgent] 设备 {serial} 连续空响应",
        text=text,
        at_mobiles=list(config.get("at_mobiles") or []),
        at_all=bool(config.get("at_all")),
    )
    if sr.ok:
        _log.info(
            "dingtalk empty-streak alert sent: device=%s count=%d batch=%s",
            serial,
            count,
            batch_id,
        )
    else:
        _log.warning(
            "dingtalk empty-streak alert failed: status=%s errcode=%s errmsg=%r",
            sr.status_code,
            sr.errcode,
            sr.errmsg,
        )


def _reset_streak_for_tests() -> None:
    """Test-only helper to clear per-device state between cases."""
    _streak.clear()
