"""Motor da previsão de fechamento — 100% PURO (sem banco, sem datas de hoje).

Convenção de sinal = razão da DRE: receita POSITIVA, custo/despesa NEGATIVOS
(valor = credito - debito). Toda fórmula soma; nunca subtrai por natureza.
Cada estratégia devolve {"previsto", "estrategia", "premissas": [str]}.
"""
from __future__ import annotations

import unicodedata

from api.queries import DRE_MODELO
from api.previsao.completude import (DISPERSAO_MAX, PISO_COMPLETUDE,
                                     completude_em, dispersao_em)

PESO_DIAS_PLENO = 3  # dias com meta decorridos para o ritmo observado valer 100%


def _brl(v: float) -> str:
    """Formata valor em R$ pt-BR (X.XXX,XX sem centavos, já que todas as estimativas são inteiras)."""
    s = f"{v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _pct(v: float, casas: int = 1) -> str:
    """Formata percentual em pt-BR (XX,X%) — casas = casa decimais após a vírgula."""
    return f"{v*100:.{casas}f}%".replace(".", ",")


def _num(v: float, casas: int = 2) -> str:
    """Formata número decimal em pt-BR (X,XX) — para índices e outras métricas."""
    return f"{v:.{casas}f}".replace(".", ",")


def _res(previsto: float, estrategia: str, premissas: list[str]) -> dict:
    return {"previsto": float(previsto), "estrategia": estrategia,
            "premissas": premissas}


def mediana(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    meio = n // 2
    return s[meio] if n % 2 else (s[meio - 1] + s[meio]) / 2.0


def prever_receita(real_acum: float, meta_acum: float, meta_mes: float,
                   ating_hist: float | None, dias_meta_decorridos: int) -> dict:
    base_hist = ating_hist if ating_hist is not None else 1.0
    ritmo_obs = (real_acum / meta_acum) if meta_acum else None
    w = min(1.0, max(0, dias_meta_decorridos) / PESO_DIAS_PLENO)
    ritmo = (w * ritmo_obs + (1 - w) * base_hist) if ritmo_obs is not None else base_hist
    meta_rest = max(0.0, meta_mes - meta_acum)
    previsto = real_acum + meta_rest * ritmo
    return _res(previsto, "driver_fiscal", [
        f"realizado fiscal MTD {_brl(real_acum)} sobre meta acumulada {_brl(meta_acum)}",
        f"ritmo aplicado ao restante da meta: {_pct(ritmo, 1)} "
        f"(observado peso {_pct(w, 0)}, historico 3m {_pct(base_hist, 1)})",
        f"meta restante do mes: {_brl(meta_rest)}",
    ])


def prever_pct_receita(receita_prev: float, pct: float, nome_pct: str) -> dict:
    return _res(receita_prev * pct, "pct_receita",
                [f"{_pct(pct, 2)} da receita prevista ({nome_pct})"])


def prever_nivel(hist: list[float], rotulo_fonte: str) -> dict:
    if not hist:
        return _res(0.0, "nivel", [f"sem historico ({rotulo_fonte})"])
    m = mediana(hist)
    return _res(m, "nivel",
                [f"mediana de {len(hist)} meses fechados ({rotulo_fonte})"])


def prever_razao_completude(razao_mtd: float, frac: float, fallback: dict,
                            dispersao: float = 0.0) -> dict:
    """dispersao = dispersao_em(...) no dia: quando a curva-media e' bimodal
    (dispersao > DISPERSAO_MAX), dividir pela media nao significa nada - uns
    meses escrituram cedo, outros so' no lote tardio - e o fallback (nivel) e'
    o mais confiavel disponivel aqui. Default 0.0 mantem os call sites/testes
    que ainda nao medem dispersao com o comportamento de sempre."""
    if dispersao > DISPERSAO_MAX:
        return _res(fallback["previsto"], fallback["estrategia"],
                    fallback["premissas"] + [
                        f"escrituracao em lote detectada (dispersao {_pct(dispersao, 0)}) "
                        f"- curva nao confiavel, usando {fallback['estrategia']}"])
    if frac < PISO_COMPLETUDE:
        return _res(fallback["previsto"], fallback["estrategia"],
                    fallback["premissas"] + [
                        f"completude esperada {_pct(frac, 0)} abaixo do piso "
                        f"{_pct(PISO_COMPLETUDE, 0)} - usando fallback"])
    return _res(razao_mtd / frac, "razao_completude", [
        f"razao MTD {_brl(razao_mtd)} dividido pela completude esperada {_pct(frac, 0)}"])


def prever_frete_compra(razao_mtd: float, vfc_mtd: float, receita_prev: float,
                        receita_mtd: float, razao_custo_receita: float,
                        fonte_receita_mtd: str = "faturamento MTD") -> dict:
    """As DUAS pernas tem de sair da MESMA regua de maturidade.

    `conhecido` vem das VIAGENS (operacional: completo para os dias decorridos,
    o acerto contabil so' chega ~6 dias depois). Se `receita_mtd` vier do razao
    (escrituracao bimodal - 1,8% a 3,8% ate D+34 em alguns meses) ou do fiscal,
    a receita restante fica INFLADA e a projecao cobre de novo o trecho do mes
    que o custo conhecido ja cobriu: dupla contagem no maior componente do CV.
    Por isso o call site passa `vfc.receita_viagens` (a receita das MESMAS
    viagens) sempre que ela existe, e diz na premissa qual regua usou."""
    conhecido = min(razao_mtd, -abs(vfc_mtd))  # mais negativo = mais custo conhecido
    receita_rest = max(0.0, receita_prev - receita_mtd)
    projetado = receita_rest * razao_custo_receita
    return _res(conhecido + projetado, "frete_compra", [
        f"conhecido: max(|razao| {_brl(abs(razao_mtd))}, |frete compra viagens| "
        f"{_brl(abs(vfc_mtd))})",
        f"receita ja coberta por esse custo: {_brl(receita_mtd)} "
        f"({fonte_receita_mtd}) - mesma regua do custo conhecido",
        f"projecao: {_pct(abs(razao_custo_receita), 1)} da receita restante prevista "
        f"{_brl(receita_rest)} (razao custo/receita 6m)"])


def prever_sazonal(vals6: list[float], indices6: list[float],
                   indice_alvo: float) -> dict:
    if not vals6:
        return _res(0.0, "sazonal", ["sem historico"])
    dessaz = [v / i for v, i in zip(vals6, indices6) if i]
    nivel = sum(dessaz) / len(dessaz) if dessaz else 0.0
    return _res(nivel * indice_alvo, "sazonal", [
        f"nivel 6m dessazonalizado {_brl(nivel)} x indice do mes {_num(indice_alvo, 2)}"])


CONSOLIDADO_EM = 0.97  # completude esperada a partir da qual o razao e a verdade


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s.upper()).encode("ascii", "ignore").decode()


def linha_do_agrupador(ag: str) -> str | None:
    na = norm(ag)
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            continue
        for s in sel:
            ns = norm(s)
            if (tipo == "nome" and na == ns) or (tipo == "pref" and na.startswith(ns)):
                return rotulo
    return None


_ESTRATEGIA_PREFIXOS = [
    ("CV - FRETE AGREGADOS", "frete_compra"),
    ("CV - FRETE TERCEIROS", "frete_compra"),
    ("CF - FOLHA", "nivel"),
    ("CF - PESSOAL", "nivel"),
    ("OVERHEAD - FOLHA", "nivel"),
    ("CR - ", "nivel"),
    ("CV - ", "razao_completude"),
    ("CF - ", "razao_completude"),
    ("OVERHEAD - ", "razao_completude"),
    ("FINANC - ", "sazonal"),
    ("INDENIZA", "sazonal"),
    ("OUTRAS ", "sazonal"),
    ("(1, ", "sazonal"),
    ("DESPESAS N", "sazonal"),
    ("RECEITA - VENDA", "sazonal"),
    ("ANULA", "sazonal"),
    ("DESCONTOS", "sazonal"),
]


def estrategia_do_agrupador(ag: str) -> str:
    na = norm(ag)
    for pref, estrat in _ESTRATEGIA_PREFIXOS:
        if na.startswith(norm(pref)):
            return estrat
    return "runrate"


def montar_cascata(direta: dict[str, float]) -> dict[str, float]:
    """Preenche todas as linhas do DRE_MODELO: diretas primeiro, fórmulas em
    ordem de declaração (mesma 2-passada do get_dre)."""
    out: dict[str, float] = {}
    for rotulo, _nivel, tipo, _sel in DRE_MODELO:
        if tipo != "formula":
            out[rotulo] = float(direta.get(rotulo, 0.0))
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            out[rotulo] = sum(out.get(r, 0.0) for r in sel)
    return out


def banda_fallback(base: float, hist6: list[float],
                   frac_restante: float) -> tuple[float, float]:
    if len(hist6) < 2:
        return base, base
    media = sum(hist6) / len(hist6)
    var = sum((v - media) ** 2 for v in hist6) / len(hist6)
    meio = (var ** 0.5) * max(0.0, min(1.0, frac_restante))
    return base - meio, base + meio


def banda_calibrada(base: float, calib_linha: dict | None,
                    dia_util: int) -> tuple[float, float] | None:
    """Intervalo provavel do FECHAMENTO a partir do previsto (`base`).

    A calibracao guarda o erro RELATIVO do metodo medido no backtest
    (scripts/backtest_previsao.py): `err = (previsto - final) / |final|`.
    Invertendo para o mes novo, no qual so' existe o previsto:

        final ~= previsto - erro_relativo x |previsto|

    ou seja SUBTRAI. Somar (o defeito corrigido aqui) joga o intervalo para o
    lado ERRADO do erro: com a calibracao de RECEITA BRUTA em D25 (p20 -3,24%,
    p80 -1,27%, os dois NEGATIVOS = o metodo SUBESTIMA), somar punha a banda
    inteira ABAIXO do previsto justamente quando o fechamento tende a vir
    ACIMA dele.

    Consequencia (esperada, nao defeito): quando p20 e p80 tem o MESMO sinal o
    metodo tem vies conhecido naquele dia e o intervalo do fechamento nao
    contem o previsto - ele fica todo do lado para onde o fechamento costuma
    andar. Quem le a banda ve o vies medido, em vez de uma simetria falsa.

    Devolve (base - p20*|base|, base - p80*|base|): com p20 <= p80 o PRIMEIRO
    elemento e' o MAIOR. Quem rotula pessimista/otimista (servico.py) resolve
    isso com min()/max(), porque "maior" nem sempre e' "melhor" (custo)."""
    if not calib_linha:
        return None
    dias = sorted(int(d) for d in calib_linha)
    if not dias:
        return None
    d = max(dias[0], min(dias[-1], dia_util))
    lo = max(x for x in dias if x <= d)
    hi = min(x for x in dias if x >= d)
    w = 0.0 if hi == lo else (d - lo) / (hi - lo)
    def _mix(campo: str) -> float:
        a = calib_linha[str(lo)][campo]
        b = calib_linha[str(hi)][campo]
        return a + (b - a) * w
    esc = abs(base)
    a, b = base - _mix("p20") * esc, base - _mix("p80") * esc
    # Contrato (menor, maior), IGUAL ao de banda_fallback: a cascata SOMA as
    # duas fontes de banda na mesma ponta antes do min()/max() por linha, entao
    # devolver as pontas em ordem trocada misturaria extremo alto de uma linha
    # com extremo baixo de outra e ESTREITARIA a banda do RESULTADO (medido:
    # -29% a -64%). O sinal de _mix depende da calibracao, entao ordenamos aqui.
    return min(a, b), max(a, b)


def fontes_fora(fontes: list[dict] | None, apenas_drivers: bool = False) -> list[str]:
    """Nomes das fontes com ok=False. PURA - e' a mesma leitura usada pelo
    gate do snapshot (servico) e pelos alertas/digest (alertas.py); duplicar a
    regra nos dois lugares e' como elas divergiriam.

    `apenas_drivers=True` ignora as fontes que NAO entram no calculo do
    previsto (hoje so' o orcamento, que alimenta a coluna de comparacao). Sem
    isso, um ano sem versao de orcamento cadastrada - estado normal em janeiro
    - marcaria a previsao inteira como degradada, pararia o snapshot diario e
    rebaixaria o alerta de resultado negativo todo dia. Fonte sem a chave
    `driver` conta como driver (default seguro para payload antigo/cache)."""
    return [f.get("nome") or "?" for f in (fontes or [])
            if not f.get("ok") and (not apenas_drivers or f.get("driver", True))]


def aplicar_ajuste(previsto: float, ajuste: dict | None) -> tuple[float, float]:
    if not ajuste:
        return previsto, 0.0
    if ajuste["tipo"] == "delta":
        return previsto + ajuste["valor"], ajuste["valor"]
    return ajuste["valor"], ajuste["valor"] - previsto


def estimar_m1(razao_ag: dict[str, float], curva: dict, dia_rel: int,
               fallback_por_ag: dict[str, dict]) -> dict[str, dict]:
    """`curva` já carrega a dispersão (montar_curva) — não precisa de outro
    parâmetro para chegar até aqui, só ler com dispersao_em(curva, ag, rot, ..).

    Quando a curva é bimodal (dispersao > DISPERSAO_MAX) dividir pela média
    dobra os meses "cedo" e esmaga os "tardios" (ver completude.py). Sem um
    jeito confiável de dividir, escolhe o MAIOR em módulo entre a razão como
    está e o fallback de nível: se o lote já entrou, a razão já superou (ou
    encostou nele) e é o melhor conhecido; se o lote ainda não entrou, a
    razão está artificialmente baixa e o nível é o melhor conhecido."""
    out: dict[str, dict] = {}
    for ag, valor in razao_ag.items():
        rot = linha_do_agrupador(ag)
        frac = completude_em(curva, ag, rot, dia_rel)
        disp = dispersao_em(curva, ag, rot, dia_rel)
        if frac >= CONSOLIDADO_EM:
            out[ag] = _res(valor, "consolidado",
                           [f"razao {_pct(frac, 0)} escriturado - consolidado"])
        elif disp > DISPERSAO_MAX:
            fb = fallback_por_ag.get(ag) or _res(valor, "razao_parcial",
                                                 ["sem fallback disponivel"])
            if abs(valor) >= abs(fb["previsto"]):
                out[ag] = _res(valor, "lote", [
                    f"escrituracao em lote detectada (dispersao {_pct(disp, 0)}) - "
                    f"razao {_brl(valor)} ja supera o nivel {_brl(fb['previsto'])} "
                    f"- usando razao"])
            else:
                out[ag] = _res(fb["previsto"], "lote", fb["premissas"] + [
                    f"escrituracao em lote detectada (dispersao {_pct(disp, 0)}) - "
                    f"razao {_brl(valor)} ainda abaixo do nivel {_brl(fb['previsto'])} "
                    f"- usando nivel"])
        elif frac < PISO_COMPLETUDE:
            fb = fallback_por_ag.get(ag) or _res(valor, "razao_parcial",
                                                 ["sem fallback disponivel"])
            out[ag] = _res(fb["previsto"], fb["estrategia"], fb["premissas"] + [
                f"completude esperada {_pct(frac, 0)} abaixo do piso - fallback"])
        else:
            out[ag] = _res(valor / frac, "razao_completude", [
                f"razao parcial {_brl(valor)} / completude esperada {_pct(frac, 0)}"])
    return out
