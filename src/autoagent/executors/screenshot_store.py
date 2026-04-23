from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ALLOWED = re.compile(r"[a-z0-9_]+")


def slug_label(label: str) -> str:
    lowered = label.strip().lower().replace(" ", "_").replace(".", "_")
    parts = _ALLOWED.findall(lowered)
    joined = "_".join(parts)
    return joined or "step"


@dataclass(frozen=True)
class ScreenshotResult:
    path: Path
    label: str
    is_sensitive: bool = False
    error: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "name": self.path.name,
            "label": self.label,
            "is_sensitive": self.is_sensitive,
            "error": self.error,
        }


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

    def artifact_path(self, label: str, suffix: str) -> Path:
        normalized = suffix if suffix.startswith(".") else f".{suffix}"
        return self._dir / f"{slug_label(label)}{normalized}"

    @classmethod
    def from_logs_dir(cls, logs_dir: Path) -> ScreenshotStore:
        self = cls.__new__(cls)
        self._dir = logs_dir.resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0
        return self
