"""A tela lê o INSTANTÂNEO, nunca a API.

Não é preferência: a Prolog tem teto de 100 por página e cota de cerca de dez
requisições por janela. Uma volta completa custa 86 requisições. Tela que
consultasse ao abrir derrubaria a integração no primeiro dia — e derrubaria
junto qualquer outra parte do sistema que dependesse da mesma cota.

Então a coleta é uma tarefa agendada e retomável (ver `coleta.py`), e aqui só
se lê o arquivo. Em troca, a tela DIZ de quando é o retrato e o quanto dele já
foi varrido — um número velho que se anuncia velho decide melhor que um número
fresco que não existe.
"""
from __future__ import annotations

from . import analise as an
from . import cliente as cli
from . import coleta


def obter(status: str = "", filial: str = "") -> dict:
    if not cli.pronto():
        falta = []
        if not cli.modo_auth():
            falta.append("credencial (PROLOG_TOKEN)")
        if not cli.filiais_configuradas():
            falta.append("PROLOG_FILIAIS (os ids das filiais da Sulista na "
                         "Prolog — a API exige e não há como adivinhar)")
        raise cli.PrologNaoConfigurado("falta " + " e ".join(falta))

    snap = coleta.ler()
    if not snap:
        raise cli.PrologNaoConfigurado(
            "ainda não houve coleta da Prolog. Rode "
            "`uv run python scripts/coletar_pneus.py` ou espere a tarefa "
            "agendada — a tela lê o instantâneo, não a API")

    pneus = snap.get("pneus") or []
    if status:
        alvos = {s.strip().upper() for s in status.split(",") if s.strip()}
        pneus = [p for p in pneus if p.get("status") in alvos]
    if filial:
        alvo = filial.strip().lower()
        pneus = [p for p in pneus if (p.get("filial") or "").lower() == alvo]

    d = an.analisar_normalizados(pneus)

    # marcas, funil, motivos e compras usam o snapshot COMPLETO por
    # definição (o rendimento de marca vive nos DESCARTES e as compras no
    # ERP) — a tela põe o badge "não segue o filtro de situação"
    todos = snap.get("pneus") or []
    d["marcas"] = an.marcas(todos)
    d["funil"] = an.funil(todos)
    d["sucata_motivos"] = an.sucata_motivos(todos)
    from api.pneus import compras_erp
    d["compras"] = compras_erp.compras()

    total_api = snap.get("total_na_api")
    lidos = len(snap.get("pneus") or [])
    d["filtros"] = {"status": status, "filial": filial}
    # a lista de filiais sai do instantâneo INTEIRO: filtrada, a filial
    # escolhida seria a única opção do próprio filtro e não haveria como voltar
    d["filiais"] = sorted({(p.get("filial") or "").strip()
                           for p in (snap.get("pneus") or [])} - {""})
    d["coleta"] = {
        "coletado_em": snap.get("coletado_em"),
        "primeira_pagina_em": snap.get("primeira_pagina_em"),
        "completo_em": snap.get("completo_em"),
        "voltas": snap.get("voltas") or 0,
        "lidos": lidos,
        "total_na_api": total_api,
        # QUANTO DO PARQUE JA ENTROU. Sem isto, "7 pneus abaixo do legal"
        # pareceria a frota inteira quando ainda e um terco dela.
        "cobertura_pct": (round(100 * lidos / total_api, 1)
                          if total_api else None),
        "em_andamento": bool(snap.get("cursor")),
        "status_coletado": snap.get("status_coletado"),
    }
    d["fonte"] = "Prolog · /api/v3/tires (instantâneo)"
    d["atualizado_em"] = (snap.get("coletado_em") or "").replace("T", " ")[:16]
    return d


def diagnostico() -> dict:
    """Estado da integração, sem expor segredo — alimenta a tela de Saúde."""
    snap = coleta.ler() or {}
    return {
        "modo_auth": cli.modo_auth() or "nenhuma",
        "filiais": cli.filiais_configuradas(),
        "base": cli.base_url(),
        "pronto": cli.pronto(),
        "coletado_em": snap.get("coletado_em"),
        "lidos": len(snap.get("pneus") or []),
        "total_na_api": snap.get("total_na_api"),
        "voltas": snap.get("voltas") or 0,
    }
