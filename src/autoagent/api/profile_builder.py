import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import uiautomator2 as u2
import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from autoagent.api.tests import execute_sync_test
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
    ProfileBuilderRuntimeCapture,
    ProfileBuilderRuntimeConnectivity,
    ProfileBuilderRuntimeScreen,
    ProfileBuilderRuntimeView,
    ProfileBuilderSessionCreate,
    ProfileBuilderSessionView,
    Sample,
)
from autoagent.profiles.registry import delete_profile, save_profile_yaml

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


def _runtime_json_path(session_id: str) -> Path:
    return _session_dir(session_id) / "runtime.json"


def _artifact_names(session: ProfileBuilderSessionView) -> list[str]:
    artifact_dir = Path(session.artifact_dir)
    if not artifact_dir.exists():
        return []
    return sorted(
        path.name
        for path in artifact_dir.iterdir()
        if path.is_file()
        and path.name != "session.json"
        and path.name != "runtime.json"
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


def _default_runtime(session: ProfileBuilderSessionView) -> ProfileBuilderRuntimeView:
    return ProfileBuilderRuntimeView(
        session_id=session.id,
        session_status=session.status,
        current_step="idle",
        step_state="idle",
        captures=[
            ProfileBuilderRuntimeCapture(step=step, status="pending") for step in session.steps
        ],
        connectivity=ProfileBuilderRuntimeConnectivity(
            status="idle",
            result_status=None,
            result_summary=None,
            screens=[],
        ),
    )


def _load_runtime_from_disk(session_id: str) -> dict | None:
    path = _runtime_json_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="profile builder runtime load failed") from exc


def _store_runtime(session_id: str, runtime: dict) -> dict:
    path = _runtime_json_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return runtime


def _get_runtime(session: ProfileBuilderSessionView) -> ProfileBuilderRuntimeView:
    runtime_data = _load_runtime_from_disk(session.id)
    if runtime_data is None:
        runtime = _default_runtime(session)
        _store_runtime(session.id, runtime.model_dump(mode="json"))
        return runtime
    try:
        runtime = ProfileBuilderRuntimeView.model_validate(runtime_data)
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail="profile builder runtime is invalid") from exc
    if runtime.session_status != session.status:
        runtime = runtime.model_copy(update={"session_status": session.status})
        _store_runtime(session.id, runtime.model_dump(mode="json"))
    return runtime


def _upsert_capture_runtime(
    runtime: ProfileBuilderRuntimeView,
    *,
    session: ProfileBuilderSessionView,
    step: str,
    status: str,
    screenshot: str | None = None,
) -> ProfileBuilderRuntimeView:
    existing = next((item for item in runtime.captures if item.step == step), None)
    now = datetime.now(timezone.utc)
    capture = ProfileBuilderRuntimeCapture(
        step=step,
        status=status,
        screenshot=(
            screenshot if screenshot is not None else (existing.screenshot if existing else None)
        ),
        updated_at=now,
    )
    captures = []
    for step_name in session.steps:
        if step_name == step:
            captures.append(capture)
            continue
        prior = next((item for item in runtime.captures if item.step == step_name), None)
        captures.append(prior or ProfileBuilderRuntimeCapture(step=step_name, status="pending"))
    prior_screens = [
        screen
        for screen in runtime.recent_screens
        if not (screen.step == step and screen.label == f"capture_{step}")
    ]
    if screenshot:
        prior_screens.append(
            ProfileBuilderRuntimeScreen(
                step=step,
                label=f"capture_{step}",
                path=screenshot,
                taken_at=now,
            )
        )
    return runtime.model_copy(
        update={
            "session_status": session.status,
            "current_step": f"capture_{step}",
            "step_state": (
                "running" if status == "running" else ("done" if status == "done" else "failed")
            ),
            "captures": captures,
            "recent_screens": prior_screens[-3:],
        }
    )


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


def _draft_profile_path(session: ProfileBuilderSessionView) -> Path:
    return Path(session.artifact_dir) / "draft_profile.yaml"


def _read_draft_profile_yaml(session: ProfileBuilderSessionView) -> str:
    path = _draft_profile_path(session)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=404, detail="draft profile not found") from exc


def _write_draft_profile_yaml(session: ProfileBuilderSessionView, draft_profile: dict) -> str:
    draft_profile_yaml = yaml.safe_dump(draft_profile, sort_keys=False, allow_unicode=True)
    _draft_profile_path(session).write_text(draft_profile_yaml, encoding="utf-8")
    return draft_profile_yaml


def _runtime_screens_for_validation(
    session: ProfileBuilderSessionView,
) -> list[ProfileBuilderRuntimeScreen]:
    artifact_dir = Path(session.artifact_dir)
    names = [
        "validate_before_input.png",
        "validate_after_input.png",
        "validate_after_send.png",
        "validate_after_result.png",
        "validate_on_error.png",
    ]
    screens = []
    for name in names:
        path = artifact_dir / name
        if not path.exists():
            continue
        screens.append(
            ProfileBuilderRuntimeScreen(
                step="connectivity",
                label=path.stem,
                path=name,
                taken_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
            )
        )
    return screens


def _ready_check_text(idle_xml: str) -> str:
    try:
        root = ElementTree.fromstring(idle_xml)
    except ElementTree.ParseError:
        return "发消息"
    preferred = []
    for node in root.iter():
        text = (node.attrib.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if any(keyword in lowered for keyword in ("发消息", "说话", "输入", "send", "message")):
            preferred.append(text)
    if preferred:
        best = min(preferred, key=len)
        return "发消息" if "发消息" in best else best
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
    stored = _store_session(session)
    _store_runtime(stored.id, _default_runtime(stored).model_dump(mode="json"))
    return stored


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    return _get_session_or_404(session_id)


@router.get("/sessions/{session_id}/runtime", response_model=ProfileBuilderRuntimeView)
async def get_session_runtime(session_id: str) -> ProfileBuilderRuntimeView:
    session = _get_session_or_404(session_id)
    return _get_runtime(session)


@router.get("/sessions/{session_id}/artifacts/{name}")
async def download_session_artifact(session_id: str, name: str) -> FileResponse:
    session = _get_session_or_404(session_id)
    target = (Path(session.artifact_dir) / name).resolve()
    root = Path(session.artifact_dir).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path traversal blocked") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    media_type = "image/png" if target.suffix == ".png" else "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@router.post("/sessions/{session_id}/capture/{step}", response_model=ProfileBuilderSessionView)
async def capture_session_step(session_id: str, step: str) -> ProfileBuilderSessionView:
    session = _get_session_or_404(session_id)
    _validate_capture_step(session, step)
    _store_runtime(
        session.id,
        _upsert_capture_runtime(
            _get_runtime(session),
            session=session,
            step=step,
            status="running",
        ).model_dump(mode="json"),
    )
    try:
        device = await asyncio.to_thread(u2.connect, session.device_serial)
    except Exception as exc:
        _store_runtime(
            session.id,
            _upsert_capture_runtime(
                _get_runtime(session),
                session=session,
                step=step,
                status="failed",
            ).model_copy(update={"last_error": str(exc)}).model_dump(mode="json"),
        )
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
        _store_runtime(
            session.id,
            _upsert_capture_runtime(
                _get_runtime(session),
                session=session,
                step=step,
                status="failed",
            ).model_copy(update={"last_error": str(exc)}).model_dump(mode="json"),
        )
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
        stored = _store_session(updated)
        _store_runtime(
            stored.id,
            _upsert_capture_runtime(
                _get_runtime(stored),
                session=stored,
                step=step,
                status="done",
                screenshot=captured.screenshot_path.name,
            ).model_dump(mode="json"),
        )
        return stored


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


@router.post("/sessions/{session_id}/review")
async def apply_review(session_id: str, payload: dict) -> dict:
    session = _get_session_or_404(session_id)
    draft_profile_yaml = _read_draft_profile_yaml(session)
    draft_profile = yaml.safe_load(draft_profile_yaml)
    if not isinstance(draft_profile, dict):
        raise HTTPException(status_code=500, detail="draft profile is invalid")

    merged_profile = merge_llm_draft(draft_profile, payload)
    updated_yaml = _write_draft_profile_yaml(session, merged_profile)
    updated_session = _store_session(session)
    return {
        "session": updated_session.model_dump(mode="json"),
        "draft_profile_yaml": updated_yaml,
    }


@router.post("/sessions/{session_id}/validate")
async def validate_draft(session_id: str) -> dict:
    session = _get_session_or_404(session_id)
    draft_profile_yaml = _read_draft_profile_yaml(session)
    _store_runtime(
        session.id,
        _get_runtime(session).model_copy(
            update={
                "session_status": "validating",
                "current_step": "connectivity",
                "step_state": "running",
                "last_error": None,
                "connectivity": ProfileBuilderRuntimeConnectivity(status="running"),
                "recent_screens": [],
            }
        ).model_dump(mode="json"),
    )
    temp_profile_name = f"pb_{session.id}"
    save_profile_yaml(temp_profile_name, draft_profile_yaml)
    try:
        result = await execute_sync_test(
            Sample(
                id=f"pb-validate-{session.id}",
                prompts=["hello"],
                mode="gui_android",
                target_profile=temp_profile_name,
                timeout_sec=get_settings().default_gui_timeout_sec,
            )
        )
    finally:
        delete_profile(temp_profile_name)

    artifact_dir = Path(session.artifact_dir)
    (artifact_dir / "connectivity_result.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    next_status = "validated" if result.status == "done" else "ready"
    updated_session = _store_session(session.model_copy(update={"status": next_status}))
    runtime_screens = _runtime_screens_for_validation(updated_session)
    result_summary = result.responses[0] if result.responses else result.error
    _store_runtime(
        updated_session.id,
        _get_runtime(updated_session).model_copy(
            update={
                "session_status": next_status,
                "current_step": "connectivity",
                "step_state": "done" if result.status == "done" else "failed",
                "last_error": None if result.status == "done" else result.error,
                "connectivity": ProfileBuilderRuntimeConnectivity(
                    status="done" if result.status == "done" else "failed",
                    result_status=result.status,
                    result_summary=result_summary,
                    screens=runtime_screens,
                ),
                "recent_screens": runtime_screens[-3:],
            }
        ).model_dump(mode="json"),
    )
    return {
        "session": updated_session.model_dump(mode="json"),
        "draft_profile_yaml": draft_profile_yaml,
        "connectivity_result": result.model_dump(mode="json"),
    }
