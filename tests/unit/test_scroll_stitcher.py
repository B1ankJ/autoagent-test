from autoagent.executors.scroll_stitcher import stitch_lines


def test_stitch_lines_dedupes_overlap() -> None:
    frames = [
        ["第一行", "第二行", "第三行"],
        ["第三行", "第四行", "第五行"],
    ]
    assert stitch_lines(frames) == "第一行\n第二行\n第三行\n第四行\n第五行"
