"""Regression coverage for the connectivity-validation screenshot pipeline.

_collect_validation_screens_from_logs copies milestone screenshots from a
validation sample's logs dir into the builder session's artifact dir. It used
to hardcode .png source/target names, but runtime screenshots write as .jpg
(ScreenshotStore JPEG-transcodes everything) — the same stale-glob class of
bug fixed in notifications/rules.py's same-response VLM judge.
"""
from __future__ import annotations

from autoagent.api.profile_builder import (
    _SCREEN_MEDIA_TYPES,
    _collect_validation_screens_from_logs,
    _runtime_screens_for_validation,
)
from autoagent.models.api import ProfileBuilderSessionView


def _session(artifact_dir) -> ProfileBuilderSessionView:
    return ProfileBuilderSessionView(
        id="pb_1",
        platform="android",
        device_serial="serial-1",
        name="demo",
        status="ready",
        steps=[],
        artifact_dir=str(artifact_dir),
        artifacts=[],
        captures=[],
    )


def test_collects_jpg_screenshots_with_correct_destination_names(tmp_path):
    logs_dir = tmp_path / "logs" / "b1" / "s1"
    logs_dir.mkdir(parents=True)
    names = ("before_input_1.jpg", "after_input_1.jpg", "after_send_1.jpg", "after_result_1.jpg")
    for name in names:
        (logs_dir / name).write_bytes(b"jpeg")

    artifact_dir = tmp_path / "session"
    artifact_dir.mkdir()
    session = _session(artifact_dir)

    screens = _collect_validation_screens_from_logs(session, str(logs_dir))

    paths = {s.path for s in screens}
    assert paths == {
        "validate_before_input.jpg",
        "validate_after_input.jpg",
        "validate_after_send.jpg",
        "validate_after_result.jpg",
    }
    # Destination name drops the source's "_1" index suffix.
    assert "validate_after_input_1.jpg" not in paths
    for s in screens:
        assert (artifact_dir / s.path).exists()
    labels = {s.label for s in screens}
    assert labels == {
        "validate_before_input",
        "validate_after_input",
        "validate_after_send",
        "validate_after_result",
    }


def test_legacy_png_sources_still_collected(tmp_path):
    logs_dir = tmp_path / "logs" / "b1" / "s1"
    logs_dir.mkdir(parents=True)
    (logs_dir / "after_result_1.png").write_bytes(b"png")

    artifact_dir = tmp_path / "session"
    artifact_dir.mkdir()
    session = _session(artifact_dir)

    screens = _collect_validation_screens_from_logs(session, str(logs_dir))

    assert {s.path for s in screens} == {"validate_after_result.png"}
    assert (artifact_dir / "validate_after_result.png").exists()


def test_missing_logs_dir_falls_back_to_existing_artifacts(tmp_path):
    artifact_dir = tmp_path / "session"
    artifact_dir.mkdir()
    (artifact_dir / "validate_on_error.jpg").write_bytes(b"jpeg")
    session = _session(artifact_dir)

    # logs_dir=None (or nonexistent) should still surface whatever the
    # artifact dir already has from a prior run.
    screens = _runtime_screens_for_validation(session)
    assert {s.path for s in screens} == {"validate_on_error.jpg"}


def test_screen_media_types_cover_both_extensions():
    assert _SCREEN_MEDIA_TYPES[".jpg"] == "image/jpeg"
    assert _SCREEN_MEDIA_TYPES[".png"] == "image/png"
