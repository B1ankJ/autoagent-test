from __future__ import annotations

from pathlib import Path

from autoagent.executors.screenshot_store import ScreenshotResult, ScreenshotStore, slug_label


def test_slug_label_keeps_alnum_underscore() -> None:
    assert slug_label("ready_state_01") == "ready_state_01"


def test_slug_label_replaces_spaces_and_dots() -> None:
    assert slug_label("after fill.ok") == "after_fill_ok"


def test_slug_label_lowercases_and_strips_junk() -> None:
    assert slug_label("Ready!!$") == "ready"


def test_slug_label_empty_becomes_step() -> None:
    assert slug_label("") == "step"
    assert slug_label("@#$") == "step"


def test_next_path_creates_parent_dir_and_zero_pads(tmp_path: Path) -> None:
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    p1 = store.next_path("ready")
    p2 = store.next_path("filled")
    assert p1.name == "01_ready.png"
    assert p2.name == "02_filled.png"
    assert p1.parent == tmp_path / "b1" / "s1"
    assert p1.parent.is_dir()


def test_next_path_survives_preexisting(tmp_path: Path) -> None:
    (tmp_path / "b1" / "s1").mkdir(parents=True)
    (tmp_path / "b1" / "s1" / "01_ready.png").write_bytes(b"")
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    p = store.next_path("filled")
    assert p.name == "01_filled.png"


def test_logs_dir_property(tmp_path: Path) -> None:
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    assert store.logs_dir == str((tmp_path / "b1" / "s1").resolve())


def test_artifact_path_keeps_logs_dir_and_suffix(tmp_path: Path) -> None:
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    assert store.artifact_path("after_input", "xml") == tmp_path / "b1" / "s1" / "after_input.xml"


def test_from_logs_dir_reuses_existing_sample_dir(tmp_path: Path) -> None:
    existing = tmp_path / "b1" / "s1"
    existing.mkdir(parents=True)
    store = ScreenshotStore.from_logs_dir(existing)
    assert store.logs_dir == str(existing.resolve())
    assert store.next_path("done").parent == existing


def test_result_metadata_round_trip(tmp_path: Path) -> None:
    result = ScreenshotResult(
        path=tmp_path / "01_ready.png",
        label="ready",
        is_sensitive=True,
        error=None,
    )
    payload = result.to_metadata()
    assert payload["name"] == "01_ready.png"
    assert payload["label"] == "ready"
    assert payload["is_sensitive"] is True
