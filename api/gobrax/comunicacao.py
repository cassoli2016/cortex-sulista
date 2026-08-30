"""Veículo que parou de mandar dado para a Gobrax.

O DENOMINADOR É O PONTO
=======================
"Quantos veículos estão sem comunicar" só significa alguma coisa se o
denominador contiver apenas quem PODE comunicar. É a lição que custou caro na
Comunicação Rastreadora: 664 de 836 rastreadores apareciam "sem sinal" e 79%
disso era cadastro — veículo de terceiro que não integra e implemento que não
emite. O número parecia crise e era ruído.

Aqui o universo é **quem a Gobrax conhece na competência**, isto é, as placas
que aparecem no cache de `vehicle-statistics`. Veículo sem equipamento Gobrax
não entra na conta, porque não tem como cumprir a regra.

O QUE A API ENTREGA, E O QUE ELA NÃO ENTREGA
============================================
`/api/v2/positions` devolve as **últimas 20 posições de cada veículo, e ignora
a janela pedida** — medido em 30/08/2026: as janelas de 2 e de 7 dias
devolveram exatamente os mesmos 1.960 pontos, 20 por veículo. Duas
consequências:

1. A **última** posição é confiável, e é ela que responde "quando falou pela
   última vez". É o que este módulo usa.
2. **Não dá para dizer "parado há 5 dias"** para quem sumiu antes do que essas
   20 posições cobrem. Quem a Gobrax conhece e não aparece na resposta entra
   como `sem_posicao` — que é PIOR que um atraso medido, não igual, e por isso
   sai destacado em vez de virar um número grande na mesma coluna.

Inventar "há mais de 7 dias" a partir da ausência seria afirmar o que a fonte
não disse.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from api.gobrax import armazenamento
from api.gobrax.cliente import Cliente, periodo_api

CAMINHO = "/api/v2/positions"
COLECAO = "comunicacao"

# 24 h é o limite que o usuário pediu. Fica como padrão de função, e não como
# constante escondida, porque a régua do que é "parado" muda com a operação:
# um veículo em manutenção programada não comunica e não é problema.
LIMITE_H = 24


def _quando(valor) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("T", " ")[:19])
    except ValueError:
        return None


def coletar(cliente=None, dias: int = 2) -> list[dict]:
    """Última posição de cada veículo que a Gobrax tem.

    `dias` existe para a chamada ter um período válido, não para recortar: a
    API devolve as últimas 20 posições independentemente dele.
    """
    c = cliente or Cliente()
    hoje = datetime.now().date()
    ini, fim = periodo_api(hoje - timedelta(days=dias), hoje)
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim}, timeout=180)
    saida = []
    for v in (corpo.get("data") or []):
        placa = (v.get("identification") or "").strip()
        if not placa:
            continue
        datas = [_quando(p.get("date")) for p in (v.get("positions") or [])]
        datas = [d for d in datas if d]
        if not datas:
            continue
        ultima = max(datas)
        saida.append({"placa": placa,
                      "ultima": ultima.isoformat(timespec="seconds"),
                      "posicoes": len(datas)})
    return saida


def sincronizar(cliente=None, path: Path | None = None) -> dict:
    """Grava na competência do dia: é um retrato do AGORA, não do mês."""
    linhas = coletar(cliente)
    hoje = datetime.now().date()
    comp = f"{hoje.year:04d}-{hoje.month:02d}"
    gravadas = armazenamento.gravar(COLECAO, comp, linhas, path)
    return {"competencia": comp, "gravadas": gravadas}


def estado(competencia: str | None = None, *, limite_h: int = LIMITE_H,
           agora: datetime | None = None, path: Path | None = None) -> dict:
    """Quem está sem comunicar, contra o universo de quem deveria.

    Três grupos, e a separação importa porque cada um tem conserto diferente:

    - **em dia** — comunicou dentro do limite;
    - **atrasado** — comunicou, mas há mais que o limite. Dá para dizer HÁ
      QUANTO, e é o caso que costuma ser equipamento sem energia ou veículo
      parado em pátio;
    - **sem posição** — a Gobrax conhece a placa e ela não aparece na resposta.
      Está calado há mais tempo do que a janela da API mostra, e é o mais
      grave: nem o "há quanto" existe.
    """
    agora = agora or datetime.now()
    hoje = agora.date()
    comp = competencia or f"{hoje.year:04d}-{hoje.month:02d}"

    # o universo: quem a Gobrax conhece na competência
    est = armazenamento.ler("estatisticas", comp, path)
    universo = sorted({(l.get("placa") or "").strip() for l in est
                       if (l.get("placa") or "").strip()})

    pos = {l["placa"]: l for l in armazenamento.ler(COLECAO, comp, path)
           if l.get("placa")}

    em_dia, atrasados, sem_posicao = [], [], []
    for placa in universo:
        p = pos.get(placa)
        d = _quando(p.get("ultima")) if p else None
        if d is None:
            sem_posicao.append({"placa": placa, "horas": None,
                                "ultima": None})
            continue
        horas = (agora - d).total_seconds() / 3600
        reg = {"placa": placa, "horas": round(horas, 1),
               "ultima": d.isoformat(timespec="seconds")}
        (atrasados if horas > limite_h else em_dia).append(reg)

    # o mais calado primeiro: é a ordem em que alguém age
    atrasados.sort(key=lambda r: -r["horas"])
    sem_posicao.sort(key=lambda r: r["placa"])

    # placas que a resposta trouxe e o cache de estatísticas não conhece: não
    # são falha nossa nem do fornecedor, são veículo que rodou sem gerar
    # estatística no mês (entrou agora, por exemplo). Fica dito, não escondido.
    fora_do_universo = sorted(set(pos) - set(universo))

    return {
        "competencia": comp,
        "limite_h": limite_h,
        "medido_em": agora.isoformat(timespec="seconds"),
        "universo": len(universo),
        "em_dia": len(em_dia),
        "atrasados": atrasados,
        "sem_posicao": sem_posicao,
        "fora_do_universo": fora_do_universo,
        # o número que vai para o cartão: os dois grupos que exigem ação
        "a_olhar": len(atrasados) + len(sem_posicao),
    }
