import pytest

from autoagent.executors.copy_button_vlm import (
    _DIALOG_DETECTION_CLAUSE,
    CopyButtonLocateResult,
    _extract_coords,
    _extract_dialog_coords,
    locate_copy_button_via_vlm,
)
from autoagent.profiles.schemas import CopyButtonVLMConfig


def test_clean_json():
    assert _extract_coords('{"found": true, "x": 100, "y": 200}') == ((100, 200), None)


def test_markdown_fence():
    content = '```json\n{"found": true, "x": 50, "y": 60}\n```'
    assert _extract_coords(content) == ((50, 60), None)


def test_plain_fence():
    assert _extract_coords('```\n{"x": 10, "y": 20}\n```') == ((10, 20), None)


def test_answer_wrapper():
    assert _extract_coords("<answer>{\"x\":1,\"y\":2}</answer>") == ((1, 2), None)


def test_prose_prefix():
    content = "好的，复制按钮在这里：{\"x\": 540, \"y\": 1850}"
    assert _extract_coords(content) == ((540, 1850), None)


def test_string_numbers():
    assert _extract_coords('{"x": "100", "y": "200"}') == ((100, 200), None)


def test_nested_coordinates_key():
    content = '{"found": true, "coordinates": [123, 456]}'
    assert _extract_coords(content) == ((123, 456), None)


def test_nested_position_dict():
    content = '{"position": {"x": 7, "y": 8}}'
    assert _extract_coords(content) == ((7, 8), None)


def test_explicit_not_found():
    assert _extract_coords('{"found": false}') == (None, "not_found")


def test_chinese_not_found_prose():
    assert _extract_coords("抱歉，截图中找不到复制按钮。") == (None, "not_found")


def test_kv_fallback():
    assert _extract_coords("Action: click(x=300, y=400)") == ((300, 400), None)


def test_yx_order_swapped():
    assert _extract_coords('{"y": 999, "x": 111}') == ((111, 999), None)


def test_list_fallback():
    assert _extract_coords("The copy button is at [250, 800].") == ((250, 800), None)


def test_tuple_fallback():
    assert _extract_coords("coords = (10, 20)") == ((10, 20), None)


def test_empty():
    assert _extract_coords("") == (None, "empty")


def test_garbage():
    assert _extract_coords("the cat sat on the mat") == (None, "parse")


# --- Blocking auth/consent dialog detection (detect_auth_dialog=True) ---


def test_extract_dialog_coords_clean_json():
    content = '{"blocking_dialog": true, "dialog_x": 360, "dialog_y": 752}'
    assert _extract_dialog_coords(content) == (360, 752)


def test_extract_dialog_coords_ignores_normal_copy_button_response():
    assert _extract_dialog_coords('{"found": true, "x": 100, "y": 200}') is None


def test_extract_dialog_coords_regex_fallback_for_messy_response():
    content = 'Sure, blocking_dialog: true, dialog_x=360, dialog_y=752'
    assert _extract_dialog_coords(content) == (360, 752)


def test_extract_dialog_coords_missing_xy_returns_none():
    assert _extract_dialog_coords('{"blocking_dialog": true}') is None


def _vlm_config(**overrides) -> CopyButtonVLMConfig:
    base = {"base_url": "https://x", "model": "m", "api_key": "k"}
    base.update(overrides)
    return CopyButtonVLMConfig(**base)


async def _fake_post_json(monkeypatch, content: str):
    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

        @property
        def text(self):
            return content

    async def _post(**kwargs):
        return _Resp()

    monkeypatch.setattr(
        "autoagent.executors.copy_button_vlm.post_json_with_retry", _post
    )


async def test_locate_copy_button_returns_dialog_coords_when_detect_auth_dialog_on(
    monkeypatch,
):
    await _fake_post_json(
        monkeypatch, '{"blocking_dialog": true, "dialog_x": 360, "dialog_y": 752}'
    )
    config = _vlm_config(detect_auth_dialog=True)
    result = await locate_copy_button_via_vlm(b"png-bytes", config)
    assert result == CopyButtonLocateResult(
        None, result.raw_response, result.latency_ms, dialog_coords=(360, 752)
    )


async def test_locate_copy_button_ignores_dialog_field_when_detect_auth_dialog_off(
    monkeypatch,
):
    # Even if a response happens to contain blocking_dialog, a profile that
    # never opted in should never get dialog_coords back.
    await _fake_post_json(
        monkeypatch, '{"blocking_dialog": true, "dialog_x": 360, "dialog_y": 752}'
    )
    config = _vlm_config(detect_auth_dialog=False)
    result = await locate_copy_button_via_vlm(b"png-bytes", config)
    assert result.dialog_coords is None


async def test_locate_copy_button_still_finds_button_when_no_dialog(monkeypatch):
    await _fake_post_json(monkeypatch, '{"found": true, "x": 10, "y": 20}')
    config = _vlm_config(detect_auth_dialog=True)
    result = await locate_copy_button_via_vlm(b"png-bytes", config)
    assert result.coords == (10, 20)
    assert result.dialog_coords is None


@pytest.mark.parametrize("detect", [True, False])
async def test_prompt_only_gains_dialog_clause_when_opted_in(monkeypatch, detect):
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"found": false}'}}]}

        @property
        def text(self):
            return '{"found": false}'

    async def _post(**kwargs):
        captured["body"] = kwargs["json"]
        return _Resp()

    monkeypatch.setattr(
        "autoagent.executors.copy_button_vlm.post_json_with_retry", _post
    )
    config = _vlm_config(detect_auth_dialog=detect)
    await locate_copy_button_via_vlm(b"png-bytes", config)
    prompt_text = captured["body"]["messages"][0]["content"][0]["text"]
    assert (_DIALOG_DETECTION_CLAUSE in prompt_text) is detect
