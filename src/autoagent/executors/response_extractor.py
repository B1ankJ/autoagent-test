from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from autoagent.executors.ocr import get_engine
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
        not stripped
        or len(stripped) < 3
        or stripped.endswith(("...", "…"))
        or "\ufffc" in stripped
    )


class UiTreeExtractor:
    def extract_from_xml(self, xml: str, *, bubble_class: str) -> ExtractionResult:
        root = ET.fromstring(xml)
        matches = [node for node in root.iter("node") if node.attrib.get("class") == bubble_class]
        text = matches[-1].attrib.get("text", "") if matches else ""
        return ExtractionResult(text=text, method_used="ui_tree", ui_tree_node_count=len(matches))


class OcrExtractor:
    async def extract(self, frames: list[bytes]) -> ExtractionResult:
        await get_engine()
        return ExtractionResult(
            text=stitch_lines([[] for _ in frames]),
            method_used="ocr",
            frames=len(frames),
            stitched=len(frames) > 1,
        )


class HybridExtractor:
    def __init__(self, ui_tree: UiTreeExtractor, ocr: OcrExtractor) -> None:
        self.ui_tree = ui_tree
        self.ocr = ocr
