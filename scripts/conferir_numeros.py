"""Reconciliacao cruzada: o MESMO conceito tem de dar o MESMO numero.

Nasceu do defeito do saldo bancario, em que a Visao Geral e o Fluxo
Consolidado mostravam R$ 914 mil de diferenca para a mesma coisa — cada tela
com a sua regra, e ninguem percebeu por meses. Este script procura o resto
dessa familia.

O que ele NAO faz: julgar se um numero esta "certo" contra o mundo real. Ele
compara o sistema consigo mesmo. Divergencia aqui e sempre uma das duas
coisas, e as duas precisam de acao:

  1. bug — duas regras para o mesmo conceito;
  2. recorte DIFERENTE de proposito — e entao a tela precisa DIZER isso, senao
     o usuario compara dois numeros que nunca deveriam bater.

Rodar:  uv run python scripts/conferir_numeros.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TOL = 0.01          # centavo: divergencia real nunca e de arredondamento
ACHADOS: list[tuple[str, str, str]] = []   # (nivel, titulo, detalhe)


def _fmt(v) -> str:
    if v is None:
        return "n/d"
    if isinstance(v, (int, float)):
        return f"{v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return str(v)


def _pct_br(v) -> str:
    """O mesmo formato do provedor do WhatsApp, para comparar TEXTO com TEXTO."""
    from api.whatsapp.valores import pct
    return pct(v)


def _brl_br(v) -> str:
    from api.whatsapp.valores import brl
    return brl(v)


def conferir(titulo: str, a_nome: str, a, b_nome: str, b, *,
             tol: float | None = TOL, nota: str = "") -> None:
    """Compara dois valores que deveriam ser iguais.

    `tol=None` compara EXATO, para texto — e o caso da mensagem do WhatsApp,
    em que o que importa nao e o numero por tras e sim o que a pessoa le.
    """
    if a is None or b is None:
        ACHADOS.append(("VAZIO", titulo,
                        f"{a_nome}={_fmt(a)} · {b_nome}={_fmt(b)}"))
        return
    if tol is None:
        # TEXTO: compara o que a pessoa LE, nao o numero por tras. Dois
        # formatadores diferentes para o mesmo valor produzem a mesma conta e
        # telas que se contradizem — e e a tela que vai para fora da empresa.
        if str(a) == str(b):
            print(f"  OK    {titulo}: {a}")
            return
        ACHADOS.append(("DIVERGE", titulo,
                        f"{a_nome}={a!r} · {b_nome}={b!r}"
                        + (f" · {nota}" if nota else "")))
        print(f"  DIFERE {titulo}: {a!r} x {b!r}")
        return
    dif = abs(float(a) - float(b))
    if dif <= tol:
        print(f"  OK    {titulo}: {_fmt(a)}")
        return
    pct = 100 * dif / max(abs(float(a)), abs(float(b)), 1)
    ACHADOS.append(("DIVERGE", titulo,
                    f"{a_nome}={_fmt(a)} · {b_nome}={_fmt(b)} · "
                    f"dif={_fmt(dif)} ({pct:.1f}%)" + (f" · {nota}" if nota else "")))
    print(f"  DIFERE {titulo}: {_fmt(a)} x {_fmt(b)}  (dif {_fmt(dif)})")


def conferir_soma(titulo: str, total, partes, *, rotulo_partes: str,
                  tol: float = TOL) -> None:
    """Total do KPI x soma das linhas da tabela. Quando um total existe e o
    detalhe nao fecha, o problema costuma ser o JOIN, nao o negocio."""
    soma = sum(float(x or 0) for x in partes)
    conferir(titulo, "KPI", total, rotulo_partes, soma, tol=tol)


def bloco(nome: str):
    print(f"\n=== {nome} ===")


def main() -> int:
    from api import queries as q

    hoje = date.today()
    ini_mes = hoje.replace(day=1)

    print(f"Reconciliacao — {hoje.isoformat()}")

    # ------------------------------------------------------------------
    bloco("SALDO BANCARIO (o defeito ja corrigido — guarda de regressao)")
    ov = q.get_overview()
    # A VISAO GERAL E OUTRA FUNCAO. `get_overview()` e o painel FINANCEIRO e
    # nao tem os recortes de receita — pedir `realizado_acumulado` a ele
    # devolvia None e a conferencia passava por VACUIDADE, verde sem medir
    # nada. Foi assim que a primeira versao deste bloco "passou".
    vg = q.get_visao_geral()
    fc = q.get_fluxo_consolidado("semana", 180)
    an = q.get_antecipacao(dias=90, reserva=0, taxa_mes=2.0)
    k = ov["kpis"]

    conferir("Saldo inicial", "Visao Geral", k["saldo_atual"],
             "Fluxo Consolidado", fc["kpis"]["saldo_inicial"])
    conferir("Saldo inicial", "Visao Geral", k["saldo_atual"],
             "Antecipacao", an["kpis"]["saldo_inicial"])
    conferir_soma("Saldo por banco x total", fc["kpis"]["saldo_inicial"]
                  - (k.get("saldo_caixa") or 0),
                  [c["saldo"] for c in fc.get("contas", [])],
                  rotulo_partes="soma das contas")

    # ------------------------------------------------------------------
    bloco("A RECEBER / A PAGAR EM ABERTO")
    conferir("A receber em aberto", "Visao Geral", k.get("receber_aberto"),
             "Fluxo Consolidado", (fc.get("recebiveis") or {}).get("aberto"))

    # aging tem de somar o total
    ag_r = ov.get("aging_receber") or []
    conferir_soma("A receber: aging x total", k.get("receber_aberto"),
                  [f.get("valor") for f in ag_r], rotulo_partes="soma do aging")
    ag_p = ov.get("aging_pagar") or []
    conferir_soma("A pagar: aging x total", k.get("pagar_aberto"),
                  [f.get("valor") for f in ag_p], rotulo_partes="soma do aging")

    # ------------------------------------------------------------------
    bloco("FLUXO CONSOLIDADO: cascata interna")
    linhas = fc.get("linhas") or []
    if linhas:
        # saldo_final de um periodo tem de ser o saldo_inicial do seguinte
        quebras = [(a["rotulo"], b["rotulo"], a["saldo_final"], b["saldo_inicial"])
                   for a, b in zip(linhas, linhas[1:])
                   if abs(a["saldo_final"] - b["saldo_inicial"]) > TOL]
        if quebras:
            ACHADOS.append(("DIVERGE", "Cascata do fluxo consolidado",
                            f"{len(quebras)} quebra(s); 1a: {quebras[0]}"))
            print(f"  DIFERE cascata: {len(quebras)} quebra(s)")
        else:
            print(f"  OK    cascata encadeia nos {len(linhas)} periodos")
        # entradas - saidas = resultado
        ruins = [l["rotulo"] for l in linhas
                 if abs((l["entradas"] - l["saidas"]) - l["resultado"]) > TOL]
        conferir("Resultado = entradas - saidas", "periodos fora", len(ruins),
                 "esperado", 0)

    # ------------------------------------------------------------------
    bloco("ANTECIPACAO: operacoes x documentos")
    ops = an.get("operacoes") or []
    if ops:
        fora = []
        for o in ops:
            docs = o.get("documentos") or []
            if o.get("documentos_total", 0) > len(docs):
                continue        # lista cortada em 40: nao da para somar
            soma = round(sum(d["valor"] for d in docs), 2)
            if abs(soma - o["valor"]) > TOL:
                fora.append((o["dia"], o["valor"], soma))
        conferir("Documentos somam o valor da operacao", "operacoes fora",
                 len(fora), "esperado", 0,
                 nota=(str(fora[:2]) if fora else ""))
        # por_cliente e integral: sempre soma o valor da operacao
        fora2 = [o["dia"] for o in ops
                 if abs(sum(c["valor"] for c in (o.get("por_cliente") or []))
                        - o["valor"]) > 0.05]
        conferir("Resumo por sacado soma a operacao", "operacoes fora",
                 len(fora2), "esperado", 0)
        conferir_soma("Total a antecipar x soma das operacoes",
                      an["kpis"]["total_antecipar"],
                      [o["valor"] for o in ops],
                      rotulo_partes="soma das operacoes",
                      tol=0.02 if an.get("operacoes_total", 0) <= len(ops) else 1e12)

    # ------------------------------------------------------------------
    bloco("KM: analise x painel de TV (mesmo periodo)")
    km = q.get_analise_km(None, ini_mes.isoformat(), hoje.isoformat())
    kk = km["kpis"]
    conferir("Km total = carregado + vazio", "km_total", kk.get("km_total"),
             "carregado+vazio", (kk.get("km_carregado") or 0) + (kk.get("km_vazio") or 0))
    conferir_soma("Km por modalidade x total", kk.get("km_total"),
                  [m.get("km_total") for m in (km.get("modalidades") or [])],
                  rotulo_partes="soma das modalidades", tol=1.0)

    # ------------------------------------------------------------------
    bloco("ORDENS DE COMPRA: faixas x KPI")
    oc = q.get_oc_pendentes(180)
    ock = oc["kpis"]
    conferir_soma("OC em aberto: faixas x KPI", ock.get("ocs"),
                  [f.get("ocs") for f in (oc.get("faixas") or [])],
                  rotulo_partes="soma das faixas")
    conferir_soma("OC em aberto (valor): faixas x KPI", ock.get("valor"),
                  [f.get("valor") for f in (oc.get("faixas") or [])],
                  rotulo_partes="soma das faixas", tol=0.05)
    conferir("Previsao: futura + vencida + sem data = total",
             "soma", (ock.get("prev_futura") or 0) + (ock.get("prev_vencida") or 0)
             + (ock.get("prev_ausente") or 0), "OCs em aberto", ock.get("ocs"))

    # ------------------------------------------------------------------
    bloco("DRE: cascata fecha")
    dre = q.get_dre(f"{ini_mes.year}-01", f"{hoje.year}-{hoje.month:02d}")
    L = {l["rotulo"]: l for l in (dre.get("linhas") or [])}

    def _tot(rot):
        """Total da linha. O campo e `total` — na primeira versao eu li
        `valor`, que nao existe, e o bloco inteiro pulava EM SILENCIO. Por isso
        `falta()` grita em vez de seguir adiante."""
        l = L.get(rot)
        return None if l is None else l.get("total")

    def falta(*rots):
        ausentes = [r for r in rots if r not in L]
        if ausentes:
            ACHADOS.append(("VAZIO", "DRE: linha ausente",
                            f"nao encontrei {ausentes} — conferencia pulada. "
                            f"rotulos disponiveis: {sorted(L)[:8]}"))
            return True
        return False

    if not falta("RECEITA BRUTA", "DEDUCOES DA RECEITA", "RECEITA LIQUIDA"):
        conferir("Receita liquida = bruta - deducoes", "calculado",
                 _tot("RECEITA BRUTA") + _tot("DEDUCOES DA RECEITA"),
                 "linha da DRE", _tot("RECEITA LIQUIDA"), tol=0.05)
    if not falta("RECEITA LIQUIDA", "CSP", "LUCRO BRUTO"):
        conferir("Lucro bruto = receita liquida + CSP", "calculado",
                 _tot("RECEITA LIQUIDA") + _tot("CSP"),
                 "linha da DRE", _tot("LUCRO BRUTO"), tol=0.05)
    if not falta("CSP", "CUSTO FIXO", "CUSTO VARIAVEL", "CREDITOS TRIBUTARIOS"):
        conferir("CSP = fixo + variavel + creditos", "calculado",
                 _tot("CUSTO FIXO") + _tot("CUSTO VARIAVEL")
                 + _tot("CREDITOS TRIBUTARIOS"),
                 "linha da DRE", _tot("CSP"), tol=0.05)
    if not falta("DEDUCOES DA RECEITA"):
        filhos = ["IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS", "IMPOSTOS MUNICIPAIS",
                  "CONTRIBUICAO PREVIDENCIARIA", "ANULACOES", "DESCONTOS"]
        if not falta(*filhos):
            conferir_soma("Deducoes = soma dos impostos",
                          _tot("DEDUCOES DA RECEITA"),
                          [_tot(f) for f in filhos],
                          rotulo_partes="soma das linhas filhas", tol=0.05)

    # cada linha tem de ser a soma dos proprios meses
    fora_mes = []
    for l in (dre.get("linhas") or []):
        meses = l.get("meses") or {}
        if not meses or l.get("total") is None:
            continue
        if abs(sum(meses.values()) - l["total"]) > 0.05:
            fora_mes.append(l["rotulo"])
    conferir("Total da linha = soma dos meses", "linhas fora",
             len(fora_mes), "esperado", 0, nota=str(fora_mes[:3]))

    # e o detalhe por agrupador tem de somar a linha
    fora_ag = []
    for l in (dre.get("linhas") or []):
        det = l.get("detalhe") or []
        if not det or l.get("total") is None:
            continue
        if abs(sum(d.get("total") or 0 for d in det) - l["total"]) > 0.05:
            fora_ag.append(l["rotulo"])
    conferir("Linha = soma dos agrupadores", "linhas fora",
             len(fora_ag), "esperado", 0, nota=str(fora_ag[:3]))

    # ------------------------------------------------------------------
    bloco("RECEITA: os tres recortes, e a regua da meta")
    # CLAUDE.md registra que sao 3 cortes distintos DE PROPOSITO (faturas
    # emitidas x frete das viagens x CT-e+KMM+NFS-e da meta). Aqui nao se exige
    # que batam — exige-se que a DIFERENCA seja conhecida, para ninguem
    # descobrir sozinho na reuniao.
    fat_mes = vg.get("faturamento_mes")
    cte_mes = vg.get("receita_mes_cte")
    real_acum = vg.get("realizado_acumulado")
    meta_acum = vg.get("meta_acumulada")
    ating = vg.get("atingimento_mes")
    rb_mes = None
    lrb = L.get("RECEITA BRUTA")
    if lrb and lrb.get("meses"):
        rb_mes = (lrb["meses"] or {}).get(f"{hoje.year}-{hoje.month:02d}")

    # CAMPO AUSENTE E FALHA, NAO SILENCIO. Um conferidor que se cala quando o
    # dado some e pior que nenhum: da a sensacao de que esta tudo conferido.
    # Foi exatamente o que aconteceu ao ler do payload errado.
    for nome, val in (("faturamento_mes", fat_mes), ("receita_mes_cte", cte_mes),
                      ("realizado_acumulado", real_acum),
                      ("meta_acumulada", meta_acum), ("atingimento_mes", ating)):
        if val is None:
            ACHADOS.append(("VAZIO", "Recorte de receita ausente",
                            f"`{nome}` nao veio da Visao Geral — sem ele a "
                            "conferencia desta familia passa por vacuidade"))
    print(f"  INFO  1) Faturas emitidas no mes    : {_fmt(fat_mes)}")
    print(f"  INFO  2) Frete das viagens (CT-e)   : {_fmt(cte_mes)}")
    print(f"  INFO  3) Realizado da regua da META : {_fmt(real_acum)}")
    print(f"  INFO     Receita bruta da DRE       : {_fmt(rb_mes)}")

    if fat_mes is not None and rb_mes is not None:
        dif = abs(fat_mes - rb_mes)
        pct = 100 * dif / max(abs(fat_mes), abs(rb_mes), 1)
        print(f"  INFO  faturas x DRE: {_fmt(dif)} ({pct:.1f}%) — emissao x competencia")
        if pct > 40:
            ACHADOS.append(("OLHAR", "Faturamento x Receita bruta",
                            f"{_fmt(fat_mes)} x {_fmt(rb_mes)} ({pct:.0f}% de "
                            "diferenca). Sao recortes distintos por definicao, "
                            "mas essa distancia merece conferencia."))
    if fat_mes is not None and real_acum is not None:
        dif = abs(fat_mes - real_acum)
        pct = 100 * dif / max(abs(fat_mes), abs(real_acum), 1)
        print(f"  INFO  faturas x regua da meta: {_fmt(dif)} ({pct:.1f}%)")
        # 25% e o dobro da distancia normal entre esses dois recortes (~12%).
        # Nao e limite de qualidade: e onde a diferenca deixa de ser explicavel
        # pelo recorte e passa a merecer alguem olhando.
        if pct > 25:
            ACHADOS.append(("OLHAR", "Faturamento x regua da meta",
                            f"{_fmt(fat_mes)} x {_fmt(real_acum)} ({pct:.0f}%). "
                            "Sao recortes distintos, mas essa distancia merece "
                            "conferencia."))

    # O PAR QUE FECHA, e o unico erro desta familia que ja quase saiu para a
    # diretoria: misturar o numerador de uma regua com o denominador de outra
    # deu 96% de atingimento onde o real era 91,3% — faltava um milhao. O que
    # fecha e `realizado_acumulado / meta_acumulada`, e e isto que se confere.
    if ating is not None and real_acum is not None and meta_acum:
        conferir("Atingimento = realizado / meta", "atingimento_mes", ating,
                 "realizado_acumulado / meta_acumulada", real_acum / meta_acum,
                 tol=0.0001,
                 nota="se divergir, alguem recalculou o atingimento com o "
                      "numerador de outra regua")

    # A REGUA E A SERIE DO GRAFICO TEM DE SER A MESMA COISA: o acumulado que o
    # KPI mostra e a soma da serie diaria que o grafico desenha. Divergir aqui
    # significa que o cartao e o grafico da mesma tela contam historias
    # diferentes sobre o mesmo mes.
    diario = vg.get("diario") or []
    if diario and real_acum is not None:
        conferir("Realizado = soma da serie diaria", "realizado_acumulado",
                 real_acum, "soma do diario",
                 sum(float(d.get("realizado") or 0) for d in diario), tol=0.05)
    if diario and meta_acum:
        conferir("Meta acumulada = soma das metas ate hoje", "meta_acumulada",
                 meta_acum, "soma do diario ate o dia de hoje",
                 sum(float(d.get("meta") or 0) for d in diario
                     if int(d.get("dia") or 0) <= hoje.day), tol=0.05)

    # ------------------------------------------------------------------
    bloco("MENSAGEM DE FATURAMENTO: o WhatsApp x a Visao Geral")
    # O provedor do WhatsApp manda numero do painel para fora da empresa. Se
    # ele e a tela discordarem, quem descobre e quem recebeu a mensagem.
    try:
        from api.whatsapp.valores import faturamento_diario
        w = faturamento_diario(vg)
        conferir("Atingimento do mes na mensagem", "WhatsApp",
                 w.get("atingimento_mes"), "Visao Geral",
                 _pct_br(ating), tol=None,
                 nota="o provedor le o atingimento PRONTO; recalcular abriria a "
                      "chance de usar o numerador de outra regua")
        conferir("Acumulado do mes na mensagem", "WhatsApp",
                 w.get("acumulado_mes"), "Visao Geral", _brl_br(real_acum),
                 tol=None)
    except Exception as exc:  # noqa: BLE001
        ACHADOS.append(("VAZIO", "Mensagem de faturamento",
                        f"nao deu para conferir ({type(exc).__name__}: {exc})"))

    # ------------------------------------------------------------------
    bloco("VENCIDOS: fluxo consolidado x aging da visao geral")
    venc_fc = fc["kpis"].get("vencido_total")
    venc_ag = sum(float(f.get("valor") or 0) for f in ag_p
                  if str(f.get("faixa", "")).startswith(("2_", "3_", "4_", "5_")))
    conferir("A pagar vencido", "Fluxo Consolidado", venc_fc,
             "aging da Visao Geral", venc_ag, tol=0.05,
             nota="o consolidado usa contaapagar direto; o aging passa pelo mesmo "
                  "recorte de filial/data da tela")

    # ------------------------------------------------------------------
    print("\n" + "=" * 66)
    if not ACHADOS:
        print("NENHUMA DIVERGENCIA.")
        return 0
    print(f"{len(ACHADOS)} PONTO(S) PARA OLHAR:\n")
    for nivel, titulo, det in ACHADOS:
        print(f"[{nivel}] {titulo}\n        {det}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
