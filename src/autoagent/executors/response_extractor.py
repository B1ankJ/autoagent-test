from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from autoagent.executors.ocr import OcrLine, get_engine
from autoagent.executors.scroll_stitcher import stitch_lines


@dataclass
class ExtractionResult:
    text: str
    method_used: str
    ocr_lines: list[str] | None = None
    ui_tree_node_count: int | None = None
    frames: int = 1
    stitched: bool = False


def _is_suspect(text: str) -> bool:
    stripped = text.strip()
    return (
        not stripped or len(stripped) < 3 or stripped.endswith(("...", "…")) or "\ufffc" in stripped
    )


_TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}$")
_UI_CHROME_PATTERNS = (
    "内容由AI生成",
    "深度思考",
    "AI生图",
    "拍题答疑",
    "发消息",
    "按住说话",
)


def _looks_like_ui_chrome(text: str) -> bool:
    stripped = text.strip()
    return bool(
        not stripped
        or _TIME_ONLY.match(stripped)
        or any(pattern in stripped for pattern in _UI_CHROME_PATTERNS)
    )


class UiTreeExtractor:
    def extract_from_xml(self, xml: str, *, bubble_class: str) -> ExtractionResult:
        root = ET.fromstring(xml)
        matches = [node for node in root.iter("node") if node.attrib.get("class") == bubble_class]
        candidates = [
            (index, node.attrib.get("text", "").strip())
            for index, node in enumerate(matches)
            if not _looks_like_ui_chrome(node.attrib.get("text", ""))
        ]
        if candidates:
            text = max(candidates, key=lambda item: (len(item[1]), item[0]))[1]
        else:
            text = ""
        return ExtractionResult(text=text, method_used="ui_tree", ui_tree_node_count=len(matches))


class OcrExtractor:
    async def extract(self, frames: list[bytes]) -> ExtractionResult:
        engine = await get_engine()
        frame_lines: list[list[str]] = []
        all_lines: list[str] = []
        for frame in frames:
            result, _elapsed = engine(frame)
            normalized: list[str] = []
            for item in result or []:
                if len(item) < 3:
                    continue
                _line = OcrLine(
                    text=str(item[1]),
                    bbox=(
                        int(item[0][0][0]),
                        int(item[0][0][1]),
                        int(item[0][2][0]),
                        int(item[0][2][1]),
                    ),
                    confidence=float(item[2]),
                )
                if _line.text.strip():
                    normalized.append(_line.text.strip())
                    all_lines.append(_line.text.strip())
            frame_lines.append(normalized)
        return ExtractionResult(
            text=stitch_lines(frame_lines),
            method_used="ocr",
            ocr_lines=all_lines,
            frames=len(frames),
            stitched=len(frames) > 1,
        )

    async def extract_from_paths(self, paths: list[Path]) -> ExtractionResult:
        frames = [path.read_bytes() for path in paths]
        return await self.extract(frames)


class HybridExtractor:
    def __init__(self, ui_tree: UiTreeExtractor, ocr: OcrExtractor) -> None:
        self.ui_tree = ui_tree
        self.ocr = ocr
