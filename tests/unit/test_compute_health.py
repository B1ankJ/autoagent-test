from autoagent.health.profile_health import HealthMetrics, compute_health


def _m(**kw):
    base = dict(
        total_runs=10, success_rate=1.0, unacked_anomalies=0,
        devices_online=None, devices_total=None,
    )
    base.update(kw)
    return HealthMetrics(**base)


def test_nodata_when_no_runs():
    assert compute_health(_m(total_runs=0, success_rate=None)) == "nodata"


def test_success_rate_thresholds():
    assert compute_health(_m(success_rate=0.95)) == "green"
    assert compute_health(_m(success_rate=0.8)) == "yellow"
    assert compute_health(_m(success_rate=0.4)) == "red"


def test_anomaly_thresholds():
    assert compute_health(_m(unacked_anomalies=0)) == "green"
    assert compute_health(_m(unacked_anomalies=1)) == "yellow"
    assert compute_health(_m(unacked_anomalies=5)) == "red"


def test_device_signal_only_when_applicable():
    assert compute_health(_m(devices_online=3, devices_total=3)) == "green"
    assert compute_health(_m(devices_online=1, devices_total=3)) == "yellow"
    assert compute_health(_m(devices_online=0, devices_total=3)) == "red"
    assert compute_health(_m(devices_online=None, devices_total=None)) == "green"
    # total set but no live online count → don't judge devices (no crash)
    assert compute_health(_m(devices_online=None, devices_total=3)) == "green"


def test_worst_of_wins():
    assert (
        compute_health(
            _m(success_rate=1.0, unacked_anomalies=5, devices_online=3, devices_total=3)
        )
        == "red"
    )
    assert compute_health(_m(success_rate=0.8, unacked_anomalies=0)) == "yellow"


def test_avg_duration_does_not_drive_color():
    assert compute_health(_m(success_rate=1.0, unacked_anomalies=0)) == "green"
