"""
Predictability Index (PI) de uma malha de controle — Bradu et al. (2017), "Automatic PID
performance monitoring applied to LHC cryogenics", a partir de Ghraizi et al. (2007).

Ideia: ajustar um modelo autorregressivo ao erro da malha `e = SP − PV` e ver quanto do erro `b`
amostras à frente ele consegue prever. Malha previsível (dinâmica regular) → PI perto de 1;
erro errático, tipo ruído branco → PI perto de 0. O artigo considera a malha mal sintonizada quando
PI fica abaixo de um limiar `PI_L` — o julgamento fica no plant-supervisor; aqui só o cálculo.

Parâmetros do artigo (eq. 3–5): `t_s` (amostragem), `t_W` (janela), `T` (constante de tempo da
malha em malha fechada) →  n = ceil(t_W / t_s),  b = ceil(T / t_s),  m = 2·b.

Nota sobre a eq. 2: o artigo imprime `PI = σ²_r / mse`, mas descreve PI = 1 para malha previsível
e PI = 0 para ruído branco, e usa "PI < PI_L → mal sintonizada". Com σ²_r / mse a escala sai
invertida (erro previsível → resíduo pequeno → razão perto de 0). Implementamos
`PI = 1 − σ²_r / mse`, que bate com a interpretação e os limiares do artigo, e devolvemos também a
razão crua (`ratio`) para transparência.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LoopResult:
    """`pi` é `None` quando o índice não é calculável (poucas amostras, erro identicamente
    zero) — melhor não ter número do que ter um número sem sentido."""

    pi: float | None
    ratio: float | None
    mse: float | None
    residual_var: float | None
    sigma_op: float | None
    n: int
    b: int
    m: int
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "pi": self.pi,
            "ratio": self.ratio,
            "mse": self.mse,
            "residual_var": self.residual_var,
            "sigma_op": self.sigma_op,
            "n": self.n,
            "b": self.b,
            "m": self.m,
            "reason": self.reason,
        }


def resample(series: list[tuple[float, float]], sample_interval_s: float) -> list[float]:
    """Decima uma série `(ts, valor)` para um grade de `sample_interval_s`: a última amostra de
    cada intervalo. Decimar (em vez de tirar média) preserva a variabilidade que o índice mede."""
    if not series:
        return []
    start = series[0][0]
    by_bin: dict[int, float] = {}
    for ts, value in series:
        by_bin[int((ts - start) // sample_interval_s)] = value
    return [by_bin[k] for k in sorted(by_bin)]


def predictability_index(
    error: list[float],
    op: list[float],
    *,
    sample_interval_s: float,
    time_constant_s: float,
    min_mse: float = 1e-12,
) -> LoopResult:
    """PI de uma malha a partir das séries já reamostradas em `sample_interval_s`."""
    b = max(1, math.ceil(time_constant_s / sample_interval_s))
    m = 2 * b
    e = np.asarray(error, dtype=float)
    n = int(e.size)
    sigma_op = float(np.std(op)) if len(op) else None

    rows = n - m - b + 1
    if rows < m + 2:
        return LoopResult(None, None, None, None, sigma_op, n, b, m, "too_few_samples")

    mse = float(np.mean(e**2))
    if mse < min_mse:
        return LoopResult(None, None, mse, None, sigma_op, n, b, m, "zero_error")

    # Linha i: [1, e(t), e(t-1), ..., e(t-m+1)] com t = i + m - 1; alvo e(t + b)  (eq. 1)
    lags = np.column_stack([e[m - 1 - j : m - 1 - j + rows] for j in range(m)])
    x = np.column_stack([np.ones(rows), lags])
    y = e[m - 1 + b : m - 1 + b + rows]
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ coef
    residual_var = float(np.var(residual))

    ratio = residual_var / mse
    pi = min(1.0, max(0.0, 1.0 - ratio))
    return LoopResult(pi, ratio, mse, residual_var, sigma_op, n, b, m)
