from __future__ import annotations

import re
from pathlib import Path

_ALLOWED = re.compile(r"[a-z0-9_]+")


def slug_label(label: str) -> str:
    lowered = label.strip().lower().replace(" ", "_").replace(".", "_")
    parts = _ALLOWED.findall(lowered)
    joined = "_".join(parts)
    return joined or "step"


class ScreenshotStore:
    """Computes per-sample screenshot file paths under <root>/<batch_id>/<sample_id>/."""

    def __init__(self, root: Path, batch_id: str, sample_id: str) -> None:
        self._dir = (root / batch_id / sample_id).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    @property
    def logs_dir(self) -> str:
        return str(self._dir)

    def next_path(self, label: str) -> Path:
        self._counter += 1
        n = f"{self._counter:02d}" if self._counter < 100 else f"{self._counter:03d}"
        return self._dir / f"{n}_{slug_label(label)}.png"
