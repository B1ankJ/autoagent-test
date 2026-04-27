from autoagent.api.profile_builder import (
    _input_focus_action_review_item,
    _ready_check_review_item,
    _ready_check_text,
)
from autoagent.executors.profile_builder_candidates import build_android_candidates


def test_build_android_candidates_prefers_repeated_response_container_hints():
    idle_xml = """
    <hierarchy>
      <node
        text="发消息或按住说话..."
        class="android.widget.TextView"
        bounds="[177,2066][777,2123]"
      />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node text="你好" class="android.widget.EditText" bounds="[36,1882][1032,2002]" />
      <node
        class="android.widget.FrameLayout"
        bounds="[909,2009][1020,2120]"
        clickable="true"
      />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
        <node
          class="androidx.recyclerview.widget.RecyclerView"
          scrollable="true"
          bounds="[0,320][1080,2060]"
        >
          <node class="android.widget.LinearLayout" bounds="[48,1340][1032,1640]">
            <node text="当然可以" class="android.widget.TextView" bounds="[96,1400][884,1490]" />
            <node
              text="我可以帮你整理任务。"
              class="android.widget.TextView"
              bounds="[96,1508][920,1600]"
            />
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

    assert draft.input_candidates[0]["locator"]["value"] == '//*[@bounds="[36,1882][1032,2002]"]'
    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[909,2009][1020,2120]"]'
    assert (
        draft.response_candidates[0]["response_container_locator"]["value"]
        == "androidx.recyclerview.widget.RecyclerView"
    )
    assert (
        draft.response_candidates[0]["scroll_container_locator"]["value"]
        == "androidx.recyclerview.widget.RecyclerView"
    )
    assert draft.response_candidates[0]["latest_bubble_match"] == {
        "type": "class",
        "value": "android.widget.TextView",
    }
    assert draft.response_candidates[0]["review_latest_bubble_match"]["value"].startswith(
        "//*[@bounds="
    )
    assert len(draft.review_items) == 2
    assert draft.review_items[0]["field"] == "input_locator"
    assert draft.review_items[1]["field"] == "send_action"


def test_build_android_candidates_emits_detailed_review_item_for_ambiguous_response_hints():
    idle_xml = """
    <hierarchy>
      <node text="发消息" class="android.widget.TextView" bounds="[177,2066][777,2123]" />
    </hierarchy>
    """
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

    assert len(draft.response_candidates) == 2
    assert len(draft.review_items) == 3
    review_item = next(
        item for item in draft.review_items if item["field"] == "latest_bubble_match"
    )
    assert review_item["field"] == "latest_bubble_match"
    assert review_item["recommended_option"] == {
        "response_container_locator": draft.response_candidates[0]["response_container_locator"],
        "scroll_container_locator": draft.response_candidates[0]["scroll_container_locator"],
        "latest_bubble_match": draft.response_candidates[0]["review_latest_bubble_match"],
        "resolved_latest_bubble_match": draft.response_candidates[0]["latest_bubble_match"],
        "bubble_preview": draft.response_candidates[0]["bubble_preview"],
    }
    assert review_item["alternative_candidates"] == [
        {
            "response_container_locator": candidate["response_container_locator"],
            "scroll_container_locator": candidate["scroll_container_locator"],
            "latest_bubble_match": candidate["review_latest_bubble_match"],
            "resolved_latest_bubble_match": candidate["latest_bubble_match"],
            "bubble_preview": candidate["bubble_preview"],
        }
        for candidate in draft.response_candidates[1:]
    ]
    assert review_item["recommended_option"] != review_item["alternative_candidates"][0]
    assert review_item["evidence_refs"][0]["source"] == "idle_xml"
    assert review_item["evidence_refs"][0]["label"] == "response-bubble"
    assert review_item["evidence_refs"][0]["text"] == "第二段回复 继续补充"
    assert review_item["evidence_refs"][1]["locator"] == draft.response_candidates[0]["response_container_locator"]
    assert review_item["evidence_refs"][1]["scroll_locator"] == draft.response_candidates[0]["scroll_container_locator"]


def test_build_android_candidates_keeps_all_matching_input_nodes_in_review():
    idle_xml = """
    <hierarchy>
      <node text="发消息" class="android.widget.TextView" bounds="[100,2000][400,2080]" />
      <node text="输入问题" class="android.widget.TextView" bounds="[500,2000][900,2080]" />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node text="你好" class="android.widget.EditText" bounds="[36,1882][520,2002]" />
      <node text="再见" class="android.widget.EditText" bounds="[540,1882][1032,2002]" />
      <node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.LinearLayout" bounds="[48,1500][1032,1760]">
        <node text="第二段回复" class="android.widget.TextView" bounds="[96,1540][884,1610]" />
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert len(draft.input_candidates) >= 4
    input_review = next(item for item in draft.review_items if item["field"] == "input_locator")
    assert len(input_review["alternative_candidates"]) >= 3
    assert input_review["evidence_refs"][0]["bounds"] == [36, 1882, 520, 2002]
    assert input_review["alternative_evidence_refs"][0][0]["bounds"] == [540, 1882, 1032, 2002]


def test_build_android_candidates_prefers_input_placeholder_and_small_send_controls():
    idle_xml = """
    <hierarchy>
      <node
        text="你好你好！嚯，升级了，直接上中文了，hh。今天这是打招呼大赏吗？"
        class="android.widget.TextView"
        bounds="[0,300][1080,474]"
      />
      <node
        text="发消息或按住说话..."
        class="android.widget.TextView"
        bounds="[177,2066][777,2123]"
      />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node
        text="你好你好！嚯，升级了，直接上中文了，hh。今天这是打招呼大赏吗？"
        class="android.widget.TextView"
        bounds="[0,300][1080,474]"
      />
      <node class="android.widget.FrameLayout" bounds="[0,1830][1080,2214]" clickable="true" />
      <node class="android.widget.FrameLayout" bounds="[798,2038][909,2149]" clickable="true" />
      <node class="android.widget.FrameLayout" bounds="[909,2038][1020,2149]" clickable="true" />
      <node
        text="发消息或按住说话..."
        class="android.widget.TextView"
        bounds="[177,2066][777,2123]"
      />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
        <node class="android.widget.LinearLayout" bounds="[0,1200][1080,1674]">
          <node
            text="你好！得，复读机模式关不掉了是吧，hh。"
            class="android.widget.TextView"
            bounds="[0,1536][1080,1674]"
          />
        </node>
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert draft.input_candidates[0]["locator"]["value"] == '//*[@bounds="[177,2066][777,2123]"]'
    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[909,2038][1020,2149]"]'


def test_build_android_candidates_prefers_latest_assistant_response_over_ui_chrome() -> None:
    idle_xml = """
    <hierarchy>
      <node text="发消息或按住说话..." class="android.widget.TextView" bounds="[177,2066][777,2123]" />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node text="hello" class="android.widget.EditText" bounds="[36,1882][1032,2002]" />
      <node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2244]">
        <node class="android.widget.FrameLayout" bounds="[0,300][1080,622]">
          <node class="android.widget.TextView" text="123" bounds="[858,300][1020,436]" />
          <node class="android.widget.TextView" text="在呢，说吧，想聊点啥？" bounds="[0,484][1080,622]" />
        </node>
        <node class="android.widget.FrameLayout" bounds="[0,622][1080,1100]">
          <node class="android.widget.TextView" text="hello" bounds="[838,622][1020,758]" />
          <node class="android.widget.TextView" text="嗨，来啦。今天怎么样？" bounds="[0,806][1080,944]" />
        </node>
        <node class="android.widget.FrameLayout" bounds="[0,1866][1080,1974]">
          <node class="android.widget.TextView" text="AI打车" bounds="[267,1896][382,1943]" />
          <node class="android.widget.TextView" text="深度思考" bounds="[535,1896][691,1943]" />
          <node class="android.widget.TextView" text="AI生图" bounds="[844,1896][959,1943]" />
        </node>
        <node class="android.widget.FrameLayout" bounds="[0,1866][1080,2214]">
          <node class="android.widget.TextView" text="发消息或按住说话..." bounds="[177,2066][777,2123]" />
          <node class="android.widget.TextView" text="内容由AI生成" bounds="[450,2208][629,2244]" />
        </node>
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert draft.response_candidates[0]["bubble_preview"] == "嗨，来啦。今天怎么样？"
    assert any(candidate["bubble_preview"] == "AI打车" for candidate in draft.response_candidates)


def test_build_android_candidates_ignores_system_ui_send_like_controls():
    idle_xml = """
    <hierarchy>
      <node text="发消息或按住说话..." class="android.widget.TextView" />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node
        text="发消息..."
        class="android.widget.EditText"
        package="com.aliyun.tongyi"
        bounds="[36,1164][1032,1284]"
      />
      <node
        class="android.widget.FrameLayout"
        package="com.aliyun.tongyi"
        bounds="[909,1291][1020,1402]"
        clickable="true"
      />
      <node
        class="android.widget.FrameLayout"
        package="com.android.systemui"
        bounds="[962,2244][1080,2376]"
        clickable="true"
      />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
        <node class="android.widget.LinearLayout" bounds="[0,1200][1080,1674]">
          <node text="你好" class="android.widget.TextView" bounds="[0,1536][1080,1674]" />
        </node>
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[909,1291][1020,1402]"]'


def test_build_android_candidates_preserves_raw_input_and_send_candidates() -> None:
    idle_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,1800][1080,2214]">
        <node
          text="发消息或按住说话..."
          class="android.widget.TextView"
          bounds="[177,2066][777,2123]"
          focusable="false"
        />
        <node
          class="android.widget.LinearLayout"
          bounds="[40,1880][820,2140]"
          clickable="true"
          focusable="true"
        />
      </node>
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node
        text="hello"
        class="android.widget.EditText"
        bounds="[120,1900][780,2010]"
        package="com.example.chat"
        focusable="true"
      />
      <node
        class="android.widget.FrameLayout"
        bounds="[36,1882][1032,2002]"
        package="com.example.chat"
        clickable="true"
        focusable="true"
      />
      <node
        class="android.widget.ImageView"
        bounds="[904,1940][952,1988]"
        package="com.example.chat"
        clickable="true"
      />
      <node
        class="android.widget.FrameLayout"
        bounds="[876,1910][980,2018]"
        package="com.example.chat"
        clickable="true"
      />
      <node
        class="android.widget.FrameLayout"
        bounds="[980,1910][1068,2018]"
        package="com.example.chat"
        clickable="true"
      />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2244]">
        <node class="android.widget.LinearLayout" bounds="[48,1200][1032,1460]">
          <node text="第二段回复" class="android.widget.TextView" bounds="[96,1240][884,1310]" />
        </node>
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert len(draft.input_candidates) >= 4
    assert len(draft.send_candidates) >= 3
    input_review = next(item for item in draft.review_items if item["field"] == "input_locator")
    send_review = next(item for item in draft.review_items if item["field"] == "send_action")
    assert len(input_review["alternative_candidates"]) >= 3
    assert len(send_review["alternative_candidates"]) >= 4


def test_build_android_candidates_groups_multi_textview_response_block() -> None:
    idle_xml = """
    <hierarchy>
      <node text="发消息或按住说话..." class="android.widget.TextView" bounds="[177,2066][777,2123]" />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node text="hello" class="android.widget.EditText" bounds="[36,1882][1032,2002]" />
      <node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2244]">
        <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,320][1080,1960]" scrollable="true">
          <node class="android.widget.LinearLayout" bounds="[48,1340][1032,1700]">
            <node text="第一段回复" class="android.widget.TextView" bounds="[96,1400][620,1480]" />
            <node text="继续说明" class="android.widget.TextView" bounds="[96,1496][660,1576]" />
            <node text="补充结尾" class="android.widget.TextView" bounds="[96,1592][620,1672]" />
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

    assert draft.response_candidates[0]["bubble_preview"] == "第一段回复 继续说明 补充结尾"
    assert not any(item["field"] == "latest_bubble_match" for item in draft.review_items)


def test_build_android_candidates_keeps_non_clickable_send_icon_candidates() -> None:
    idle_xml = """
    <hierarchy>
      <node text="请输入" class="android.widget.TextView" bounds="[920,2025][988,2095]" />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node class="android.view.View" bounds="[0,1953][1080,2244]">
        <node class="android.view.View" bounds="[46,1987][1034,2132]">
          <node
            class="android.widget.EditText"
            package="com.eg.android.AlipayGphone"
            clickable="true"
            focusable="true"
            bounds="[92,2029][899,2090]"
            hint="请输入"
          />
          <node
            class="android.widget.Image"
            package="com.eg.android.AlipayGphone"
            text="发送"
            clickable="false"
            bounds="[915,2013][1009,2106]"
          />
        </node>
      </node>
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.LinearLayout" bounds="[48,1500][1032,1760]">
        <node text="第二段回复" class="android.widget.TextView" bounds="[96,1540][884,1610]" />
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    assert len(draft.send_candidates) >= 2
    assert any(
        candidate["locator"]["value"] == '//*[@bounds="[915,2013][1009,2106]"]'
        for candidate in draft.send_candidates
    )
    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[915,2013][1009,2106]"]'


def test_build_android_candidates_keeps_all_bounded_nodes_for_manual_review() -> None:
    idle_xml = """
    <hierarchy>
      <node class="android.widget.TextView" text="19:58" package="com.android.systemui" bounds="[51,19][173,110]" />
      <node class="android.widget.TextView" text="输入区提示" package="com.example.app" bounds="[700,1800][980,1880]" />
    </hierarchy>
    """
    editing_xml = """
    <hierarchy>
      <node class="android.widget.TextView" text="顶部标题" package="com.example.app" bounds="[120,120][540,220]" />
      <node class="android.widget.EditText" package="com.example.app" bounds="[92,2029][899,2090]" clickable="true" focusable="true" />
      <node class="android.widget.Image" text="发送" package="com.example.app" bounds="[915,2013][1009,2106]" clickable="false" />
      <node class="android.widget.ImageView" package="com.android.systemui" bounds="[152,2244][392,2376]" clickable="true" />
    </hierarchy>
    """
    response_xml = """
    <hierarchy>
      <node class="android.widget.LinearLayout" bounds="[48,1500][1032,1760]">
        <node text="第二段回复" class="android.widget.TextView" bounds="[96,1540][884,1610]" />
      </node>
    </hierarchy>
    """

    draft = build_android_candidates(
        idle_xml=idle_xml,
        editing_xml=editing_xml,
        response_xml=response_xml,
    )

    input_values = {candidate["locator"]["value"] for candidate in draft.input_candidates}
    send_values = {candidate["locator"]["value"] for candidate in draft.send_candidates}
    focus_review = _input_focus_action_review_item(idle_xml, draft.input_candidates)

    assert '//*[@bounds="[120,120][540,220]"]' in input_values
    assert '//*[@bounds="[51,19][173,110]"]' in input_values
    assert '//*[@bounds="[152,2244][392,2376]"]' in input_values
    assert '//*[@bounds="[120,120][540,220]"]' in send_values
    assert '//*[@bounds="[152,2244][392,2376]"]' in send_values
    assert focus_review is not None
    assert any(
        option == [{"action": "tap_xy", "x": 330, "y": 170}]
        for option in focus_review["alternative_candidates"]
    )


def test_ready_check_text_prefers_input_placeholder_over_chat_content():
    idle_xml = """
    <hierarchy>
      <node
        text="你好你好！嚯，升级了，直接上中文了，hh。今天这是打招呼大赏吗？"
        class="android.widget.TextView"
      />
      <node text="发消息或按住说话..." class="android.widget.TextView" />
    </hierarchy>
    """

    assert _ready_check_text(idle_xml) == "发消息"


def test_ready_check_text_returns_multiple_candidates_when_available():
    idle_xml = """
    <hierarchy>
      <node text="发消息" class="android.widget.TextView" />
      <node text="语音输入" class="android.widget.ImageView" />
      <node text="输入消息" class="android.widget.TextView" />
    </hierarchy>
    """

    assert _ready_check_text(idle_xml) == ["发消息", "语音输入", "输入消息"]


def test_ready_check_review_item_emits_multi_select_candidates():
    idle_xml = """
    <hierarchy>
      <node text="发消息" class="android.widget.TextView" bounds="[100,2000][400,2080]" />
      <node text="语音输入" class="android.widget.ImageView" bounds="[500,2000][900,2080]" />
      <node text="输入消息" class="android.widget.TextView" bounds="[100,2100][400,2180]" />
    </hierarchy>
    """

    item = _ready_check_review_item(idle_xml)

    assert item is not None
    assert item["field"] == "ready_check"
    assert item["recommended_option"] == {
        "type": "ui_tree_contains",
        "text": ["发消息", "语音输入", "输入消息"],
        "timeout_sec": 5,
    }
    assert item["candidate_texts"] == ["发消息", "语音输入", "输入消息"]
    assert [ref["text"] for ref in item["evidence_refs"]] == ["发消息", "语音输入", "输入消息"]
