from __future__ import annotations

from pathlib import Path

_CHUNK_SIZE = 65536


def tail_lines(path: Path, max_lines: int) -> tuple[str, bool]:
    """Return the last `max_lines` lines of a text file, plus whether the
    file had more lines before that (i.e. this isn't the whole file).

    Reads backward from the end in fixed-size chunks until either enough
    newlines have been seen or the start of the file is reached, so memory
    use is bounded by roughly `max_lines`' worth of trailing bytes rather
    than the file size — Settings.log_file has no rotation, so this is the
    only way to view it without risking loading a multi-GB file into memory.
    """
    if not path.exists() or not path.is_file():
        return "", False
    with path.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        blocks: list[bytes] = []
        newline_count = 0
        while pos > 0 and newline_count <= max_lines:
            read_size = min(_CHUNK_SIZE, pos)
            pos -= read_size
            f.seek(pos)
            blocks.append(f.read(read_size))
            newline_count += blocks[-1].count(b"\n")
        data = b"".join(reversed(blocks))
    lines = data.decode("utf-8", errors="replace").splitlines()
    if pos > 0 and lines:
        # The earliest line we read may have been split mid-line at the
        # chunk boundary (pos isn't guaranteed to land right after a `\n`
        # unless we reached the true start of the file) — drop it rather
        # than show a garbled partial line.
        lines = lines[1:]
    # Truncated whenever there's more before what we kept — either we
    # stopped reading early (pos > 0), or we read everything (even a small
    # file can come back in a single chunk) but it still has more lines
    # than requested.
    truncated = pos > 0 or len(lines) > max_lines
    return "\n".join(lines[-max_lines:]), truncated
