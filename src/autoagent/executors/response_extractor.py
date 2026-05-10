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
_MIN_BUBBLE_HEIGHT = 8


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


def _expand_winner_text(
    winner_block: list[ET.Element],
    all_blocks: list[list[ET.Element]],
) -> str:
    """Expand the winner block upward by chaining tightly-connected adjacent blocks.

    A chat response can span multiple TextViews whose inter-node gap exceeds
    _group_candidate_blocks' 90 px threshold.  Walking backward through
    spatially-sorted blocks and following a chain where each consecutive gap
    is ≤ 150 px (in the same x-column) captures multi-paragraph replies while
    stopping at genuine message boundaries (which have larger gaps).
    """
    winner_bounds = _node_bounds(winner_block[-1])
    if winner_bounds is None:
        return _block_text(winner_block)

    winner_x = winner_bounds[0]
    sorted_blocks = sorted(
        all_blocks,
        key=lambda b: (_node_bounds(b[0]) or (0, 0, 0, 0))[1],
    )
    winner_sorted_idx = next(
        (i for i, b in enumerate(sorted_blocks) if b is winner_block),
        len(sorted_blocks) - 1,
    )
    connected: list[list[ET.Element]] = [winner_block]
    for i in range(winner_sorted_idx - 1, -1, -1):
        b = sorted_blocks[i]
        b_bounds = _node_bounds(b[-1])
        if b_bounds is None:
            break
        next_top = (_node_bounds(connected[0][0]) or (0, 0, 0, 0))[1]
        gap = next_top - b_bounds[3]
        if abs(b_bounds[0] - winner_x) <= 120 and gap <= 150:
            connected.insert(0, b)
        else:
            break
    return _block_text([node for b in connected for node in b])


def _looks_like_suggestion_chip_block(block: list[ET.Element]) -> bool:
    texts = [(node.attrib.get("text") or "").strip() for node in block]
    texts = [text for text in texts if text]
    if len(texts) < 3:
        return False
    if any(len(text) > 24 for text in texts):
        return False
    total_len = sum(len(text) for text in texts)
    if total_len > 80:
        return False
    heights = []
    for node in block:
        bounds = _node_bounds(node)
        if bounds is None:
            return False
        heights.append(bounds[3] - bounds[1])
    return all(height <= 140 for height in heights)


def _block_score(block: list[ET.Element], *, index: int) -> tuple[int, int, int, int]:
    last = block[-1]
    bounds = _node_bounds(last)
    text = _block_text(block)
    if bounds is None:
        return (0, index, len(text), len(block))
    # Short texts (< 15 chars) are likely suggestion chips or placeholders
    # that sit below the actual response. Apply a y-penalty so a genuine
    # response higher on screen still wins over them.
    y_penalty = 2500 if len(text) < 15 else 0
    return (1, bounds[3] - y_penalty, len(text), index)


def _is_zero_bounds(node: ET.Element) -> bool:
    bounds = _node_bounds(node)
    return bounds is not None and bounds[0] == 0 and bounds[1] == 0 and bounds[2] == 0 and bounds[3] == 0


def _collect_offscreen_text(container: ET.Element, locator: Locator) -> str:
    """Collect text from zero-bounds nodes matching the locator within container.

    WebView-based apps report off-screen nodes with bounds="[0,0][0,0]" instead
    of real coordinates. These are excluded from layout-based extraction but still
    hold the full response text. Collecting them in document order recovers content
    that has scrolled above the visible viewport.
    """
    parts: list[str] = []
    for node in container.iter("node"):
        if not _matches_locator(node, locator):
            continue
        if not _is_zero_bounds(node):
            continue
        text = (node.attrib.get("text") or "").strip()
        if text and not _is_suspect(text) and not _looks_like_ui_chrome(text):
            parts.append(text)
    return " ".join(parts)


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
            if any(len(_block_text(block)) >= 40 for block in blocks):
                non_chip_blocks = [
                    block for block in blocks if not _looks_like_suggestion_chip_block(block)
                ]
                if non_chip_blocks:
                    blocks = non_chip_blocks
            # When substantial blocks exist, filter out short single-node items
            # (suggestion prompts / placeholder chips that sit below the response)
            winner_index, winner_block = max(
                enumerate(blocks),
                key=lambda item: _block_score(item[1], index=item[0]),
            )
            winner_text = _expand_winner_text(winner_block, blocks)
            # Prepend off-screen text from zero-bounds nodes in the same container.
            # WebView-based apps (e.g. Alipay mini-programs) expose scrolled-away
            # content with bounds="[0,0][0,0]"; these are filtered out of candidate
            # blocks but still carry the full response text in document order.
            offscreen_text = _collect_offscreen_text(container, latest_bubble_locator)
            if offscreen_text and offscreen_text not in winner_text:
                winner_text = offscreen_text + " " + winner_text
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
