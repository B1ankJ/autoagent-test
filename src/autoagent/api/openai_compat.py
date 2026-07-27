from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from autoagent.api._deps import get_scheduler
from autoagent.auth.bearer import BearerAuthError, resolve_bearer_subject
from autoagent.openai_compat.chat_completions import (
    OpenAICompatError,
    build_chat_completion_response,
    build_sample_from_request,
    ensure_supported_request,
    parse_chat_completions_request,
    resolve_profile,
)
from autoagent.services.sync_tests import (
    SyncSampleResultMissingError,
    blocking_session_ids,
    execute_sync_sample,
)
from autoagent.storage.samples import list_samples_for_batch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["openai_compat"])


def _require_openai_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OpenAICompatError(
            status_code=401,
            message="Missing bearer token",
            error_type="invalid_request_error",
            code="invalid_api_key",
        )
    try:
        return resolve_bearer_subject(token)
    except BearerAuthError as exc:
        message = "Malformed token" if exc.reason == "malformed" else "Invalid or expired token"
        raise OpenAICompatError(
            status_code=401,
            message=message,
            error_type="invalid_request_error",
            code="invalid_api_key",
        ) from exc


@router.post("/chat/completions")
async def create_chat_completion(request: Request) -> JSONResponse:
    # Set once parsing succeeds; stays None if the request never got that
    # far (e.g. failed auth) so the except blocks below can still log which
    # model/sample this was for without assuming it's bound.
    body = None
    try:
        _require_openai_bearer(request)
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise OpenAICompatError(
                status_code=400,
                message="invalid chat.completions request: malformed JSON body",
                error_type="invalid_request_error",
                code="invalid_request",
            ) from exc
        body = parse_chat_completions_request(payload)
        ensure_supported_request(body)
        profile = resolve_profile(body.model)
        sample = build_sample_from_request(body, profile)
        result = await execute_sync_sample(
            sample,
            get_scheduler_fn=get_scheduler,
            list_samples_for_batch_fn=list_samples_for_batch,
        )
        blocking = blocking_session_ids(result)
        if blocking:
            raise OpenAICompatError(
                status_code=429,
                message=result.error or "all devices reserved by other session(s)",
                error_type="rate_limit_error",
                code="device_reserved",
                extra={"blocking_session_ids": blocking},
            )
        response = build_chat_completion_response(body, result, profile)
        return JSONResponse(status_code=200, content=response.model_dump())
    except SyncSampleResultMissingError:
        log.warning(
            "chat.completions model=%s: batch finished with no recorded result",
            body.model if body else "unknown",
        )
        error = OpenAICompatError(
            status_code=500,
            message="no result recorded",
            error_type="api_error",
        )
        return JSONResponse(status_code=500, content=error.to_response().model_dump())
    except OpenAICompatError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_response().model_dump())
    except Exception:
        # Previously swallowed with no logging at all — an unexpected crash
        # anywhere in this handler (profile resolution, executor, response
        # building) just returned a generic message with zero way to find
        # out what actually broke. log.exception captures the traceback.
        log.exception(
            "chat.completions model=%s: internal execution failure",
            body.model if body else "unknown",
        )
        error = OpenAICompatError(
            status_code=500,
            message="internal execution failure",
            error_type="api_error",
        )
        return JSONResponse(status_code=500, content=error.to_response().model_dump())
