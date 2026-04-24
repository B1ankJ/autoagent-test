from dataclasses import asdict, dataclass
from xml.etree import ElementTree

_INPUT_HINT_KEYWORDS = ("发消息", "说话", "输入", "send", "message", "chat")
_RESPONSE_UI_CHROME_PATTERNS = (
    "内容由AI生成",
    "深度思考",
    "AI生图",
    "AI打车",
    "拍题答疑",
    "发消息",
    "按住说话",
)
_SYSTEM_PACKAGE_PREFIXES = (
    "com.android.systemui",
    "com.baidu.input",
    "com.google.android.inputmethod",
)


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


def _element_bounds(node: ElementTree.Element) -> tuple[int, int, int, int] | None:
    return _parse_bounds(node.attrib.get("bounds"))


def _node_attrs(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    return [dict(node.attrib) for node in root.iter() if node is not root]


def _xpath_locator(value: str) -> dict:
    return {"type": "xpath", "value": value}


def _class_locator(value: str) -> dict:
    return {"type": "class", "value": value}


def _resource_id_locator(value: str) -> dict:
    return {"type": "resource_id", "value": value}


def _bounds_payload(bounds: tuple[int, int, int, int] | None) -> list[int] | None:
    if bounds is None:
        return None
    return [bounds[0], bounds[1], bounds[2], bounds[3]]


def _evidence_ref(
    *,
    source: str,
    step: str,
    artifact: str,
    locator: dict | None = None,
    bounds: tuple[int, int, int, int] | None = None,
    label: str | None = None,
    text: str | None = None,
    scroll_locator: dict | None = None,
    text_count: int | None = None,
    total_text_length: int | None = None,
) -> dict:
    ref: dict[str, object] = {
        "source": source,
        "step": step,
        "artifact": artifact,
    }
    if locator is not None:
        ref["locator"] = locator
    if bounds is not None:
        ref["bounds"] = _bounds_payload(bounds)
    if label is not None:
        ref["label"] = label
    if text is not None:
        ref["text"] = text
    if scroll_locator is not None:
        ref["scroll_locator"] = scroll_locator
    if text_count is not None:
        ref["text_count"] = text_count
    if total_text_length is not None:
        ref["total_text_length"] = total_text_length
    return ref


def _app_package(nodes: list[dict[str, str]]) -> str | None:
    package_counts: dict[str, int] = {}
    for node in nodes:
        package = node.get("package", "").strip()
        if not package:
            continue
        if any(package.startswith(prefix) for prefix in _SYSTEM_PACKAGE_PREFIXES):
            continue
        package_counts[package] = package_counts.get(package, 0) + 1
    if not package_counts:
        return None
    return max(package_counts.items(), key=lambda item: item[1])[0]


def _locator_from_node(node: ElementTree.Element | None) -> dict:
    if node is None:
        return _class_locator("android.widget.TextView")
    bounds = node.attrib.get("bounds")
    if bounds:
        return _xpath_locator(f'//*[@bounds="{bounds}"]')
    node_class = node.attrib.get("class")
    if node_class:
        return _xpath_locator(f'//*[@class="{node_class}"]')
    return _class_locator("android.widget.TextView")


def _stable_locator_from_node(node: ElementTree.Element | None) -> dict:
    if node is None:
        return _class_locator("android.widget.TextView")
    resource_id = (node.attrib.get("resource-id") or "").strip()
    if resource_id:
        return _resource_id_locator(resource_id)
    node_class = (node.attrib.get("class") or "").strip()
    if node_class:
        return _class_locator(node_class)
    bounds = node.attrib.get("bounds")
    if bounds:
        return _xpath_locator(f'//*[@bounds="{bounds}"]')
    return _class_locator("android.widget.TextView")


def _candidate_key(candidate: dict) -> str:
    locator = candidate.get("locator") or {}
    return f"{locator.get('type')}:{locator.get('value')}"


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        existing = deduped.get(key)
        if existing is None or candidate.get("score", 0) > existing.get("score", 0):
            deduped[key] = {
                **candidate,
                "evidence_refs": list(candidate.get("evidence_refs", [])),
            }
            continue
        merged_refs = existing.setdefault("evidence_refs", [])
        for ref in candidate.get("evidence_refs", []):
            if ref not in merged_refs:
                merged_refs.append(ref)
    return sorted(deduped.values(), key=lambda item: item.get("score", 0), reverse=True)


def _composer_region(bounds: tuple[int, int, int, int] | None) -> bool:
    if bounds is None:
        return False
    _x1, y1, _x2, y2 = bounds
    return y2 >= 1200 or y1 >= 1100


def _is_input_hint_text(text: str) -> bool:
    lowered = text.lower()
    return bool(text and any(keyword in lowered for keyword in _INPUT_HINT_KEYWORDS))


def _node_locator(node: dict[str, str], fallback_class: str) -> dict:
    resource_id = (node.get("resource-id") or "").strip()
    if resource_id:
        return _resource_id_locator(resource_id)
    bounds_raw = node.get("bounds")
    if bounds_raw:
        return _xpath_locator(f'//*[@bounds="{bounds_raw}"]')
    node_class = (node.get("class") or "").strip()
    if node_class:
        return _class_locator(node_class)
    return _class_locator(fallback_class)


def _build_input_candidates(
    editing_nodes: list[dict[str, str]],
    idle_nodes: list[dict[str, str]],
) -> list[dict]:
    candidates: list[dict] = []

    for index, node in enumerate(editing_nodes):
        if node.get("class") != "android.widget.EditText":
            continue
        bounds = _parse_bounds(node.get("bounds"))
        locator = _xpath_locator(f'//*[@bounds="{node["bounds"]}"]') if node.get("bounds") else _xpath_locator('//*[@class="android.widget.EditText"]')
        candidates.append(
            {
                "locator": locator,
                "score": 2000 - index,
                "reason": "editing EditText",
                "evidence_refs": [
                    _evidence_ref(
                        source="editing_xml",
                        step="editing",
                        artifact="capture_editing.png",
                        locator=locator,
                        bounds=bounds,
                        label="input",
                        text=(node.get("text") or "").strip() or None,
                    )
                ],
            }
        )

    def _placeholder_candidates(nodes: list[dict[str, str]], *, source: str) -> None:
        for index, node in enumerate(nodes):
            text = node.get("text", "").strip()
            if not _is_input_hint_text(text):
                continue
            bounds = _parse_bounds(node.get("bounds"))
            locator = (
                _xpath_locator(f'//*[@bounds="{node["bounds"]}"]')
                if node.get("bounds")
                else _xpath_locator(f'//*[contains(@text, "{text}")]')
            )
            candidates.append(
                {
                    "locator": locator,
                    "score": (1000 if source == "idle_xml" else 1400) - index,
                    "reason": f"{source.split('_')[0]} input placeholder",
                    "evidence_refs": [
                        _evidence_ref(
                            source=source,
                            step="editing" if source == "editing_xml" else "idle",
                            artifact=(
                                "capture_editing.png"
                                if source == "editing_xml"
                                else "capture_idle.png"
                            ),
                            locator=locator,
                            bounds=bounds,
                            label="input-placeholder",
                            text=text,
                        )
                    ],
                }
            )

    def _composer_proxy_candidates(nodes: list[dict[str, str]], *, source: str) -> None:
        for index, node in enumerate(nodes):
            bounds = _parse_bounds(node.get("bounds"))
            if not _composer_region(bounds):
                continue
            if node.get("class") == "android.widget.EditText":
                continue
            if node.get("clickable") != "true" and node.get("focusable") != "true":
                continue
            area = _bounds_area(bounds)
            if area <= 0 or area > 400_000:
                continue
            locator = _node_locator(node, "android.widget.EditText")
            candidates.append(
                {
                    "locator": locator,
                    "score": 900 - index + min(area // 2000, 180),
                    "reason": f"{source.split('_')[0]} composer proxy",
                    "evidence_refs": [
                        _evidence_ref(
                            source=source,
                            step="editing" if source == "editing_xml" else "idle",
                            artifact=(
                                "capture_editing.png"
                                if source == "editing_xml"
                                else "capture_idle.png"
                            ),
                            locator=locator,
                            bounds=bounds,
                            label="input-proxy",
                            text=(node.get("text") or "").strip() or None,
                        )
                    ],
                }
            )

    _placeholder_candidates(editing_nodes, source="editing_xml")
    _placeholder_candidates(idle_nodes, source="idle_xml")
    _composer_proxy_candidates(editing_nodes, source="editing_xml")
    _composer_proxy_candidates(idle_nodes, source="idle_xml")
    return _dedupe_candidates(candidates)


def _build_send_candidates(editing_nodes: list[dict[str, str]]) -> list[dict]:
    return _build_send_candidates_from_nodes(editing_nodes, source="editing_xml")


def _build_send_candidates_from_nodes(
    editing_nodes: list[dict[str, str]],
    *,
    source: str,
) -> list[dict]:
    app_package = _app_package(editing_nodes)
    candidates: list[dict] = []
    for index, node in enumerate(editing_nodes):
        if node.get("clickable") != "true":
            continue
        package = node.get("package", "").strip()
        if app_package and package and package != app_package:
            continue
        bounds_raw = node.get("bounds")
        bounds = _parse_bounds(bounds_raw)
        if bounds is None or bounds_raw is None:
            continue
        x1, y1, x2, y2 = bounds
        width = x2 - x1
        height = y2 - y1
        area = _bounds_area(bounds)
        if not _composer_region(bounds):
            continue
        if width < 24 or height < 24:
            continue
        if area > 240_000:
            continue
        locator = _xpath_locator(f'//*[@bounds="{bounds_raw}"]')
        score = y2 + x2 - (area // 5000) - index
        if x1 > 700:
            score += 400
        if area < 20_000:
            score += 120
        candidates.append(
            {
                "locator": locator,
                "score": score,
                "reason": "composer clickable control",
                "evidence_refs": [
                    _evidence_ref(
                        source=source,
                        step="connectivity" if source == "runtime_probe_xml" else "editing",
                        artifact=(
                            "runtime_probe_editing.png"
                            if source == "runtime_probe_xml"
                            else "capture_editing.png"
                        ),
                        locator=locator,
                        bounds=bounds,
                        label="send-button",
                    )
                ],
            }
        )
    return _dedupe_candidates(candidates)


def _element_depth(
    node: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> int:
    depth = 0
    current = node
    while current in parents:
        current = parents[current]
        depth += 1
    return depth


def _nearest_message_container(
    text_node: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> ElementTree.Element:
    current = text_node
    while current in parents:
        parent = parents[current]
        text_descendants = [
            descendant
            for descendant in parent.iter()
            if descendant is not parent
            and descendant.attrib.get("class") == "android.widget.TextView"
            and (descendant.attrib.get("text") or "").strip()
        ]
        if len(text_descendants) >= 2:
            return parent
        current = parent
    return text_node


def _nearest_scroll_container(
    node: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> ElementTree.Element | None:
    current: ElementTree.Element | None = node
    while current is not None:
        node_class = current.attrib.get("class", "")
        if current.attrib.get("scrollable") == "true" or any(
            marker in node_class for marker in ("RecyclerView", "ListView", "ScrollView")
        ):
            return current
        current = parents.get(current)
    return None


def _latest_bubble_locator(text_nodes: list[ElementTree.Element]) -> dict:
    classes = {node.attrib.get("class") for node in text_nodes if node.attrib.get("class")}
    if len(classes) == 1:
        return _class_locator(next(iter(classes)))
    fallback = text_nodes[-1].attrib.get("class") if text_nodes else None
    if fallback:
        return _class_locator(fallback)
    return _class_locator("android.widget.TextView")


def _group_response_blocks(
    text_nodes: list[ElementTree.Element],
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> list[list[ElementTree.Element]]:
    if not text_nodes:
        return []
    ordered = sorted(
        text_nodes,
        key=lambda node: (
            (_element_bounds(node) or (0, 0, 0, 0))[1],
            (_element_bounds(node) or (0, 0, 0, 0))[0],
        ),
    )
    blocks: list[list[ElementTree.Element]] = []
    current: list[ElementTree.Element] = []
    for node in ordered:
        bounds = _element_bounds(node)
        if bounds is None:
            if current:
                blocks.append(current)
            current = [node]
            continue
        if not current:
            current = [node]
            continue
        previous_bounds = _element_bounds(current[-1])
        if previous_bounds is None:
            blocks.append(current)
            current = [node]
            continue
        same_parent = parents.get(current[-1]) is parents.get(node)
        same_column = abs(bounds[0] - previous_bounds[0]) <= 120
        close_vertically = bounds[1] - previous_bounds[3] <= 90
        if same_parent and same_column and close_vertically:
            current.append(node)
            continue
        blocks.append(current)
        current = [node]
    if current:
        blocks.append(current)
    return blocks


def _block_text(text_nodes: list[ElementTree.Element]) -> str:
    parts = [(node.attrib.get("text") or "").strip() for node in text_nodes]
    return " ".join(part for part in parts if part)


def _review_locator_from_node(node: ElementTree.Element) -> dict:
    bounds = node.attrib.get("bounds")
    if bounds:
        return _xpath_locator(f'//*[@bounds="{bounds}"]')
    node_class = node.attrib.get("class")
    if node_class:
        return _class_locator(node_class)
    return _class_locator("android.widget.TextView")


def _looks_like_response_ui_chrome(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and any(pattern in stripped for pattern in _RESPONSE_UI_CHROME_PATTERNS))


def _response_text_score(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return -2000
    if _looks_like_response_ui_chrome(stripped):
        return -4000
    if len(stripped) <= 3:
        return -1200
    return min(len(stripped) * 8, 320)


def _response_layout_score(bounds: tuple[int, int, int, int] | None) -> int:
    if bounds is None:
        return 0
    x1, y1, x2, y2 = bounds
    width = x2 - x1
    score = y2
    if y2 > 1850:
        score -= 2500
    if width > 600 and x1 < 120:
        score += 600
    if x1 > 300:
        score -= 900
    if width < 280:
        score -= 600
    if y1 < 180:
        score -= 300
    return score


def _response_review_option(candidate: dict) -> dict:
    option = {
        "response_container_locator": candidate["response_container_locator"],
        "scroll_container_locator": candidate["scroll_container_locator"],
        "latest_bubble_match": candidate["review_latest_bubble_match"],
        "resolved_latest_bubble_match": candidate["latest_bubble_match"],
        "bubble_preview": candidate["bubble_preview"],
    }
    return option


def _response_candidate(
    *,
    container: ElementTree.Element,
    scroll_container: ElementTree.Element | None,
    text_nodes: list[ElementTree.Element],
    bubble_nodes: list[ElementTree.Element],
) -> dict:
    container_bounds = _parse_bounds(container.attrib.get("bounds"))
    total_text_len = sum(len((node.attrib.get("text") or "").strip()) for node in text_nodes)
    repeated_count = len(text_nodes)
    container_bonus = 60 if repeated_count >= 2 else 0
    scroll_bonus = 40 if scroll_container is not None else 0
    bubble_node = bubble_nodes[-1]
    bubble_bounds = _parse_bounds(bubble_node.attrib.get("bounds"))
    bubble_text = _block_text(bubble_nodes)
    score = repeated_count * 100 + total_text_len * 5 + _bounds_area(container_bounds) // 1000
    locator = _stable_locator_from_node(scroll_container or container)
    scroll_locator = _stable_locator_from_node(scroll_container or container)
    latest_locator = _latest_bubble_locator(text_nodes)
    return {
        "response_container_locator": locator,
        "scroll_container_locator": scroll_locator,
        "latest_bubble_match": latest_locator,
        "review_latest_bubble_match": _review_locator_from_node(bubble_node),
        "bubble_preview": bubble_text[:80],
        "score": (
            score
            + container_bonus
            + scroll_bonus
            + _response_layout_score(bubble_bounds)
            + _response_text_score(bubble_text)
        ),
        "reason": "visible response text node inside repeated response container",
        "evidence_refs": [
            _evidence_ref(
                source="idle_xml",
                step="idle",
                artifact="capture_idle.png",
                locator=_review_locator_from_node(bubble_node),
                bounds=bubble_bounds,
                label="response-bubble",
                text=bubble_text,
            ),
            _evidence_ref(
                source="idle_xml",
                step="idle",
                artifact="capture_idle.png",
                locator=locator,
                bounds=container_bounds,
                label="response-container",
                scroll_locator=scroll_locator,
                text_count=repeated_count,
                total_text_length=total_text_len,
            )
        ],
    }


def _build_response_candidates(response_xml: str) -> list[dict]:
    root = ElementTree.fromstring(response_xml)
    parents = {child: parent for parent in root.iter() for child in parent}
    text_nodes = [
        node
        for node in root.iter()
        if node.attrib.get("class") == "android.widget.TextView"
        and (node.attrib.get("text") or "").strip()
    ]
    grouped: dict[ElementTree.Element, list[ElementTree.Element]] = {}
    for text_node in text_nodes:
        grouped.setdefault(_nearest_message_container(text_node, parents), []).append(text_node)

    ranked: list[tuple[tuple[int, int, int], dict]] = []
    for container, grouped_text_nodes in grouped.items():
        if not grouped_text_nodes:
            continue
        scroll_container = _nearest_scroll_container(container, parents)
        for bubble_nodes in _group_response_blocks(grouped_text_nodes, parents):
            candidate = _response_candidate(
                container=container,
                scroll_container=scroll_container,
                text_nodes=grouped_text_nodes,
                bubble_nodes=bubble_nodes,
            )
            ranked.append(
                (
                    (
                        candidate["score"],
                        len(bubble_nodes),
                        _element_depth(container, parents),
                    ),
                    candidate,
                )
            )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked]


def _review_item(
    *,
    field: str,
    reason: str,
    recommended_option: dict,
    alternative_candidates: list[dict],
    evidence_refs: list[dict],
    alternative_evidence_refs: list[list[dict]] | None = None,
) -> dict:
    return {
        "field": field,
        "reason": reason,
        "recommended_option": recommended_option,
        "alternative_candidates": alternative_candidates,
        "evidence_refs": evidence_refs,
        "alternative_evidence_refs": alternative_evidence_refs or [],
    }


def _action_option_from_locator(locator: dict, *, bounds: list[int] | None = None) -> list[dict]:
    if bounds and len(bounds) == 4:
        x1, y1, x2, y2 = bounds
        return [{"action": "tap_xy", "x": (x1 + x2) // 2, "y": (y1 + y2) // 2}]
    return [{"action": "click_locator", "locator": locator}]


def _click_locator_option(locator: dict) -> list[dict]:
    return [{"action": "click_locator", "locator": locator}]


def _send_review_choices(candidate: dict) -> list[tuple[list[dict], list[dict]]]:
    locator = candidate["locator"]
    evidence_refs = candidate.get("evidence_refs", [])
    bounds = next(
        (
            ref["bounds"]
            for ref in evidence_refs
            if isinstance(ref, dict) and isinstance(ref.get("bounds"), list)
        ),
        None,
    )
    options: list[tuple[list[dict], list[dict]]] = []
    tap_or_click = _action_option_from_locator(locator, bounds=bounds)
    options.append((tap_or_click, evidence_refs))
    click_option = _click_locator_option(locator)
    if click_option != tap_or_click:
        options.append((click_option, evidence_refs))
    return options


def _build_review_items(
    input_candidates: list[dict],
    send_candidates: list[dict],
    response_candidates: list[dict],
) -> list[dict]:
    review_items: list[dict] = []
    if len(input_candidates) > 1:
        review_items.append(
            _review_item(
                field="input_locator",
                reason="Multiple input candidates matched the editing capture.",
                recommended_option=input_candidates[0]["locator"],
                alternative_candidates=[candidate["locator"] for candidate in input_candidates[1:]],
                evidence_refs=input_candidates[0].get("evidence_refs", []),
                alternative_evidence_refs=[
                    candidate.get("evidence_refs", []) for candidate in input_candidates[1:]
                ],
            )
        )
    if send_candidates:
        recommended_option, recommended_evidence = _send_review_choices(send_candidates[0])[0]
        alternative_candidates: list[list[dict]] = []
        alternative_evidence_refs: list[list[dict]] = []
        for option, evidence in _send_review_choices(send_candidates[0])[1:]:
            alternative_candidates.append(option)
            alternative_evidence_refs.append(evidence)
        for candidate in send_candidates[1:]:
            for option, evidence in _send_review_choices(candidate):
                alternative_candidates.append(option)
                alternative_evidence_refs.append(evidence)
        reason = "Confirm how the send control should be triggered in runtime editing state."
        if len(send_candidates) > 1:
            reason = "Multiple clickable controls looked like send buttons."
        review_items.append(
            _review_item(
                field="send_action",
                reason=reason,
                recommended_option=recommended_option,
                alternative_candidates=alternative_candidates,
                evidence_refs=recommended_evidence,
                alternative_evidence_refs=alternative_evidence_refs,
            )
        )
    if len(response_candidates) > 1:
        review_items.append(
            _review_item(
                field="latest_bubble_match",
                reason="Multiple response containers look plausible from repeated response text.",
                recommended_option=_response_review_option(response_candidates[0]),
                alternative_candidates=[
                    _response_review_option(candidate) for candidate in response_candidates[1:]
                ],
                evidence_refs=response_candidates[0].get("evidence_refs", []),
                alternative_evidence_refs=[
                    candidate.get("evidence_refs", []) for candidate in response_candidates[1:]
                ],
            )
        )
    elif response_candidates and response_candidates[0]["score"] < 260:
        review_items.append(
            _review_item(
                field="latest_bubble_match",
                reason=(
                    "Response candidate confidence is low because the XML has weak repetition "
                    "or container hints."
                ),
                recommended_option=_response_review_option(response_candidates[0]),
                alternative_candidates=[],
                evidence_refs=response_candidates[0].get("evidence_refs", []),
                alternative_evidence_refs=[],
            )
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

    input_candidates = _build_input_candidates(
        editing_nodes,
        idle_nodes,
    )
    send_candidates = _build_send_candidates(editing_nodes)
    response_candidates = _build_response_candidates(response_xml)
    review_items = _build_review_items(
        input_candidates,
        send_candidates,
        response_candidates,
    )

    return AndroidCandidateDraft(
        input_candidates=input_candidates,
        send_candidates=send_candidates,
        response_candidates=response_candidates,
        review_items=review_items,
    )
