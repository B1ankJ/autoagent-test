"""DingTalk custom-robot webhook sender.

Docs: https://open.dingtalk.com/document/robots/custom-robot-access
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

_log = logging.getLogger(__name__)
_TIMEOUT_SEC = 10.0

# Send retry: DingTalk's edge occasionally 5xx / rate-limits; a single miss
# = a lost alert, which defeats the purpose. Retry 3 times total with
# 1/2/4s backoff. Only network / 5xx / rate-limit errcode is retried;
# permission errcode (300xxx) or config problems don't help by retrying.
_MAX_ATTEMPTS = 3
_BACKOFF_SEC = (1.0, 2.0, 4.0)
_RATE_LIMIT_ERRCODES = {130101, 130102, 130103, 130104, -1}


@dataclass
class SendResult:
    ok: bool
    status_code: int | None
    errcode: int | None
    errmsg: str | None


def _sign_url(webhook_url: str, secret: str) -> str:
    """Append timestamp + HMAC-SHA256 signature per DingTalk's signing scheme."""
    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    sep = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{sep}timestamp={ts}&sign={sign}"


def _is_retryable(result: SendResult) -> bool:
    """Retry only on things that plausibly go away by trying again."""
    # Network / timeout: no status_code and no errcode → retry.
    if result.status_code is None and result.errcode is None:
        return True
    # 5xx from DingTalk edge → retry.
    if result.status_code is not None and 500 <= result.status_code < 600:
        return True
    # DingTalk-side rate limit → retry with backoff.
    if result.errcode in _RATE_LIMIT_ERRCODES:
        return True
    return False


async def _send_once(
    *,
    url: str,
    payload: dict[str, Any],
) -> SendResult:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        return SendResult(ok=False, status_code=None, errcode=None, errmsg=str(e))

    if resp.status_code != 200:
        return SendResult(
            ok=False,
            status_code=resp.status_code,
            errcode=None,
            errmsg=resp.text[:300],
        )
    try:
        data = resp.json()
    except ValueError:
        return SendResult(ok=False, status_code=200, errcode=None, errmsg="non-json response")
    errcode = data.get("errcode")
    errmsg = data.get("errmsg")
    return SendResult(
        ok=errcode == 0,
        status_code=200,
        errcode=errcode if isinstance(errcode, int) else None,
        errmsg=errmsg if isinstance(errmsg, str) else None,
    )


async def send_markdown(
    *,
    webhook_url: str,
    secret: str | None,
    title: str,
    text: str,
    at_mobiles: list[str] | None = None,
    at_all: bool = False,
) -> SendResult:
    """POST a markdown message to the DingTalk webhook, with retry."""
    url = _sign_url(webhook_url, secret) if secret else webhook_url
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    if at_mobiles or at_all:
        payload["at"] = {
            "atMobiles": at_mobiles or [],
            "isAtAll": at_all,
        }

    last: SendResult | None = None
    for attempt in range(_MAX_ATTEMPTS):
        result = await _send_once(url=url, payload=payload)
        if result.ok:
            if attempt > 0:
                _log.info("dingtalk send recovered on attempt %d/%d", attempt + 1, _MAX_ATTEMPTS)
            return result
        last = result
        if not _is_retryable(result) or attempt == _MAX_ATTEMPTS - 1:
            break
        _log.warning(
            "dingtalk send attempt %d/%d failed (status=%s errcode=%s errmsg=%r); "
            "retrying in %.1fs",
            attempt + 1,
            _MAX_ATTEMPTS,
            result.status_code,
            result.errcode,
            result.errmsg,
            _BACKOFF_SEC[attempt],
        )
        await asyncio.sleep(_BACKOFF_SEC[attempt])
    assert last is not None
    _log.warning(
        "dingtalk send exhausted retries: status=%s errcode=%s errmsg=%r",
        last.status_code,
        last.errcode,
        last.errmsg,
    )
    return last
