import numpy as np
from fastapi.testclient import TestClient

from tep_historian.api import create_app
from tep_historian.buffer import SignalBuffer
from tep_historian.collector import CollectorState
from tep_historian.loop_performance import predictability_index, resample

RNG = np.random.default_rng(0)


def pi_of(error, op=None, ts=1.0, tc=3.0):
    op = op if op is not None else list(RNG.normal(50, 1, len(error)))
    return predictability_index(list(error), op, sample_interval_s=ts, time_constant_s=tc)


def test_white_noise_error_is_unpredictable():
    r = pi_of(RNG.normal(0, 1, 2000))
    assert r.pi is not None and r.pi < 0.05, r


def test_slow_autocorrelated_error_is_predictable():
    e = np.zeros(2000)
    for t in range(1, 2000):
        e[t] = 0.98 * e[t - 1] + RNG.normal(0, 1)
    r = pi_of(e)
    assert r.pi is not None and r.pi > 0.8, r


def test_constant_offset_has_no_fluctuation_and_is_reported_apart():
    r = pi_of(np.full(500, 2.0))
    assert r.pi is None and r.reason == "no_fluctuation"
    assert r.offset == 2.0
    assert r.pi_raw == 1.0  # sobre o erro bruto o offset parece "perfeitamente previsível"


def test_offset_does_not_inflate_the_index():
    # Ruído branco em torno de um offset grande: PI bruto ~1 (artefato), PI da flutuação ~0
    r = pi_of(9.4 + RNG.normal(0, 0.3, 2000))
    assert abs(r.offset - 9.4) < 0.05
    assert r.pi_raw > 0.95
    assert r.pi < 0.05


def test_identically_zero_error_has_no_index():
    r = pi_of(np.zeros(500))
    assert r.pi is None and r.reason == "no_fluctuation" and r.pi_raw is None


def test_too_few_samples_has_no_index():
    r = pi_of(RNG.normal(0, 1, 10), tc=5.0)
    assert r.pi is None and r.reason == "too_few_samples"


def test_parameters_follow_the_article():
    # t_s = 10 s, T = 2 min  →  b = ceil(120/10) = 12, m = 2b = 24  (eq. 4–5)
    r = predictability_index(list(RNG.normal(0, 1, 400)), [0.0] * 400, sample_interval_s=10, time_constant_s=120)
    assert (r.b, r.m) == (12, 24)


def test_sigma_op_is_the_std_of_the_controller_output():
    op = list(RNG.normal(40, 0.5, 2000))
    r = pi_of(RNG.normal(0, 1, 2000), op=op)
    assert abs(r.sigma_op - 0.5) < 0.05


def test_resample_keeps_last_sample_of_each_interval():
    series = [(0.0, 1.0), (0.4, 2.0), (1.1, 3.0), (1.6, 4.0), (2.2, 5.0)]
    assert resample(series, 1.0) == [2.0, 4.0, 5.0]


def test_endpoint_computes_each_loop_and_reports_missing_signals():
    buf = SignalBuffer(retention_s=10_000)
    e = np.zeros(3000)
    for t in range(1, 3000):
        e[t] = 0.98 * e[t - 1] + RNG.normal(0, 1)
    for t in range(3000):
        buf.append(float(t), {"pv": 50.0 - e[t], "op": 40.0 + RNG.normal(0, 1)})
    state = CollectorState()
    state.connected = True

    import tep_historian.api as api_module

    real_monotonic = api_module.time.monotonic
    api_module.time.monotonic = lambda: 3000.0
    try:
        with TestClient(create_app(buffer=buf, state=state, start_collector=False)) as c:
            body = c.post(
                "/loop-performance",
                json={
                    "loops": [
                        {"name": "level", "pv": "pv", "sp": 50.0, "op": "op", "time_constant_s": 3},
                        {"name": "ghost", "pv": "nope", "sp": 1.0, "op": "op", "time_constant_s": 3},
                    ],
                    "window_s": 3000,
                    "sample_interval_s": 1,
                },
            ).json()
    finally:
        api_module.time.monotonic = real_monotonic

    assert body["loops"]["level"]["pi"] > 0.8
    assert body["loops"]["ghost"] == {"pi": None, "reason": "missing_signal"}


def test_endpoint_validates_input():
    with TestClient(create_app(buffer=SignalBuffer(retention_s=10), state=CollectorState(), start_collector=False)) as c:
        assert c.post("/loop-performance", json={"loops": [], "window_s": 60, "sample_interval_s": 1}).status_code == 422
