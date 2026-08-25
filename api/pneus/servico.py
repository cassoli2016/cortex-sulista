"""Orquestra a coleta da Prolog e entrega a tela pronta.

Cache curto: a Prolog e uma API externa e a frota de pneus nao muda de minuto
a minuto. Sem cache, cada troca de filtro na tela viraria uma varredura
paginada inteira do outro lado.
"""
from __future__ import annotations

from datetime import datetime

from ..queries import cached
from . import analise as an
from . import cliente as cli

TTL = 300


@cached(ttl=TTL)
def _coletar(status: str = "") -> list[dict]:
    alvos = [s for s in (status or "").split(",") if s.strip()] or None
    return cli.Cliente().pneus(status=alvos)


def obter(status: str = "", filial: str = "") -> dict:
    """Tela de pneus. `status` e aplicado NA API (menos tráfego); `filial` e
    aplicado aqui, para nao multiplicar chave de cache — o mesmo padrao do
    Painel de Custos."""
    if not cli.pronto():
        # a mensagem diz o que falta: "nao configurado" sem dizer o que
        # configurar obriga a abrir o codigo
        falta = []
        if not cli.modo_auth():
            falta.append("credencial (PROLOG_TOKEN, ou usuario+senha, ou "
                         "client_id+secret)")
        if not cli.filiais_configuradas():
            falta.append("PROLOG_FILIAIS (os ids das filiais da Sulista na "
                         "Prolog — a API exige e nao ha como adivinhar)")
        raise cli.PrologNaoConfigurado("falta " + " e ".join(falta))

    brutos = _coletar(status)

    # FILTRA O BRUTO e analisa UMA vez. Filtrar depois de analisar deixaria os
    # indicadores falando da frota inteira enquanto a tabela mostra uma filial
    # — o descasamento que a Análise de KM já teve entre cabeçalho e tabela.
    if filial:
        alvo = filial.strip().lower()
        brutos = [r for r in brutos
                  if str(r.get("branchOfficeName") or "").strip().lower() == alvo]

    d = an.analisar(brutos)
    d["filtros"] = {"status": status, "filial": filial}
    # a lista de filiais tem de vir de TODOS os pneus, nao do recorte: filtrada,
    # a filial escolhida seria a unica opcao do proprio filtro e nao haveria
    # como voltar
    d["filiais"] = sorted({str(r.get("branchOfficeName") or "").strip()
                          for r in _coletar(status)} - {""})
    d["fonte"] = "Prolog · /api/v3/tires"
    d["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return d


def diagnostico() -> dict:
    """Estado da integração, sem expor segredo — alimenta a tela de Saúde."""
    return {
        "modo_auth": cli.modo_auth() or "nenhuma",
        "filiais": cli.filiais_configuradas(),
        "base": cli.base_url(),
        "pronto": cli.pronto(),
    }
