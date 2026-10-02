import time

from fastapi.testclient import TestClient

from tep_historian.api import create_app
from tep_historian.buffer import SignalBuffer
from tep_historian.collector import CollectorState


def make_client():
    buf = SignalBuffer(retention_s=3600)
    now = time.monotonic()
    for i in range(5):
        buf.append(now - i, {"xmeas.a": 10.0 + i, "xmeas.b": 1.0})
    state = CollectorState()
    state.connected = True
    return TestClient(create_app(buffer=buf, state=state, start_collector=False))


def test_signals_lists_keys():
    with make_client() as c:
        assert c.get("/signals").json() == {"keys": ["xmeas.a", "xmeas.b"]}


def test_aggregate_returns_stats_and_missing():
    with make_client() as c:
        body = c.post("/aggregate", json={"keys": ["xmeas.a", "xmeas.zzz"], "window_s": 60}).json()

    assert body["connected"] is True
    assert body["missing"] == ["xmeas.zzz"]
    a = body["signals"]["xmeas.a"]
    assert a["count"] == 5
    assert a["mean"] == 12.0


def test_aggregate_validates_input():
    with make_client() as c:
        assert c.post("/aggregate", json={"keys": [], "window_s": 60}).status_code == 422
        assert c.post("/aggregate", json={"keys": ["x"], "window_s": 0}).status_code == 422


def test_healthz():
    with make_client() as c:
        body = c.get("/healthz").json()
    assert body["connected"] is True
    assert body["signals"] == 2
