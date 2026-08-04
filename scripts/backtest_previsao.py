# scripts/backtest_previsao.py
"""Backtest da previsão de fechamento — roda o motor "as-of" datas passadas.

lancamento.dtinc reconstrói o razão como era visível em cada data; o driver
fiscal usa dtemissao (data do documento) e a meta é estática — as-of exato.
Aproximações declaradas:
- viagens as-of por dtsaida (a data de INCLUSÃO da programação não é
  filtrável aqui);
- histórico (hist_ag/indices_sazonais) as-of o 1º dia do MÊS ALVO (`prim`),
  não a data real de execução do backtest. Rodar ao vivo em, digamos, fev/26
  só veria o razão histórico como estava assentado até fev/26 — usar "hoje"
  (a data real de hoje) deixaria os meses mais antigos do histórico
  artificialmente mais maduros que os mais recentes (viés otimista: bandas
  calibradas ficariam mais estreitas do que uma previsão ao vivo veria). Isto
  NÃO se aplica à curva de completude (COMPLETUDE_SQL): ela só mede meses já
  fechados nos dois casos, então é consistente sem ajuste.

Uso: uv run python scripts/backtest_previsao.py [--meses 6] [--dias 5,10,15,20,25]
Gera: data/previsao_calibracao.json + docs/previsao-backtest.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# "python scripts/backtest_previsao.py" põe sys.path[0] = scripts/ (diretório
# do script), não a raiz do repo — sem isto "from api import ..." falha com
# ModuleNotFoundError mesmo rodando via `uv run` a partir da raiz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db
from api.orcamento.derivacao import indices_sazonais
from api.previsao.completude import montar_curva
from api.previsao.motor import linha_do_agrupador
from api.previsao.servico import _hist_linha, montar_resposta
from api.previsao.sql import (COMPLETUDE_SQL, DIARIO_ASOF_SQL, RAZAO_ASOF_SQL,
                              VFC_MTD_SQL, meses_fechados_prev)
from api.queries import DRE_MODELO, _comp_bounds

ROOT = Path(__file__).resolve().parent.parent


def _percentil(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _razao_asof(de: str, ate: str, asof: str) -> dict[str, dict[str, float]]:
    rows = db.query(RAZAO_ASOF_SQL, {"de": de, "ate": ate, "asof": asof})
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        out.setdefault(r["agrupador"], {})[r["mes"]] = \
            out.get(r["agrupador"], {}).get(r["mes"], 0.0) + r["valor"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meses", type=int, default=6)
    ap.add_argument("--dias", default="5,10,15,20,25")
    args = ap.parse_args()
    dias = [int(d) for d in args.dias.split(",")]
    hoje = date.today()
    alvos = meses_fechados_prev(hoje, args.meses)

    erros: dict[str, dict[int, list[float]]] = {}
    relatorio = ["# Backtest da previsão de fechamento", "",
                 f"Gerado em {hoje.isoformat()} · meses: {', '.join(alvos)}", ""]

    for mes in alvos:
        de_m, ate_m = _comp_bounds(mes, mes)
        prim = date(int(mes[:4]), int(mes[5:7]), 1)
        # "final" = razão com tudo que existe hoje
        final_ag = _razao_asof(de_m, ate_m, hoje.isoformat())
        final_linha: dict[str, float] = {}
        for ag, serie in final_ag.items():
            rot = linha_do_agrupador(ag)
            if rot:
                final_linha[rot] = final_linha.get(rot, 0.0) + serie.get(mes, 0.0)
        diario_rows = db.query(DIARIO_ASOF_SQL, {"de": de_m, "ate": ate_m})
        meta_mes = sum(r["meta"] for r in diario_rows)

        # historico/curva/indices SEM olhar o futuro: fechados ANTES do mes alvo.
        # asof = prim (1o dia do mes alvo), NAO hoje: senao o historico de um
        # mes-alvo antigo (ex. fev/26) enxergaria assentamento contabil que so
        # existe porque estamos rodando o backtest hoje - vazamento as-of que
        # deixaria a calibracao otimista demais (bandas mais estreitas do que
        # uma previsao ao vivo veria).
        hist_meses = meses_fechados_prev(prim, 24)
        de_h = f"{hist_meses[0]}-01"
        _, ate_h = _comp_bounds(hist_meses[-1], hist_meses[-1])
        hist_por_ag_full = _razao_asof(de_h, ate_h, prim.isoformat())
        hist_ag = {ag: {m: v for m, v in serie.items() if m in hist_meses}
                   for ag, serie in hist_por_ag_full.items()}
        curva_meses = meses_fechados_prev(prim, 6)
        rows_c = db.query(COMPLETUDE_SQL, {"de": f"{curva_meses[0]}-01",
                                           "ate": de_m})
        ags = {r["agrupador"] for r in rows_c}
        curva = montar_curva([dict(r) for r in rows_c],
                             {a: linha_do_agrupador(a) for a in ags})
        indices = indices_sazonais(_hist_linha(hist_ag, hist_meses), hist_meses)
        ath_rows = db.query(DIARIO_ASOF_SQL,
                            {"de": f"{meses_fechados_prev(prim, 3)[0]}-01",
                             "ate": de_m})
        # atingimento medio 3m: agregado unico (meta e realizado somados)
        soma_meta = sum(r["meta"] for r in ath_rows)
        ating_hist = (sum(r["realizado"] for r in ath_rows) / soma_meta) \
            if soma_meta else None

        for dia in dias:
            asof = prim + timedelta(days=dia - 1)
            razao_asof = _razao_asof(de_m, ate_m, asof.isoformat())
            razao_ag_mes = {ag: serie.get(mes, 0.0)
                            for ag, serie in razao_asof.items()}
            real_acum = sum(r["realizado"] for r in diario_rows if r["dia"] <= dia)
            meta_acum = sum(r["meta"] for r in diario_rows if r["dia"] <= dia)
            dias_meta = sum(1 for r in diario_rows if r["meta"] and r["dia"] <= dia)
            vfc = db.query(VFC_MTD_SQL, {"de": de_m, "ate": asof.isoformat()})
            ctx = {"mes": mes, "modo": "corrente", "dia_rel": dia,
                   "hoje": asof.isoformat(), "dias_meta_decorridos": dias_meta,
                   "razao_ag_mes": razao_ag_mes, "hist_ag": hist_ag,
                   "meses_hist": hist_meses,
                   "diario": {"real_acum": real_acum, "meta_acum": meta_acum,
                              "meta_mes": meta_mes},
                   "ating_hist": ating_hist, "curva": curva,
                   "vfc": dict(vfc[0]) if vfc else {"frete_compra": 0.0,
                                                    "receita_viagens": 0.0,
                                                    "viagens": 0},
                   "ctaplus": None, "cap": None, "breakeven": None,
                   "orcado_linha": {}, "meses_circulares": [], "calibracao": {},
                   "ajustes": {}, "indices": indices, "snapshots": [],
                   "fontes": []}
            resp = montar_resposta(ctx)
            for ln in resp["linhas"]:
                rot = ln["linha"]
                final = final_linha.get(rot)
                if rot == "NAO ALOCADO / CLASSIFICAR" or ln["formula"] or not final:
                    continue
                err = (ln["previsto"] - final) / abs(final)
                erros.setdefault(rot, {}).setdefault(dia, []).append(err)

    calib = {rot: {str(d): {"p20": round(_percentil(v, 0.20), 4),
                            "p80": round(_percentil(v, 0.80), 4)}
                   for d, v in por_dia.items()}
             for rot, por_dia in erros.items()}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "previsao_calibracao.json").write_text(
        json.dumps(calib, indent=1, ensure_ascii=True))

    relatorio.append("| Linha | " + " | ".join(f"D{d} p20..p80" for d in dias) + " |")
    relatorio.append("|---|" + "---|" * len(dias))
    for rot, _n, tipo, _s in DRE_MODELO:
        if tipo == "formula" or rot not in calib:
            continue
        cel = [f"{calib[rot].get(str(d), {}).get('p20', 0):+.1%} .. "
               f"{calib[rot].get(str(d), {}).get('p80', 0):+.1%}" for d in dias]
        relatorio.append(f"| {rot} | " + " | ".join(cel) + " |")
    (ROOT / "docs" / "previsao-backtest.md").write_text("\n".join(relatorio))
    print("ok: data/previsao_calibracao.json + docs/previsao-backtest.md")


if __name__ == "__main__":
    main()
