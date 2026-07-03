from __future__ import annotations

import pytest

from autoagent.devices import expected_state
from autoagent.notifications import device_state


@pytest.fixture(autouse=True)
def _reset():
    expected_state._expected_reboot.clear()


def _stub_config(value):
    async def _get(_key):
        return value

    return _get


def _capture_send(sink):
    async def _send(**kwargs):
        sink.append(kwargs)

        class _R:
            ok = True
            status_code = 200
            errcode = 0
            errmsg = "ok"

        return _R()

    return _send


_CFG = {"enabled": True, "webhook_url": "https://x", "at_all": True}


async def test_unexpected_offline_is_alarming(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(device_state, "get_config", _stub_config(_CFG))
    monkeypatch.setattr(device_state, "send_markdown", _capture_send(sent))

    await device_state.on_device_state_change("dev-A", "online", "offline")
    assert len(sent) == 1
    assert "异常掉线" in sent[0]["text"]
    assert "掉线" in sent[0]["title"]
    # Real fault @-alls if configured.
    assert sent[0]["at_all"] is True


async def test_expected_reboot_is_calm(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(device_state, "get_config", _stub_config(_CFG))
    monkeypatch.setattr(device_state, "send_markdown", _capture_send(sent))

    expected_state.mark_expected_reboot("dev-A", ttl_sec=120)
    await device_state.on_device_state_change("dev-A", "online", "missing")
    assert len(sent) == 1
    assert "初始化重启" in sent[0]["text"]
    assert "初始化重启" in sent[0]["title"]
    assert "无需处理" in sent[0]["text"]
    # Never @-all on an expected reboot.
    assert sent[0]["at_all"] is False


async def test_recovery_does_not_alert(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(device_state, "get_config", _stub_config(_CFG))
    monkeypatch.setattr(device_state, "send_markdown", _capture_send(sent))

    await device_state.on_device_state_change("dev-A", "offline", "online")
    assert sent == []


def test_expected_reboot_expires():
    expected_state.mark_expected_reboot("dev-A", ttl_sec=-1)  # already expired
    assert expected_state.is_expected_reboot("dev-A") is False
