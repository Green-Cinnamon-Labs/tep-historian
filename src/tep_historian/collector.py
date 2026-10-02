"""
Coletor OPC-UA — lê periodicamente todos os nodes da pasta `Signals` e grava no `SignalBuffer`.

Genérico de propósito: não há lista de chaves TEP aqui. Qualquer node que o servidor
(`monjolo::adapter::opcua`) publicar sob `Signals` vira uma série. A resolução por browse name é a
mesma do `tep-ihm` (`src/server.py::_resolve_signal_nodes`), que por sua vez segue o cliente de
referência `monjolo/examples/opcua_browse.rs`.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .buffer import SignalBuffer

log = logging.getLogger("tep_historian.collector")


class CollectorState:
    """O que a API expõe sobre a saúde da coleta."""

    def __init__(self) -> None:
        self.connected = False
        self.last_sample_at: float | None = None
        self.last_error: str | None = None


async def resolve_signal_nodes(client) -> dict:
    """Browse `Objects → Signals` e devolve `{browse_name: Node}`. Casa por browse name em vez de
    assumir índice de namespace fixo, que o servidor atribui em tempo de execução."""
    objects = client.get_objects_node()
    signals_folder = None
    for node in await objects.get_children():
        if (await node.read_browse_name()).Name == "Signals":
            signals_folder = node
            break
    if signals_folder is None:
        raise RuntimeError('pasta "Signals" não encontrada — o servidor OPC-UA subiu sem sinais?')

    nodes_by_name = {}
    for node in await signals_folder.get_children():
        name = (await node.read_browse_name()).Name
        nodes_by_name[name] = node
    return nodes_by_name


def to_numeric(values: dict[str, object]) -> dict[str, float]:
    """Mantém só valores numéricos; booleanos viram 0/1 (ex.: `status.shutdown_detected`)."""
    numeric = {}
    for key, value in values.items():
        if isinstance(value, bool):
            numeric[key] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            numeric[key] = float(value)
    return numeric


async def run_collector(
    endpoint: str,
    buffer: SignalBuffer,
    state: CollectorState,
    interval_s: float,
    reconnect_s: float = 3.0,
) -> None:
    """Loop infinito: conecta, coleta a cada `interval_s`, reconecta em caso de erro. Diferente do
    `tep-ihm`, não desiste depois de N tentativas — o historian é infraestrutura e precisa voltar
    sozinho quando a planta voltar."""
    from asyncua import Client

    while True:
        try:
            async with Client(url=endpoint) as client:
                nodes_by_name = await resolve_signal_nodes(client)
                names = list(nodes_by_name)
                nodes = [nodes_by_name[n] for n in names]
                state.connected = True
                state.last_error = None
                log.info("conectado em %s — %d sinais", endpoint, len(names))

                while True:
                    raw = await client.read_values(nodes)
                    now = time.monotonic()
                    buffer.append(now, to_numeric(dict(zip(names, raw))))
                    state.last_sample_at = time.time()
                    await asyncio.sleep(interval_s)

        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — qualquer falha de rede/servidor → reconectar
            state.connected = False
            state.last_error = f"{type(e).__name__}: {e}"
            log.warning("coleta falhou (%s) — reconectando em %.0fs", state.last_error, reconnect_s)
            await asyncio.sleep(reconnect_s)
