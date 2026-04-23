from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autoagent.executors.profile_builder_capture import capture_android_state


@pytest.mark.asyncio
async def test_capture_android_state_writes_expected_artifacts(tmp_path: Path):
    device = MagicMock()
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"png-bytes"

    result = await capture_android_state(
        device=device,
        session_dir=tmp_path,
        step="idle",
    )

    assert result.package == "com.aliyun.tongyi"
    assert result.activity == ".BrowserActivity"
    assert (tmp_path / "capture_idle.xml").read_text(encoding="utf-8").startswith("<hierarchy>")
    assert (tmp_path / "capture_idle.png").read_bytes() == b"png-bytes"
