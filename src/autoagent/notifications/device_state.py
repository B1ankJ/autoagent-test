"""DingTalk alert when a device transitions to offline / missing state.

Called by DeviceMonitor on each detected state change. Only fires for
online → offline / online → missing transitions (the ones worth waking
someone up); ignores the reverse and any offline↔missing chatter.
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


async def on_device_state_change(serial: str, prev: str, new: str) -> None:
    """Fire a DingTalk alert on device going offline / missing.

    Best-effort — any error is logged and swallowed; the device monitor
    must never stop because notification delivery hiccuped.
    """
    try:
        # Only alert on "device went bad", not recoveries.
        if prev != "online" or new == "online":
            return
        config = await get_config("notifications")
        if not config or not config.get("enabled"):
            return
        webhook = (config.get("webhook_url") or "").strip()
        if not webhook:
            return

        # Distinguish an init-triggered reboot from a real fault. During an
        # init playbook the serial is marked expected; that transition is
        # planned, so send a calm informational message instead of an alarm.
        expected = is_expected_reboot(serial)
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
            secret=(
                (str(config.get("secret")).strip() or None) if config.get("secret") else None
            ),
            title=title,
            text=text,
            at_mobiles=list(config.get("at_mobiles") or []),
            # Don't @-ping people for an expected init reboot.
            at_all=bool(config.get("at_all")) and not expected,
        )
        if sr.ok:
            _log.info(
                "dingtalk device-state alert sent: %s %s→%s expected=%s",
                serial,
                prev,
                new,
                expected,
            )
        else:
            _log.warning(
                "dingtalk device-state alert failed: serial=%s status=%s errcode=%s errmsg=%r",
                serial,
                sr.status_code,
                sr.errcode,
                sr.errmsg,
            )
    except Exception:  # noqa: BLE001
        _log.exception("on_device_state_change hook failed for %s (%s→%s)", serial, prev, new)
