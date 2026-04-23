from autoagent.executors.profile_builder_candidates import build_android_candidates


def test_build_android_candidates_prefers_repeated_response_container_hints():
    idle_xml = """<hierarchy><node text="发消息或按住说话..." class="android.widget.TextView" bounds="[177,2066][777,2123]" /></hierarchy>"""
    editing_xml = """<hierarchy><node text="你好" class="android.widget.EditText" bounds="[36,1882][1032,2002]" /><node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" /></hierarchy>"""
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
        <node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" bounds="[0,320][1080,2060]">
          <node class="android.widget.LinearLayout" bounds="[48,1340][1032,1640]">
            <node text="当然可以" class="android.widget.TextView" bounds="[96,1400][884,1490]" />
            <node text="我可以帮你整理任务。" class="android.widget.TextView" bounds="[96,1508][920,1600]" />
          </node>
        </node>
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert draft.input_candidates[0]["locator"]["value"] == '//*[@class="android.widget.EditText"]'
    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[909,2009][1020,2120]"]'
    assert (
        draft.response_candidates[0]["response_container_locator"]["value"]
        == '//*[@bounds="[48,1340][1032,1640]"]'
    )
    assert (
        draft.response_candidates[0]["scroll_container_locator"]["value"]
        == '//*[@bounds="[0,320][1080,2060]"]'
    )
    assert draft.response_candidates[0]["latest_bubble_match"]["value"] == '//*[@class="android.widget.TextView"]'
    assert draft.review_items == []


def test_build_android_candidates_emits_detailed_review_item_for_ambiguous_response_hints():
    idle_xml = """<hierarchy><node text="发消息" class="android.widget.TextView" bounds="[177,2066][777,2123]" /></hierarchy>"""
    editing_xml = """
    <hierarchy>
      <node text="你好" class="android.widget.EditText" bounds="[36,1882][1032,2002]" />
      <node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
        <node class="android.widget.LinearLayout" bounds="[48,1200][1032,1460]">
          <node text="第一段回复" class="android.widget.TextView" bounds="[96,1240][884,1310]" />
          <node text="继续说明" class="android.widget.TextView" bounds="[96,1326][920,1400]" />
        </node>
        <node class="android.widget.LinearLayout" bounds="[48,1500][1032,1760]">
          <node text="第二段回复" class="android.widget.TextView" bounds="[96,1540][884,1610]" />
          <node text="继续补充" class="android.widget.TextView" bounds="[96,1626][920,1700]" />
        </node>
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert len(draft.response_candidates) >= 2
    assert len(draft.review_items) == 1
    review_item = draft.review_items[0]
    assert review_item["field"] == "latest_bubble_match"
    assert review_item["recommended_option"] == draft.response_candidates[0]["latest_bubble_match"]
    assert review_item["alternative_candidates"] == [
        candidate["latest_bubble_match"] for candidate in draft.response_candidates[1:]
    ]
    assert review_item["evidence_refs"][0]["source"] == "response_xml"
    assert (
        review_item["evidence_refs"][0]["container_locator"]
        == draft.response_candidates[0]["response_container_locator"]
    )
    assert (
        review_item["evidence_refs"][0]["scroll_locator"]
        == draft.response_candidates[0]["scroll_container_locator"]
    )
