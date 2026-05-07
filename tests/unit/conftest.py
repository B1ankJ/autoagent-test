import pytest


@pytest.fixture(autouse=True)
def _patch_dump_hierarchy_via_adb(monkeypatch):
    """Prevent real adb subprocess calls in unit tests by default."""
    monkeypatch.setattr(
        "autoagent.executors.complete_detector.dump_hierarchy_via_adb",
        lambda _device: "<hierarchy/>",
    )
    monkeypatch.setattr(
        "autoagent.executors.android_executor.dump_hierarchy_via_adb",
        lambda _device: "<hierarchy/>",
    )
