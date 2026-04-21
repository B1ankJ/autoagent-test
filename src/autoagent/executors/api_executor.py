from __future__ import annotations

import os
from typing import Any

import httpx

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ApiProfile


class ApiExecutor(Executor):
    """Calls any OpenAI-compatible /v1/chat/completions endpoint."""

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, ApiProfile):
            raise TypeError(f"ApiExecutor expects ApiProfile, got {type(profile).__name__}")

        api_key = os.getenv(profile.api.api_key_env)
        if not api_key:
            raise RuntimeError(f"env var {profile.api.api_key_env} is not set")

        url = profile.api.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **profile.api.extra_headers,
        }

        messages: list[dict[str, str]] = []
        responses: list[str] = []

        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
            for prompt in sample.prompts:
                if profile.multi_turn_mode == "history":
                    messages.append({"role": "user", "content": prompt})
                else:
                    messages = [{"role": "user", "content": prompt}]

                payload: dict[str, Any] = {"model": profile.api.model, "messages": messages}
                if profile.api.temperature is not None:
                    payload["temperature"] = profile.api.temperature
                if profile.api.max_tokens is not None:
                    payload["max_tokens"] = profile.api.max_tokens

                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                try:
                    text = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    raise RuntimeError(f"unexpected response shape: {data}") from e

                responses.append(text)
                if profile.multi_turn_mode == "history":
                    messages.append({"role": "assistant", "content": text})

        return responses
