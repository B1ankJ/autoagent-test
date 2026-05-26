from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import subprocess
import time
from typing import Any

from autoagent.profiles.schemas import CompleteDetection, DomStable, SendButtonReenable

_log = logging.getLogger(__name__)


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


_DUMP_RETRIES = 3
_DUMP_RETRY_DELAY_SEC = 1.0


def ensure_screen_awake(serial: str) -> None:
    """Wake the screen and dismiss the swipe lock screen if needed.

    Sends KEYCODE_POWER when the device is asleep, then swipes up to dismiss
    a swipe-only lock screen. PIN/pattern lock screens are not handled here —
    the device should be set to swipe-only unlock for automated testing.
    """
    power = subprocess.run(
        ["adb", "-s", serial, "shell", "dumpsys", "power"],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    asleep = "mWakefulness=Asleep" in power or "mWakefulness=Dozing" in power
    if asleep:
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "keyevent", "26"],
            capture_output=True,
            timeout=10,
        )
        time.sleep(1.0)

    window = subprocess.run(
        ["adb", "-s", serial, "shell", "dumpsys", "window"],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    if "mDreamingLockscreen=true" in window:
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "swipe", "540", "1800", "540", "900"],
            capture_output=True,
            timeout=10,
        )
        time.sleep(0.5)


def dump_hierarchy_via_adb(device: Any) -> str:
    """Dump the UI hierarchy via adb shell uiautomator dump.

    uiautomator2's device.dump_hierarchy() can silently truncate large trees
    (RecyclerView-heavy chat UIs with hundreds of nodes). Calling adb directly
    returns the full XML that uiautomator writes to disk.
    """
    serial: str = device.serial
    # /data/local/tmp is always writable by the shell uid and the uiautomator
    # CLI uid; /sdcard depends on scoped-storage policy on Android 11+.
    dump_path = "/data/local/tmp/window_dump.xml"

    # Always free the UiAutomation slot before dumping. The executor calls
    # uiautomator2 (tap/screenshot/set_text) all over the place, so the
    # instrumentation host is essentially always attached by the time we get
    # here. Doing this unconditionally is cheaper than letting attempt 1 fail.
    _release_uiautomation_slot(serial)

    last_stderr = ""
    for attempt in range(_DUMP_RETRIES):
        # Remove stale file so a failed dump doesn't return old content.
        subprocess.run(
            ["adb", "-s", serial, "shell", "rm", "-f", dump_path],
            capture_output=True,
            timeout=10,
        )
        dump_proc = subprocess.run(
            ["adb", "-s", serial, "shell", "uiautomator", "dump", dump_path],
            capture_output=True,
            timeout=30,
        )
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "cat", dump_path],
            capture_output=True,
            timeout=30,
        )
        xml = result.stdout.decode("utf-8", errors="replace").strip()
        if xml.startswith("<?xml") and "</hierarchy>" in xml:
            return xml
        # Full diagnostic snapshot so we can root-cause without re-running.
        ls_proc = subprocess.run(
            ["adb", "-s", serial, "shell", "ls", "-la", dump_path],
            capture_output=True,
            timeout=10,
        )
        ps_proc = subprocess.run(
            ["adb", "-s", serial, "shell", "ps", "-A", "-o", "USER,PID,NAME,CMD"],
            capture_output=True,
            timeout=10,
        )
        ps_filtered = "\n".join(
            line
            for line in ps_proc.stdout.decode("utf-8", errors="replace").splitlines()
            if "uiautomator" in line or "app_process" in line
        )
        last_stderr = (
            dump_proc.stdout.decode("utf-8", errors="replace")
            + dump_proc.stderr.decode("utf-8", errors="replace")
        ).strip()
        _log.warning(
            "uiautomator dump attempt %d/%d failed on %s:\n"
            "  dump_rc=%d dump_out=%r dump_err=%r\n"
            "  ls_rc=%d ls_out=%r ls_err=%r\n"
            "  cat_rc=%d cat_bytes=%d cat_err=%r\n"
            "  device_procs:\n%s",
            attempt + 1,
            _DUMP_RETRIES,
            serial,
            dump_proc.returncode,
            dump_proc.stdout.decode("utf-8", errors="replace").strip(),
            dump_proc.stderr.decode("utf-8", errors="replace").strip(),
            ls_proc.returncode,
            ls_proc.stdout.decode("utf-8", errors="replace").strip(),
            ls_proc.stderr.decode("utf-8", errors="replace").strip(),
            result.returncode,
            len(result.stdout),
            result.stderr.decode("utf-8", errors="replace").strip(),
            ps_filtered or "  (no uiautomator/app_process found)",
        )
        # Re-release the slot in case something respawned instrumentation.
        _release_uiautomation_slot(serial)
        if attempt < _DUMP_RETRIES - 1:
            time.sleep(_DUMP_RETRY_DELAY_SEC)

    raise RuntimeError(
        f"uiautomator dump failed after {_DUMP_RETRIES} attempts on {serial}: "
        f"{last_stderr or 'no error output'}"
    )


def _release_uiautomation_slot(serial: str) -> None:
    """Kill any process holding the device's UiAutomation slot.

    On rooted devices uiautomator2's instrumentation runs as root and
    `am force-stop` is a no-op against it, so we fall through to `pkill -9`
    matched against the host package name in /proc/<pid>/cmdline. The
    `uiautomator` CLI doesn't carry that string in its own cmdline, so this
    won't kill the dump command we're about to run.
    """
    for pkg in ("com.github.uiautomator.test", "com.github.uiautomator"):
        subprocess.run(
            ["adb", "-s", serial, "shell", "am", "force-stop", pkg],
            capture_output=True,
            timeout=10,
        )
    pkill = subprocess.run(
        ["adb", "-s", serial, "shell", "pkill", "-9", "-f", "com.github.uiautomator"],
        capture_output=True,
        timeout=10,
    )
    _log.info(
        "uiautomator pkill on %s rc=%d stdout=%r stderr=%r",
        serial,
        pkill.returncode,
        pkill.stdout.decode("utf-8", errors="replace").strip(),
        pkill.stderr.decode("utf-8", errors="replace").strip(),
    )
    # Give the kernel time to release the UiAutomation binder. Manual testing
    # shows 0.5s can be too tight on some ROMs; 1s matches a known-good flow.
    time.sleep(1.0)


def _xml_text_fingerprint(xml: str) -> str:
    """Hash the text content of all nodes, ignoring XML structure/attributes.

    Comparing full XML strings breaks when dump_hierarchy() returns slightly
    different attribute ordering or truncates at different points across calls.
    Hashing only the visible text makes stability detection robust to those
    cosmetic differences while still detecting real content changes.
    """
    try:
        from xml.etree import ElementTree as ET

        root = ET.fromstring(xml)
        texts = sorted(
            node.attrib.get("text", "").strip()
            for node in root.iter("node")
            if node.attrib.get("text", "").strip()
        )
        return hashlib.md5("\n".join(texts).encode()).hexdigest()
    except Exception:
        return hashlib.md5(xml.encode()).hexdigest()


async def wait_for_ui_tree_stable(
    device: Any,
    *,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float = 0.1,
) -> str:
    deadline = time.monotonic() + max_wait_sec
    last_fingerprint: str | None = None
    last_xml: str = ""
    stable_since: float | None = None

    while time.monotonic() < deadline:
        xml = await asyncio.to_thread(dump_hierarchy_via_adb, device)
        now = time.monotonic()
        if not xml:
            # Dump failed entirely — don't treat empty as stable, just retry.
            await asyncio.sleep(poll_interval_sec)
            continue
        fingerprint = _xml_text_fingerprint(xml)
        last_xml = xml
        if fingerprint == last_fingerprint:
            if stable_since is None:
                if stable_sec <= 0:
                    return xml
                stable_since = now
            elif now - stable_since >= stable_sec:
                return xml
        else:
            last_fingerprint = fingerprint
            stable_since = None
        await asyncio.sleep(poll_interval_sec)

    # Return last xml even if stability was not reached (max_wait_sec expired).
    return last_xml


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
