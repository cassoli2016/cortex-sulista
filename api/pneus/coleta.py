"""Coleta da Prolog em INSTANTÂNEO retomável — a tela lê o arquivo, não a API.

DUAS RESTRIÇÕES DURAS, as duas medidas contra a API de verdade:

1. O teto de página é 100. São 8.572 pneus nas quatro filiais, ou seja 86
   requisições para uma volta completa.
2. A cota é de cerca de DEZ requisições por janela. Medido: a coleta parou
   sozinha na décima página com 429, e a cota se recompôs em minutos.

Dez de oitenta e seis. Uma coleta "de uma vez" não existe aqui — então ela é
RETOMÁVEL: cada execução avança o que a cota permitir, grava onde parou, e a
próxima continua dali. Depois de algumas rodadas o retrato está completo, e a
partir daí ele se renova em volta.

Isso torna o instantâneo levemente heterogêneo no tempo (a primeira página é
mais velha que a última). Para pneu, que muda em semanas, é irrelevante — e a
tela diz de quando é cada coisa em vez de fingir que é tudo de agora.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import analise as an
from . import cliente as cli

ROOT = Path(__file__).resolve().parent.parent.parent
DIR = ROOT / "data" / "pneus"
ATUAL = DIR / "pneus-atual.json"

# Segundos entre paginas. Nao e gentileza: espacar reduz a chance de bater no
# limite de janela antes de aproveitar a cota inteira.
PAUSA_S = 1.5

# Teto por execucao. Fica um pouco ABAIXO da cota observada de propósito: a
# execucao que termina por conta propria deixa a integracao saudavel, a que
# termina em 429 deixa a proxima chamada de qualquer outra tela falhando.
PAGINAS_POR_EXECUCAO = 8


def _escrever_atomico(caminho: Path, conteudo: str) -> None:
    """Arquivo temporario no MESMO diretorio + os.replace: a tela pode estar
    lendo enquanto a tarefa grava, e um arquivo pela metade viraria JSON
    invalido na cara do usuario."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(caminho.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(conteudo)
        os.replace(tmp, caminho)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def ler() -> dict | None:
    """Instantaneo mais recente, ou None se ainda nao houve coleta."""
    try:
        return json.loads(ATUAL.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _estado() -> dict:
    d = ler() or {}
    return {
        "pneus": {str(p["id"]): p for p in (d.get("pneus") or []) if p.get("id")},
        "cursor": int(d.get("cursor") or 0),
        "voltas": int(d.get("voltas") or 0),
        "primeira_pagina_em": d.get("primeira_pagina_em"),
        "completo_em": d.get("completo_em"),
        "status_coletado": d.get("status_coletado"),
    }


def coletar(status: list[str] | None = None, pausa: float = PAUSA_S,
            paginas: int = PAGINAS_POR_EXECUCAO, http=None) -> dict:
    """Avanca a coleta a partir de onde parou e regrava o instantaneo."""
    if not cli.pronto():
        raise cli.PrologNaoConfigurado(
            "integracao da Prolog incompleta — rode "
            "scripts/verificar_prolog.py para ver o que falta")

    st = _estado()
    alvo = status or st.get("status_coletado") or list(cli.STATUS)
    # trocar o recorte invalida o acumulado: misturar volta de INSTALLED com
    # volta de tudo produziria um retrato que nunca existiu
    if st.get("status_coletado") and sorted(st["status_coletado"]) != sorted(alvo):
        st = {"pneus": {}, "cursor": 0, "voltas": 0,
              "primeira_pagina_em": None, "completo_em": None}

    c = cli.Cliente(http=http)
    params: dict = {"branchOfficesId": cli.filiais_configuradas()}
    if status:
        params["tireStatuses"] = status

    t0 = time.monotonic()
    pagina = st["cursor"]
    if pagina == 0:
        st["primeira_pagina_em"] = datetime.now().isoformat(timespec="seconds")
    lidas, novos, fim_de_volta, cota = 0, 0, False, False
    total_api = None

    while lidas < paginas:
        try:
            d = c.get("/api/v3/tires", {**params, "pageSize": cli.PAGINA_MAX,
                                       "pageNumber": pagina})
        except cli.PrologIndisponivel as exc:
            if "cota" not in str(exc).lower():
                raise
            cota = True
            break
        total_api = d.get("totalElements", total_api)
        lote = d.get("content") or []
        for r in lote:
            chave = str(r.get("id"))
            if chave not in st["pneus"]:
                novos += 1
            st["pneus"][chave] = an.pneu(r)
        lidas += 1
        pagina += 1
        if not lote or d.get("lastPage") is True:
            fim_de_volta = True
            break
        if pausa and lidas < paginas:
            time.sleep(pausa)

    if fim_de_volta:
        st["cursor"] = 0
        st["voltas"] += 1
        st["completo_em"] = datetime.now().isoformat(timespec="seconds")
    else:
        st["cursor"] = pagina

    lista = list(st["pneus"].values())
    kpis = an.analisar_normalizados(lista)["kpis"]
    snap = {
        "coletado_em": datetime.now().isoformat(timespec="seconds"),
        "primeira_pagina_em": st["primeira_pagina_em"],
        "completo_em": st["completo_em"],
        "cursor": st["cursor"],
        "voltas": st["voltas"],
        "total_na_api": total_api,
        "filiais": cli.filiais_configuradas(),
        "status_coletado": alvo,
        "kpis": kpis,
        "pneus": lista,
    }
    _escrever_atomico(ATUAL, json.dumps(snap, ensure_ascii=False, default=str))
    return {
        "paginas_lidas": lidas, "novos": novos, "acumulado": len(lista),
        "total_na_api": total_api, "cursor": st["cursor"],
        "voltas": st["voltas"], "volta_fechou": fim_de_volta,
        "parou_por_cota": cota,
        "segundos": round(time.monotonic() - t0, 1),
        "kpis": kpis,
    }
