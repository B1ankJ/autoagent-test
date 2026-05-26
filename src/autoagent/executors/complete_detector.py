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


# Subprocess cap. A healthy dump takes 1–3s; UI-not-idle path is bounded by
# the uiautomator CLI's internal Configurator wait. Keep this generous enough
# that we don't kill a dump that is legitimately waiting for an animation to
# finish, but short enough that a wedged adb shell doesn't stall the poll loop.
_DUMP_CMD_TIMEOUT_SEC = 12


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

    # Two attempts: the first runs as-is so a healthy device dumps in ~1s with
    # zero overhead. If it fails because the slot is busy, we release once and
    # retry. Anything else (UI not idle, adb hiccup) is returned as an empty
    # string so the outer poll loop in wait_for_ui_tree_stable can sleep and
    # try again — that loop is the right place to wait out animations.
    for attempt in range(2):
        xml, rc, err = _try_dump_once(serial, dump_path)
        if xml:
            return xml
        slot_busy = rc in (137, -9)
        _log.info(
            "uiautomator dump attempt %d failed on %s: rc=%d err=%r slot_busy=%s",
            attempt + 1,
            serial,
            rc,
            err,
            slot_busy,
        )
        if not slot_busy:
            return ""
        _release_uiautomation_slot(serial)

    return ""


def _try_dump_once(serial: str, dump_path: str) -> tuple[str, int, str]:
    """Single dump attempt. Returns (xml, dump_rc, err_excerpt)."""
    subprocess.run(
        ["adb", "-s", serial, "shell", "rm", "-f", dump_path],
        capture_output=True,
        timeout=10,
    )
    try:
        dump_proc = subprocess.run(
            ["adb", "-s", serial, "shell", "uiautomator", "dump", dump_path],
            capture_output=True,
            timeout=_DUMP_CMD_TIMEOUT_SEC,
        )
        rc = dump_proc.returncode
        err = dump_proc.stderr.decode("utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired:
        rc = -1
        err = f"adb shell uiautomator dump exceeded {_DUMP_CMD_TIMEOUT_SEC}s"

    result = subprocess.run(
        ["adb", "-s", serial, "shell", "cat", dump_path],
        capture_output=True,
        timeout=15,
    )
    xml = result.stdout.decode("utf-8", errors="replace").strip()
    if xml.startswith("<?xml") and "</hierarchy>" in xml:
        return xml, rc, ""
    return "", rc, err


def _find_uiautomation_pids(serial: str) -> list[int]:
    """Find PIDs of standalone app_process instances hosting instrumentation.

    After uiautomator2 attaches, the instrumentation host renames its comm
    via prctl(PR_SET_NAME) to "main", which makes `pkill -f` match against
    /proc/<pid>/cmdline fail because the package string is gone. The NAME
    column in `ps` still reports the binary basename `app_process`, and the
    only standalone `app_process` instances on a normal device are
    instrumentation hosts spawned by `am instrument` (system_server runs as
    its own binary).
    """
    proc = subprocess.run(
        ["adb", "-s", serial, "shell", "ps", "-A", "-o", "PID,NAME"],
        capture_output=True,
        timeout=10,
    )
    pids: list[int] = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[1] in ("app_process", "app_process32", "app_process64"):
            try:
                pids.append(int(parts[0]))
            except ValueError:
                pass
    return pids


def _release_uiautomation_slot(serial: str) -> None:
    """Kill any process holding the device's UiAutomation slot.

    Three layers: `am force-stop` handles non-root setups; `pkill -f` catches
    the host process before it renames its cmdline via prctl(PR_SET_NAME);
    `kill -9 <pid>` against standalone `app_process` entries handles the
    common case where instrumentation has finished initializing and its
    cmdline no longer contains the package string.
    """
    for pkg in ("com.github.uiautomator.test", "com.github.uiautomator"):
        subprocess.run(
            ["adb", "-s", serial, "shell", "am", "force-stop", pkg],
            capture_output=True,
            timeout=10,
        )
    subprocess.run(
        ["adb", "-s", serial, "shell", "pkill", "-9", "-f", "com.github.uiautomator"],
        capture_output=True,
        timeout=10,
    )
    pids = _find_uiautomation_pids(serial)
    if pids:
        kill_proc = subprocess.run(
            ["adb", "-s", serial, "shell", "kill", "-9", *(str(p) for p in pids)],
            capture_output=True,
            timeout=10,
        )
        _log.info(
            "uiautomator kill -9 on %s pids=%s rc=%d stderr=%r",
            serial,
            pids,
            kill_proc.returncode,
            kill_proc.stderr.decode("utf-8", errors="replace").strip(),
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


def _u2_dump_hierarchy(device: Any) -> str:
    """uiautomator2 fallback. May truncate large trees but never blocks on the
    UiAutomation slot, so it works when the adb CLI path keeps failing."""
    try:
        return device.dump_hierarchy(compressed=False) or ""
    except Exception as e:
        _log.warning(
            "u2 dump_hierarchy fallback failed on %s: %s",
            getattr(device, "serial", "?"),
            e,
        )
        return ""


# Consecutive empty CLI dumps before we give up and fall back to u2 for the
# rest of this poll session. 3 attempts × ~12s timeout each ≈ 36s upper bound.
_CLI_FALLBACK_THRESHOLD = 3


async def wait_for_ui_tree_stable(
    device: Any,
    *,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float = 0.1,
    prefer_u2: bool = False,
) -> str:
    """Poll the UI tree until two consecutive dumps share a fingerprint.

    `prefer_u2=True` skips the adb CLI path entirely — use this when the
    caller only needs the XML for a quick lookup (e.g. finding a copy button)
    and a possibly-truncated tree is acceptable.
    """
    deadline = time.monotonic() + max_wait_sec
    last_fingerprint: str | None = None
    last_xml: str = ""
    stable_since: float | None = None
    consecutive_cli_failures = 0
    use_u2 = prefer_u2

    while time.monotonic() < deadline:
        if use_u2:
            xml = await asyncio.to_thread(_u2_dump_hierarchy, device)
        else:
            xml = await asyncio.to_thread(dump_hierarchy_via_adb, device)
            if not xml:
                consecutive_cli_failures += 1
                if consecutive_cli_failures >= _CLI_FALLBACK_THRESHOLD:
                    _log.warning(
                        "adb CLI dump empty %d times in a row on %s; "
                        "falling back to u2 dump_hierarchy(compressed=False)",
                        consecutive_cli_failures,
                        getattr(device, "serial", "?"),
                    )
                    use_u2 = True
            else:
                consecutive_cli_failures = 0
        now = time.monotonic()
        if not xml:
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

    # Final fallback: if every CLI dump failed and we never tried u2, do it
    # once now so the caller doesn't get an empty string.
    if not last_xml and not use_u2:
        last_xml = await asyncio.to_thread(_u2_dump_hierarchy, device)
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
