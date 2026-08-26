# api/previsao/servico.py
"""Orquestração da previsão de fechamento.

I/O aqui; cálculo no motor (puro). Fetch em grupos paralelos com conexão
própria (padrão get_visao_geral — o túnel tem RTT alto). montar_resposta é
pura e recebe o contexto pronto: é ela que o backtest reexecuta "as-of".
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from api import db
from api.orcamento import armazenamento as orc_arm
from api.orcamento import rollup
from api.orcamento.derivacao import indices_sazonais
from api.orcamento.servico import meses_circulares
from api.orcamento.sql import AGRUP_CONTA_SQL
from api.previsao import armazenamento as arm
from api.previsao import motor
from api.previsao.completude import completude_em, dispersao_em, montar_curva
from api.previsao.sql import (ATING_HIST_SQL, CAP_MES_SQL, COMPLETUDE_SQL,
                              CTAPLUS_MTD_SQL, VFC_MTD_SQL, meses_fechados_prev)
from api.previsao.motor import _brl
from api.queries import (BREAKEVEN_SQL, DRE_AG_SQL, DRE_AJUSTADAS_SQL,
                         DRE_MODELO, VG_DIARIO_SQL, _comp_bounds,
                         _ponto_equilibrio, ler_ajustes)

log = logging.getLogger("cortex.previsao")
ROOT = Path(__file__).resolve().parent.parent.parent
CALIB_PATH = ROOT / "data" / "previsao_calibracao.json"

# linhas cujo previsto NAO vem do loop de agrupadores (tratadas no nivel da linha)
_LINHAS_NIVEL_LINHA = {"RECEITA BRUTA", "IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS",
                       "IMPOSTOS MUNICIPAIS", "CONTRIBUICAO PREVIDENCIARIA",
                       "ANULACOES", "DESCONTOS"}
_LINHAS_PCT = ("IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS", "IMPOSTOS MUNICIPAIS",
               "CONTRIBUICAO PREVIDENCIARIA")
DIVERGENCIA_COMB = 0.10


def resolver_modo(mes: str, hoje: date) -> tuple[str, int]:
    """("corrente", dias desde o dia 1 do mes corrente, incluso hoje) |
    ("fechando", dias desde o dia 1 do mes M-1 ate hoje) | ("fechado", 0).

    NOTA (decisao do controller, task 6): corrente usa hoje.day (nao
    (hoje - hoje.replace(day=1)).days, que daria 1 a menos) para casar com o
    teste fixado: resolver_modo("2026-08", 2026-08-02) == ("corrente", 2).
    """
    corrente = f"{hoje.year}-{hoje.month:02d}"
    if mes == corrente:
        return "corrente", hoje.day
    prim_corrente = hoje.replace(day=1)
    m1 = (prim_corrente - timedelta(days=1)).replace(day=1)
    if mes == f"{m1.year}-{m1.month:02d}":
        dia_rel = (hoje - m1).days
        if dia_rel <= 45:
            return "fechando", dia_rel
    return "fechado", 0


def _hist_linha(hist_ag: dict, meses: list[str]) -> dict[str, dict[str, float]]:
    por: dict[str, dict[str, float]] = {}
    for ag, serie in hist_ag.items():
        rot = motor.linha_do_agrupador(ag)
        if not rot:
            continue
        alvo = por.setdefault(rot, {})
        for m, v in serie.items():
            alvo[m] = alvo.get(m, 0.0) + v
    return por


def _ultimos(serie: dict[str, float], meses: list[str], n: int) -> list[float]:
    return [serie.get(m, 0.0) for m in meses[-n:]]


# premissa/aviso da degradacao da curva (spec 11): completude_em devolve o
# NEUTRO 1.0 quando a curva esta ausente, o que transformaria "razao parcial"
# em "previsto" e subestimaria grosseiramente toda linha razao_completude no
# comeco do mes. Sem curva NAO se divide: cai para o nivel historico.
PREM_SEM_CURVA = "curva de completude indisponivel - usando nivel"
PREM_PISO_RAZAO = ("piso do razao: o ja escriturado no mes supera o nivel "
                   "historico - previsto = razao")
AVISO_SEM_CURVA = (
    "Curva de completude indisponivel: as linhas que dependem dela NAO foram "
    "divididas pela completude esperada - cairam para o nivel historico "
    "(mediana dos 3 ultimos meses fechados), com piso no que o razao ja "
    "mostra no mes (nunca menos, em modulo, que o ja escriturado). Sem a "
    "curva nao ha' como saber quanto do mes ainda falta escriturar: nessas "
    "linhas o previsto tende a ficar SUBESTIMADO enquanto o mes corre, e no "
    "fim so' acompanha o razao. Trate os numeros dessas linhas como piso, "
    "nao como previsao fechada.")

# nomes canonicos das fontes (chips da tela + gate do snapshot + alertas)
FONTE_RAZAO = "razao contabil (AVA)"
FONTE_CURVA = "curva de completude"
FONTE_DIARIO = "meta diaria / faturamento fiscal"
FONTE_OPS = "viagens / abastecimentos / contas a pagar"


def _curva_utilizavel(curva: dict | None) -> bool:
    """A curva so' serve se tiver ALGUMA serie de fracoes (por agrupador ou a
    global). Com {} (fonte degradada) completude_em cai no neutro 1.0 e
    dispersao_em no neutro 0.0 - os dois "tudo certo" mais perigosos possiveis
    aqui, porque produzem um numero errado em silencio em vez de um erro."""
    c = curva or {}
    return bool(c.get("ag") or c.get("global"))


def _diario_utilizavel(diario: dict | None) -> bool:
    """Simetrico do _curva_utilizavel para o DRIVER FISCAL.

    VG_DIARIO_SQL pode voltar sem linha nenhuma (fonte fora) ou com linhas
    cuja meta e' toda zero (meta do mes nao cadastrada - a origem mais
    provavel). Nos dois casos o dict montado por get_previsao continua TRUTHY
    e prever_receita recebe meta_mes = 0: `meta_rest = max(0, 0 - 0) = 0` e o
    previsto vira o proprio MTD (ou R$ 0,00 no dia 1o), carimbado
    "driver_fiscal", com o chip da fonte VERDE e nenhum aviso - a mesma
    catastrofe silenciosa que a onda anterior fechou, pela porta da frente.

    Sem meta do mes nao existe "restante do mes" para aplicar ritmo nenhum: a
    fonte esta' fora, e quem resolve e' o fallback por nivel. So' olha chaves
    que TODO ctx tem (backtest inclusive) - nada de contagem de linhas."""
    d = diario or {}
    return float(d.get("meta_mes") or 0.0) > 0.0


def _marcar_fonte_fora(fontes: list[dict], nome: str) -> list[dict]:
    """Copia a lista marcando `nome` como ok=False (ou acrescentando-a).
    Copia porque montar_resposta e' PURA: mutar ctx["fontes"] mudaria a lista
    do chamador (e o backtest reexecuta a mesma ctx varias vezes)."""
    out = [dict(f) for f in fontes]
    for f in out:
        if f.get("nome") == nome:
            f["ok"] = False
            return out
    out.append({"nome": nome, "ok": False, "driver": True})
    return out


def montar_resposta(ctx: dict) -> dict:
    """ctx (tudo plain data — ver get_previsao para o preenchimento):
    mes, modo ('corrente'|'fechando'|'fechado'), dia_rel, hoje (iso),
    dias_meta_decorridos, razao_ag_mes {ag: valor}, hist_ag {ag: {mes: valor}}
    (meses FECHADOS, ajustes contábeis já migrados), meses_hist [YYYY-MM asc],
    diario {real_acum, meta_acum, meta_mes} | None, ating_hist float|None,
    curva (montar_curva), vfc {frete_compra, receita_viagens, viagens},
    ctaplus {custo, abastecimentos}, cap {valor, titulos}, breakeven dict|None,
    orcado_linha {rotulo: valor}, meses_circulares [int], calibracao {linha:
    {dia: {p20,p80}}}, ajustes (armazenamento.ler_ajustes_prev), indices =
    (indices_por_linha, linhas_flat), snapshots [], fontes [{nome, ok}],
    avisos_previos [str] (avisos ja escritos pela camada de I/O).

    DEGRADACAO POR FONTE (spec 11): curva {} e diario None NAO sao "neutro",
    sao "fonte fora" — em vez de dividir por uma completude 1.0 fantasma ou
    prever receita 0,00, essas linhas trocam de METODO (nivel historico) e
    dizem isso na premissa e no aviso. A degradacao tambem pode ser detectada
    AQUI (driver fiscal presente mas sem meta): neste caso montar_resposta
    devolve fontes[] com a fonte marcada ok=False - sem mutar a lista do ctx."""
    modo = ctx["modo"]
    meses = ctx["meses_hist"]
    hist_ag = ctx["hist_ag"]
    hist_linha = _hist_linha(hist_ag, meses)
    razao_ag = ctx["razao_ag_mes"]
    indices_por_linha, linhas_flat = ctx.get("indices") or ({}, [])
    avisos: list[str] = list(ctx.get("avisos_previos") or [])
    fontes: list[dict] = [dict(f) for f in (ctx.get("fontes") or [])]

    # driver fiscal presente PORE'M inutilizavel (meta do mes nao cadastrada):
    # a camada de I/O nao tem como saber - a query respondeu. Aqui vira fonte
    # fora, com o mesmo tratamento do driver ausente logo abaixo.
    diario = ctx.get("diario")
    if diario and not _diario_utilizavel(diario):
        avisos.append(
            "Meta diaria do mes sem valor cadastrado (meta do mes "
            f"{_brl(float(diario.get('meta_mes') or 0.0))}): sem meta nao ha' "
            "\"restante do mes\" para projetar e o driver fiscal foi tratado "
            "como fonte FORA - o realizado fiscal do mes "
            f"({_brl(float(diario.get('real_acum') or 0.0))}) sozinho nao e' "
            "previsao. Cadastrar a meta em metafaturamento restabelece o metodo.")
        fontes = _marcar_fonte_fora(fontes, FONTE_DIARIO)
        diario = None

    # realizado contábil por linha direta (sempre exposto)
    realizado_direta: dict[str, float] = {}
    nao_alocado_real = 0.0
    for ag, v in razao_ag.items():
        rot = motor.linha_do_agrupador(ag)
        if rot:
            realizado_direta[rot] = realizado_direta.get(rot, 0.0) + v
        else:
            nao_alocado_real += v

    previsto_direta: dict[str, dict] = {}
    curva_ok = _curva_utilizavel(ctx.get("curva"))
    if not curva_ok and modo in ("corrente", "fechando"):
        avisos.append(AVISO_SEM_CURVA)

    def _fallback_nivel(ag: str) -> dict:
        return motor.prever_nivel(_ultimos(hist_ag.get(ag, {}), meses, 3), f"{ag} 3m")

    def _nivel_sem_curva(ag: str) -> dict:
        """Nivel historico com PISO no razao ja escriturado (mesma regra que
        motor.estimar_m1 aplica na rota `lote`): nunca prever MENOS, em
        modulo, do que o razao ja mostra para o agrupador. Sem o piso, uma
        linha de custo com o razao ja adiantado no mes recebia um nivel MENOR
        que o realizado: o "projetado" (previsto - realizado) invertia de
        sinal e o RESULTADO aparecia OTIMISTA - o oposto do que o aviso da
        tela prometia."""
        r = _fallback_nivel(ag)
        v = razao_ag.get(ag, 0.0)
        if abs(v) >= abs(r["previsto"]) and v:
            return {"previsto": v, "estrategia": r["estrategia"],
                    "premissas": r["premissas"] + [
                        PREM_SEM_CURVA,
                        f"{PREM_PISO_RAZAO} ({_brl(v)} contra nivel "
                        f"{_brl(r['previsto'])})"]}
        return {**r, "premissas": r["premissas"] + [PREM_SEM_CURVA]}

    if modo == "fechado":
        for rot, v in realizado_direta.items():
            previsto_direta[rot] = {"previsto": v, "estrategia": "fechado",
                                    "premissas": ["mes fechado - razao"]}
        avisos.append("Mes fechado: previsto = razao. Consulte a DRE Gerencial.")
    elif modo == "fechando":
        # sem curva nao ha' como decidir consolidado/lote/razao_completude: o
        # M-1 inteiro cai no nivel historico (mesma regra do corrente).
        est = (motor.estimar_m1(razao_ag, ctx["curva"], ctx["dia_rel"],
                                {ag: _fallback_nivel(ag) for ag in razao_ag})
               if curva_ok else {ag: _nivel_sem_curva(ag) for ag in razao_ag})
        for ag, r in est.items():
            rot = motor.linha_do_agrupador(ag)
            if not rot:
                continue
            atual = previsto_direta.setdefault(
                rot, {"previsto": 0.0, "estrategia": r["estrategia"], "premissas": []})
            atual["previsto"] += r["previsto"]
            atual["premissas"] = (atual["premissas"] + r["premissas"])[:6]
            if r["estrategia"] != "consolidado":
                atual["estrategia"] = r["estrategia"]
    else:  # corrente
        d = diario
        if d:
            rec = motor.prever_receita(d["real_acum"], d["meta_acum"], d["meta_mes"],
                                       ctx.get("ating_hist"),
                                       ctx["dias_meta_decorridos"])
        else:
            # driver fiscal fora (spec 11). Zerar o diario faria prever_receita
            # devolver 0,00 de RECEITA BRUTA e a cascata inteira (impostos,
            # frete de compra, % da receita) desabaria junto: numero errado em
            # silencio. Sem o driver, o nivel historico e' o melhor conhecido.
            rec = motor.prever_nivel(
                _ultimos(hist_linha.get("RECEITA BRUTA", {}), meses, 3),
                "receita 3m (driver fiscal indisponivel)")
            # receita MTD pelo RAZAO (unica medida de receita decorrida que
            # sobra) para o bloco do frete de compra nao projetar o mes inteiro
            # POR CIMA do custo ja conhecido.
            d = {"real_acum": realizado_direta.get("RECEITA BRUTA", 0.0),
                 "meta_acum": 0.0, "meta_mes": 0.0}
            avisos.append(
                "Meta diaria / faturamento fiscal indisponivel: a RECEITA BRUTA "
                f"prevista ({_brl(rec['previsto'])}) vem do nivel historico "
                "(mediana dos 3 ultimos meses fechados), nao do driver fiscal - "
                "e o atingimento do mes fica sem base para ser calculado.")
        previsto_direta["RECEITA BRUTA"] = rec
        rb_hist = hist_linha.get("RECEITA BRUTA", {})
        rb6 = _ultimos(rb_hist, meses, 6)
        media_rb6 = (sum(rb6) / len(rb6)) if rb6 else 0.0
        for rot in _LINHAS_PCT:
            serie6 = _ultimos(hist_linha.get(rot, {}), meses, 6)
            pct = (sum(serie6) / len(serie6)) / media_rb6 if media_rb6 else 0.0
            previsto_direta[rot] = motor.prever_pct_receita(
                rec["previsto"], pct, f"media 6m ({rot.lower()})")
        for rot in ("ANULACOES", "DESCONTOS"):
            idx = indices_por_linha.get(rot) or {m: 1.0 for m in range(1, 13)}
            vals6 = _ultimos(hist_linha.get(rot, {}), meses, 6)
            i6 = [idx[int(m[5:7])] for m in meses[-6:]]
            previsto_direta[rot] = motor.prever_sazonal(
                vals6, i6, idx[int(ctx["mes"][5:7])])

        # frete de compra: agregados + terceiros JUNTOS (proxy sem join de
        # veiculo), depois split pela participacao historica das duas linhas
        ags_frete = [ag for ag in set(razao_ag) | set(hist_ag)
                     if motor.estrategia_do_agrupador(ag) == "frete_compra"]
        if ags_frete:
            razao_mtd_frete = sum(razao_ag.get(ag, 0.0) for ag in ags_frete)
            hist_frete6 = sum(sum(_ultimos(hist_ag.get(ag, {}), meses, 6))
                              for ag in ags_frete)
            razao_cr = (hist_frete6 / sum(rb6)) if sum(rb6) else 0.0
            # leitura defensiva: sum() sobre zero linhas no Postgres devolve
            # NULL (o coalesce externo em VFC_MTD_SQL cobre o banco real, mas
            # ctx e' plain data e pode chegar com None de outras origens - ex.:
            # backtest as-of, teste, cache antigo).
            vfc_frete_compra = float(ctx["vfc"].get("frete_compra") or 0.0)
            # DUPLA CONTAGEM: o custo conhecido sai das VIAGENS (completo para
            # os dias decorridos) e a receita ja coberta por ele tem de sair
            # das MESMAS viagens. d["real_acum"] e' o fiscal (ou, com o driver
            # fora, o razao) - reguas que maturam em outro ritmo: usa-la deixa
            # a "receita restante" inflada e a projecao cobre de novo o trecho
            # que o custo conhecido ja cobriu. Cai para d["real_acum"] so'
            # quando as viagens nao existem (grupo operacional degradado, 1o
            # dia do mes). ATENCAO: nesse fallback o descasamento volta
            # ESPELHADO - sem viagens o custo conhecido vira o razao (regua
            # lenta) contra uma receita ja coberta pelo fiscal (regua rapida),
            # subestimando o custo. E' aceito porque o grupo ops fora e' fonte
            # driver: a tela avisa, o snapshot nao grava e o alerta e' rebaixado.
            receita_viagens = float(ctx["vfc"].get("receita_viagens") or 0.0)
            if receita_viagens > 0.0:
                receita_ja_coberta, fonte_rec = receita_viagens, "viagens do mes"
            else:
                receita_ja_coberta = d["real_acum"]
                fonte_rec = "faturamento MTD (viagens indisponiveis)"
            comb = motor.prever_frete_compra(
                razao_mtd_frete, vfc_frete_compra, rec["previsto"],
                receita_ja_coberta, razao_cr, fonte_rec)
            total_h = {ag: abs(sum(_ultimos(hist_ag.get(ag, {}), meses, 6)))
                       for ag in ags_frete}
            soma_h = sum(total_h.values()) or 1.0
            for ag in ags_frete:
                parte = comb["previsto"] * (total_h[ag] / soma_h)
                rot = motor.linha_do_agrupador(ag) or "CUSTO VARIAVEL"
                atual = previsto_direta.setdefault(
                    rot, {"previsto": 0.0, "estrategia": "frete_compra",
                          "premissas": comb["premissas"]})
                atual["previsto"] += parte

        for ag in sorted(set(razao_ag) | set(hist_ag)):
            estrat = motor.estrategia_do_agrupador(ag)
            rot = motor.linha_do_agrupador(ag)
            if estrat == "frete_compra" or (rot in _LINHAS_NIVEL_LINHA):
                continue  # ja tratados no nivel da linha / bloco do frete
            v_mtd = razao_ag.get(ag, 0.0)
            if estrat == "nivel" or estrat == "runrate":
                r = _fallback_nivel(ag)
            elif estrat == "sazonal":
                idx = (indices_por_linha.get(rot) if rot else None) \
                    or {m: 1.0 for m in range(1, 13)}
                vals6 = _ultimos(hist_ag.get(ag, {}), meses, 6)
                i6 = [idx[int(m[5:7])] for m in meses[-6:]]
                r = motor.prever_sazonal(vals6, i6, idx[int(ctx["mes"][5:7])])
            elif not curva_ok:  # razao_completude sem curva: NAO divide
                r = _nivel_sem_curva(ag)
            else:  # razao_completude
                frac = completude_em(ctx["curva"], ag, rot, ctx["dia_rel"])
                disp = dispersao_em(ctx["curva"], ag, rot, ctx["dia_rel"])
                r = motor.prever_razao_completude(v_mtd, frac, _fallback_nivel(ag), disp)
            alvo = rot or "NAO ALOCADO / CLASSIFICAR"
            atual = previsto_direta.setdefault(
                alvo, {"previsto": 0.0, "estrategia": r["estrategia"],
                       "premissas": []})
            atual["previsto"] += r["previsto"]
            atual["premissas"] = (atual["premissas"] + r["premissas"])[:6]

    # ---- ajustes manuais + cascata + bandas + comparaveis (todos os modos)
    nao_alocado = previsto_direta.pop("NAO ALOCADO / CLASSIFICAR",
                                      {"previsto": nao_alocado_real,
                                       "estrategia": "runrate", "premissas": []})
    ajustes = ctx.get("ajustes") or {}
    base_direta: dict[str, float] = {}
    shift_direta: dict[str, float] = {}
    for rotulo, _n, tipo, _s in DRE_MODELO:
        if tipo == "formula":
            continue
        calc = previsto_direta.get(rotulo, {"previsto": 0.0})["previsto"]
        efetivo, shift = motor.aplicar_ajuste(calc, ajustes.get(rotulo))
        base_direta[rotulo] = efetivo
        shift_direta[rotulo] = shift

    frac_rest = 0.0
    if modo == "corrente" and diario:
        mm = diario["meta_mes"]
        frac_rest = max(0.0, 1.0 - (diario["meta_acum"] / mm)) if mm else 0.5
    elif modo == "corrente":
        # sem meta diaria nao da' para medir quanto do mes falta pela meta; o
        # calendario e' a aproximacao honesta. Deixar 0.0 aqui colapsaria a
        # banda de banda_fallback justo no cenario MAIS incerto (driver fora).
        frac_rest = max(0.0, min(1.0, 1.0 - ctx.get("dia_rel", 0) / 30.0))
    elif modo == "fechando":
        frac_rest = 0.3

    pess_direta, otim_direta = {}, {}
    calib = ctx.get("calibracao") or {}
    # dias_meta_decorridos so' e' preenchido (>0) no modo corrente; nos demais
    # modos a chave sempre existe valendo 0 (get_previsao so' calcula fora do
    # corrente), entao o default do .get() nunca dispara - "or" (nao o default
    # posicional do .get) e' o que de fato cai para dia_rel quando o valor e' 0.
    dia_util = ctx.get("dias_meta_decorridos") or ctx.get("dia_rel", 0)
    for rotulo, base in base_direta.items():
        b = motor.banda_calibrada(base - shift_direta[rotulo],
                                  calib.get(rotulo), dia_util)
        if b is None:
            hist6 = _ultimos(hist_linha.get(rotulo, {}), meses, 6)
            b = motor.banda_fallback(base - shift_direta[rotulo], hist6, frac_rest)
        pess_direta[rotulo] = b[0] + shift_direta[rotulo]
        otim_direta[rotulo] = b[1] + shift_direta[rotulo]

    casc_base = motor.montar_cascata(base_direta)
    casc_pess = motor.montar_cascata(pess_direta)
    casc_otim = motor.montar_cascata(otim_direta)
    casc_real = motor.montar_cascata(realizado_direta)
    orcado = ctx.get("orcado_linha") or {}
    casc_orc = motor.montar_cascata({r: orcado.get(r, 0.0) for r in orcado}) \
        if orcado else {}

    linhas = []
    for rotulo, nivel, tipo, _s in DRE_MODELO:
        prev = casc_base.get(rotulo, 0.0)
        item = {
            "linha": rotulo, "nivel": nivel, "formula": tipo == "formula",
            "realizado": casc_real.get(rotulo, 0.0),
            "previsto": prev,
            "projetado": prev - casc_real.get(rotulo, 0.0),
            "previsto_pess": min(casc_pess.get(rotulo, prev), casc_otim.get(rotulo, prev)),
            "previsto_otim": max(casc_pess.get(rotulo, prev), casc_otim.get(rotulo, prev)),
            "orcado": casc_orc.get(rotulo) if casc_orc else None,
            "estrategia": ("formula" if tipo == "formula" else
                           previsto_direta.get(rotulo, {}).get("estrategia", "runrate")),
            "premissas": previsto_direta.get(rotulo, {}).get("premissas", []),
            "ajuste": ajustes.get(rotulo),
        }
        if item["orcado"] is not None:
            item["desvio"] = item["previsto"] - item["orcado"]
        linhas.append(item)
    linhas.append({
        "linha": "NAO ALOCADO / CLASSIFICAR", "nivel": 0, "formula": False,
        "realizado": nao_alocado_real, "previsto": nao_alocado["previsto"],
        "projetado": nao_alocado["previsto"] - nao_alocado_real,
        "previsto_pess": nao_alocado["previsto"], "previsto_otim": nao_alocado["previsto"],
        "orcado": None, "estrategia": nao_alocado["estrategia"],
        "premissas": nao_alocado["premissas"], "ajuste": None,
    })

    # avisos
    if modo == "corrente" and ctx.get("ctaplus"):
        comb_prev = None
        for ag in razao_ag:
            if motor.norm(ag).startswith("CV - COMBUSTIVEL"):
                if not curva_ok:  # mesma rota do loop principal: nao divide
                    comb_prev = _nivel_sem_curva(ag)["previsto"]
                    continue
                frac = completude_em(ctx["curva"], ag, "CUSTO VARIAVEL", ctx["dia_rel"])
                disp = dispersao_em(ctx["curva"], ag, "CUSTO VARIAVEL", ctx["dia_rel"])
                comb_prev = motor.prever_razao_completude(
                    razao_ag[ag], frac, _fallback_nivel(ag), disp)["previsto"]
        custo_ctaplus = -abs(ctx["ctaplus"].get("custo") or 0.0)
        if comb_prev and custo_ctaplus and razao_ag:
            razao_comb_mtd = sum(v for a, v in razao_ag.items()
                                 if motor.norm(a).startswith("CV - COMBUSTIVEL"))
            if razao_comb_mtd and abs(custo_ctaplus - razao_comb_mtd) \
                    > DIVERGENCIA_COMB * abs(razao_comb_mtd):
                avisos.append(
                    f"Combustivel diverge: razao MTD {_brl(abs(razao_comb_mtd))} x "
                    f"abastecimentos {_brl(abs(custo_ctaplus))} (>10%). Conferir fontes.")
    if ctx.get("meses_circulares") and int(ctx["mes"][5:7]) in ctx["meses_circulares"]:
        avisos.append("Mes dentro da base de derivacao do orcamento vigente - "
                      "o desvio contra o orcado mede so o fator (comparacao circular).")
    for rot, aj in ajustes.items():
        if modo == "fechado":
            avisos.append(f"Ajuste manual vencido em {rot} (mes ja fechado).")

    # ESCRITURACAO: quanto do mes ja esta no razao, no total e POR BLOCO.
    #
    # Antes so era calculado no modo "fechando". Mas e no mes CORRENTE que a
    # pergunta importa: o intervalo do resultado nao encolhe ao longo do mes, e
    # a razao nao e o modelo — e que o custo entra no razao com semanas de
    # atraso. Em 25/08/2026, com 81% do mes corrido, a receita estava 81,1%
    # escriturada e o custo fixo 44,5%. Sem esse numero na tela, "resultado
    # previsto" parece ter a mesma confianca no dia 5 e no dia 25.
    def _consolidado(rotulos: tuple[str, ...] | None) -> float | None:
        alvo = [ln for ln in linhas if not ln["formula"]
                and (rotulos is None or motor.norm(ln["linha"]).startswith(rotulos))]
        prev = sum(abs(ln["previsto"]) for ln in alvo)
        real = sum(abs(ln["realizado"]) for ln in alvo)
        return min(1.0, real / prev) if prev else None

    consolidacao = _consolidado(None)
    consolidacao_blocos = {
        "receita": _consolidado(("RECEITA",)),
        "custo_variavel": _consolidado(("CV -", "CUSTO VARIAVEL")),
        "custo_fixo": _consolidado(("CF -", "CUSTO FIXO")),
    }

    # O CUSTO ATRASADO E A PRINCIPAL FONTE DE ERRO DA PREVISAO, e ela e
    # invisivel para quem olha so o resultado. Vinte pontos abaixo da receita
    # ja bastam para o resultado do mes virar de sinal quando o razao alcancar.
    _cr = consolidacao_blocos.get("receita")
    _cf = consolidacao_blocos.get("custo_fixo")
    _cv = consolidacao_blocos.get("custo_variavel")
    if _cr and _cf and _cr - _cf > 0.20:
        avisos.append(
            f"Custo fixo escriturado em {_cf:.0%} contra {_cr:.0%} da receita: "
            "o resultado previsto tende a PIORAR quando o razao alcancar. Em "
            "julho o mes aparecia com +R$ 1,7 mi no dia 4 e fechou em "
            "-R$ 945 mil pelo mesmo motivo.")
    elif _cr and _cv and _cr - _cv > 0.20:
        avisos.append(
            f"Custo variavel escriturado em {_cv:.0%} contra {_cr:.0%} da "
            "receita: o resultado previsto tende a piorar quando o razao "
            "alcancar.")


    kpis = {
        "resultado_previsto": casc_base.get("RESULTADO DO EXERCICIO", 0.0),
        "resultado_pess": min(casc_pess.get("RESULTADO DO EXERCICIO", 0.0),
                              casc_otim.get("RESULTADO DO EXERCICIO", 0.0)),
        "resultado_otim": max(casc_pess.get("RESULTADO DO EXERCICIO", 0.0),
                              casc_otim.get("RESULTADO DO EXERCICIO", 0.0)),
        "resultado_orcado": casc_orc.get("RESULTADO DO EXERCICIO") if casc_orc else None,
        "receita_prevista": casc_base.get("RECEITA BRUTA", 0.0),
        # `diario` (local) e nao ctx["diario"]: com a meta zerada a fonte esta'
        # FORA, entao atingimento/meta do mes nao existem - mostrar "meta do
        # mes R$ 0" seria o mesmo zero-por-lacuna que o aviso acabou de negar.
        "atingimento_mtd": ((diario["real_acum"] / diario["meta_acum"])
                            if diario and diario["meta_acum"] else None),
        "meta_mes": diario["meta_mes"] if diario else None,
        "breakeven": ctx.get("breakeven"),
        "cap_mes": ctx.get("cap"),
        "consolidacao_pct": consolidacao,
        "consolidacao_blocos": consolidacao_blocos,
        "dados_ate": ctx["hoje"],
    }
    return {"mes": ctx["mes"], "modo": modo, "kpis": kpis, "linhas": linhas,
            "avisos": avisos, "linhas_flat": (ctx.get("indices") or ({}, []))[1],
            "serie_snapshots": ctx.get("snapshots") or [],
            "fontes": fontes,
            "fonte": ("ERP AVA (razao + documentos fiscais + viagens + ctaplus) "
                      "+ orcamento local · previsao, nao numero fechado")}


def snapshot_se_integro(resp: dict, mes: str, data_foto: str) -> bool:
    """Grava a foto do dia SO' se nenhum driver estiver degradado. Devolve se
    gravou (o teste unitario troca arm.gravar_snapshot e olha o retorno).

    `gravar_snapshot` e' INSERT OR REPLACE por (data, mes, linha): uma rodada
    degradada - um piscar do tunel as 3h, durante o digest - SOBRESCREVE para
    sempre o ponto bom daquele dia, e a "Evolucao da previsao" desenha
    previsto_base sem nenhuma marca de degradacao. Foto ruim nao entra no
    album: perder o ponto do dia se resolve na proxima consulta; um ponto
    errado no historico, nao. O orcamento (driver=False) nao conta - ele nao
    entra em previsto nenhum."""
    fora = motor.fontes_fora(resp.get("fontes"), apenas_drivers=True)
    if fora:
        log.warning("previsao: snapshot de %s (%s) NAO gravado - fonte(s) "
                    "degradada(s): %s. O ponto do dia fica com o valor bom "
                    "anterior, se houver.", mes, data_foto, ", ".join(fora))
        return False
    try:  # snapshot diario best-effort (idempotente por dia)
        arm.gravar_snapshot(arm.DB_PATH, data_foto, mes, [
            {"linha": ln["linha"], "previsto_base": ln["previsto"],
             "previsto_otim": ln["previsto_otim"], "previsto_pess": ln["previsto_pess"],
             "realizado_contabil": ln["realizado"], "estrategia": ln["estrategia"]}
            for ln in resp["linhas"]])
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao: snapshot falhou: %s", exc)
        return False


def _fetch_grupo(sqls: list[tuple[str, dict | None]]) -> list[list[dict]]:
    out = []
    with db.get_conn() as conn, conn.cursor() as cur:
        for sql, params in sqls:
            cur.execute(sql, params)
            out.append(cur.fetchall())
    return out


def _curva_do_banco(hoje: date, mapa_ag_linha_fn) -> dict:
    meses6 = meses_fechados_prev(hoje, 6)
    de = f"{meses6[0]}-01"
    _, ate = _comp_bounds(meses6[-1], meses6[-1])
    rows = db.query(COMPLETUDE_SQL, {"de": de, "ate": ate})
    ags = {r["agrupador"] for r in rows}
    return montar_curva([dict(r) for r in rows],
                        {ag: mapa_ag_linha_fn(ag) for ag in ags})


def get_previsao(mes: str | None = None, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    mes = mes or f"{hoje.year}-{hoje.month:02d}"
    modo, dia_rel = resolver_modo(mes, hoje)
    de_mes, ate_mes = _comp_bounds(mes, mes)
    meses24 = meses_fechados_prev(hoje, 24)
    de24 = f"{meses24[0]}-01"
    _, ate24 = _comp_bounds(meses24[-1], meses24[-1])
    ajustes_ctb = ler_ajustes()
    fontes: list[dict] = []
    avisos_previos: list[str] = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_razao = ex.submit(_fetch_grupo, [
            (DRE_AG_SQL, {"de": de24, "ate": ate24}),
            (DRE_AG_SQL, {"de": de_mes, "ate": ate_mes}),
        ] + ([(DRE_AJUSTADAS_SQL, {"de": de24, "ate": ate24,
                                   "chaves": list(ajustes_ctb.keys())}),
              (DRE_AJUSTADAS_SQL, {"de": de_mes, "ate": ate_mes,
                                   "chaves": list(ajustes_ctb.keys())})]
             if ajustes_ctb else []))
        f_curva = ex.submit(_curva_do_banco, hoje, motor.linha_do_agrupador)
        f_diario = ex.submit(_fetch_grupo, [
            (VG_DIARIO_SQL, None),
            (ATING_HIST_SQL, {"de": f"{meses_fechados_prev(hoje, 3)[0]}-01",
                              "ate": f"{hoje.year}-{hoje.month:02d}-01"}),
            # BREAKEVEN_SQL: mesmos nomes de parametro que get_visao_geral usa
            # ao executa-la (api/queries.py ~1909) — a query e' generica (%(de)s
            # /%(ate)s via _DRE_BASE), so os VALORES (janela de 12m) mudam aqui.
            (BREAKEVEN_SQL, {"de": f"{meses_fechados_prev(hoje, 12)[0]}-01",
                             "ate": f"{hoje.year}-{hoje.month:02d}-01"}),
        ])
        f_ops = ex.submit(_fetch_grupo, [
            (VFC_MTD_SQL, {"de": de_mes, "ate": ate_mes}),
            (CTAPLUS_MTD_SQL, {"de": de_mes, "ate": ate_mes}),
            (CAP_MES_SQL, {"de": de_mes, "ate": ate_mes}),
        ])
        # Degradacao POR FONTE (spec 11): um driver externo fora nao derruba a
        # tela inteira. Excecao deliberada: o RAZAO e' ESSENCIAL - sem ele nao
        # existe previsao nenhuma, entao propaga (o endpoint mapeia
        # OperationalError -> 503 e o resto -> 500).
        razao_out = f_razao.result()
        fontes.append({"nome": FONTE_RAZAO, "ok": True, "driver": True})
        try:
            curva = f_curva.result()
            fontes.append({"nome": FONTE_CURVA, "ok": True, "driver": True})
        except Exception as exc:  # noqa: BLE001
            log.warning("previsao: curva de completude indisponivel: %s", exc)
            curva = {}
            # o aviso da curva sai de montar_resposta (AVISO_SEM_CURVA), que e'
            # quem sabe se o modo do mes chega a usar a curva - repetir aqui
            # duplicaria a linha na tela.
            fontes.append({"nome": FONTE_CURVA, "ok": False, "driver": True})
        try:
            diario_out = f_diario.result()
            # ok=True aqui e' so' "a query respondeu"; se a meta do mes vier
            # zerada quem rebaixa a fonte e' montar_resposta (_diario_utilizavel).
            fontes.append({"nome": FONTE_DIARIO, "ok": True, "driver": True})
        except Exception as exc:  # noqa: BLE001
            log.warning("previsao: driver fiscal indisponivel: %s", exc)
            diario_out = None
            fontes.append({"nome": FONTE_DIARIO, "ok": False, "driver": True})
            # so' o que montar_resposta NAO tem como dizer sozinha (ela ja
            # declara a receita por nivel e o atingimento sem base) - senao a
            # tela repetiria a mesma frase em dois avisos.
            avisos_previos.append(
                "Meta diaria e faturamento fiscal (CT-e/NFS-e/KMM) indisponiveis: "
                "o ponto de equilibrio do mes nao foi calculado nesta consulta.")
        try:
            ops_out = f_ops.result()
            fontes.append({"nome": FONTE_OPS, "ok": True, "driver": True})
        except Exception as exc:  # noqa: BLE001
            log.warning("previsao: drivers operacionais indisponiveis: %s", exc)
            ops_out = None
            fontes.append({"nome": FONTE_OPS, "ok": False, "driver": True})
            avisos_previos.append(
                "Viagens, abastecimentos e contas a pagar indisponiveis: o frete "
                "de compra fica so' com o razao (sem o cruzamento das viagens), e "
                "a conferencia do combustivel contra os abastecimentos e o titulo "
                "a pagar do mes nao aparecem nesta consulta.")

    # Razao 24m + mes alvo, com migracao dos ajustes contabeis: subtrai do
    # agrupador original e soma no novo.
    #
    # Isto NAO e' mais "a mesma logica de get_dre" inteira: a DRE Gerencial le
    # o periodo corrente no nivel da CONTA (DRE_AG_CONTA_SQL) e la o ajuste e'
    # aplicado movendo a conta inteira de agrupador, sem subtrair/somar. O
    # subtrai-soma continua sendo o caminho de get_dre para o comparativo do
    # ANO ANTERIOR, que e' lido por agrupador — que e' exatamente o caso aqui:
    # a previsao le as duas janelas por agrupador (DRE_AG_SQL). O par
    # DRE_AG_SQL + DRE_AJUSTADAS_SQL carrega os MESMOS predicados (planoconta
    # ativoinativo = 1 e elegibilidade), entao o valor debitado da origem e'
    # sempre o que foi somado nela.
    def _aplica_mudancas(val: dict, mudancas: list[dict]) -> None:
        for m in mudancas:
            novo = ajustes_ctb[m["chave"]]["agrupador"]
            if novo == m["agrupador_orig"]:
                continue
            k_orig = (m["mes"], m["agrupador_orig"])
            val[k_orig] = val.get(k_orig, 0.0) - m["valor"]
            val[(m["mes"], novo)] = val.get((m["mes"], novo), 0.0) + m["valor"]

    val24: dict = {}
    for r in razao_out[0]:
        val24[(r["mes"], r["agrupador"])] = \
            val24.get((r["mes"], r["agrupador"]), 0.0) + r["valor"]
    val_mes: dict = {}
    for r in razao_out[1]:
        val_mes[(r["mes"], r["agrupador"])] = \
            val_mes.get((r["mes"], r["agrupador"]), 0.0) + r["valor"]
    if ajustes_ctb and len(razao_out) >= 4:
        _aplica_mudancas(val24, razao_out[2])
        _aplica_mudancas(val_mes, razao_out[3])

    hist_ag: dict[str, dict[str, float]] = {}
    for (m, ag), v in val24.items():
        if m in meses24:
            hist_ag.setdefault(ag, {})[m] = v
    razao_ag_mes = {ag: v for (m, ag), v in val_mes.items() if m == mes}

    # diario do mes corrente (VG_DIARIO_SQL e fixo no mes corrente do banco)
    diario = None
    dias_meta_decorridos = 0
    ating_hist = None
    breakeven = None
    if diario_out is not None and modo == "corrente":
        rows_d = diario_out[0]
        meta_mes = sum(r["meta"] for r in rows_d)
        meta_acum = sum(r["meta"] for r in rows_d if r["dia"] <= hoje.day)
        real_acum = sum(r["realizado"] for r in rows_d)
        dias_meta_decorridos = sum(1 for r in rows_d
                                   if r["meta"] and r["dia"] <= hoje.day)
        diario = {"real_acum": real_acum, "meta_acum": meta_acum,
                  "meta_mes": meta_mes}
    if diario_out is not None:
        ath = [r for r in diario_out[1] if r["meta"]]
        ating_hist = (sum(r["realizado"] / r["meta"] for r in ath) / len(ath)) \
            if ath else None
        try:
            # _ponto_equilibrio espera {grupo: valor} (ver api/queries.py get_visao_geral,
            # que monta be_rows = {r["grupo"]: r["valor"] for r in ...} antes de chamar) —
            # aqui as linhas cruas de BREAKEVEN_SQL precisam do mesmo tratamento.
            be_rows = {r["grupo"]: r["valor"] for r in diario_out[2]}
            breakeven = _ponto_equilibrio(be_rows)
        except Exception:  # noqa: BLE001
            pass

    # indices sazonais por linha (24 meses) — reuso do orcamento
    serie_linha = _hist_linha(hist_ag, meses24)
    indices = indices_sazonais(serie_linha, meses24)

    # orcado do mes por linha (best-effort: nunca derruba a previsao)
    orcado_linha: dict[str, float] = {}
    circulares: list[int] = []
    try:
        orc_arm.init_db(orc_arm.DB_PATH)
        vig = orc_arm.versao_vigente(orc_arm.DB_PATH, ano=int(mes[:4]))
        if vig:
            agrup_rows = db.query(AGRUP_CONTA_SQL)
            agrup_por_conta = {r["conta"]: r["agrupador"] for r in agrup_rows}
            mapa = rollup.mapa_conta_linha(agrup_por_conta, ajustes_ctb)
            mnum = int(mes[5:7])
            for ln in orc_arm.ler_linhas(orc_arm.DB_PATH, vig["id"]):
                if ln["mes"] != mnum:
                    continue
                rot = mapa.get(ln["conta"])
                if rot:
                    orcado_linha[rot] = orcado_linha.get(rot, 0.0) + ln["valor_efetivo"]
            circulares = meses_circulares(int(mes[:4]),
                                          json.loads(vig.get("meses_base") or "[]"))
            fontes.append({"nome": f"orcamento: {vig['rotulo']}", "ok": True,
                           "driver": False})
        else:
            # driver=False: o orcado NAO entra em nenhum previsto (so' na
            # coluna de comparacao). Ano sem versao cadastrada e' estado
            # normal em janeiro - nao pode parar o snapshot diario nem
            # rebaixar o alerta de resultado negativo (ver motor.fontes_fora).
            fontes.append({"nome": "orcamento (sem versao do ano)", "ok": False,
                           "driver": False})
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao: orcado indisponivel: %s", exc)
        fontes.append({"nome": "orcamento", "ok": False, "driver": False})

    calib = {}
    try:
        calib = json.loads(CALIB_PATH.read_text())
    except Exception:  # noqa: BLE001
        pass

    arm.init_db(arm.DB_PATH)
    ctx = {"mes": mes, "modo": modo, "dia_rel": dia_rel, "hoje": hoje.isoformat(),
           "dias_meta_decorridos": dias_meta_decorridos,
           "razao_ag_mes": razao_ag_mes, "hist_ag": hist_ag, "meses_hist": meses24,
           "diario": diario, "ating_hist": ating_hist, "curva": curva,
           # ops_out None = grupo operacional degradado (spec 11): vfc zerado,
           # ctaplus/cap ausentes — os tres ja sao tolerados rio abaixo.
           "vfc": dict(ops_out[0][0]) if (ops_out and ops_out[0])
                  else {"frete_compra": 0.0, "receita_viagens": 0.0, "viagens": 0},
           "ctaplus": dict(ops_out[1][0]) if (ops_out and ops_out[1]) else None,
           "cap": dict(ops_out[2][0]) if (ops_out and ops_out[2]) else None,
           "breakeven": breakeven, "orcado_linha": orcado_linha,
           "avisos_previos": avisos_previos,
           "meses_circulares": circulares, "calibracao": calib,
           "ajustes": arm.ler_ajustes_prev(arm.DB_PATH, mes),
           "indices": indices,
           "snapshots": arm.ler_snapshots(arm.DB_PATH, mes), "fontes": fontes}
    resp = montar_resposta(ctx)
    snapshot_se_integro(resp, mes, hoje.isoformat())
    return resp
