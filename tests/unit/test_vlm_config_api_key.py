import pytest
from pydantic import ValidationError

from autoagent.models.api import VLMConfig


def test_vlm_config_defaults_are_all_none():
    cfg = VLMConfig()
    assert cfg.base_url is None
    assert cfg.model is None
    assert cfg.api_key is None
    assert cfg.extra_headers == {}


def test_vlm_config_accepts_api_key_literal():
    cfg = VLMConfig(base_url="u", model="m", api_key="sk-xxx")
    assert cfg.api_key == "sk-xxx"


def test_vlm_config_rejects_old_api_key_env_field():
    with pytest.raises(ValidationError):
        VLMConfig(base_url="u", model="m", api_key_env="SOME_ENV")
