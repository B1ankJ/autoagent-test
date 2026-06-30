"""Notification rules. Currently:

  - empty_response_streak: when N samples in a row from the same device
    return an empty response, fire a DingTalk alert. Useful for catching
    "device wedged / automation lost the page" without a human watching.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from autoagent.config.settings import get_settings
from autoagent.models.api import SampleResult
from autoagent.notifications import whitelist
from autoagent.notifications.dingtalk import send_markdown
from autoagent.notifications.vlm_judge import is_normal_chat_page
from autoagent.storage.configs import get_config

_log = logging.getLogger(__name__)

# Per-device counter of consecutive empty responses. Process-local — resets
# on restart. That's fine: the rule is a "noisy alert" not an audit trail.
_streak: dict[str, int] = {}


@dataclass
class _SameResponseState:
    response: str
    refs: list[tuple[str, str]] = field(default_factory=list)  # (batch_id, sample_id)


# Per (device, profile) state for the "same response" streak rule.
_same_state: dict[tuple[str, str], _SameResponseState] = {}

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

    Runs every enabled rule in sequence. Cheap and best-effort — any
    exception is swallowed; this must never affect batch progress.
    """
    try:
        if not _is_terminal_done(result):
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

        await _rule_empty_streak(
            config=config, webhook=webhook, serial=serial, batch_id=batch_id, result=result
        )
        await _rule_same_response_streak(
            config=config, webhook=webhook, serial=serial, batch_id=batch_id, result=result
        )
    except Exception:  # noqa: BLE001
        _log.exception("notification rule failed for sample %s", result.id)


async def _rule_empty_streak(
    *,
    config: dict[str, Any],
    webhook: str,
    serial: str,
    batch_id: str,
    result: SampleResult,
) -> None:
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
            _streak[serial] = 0

    if should_fire:
        await _fire_empty_streak_alert(
            config=config,
            serial=serial,
            count=count,
            batch_id=batch_id,
            result=result,
        )


async def _rule_same_response_streak(
    *,
    config: dict[str, Any],
    webhook: str,
    serial: str,
    batch_id: str,
    result: SampleResult,
) -> None:
    if not bool(config.get("same_response_enabled")):
        return
    threshold = int(config.get("same_response_threshold") or 3)
    if threshold < 1:
        return
    # VLM precondition: this rule depends on a configured global VLM. If
    # the user hasn't set one, we can't judge "is this the chat page",
    # so skip silently rather than half-running the streak detection.
    vlm_cfg = await get_config("vlm")
    if not vlm_cfg or not all(vlm_cfg.get(k) for k in ("base_url", "model", "api_key")):
        return

    # Skip empty responses entirely — the other rule already covers them
    # and we don't want to double-alert.
    if _has_empty_response(result):
        return
    response = (result.responses[0] or "").strip()
    if not response:
        return

    profile = result.target_profile
    if not profile:
        return

    if await whitelist.contains(profile, response):
        # Streak resets when something whitelisted comes through.
        async with _lock:
            _same_state.pop((serial, profile), None)
        return

    key = (serial, profile)
    refs_to_judge: list[tuple[str, str]] | None = None
    async with _lock:
        state = _same_state.get(key)
        if state is None or state.response != response:
            state = _SameResponseState(response=response, refs=[(batch_id, result.id)])
        else:
            state.refs.append((batch_id, result.id))
        _same_state[key] = state
        if len(state.refs) >= threshold:
            refs_to_judge = list(state.refs[-threshold:])
            # Reset so the next round needs to rebuild — both whitelist
            # and alert decisions consume the streak.
            del _same_state[key]

    if refs_to_judge is None:
        return

    await _judge_and_act(
        config=config,
        serial=serial,
        profile=profile,
        response=response,
        refs=refs_to_judge,
        vlm_cfg=vlm_cfg,
    )


async def _judge_and_act(
    *,
    config: dict[str, Any],
    serial: str,
    profile: str,
    response: str,
    refs: list[tuple[str, str]],
    vlm_cfg: dict[str, Any],
) -> None:
    settings = get_settings()
    shot_paths = []
    for batch_id, sample_id in refs:
        sample_dir = settings.logs_root / batch_id / sample_id
        # Pick the last after_result_*.png in the sample dir (typically
        # after_result_1.png for single-prompt samples).
        if sample_dir.is_dir():
            candidates = sorted(sample_dir.glob("after_result_*.png"))
            if candidates:
                shot_paths.append(candidates[-1])

    judgement = await is_normal_chat_page(
        screenshot_paths=shot_paths,
        base_url=str(vlm_cfg["base_url"]),
        model=str(vlm_cfg["model"]),
        api_key=str(vlm_cfg["api_key"]),
    )

    if judgement.error is not None:
        # VLM unavailable — err on the side of alerting (per user request).
        _log.warning(
            "vlm judge unavailable for %s/%s: %s — alerting anyway",
            serial,
            profile,
            judgement.error,
        )
        await _fire_same_response_alert(
            config=config,
            serial=serial,
            profile=profile,
            response=response,
            refs=refs,
            normal=None,
            reason=f"VLM 不可用: {judgement.error}",
        )
        return

    if judgement.normal:
        # Page is fine, the App is just answering identically. Whitelist
        # so this exact response never trips again for this (device, profile).
        await whitelist.add(profile, response)
        _log.info(
            "same-response streak on %s/%s judged normal by VLM; whitelisted "
            "(reason=%r)",
            serial,
            profile,
            judgement.reason,
        )
        return

    await _fire_same_response_alert(
        config=config,
        serial=serial,
        profile=profile,
        response=response,
        refs=refs,
        normal=False,
        reason=judgement.reason,
    )


async def _fire_same_response_alert(
    *,
    config: dict[str, Any],
    serial: str,
    profile: str,
    response: str,
    refs: list[tuple[str, str]],
    normal: bool | None,
    reason: str | None,
) -> None:
    excerpt = response.replace("\n", " ")
    if len(excerpt) > 160:
        excerpt = excerpt[:160] + "…"
    samples_md = "\n".join(f"  - `{b}` / `{s}`" for b, s in refs)
    verdict = (
        "VLM 判断当前页面**不是正常聊天页**"
        if normal is False
        else "VLM 判断**未完成**(见原因),保险起见仍然报警"
    )
    text = (
        f"### ⚠️ 设备 {serial} 重复响应异常\n\n"
        f"- **设备**: `{serial}`\n"
        f"- **Profile**: `{profile}`\n"
        f"- **连续相同响应**: {excerpt or '_(空)_'}\n"
        f"- **判定**: {verdict}\n"
        f"- **VLM 原因**: {reason or '_(无)_'}\n"
        f"- **涉及 sample**:\n{samples_md}\n\n"
        "可能页面跳到了非聊天页面 / 设备卡住,请人工排查。"
        "如果其实是正常的,可去 Config 把这条响应加入白名单。"
    )
    sr = await send_markdown(
        webhook_url=str(config["webhook_url"]).strip(),
        secret=(str(config.get("secret")).strip() or None) if config.get("secret") else None,
        title=f"[AutoAgent] {serial} 重复响应异常",
        text=text,
        at_mobiles=list(config.get("at_mobiles") or []),
        at_all=bool(config.get("at_all")),
    )
    if sr.ok:
        _log.info("dingtalk same-response alert sent: device=%s profile=%s", serial, profile)
    else:
        _log.warning(
            "dingtalk same-response alert failed: status=%s errcode=%s errmsg=%r",
            sr.status_code,
            sr.errcode,
            sr.errmsg,
        )


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
    _same_state.clear()
