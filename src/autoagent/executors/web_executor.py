from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from autoagent.executors.action_runner import ActionRunner
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.complete_detector import wait_for_complete
from autoagent.executors.screenshot_store import ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import WebProfile, WebSendMethodClick, WebSendMethodKeyboard


class WebExecutor(Executor):
    """Playwright-backed executor for `mode=gui_pc_web`."""

    def __init__(self, screenshots_root: Path | None = None) -> None:
        self._root = Path(screenshots_root) if screenshots_root else Path("./data/logs")

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, WebProfile):
            raise TypeError(f"WebExecutor requires WebProfile, got {type(profile).__name__}")

        batch_id = ctx.logs_dir or "ad_hoc"
        store = ScreenshotStore(root=self._root, batch_id=batch_id, sample_id=sample.id)
        ctx.logs_dir = store.logs_dir
        responses: list[str] = []

        async with async_playwright() as pw:
            if profile.browser.user_data_dir:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile.browser.user_data_dir,
                    channel="chromium",
                    headless=profile.browser.headless,
                )
                browser = None
            else:
                browser = await pw.chromium.launch(
                    channel="chromium", headless=profile.browser.headless
                )
                context = await browser.new_context()

            try:
                page = await context.new_page()
                runner = ActionRunner(page)

                await page.goto(profile.url, timeout=30_000)
                await page.wait_for_selector(
                    profile.ready_check.selector,
                    timeout=int(profile.ready_check.timeout_sec * 1000),
                )
                await self._screenshot(page, store, "ready", verbose=True)

                if sample.new_session and profile.new_session_action:
                    await runner.run(list(profile.new_session_action))
                    await self._screenshot(page, store, "new_session", verbose=ctx.verbose_logs)

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
                        text = stable_text
                        if text is None:
                            text = await page.inner_text(profile.response_container_selector)
                        responses.append(text)
                        await self._screenshot(page, store, f"done_{idx}", verbose=True)
                    except Exception:
                        await self._screenshot(page, store, f"error_{idx}", verbose=True)
                        try:
                            await runner.run(list(profile.recovery_path))
                        except Exception:
                            pass
                        raise

                ctx.action_log = runner.log  # type: ignore[attr-defined]
                return responses
            finally:
                if browser is not None:
                    await browser.close()
                else:
                    await context.close()

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
            await page.screenshot(path=str(path), full_page=False)
        except Exception:  # noqa: BLE001
            pass


def _send_button_selector(method: Any) -> str | None:
    if isinstance(method, WebSendMethodClick):
        return method.selector
    return None
