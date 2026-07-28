from __future__ import annotations

from pathlib import Path

from autoagent.utils.tail import tail_lines


def test_missing_file_returns_empty_not_truncated(tmp_path: Path):
    content, truncated = tail_lines(tmp_path / "nope.log", 100)
    assert content == ""
    assert truncated is False


def test_empty_file(tmp_path: Path):
    path = tmp_path / "empty.log"
    path.write_text("")
    content, truncated = tail_lines(path, 100)
    assert content == ""
    assert truncated is False


def test_fewer_lines_than_requested_not_truncated(tmp_path: Path):
    path = tmp_path / "small.log"
    path.write_text("a\nb\nc\n")
    content, truncated = tail_lines(path, 100)
    assert content == "a\nb\nc"
    assert truncated is False


def test_returns_last_n_lines_and_reports_truncated(tmp_path: Path):
    path = tmp_path / "big.log"
    path.write_text("\n".join(f"line{i}" for i in range(1, 101)) + "\n")
    content, truncated = tail_lines(path, 10)
    assert content.splitlines() == [f"line{i}" for i in range(91, 101)]
    assert truncated is True


def test_no_trailing_newline_still_returns_last_line(tmp_path: Path):
    path = tmp_path / "no_trailing_newline.log"
    path.write_text("a\nb\nc")  # no trailing \n
    content, truncated = tail_lines(path, 2)
    assert content == "b\nc"
    assert truncated is True


def test_correct_across_chunk_boundaries(tmp_path: Path, monkeypatch):
    """Force a tiny chunk size so a real multi-chunk backward read happens,
    including a chunk boundary landing mid-line — the exact case the
    partial-first-line trim exists for."""
    import autoagent.utils.tail as tail_mod

    monkeypatch.setattr(tail_mod, "_CHUNK_SIZE", 10)
    path = tmp_path / "chunked.log"
    lines = [f"this is line number {i}" for i in range(1, 51)]
    path.write_text("\n".join(lines) + "\n")

    content, truncated = tail_lines(path, 5)
    assert content.splitlines() == lines[-5:]
    assert truncated is True


def test_requesting_more_lines_than_file_has_after_chunking(tmp_path: Path, monkeypatch):
    import autoagent.utils.tail as tail_mod

    monkeypatch.setattr(tail_mod, "_CHUNK_SIZE", 10)
    path = tmp_path / "chunked2.log"
    lines = [f"L{i}" for i in range(1, 6)]
    path.write_text("\n".join(lines) + "\n")

    content, truncated = tail_lines(path, 100)
    assert content.splitlines() == lines
    assert truncated is False
