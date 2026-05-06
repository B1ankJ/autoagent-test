from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

_log = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    base_url: str
    model: str
    api_key: str
    timeout_sec: float = 30.0


class ModelClient:
    """OpenAI-compatible VLM client using httpx."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config

    def call(self, messages: list[dict]) -> str:
        """Send messages to the VLM, return the raw text response.

        Synchronous by design — called from within a run_in_executor thread.
        """
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": 512,
        }
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=self._config.timeout_sec,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
