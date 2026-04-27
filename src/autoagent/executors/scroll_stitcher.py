from __future__ import annotations


def stitch_lines(frames: list[list[str]]) -> str:
    merged: list[str] = []
    for frame in frames:
        normalized = [line.strip() for line in frame if line.strip()]
        overlap = 0
        for n in range(min(3, len(merged), len(normalized)), 0, -1):
            if merged[-n:] == normalized[:n]:
                overlap = n
                break
        merged.extend(normalized[overlap:])
    return "\n".join(merged)
