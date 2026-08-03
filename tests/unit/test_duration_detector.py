from autoagent.anomalies.duration_detector import evaluate_duration


def test_returns_none_when_history_too_small():
    assert evaluate_duration(9999, [100, 200, 300]) is None


def test_flags_high_outlier():
    history = list(range(100, 120)) + [110] * 10  # 30 samples, tight around ~110
    verdict = evaluate_duration(10000, history)
    assert verdict is not None
    assert verdict["direction"] == "high"
    assert verdict["value"] == 10000
    assert verdict["fence_high"] < 10000
    assert verdict["sample_count"] == len(history)


def test_flags_low_outlier():
    history = list(range(1000, 1030))  # 30 samples ~1000-1029
    verdict = evaluate_duration(1, history)
    assert verdict is not None
    assert verdict["direction"] == "low"


def test_normal_value_returns_none():
    history = list(range(1000, 1030))
    assert evaluate_duration(1015, history) is None


def test_all_equal_history_only_flags_strict_outside():
    history = [500] * 25  # IQR 0 → fences both == 500
    assert evaluate_duration(500, history) is None
    assert evaluate_duration(501, history) is not None
    assert evaluate_duration(501, history)["direction"] == "high"
