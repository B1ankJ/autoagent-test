"""Authenticated media serving for sample screenshots.

Separate from the batches router because these URLs are used directly as
`<img src>`, which can't send an Authorization header — auth is via a
`?token=` query param instead (same pattern as the device stream). Adds
an optional `?w=` thumbnail so the log view downloads ~15KB previews
instead of the full ~700KB device screenshots, and only fetches full
resolution when the user zooms in.
"""
from __future__ import annotations

import io
import re
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from PIL import Image

from autoagent.auth.bearer import BearerAuthError, resolve_bearer_subject
from autoagent.config.settings import get_settings

router = APIRouter(prefix="/media", tags=["media"])

# Accept both .png (legacy batches) and .jpg (current, JPEG-compressed).
_SCREENSHOT_RE = re.compile(r"^[a-z0-9_]+\.(png|jpg)$")
_MAX_THUMB_W = 720
# Immutable: the file at <batch>/<sample>/<name> never changes once written.
_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}

# Bounded in-memory thumbnail cache. Screenshots are immutable, so the key
# is (path, mtime_ns, width); value is encoded JPEG bytes.
_THUMB_CACHE: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()
_THUMB_CACHE_MAX = 300


def _require_query_token(token: str | None) -> None:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        resolve_bearer_subject(token)
    except BearerAuthError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e


def _safe_target(batch_id: str, sample_id: str, name: str) -> Path:
    if not _SCREENSHOT_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid screenshot name")
    root = get_settings().logs_root.resolve()
    target = (root / batch_id / sample_id / name).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path traversal blocked") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return target


def _make_thumbnail(target: Path, width: int) -> bytes:
    mtime_ns = target.stat().st_mtime_ns
    key = (str(target), mtime_ns, width)
    cached = _THUMB_CACHE.get(key)
    if cached is not None:
        _THUMB_CACHE.move_to_end(key)
        return cached

    with Image.open(target) as im:
        im = im.convert("RGB")
        if im.width > width:
            height = round(im.height * width / im.width)
            im = im.resize((width, height), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80, optimize=True)
        data = buf.getvalue()

    _THUMB_CACHE[key] = data
    _THUMB_CACHE.move_to_end(key)
    while len(_THUMB_CACHE) > _THUMB_CACHE_MAX:
        _THUMB_CACHE.popitem(last=False)
    return data


@router.get("/batches/{batch_id}/samples/{sample_id}/screenshot/{name}")
async def get_screenshot(
    batch_id: str,
    sample_id: str,
    name: str,
    token: str | None = None,
    w: int | None = None,
) -> Response:
    """Serve a sample screenshot. `?w=N` returns a downscaled JPEG thumbnail."""
    _require_query_token(token)
    target = _safe_target(batch_id, sample_id, name)

    if w is not None and w > 0:
        width = min(w, _MAX_THUMB_W)
        data = _make_thumbnail(target, width)
        return Response(content=data, media_type="image/jpeg", headers=_CACHE_HEADERS)

    media_type = "image/jpeg" if target.suffix.lower() == ".jpg" else "image/png"
    return Response(
        content=target.read_bytes(),
        media_type=media_type,
        headers=_CACHE_HEADERS,
    )
