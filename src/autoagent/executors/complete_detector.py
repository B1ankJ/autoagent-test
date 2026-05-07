from __future__ import annotations

import asyncio
import hashlib
import io
import subprocess
import time
from typing import Any

from autoagent.profiles.schemas import CompleteDetection, DomStable, SendButtonReenable


async def wait_for_complete(
    page: Any,
    strategy: CompleteDetection,
    *,
    response_selector: str,
    send_button_selector: str | None = None,
    poll_interval_sec: float = 0.2,
    max_wait_sec: float | None = None,
) -> str | None:
    """Block until the chosen strategy reports completion. Raises TimeoutError on timeout."""

    if isinstance(strategy, DomStable):
        return await _dom_stable(
            page,
            response_selector=response_selector,
            stable_sec=float(strategy.stable_sec),
            max_wait_sec=float(strategy.max_wait_sec if max_wait_sec is None else max_wait_sec),
            poll_interval_sec=poll_interval_sec,
        )
    elif isinstance(strategy, SendButtonReenable):
        if send_button_selector is None:
            raise ValueError("send_button_reenable requires send_button_selector")
        await _send_button_reenable(
            page,
            selector=send_button_selector,
            max_wait_sec=float(max_wait_sec if max_wait_sec is not None else 180),
            poll_interval_sec=poll_interval_sec,
        )
        return None
    else:
        raise ValueError(f"unsupported completion strategy: {type(strategy).__name__}")


async def _collect_text(page: Any, selector: str) -> str:
    """Return innerText of ALL elements matching selector, joined by newlines.

    Falls back to the first-match behaviour of page.inner_text() if the JS
    evaluation fails for any reason.
    """
    try:
        parts: list[str] = await page.evaluate(
            "([sel]) => Array.from(document.querySelectorAll(sel))"
            ".map(el => (el.innerText || el.textContent || '').trim())"
            ".filter(t => t.length > 0)",
            [selector],
        )
        return "\n".join(parts) if parts else ""
    except Exception:
        return await page.inner_text(selector)


async def _collect_latest_text(page: Any, selector: str) -> str:
    """Return innerText of the last non-empty element matching selector."""
    try:
        parts: list[str] = await page.evaluate(
            "([sel]) => Array.from(document.querySelectorAll(sel))"
            ".map(el => (el.innerText || el.textContent || '').trim())"
            ".filter(t => t.length > 0)",
            [selector],
        )
        return parts[-1] if parts else ""
    except Exception:
        return ""


async def _dom_stable(
    page: Any,
    *,
    response_selector: str,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float,
) -> str:
    deadline = time.monotonic() + max_wait_sec
    last_text: str | None = None
    stable_since: float | None = None

    while time.monotonic() < deadline:
        text = await _collect_text(page, response_selector)
        now = time.monotonic()
        # Don't start stability timer on empty text — wait for the response to begin.
        if text and text == last_text:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_sec:
                return text
        else:
            last_text = text
            stable_since = None
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"dom_stable not reached within {max_wait_sec}s")


async def _send_button_reenable(
    page: Any,
    *,
    selector: str,
    max_wait_sec: float,
    poll_interval_sec: float,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    saw_disabled = False

    while time.monotonic() < deadline:
        disabled = await page.is_disabled(selector)
        if disabled:
            saw_disabled = True
        elif saw_disabled:
            return
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"send_button_reenable not reached within {max_wait_sec}s")


def dump_hierarchy_via_adb(device: Any) -> str:
    """Dump the UI hierarchy via adb shell uiautomator dump.

    uiautomator2's device.dump_hierarchy() can silently truncate large trees
    (RecyclerView-heavy chat UIs with hundreds of nodes). Calling adb directly
    returns the full XML that uiautomator writes to disk.
    """
    serial: str = device.serial
    dump_path = "/sdcard/window_dump.xml"
    subprocess.run(
        ["adb", "-s", serial, "shell", "uiautomator", "dump", dump_path],
        capture_output=True,
        timeout=30,
    )
    result = subprocess.run(
        ["adb", "-s", serial, "shell", "cat", dump_path],
        capture_output=True,
        timeout=30,
    )
    return result.stdout.decode("utf-8", errors="replace")


async def wait_for_ui_tree_stable(
    device: Any,
    *,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float = 0.1,
) -> str:
    deadline = time.monotonic() + max_wait_sec
    last_xml: str | None = None
    stable_since: float | None = None

    while time.monotonic() < deadline:
        xml = await asyncio.to_thread(dump_hierarchy_via_adb, device)
        now = time.monotonic()
        if xml == last_xml:
            if stable_since is None:
                if stable_sec <= 0:
                    return xml
                stable_since = now
            elif now - stable_since >= stable_sec:
                return xml
        else:
            last_xml = xml
            stable_since = None
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"ui_tree_stable not reached within {max_wait_sec}s")


async def wait_for_pixel_stable(
    device: Any,
    *,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float = 0.1,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    last_hash: str | None = None
    stable_since: float | None = None

    while time.monotonic() < deadline:
        raw = await asyncio.to_thread(capture_screenshot_bytes, device)
        digest = hashlib.md5(raw).hexdigest()
        now = time.monotonic()
        if digest == last_hash:
            if stable_since is None:
                if stable_sec <= 0:
                    return
                stable_since = now
            elif now - stable_since >= stable_sec:
                return
        else:
            last_hash = digest
            stable_since = None
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"pixel_stable not reached within {max_wait_sec}s")


def capture_screenshot_bytes(device: Any) -> bytes:
    try:
        raw = device.screenshot(format="raw")
        if isinstance(raw, bytes):
            return raw
    except Exception:
        pass

    image = device.screenshot(format="pillow")
    if isinstance(image, bytes):
        return image

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
