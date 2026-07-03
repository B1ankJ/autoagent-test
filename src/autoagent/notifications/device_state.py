"""DingTalk alert on device state transitions.

Called by DeviceMonitor on each detected state change. Alerts on a device
going down (online → offline/missing) and, paired with that, on it coming
back (offline/missing → online). offline↔missing chatter is ignored.
"""
from __future__ import annotations

import logging

from autoagent.devices.expected_state import is_expected_reboot
from autoagent.notifications.dingtalk import send_markdown
from autoagent.storage.configs import get_config

_log = logging.getLogger(__name__)

_STATE_LABEL = {
    "online": "在线",
    "offline": "离线",
    "missing": "掉线(adb 完全看不到)",
}

_DOWN = ("offline", "missing")

# serial -> was the down-transition an expected init reboot. Populated when we
# actually send a down-alert; consumed on recovery so a "已恢复" message is
# only sent when we previously reported the device down (no orphan recoveries).
_down_devices: dict[str, bool] = {}


def _secret_of(config: dict) -> str | None:
    s = config.get("secret")
    return (str(s).strip() or None) if s else None


async def on_device_state_change(serial: str, prev: str, new: str) -> None:
    """Alert on down / recovery transitions. Best-effort; never raises out."""
    try:
        went_down = prev == "online" and new in _DOWN
        recovered = prev in _DOWN and new == "online"
        if not (went_down or recovered):
            return  # online→online or offline↔missing: nothing to say.

        config = await get_config("notifications")
        if not config or not config.get("enabled"):
            return
        webhook = (config.get("webhook_url") or "").strip()
        if not webhook:
            return

        if went_down:
            await _alert_down(config, webhook, serial, prev, new)
        else:
            await _alert_recovered(config, webhook, serial, prev, new)
    except Exception:  # noqa: BLE001
        _log.exception("on_device_state_change hook failed for %s (%s→%s)", serial, prev, new)


async def _alert_down(config: dict, webhook: str, serial: str, prev: str, new: str) -> None:
    # Distinguish an init-triggered reboot from a real fault: during an init
    # playbook the serial is marked expected, so send a calm note not an alarm.
    expected = is_expected_reboot(serial)
    _down_devices[serial] = expected
    if expected:
        title = f"[AutoAgent] 设备 {serial} 初始化重启中"
        text = (
            f"### ℹ️ 设备初始化重启(预期内)\n\n"
            f"- **设备**: `{serial}`\n"
            f"- **状态**: {_STATE_LABEL.get(prev, prev)} → "
            f"**{_STATE_LABEL.get(new, new)}**\n\n"
            "这是执行初始化剧本触发的重启,属于预期行为,**无需处理**。"
            "设备重启完成后会自动回到设备池。"
        )
    else:
        title = f"[AutoAgent] 设备 {serial} 掉线"
        text = (
            f"### ⚠️ 设备异常掉线\n\n"
            f"- **设备**: `{serial}`\n"
            f"- **状态**: {_STATE_LABEL.get(prev, prev)} → "
            f"**{_STATE_LABEL.get(new, new)}**\n\n"
            "该设备已从设备池摘除,此前排队 acquire 到它的样本会等超时或改用其它设备。"
            "**非初始化触发**,请检查 USB / 网络 / 设备电量。"
        )
    sr = await send_markdown(
        webhook_url=webhook,
        secret=_secret_of(config),
        title=title,
        text=text,
        at_mobiles=list(config.get("at_mobiles") or []),
        # Don't @-ping people for an expected init reboot.
        at_all=bool(config.get("at_all")) and not expected,
    )
    _log_result(sr, serial, prev, new, expected=expected)


async def _alert_recovered(config: dict, webhook: str, serial: str, prev: str, new: str) -> None:
    # Only announce recovery if we previously announced the device down —
    # otherwise a first-seen online device or a startup blip would produce a
    # confusing lone "已恢复". Whether it was an expected reboot is remembered
    # from the down transition, sidestepping the mark's clear-timing race.
    if serial not in _down_devices:
        return
    was_expected = _down_devices.pop(serial)
    if was_expected:
        title = f"[AutoAgent] 设备 {serial} 初始化重启完成"
        text = (
            f"### ✅ 初始化重启完成,设备已恢复\n\n"
            f"- **设备**: `{serial}`\n"
            f"- **状态**: {_STATE_LABEL.get(prev, prev)} → **在线**\n\n"
            "设备已重新回到设备池,可正常接收任务。"
        )
    else:
        title = f"[AutoAgent] 设备 {serial} 已恢复上线"
        text = (
            f"### ✅ 设备已恢复上线\n\n"
            f"- **设备**: `{serial}`\n"
            f"- **状态**: {_STATE_LABEL.get(prev, prev)} → **在线**\n\n"
            "此前异常掉线的设备已恢复,重新回到设备池。"
        )
    sr = await send_markdown(
        webhook_url=webhook,
        secret=_secret_of(config),
        title=title,
        text=text,
        # Recovery is good news — never @-all.
        at_mobiles=list(config.get("at_mobiles") or []),
        at_all=False,
    )
    _log_result(sr, serial, prev, new, expected=was_expected)


def _log_result(sr, serial: str, prev: str, new: str, *, expected: bool) -> None:
    if sr.ok:
        _log.info(
            "dingtalk device-state alert sent: %s %s→%s expected=%s", serial, prev, new, expected
        )
    else:
        _log.warning(
            "dingtalk device-state alert failed: serial=%s status=%s errcode=%s errmsg=%r",
            serial,
            sr.status_code,
            sr.errcode,
            sr.errmsg,
        )
