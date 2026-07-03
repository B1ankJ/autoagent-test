from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

_ALLOWED = re.compile(r"[a-z0-9_]+")
_log = logging.getLogger(__name__)

# Screenshots are stored as JPEG to cut ~70% off disk vs the raw PNG the
# device screencap emits. Quality 85 is visually lossless for UI captures.
_JPEG_QUALITY = 85


def slug_label(label: str) -> str:
    lowered = label.strip().lower().replace(" ", "_").replace(".", "_")
    parts = _ALLOWED.findall(lowered)
    joined = "_".join(parts)
    return joined or "step"


def encode_jpeg(raw: bytes) -> bytes:
    """Transcode raw PNG screenshot bytes to JPEG. Falls back to raw on error."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
            return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        _log.warning("jpeg transcode failed, storing raw bytes: %s", e)
        return raw


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
        return self._dir / f"{n}_{slug_label(label)}.jpg"

    def artifact_path(self, label: str, suffix: str) -> Path:
        normalized = suffix if suffix.startswith(".") else f".{suffix}"
        return self._dir / f"{slug_label(label)}{normalized}"

    def write_screenshot(self, label: str, raw_png: bytes) -> Path:
        """Transcode a raw screenshot to JPEG and write it as <label>.jpg.

        Central sink for milestone screenshots so the storage format lives in
        one place. Returns the written path. Blocking IO — call via to_thread.
        """
        path = self._dir / f"{slug_label(label)}.jpg"
        path.write_bytes(encode_jpeg(raw_png))
        return path

    @classmethod
    def from_logs_dir(cls, logs_dir: Path) -> ScreenshotStore:
        self = cls.__new__(cls)
        self._dir = logs_dir.resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0
        return self
