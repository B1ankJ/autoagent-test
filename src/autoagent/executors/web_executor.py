from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from autoagent.executors.action_runner import ActionRunner
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.complete_detector import (
    _collect_latest_text,
    _collect_text,
    wait_for_complete,
)
from autoagent.executors.screenshot_store import ScreenshotStore
from autoagent.executors.web_response_llm_extractor import (
    LLMExtractionResult,
    extract_web_response_via_llm,
)
from autoagent.models.api import Sample
from autoagent.profiles.schemas import WebProfile, WebSendMethodClick, WebSendMethodKeyboard

_log = logging.getLogger(__name__)


class _WebSession:
    """Holds a live browser context + page for one profile."""

    def __init__(self, context: Any, page: Any, runner: ActionRunner) -> None:
        self.context = context
        self.page = page
        self.runner = runner
        self._lock = asyncio.Lock()


class WebExecutor(Executor):
    """Playwright-backed executor for `mode=gui_pc_web`.

    Browser sessions are reused across samples when new_session=False.
    Each profile gets its own persistent context keyed by profile.name.
    """

    def __init__(self, screenshots_root: Path | None = None) -> None:
        if screenshots_root is None:
            from autoagent.config.settings import get_settings
            screenshots_root = get_settings().logs_root
        self._root = Path(screenshots_root)
        self._pw: Any = None
        self._sessions: dict[str, _WebSession] = {}

    async def _ensure_playwright(self) -> Any:
        if self._pw is None:
            self._pw = await async_playwright().start()
        return self._pw

    async def _launch_context(self, profile: WebProfile) -> Any:
        pw = await self._ensure_playwright()
        if profile.browser.user_data_dir:
            launch_kwargs = {
                "user_data_dir": profile.browser.user_data_dir,
                "channel": profile.browser.channel,
                "headless": profile.browser.headless,
            }
            try:
                context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                return context, None
            except Exception:
                cleaned = _cleanup_stale_singleton_artifacts(profile.browser.user_data_dir)
                if cleaned:
                    _log.warning(
                        "web_executor: cleaned stale singleton artifacts under %s and retrying",
                        profile.browser.user_data_dir,
                    )
                    context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                    return context, None

                fallback_channel = _persistent_channel_fallback(
                    profile.browser.channel,
                    profile.browser.user_data_dir,
                )
                if fallback_channel is None:
                    raise
                _log.warning(
                    "web_executor: persistent launch failed for channel=%s under %s;"
                    " retrying with channel=%s",
                    profile.browser.channel,
                    profile.browser.user_data_dir,
                    fallback_channel,
                )
                launch_kwargs["channel"] = fallback_channel
                context = await pw.chromium.launch_persistent_context(**launch_kwargs)
                return context, None
        browser = await pw.chromium.launch(
            channel=profile.browser.channel,
            headless=profile.browser.headless,
        )
        return await browser.new_context(), browser

    async def _get_or_create_session(
        self, profile: WebProfile, store: ScreenshotStore, verbose: bool
    ) -> _WebSession:
        """Return an existing warm session for this profile, creating one if needed."""
        key = profile.name
        if key in self._sessions:
            return self._sessions[key]

        context, _browser = await self._launch_context(profile)
        page = await context.new_page()
        runner = ActionRunner(page)

        await page.goto(profile.url, timeout=30_000)
        await page.wait_for_selector(
            profile.ready_check.selector,
            timeout=int(profile.ready_check.timeout_sec * 1000),
        )
        await self._screenshot(page, store, "ready", verbose=True)

        session = _WebSession(context, page, runner)
        self._sessions[key] = session
        return session

    async def _invalidate_session(self, profile_name: str) -> None:
        session = self._sessions.pop(profile_name, None)
        if session:
            try:
                await session.context.close()
            except Exception:
                pass

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, WebProfile):
            raise TypeError(f"WebExecutor requires WebProfile, got {type(profile).__name__}")

        batch_id = ctx.logs_dir or "ad_hoc"
        store = ScreenshotStore(root=self._root, batch_id=batch_id, sample_id=sample.id)
        ctx.logs_dir = store.logs_dir
        responses: list[str] = []

        session = await self._get_or_create_session(profile, store, ctx.verbose_logs)

        async with session._lock:
            page = session.page
            runner = session.runner

            try:
                if sample.new_session:
                    if profile.new_session_action:
                        await runner.run(list(profile.new_session_action))
                        await self._screenshot(page, store, "new_session", verbose=ctx.verbose_logs)
                    else:
                        # No new_session_action defined: navigate fresh
                        await page.goto(profile.url, timeout=30_000)
                        await page.wait_for_selector(
                            profile.ready_check.selector,
                            timeout=int(profile.ready_check.timeout_sec * 1000),
                        )
                        await self._screenshot(page, store, "ready", verbose=True)

                for idx, prompt in enumerate(sample.prompts, start=1):
                    try:
                        await page.fill(profile.input_selector, prompt, timeout=5000)
                        await self._screenshot(
                            page, store, f"filled_{idx}", verbose=ctx.verbose_logs
                        )

                        await self._send(page, profile.send_method)
                        await self._screenshot(page, store, f"sent_{idx}", verbose=ctx.verbose_logs)

                        stable_text = await wait_for_complete(
                            page,
                            profile.complete_detection,
                            response_selector=profile.response_container_selector,
                            send_button_selector=_send_button_selector(profile.send_method),
                        )
                        text = await _collect_latest_text(page, profile.response_container_selector)
                        if not text:
                            text = stable_text or await _collect_text(
                                page, profile.response_container_selector
                            )
                        responses.append(text)
                        if profile.llm_response_enabled():
                            try:
                                html = await _capture_html(
                                    page, profile.response_container_selector
                                )
                                llm_res = await extract_web_response_via_llm(
                                    prompt=prompt,
                                    html=html,
                                    base_url=profile.base_url,
                                    model=profile.model,
                                    api_key=profile.api_key,
                                )
                            except Exception:  # noqa: BLE001
                                llm_res = LLMExtractionResult(
                                    text="", error="connect", latency_ms=0
                                )
                            ctx.llm_responses.append(llm_res.text)
                            ctx.llm_errors.append(llm_res.error)
                            _log.debug(
                                "web sample %s prompt %s llm extraction: "
                                "error=%s latency_ms=%s text=%r",
                                sample.id,
                                idx,
                                llm_res.error,
                                llm_res.latency_ms,
                                llm_res.text,
                            )
                        await self._screenshot(page, store, f"done_{idx}", verbose=True)
                    except Exception:
                        await self._screenshot(page, store, f"error_{idx}", verbose=True)
                        try:
                            await runner.run(list(profile.recovery_path))
                        except Exception:
                            pass
                        # Invalidate session on error so next call gets a fresh browser
                        await self._invalidate_session(profile.name)
                        raise

                ctx.action_log = runner.log  # type: ignore[attr-defined]
                return responses

            except Exception:
                # If session was already invalidated above, that's fine
                raise

    async def _send(self, page: Any, method: Any) -> None:
        if isinstance(method, WebSendMethodKeyboard):
            await page.keyboard.press(method.key)
        elif isinstance(method, WebSendMethodClick):
            await page.click(method.selector, timeout=5000)
        else:
            raise ValueError(f"unsupported send method: {method}")

    async def _screenshot(
        self, page: Any, store: ScreenshotStore, label: str, *, verbose: bool
    ) -> None:
        if (
            not verbose
            and label not in {"ready"}
            and not label.startswith("done_")
            and not label.startswith("error_")
        ):
            return
        path = store.next_path(label)
        try:
            # JPEG q85 keeps these ~70% smaller than PNG; path ends in .jpg.
            await page.screenshot(
                path=str(path), full_page=False, type="jpeg", quality=85
            )
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        """Release all sessions and the playwright subprocess."""
        for session in list(self._sessions.values()):
            try:
                await session.context.close()
            except Exception:
                pass
        self._sessions.clear()
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None


async def _capture_html(page: Any, selector: str) -> str:
    html = await page.evaluate(
        "(sel) => { const el = document.querySelector(sel); return el ? el.outerHTML : null; }",
        selector,
    )
    if html is None:
        html = await page.evaluate("() => document.body.outerHTML")
    return html or ""


def _send_button_selector(method: Any) -> str | None:
    if isinstance(method, WebSendMethodClick):
        return method.selector
    return None


def _cleanup_stale_singleton_artifacts(user_data_dir: str) -> bool:
    root = Path(user_data_dir)
    cleaned = False
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = root / name
        if not path.is_symlink():
            continue
        try:
            target_exists = path.exists()
        except OSError:
            target_exists = False
        if target_exists:
            continue
        path.unlink(missing_ok=True)
        cleaned = True
    return cleaned


def _persistent_channel_fallback(channel: str, user_data_dir: str) -> str | None:
    normalized = user_data_dir.lower()
    if channel == "chromium" and "/google/" in normalized:
        return "chrome"
    return None
