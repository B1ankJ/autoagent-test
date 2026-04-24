from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from autoagent.executors.ocr import OcrLine, get_engine
from autoagent.executors.scroll_stitcher import stitch_lines
from autoagent.profiles.schemas import Locator


@dataclass
class ExtractionResult:
    text: str
    method_used: str
    ocr_lines: list[str] | None = None
    ui_tree_node_count: int | None = None
    frames: int = 1
    stitched: bool = False
    container_found: bool = True
    matched_locator_count: int | None = None


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
_MIN_BUBBLE_HEIGHT = 80


def _looks_like_ui_chrome(text: str) -> bool:
    stripped = text.strip()
    return bool(
        not stripped
        or _TIME_ONLY.match(stripped)
        or any(pattern in stripped for pattern in _UI_CHROME_PATTERNS)
    )


def _matches_locator(node: ET.Element, locator: Locator) -> bool:
    if locator.type == "resource_id":
        return node.attrib.get("resource-id") == locator.value
    if locator.type == "text":
        return node.attrib.get("text", "").strip() == locator.value
    if locator.type == "class":
        return node.attrib.get("class") == locator.value
    if locator.type == "last_child_with_class":
        return node.attrib.get("class") == locator.value
    if locator.type == "xpath":
        value = locator.value
        bounds_match = re.fullmatch(r'//\*\[@bounds="([^"]+)"\]', value)
        if bounds_match:
            return node.attrib.get("bounds") == bounds_match.group(1)
        class_match = re.fullmatch(r'//\*\[@class="([^"]+)"\]', value)
        if class_match:
            return node.attrib.get("class") == class_match.group(1)
        text_contains_match = re.fullmatch(r'//\*\[contains\(@text, "([^"]+)"\)\]', value)
        if text_contains_match:
            return text_contains_match.group(1) in node.attrib.get("text", "")
        return False
    return False


def _find_first_match(root: ET.Element, locator: Locator) -> ET.Element | None:
    for node in root.iter("node"):
        if _matches_locator(node, locator):
            return node
    return None


def _find_all_matches(root: ET.Element, locator: Locator) -> list[ET.Element]:
    return [node for node in root.iter("node") if _matches_locator(node, locator)]


def _candidate_nodes(container: ET.Element, locator: Locator) -> list[ET.Element]:
    matches = [node for node in container.iter("node") if _matches_locator(node, locator)]
    if locator.type == "last_child_with_class":
        return matches[-1:] if matches else []
    return matches


def _requires_strict_container_match(locator: Locator) -> bool:
    return locator.type == "xpath" and "@bounds=" in locator.value


def _node_bounds(node: ET.Element) -> tuple[int, int, int, int] | None:
    raw = node.attrib.get("bounds")
    if not raw:
        return None
    normalized = raw.replace("][", ",").replace("[", "").replace("]", "")
    parts = normalized.split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _bubble_score(node: ET.Element, *, index: int) -> tuple[int, int, int, int]:
    bounds = _node_bounds(node)
    text = node.attrib.get("text", "").strip()
    if bounds is not None:
        return (1, bounds[3], len(text), index)
    return (0, index, len(text), index)


def _is_latest_bubble_candidate(node: ET.Element) -> bool:
    bounds = _node_bounds(node)
    if bounds is not None and (bounds[3] - bounds[1]) < _MIN_BUBBLE_HEIGHT:
        return False
    return not _looks_like_ui_chrome(node.attrib.get("text", ""))


def _group_candidate_blocks(
    nodes: list[ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> list[list[ET.Element]]:
    if not nodes:
        return []
    ordered = sorted(
        nodes,
        key=lambda node: (
            (_node_bounds(node) or (0, 0, 0, 0))[1],
            (_node_bounds(node) or (0, 0, 0, 0))[0],
        ),
    )
    blocks: list[list[ET.Element]] = []
    current: list[ET.Element] = []
    for node in ordered:
        bounds = _node_bounds(node)
        if bounds is None:
            if current:
                blocks.append(current)
            current = [node]
            continue
        if not current:
            current = [node]
            continue
        prev_bounds = _node_bounds(current[-1])
        if prev_bounds is None:
            blocks.append(current)
            current = [node]
            continue
        same_parent = parents.get(current[-1]) is parents.get(node)
        same_column = abs(bounds[0] - prev_bounds[0]) <= 120
        close_vertically = bounds[1] - prev_bounds[3] <= 90
        if same_parent and same_column and close_vertically:
            current.append(node)
            continue
        blocks.append(current)
        current = [node]
    if current:
        blocks.append(current)
    return blocks


def _block_text(block: list[ET.Element]) -> str:
    return " ".join((node.attrib.get("text") or "").strip() for node in block if (node.attrib.get("text") or "").strip())


def _block_score(block: list[ET.Element], *, index: int) -> tuple[int, int, int, int]:
    last = block[-1]
    bounds = _node_bounds(last)
    text = _block_text(block)
    if bounds is None:
        return (0, index, len(text), len(block))
    return (1, bounds[3], len(text), index)


class UiTreeExtractor:
    def extract_from_xml(
        self,
        xml: str,
        *,
        response_container_locator: Locator,
        latest_bubble_locator: Locator,
    ) -> ExtractionResult:
        root = ET.fromstring(xml)
        parents = {child: parent for parent in root.iter() for child in parent}
        containers = _find_all_matches(root, response_container_locator)
        if not containers:
            if _requires_strict_container_match(response_container_locator):
                return ExtractionResult(
                    text="",
                    method_used="ui_tree",
                    ui_tree_node_count=0,
                    container_found=False,
                    matched_locator_count=0,
                )
            containers = [root]

        best_text = ""
        best_container_found = False
        best_count = 0
        best_score: tuple[int, int, int] | None = None

        for container in containers:
            matches = _candidate_nodes(container, latest_bubble_locator)
            candidate_nodes = [
                node
                for node in matches
                if _is_latest_bubble_candidate(node) and not _is_suspect(node.attrib.get("text", ""))
            ]
            blocks = _group_candidate_blocks(candidate_nodes, parents)
            if not blocks:
                continue
            winner_index, winner_block = max(
                enumerate(blocks),
                key=lambda item: _block_score(item[1], index=item[0]),
            )
            winner_text = _block_text(winner_block)
            winner_score = _block_score(winner_block, index=winner_index)
            if best_score is None or winner_score > best_score:
                best_score = winner_score
                best_text = winner_text
                best_container_found = True
                best_count = len(matches)

        return ExtractionResult(
            text=best_text,
            method_used="ui_tree",
            ui_tree_node_count=best_count,
            container_found=best_container_found,
            matched_locator_count=best_count,
        )


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
