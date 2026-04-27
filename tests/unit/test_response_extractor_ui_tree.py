from autoagent.executors.response_extractor import UiTreeExtractor
from autoagent.profiles.schemas import Locator


def test_ui_tree_extractor_returns_latest_bubble() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.ListView">
        <node class="android.widget.LinearLayout">
          <node class="android.widget.TextView" text="old" />
        </node>
        <node class="android.widget.LinearLayout">
          <node class="android.widget.TextView" text="new" />
        </node>
      </node>
    </hierarchy>
    """
    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="class", value="android.widget.ListView"),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )
    assert result.text == "new"
    assert result.method_used == "ui_tree"


def test_ui_tree_extractor_ignores_time_and_ui_chrome() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.TextView" text="这是千问真正的回答内容" />
      <node class="android.widget.TextView" text="深度思考" />
      <node class="android.widget.TextView" text="14:16" />
      <node class="android.widget.TextView" text="内容由AI生成" />
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="xpath", value='//*[@class="android.widget.FrameLayout"]'),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert result.text == "这是千问真正的回答内容"


def test_ui_tree_extractor_prefers_latest_meaningful_bubble_over_older_longer_text() -> None:
    old_text = "这是上一轮的一段更长的历史回答内容，会误导全局最长策略"
    xml = f"""
    <hierarchy>
      <node class="android.widget.TextView" text="{old_text}" />
      <node class="android.widget.TextView" text="14:16" />
      <node class="android.widget.TextView" text="内容由AI生成" />
      <node class="android.widget.TextView" text="最新回复" />
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="xpath", value='//*[@class="android.widget.FrameLayout"]'),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert result.text == "最新回复"


def test_ui_tree_extractor_limits_matches_to_selected_response_container() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,300][1080,778]">
        <node class="android.widget.TextView" text="123" bounds="[858,300][1020,436]" />
        <node class="android.widget.TextView" text="在呢，说吧，想聊点啥？" bounds="[0,484][1080,622]" />
      </node>
      <node class="android.widget.FrameLayout" bounds="[0,1738][1080,2244]">
        <node class="android.widget.TextView" text="AI打车" bounds="[267,1768][382,1815]" />
        <node class="android.widget.TextView" text="深度思考" bounds="[535,1768][691,1815]" />
        <node class="android.widget.TextView" text="内容由AI生成" bounds="[450,2208][629,2244]" />
      </node>
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="xpath", value='//*[@bounds="[0,300][1080,778]"]'),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert result.text == "在呢，说吧，想聊点啥？"


def test_ui_tree_extractor_does_not_fallback_to_whole_page_when_container_is_missing() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,1738][1080,2244]">
        <node class="android.widget.TextView" text="AI打车" bounds="[267,1768][382,1815]" />
      </node>
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="xpath", value='//*[@bounds="[0,944][1080,1422]"]'),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert result.text == ""


def test_ui_tree_extractor_prefers_latest_visible_assistant_reply_over_bottom_chips() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2244]">
        <node class="android.widget.TextView" text="在呢，说吧，想聊点啥？" bounds="[0,484][1080,622]" />
        <node class="android.widget.TextView" text="嗨，来啦。今天怎么样？" bounds="[0,806][1080,944]" />
        <node class="android.widget.TextView" text="hello呀，今天心情怎么样？" bounds="[0,1128][1080,1266]" />
        <node class="android.widget.TextView" text="内容由AI生成" bounds="[450,2208][629,2244]" />
        <node class="android.widget.TextView" text="AI打车" bounds="[267,1768][382,1815]" />
        <node class="android.widget.TextView" text="深度思考" bounds="[535,1768][691,1815]" />
        <node class="android.widget.TextView" text="AI生图" bounds="[844,1768][959,1815]" />
        <node class="android.widget.EditText" text="hello" bounds="[36,1882][1032,2002]" />
      </node>
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="resource_id", value="missing:id/container"),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert result.text == "hello呀，今天心情怎么样？"


def test_ui_tree_extractor_aggregates_latest_multi_textview_response_block() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2244]">
        <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,320][1080,1960]" resource-id="com.example:id/chat_list">
          <node class="android.widget.LinearLayout" bounds="[48,980][1032,1190]">
            <node class="android.widget.TextView" text="旧回复" bounds="[96,1020][420,1100]" />
          </node>
          <node class="android.widget.LinearLayout" bounds="[48,1340][1032,1700]">
            <node class="android.widget.TextView" text="第一段回复" bounds="[96,1400][620,1480]" />
            <node class="android.widget.TextView" text="继续说明" bounds="[96,1496][660,1576]" />
            <node class="android.widget.TextView" text="补充结尾" bounds="[96,1592][620,1672]" />
          </node>
        </node>
      </node>
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(
            type="resource_id",
            value="com.example:id/chat_list",
        ),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert result.text == "第一段回复 继续说明 补充结尾"


def test_ui_tree_extractor_deprioritizes_bottom_suggestion_chip_blocks() -> None:
    xml = """
        <hierarchy>
          <node class="android.widget.FrameLayout" bounds="[0,0][1080,2244]">
            <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,300][1080,1233]">
          <node class="android.widget.TextView" text="关于“当下”的碎片&#10;&#10;窗外的风刚刚停歇，带走了午后最后一丝燥热。在这个快节奏的数字时代，我们往往走得太快，以至于忘记了停下来看看路边的风景。&#10;&#10;未来的无限可能&#10;&#10;当我们谈论未来时，我们实际上是在谈论一种信念。无论是人工智能的迭代更新，还是人类对星辰大海的探索。" bounds="[0,300][1080,1233]" />
            </node>
        <node class="android.widget.LinearLayout" bounds="[0,1389][1080,1782]">
          <node class="android.widget.TextView" text="生成一段未来科技感的文字" bounds="[60,1389][600,1496]" />
          <node class="android.widget.TextView" text="写一段关于友情的回忆" bounds="[60,1532][522,1639]" />
          <node class="android.widget.TextView" text="写一段关于旅行的文字" bounds="[60,1675][522,1782]" />
        </node>
      </node>
    </hierarchy>
    """

    result = UiTreeExtractor().extract_from_xml(
        xml,
        response_container_locator=Locator(type="class", value="android.widget.FrameLayout"),
        latest_bubble_locator=Locator(type="class", value="android.widget.TextView"),
    )

    assert "关于“当下”的碎片" in result.text
    assert "未来的无限可能" in result.text
