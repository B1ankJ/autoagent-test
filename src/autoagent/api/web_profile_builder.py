"""Web Profile Builder — guided selector capture for WebProfile YAML generation."""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel

from autoagent.auth.deps import require_user

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/web-profile-builder",
    tags=["web-profile-builder"],
    dependencies=[Depends(require_user)],
)

# ── in-memory session store ────────────────────────────────────────────────────

_sessions: dict[str, dict[str, Any]] = {}


# ── JS helper injected into the page to derive a stable CSS selector ──────────

_SELECTOR_JS = """
([x, y]) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;

    function trySelector(sel) {
        try { return document.querySelector(sel) === el ? sel : null; }
        catch { return null; }
    }

    // 1. id
    if (el.id) {
        const s = '#' + CSS.escape(el.id);
        if (trySelector(s)) return s;
    }
    // 2. data-testid
    const tid = el.getAttribute('data-testid');
    if (tid) {
        const s = `[data-testid="${tid}"]`;
        if (trySelector(s)) return s;
    }
    // 3. role + aria-label
    const role = el.getAttribute('role');
    const label = el.getAttribute('aria-label');
    if (role && label) {
        const s = `[role="${role}"][aria-label="${CSS.escape(label)}"]`;
        if (trySelector(s)) return s;
    }
    // 4. role alone (if unique)
    if (role) {
        const s = `[role="${role}"]`;
        if (trySelector(s)) return s;
    }
    // 5. placeholder
    const ph = el.getAttribute('placeholder');
    if (ph) {
        const s = `[placeholder="${ph}"]`;
        if (trySelector(s)) return s;
    }
    // 6. contenteditable
    if (el.getAttribute('contenteditable') === 'true') {
        const s = '[contenteditable="true"]';
        if (trySelector(s)) return s;
    }
    // 7. class (first meaningful class)
    for (const cls of el.classList) {
        if (cls.length > 2 && !cls.match(/^[a-z]+-[a-zA-Z0-9]{6,}$/)) {
            const s = '.' + CSS.escape(cls);
            if (trySelector(s)) return s;
        }
    }
    // 8. tag
    return el.tagName.toLowerCase();
}
"""

_ELEMENT_INFO_JS = """
([x, y]) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    return {
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role'),
        placeholder: el.getAttribute('placeholder'),
        text: (el.innerText || el.textContent || '').trim().slice(0, 80),
        contenteditable: el.getAttribute('contenteditable') === 'true',
    };
}
"""


# ── request / response models ─────────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    url: str
    channel: str = "chromium"
    headless: bool = False
    user_data_dir: str | None = None


class SessionView(BaseModel):
    id: str
    url: str
    selections: dict[str, Any]


class PickRequest(BaseModel):
    field: str  # "input" | "send" | "response" | "ready_check" | "new_session"
    x: float
    y: float
    send_type: str = "keyboard"  # "keyboard" | "click"
    keyboard_key: str = "Enter"


class PickResult(BaseModel):
    field: str
    selector: str
    element_info: dict[str, Any]


class GenerateRequest(BaseModel):
    name: str
    profile_url: str | None = None  # override if navigated away
    stable_sec: float = 3.0
    ready_timeout_sec: float = 15.0


# ── helpers ───────────────────────────────────────────────────────────────────


async def _take_screenshot_b64(page: Any) -> str:
    raw: bytes = await page.screenshot(full_page=False)
    return base64.b64encode(raw).decode()


async def _get_selector(page: Any, x: float, y: float) -> str | None:
    return await page.evaluate(_SELECTOR_JS, [x, y])


async def _get_element_info(page: Any, x: float, y: float) -> dict[str, Any]:
    info = await page.evaluate(_ELEMENT_INFO_JS, [x, y])
    return info or {}


def _get_session(session_id: str) -> dict[str, Any]:
    s = _sessions.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.post("/sessions", response_model=SessionView)
async def create_session(req: SessionCreateRequest) -> SessionView:
    session_id = str(uuid.uuid4())[:8]
    pw = await async_playwright().start()
    try:
        if req.user_data_dir:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=req.user_data_dir,
                channel=req.channel,
                headless=req.headless,
            )
        else:
            browser = await pw.chromium.launch(channel=req.channel, headless=req.headless)
            context = await browser.new_context()
        page = await context.new_page()
        await page.goto(req.url, timeout=30_000)
    except Exception as exc:
        await pw.stop()
        raise HTTPException(status_code=502, detail=f"browser launch failed: {exc}") from exc

    _sessions[session_id] = {
        "id": session_id,
        "url": req.url,
        "channel": req.channel,
        "headless": req.headless,
        "user_data_dir": req.user_data_dir,
        "pw": pw,
        "context": context,
        "page": page,
        "selections": {},
    }
    return SessionView(id=session_id, url=req.url, selections={})


@router.get("/sessions/{session_id}/screenshot")
async def get_screenshot(session_id: str) -> dict[str, str]:
    s = _get_session(session_id)
    try:
        img_b64 = await _take_screenshot_b64(s["page"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"image": img_b64}


@router.post("/sessions/{session_id}/pick", response_model=PickResult)
async def pick_element(session_id: str, req: PickRequest) -> PickResult:
    s = _get_session(session_id)
    page = s["page"]
    selector = await _get_selector(page, req.x, req.y)
    if not selector:
        raise HTTPException(status_code=422, detail="no element found at that position")
    info = await _get_element_info(page, req.x, req.y)

    entry: dict[str, Any] = {"selector": selector, "info": info}
    if req.field == "send":
        entry["send_type"] = req.send_type
        entry["keyboard_key"] = req.keyboard_key
    s["selections"][req.field] = entry

    return PickResult(field=req.field, selector=selector, element_info=info)


@router.delete("/sessions/{session_id}/selections/{field}")
async def clear_selection(session_id: str, field: str) -> dict[str, str]:
    s = _get_session(session_id)
    s["selections"].pop(field, None)
    return {"status": "cleared"}


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(session_id: str) -> SessionView:
    s = _get_session(session_id)
    return SessionView(id=s["id"], url=s["url"], selections=s["selections"])


@router.post("/sessions/{session_id}/generate")
async def generate_yaml(session_id: str, req: GenerateRequest) -> dict[str, str]:
    s = _get_session(session_id)
    sel = s["selections"]

    missing = [f for f in ("input", "send", "response") if f not in sel]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"missing required selections: {', '.join(missing)}",
        )

    input_sel = sel["input"]["selector"]
    send_entry = sel["send"]
    response_sel = sel["response"]["selector"]
    ready_sel = sel.get("ready_check", {}).get("selector") or input_sel

    if send_entry.get("send_type") == "click":
        send_method = {"type": "click_button", "selector": send_entry["selector"]}
    else:
        send_method = {"type": "keyboard", "key": send_entry.get("keyboard_key", "Enter")}

    new_session_action: list[dict] = []
    if "new_session" in sel:
        new_session_action = [{"action": "click", "selector": sel["new_session"]["selector"]}]

    profile: dict[str, Any] = {
        "name": req.name,
        "platform": "web",
        "url": req.profile_url or s["url"],
        "browser": {
            "headless": s["headless"],
            "channel": s["channel"],
        },
        "ready_check": {
            "type": "dom_selector",
            "selector": ready_sel,
            "timeout_sec": req.ready_timeout_sec,
        },
        "input_selector": input_sel,
        "send_method": send_method,
        "response_container_selector": response_sel,
        "complete_detection": {
            "type": "dom_stable",
            "stable_sec": req.stable_sec,
            "max_wait_sec": 120,
        },
        "recovery_path": [],
        "new_session_action": new_session_action,
    }
    if s["user_data_dir"]:
        profile["browser"]["user_data_dir"] = s["user_data_dir"]

    return {"yaml": yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)}


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str) -> dict[str, str]:
    s = _sessions.pop(session_id, None)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        await s["context"].close()
    except Exception:
        pass
    try:
        await s["pw"].stop()
    except Exception:
        pass
    return {"status": "closed"}
