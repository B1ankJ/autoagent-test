from autoagent.executors.android_input import resolve_input_method


def test_auto_uses_adb_keyboard_for_non_ascii() -> None:
    assert resolve_input_method("auto", "你好") == "adb_keyboard"
