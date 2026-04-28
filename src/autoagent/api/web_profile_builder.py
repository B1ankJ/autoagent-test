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
from autoagent.models.api import VLMConfig
from autoagent.storage.configs import get_config

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
([x, y, field]) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;

    const textOf = (node) => ((node.innerText || node.textContent || '').trim());
    const meaningfulClasses = (node) =>
        Array.from(node.classList || []).filter(
            (cls) => cls.length > 2 && !(cls.match(/^[a-z]+-[a-zA-Z0-9]{6,}$/) && /\\d/.test(cls))
        );
    const classSummary = (node) => meaningfulClasses(node).join(' ').toLowerCase();
    const semanticContentSummary = (summary) =>
        summary.includes('markdown') ||
        summary.includes('content') ||
        summary.includes('message') ||
        summary.includes('answer') ||
        summary.includes('reply');

    function simpleCandidates(node) {
        const out = [];
        if (node.id) out.push('#' + CSS.escape(node.id));
        const tid = node.getAttribute('data-testid');
        if (tid) out.push(`[data-testid="${tid}"]`);
        const role = node.getAttribute('role');
        const label = node.getAttribute('aria-label');
        if (role && label) out.push(`[role="${role}"][aria-label="${CSS.escape(label)}"]`);
        if (role) out.push(`[role="${role}"]`);
        const ph = node.getAttribute('placeholder');
        if (ph) out.push(`[placeholder="${ph}"]`);
        if (node.getAttribute('contenteditable') === 'true') out.push('[contenteditable="true"]');
        for (const cls of meaningfulClasses(node)) {
            out.push('.' + CSS.escape(cls));
        }
        return out;
    }

    function isInputLike(node) {
        if (!node) return false;
        const tag = node.tagName.toLowerCase();
        const role = (node.getAttribute('role') || '').toLowerCase();
        return (
            tag === 'textarea' ||
            tag === 'input' ||
            node.getAttribute('contenteditable') === 'true' ||
            role === 'textbox' ||
            role === 'searchbox' ||
            role === 'combobox'
        );
    }

    function isClickableLike(node) {
        if (!node) return false;
        const tag = node.tagName.toLowerCase();
        const role = (node.getAttribute('role') || '').toLowerCase();
        return (
            tag === 'button' ||
            tag === 'a' ||
            role === 'button' ||
            role === 'link' ||
            node.getAttribute('aria-haspopup') !== null
        );
    }

    function isUniqueMatch(root, node, sel) {
        try {
            const matches = root.querySelectorAll(sel);
            return matches.length === 1 && matches[0] === node;
        } catch {
            return false;
        }
    }

    function firstUniqueSimpleSelector(root, node) {
        for (const sel of simpleCandidates(node)) {
            if (isUniqueMatch(root, node, sel)) return sel;
        }
        return null;
    }

    function nthOfTypeSegment(node) {
        const tag = node.tagName.toLowerCase();
        let index = 1;
        let prev = node.previousElementSibling;
        while (prev) {
            if (prev.tagName === node.tagName) index += 1;
            prev = prev.previousElementSibling;
        }
        return `${tag}:nth-of-type(${index})`;
    }

    function pathFromAncestor(ancestor, node) {
        const segments = [];
        let cur = node;
        while (cur && cur !== ancestor) {
            segments.unshift(nthOfTypeSegment(cur));
            cur = cur.parentElement;
        }
        return segments.join(' > ');
    }

    function uniqueSelectorFor(node) {
        const direct = firstUniqueSimpleSelector(document, node);
        if (direct) return direct;

        let ancestor = node.parentElement;
        while (ancestor && ancestor !== document.documentElement) {
            const anchor = firstUniqueSimpleSelector(document, ancestor);
            if (anchor) {
                const suffix = pathFromAncestor(ancestor, node);
                return suffix ? `${anchor} > ${suffix}` : anchor;
            }
            ancestor = ancestor.parentElement;
        }

        const suffix = pathFromAncestor(document.documentElement, node);
        return suffix ? `html > ${suffix}` : 'html';
    }

    function repeatedItemSelector(node) {
        const parent = node.parentElement;
        if (!parent) return null;

        for (const cls of meaningfulClasses(node)) {
            const siblings = Array.from(parent.children).filter(
                (child) => child.classList && child.classList.contains(cls)
            );
            if (siblings.length >= 2) return '.' + CSS.escape(cls) + ':last-child';
        }

        const sameTagSiblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
        if (sameTagSiblings.length >= 2) {
            const parentSelector = firstUniqueSimpleSelector(document, parent) || uniqueSelectorFor(parent);
            return `${parentSelector} > ${node.tagName.toLowerCase()}:last-child`;
        }

        return null;
    }

    function promotedResponseNode(node) {
        const baseText = textOf(node);
        let cur = node;
        let candidate = node;
        for (let depth = 0; depth < 4 && cur.parentElement; depth += 1) {
            cur = cur.parentElement;
            const curText = textOf(cur);
            if (baseText && curText && curText !== baseText) {
                candidate = cur;
                break;
            }
        }

        let container = candidate;
        for (let depth = 0; depth < 3 && container.parentElement; depth += 1) {
            const summary = classSummary(container);
            if (semanticContentSummary(summary)) {
                return container;
            }
            container = container.parentElement;
        }
        return candidate;
    }

    function promoteFieldNode(node, field) {
        if (field === 'response') return promotedResponseNode(node);

        let cur = node;
        for (let depth = 0; depth < 6 && cur && cur !== document.body; depth += 1) {
            if ((field === 'input' || field === 'ready_check') && isInputLike(cur)) {
                return cur;
            }
            if ((field === 'send' || field === 'new_session') && isClickableLike(cur)) {
                return cur;
            }
            cur = cur.parentElement;
        }
        return node;
    }

    function findRepeatedItem(node) {
        let cur = node;
        for (let depth = 0; depth < 6 && cur && cur !== document.body; depth += 1) {
            if (repeatedItemSelector(cur)) return cur;
            cur = cur.parentElement;
        }
        return null;
    }

    function relativeSelectorWithin(ancestor, node) {
        if (ancestor === node) return '';

        let cur = node;
        while (cur && cur !== ancestor) {
            const direct = firstUniqueSimpleSelector(ancestor, cur);
            if (direct) return direct;
            cur = cur.parentElement;
        }

        const suffix = pathFromAncestor(ancestor, node);
        return suffix || '';
    }

    function preferredResponseNodeWithin(itemNode, originNode, fallbackNode) {
        let cur = originNode;
        while (cur && cur !== itemNode) {
            if (semanticContentSummary(classSummary(cur))) {
                return cur;
            }
            cur = cur.parentElement;
        }
        return fallbackNode;
    }

    if (field === 'response') {
        const textNode = promoteFieldNode(el, field);
        const itemNode = findRepeatedItem(textNode) || findRepeatedItem(el);
        if (itemNode) {
            const itemSelector = repeatedItemSelector(itemNode);
            if (itemSelector) {
                const preferredNode = preferredResponseNodeWithin(itemNode, el, textNode);
                const rel = relativeSelectorWithin(itemNode, preferredNode);
                return rel ? `${itemSelector} ${rel}` : itemSelector;
            }
        }
        return uniqueSelectorFor(textNode);
    }

    return uniqueSelectorFor(promoteFieldNode(el, field));
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
    inject_llm: bool = False


# ── helpers ───────────────────────────────────────────────────────────────────


async def _take_screenshot_b64(page: Any) -> str:
    raw: bytes = await page.screenshot(full_page=False)
    return base64.b64encode(raw).decode()


async def _get_selector(page: Any, x: float, y: float, field: str) -> str | None:
    return await page.evaluate(_SELECTOR_JS, [x, y, field])


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
    selector = await _get_selector(page, req.x, req.y, req.field)
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

    if req.inject_llm:
        raw_vlm = await get_config("vlm")
        vlm = VLMConfig.model_validate(raw_vlm) if raw_vlm else VLMConfig()
        if not (vlm.base_url and vlm.model and vlm.api_key):
            raise HTTPException(status_code=400, detail={"error": "llm_config_incomplete"})
        profile["base_url"] = vlm.base_url
        profile["model"] = vlm.model
        profile["api_key"] = vlm.api_key

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
