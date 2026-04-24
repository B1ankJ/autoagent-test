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
