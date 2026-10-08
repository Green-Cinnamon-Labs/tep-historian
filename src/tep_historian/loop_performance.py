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

Desvio deliberado do artigo — o offset: as malhas do artigo são PID, sem erro em regime. As do TEP
aqui são proporcionais (P) e deixam um offset constante (ex.: pressão do reator ~9.4 kPa abaixo do
setpoint). Sobre o erro bruto, esse offset domina o mse e o intercepto do modelo AR o "prevê",
empurrando o PI para 1 sem relação com a sintonia. Por isso o PI (`pi`) é calculado sobre a
flutuação em torno da média, `ẽ = e − média(e)`, e o offset é devolvido à parte (`offset`). O PI
sobre o erro bruto continua disponível como `pi_raw`, só para comparação. Ver spec #87.
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
    offset: float | None
    pi_raw: float | None
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
            "offset": self.offset,
            "pi_raw": self.pi_raw,
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


def _fit_pi(e: "np.ndarray", b: int, m: int, rows: int) -> tuple[float, float, float]:
    """Ajuste AR da eq. 1 sobre `e`; devolve `(pi, ratio, residual_var)` com mse = média(e²)."""
    mse = float(np.mean(e**2))
    # Linha i: [1, e(t), e(t-1), ..., e(t-m+1)] com t = i + m - 1; alvo e(t + b)  (eq. 1)
    lags = np.column_stack([e[m - 1 - j : m - 1 - j + rows] for j in range(m)])
    x = np.column_stack([np.ones(rows), lags])
    y = e[m - 1 + b : m - 1 + b + rows]
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual_var = float(np.var(y - x @ coef))
    ratio = residual_var / mse
    return min(1.0, max(0.0, 1.0 - ratio)), ratio, residual_var


def predictability_index(
    error: list[float],
    op: list[float],
    *,
    sample_interval_s: float,
    time_constant_s: float,
    min_mse: float = 1e-12,
) -> LoopResult:
    """PI de uma malha a partir das séries já reamostradas em `sample_interval_s`. O PI principal é
    calculado sobre a flutuação do erro em torno da média; o offset sai à parte."""
    b = max(1, math.ceil(time_constant_s / sample_interval_s))
    m = 2 * b
    e = np.asarray(error, dtype=float)
    n = int(e.size)
    sigma_op = float(np.std(op)) if len(op) else None

    rows = n - m - b + 1
    if rows < m + 2:
        return LoopResult(None, None, None, None, None, None, sigma_op, n, b, m, "too_few_samples")

    offset = float(np.mean(e))
    pi_raw = _fit_pi(e, b, m, rows)[0] if float(np.mean(e**2)) >= min_mse else None

    fluctuation = e - offset
    mse = float(np.mean(fluctuation**2))
    if mse < min_mse:
        return LoopResult(None, None, offset, pi_raw, mse, None, sigma_op, n, b, m, "no_fluctuation")

    pi, ratio, residual_var = _fit_pi(fluctuation, b, m, rows)
    return LoopResult(pi, ratio, offset, pi_raw, mse, residual_var, sigma_op, n, b, m)
