"""Notification rules. Currently:

  - empty_response_streak: when N samples in a row from the same device
    return an empty response, fire a DingTalk alert. Useful for catching
    "device wedged / automation lost the page" without a human watching.
  - same_response_streak: when N samples in a row from the same (device,
    profile) return the identical response, ask a VLM whether the page
    still looks like a normal chat page before alerting.
  - anr_check: after each gui_android sample finishes (including failures/
    timeouts, unlike the two rules above), check the device's own
    ActivityManager log for an ANR in the profile's package. A hit always
    triggers the profile's init playbook (no separate opt-in — enabling
    the rule is the consent) plus a DingTalk alert.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from autoagent.anomalies import store as anomaly_store
from autoagent.config.settings import get_settings
from autoagent.devices import adb
from autoagent.models.api import SampleResult
from autoagent.notifications import blacklist, whitelist
from autoagent.notifications.dingtalk import send_markdown
from autoagent.notifications.vlm_judge import describe_judgement_error, is_normal_chat_page
from autoagent.openai_compat.chat_completions import select_effective_response
from autoagent.storage.configs import get_config, put_config

_log = logging.getLogger(__name__)

# Per-device counter of consecutive empty responses. Persisted to the kv
# config so uvicorn reload doesn't reset a mid-flight streak — that used
# to mean "N more empties needed after every restart" and, at worst, the
# streak never crossed the threshold on a chatty reload cycle.
_streak: dict[str, int] = {}


@dataclass
class _SameResponseState:
    response: str
    refs: list[tuple[str, str]] = field(default_factory=list)  # (batch_id, sample_id)


# Per (device, profile) state for the "same response" streak rule.
_same_state: dict[tuple[str, str], _SameResponseState] = {}

_lock = asyncio.Lock()
_state_loaded = False

_CONFIG_KEY = "notifications"
_STATE_KEY = "notification_state"


async def _load_config() -> dict[str, Any] | None:
    return await get_config(_CONFIG_KEY)


async def _hydrate_state_once() -> None:
    """Lazy-load persisted streak state on first rule invocation.

    We can't do this at import time (no event loop / DB yet). Callers
    hold `_lock` when they invoke us, so this is single-flight per
    process.
    """
    global _state_loaded
    if _state_loaded:
        return
    _state_loaded = True
    try:
        raw = await get_config(_STATE_KEY)
    except Exception:  # noqa: BLE001
        raw = None
    if not isinstance(raw, dict):
        return
    for serial, count in (raw.get("streak") or {}).items():
        if isinstance(serial, str) and isinstance(count, int) and count > 0:
            _streak[serial] = count
    for key, payload in (raw.get("same") or {}).items():
        # kv can't store tuple keys — we serialize as "device|profile".
        if not isinstance(key, str) or "|" not in key:
            continue
        device, profile = key.split("|", 1)
        if not isinstance(payload, dict):
            continue
        response = payload.get("response")
        refs = payload.get("refs")
        if not isinstance(response, str) or not isinstance(refs, list):
            continue
        rebuilt_refs: list[tuple[str, str]] = []
        for entry in refs:
            if (
                isinstance(entry, list)
                and len(entry) == 2
                and all(isinstance(x, str) for x in entry)
            ):
                rebuilt_refs.append((entry[0], entry[1]))
        if rebuilt_refs:
            _same_state[(device, profile)] = _SameResponseState(
                response=response, refs=rebuilt_refs
            )


async def _persist_state() -> None:
    """Write current streak dicts back to kv. Caller must hold _lock."""
    payload = {
        "streak": {s: c for s, c in _streak.items() if c > 0},
        "same": {
            f"{d}|{p}": {"response": st.response, "refs": [list(r) for r in st.refs]}
            for (d, p), st in _same_state.items()
        },
    }
    try:
        await put_config(_STATE_KEY, payload)
    except Exception:  # noqa: BLE001
        _log.exception("failed to persist notification state")


async def _safe_record_anomaly(**kwargs: Any) -> None:
    """Persist an anomaly record for a fired rule, best-effort. A DB failure
    here must never break the alert itself — same posture as the DingTalk
    send being best-effort."""
    try:
        await anomaly_store.record_anomaly(**kwargs)
    except Exception:  # noqa: BLE001
        _log.exception("failed to record anomaly for a fired notification rule")


def _is_terminal_done(result: SampleResult) -> bool:
    return result.status == "done"


# Statuses where the sample actually reached a device (as opposed to being
# cancelled or rejected before the executor ever ran) — the ANR rule cares
# about failures/timeouts too (an ANR is a plausible *cause* of a timeout),
# unlike the empty/same-response rules which only make sense for a cleanly
# completed sample.
_DEVICE_EXECUTED_STATUSES = {"done", "failed", "timeout", "extraction_failed"}


def _sample_reached_device(result: SampleResult) -> bool:
    return result.status in _DEVICE_EXECUTED_STATUSES


def _effective_response(result: SampleResult) -> str:
    """The response this system actually stands behind (see
    select_effective_response) — prefers the LLM-reviewed extraction over
    the raw one when it ran and succeeded. Both notification rules below
    must judge "empty" / "same response" against this, not raw `responses`
    directly: a profile with LLM response extraction enabled routinely has
    an empty raw extraction (nothing directly copyable in the UI) that the
    LLM review recovers real text from, which used to trip both rules as
    false positives.
    """
    return select_effective_response(result.responses, result.llm_responses, result.llm_errors)


def _has_empty_response(result: SampleResult) -> bool:
    """True when the sample finished cleanly but produced no usable text."""
    return not _effective_response(result).strip()


def _device_serial_of(result: SampleResult) -> str | None:
    s = result.metadata.get("device_serial") if result.metadata else None
    return s if isinstance(s, str) and s else None


async def on_sample_result(result: SampleResult, batch_id: str) -> None:
    """Hook called by the scheduler after each sample is persisted.

    Runs every enabled rule in sequence. Cheap and best-effort — any
    exception is swallowed; this must never affect batch progress.
    """
    try:
        if not _sample_reached_device(result):
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

        if _is_terminal_done(result):
            await _rule_empty_streak(
                config=config, webhook=webhook, serial=serial, batch_id=batch_id, result=result
            )
            await _rule_same_response_streak(
                config=config, webhook=webhook, serial=serial, batch_id=batch_id, result=result
            )
        await _rule_anr_check(
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
        await _hydrate_state_once()
        if empty:
            _streak[serial] = _streak.get(serial, 0) + 1
            count = _streak[serial]
        else:
            _streak[serial] = 0
            count = 0
        should_fire = empty and count >= threshold
        if should_fire:
            _streak[serial] = 0
        await _persist_state()

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

    # Skip empty responses entirely — the other rule already covers them
    # and we don't want to double-alert.
    if _has_empty_response(result):
        return
    response = _effective_response(result).strip()
    if not response:
        return

    profile = result.target_profile
    if not profile:
        return

    # Blacklist: a human already confirmed this exact response is a real
    # anomaly for this profile, so skip the streak wait *and* the VLM judge
    # entirely and alert on the very first occurrence. Checked before the
    # VLM-config gate below on purpose — a blacklist hit must still fire
    # even when no VLM is configured at all.
    if await blacklist.contains(profile, response):
        async with _lock:
            await _hydrate_state_once()
            _same_state.pop((serial, profile), None)
            await _persist_state()
        await _fire_same_response_alert(
            config=config,
            serial=serial,
            profile=profile,
            response=response,
            refs=[(batch_id, result.id)],
            normal=False,
            reason="命中黑名单,已跳过 VLM 判断直接告警",
        )
        return

    # VLM precondition: the streak-judge path below depends on a configured
    # global VLM. If the user hasn't set one, we can't judge "is this the
    # chat page", so skip silently rather than half-running the detection.
    vlm_cfg = await get_config("vlm")
    if not vlm_cfg or not all(vlm_cfg.get(k) for k in ("base_url", "model", "api_key")):
        return

    if await whitelist.contains(profile, response):
        # Streak resets when something whitelisted comes through.
        async with _lock:
            await _hydrate_state_once()
            _same_state.pop((serial, profile), None)
            await _persist_state()
        return

    key = (serial, profile)
    refs_to_judge: list[tuple[str, str]] | None = None
    async with _lock:
        await _hydrate_state_once()
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
        await _persist_state()

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


async def _rule_anr_check(
    *,
    config: dict[str, Any],
    webhook: str,
    serial: str,
    batch_id: str,
    result: SampleResult,
) -> None:
    if not bool(config.get("anr_check_enabled")):
        return
    # Only gui_android profiles declare a `package` — agent_android is a
    # free-roaming LLM agent with no fixed target app (and no init_action
    # to recover with), same restriction _maybe_auto_reinit already applies.
    if result.mode != "gui_android":
        return
    profile_name = result.target_profile
    if not profile_name:
        return

    try:
        from autoagent.profiles.registry import load_profile
        from autoagent.profiles.schemas import AndroidProfile

        profile = load_profile(profile_name)
    except Exception:  # noqa: BLE001
        return
    if not isinstance(profile, AndroidProfile):
        return
    package = profile.package
    if not package:
        return

    hit = await asyncio.to_thread(adb.logcat_anr_check, serial, package)
    if not hit:
        return

    await _fire_anr_alert(
        config=config,
        serial=serial,
        profile_name=profile_name,
        package=package,
        batch_id=batch_id,
        result=result,
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
        # Pick the last after_result_* in the sample dir (typically
        # after_result_1.jpg for single-prompt samples). Screenshots write as
        # JPEG now but accept legacy .png too, same as media.py's serving route.
        if sample_dir.is_dir():
            candidates = sorted(
                [*sample_dir.glob("after_result_*.jpg"), *sample_dir.glob("after_result_*.png")]
            )
            if candidates:
                shot_paths.append(candidates[-1])

    judgement = await is_normal_chat_page(
        screenshot_paths=shot_paths,
        base_url=str(vlm_cfg["base_url"]),
        model=str(vlm_cfg["model"]),
        api_key=str(vlm_cfg["api_key"]),
    )

    if judgement.error is not None:
        # Judgement couldn't complete (either the VLM call itself failed, or
        # we never had a screenshot to send it) — err on the side of
        # alerting rather than silently skipping (per user request).
        detail = describe_judgement_error(judgement.error)
        _log.warning(
            "vlm judge unavailable for %s/%s: %s (%s) — alerting anyway",
            serial,
            profile,
            judgement.error,
            detail,
        )
        await _fire_same_response_alert(
            config=config,
            serial=serial,
            profile=profile,
            response=response,
            refs=refs,
            normal=None,
            reason=f"{detail}(error={judgement.error})",
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

    # VLM confirmed this is a real anomaly, not just a coincidentally static
    # reply — blacklist it so the next occurrence skips the streak wait and
    # the VLM judge entirely and alerts immediately (symmetric with the
    # normal-judgement branch above auto-whitelisting).
    await blacklist.add(profile, response)
    await _fire_same_response_alert(
        config=config,
        serial=serial,
        profile=profile,
        response=response,
        refs=refs,
        normal=False,
        reason=judgement.reason,
    )


async def _start_reinit_job(serial: str, profile_name: str) -> bool:
    """Run the profile's init playbook on the device to reset it.

    Uses a generous device-lock hold timeout so the reinit waits for the
    in-flight sample to finish (the device is by definition busy — that's
    how the streak/ANR was detected) then resets before the next sample.
    Returns True when a reinit job was actually started.
    """
    try:
        from autoagent.profiles.registry import load_profile
        from autoagent.profiles.schemas import AndroidProfile

        profile = load_profile(profile_name)
        if not isinstance(profile, AndroidProfile):
            return False
        from autoagent.api._deps import get_device_pool
        from autoagent.devices.init_jobs import start_job

        start_job(
            profile,
            [serial],
            pool=get_device_pool(),
            # Wait out the current sample rather than fail-fast; give it up
            # to a few minutes to grab the lock before the next sample.
            hold_timeout_sec=300.0,
        )
        _log.info("auto-reinit started for %s/%s", serial, profile_name)
        return True
    except Exception:  # noqa: BLE001
        _log.exception("auto-reinit failed to start for %s/%s", serial, profile_name)
        return False


async def _maybe_auto_reinit(
    config: dict[str, Any], serial: str, profile_name: str, *, config_key: str
) -> bool:
    """If configured, run the profile's init playbook on the device to reset it.

    `config_key` picks which rule's opt-in flag gates this
    (`same_response_auto_reinit` / `empty_response_auto_reinit`) — the two
    rules are independent opt-ins, not one shared switch, since a false
    empty-response streak (raw extraction genuinely empty but LLM review
    recovered real text) and a real same-response streak aren't the same
    kind of anomaly, and a user may only trust auto-recovery for one of them.
    """
    if not bool(config.get(config_key)):
        return False
    return await _start_reinit_job(serial, profile_name)


def _sample_ref_md(app_base_url: str, batch_id: str, sample_id: str) -> str:
    """Render a (batch_id, sample_id) ref for alert markdown.

    Links to the sample's detail page (screenshots + response) when
    app_base_url is configured; otherwise plain code text, same as before —
    DingTalk custom-robot webhooks have no authenticated-image support, so
    linking to the already-logged-in web UI is the only way to hand someone
    the screenshot without leaking a token into the chat.
    """
    if app_base_url:
        url = f"{app_base_url.rstrip('/')}/batches/{batch_id}/samples/{sample_id}"
        return f"[`{batch_id}` / `{sample_id}`]({url})"
    return f"`{batch_id}` / `{sample_id}`"


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
    reinit = await _maybe_auto_reinit(
        config, serial, profile, config_key="same_response_auto_reinit"
    )
    excerpt = response.replace("\n", " ")
    if len(excerpt) > 160:
        excerpt = excerpt[:160] + "…"
    app_base_url = str(config.get("app_base_url") or "").strip()
    samples_md = "\n".join(f"  - {_sample_ref_md(app_base_url, b, s)}" for b, s in refs)
    verdict = (
        "VLM 判断当前页面**不是正常聊天页**"
        if normal is False
        else "VLM 判断**未完成**(见原因),保险起见仍然报警"
    )
    reinit_line = (
        "- **自动复位**: 已触发初始化剧本,设备将在当前任务结束后复位\n"
        if reinit
        else ""
    )
    text = (
        f"### ⚠️ 设备 {serial} 重复响应异常\n\n"
        f"- **设备**: `{serial}`\n"
        f"- **Profile**: `{profile}`\n"
        f"- **连续相同响应**: {excerpt or '_(空)_'}\n"
        f"- **判定**: {verdict}\n"
        f"- **VLM 原因**: {reason or '_(无)_'}\n"
        f"{reinit_line}"
        f"- **涉及 sample**:\n{samples_md}\n\n"
        "可能页面跳到了非聊天页面 / 设备卡住,请人工排查。"
        "如果其实是正常的,可去 Config 把这条响应加入白名单。"
    )
    ref_batch, ref_sample = refs[-1] if refs else ("", "")
    await _safe_record_anomaly(
        type="same_response",
        batch_id=ref_batch,
        sample_id=ref_sample,
        target_profile=profile,
        device_serial=serial,
        summary=f"设备 {serial} 连续重复响应",
        detail={"streak_count": len(refs), "response": response},
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
    reinit = await _maybe_auto_reinit(
        config, serial, result.target_profile, config_key="empty_response_auto_reinit"
    )
    prompt_excerpt = ""
    if result.prompts_sent:
        first = result.prompts_sent[0] if isinstance(result.prompts_sent[0], str) else ""
        prompt_excerpt = (first[:120] + ("…" if len(first) > 120 else "")).replace("\n", " ")
    app_base_url = str(config.get("app_base_url") or "").strip()
    sample_ref = _sample_ref_md(app_base_url, batch_id, result.id)
    reinit_line = (
        "- **自动复位**: 已触发初始化剧本,设备将在当前任务结束后复位\n" if reinit else ""
    )
    text = (
        f"### ⚠️ 设备连续 {count} 次响应为空\n\n"
        f"- **设备**: `{serial}`\n"
        f"- **Profile**: `{result.target_profile}`\n"
        f"- **最新样本**: {sample_ref}\n"
        f"- **最新 prompt**: {prompt_excerpt or '_(空)_'}\n"
        f"{reinit_line}\n"
        "可能是设备卡死 / 自动化点到了奇怪的页面,需要人工介入排查。"
    )
    await _safe_record_anomaly(
        type="empty_streak",
        batch_id=batch_id,
        sample_id=result.id,
        target_profile=result.target_profile,
        device_serial=serial,
        summary=f"设备 {serial} 连续 {count} 次空响应",
        detail={"streak_count": count, "response": ""},
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


async def _fire_anr_alert(
    *,
    config: dict[str, Any],
    serial: str,
    profile_name: str,
    package: str,
    batch_id: str,
    result: SampleResult,
) -> None:
    # Unlike rules 1/2, there's no separate opt-in flag here — enabling
    # anr_check_enabled at all is the consent to auto-reinit on a hit, per
    # the user's own framing of this rule ("如果发现失去响应直接触发初始化脚本").
    reinit = await _start_reinit_job(serial, profile_name)
    app_base_url = str(config.get("app_base_url") or "").strip()
    sample_ref = _sample_ref_md(app_base_url, batch_id, result.id)
    reinit_line = (
        "- **自动复位**: 已触发初始化剧本,设备将在当前任务结束后复位\n"
        if reinit
        else "- **自动复位**: 触发失败,请人工检查设备\n"
    )
    text = (
        f"### 🛑 设备 {serial} 应用无响应(ANR)\n\n"
        f"- **设备**: `{serial}`\n"
        f"- **Profile**: `{profile_name}`\n"
        f"- **包名**: `{package}`\n"
        f"- **触发样本**: {sample_ref}\n"
        f"{reinit_line}\n"
        "系统日志检测到该应用触发了 ANR(Application Not Responding),已自动重启初始化。"
    )
    await _safe_record_anomaly(
        type="anr",
        batch_id=batch_id,
        sample_id=result.id,
        target_profile=profile_name,
        device_serial=serial,
        summary=f"设备 {serial} 应用无响应 (ANR): {package}",
        detail={"package": package},
    )
    sr = await send_markdown(
        webhook_url=str(config["webhook_url"]).strip(),
        secret=(str(config.get("secret")).strip() or None) if config.get("secret") else None,
        title=f"[AutoAgent] {serial} 应用无响应(ANR)",
        text=text,
        at_mobiles=list(config.get("at_mobiles") or []),
        at_all=bool(config.get("at_all")),
    )
    if sr.ok:
        _log.info(
            "dingtalk anr alert sent: device=%s profile=%s package=%s",
            serial,
            profile_name,
            package,
        )
    else:
        _log.warning(
            "dingtalk anr alert failed: status=%s errcode=%s errmsg=%r",
            sr.status_code,
            sr.errcode,
            sr.errmsg,
        )


def _reset_streak_for_tests() -> None:
    """Test-only helper to clear per-device state between cases."""
    global _state_loaded
    _streak.clear()
    _same_state.clear()
    _state_loaded = True  # skip hydrate; tests stub get_config themselves
