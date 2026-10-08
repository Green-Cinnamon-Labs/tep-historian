"""
API HTTP do historian.

- `GET  /healthz`    → estado da coleta (conectado, última amostra, último erro).
- `GET  /signals`    → chaves disponíveis no buffer.
- `POST /aggregate`  → estatísticas por janela para as chaves pedidas.
- `POST /loop-performance` → Predictability Index de cada malha de controle pedida.

O `plant-supervisor` consome os dois: pede só as chaves que a `CostFunction` e a `OperatingPolicy`
ativas usam, e o historian não precisa saber o porquê. O historian calcula; quem julga (limiares,
persistência) é o supervisor.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .buffer import SignalBuffer
from .collector import CollectorState, run_collector
from .loop_performance import predictability_index, resample


class AggregateRequest(BaseModel):
    keys: list[str] = Field(min_length=1)
    window_s: float = Field(gt=0)


class LoopSpec(BaseModel):
    name: str = Field(min_length=1)
    pv: str = Field(min_length=1)
    sp: float
    op: str = Field(min_length=1)
    time_constant_s: float = Field(gt=0)


class LoopPerformanceRequest(BaseModel):
    loops: list[LoopSpec] = Field(min_length=1)
    window_s: float = Field(gt=0)
    sample_interval_s: float = Field(gt=0)


def create_app(
    buffer: SignalBuffer | None = None,
    state: CollectorState | None = None,
    start_collector: bool = True,
) -> FastAPI:
    """Monta o app. Testes passam `buffer`/`state` próprios e `start_collector=False`."""
    buffer = buffer or SignalBuffer(retention_s=float(os.environ.get("RETENTION_S", "3600")))
    state = state or CollectorState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if start_collector:
            endpoint = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://127.0.0.1:4840/tep/server/")
            interval_s = float(os.environ.get("SAMPLE_INTERVAL_MS", "500")) / 1000.0
            task = asyncio.create_task(run_collector(endpoint, buffer, state, interval_s))
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title="tep-historian", lifespan=lifespan)

    # Endpoints são `async def` de propósito: rodam no event loop, o mesmo onde o coletor faz
    # `buffer.append`. Um `def` comum iria para o threadpool do FastAPI e iteraria os deques
    # enquanto o coletor os altera ("deque mutated during iteration").
    @app.get("/healthz")
    async def healthz():
        return {
            "connected": state.connected,
            "last_sample_at": state.last_sample_at,
            "last_error": state.last_error,
            "signals": len(buffer.keys()),
        }

    @app.get("/signals")
    async def signals():
        return {"keys": buffer.keys()}

    @app.post("/aggregate")
    async def aggregate(req: AggregateRequest):
        stats = buffer.aggregate(req.keys, req.window_s, now=time.monotonic())
        return {
            "window_s": req.window_s,
            "connected": state.connected,
            "signals": {key: s.to_dict() for key, s in stats.items()},
            "missing": [key for key in req.keys if key not in stats],
        }

    @app.post("/loop-performance")
    async def loop_performance(req: LoopPerformanceRequest):
        keys = {k for loop in req.loops for k in (loop.pv, loop.op)}
        raw = buffer.series(keys, req.window_s, now=time.monotonic())
        loops = {}
        for loop in req.loops:
            if loop.pv not in raw or loop.op not in raw:
                loops[loop.name] = {"pi": None, "reason": "missing_signal"}
                continue
            # PV e OP alinhados pelo timestamp (o coletor grava todas as chaves no mesmo instante)
            op_at = dict(raw[loop.op])
            pairs = [(ts, pv) for ts, pv in raw[loop.pv] if ts in op_at]
            error = resample([(ts, loop.sp - pv) for ts, pv in pairs], req.sample_interval_s)
            op = resample([(ts, op_at[ts]) for ts, _ in pairs], req.sample_interval_s)
            loops[loop.name] = predictability_index(
                error,
                op,
                sample_interval_s=req.sample_interval_s,
                time_constant_s=loop.time_constant_s,
            ).to_dict()
        return {"window_s": req.window_s, "connected": state.connected, "loops": loops}

    return app
