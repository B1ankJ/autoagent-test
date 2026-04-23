from __future__ import annotations

from dataclasses import dataclass

_engine_instance = None
_engine_error: Exception | None = None


@dataclass
class OcrLine:
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float


async def get_engine():
    global _engine_error, _engine_instance
    if _engine_error is not None:
        raise RuntimeError("OCR init failed previously") from _engine_error
    if _engine_instance is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine_instance = RapidOCR()
        except Exception as e:  # noqa: BLE001
            _engine_error = e
            raise
    return _engine_instance
