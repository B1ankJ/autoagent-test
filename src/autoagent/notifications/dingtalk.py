"""DingTalk custom-robot webhook sender.

Docs: https://open.dingtalk.com/document/robots/custom-robot-access
"""
from __future__ import annotations

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


async def send_markdown(
    *,
    webhook_url: str,
    secret: str | None,
    title: str,
    text: str,
    at_mobiles: list[str] | None = None,
    at_all: bool = False,
) -> SendResult:
    """POST a markdown message to the DingTalk webhook."""
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
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        _log.warning("dingtalk send failed: %s", e)
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
