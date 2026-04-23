import asyncio
import json
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import uiautomator2 as u2
import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.executors.profile_builder_candidates import build_android_candidates
from autoagent.executors.profile_builder_capture import CapturedState, capture_android_state
from autoagent.executors.profile_builder_generator import (
    maybe_generate_llm_draft,
    merge_llm_draft,
)
from autoagent.models.api import (
    ProfileBuilderCaptureArtifact,
    ProfileBuilderSessionCreate,
    ProfileBuilderSessionView,
)

router = APIRouter(
    prefix="/profile-builder",
    tags=["profile-builder"],
    dependencies=[Depends(require_user)],
)

_SESSIONS: dict[str, ProfileBuilderSessionView] = {}
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def reset_sessions_for_tests() -> None:
    _SESSIONS.clear()
    _SESSION_LOCKS.clear()


def _get_session_lock(session_id: str) -> asyncio.Lock:
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    return lock


def _session_dir(session_id: str) -> Path:
    return get_settings().data_root / "profile_builder" / session_id


def _session_json_path(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _artifact_names(session: ProfileBuilderSessionView) -> list[str]:
    artifact_dir = Path(session.artifact_dir)
    if not artifact_dir.exists():
        return []
    return sorted(
        path.name
        for path in artifact_dir.iterdir()
        if path.is_file()
        and path.name != "session.json"
        and not path.name.startswith("session.json.")
        and not path.name.endswith(".tmp")
    )


def _persist_session(session: ProfileBuilderSessionView) -> None:
    artifact_dir = Path(session.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    session_json = artifact_dir / "session.json"
    session_tmp = artifact_dir / "session.json.tmp"
    session_tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    session_tmp.replace(session_json)


def _load_session_from_disk(session_id: str) -> ProfileBuilderSessionView | None:
    session_json = _session_json_path(session_id)
    if not session_json.exists():
        return None
    try:
        return ProfileBuilderSessionView.model_validate_json(
            session_json.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise HTTPException(status_code=500, detail="profile builder session load failed") from exc


def _sync_artifacts(session: ProfileBuilderSessionView) -> ProfileBuilderSessionView:
    artifacts = _artifact_names(session)
    if session.artifacts == artifacts:
        return session
    return session.model_copy(update={"artifacts": artifacts})


def _store_session(session: ProfileBuilderSessionView) -> ProfileBuilderSessionView:
    synced = _sync_artifacts(session)
    _persist_session(synced)
    _SESSIONS[synced.id] = synced
    return synced


def _get_session_or_404(session_id: str) -> ProfileBuilderSessionView:
    session = _load_session_from_disk(session_id)
    if session is None:
        session = _SESSIONS.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
    synced = _sync_artifacts(session)
    if synced != session:
        _persist_session(synced)
    _SESSIONS[session_id] = synced
    return synced


def _validate_capture_step(session: ProfileBuilderSessionView, step: str) -> None:
    if step not in session.steps:
        raise HTTPException(status_code=422, detail=f"unknown capture step: {step}")


def _capture_artifact_from_state(captured: CapturedState) -> ProfileBuilderCaptureArtifact:
    return ProfileBuilderCaptureArtifact(
        step=captured.step,
        package=captured.package,
        activity=captured.activity,
        xml_artifact=captured.xml_path.name,
        screenshot_artifact=captured.screenshot_path.name,
    )


def _capture_map(session: ProfileBuilderSessionView) -> dict[str, ProfileBuilderCaptureArtifact]:
    return {capture.step: capture for capture in session.captures}


def _require_complete_captures(
    session: ProfileBuilderSessionView,
) -> dict[str, ProfileBuilderCaptureArtifact]:
    captures = _capture_map(session)
    missing = [step for step in session.steps if step not in captures]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"missing required captures: {', '.join(missing)}",
        )
    return captures


def _read_capture_xml(session: ProfileBuilderSessionView, artifact_name: str) -> str:
    path = Path(session.artifact_dir) / artifact_name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="profile builder draft load failed") from exc


def _ready_check_text(idle_xml: str) -> str:
    try:
        root = ElementTree.fromstring(idle_xml)
    except ElementTree.ParseError:
        return "发消息"
    for node in root.iter():
        text = (node.attrib.get("text") or "").strip()
        if text:
            return text
    return "发消息"


def _draft_profile_from_candidates(
    *,
    session: ProfileBuilderSessionView,
    captures: dict[str, ProfileBuilderCaptureArtifact],
    candidates: dict,
    idle_xml: str,
) -> dict:
    input_candidates = candidates["input_candidates"]
    send_candidates = candidates["send_candidates"]
    response_candidates = candidates["response_candidates"]
    if not input_candidates or not send_candidates or not response_candidates:
        raise HTTPException(status_code=422, detail="insufficient candidates to generate draft")

    response_capture = captures["response"]
    first_response = response_candidates[0]
    return {
        "name": session.name,
        "platform": session.platform,
        "package": response_capture.package,
        "activity": response_capture.activity,
        "serial": session.device_serial,
        "input_method": "auto",
        "ready_check": {
            "type": "ui_tree_contains",
            "text": _ready_check_text(idle_xml),
            "timeout_sec": 5,
        },
        "recovery_path": [],
        "input_locator": input_candidates[0]["locator"],
        "send_button_locator": send_candidates[0]["locator"],
        "response_extraction": {
            "method": "ui_tree_only",
            "response_container_locator": first_response["response_container_locator"],
            "scroll_container_locator": first_response["scroll_container_locator"],
            "latest_bubble_match": first_response["latest_bubble_match"],
        },
        "new_session_action": [],
        "complete_detection": {
            "type": "ui_tree_stable",
            "stable_sec": 2,
            "max_wait_sec": 180,
        },
    }


@router.post(
    "/sessions",
    response_model=ProfileBuilderSessionView,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(payload: ProfileBuilderSessionCreate) -> ProfileBuilderSessionView:
    session_id = f"pb_{uuid4().hex[:12]}"
    session = ProfileBuilderSessionView(
        id=session_id,
        platform=payload.platform,
        device_serial=payload.device_serial,
        name=payload.name,
        status="draft",
        steps=["idle", "editing", "response"],
        artifact_dir=str(get_settings().data_root / "profile_builder" / session_id),
        artifacts=[],
        captures=[],
    )
    return _store_session(session)


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    return _get_session_or_404(session_id)


@router.post("/sessions/{session_id}/capture/{step}", response_model=ProfileBuilderSessionView)
async def capture_session_step(session_id: str, step: str) -> ProfileBuilderSessionView:
    session = _get_session_or_404(session_id)
    _validate_capture_step(session, step)
    try:
        device = await asyncio.to_thread(u2.connect, session.device_serial)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"profile builder capture connect failed: {exc}",
        ) from exc

    try:
        captured = await capture_android_state(
            device=device,
            session_dir=Path(session.artifact_dir),
            step=step,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"profile builder capture failed: {exc}",
        ) from exc

    async with _get_session_lock(session_id):
        current_session = _get_session_or_404(session_id)
        _validate_capture_step(current_session, step)
        capture_record = _capture_artifact_from_state(captured)
        captures = [record for record in current_session.captures if record.step != step]
        captures.append(capture_record)
        captures.sort(key=lambda record: current_session.steps.index(record.step))
        updated = current_session.model_copy(update={"captures": captures})
        return _store_session(updated)


@router.post("/sessions/{session_id}/draft")
async def generate_draft(session_id: str) -> dict:
    session = _get_session_or_404(session_id)
    settings = get_settings()
    captures = _require_complete_captures(session)
    idle_xml = _read_capture_xml(session, captures["idle"].xml_artifact)
    editing_xml = _read_capture_xml(session, captures["editing"].xml_artifact)
    response_xml = _read_capture_xml(session, captures["response"].xml_artifact)

    candidate_draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )
    candidates = candidate_draft.asdict()
    rule_draft = _draft_profile_from_candidates(
        session=session,
        captures=captures,
        candidates=candidates,
        idle_xml=idle_xml,
    )
    llm_output = await maybe_generate_llm_draft(
        settings=settings,
        rule_draft=rule_draft,
        candidates=candidates,
        captures={step: capture.model_dump(mode="json") for step, capture in captures.items()},
    )
    draft_profile = merge_llm_draft(rule_draft, llm_output)

    artifact_dir = Path(session.artifact_dir)
    (artifact_dir / "candidates.json").write_text(
        json.dumps(
            {
                "input_candidates": candidates["input_candidates"],
                "send_candidates": candidates["send_candidates"],
                "response_candidates": candidates["response_candidates"],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "review_items.json").write_text(
        json.dumps(candidates["review_items"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    draft_profile_yaml = yaml.safe_dump(draft_profile, sort_keys=False, allow_unicode=True)
    (artifact_dir / "draft_profile.yaml").write_text(draft_profile_yaml, encoding="utf-8")

    updated = _store_session(session.model_copy(update={"status": "ready"}))
    return {
        "session": updated.model_dump(mode="json"),
        "candidates": candidates,
        "review_items": candidates["review_items"],
        "draft_profile_yaml": draft_profile_yaml,
    }
