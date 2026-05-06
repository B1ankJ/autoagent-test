from __future__ import annotations

import pytest
from pydantic import ValidationError

from autoagent.profiles.schemas import AgentAndroidProfile, AgentPcProfile, parse_profile


def test_agent_pc_profile_defaults():
    p = AgentPcProfile.model_validate({
        "name": "test", "platform": "agent_pc",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "type '{prompt}'", "response_hint": "latest reply",
    })
    assert p.max_steps == 20
    assert p.new_session_task_template is None


def test_agent_pc_task_template_format():
    p = AgentPcProfile.model_validate({
        "name": "test", "platform": "agent_pc",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "type '{prompt}' and send", "response_hint": "reply",
    })
    assert p.task_template.format(prompt="hello") == "type 'hello' and send"


def test_agent_android_profile_defaults():
    p = AgentAndroidProfile.model_validate({
        "name": "test", "platform": "agent_android",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "tap '{prompt}'", "response_hint": "reply",
        "serial": "emulator-5554",
    })
    assert p.serial == "emulator-5554"
    assert p.max_steps == 30


def test_parse_profile_dispatches_agent_pc():
    p = parse_profile({
        "name": "test", "platform": "agent_pc",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "do '{prompt}'", "response_hint": "reply",
    })
    assert isinstance(p, AgentPcProfile)


def test_parse_profile_dispatches_agent_android():
    p = parse_profile({
        "name": "test", "platform": "agent_android",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "do '{prompt}'", "response_hint": "reply",
    })
    assert isinstance(p, AgentAndroidProfile)


def test_agent_pc_missing_response_hint_raises():
    with pytest.raises(ValidationError):
        AgentPcProfile.model_validate({
            "name": "test", "platform": "agent_pc",
            "base_url": "http://x", "model": "m", "api_key": "k",
            "task_template": "do '{prompt}'",
        })


def test_agent_pc_missing_task_template_raises():
    with pytest.raises(ValidationError):
        AgentPcProfile.model_validate({
            "name": "test", "platform": "agent_pc",
            "base_url": "http://x", "model": "m", "api_key": "k",
            "response_hint": "reply",
        })
