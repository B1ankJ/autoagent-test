import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from xml.etree import ElementTree

import uiautomator2 as u2
import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from autoagent.api.tests import execute_sync_test
from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.devices.adb import set_ime
from autoagent.executors.android_input import ensure_adb_keyboard_ready
from autoagent.executors import profile_builder_new_session
from autoagent.executors.profile_builder_candidates import build_android_candidates
from autoagent.executors.profile_builder_capture import CapturedState, capture_android_state
from autoagent.executors.profile_builder_generator import (
    maybe_generate_llm_draft,
    merge_llm_draft,
    resolve_smart_draft,
)
from autoagent.models.api import (
    ProfileBuilderCaptureArtifact,
    ProfileBuilderDraftResponse,
    ProfileBuilderNewSessionConfigRequest,
    ProfileBuilderNewSessionConfirmRequest,
    ProfileBuilderNewSessionStep,
    ProfileBuilderRuntimeCapture,
    ProfileBuilderRuntimeConnectivity,
    ProfileBuilderRuntimeScreen,
    ProfileBuilderRuntimeView,
    ProfileBuilderSessionCreate,
    ProfileBuilderSessionView,
    Sample,
    VLMConfig,
)
from autoagent.profiles.registry import delete_profile, save_profile_yaml
from autoagent.storage.configs import get_config

router = APIRouter(
    prefix="/profile-builder",
    tags=["profile-builder"],
    dependencies=[Depends(require_user)],
)

_SESSIONS: dict[str, ProfileBuilderSessionView] = {}
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


class _GenerateDraftRequest(BaseModel):
    draft_mode: Literal["rule", "smart"] = "rule"
    use_llm_optimization: bool | None = None
    inject_llm: bool = False

    def resolved_draft_mode(self) -> Literal["rule", "smart"]:
        if self.use_llm_optimization is not None:
            return "smart" if self.use_llm_optimization else "rule"
        return self.draft_mode


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


def _new_session_state_path(session_id: str) -> Path:
    return _session_dir(session_id) / "new_session_state.json"


def _is_internal_artifact_name(name: str) -> bool:
    return name in {"session.json", "runtime.json", "new_session_state.json"}


def _artifact_names(session: ProfileBuilderSessionView) -> list[str]:
    artifact_dir = Path(session.artifact_dir)
    if not artifact_dir.exists():
        return []
    return sorted(
        path.name
        for path in artifact_dir.iterdir()
        if path.is_file()
        and not _is_internal_artifact_name(path.name)
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
        builder_adb_keyboard_active=False,
        builder_previous_ime=None,
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


def _default_new_session_state() -> dict:
    return {"strategy": "disabled", "steps": []}


def _empty_new_session_step(step_index: int) -> dict:
    return {
        "step_index": step_index,
        "xml_artifact": None,
        "screenshot_artifact": None,
        "recommended_tap": {"point": None, "reason": None, "status": "idle"},
        "confirmed_tap": None,
        "source": None,
    }


def _load_new_session_state_from_disk(session_id: str) -> dict | None:
    path = _new_session_state_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="profile builder new-session load failed") from exc


def _store_new_session_state(session_id: str, state: dict) -> dict:
    path = _new_session_state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return state


def _resize_new_session_steps(steps: list[dict], step_count: int) -> list[dict]:
    next_steps = [dict(step) for step in steps[:step_count]]
    while len(next_steps) < step_count:
        next_steps.append(_empty_new_session_step(len(next_steps)))
    for index, step in enumerate(next_steps):
        step["step_index"] = index
    return next_steps


def _get_new_session_state(session: ProfileBuilderSessionView) -> dict:
    raw_state = _load_new_session_state_from_disk(session.id) or _default_new_session_state()
    strategy = raw_state.get("strategy")
    raw_steps = raw_state.get("steps")
    if strategy not in {"disabled", "guided_tap_sequence"} or not isinstance(raw_steps, list):
        normalized = _default_new_session_state()
        _store_new_session_state(session.id, normalized)
        return normalized
    if strategy == "guided_tap_sequence" and not raw_steps:
        normalized = _default_new_session_state()
        _store_new_session_state(session.id, normalized)
        return normalized

    step_count = len(raw_steps) if strategy == "guided_tap_sequence" else 0
    normalized_steps = _resize_new_session_steps(
        [dict(step) for step in raw_steps if isinstance(step, dict)],
        step_count,
    )
    try:
        validated_steps = [
            ProfileBuilderNewSessionStep.model_validate(step).model_dump(mode="json")
            for step in normalized_steps
        ]
    except ValidationError:
        normalized = _default_new_session_state()
        _store_new_session_state(session.id, normalized)
        return normalized
    normalized = {
        "strategy": strategy,
        "steps": validated_steps if strategy == "guided_tap_sequence" else [],
    }
    if normalized != raw_state:
        _store_new_session_state(session.id, normalized)
    return normalized


def _new_session_action_from_state(state: dict) -> list[dict]:
    if state["strategy"] != "guided_tap_sequence":
        return []
    action: list[dict] = []
    for step in state["steps"]:
        confirmed_tap = step.get("confirmed_tap")
        if not isinstance(confirmed_tap, dict):
            continue
        action.append(
            {
                "action": "tap_xy",
                "x": confirmed_tap["x"],
                "y": confirmed_tap["y"],
            }
        )
    return action


def _require_guided_new_session_step(
    session: ProfileBuilderSessionView,
    step_index: int,
) -> dict:
    state = _get_new_session_state(session)
    if state["strategy"] != "guided_tap_sequence":
        raise HTTPException(status_code=422, detail="new-session guided flow is not configured")
    if step_index < 0 or step_index >= len(state["steps"]):
        raise HTTPException(status_code=422, detail=f"unknown new-session step index: {step_index}")
    return state


def _draft_profile_preview(session: ProfileBuilderSessionView) -> dict:
    return {
        "name": session.name,
        "platform": session.platform,
        "new_session_action": [],
    }


def _draft_profile_for_state(session: ProfileBuilderSessionView, state: dict) -> dict:
    draft_path = _draft_profile_path(session)
    if draft_path.exists():
        draft_profile = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
        if not isinstance(draft_profile, dict):
            raise HTTPException(status_code=500, detail="draft profile is invalid")
    else:
        draft_profile = _draft_profile_preview(session)
    draft_profile["new_session_action"] = _new_session_action_from_state(state)
    return draft_profile


def _draft_response_payload(
    *,
    session: ProfileBuilderSessionView,
    draft_profile_yaml: str,
    state: dict,
    candidates: dict | None = None,
    review_items: list[dict] | None = None,
    draft_mode: Literal["rule", "smart"] = "rule",
    requires_manual_review: bool = True,
    applied_review_choices: dict | None = None,
    pending_review_fields: list[str] | None = None,
    auto_review_source: Literal["manual", "llm"] = "manual",
) -> dict:
    return {
        "session": session.model_dump(mode="json"),
        "candidates": candidates or {},
        "review_items": review_items or [],
        "draft_profile_yaml": draft_profile_yaml,
        "draft_mode": draft_mode,
        "requires_manual_review": requires_manual_review,
        "applied_review_choices": applied_review_choices or {},
        "pending_review_fields": pending_review_fields or [],
        "auto_review_source": auto_review_source,
        "new_session_strategy": state["strategy"],
        "new_session_steps": state["steps"],
    }


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


def _builder_runtime_update(
    runtime: ProfileBuilderRuntimeView,
    *,
    active: bool,
    previous_ime: str | None,
) -> ProfileBuilderRuntimeView:
    return runtime.model_copy(
        update={
            "builder_adb_keyboard_active": active,
            "builder_previous_ime": previous_ime,
        }
    )


async def _activate_builder_adb_keyboard(
    session: ProfileBuilderSessionView,
) -> ProfileBuilderRuntimeView:
    runtime = _get_runtime(session)
    if runtime.builder_adb_keyboard_active:
        return runtime
    device = await asyncio.to_thread(u2.connect, session.device_serial)
    previous_ime = await asyncio.to_thread(ensure_adb_keyboard_ready, device)
    next_runtime = _builder_runtime_update(runtime, active=True, previous_ime=previous_ime)
    _store_runtime(session.id, next_runtime.model_dump(mode="json"))
    return next_runtime


async def _restore_builder_adb_keyboard(
    session: ProfileBuilderSessionView,
) -> ProfileBuilderRuntimeView:
    runtime = _get_runtime(session)
    if not runtime.builder_adb_keyboard_active:
        return runtime
    if runtime.builder_previous_ime:
        await asyncio.to_thread(set_ime, session.device_serial, runtime.builder_previous_ime)
    next_runtime = _builder_runtime_update(runtime, active=False, previous_ime=None)
    _store_runtime(session.id, next_runtime.model_dump(mode="json"))
    return next_runtime


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
        active=True,
        captured_at=datetime.now(timezone.utc),
    )


def _capture_map(session: ProfileBuilderSessionView) -> dict[str, ProfileBuilderCaptureArtifact]:
    captures = [capture for capture in session.captures if capture.active]
    if captures:
        return {capture.step: capture for capture in captures}
    return {capture.step: capture for capture in session.captures}


def _capture_sort_key(
    session: ProfileBuilderSessionView,
    capture: ProfileBuilderCaptureArtifact,
) -> tuple[int, int, str]:
    captured_at = capture.captured_at.isoformat() if capture.captured_at else ""
    return (
        session.steps.index(capture.step),
        0 if capture.active else 1,
        captured_at,
    )


def _archive_capture_artifacts(
    session: ProfileBuilderSessionView,
    capture: ProfileBuilderCaptureArtifact,
) -> ProfileBuilderCaptureArtifact:
    session_dir = Path(session.artifact_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    archive_token = f"{timestamp}_{uuid4().hex[:8]}"
    archived_xml = f"capture_{capture.step}_{archive_token}.xml"
    archived_png = f"capture_{capture.step}_{archive_token}.png"
    xml_path = session_dir / capture.xml_artifact
    png_path = session_dir / capture.screenshot_artifact
    if xml_path.exists():
        xml_path.replace(session_dir / archived_xml)
    if png_path.exists():
        png_path.replace(session_dir / archived_png)
    return capture.model_copy(
        update={
            "active": False,
            "xml_artifact": archived_xml,
            "screenshot_artifact": archived_png,
        }
    )


def _stage_new_session_step_artifacts_for_recapture(
    session: ProfileBuilderSessionView,
    step_state: dict,
) -> list[tuple[Path, Path, Path]]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    archive_token = f"{timestamp}_{uuid4().hex[:8]}"
    session_dir = Path(session.artifact_dir)
    step_index = step_state["step_index"]
    staged: list[tuple[Path, Path, Path]] = []
    artifacts = (
        ("xml_artifact", ".xml"),
        ("screenshot_artifact", ".png"),
    )
    for field_name, suffix in artifacts:
        artifact_name = step_state.get(field_name)
        if not artifact_name:
            continue
        artifact_path = session_dir / artifact_name
        if not artifact_path.exists():
            continue
        staged_path = session_dir / f"{artifact_name}.{archive_token}.recapture.tmp"
        artifact_path.replace(staged_path)
        staged.append(
            (
                artifact_path,
                staged_path,
                session_dir / f"capture_new_session_step_{step_index}_{archive_token}{suffix}",
            )
        )
    return staged


def _restore_staged_new_session_step_artifacts(
    staged_artifacts: list[tuple[Path, Path, Path]]
) -> None:
    for original_path, staged_path, _archive_path in staged_artifacts:
        if not staged_path.exists():
            continue
        staged_path.replace(original_path)


def _finalize_staged_new_session_step_artifacts(
    staged_artifacts: list[tuple[Path, Path, Path]]
) -> None:
    for _original_path, staged_path, archive_path in staged_artifacts:
        if staged_path.exists():
            staged_path.replace(archive_path)


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


def _dump_draft_profile_yaml(draft_profile: dict) -> str:
    return yaml.safe_dump(draft_profile, sort_keys=False, allow_unicode=True)


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


def _collect_validation_screens_from_logs(
    session: ProfileBuilderSessionView,
    logs_dir: str | None,
) -> list[ProfileBuilderRuntimeScreen]:
    if not logs_dir:
        return _runtime_screens_for_validation(session)
    source_dir = Path(logs_dir)
    if not source_dir.exists():
        return _runtime_screens_for_validation(session)
    artifact_dir = Path(session.artifact_dir)
    copies = [
        ("before_input_1.png", "validate_before_input.png"),
        ("after_input_1.png", "validate_after_input.png"),
        ("after_send_1.png", "validate_after_send.png"),
        ("after_result_1.png", "validate_after_result.png"),
        ("on_error.png", "validate_on_error.png"),
    ]
    for source_name, target_name in copies:
        source_path = source_dir / source_name
        if not source_path.exists():
            continue
        shutil.copy2(source_path, artifact_dir / target_name)
    return _runtime_screens_for_validation(session)


def _ready_check_text(idle_xml: str) -> str:
    try:
        root = ElementTree.fromstring(idle_xml)
    except ElementTree.ParseError:
        return "发消息"
    fallback_texts: list[str] = []
    preferred = []
    for node in root.iter():
        text = (node.attrib.get("text") or "").strip()
        if not text:
            continue
        package = (node.attrib.get("package") or "").strip()
        if package.startswith("com.android.systemui"):
            continue
        lowered = text.lower()
        if any(keyword in lowered for keyword in ("发消息", "说话", "输入", "send", "message")):
            preferred.append(text)
            continue
        fallback_texts.append(text)
    if preferred:
        best = min(preferred, key=len)
        return "发消息" if "发消息" in best else best
    if fallback_texts:
        return fallback_texts[0]
    return "发消息"


def _input_placeholder_locator(idle_xml: str) -> dict | None:
    try:
        root = ElementTree.fromstring(idle_xml)
    except ElementTree.ParseError:
        return None
    for node in root.iter():
        text = (node.attrib.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if "发消息" in text:
            return {"type": "xpath", "value": '//*[contains(@text, "发消息")]'}
        if any(keyword in lowered for keyword in ("说话", "输入", "send", "message", "chat")):
            return {"type": "xpath", "value": f'//*[contains(@text, "{text}")]'}
    return None


def _input_placeholder_ref(idle_xml: str) -> dict | None:
    try:
        root = ElementTree.fromstring(idle_xml)
    except ElementTree.ParseError:
        return None
    for node in root.iter():
        text = (node.attrib.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if not (
            "发消息" in text
            or any(keyword in lowered for keyword in ("说话", "输入", "send", "message", "chat"))
        ):
            continue
        target = "发消息" if "发消息" in text else text
        return {
            "text": target,
            "bounds": _parse_bounds(node.attrib.get("bounds")),
        }
    return None


def _parse_bounds(raw: str | None) -> tuple[int, int, int, int] | None:
    if not raw or not raw.startswith("["):
        return None
    normalized = raw.replace("][", ",").replace("[", "").replace("]", "")
    parts = normalized.split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _input_placeholder_tap_action(idle_xml: str) -> dict | None:
    placeholder_ref = _input_placeholder_ref(idle_xml)
    if placeholder_ref is None or placeholder_ref["bounds"] is None:
        return None
    x1, y1, x2, y2 = placeholder_ref["bounds"]
    return {
        "action": "tap_xy",
        "x": (x1 + x2) // 2,
        "y": (y1 + y2) // 2,
    }


def _input_focus_action_review_item(idle_xml: str, input_candidates: list[dict]) -> dict | None:
    placeholder_locator = _input_placeholder_locator(idle_xml)
    placeholder_tap_action = _input_placeholder_tap_action(idle_xml)
    placeholder_ref = _input_placeholder_ref(idle_xml)
    options: list[tuple[list[dict], list[dict]]] = []
    seen: set[str] = set()

    def _append_option(option: list[dict], evidence_refs: list[dict]) -> None:
        key = json.dumps(option, sort_keys=True, ensure_ascii=False)
        if key in seen:
            return
        seen.add(key)
        options.append((option, evidence_refs))

    if (
        placeholder_locator is not None
        and placeholder_tap_action is not None
        and placeholder_ref is not None
    ):
        evidence_ref = {
            "source": "idle_xml",
            "step": "idle",
            "artifact": "capture_idle.png",
            "locator": placeholder_locator,
            "bounds": (
                list(placeholder_ref["bounds"]) if placeholder_ref["bounds"] is not None else None
            ),
            "label": "entry-action",
        }
        _append_option([placeholder_tap_action], [evidence_ref])
        _append_option(
            [{"action": "click_locator", "locator": placeholder_locator}], [evidence_ref]
        )

    for candidate in input_candidates:
        evidence_refs = candidate.get("evidence_refs", [])
        locator = candidate.get("locator")
        bounds = next(
            (
                ref["bounds"]
                for ref in evidence_refs
                if isinstance(ref, dict) and isinstance(ref.get("bounds"), list)
            ),
            None,
        )
        if isinstance(bounds, list) and len(bounds) == 4:
            x1, y1, x2, y2 = bounds
            _append_option(
                [{"action": "tap_xy", "x": (x1 + x2) // 2, "y": (y1 + y2) // 2}],
                evidence_refs,
            )
        if locator is not None:
            _append_option([{"action": "click_locator", "locator": locator}], evidence_refs)

    if not options:
        return None

    recommended_option, recommended_evidence = options[0]
    alternative_candidates = [option for option, _ in options[1:]]
    alternative_evidence_refs = [evidence for _, evidence in options[1:]]
    return {
        "field": "input_focus_action",
        "reason": "Review every viable way to focus the input area before text entry.",
        "recommended_option": recommended_option,
        "alternative_candidates": alternative_candidates,
        "evidence_refs": recommended_evidence,
        "alternative_evidence_refs": alternative_evidence_refs,
    }


def _action_option_from_candidate(candidate: dict) -> list[dict]:
    evidence_refs = candidate.get("evidence_refs", [])
    bounds = next(
        (
            ref["bounds"]
            for ref in evidence_refs
            if isinstance(ref, dict) and isinstance(ref.get("bounds"), list)
        ),
        None,
    )
    if isinstance(bounds, list) and len(bounds) == 4:
        x1, y1, x2, y2 = bounds
        return [{"action": "tap_xy", "x": (x1 + x2) // 2, "y": (y1 + y2) // 2}]
    return [{"action": "click_locator", "locator": candidate["locator"]}]


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

    response_capture = captures["idle"]
    first_response = response_candidates[0]
    input_locator = input_candidates[0]["locator"]
    placeholder_locator = _input_placeholder_locator(idle_xml)
    placeholder_tap_action = _input_placeholder_tap_action(idle_xml)
    input_focus_action = []
    if placeholder_locator is not None:
        input_focus_action = (
            [placeholder_tap_action]
            if placeholder_tap_action is not None
            else [{"action": "click_locator", "locator": placeholder_locator}]
        )
    elif input_candidates:
        input_focus_action = _action_option_from_candidate(input_candidates[0])
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
        "input_locator": input_locator,
        "send_button_locator": send_candidates[0]["locator"],
        "response_extraction": {
            "method": "ui_tree_only",
            "response_container_locator": first_response["response_container_locator"],
            "scroll_container_locator": first_response["scroll_container_locator"],
            "latest_bubble_match": first_response["latest_bubble_match"],
        },
        "new_session_action": [],
        "input_focus_action": input_focus_action,
        "send_action": _action_option_from_candidate(send_candidates[0]),
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
        steps=["idle", "editing"],
        artifact_dir=str(get_settings().data_root / "profile_builder" / session_id),
        artifacts=[],
        captures=[],
    )
    stored = _store_session(session)
    _store_runtime(stored.id, _default_runtime(stored).model_dump(mode="json"))
    try:
        await _activate_builder_adb_keyboard(stored)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"profile builder session setup failed: {exc}",
        ) from exc
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
    if _is_internal_artifact_name(name):
        raise HTTPException(status_code=404, detail="artifact not found")
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
            )
            .model_copy(update={"last_error": str(exc)})
            .model_dump(mode="json"),
        )
        raise HTTPException(
            status_code=502,
            detail=f"profile builder capture connect failed: {exc}",
        ) from exc

    async with _get_session_lock(session_id):
        current_session = _get_session_or_404(session_id)
        _validate_capture_step(current_session, step)
        archived_captures: list[ProfileBuilderCaptureArtifact] = []
        remaining_captures: list[ProfileBuilderCaptureArtifact] = []
        for record in current_session.captures:
            if record.step == step and record.active:
                archived_captures.append(_archive_capture_artifacts(current_session, record))
            else:
                remaining_captures.append(record)
        archived_session = current_session.model_copy(
            update={"captures": remaining_captures + archived_captures}
        )
        stored_archived = _store_session(archived_session)

        try:
            captured = await capture_android_state(
                device=device,
                session_dir=Path(stored_archived.artifact_dir),
                step=step,
                enable_adb_keyboard=False,
            )
        except Exception as exc:
            _store_runtime(
                stored_archived.id,
                _upsert_capture_runtime(
                    _get_runtime(stored_archived),
                    session=stored_archived,
                    step=step,
                    status="failed",
                )
                .model_copy(update={"last_error": str(exc)})
                .model_dump(mode="json"),
            )
            raise HTTPException(
                status_code=502,
                detail=f"profile builder capture failed: {exc}",
            ) from exc

        capture_record = _capture_artifact_from_state(captured)
        captures = [
            record
            for record in stored_archived.captures
            if not (record.step == step and record.active)
        ]
        captures.append(capture_record)
        captures.sort(key=lambda record: _capture_sort_key(stored_archived, record))
        updated = stored_archived.model_copy(update={"captures": captures})
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


@router.put("/sessions/{session_id}/new-session/config", response_model=ProfileBuilderDraftResponse)
async def configure_new_session(
    session_id: str,
    body: ProfileBuilderNewSessionConfigRequest,
) -> ProfileBuilderDraftResponse:
    async with _get_session_lock(session_id):
        session = _get_session_or_404(session_id)
        steps = (
            _resize_new_session_steps(_get_new_session_state(session)["steps"], body.step_count)
            if body.strategy == "guided_tap_sequence"
            else []
        )
        state = _store_new_session_state(
            session.id,
            {"strategy": body.strategy, "steps": steps},
        )
        draft_profile = _draft_profile_for_state(session, state)
        draft_profile_yaml = (
            _write_draft_profile_yaml(session, draft_profile)
            if _draft_profile_path(session).exists()
            else _dump_draft_profile_yaml(draft_profile)
        )
    return _draft_response_payload(
        session=session,
        draft_profile_yaml=draft_profile_yaml,
        state=state,
    )


@router.post(
    "/sessions/{session_id}/new-session/step/{step_index}/capture",
    response_model=ProfileBuilderDraftResponse,
)
async def capture_new_session_step(
    session_id: str,
    step_index: int,
) -> ProfileBuilderDraftResponse:
    session = _get_session_or_404(session_id)
    try:
        device = await asyncio.to_thread(u2.connect, session.device_serial)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"profile builder capture connect failed: {exc}",
        ) from exc

    async with _get_session_lock(session_id):
        session = _get_session_or_404(session_id)
        state = _require_guided_new_session_step(session, step_index)
        step_name = f"new_session_step_{step_index}"
        staged_artifacts = _stage_new_session_step_artifacts_for_recapture(
            session, state["steps"][step_index]
        )

        try:
            captured = await capture_android_state(
                device=device,
                session_dir=Path(session.artifact_dir),
                step=step_name,
                enable_adb_keyboard=False,
            )
        except Exception as exc:
            _restore_staged_new_session_step_artifacts(staged_artifacts)
            raise HTTPException(
                status_code=502,
                detail=f"profile builder capture failed: {exc}",
            ) from exc
        _finalize_staged_new_session_step_artifacts(staged_artifacts)

        step_count = len(state["steps"])
        stored_session = _store_session(session)
        step = {
            "step_index": step_index,
            "xml_artifact": captured.xml_path.name,
            "screenshot_artifact": captured.screenshot_path.name,
            "recommended_tap": {"point": None, "reason": None, "status": "idle"},
            "confirmed_tap": None,
            "source": None,
        }

        xml_text = captured.xml_path.read_text(encoding="utf-8")
        raw_vlm = await get_config("vlm")
        vlm = VLMConfig.model_validate(raw_vlm) if raw_vlm else None
        recommendation_failed = False
        try:
            recommendation = await asyncio.to_thread(
                profile_builder_new_session.recommend_tap_point,
                screenshot_path=captured.screenshot_path,
                xml_text=xml_text,
                step_index=step_index,
                step_count=step_count,
                vlm=vlm,
            )
        except profile_builder_new_session.RecommendationProviderError:
            recommendation_failed = True
        else:
            step["recommended_tap"] = {
                "point": {"x": recommendation["x"], "y": recommendation["y"]},
                "reason": recommendation["reason"],
                "status": "ready",
            }

        if recommendation_failed:
            step["recommended_tap"] = {"point": None, "reason": None, "status": "failed"}

        session = _get_session_or_404(session_id)
        state = _require_guided_new_session_step(session, step_index)
        steps = [dict(item) for item in state["steps"]]
        steps[step_index] = ProfileBuilderNewSessionStep.model_validate(step).model_dump(mode="json")
        state = _store_new_session_state(
            session.id,
            {"strategy": state["strategy"], "steps": steps},
        )
        stored_session = _store_session(session)
        draft_profile = _draft_profile_for_state(stored_session, state)
        draft_profile_yaml = (
            _write_draft_profile_yaml(stored_session, draft_profile)
            if _draft_profile_path(stored_session).exists()
            else _dump_draft_profile_yaml(draft_profile)
        )
    return _draft_response_payload(
        session=stored_session,
        draft_profile_yaml=draft_profile_yaml,
        state=state,
    )


@router.put(
    "/sessions/{session_id}/new-session/step/{step_index}/confirm",
    response_model=ProfileBuilderDraftResponse,
)
async def confirm_new_session_step(
    session_id: str,
    step_index: int,
    body: ProfileBuilderNewSessionConfirmRequest,
) -> ProfileBuilderDraftResponse:
    async with _get_session_lock(session_id):
        session = _get_session_or_404(session_id)
        state = _require_guided_new_session_step(session, step_index)
        steps = [dict(item) for item in state["steps"]]
        updated_step = dict(steps[step_index])
        updated_step["confirmed_tap"] = {"x": body.x, "y": body.y}
        updated_step["source"] = body.source
        steps[step_index] = ProfileBuilderNewSessionStep.model_validate(updated_step).model_dump(
            mode="json"
        )
        state = _store_new_session_state(
            session.id,
            {"strategy": state["strategy"], "steps": steps},
        )
        draft_profile = _draft_profile_for_state(session, state)
        draft_profile_yaml = (
            _write_draft_profile_yaml(session, draft_profile)
            if _draft_profile_path(session).exists()
            else _dump_draft_profile_yaml(draft_profile)
        )
    return _draft_response_payload(
        session=session,
        draft_profile_yaml=draft_profile_yaml,
        state=state,
    )


@router.post("/sessions/{session_id}/draft", response_model=ProfileBuilderDraftResponse)
async def generate_draft(
    session_id: str,
    body: _GenerateDraftRequest = Body(default_factory=_GenerateDraftRequest),
) -> ProfileBuilderDraftResponse:
    session = _get_session_or_404(session_id)
    draft_mode = body.resolved_draft_mode()
    try:
        captures = _require_complete_captures(session)
        idle_xml = _read_capture_xml(session, captures["idle"].xml_artifact)
        editing_xml = _read_capture_xml(session, captures["editing"].xml_artifact)

        candidate_draft = build_android_candidates(
            idle_xml=idle_xml,
            editing_xml=editing_xml,
            response_xml=idle_xml,
        )
        candidates = candidate_draft.asdict()
        rule_draft = _draft_profile_from_candidates(
            session=session,
            captures=captures,
            candidates=candidates,
            idle_xml=idle_xml,
        )
        input_focus_action_review_item = _input_focus_action_review_item(
            idle_xml,
            candidates["input_candidates"],
        )
        if input_focus_action_review_item is not None and not any(
            item.get("field") == "input_focus_action" for item in candidates["review_items"]
        ):
            candidates["review_items"].insert(0, input_focus_action_review_item)
        raw_vlm = await get_config("vlm")
        vlm = VLMConfig.model_validate(raw_vlm) if raw_vlm else VLMConfig()
        llm_output = (
            await maybe_generate_llm_draft(
                vlm=vlm,
                rule_draft=rule_draft,
                candidates=candidates,
                captures={step: capture.model_dump(mode="json") for step, capture in captures.items()},
            )
            if draft_mode == "smart"
            else None
        )
        smart_draft = (
            resolve_smart_draft(
                rule_draft=rule_draft,
                review_items=candidates["review_items"],
                llm_output=llm_output,
            )
            if draft_mode == "smart"
            else None
        )
        draft_profile = (
            smart_draft["draft"] if smart_draft is not None else merge_llm_draft(rule_draft, llm_output)
        )
        new_session_state = _get_new_session_state(session)
        draft_profile["new_session_action"] = _new_session_action_from_state(new_session_state)
        if body.inject_llm:
            if not (vlm.base_url and vlm.model and vlm.api_key):
                raise HTTPException(status_code=400, detail={"error": "llm_config_incomplete"})
            items = list(draft_profile.items())
            insert_after = next(
                (idx + 1 for idx, (key, _) in enumerate(items) if key == "serial"),
                len(items),
            )
            draft_profile = dict(
                items[:insert_after]
                + [("base_url", vlm.base_url), ("model", vlm.model), ("api_key", vlm.api_key)]
                + items[insert_after:]
                + []
            )

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
        draft_profile_yaml = _dump_draft_profile_yaml(draft_profile)
        (artifact_dir / "draft_profile.yaml").write_text(draft_profile_yaml, encoding="utf-8")

        updated = _store_session(session.model_copy(update={"status": "ready"}))
        return _draft_response_payload(
            session=updated,
            draft_profile_yaml=draft_profile_yaml,
            state=new_session_state,
            candidates=candidates,
            review_items=candidates["review_items"],
            draft_mode=draft_mode,
            requires_manual_review=(
                smart_draft["requires_manual_review"] if smart_draft is not None else True
            ),
            applied_review_choices=(
                smart_draft["applied_review_choices"] if smart_draft is not None else {}
            ),
            pending_review_fields=(
                smart_draft["pending_review_fields"]
                if smart_draft is not None
                else [item["field"] for item in candidates["review_items"] if item.get("field")]
            ),
            auto_review_source=(
                smart_draft["auto_review_source"] if smart_draft is not None else "manual"
            ),
        )
    finally:
        await _restore_builder_adb_keyboard(session)


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
        _get_runtime(session)
        .model_copy(
            update={
                "session_status": "validating",
                "current_step": "connectivity",
                "step_state": "running",
                "last_error": None,
                "connectivity": ProfileBuilderRuntimeConnectivity(status="running"),
                "recent_screens": [],
            }
        )
        .model_dump(mode="json"),
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
    runtime_screens = _collect_validation_screens_from_logs(updated_session, result.logs_dir)
    result_summary = result.responses[0] if result.responses else result.error
    _store_runtime(
        updated_session.id,
        _get_runtime(updated_session)
        .model_copy(
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
        )
        .model_dump(mode="json"),
    )
    return {
        "session": updated_session.model_dump(mode="json"),
        "draft_profile_yaml": draft_profile_yaml,
        "connectivity_result": result.model_dump(mode="json"),
    }
