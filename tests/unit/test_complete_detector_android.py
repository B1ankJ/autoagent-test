import pytest

from autoagent.executors.complete_detector import (
    capture_screenshot_bytes,
    wait_for_pixel_stable,
    wait_for_ui_tree_stable,
)


@pytest.mark.asyncio
async def test_wait_for_ui_tree_stable_returns_after_same_xml():
    seq = iter(["<a/>", "<a/>", "<a/>"])

    class Device:
        def dump_hierarchy(self, compressed=False):
            return next(seq)

    await wait_for_ui_tree_stable(Device(), stable_sec=0.0, max_wait_sec=0.2)


@pytest.mark.asyncio
async def test_wait_for_pixel_stable_hashes_same_frames():
    seq = iter([b"a", b"a", b"a"])

    class Device:
        def screenshot(self, format="raw"):
            return next(seq)

    await wait_for_pixel_stable(Device(), stable_sec=0.0, max_wait_sec=0.2)


def test_capture_screenshot_bytes_falls_back_when_raw_unsupported():
    class Shot:
        def save(self, buf, format="PNG"):
            buf.write(b"png-bytes")

    class Device:
        def screenshot(self, format="raw"):
            if format == "raw":
                raise ValueError("Unsupported format")
            assert format == "pillow"
            return Shot()

    assert capture_screenshot_bytes(Device()) == b"png-bytes"
