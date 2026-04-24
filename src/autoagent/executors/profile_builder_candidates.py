from dataclasses import asdict, dataclass
from xml.etree import ElementTree

_INPUT_HINT_KEYWORDS = ("发消息", "说话", "输入", "send", "message", "chat")
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


def _node_attrs(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    return [dict(node.attrib) for node in root.iter() if node is not root]


def _xpath_locator(value: str) -> dict:
    return {"type": "xpath", "value": value}


def _class_locator(value: str) -> dict:
    return {"type": "class", "value": value}


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


def _build_input_candidates(
    editing_nodes: list[dict[str, str]],
    idle_nodes: list[dict[str, str]],
) -> list[dict]:
    candidates: list[dict] = []
    seen_locators: set[tuple[str, str]] = set()

    def _append_candidate(candidate: dict) -> None:
        locator = candidate["locator"]
        key = (locator["type"], locator["value"])
        if key in seen_locators:
            return
        seen_locators.add(key)
        candidates.append(candidate)

    for node in editing_nodes:
        if node.get("class") != "android.widget.EditText":
            continue
        bounds = _parse_bounds(node.get("bounds"))
        _append_candidate(
            {
                "locator": _xpath_locator('//*[@class="android.widget.EditText"]'),
                "score": 100 + _bounds_area(bounds),
                "reason": "editing EditText",
                "evidence_refs": [
                    _evidence_ref(
                        source="editing_xml",
                        step="editing",
                        artifact="capture_editing.png",
                        locator=_xpath_locator('//*[@class="android.widget.EditText"]'),
                        bounds=bounds,
                        label="input",
                    )
                ],
            }
        )

    for node in idle_nodes:
        text = node.get("text", "").strip()
        if not text:
            continue
        if not any(keyword in text.lower() for keyword in _INPUT_HINT_KEYWORDS):
            continue
        target = "发消息" if "发消息" in text else text
        locator = _xpath_locator(f'//*[contains(@text, "{target}")]')
        _append_candidate(
            {
                "locator": locator,
                "score": 1000 - len(text),
                "reason": "idle input placeholder",
                "evidence_refs": [
                    _evidence_ref(
                        source="idle_xml",
                        step="idle",
                        artifact="capture_idle.png",
                        locator=locator,
                        bounds=_parse_bounds(node.get("bounds")),
                        label="input-placeholder",
                    )
                ],
            }
        )
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _build_send_candidates(editing_nodes: list[dict[str, str]]) -> list[dict]:
    return _build_send_candidates_from_nodes(editing_nodes, source="editing_xml")


def _build_send_candidates_from_nodes(
    editing_nodes: list[dict[str, str]],
    *,
    source: str,
) -> list[dict]:
    app_package = _app_package(editing_nodes)
    ranked: list[tuple[tuple[int, int, int], dict]] = []
    for node in editing_nodes:
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
        if width < 48 or height < 48:
            continue
        if area > 100_000:
            continue
        if y1 < 1200:
            continue
        locator = _xpath_locator(f'//*[@bounds="{bounds_raw}"]')
        ranked.append(
            (
                (y2, x2, -area),
                {
                    "locator": locator,
                    "score": x2 + y2,
                    "reason": "rightmost clickable near bottom",
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
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in ranked]


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


def _response_review_option(candidate: dict) -> dict:
    return {
        "response_container_locator": candidate["response_container_locator"],
        "scroll_container_locator": candidate["scroll_container_locator"],
        "latest_bubble_match": candidate["latest_bubble_match"],
    }


def _response_candidate(
    *,
    container: ElementTree.Element,
    scroll_container: ElementTree.Element | None,
    text_nodes: list[ElementTree.Element],
) -> dict:
    container_bounds = _parse_bounds(container.attrib.get("bounds"))
    total_text_len = sum(len((node.attrib.get("text") or "").strip()) for node in text_nodes)
    repeated_count = len(text_nodes)
    container_bonus = 60 if repeated_count >= 2 else 0
    scroll_bonus = 40 if scroll_container is not None else 0
    score = repeated_count * 100 + total_text_len * 5 + _bounds_area(container_bounds) // 1000
    locator = _locator_from_node(container)
    scroll_locator = _locator_from_node(scroll_container or container)
    latest_locator = _latest_bubble_locator(text_nodes)
    return {
        "response_container_locator": locator,
        "scroll_container_locator": scroll_locator,
        "latest_bubble_match": latest_locator,
        "score": score + container_bonus + scroll_bonus,
        "reason": "container with repeated visible response text",
        "evidence_refs": [
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
        candidate = _response_candidate(
            container=container,
            scroll_container=scroll_container,
            text_nodes=grouped_text_nodes,
        )
        ranked.append(
            (
                (
                    candidate["score"],
                    len(grouped_text_nodes),
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
