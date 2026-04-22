from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass
class ExtractionResult:
    text: str
    method_used: str
    ocr_lines: list[str] | None = None
    ui_tree_node_count: int | None = None
    frames: int = 1
    stitched: bool = False


class UiTreeExtractor:
    def extract_from_xml(self, xml: str, *, bubble_class: str) -> ExtractionResult:
        root = ET.fromstring(xml)
        matches = [node for node in root.iter("node") if node.attrib.get("class") == bubble_class]
        text = matches[-1].attrib.get("text", "") if matches else ""
        return ExtractionResult(text=text, method_used="ui_tree", ui_tree_node_count=len(matches))
