from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

from autoagent.profiles.schemas import ActionStep

ENV_VAR_RE = re.compile(r"^\$([A-Z_][A-Z0-9_]*)$")


class ActionRunner:
    """Executes declarative action steps against a Playwright Page.

    Supported actions: goto, wait_for, click, sleep, fill, press.
    """

    def __init__(self, page: Any) -> None:
        self.page = page
        self.log: list[dict[str, Any]] = []
        self._t0 = time.monotonic()

    async def run(self, steps: list[ActionStep]) -> None:
        for step in steps:
            entry: dict[str, Any] = {
                "t_ms": int((time.monotonic() - self._t0) * 1000),
                "action": step.action,
                "selector": getattr(step, "selector", None),
                "ok": False,
                "error": None,
            }
            try:
                await self._dispatch(step)
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"{type(e).__name__}: {e}"
                self.log.append(entry)
                raise
            entry["ok"] = True
            self.log.append(entry)

    async def _dispatch(self, step: ActionStep) -> None:
        action = step.action
        if action == "goto":
            url = step.url  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 30) * 1000)
            await self.page.goto(url, timeout=timeout_ms)
        elif action == "wait_for":
            selector = step.selector  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 30) * 1000)
            await self.page.wait_for_selector(selector, timeout=timeout_ms)
        elif action == "click":
            selector = step.selector  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 5) * 1000)
            await self.page.click(selector, timeout=timeout_ms)
        elif action == "sleep":
            ms = int(getattr(step, "ms", 0))
            await asyncio.sleep(ms / 1000)
        elif action == "fill":
            selector = step.selector  # type: ignore[attr-defined]
            text = self._expand_env(step.text)  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 5) * 1000)
            await self.page.fill(selector, text, timeout=timeout_ms)
        elif action == "press":
            key = step.key  # type: ignore[attr-defined]
            await self.page.keyboard.press(key)
        else:
            raise ValueError(f"unknown action: {action}")

    @staticmethod
    def _expand_env(text: str) -> str:
        match = ENV_VAR_RE.match(text)
        if not match:
            return text
        name = match.group(1)
        value = os.environ.get(name)
        if value is None:
            raise ValueError(f"environment variable {name} is not set")
        return value
