from autoagent.executors.profile_builder_candidates import build_android_candidates


def test_build_android_candidates_finds_input_send_and_response_hints(tmp_path):
    idle_xml = """<hierarchy><node text="发消息或按住说话..." class="android.widget.TextView" bounds="[177,2066][777,2123]" /></hierarchy>"""
    editing_xml = """<hierarchy><node text="你好" class="android.widget.EditText" bounds="[36,1882][1032,2002]" /><node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" /></hierarchy>"""
    response_xml = """<hierarchy><node text="你好" class="android.widget.EditText" /><node text="当然可以" class="android.widget.TextView" /></hierarchy>"""

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert draft.input_candidates[0]["locator"]["value"] == '//*[@class="android.widget.EditText"]'
    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[909,2009][1020,2120]"]'
    assert draft.review_items[0]["field"] in {
        "input_locator",
        "send_button_locator",
        "latest_bubble_match",
    }
