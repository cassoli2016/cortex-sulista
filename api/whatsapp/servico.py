"""Diagnóstico da integração de WhatsApp — alimenta a tela de Saúde do Servidor.

Regra herdada da Monkey e da Prolog: a Saúde recarrega a cada 5 segundos, então
`diagnostico()` NÃO PODE sair para a rede a cada chamada. Aqui isso é ainda mais
sério que nas outras integrações, porque o que interessa saber (o aparelho está
conectado?) só existe na API do fornecedor — não há posição gravada para ler.

A saída é `cliente.estado()`, que tem cache de 60 s. Assim a tela mostra o
estado real com até um minuto de atraso, custando ~1.440 chamadas por dia em
vez das ~17.000 que o refresh de 5 s produziria.
"""
from __future__ import annotations

from . import cliente, config as cfg, registro


def diagnostico() -> dict:
    """Sem segredo nenhum na saída — a Saúde é uma tela, não um cofre."""
    c = cfg.ler()
    d = {
        "configurado": cliente.configurado(),
        "ativo": bool(c["ativo"]),
        "client_token": bool(cliente.client_token()),
        "limite_dia": c["limite_dia"],
        "janela": f"{c['janela_inicio']}–{c['janela_fim']}",
        "dentro_da_janela": cfg.dentro_da_janela(),
        "conectado": False,
        "celular": False,
        "erro": "",
        "hoje": 0,
        "ultimo": None,
        "falhas": 0,
    }
    if not d["configurado"]:
        return d

    est = cliente.estado()
    d["conectado"] = bool(est.get("conectado"))
    d["celular"] = bool(est.get("celular"))
    d["erro"] = est.get("erro") or ""

    try:
        r = registro.resumo()
        d["hoje"] = r["hoje"]
        d["ultimo"] = r["ultimo"]
        d["falhas"] = r["falha"]
    except Exception:   # noqa: BLE001
        # banco local fora não pode apagar a linha da integração na Saúde —
        # é justamente onde se olha quando algo está errado
        pass
    return d
