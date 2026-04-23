import pytest

from autoagent.executors.complete_detector import wait_for_pixel_stable, wait_for_ui_tree_stable


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
