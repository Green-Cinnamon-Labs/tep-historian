import math

import pytest

from tep_historian.buffer import SignalBuffer
from tep_historian.collector import to_numeric


def test_aggregate_computes_window_stats():
    buf = SignalBuffer(retention_s=100)
    for t, v in [(1, 2.0), (2, 4.0), (3, 4.0), (4, 4.0), (5, 5.0), (6, 5.0), (7, 7.0), (8, 9.0)]:
        buf.append(t, {"x": v})

    s = buf.aggregate(["x"], window_s=10, now=8)["x"]

    assert s.count == 8
    assert s.mean == pytest.approx(5.0)
    assert s.std == pytest.approx(2.0)  # exemplo clássico de desvio padrão populacional
    assert (s.min, s.max, s.last) == (2.0, 9.0, 9.0)


def test_window_excludes_older_samples():
    buf = SignalBuffer(retention_s=100)
    for t in range(10):
        buf.append(t, {"x": float(t)})

    s = buf.aggregate(["x"], window_s=3, now=9)["x"]  # ts > 6 → 7, 8, 9

    assert s.count == 3
    assert s.mean == pytest.approx(8.0)


def test_retention_drops_old_samples():
    buf = SignalBuffer(retention_s=5)
    for t in range(20):
        buf.append(t, {"x": 1.0})

    assert buf.aggregate(["x"], window_s=1000, now=19)["x"].count == 5


def test_unknown_key_is_absent_and_empty_window_has_no_values():
    buf = SignalBuffer(retention_s=100)
    buf.append(0, {"x": 1.0})

    result = buf.aggregate(["x", "nope"], window_s=1, now=50)

    assert "nope" not in result
    assert result["x"].count == 0
    assert result["x"].mean is None


def test_invalid_parameters():
    with pytest.raises(ValueError):
        SignalBuffer(retention_s=0)
    with pytest.raises(ValueError):
        SignalBuffer(retention_s=1).aggregate(["x"], window_s=0, now=0)


def test_to_numeric_keeps_numbers_and_maps_bools():
    out = to_numeric({"a": 1, "b": 2.5, "flag": True, "off": False, "s": "txt", "n": None})
    assert out == {"a": 1.0, "b": 2.5, "flag": 1.0, "off": 0.0}
    assert all(not math.isnan(v) for v in out.values())
