"""
Buffer em memória dos sinais coletados — uma série `(timestamp, valor)` por chave.

Não sabe nada de TEP: qualquer chave que o coletor entregar vira uma série. É aqui que mora toda a
matemática de janela (média, desvio padrão, mín/máx), isolada do OPC-UA para poder ser testada sem
planta rodando.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class WindowStats:
    """Estatísticas de uma chave dentro da janela. `count == 0` → janela sem amostras, os demais
    campos ficam `None` (não inventar valor)."""

    count: int
    mean: float | None
    std: float | None
    min: float | None
    max: float | None
    last: float | None

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "last": self.last,
        }


EMPTY = WindowStats(count=0, mean=None, std=None, min=None, max=None, last=None)


class SignalBuffer:
    """Séries temporais por chave, com retenção em segundos. Timestamps são monotônicos e vêm de
    quem chama (`append`/`aggregate` recebem `now`) — facilita teste e evita depender de relógio."""

    def __init__(self, retention_s: float):
        if retention_s <= 0:
            raise ValueError("retention_s precisa ser > 0")
        self.retention_s = retention_s
        self._series: dict[str, deque[tuple[float, float]]] = {}

    def keys(self) -> list[str]:
        return sorted(self._series)

    def append(self, ts: float, values: Mapping[str, float]) -> None:
        """Registra uma amostra de cada chave em `values` no instante `ts` e descarta o que saiu
        da retenção."""
        for key, value in values.items():
            series = self._series.setdefault(key, deque())
            series.append((ts, float(value)))
        self._prune(ts)

    def aggregate(self, keys: Iterable[str], window_s: float, now: float) -> dict[str, WindowStats]:
        """Estatísticas de cada chave nas amostras com `ts > now - window_s`. Chave desconhecida
        não aparece no resultado — quem chama decide o que fazer com ela."""
        if window_s <= 0:
            raise ValueError("window_s precisa ser > 0")
        start = now - window_s
        result: dict[str, WindowStats] = {}
        for key in keys:
            series = self._series.get(key)
            if series is None:
                continue
            values = [v for ts, v in series if ts > start]
            result[key] = _stats(values)
        return result

    def _prune(self, now: float) -> None:
        cutoff = now - self.retention_s
        for series in self._series.values():
            while series and series[0][0] <= cutoff:
                series.popleft()


def _stats(values: list[float]) -> WindowStats:
    n = len(values)
    if n == 0:
        return EMPTY
    mean = sum(values) / n
    # Desvio padrão populacional: a janela é a população que interessa, não uma amostra dela.
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    return WindowStats(count=n, mean=mean, std=std, min=min(values), max=max(values), last=values[-1])
