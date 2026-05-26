from autoagent.executors.copy_button_vlm import _extract_coords


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
