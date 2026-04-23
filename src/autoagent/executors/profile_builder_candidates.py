from dataclasses import asdict, dataclass
from xml.etree import ElementTree


@dataclass
class AndroidCandidateDraft:
    input_candidates: list[dict]
    send_candidates: list[dict]
    response_candidates: list[dict]
    review_items: list[dict]

    def asdict(self) -> dict:
        return asdict(self)


def _parse_bounds(raw: str | None) -> tuple[int, int, int, int] | None:
    if not raw or not raw.startswith("["):
        return None
    normalized = raw.replace("][", ",").replace("[", "").replace("]", "")
    parts = normalized.split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _bounds_area(bounds: tuple[int, int, int, int] | None) -> int:
    if bounds is None:
        return 0
    x1, y1, x2, y2 = bounds
    return max(0, x2 - x1) * max(0, y2 - y1)


def _node_attrs(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    return [dict(node.attrib) for node in root.iter() if node is not root]


def _xpath_locator(value: str) -> dict:
    return {"type": "xpath", "value": value}


def _class_locator(value: str) -> dict:
    return {"type": "class", "value": value}


def _build_input_candidates(editing_nodes: list[dict[str, str]], idle_nodes: list[dict[str, str]]) -> list[dict]:
    candidates: list[dict] = []
    for node in editing_nodes:
        if node.get("class") != "android.widget.EditText":
            continue
        bounds = _parse_bounds(node.get("bounds"))
        candidates.append(
            {
                "locator": _xpath_locator('//*[@class="android.widget.EditText"]'),
                "score": 100 + _bounds_area(bounds),
                "reason": "editing EditText",
            }
        )
    if candidates:
        return sorted(candidates, key=lambda item: item["score"], reverse=True)

    for node in idle_nodes:
        text = node.get("text", "").strip()
        if not text:
            continue
        candidates.append(
            {
                "locator": _xpath_locator(f'//*[contains(@text, "{text}")]'),
                "score": len(text),
                "reason": "idle text placeholder",
            }
        )
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _build_send_candidates(editing_nodes: list[dict[str, str]]) -> list[dict]:
    ranked: list[tuple[tuple[int, int, int], dict]] = []
    for node in editing_nodes:
        if node.get("clickable") != "true":
            continue
        bounds_raw = node.get("bounds")
        bounds = _parse_bounds(bounds_raw)
        if bounds is None or bounds_raw is None:
            continue
        x1, y1, x2, y2 = bounds
        ranked.append(
            (
                (x2, y2, _bounds_area(bounds)),
                {
                    "locator": _xpath_locator(f'//*[@bounds="{bounds_raw}"]'),
                    "score": x2 + y2,
                    "reason": "rightmost clickable near bottom",
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked]


def _build_response_candidates(response_nodes: list[dict[str, str]]) -> list[dict]:
    by_class: dict[str, list[dict[str, str]]] = {}
    for node in response_nodes:
        node_class = node.get("class")
        if node_class != "android.widget.TextView":
            continue
        text = node.get("text", "").strip()
        if not text:
            continue
        by_class.setdefault(node_class, []).append(node)

    candidates: list[dict] = []
    for node_class, nodes in by_class.items():
        size_score = sum(max(len(node.get("text", "").strip()), 1) for node in nodes)
        candidates.append(
            {
                "response_container_locator": _class_locator(node_class),
                "scroll_container_locator": _class_locator(node_class),
                "latest_bubble_match": _class_locator(node_class),
                "score": len(nodes) * 100 + size_score,
                "reason": "repeated response TextView nodes",
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _build_review_items(
    input_candidates: list[dict],
    send_candidates: list[dict],
    response_candidates: list[dict],
) -> list[dict]:
    review_items: list[dict] = []
    if len(input_candidates) > 1:
        review_items.append(
            {
                "field": "input_locator",
                "reason": "Multiple input candidates matched the editing capture.",
                "candidate_count": len(input_candidates),
            }
        )
    if len(send_candidates) > 1:
        review_items.append(
            {
                "field": "send_button_locator",
                "reason": "Multiple clickable controls looked like send buttons.",
                "candidate_count": len(send_candidates),
            }
        )
    if response_candidates:
        review_items.append(
            {
                "field": "latest_bubble_match",
                "reason": "Response extraction is heuristic and should be confirmed.",
                "candidate_count": len(response_candidates),
            }
        )
    return review_items


def build_android_candidates(
    *,
    idle_xml: str,
    editing_xml: str,
    response_xml: str,
) -> AndroidCandidateDraft:
    idle_nodes = _node_attrs(idle_xml)
    editing_nodes = _node_attrs(editing_xml)
    response_nodes = _node_attrs(response_xml)

    input_candidates = _build_input_candidates(editing_nodes, idle_nodes)
    send_candidates = _build_send_candidates(editing_nodes)
    response_candidates = _build_response_candidates(response_nodes)
    review_items = _build_review_items(input_candidates, send_candidates, response_candidates)

    return AndroidCandidateDraft(
        input_candidates=input_candidates,
        send_candidates=send_candidates,
        response_candidates=response_candidates,
        review_items=review_items,
    )
