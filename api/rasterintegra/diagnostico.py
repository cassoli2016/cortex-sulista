# -*- coding: utf-8 -*-
"""Diagnóstico do RasterIntegra para a Saúde do Servidor.

Custo EXTERNO leva cache com TTL (regra da casa: a Saúde recarrega a cada
olhada e não pode gastar o rate-limit do fornecedor a cada F5). Sem
credencial NÃO é falha: é instalação incompleta — `info`, nunca alarme.
"""
from __future__ import annotations

import time

from api.rasterintegra import cliente

_CACHE: dict = {}
_TTL = 600.0  # 10 min: prova de vida, não monitoração


def diagnostico(force: bool = False) -> dict:
    if not cliente.configurado():
        return {"configurado": False}
    agora = time.time()
    hit = _CACHE.get("d")
    if hit and not force and agora - hit[0] < _TTL:
        return hit[1]
    try:
        t = cliente.testar()
        out = {"configurado": True, "ok": True, "itens": t.get("itens", 0)}
    except cliente.MetodoNaoLiberado as exc:
        out = {"configurado": True, "ok": False, "erro": str(exc)}
    except Exception as exc:  # noqa: BLE001
        out = {"configurado": True, "ok": False,
               "erro": f"{type(exc).__name__}: {str(exc)[:160]}"}
    _CACHE["d"] = (agora, out)
    return out
