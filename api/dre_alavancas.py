# -*- coding: utf-8 -*-
"""Onde atacar para virar o resultado — alavancas medidas, não opiniões.

A aba responde UMA pergunta: quanto falta por mês para o resultado virar, e
quais são os poucos lugares onde esse dinheiro pode sair. Tudo aqui é medido
contra o razão e a operação; nada é meta, palpite ou benchmark de fora.

TRÊS REGRAS QUE DECIDEM O QUE ENTRA:

1. **ALAVANCA TEM TAMANHO EM R$/MÊS.** "Reduzir custos" não é alavanca; "o
   financeiro custa R$ 819 mil/mês" é. O que não se mede não entra na lista,
   por mais verdadeiro que pareça.

2. **O QUE PRECISA DE CONFIRMAÇÃO SE DECLARA.** A comparação entre frota
   própria e agregado depende de saber se o R$/km pago ao agregado inclui o
   combustível que a empresa adianta e recupera depois. Enquanto isso não for
   confirmado, a alavanca aparece com o aviso — recomendação sobre número
   incerto é pior que recomendação nenhuma.

3. **O QUE JÁ ESTÁ BOM SAI DA LISTA.** O retorno vazio está em 17,8%, abaixo
   do limite de 20% da casa. Ele aparece como "não é aqui" justamente para
   ninguém gastar energia nele — lista de problemas que inclui não-problemas
   dilui a atenção de quem lê.

A ORDEM É POR R$/MÊS EM JOGO, e "em jogo" não é "economia garantida": é o
tamanho da conta que aquela decisão mexe. A tela diz isso com todas as letras,
porque somar as alavancas e prometer o total seria vender o que não existe.
"""
from __future__ import annotations

import logging
from datetime import date

from . import db, queries

log = logging.getLogger("cortex.dre_alavancas")

#: Km/mês que um cavalo de lotação deveria rodar. NÃO é meta da casa: é a
#: faixa de referência do setor (8–10 mil), e entra como o piso dela para a
#: conta ser conservadora. A tela DIZ que é referência externa.
KM_MES_REFERENCIA = 8000

#: Acima disto o retorno vazio é problema (regra da casa, FTL).
VAZIO_LIMITE = 0.20


def _mm(vals: list[float], meses: int) -> float:
    return (sum(vals) / meses) if meses else 0.0


def calcular(comp_de: str, comp_ate: str) -> dict:
    """As alavancas do período, ordenadas por R$/mês em jogo."""
    dre = queries.get_dre(comp_de, comp_ate)
    meses = dre["meses"]
    n = len(meses) or 1
    linhas = {l["rotulo"]: [l["meses"].get(m, 0.0) for m in meses]
              for l in dre["linhas"]}
    ag = {a["agrupador"]: [a["meses"].get(m, 0.0) for m in meses]
          for l in dre["linhas"] for a in (l.get("detalhe") or [])}

    def med(rot):
        return _mm(linhas.get(rot, [0.0]), n)

    resultado_mes = med("RESULTADO DO EXERCICIO")
    receita_mes = med("RECEITA LIQUIDA")

    de_iso = comp_de + "-01"
    ate_iso = (date(int(comp_ate[:4]) + (1 if comp_ate[5:7] == "12" else 0),
                    1 if comp_ate[5:7] == "12" else int(comp_ate[5:7]) + 1,
                    1)).isoformat()

    alavancas = []

    # ---------------------------------------------------------- financeiro
    fin = med("RESULTADO FINANCEIRO")
    if fin < 0:
        metade = len(meses) // 2 or 1
        prim = _mm(linhas["RESULTADO FINANCEIRO"][:metade], metade)
        ult = _mm(linhas["RESULTADO FINANCEIRO"][metade:], len(meses) - metade)
        piorou = ult < prim
        alavancas.append({
            "chave": "financeiro",
            "titulo": "Custo do dinheiro",
            "valor_mes": abs(fin),
            "pct_receita": (abs(fin) / receita_mes) if receita_mes else None,
            "certeza": "medido",
            "o_que_e": (
                "Despesa financeira líquida: %s por mês, %s da receita "
                "líquida." % (_brl(abs(fin)), _pct(abs(fin) / receita_mes
                                                   if receita_mes else 0))
                + (" E PIOROU: passou de %s para %s por mês entre a primeira "
                   "e a segunda metade do período."
                   % (_brl(abs(prim)), _brl(abs(ult))) if piorou else "")),
            "o_que_fazer": (
                "Abrir o custo da dívida por contrato e o ciclo de caixa. "
                "É o único buraco que piorou enquanto a operação melhorava — "
                "e sozinho ele é maior que a margem bruta de vários meses."),
            "fonte": "DRE · linha RESULTADO FINANCEIRO",
        })

    # ------------------------------------------------- ociosidade da frota
    try:
        mvb = queries.get_make_vs_buy(comp_de, comp_ate)["resumo"]
        km_prop = mvb.get("km_proprio_medido") or 0
        comp = mvb.get("componentes_km") or {}
        # SÓ O QUE VARIA COM O KM. `componentes_km` traz também motoristas,
        # fixo e depreciação — somar tudo dá o custo CHEIO (R$ 24,52/km), e
        # chamar isso de "variável" fazia a alavanca aparecer valendo R$ 4
        # milhões por mês. Número absurdo passa despercebido numa tela; num
        # comitê, não.
        custo_var_km = sum(float(comp.get(k) or 0)
                           for k in ("combustivel", "manutencao", "pneus",
                                     "outros_var"))
        rs_km_agregado = mvb.get("rs_km_agregado") or 0
        ckm_cheio = mvb.get("ckm_cheio") or 0
        cavalos = db.query(
            "SELECT count(*)::int AS n FROM veiculo"
            " WHERE ativoinativo = 1 AND possuimotor = 1 AND tipofrota = 1")[0]["n"]
    except Exception as exc:  # noqa: BLE001
        log.warning("alavanca de frota indisponivel: %s", type(exc).__name__)
        km_prop = cavalos = custo_var_km = rs_km_agregado = ckm_cheio = 0

    if cavalos and km_prop:
        km_cavalo_mes = km_prop / n / cavalos
        # O custo fixo que a ociosidade NÃO cobre: a diferença entre o custo
        # cheio e o marginal é o fixo por km; multiplicada pelos km que
        # DEIXAM de ser rodados, é o tamanho da ociosidade.
        # o FIXO por km é o que sobra do custo cheio depois do que varia e da
        # folha do motorista — é ele que a ociosidade deixa de cobrir
        ckm_marg = float(mvb.get("ckm_marginal") or 0)
        fixo_km = max(0.0, ckm_cheio - ckm_marg)
        # O QUE ESTÁ EM JOGO É O FIXO QUE A FROTA JÁ CARREGA, não uma
        # multiplicação por quilômetros que não existem. A primeira versão
        # fazia `fixo_km × km_que_faltam` e chegava a R$ 4,85 milhões/mês —
        # aritmética solta: aquele dinheiro não existe para ser economizado.
        # O número honesto é o custo fixo que os 81 cavalos consomem hoje,
        # rodando um terço do que deveriam.
        fixo_mes = fixo_km * (km_prop / n)
        alavancas.append({
            "chave": "ociosidade",
            "titulo": "Frota própria parada",
            "valor_mes": fixo_mes,
            "pct_receita": None,
            "certeza": "medido",
            "o_que_e": (
                "%d cavalos próprios rodando %s km por mês cada. A referência "
                "do setor para lotação é de 8 a 10 mil. Com essa ociosidade o "
                "custo fixo se espalha por quilômetro nenhum, e o custo cheio "
                "chega a %s/km."
                % (cavalos, _num(km_cavalo_mes), _brl(ckm_cheio, 2))),
            "o_que_fazer": (
                "Duas saídas e nenhuma terceira: realocar para a frota própria "
                "a carga que hoje vai para agregado, ou reduzir a frota. "
                "Manter cavalo parado é pagar custo fixo para não rodar."),
            "fonte": "Make-vs-Buy · km medido do ERP × cadastro de veículos",
        })

    # ------------------------------------------------------- make vs buy
    if custo_var_km and rs_km_agregado:
        dif = custo_var_km - rs_km_agregado
        alavancas.append({
            "chave": "make_vs_buy",
            "titulo": "Próprio × agregado",
            "valor_mes": abs(dif) * (km_prop / n) if dif > 0 else 0.0,
            "pct_receita": None,
            # A RESSALVA É PARTE DO NÚMERO, não uma nota de rodapé.
            "certeza": "confirmar",
            "o_que_e": (
                "Só o custo variável do caminhão próprio (combustível, "
                "manutenção e pneus) é %s/km. Pagamos %s/km ao agregado — e "
                "esse valor já inclui o caminhão, o motorista e o lucro dele."
                % (_brl(custo_var_km, 2), _brl(rs_km_agregado, 2))),
            "o_que_fazer": (
                "ANTES de decidir: confirmar se o R$/km pago ao agregado está "
                "líquido do combustível que a empresa adianta e recupera "
                "depois. Se estiver, a comparação muda de tamanho. É pergunta "
                "para o Suprimentos, não para o sistema."),
            "fonte": "Make-vs-Buy · CKM da casa × acerto de agregado",
        })

    # ------------------------------------------- o que mais cresceu no custo
    metade = len(meses) // 2
    rec_l = linhas.get("RECEITA LIQUIDA") or []
    cresc_receita = 0.0
    if metade and rec_l and sum(rec_l[:metade]):
        cresc_receita = (sum(rec_l[metade:]) - sum(rec_l[:metade])) / abs(sum(rec_l[:metade]))
    if metade:
        crescimentos = []
        for nome, vals in ag.items():
            prim, ult = sum(vals[:metade]), sum(vals[metade:])
            # IMPOSTO NÃO É ALAVANCA: ele cresce com a receita, e a receita
            # cresceu 17% no período. Deixá-lo na lista faria a tela mandar
            # atacar justamente o efeito de estar vendendo mais.
            if "IMPOSTO" in nome.upper() or "CONTRIBUIC" in nome.upper():
                continue
            if prim >= 0 or abs(prim) < 200000:
                continue
            # CRESCER COM A RECEITA NÃO É PROBLEMA. O frete agregado subiu
            # 33% enquanto a receita subiu 17% — o que interessa é o EXCESSO
            # sobre o crescimento da receita, não o crescimento bruto. Sem
            # isso a tela mandaria atacar o efeito de estar vendendo mais.
            esperado = prim * (1 + cresc_receita)
            delta_mes = (ult - esperado) / (len(meses) - metade)
            if delta_mes < -20000:      # ficou mais caro do que a receita explica
                crescimentos.append((nome, abs(delta_mes), prim, ult))
        crescimentos.sort(key=lambda x: -x[1])
        for nome, delta, prim, ult in crescimentos[:3]:
            alavancas.append({
                "chave": "cresceu:" + nome,
                "titulo": nome,
                "valor_mes": delta,
                "pct_receita": None,
                "certeza": "medido",
                "o_que_e": (
                    "Ficou %s por mês mais caro do que o crescimento da "
                    "receita (%s no período) explica." % (_brl(delta), _pct(cresc_receita))),
                "o_que_fazer": (
                    "Abrir por centro de custo e por lançamento na aba "
                    "Resultado — a linha diz QUANTO, o drill-down diz de quem."),
                "fonte": "DRE · agrupador gerencial",
            })

    alavancas.sort(key=lambda a: -(a["valor_mes"] or 0))

    # ------------------------------------------------------- o que NÃO é
    nao_e = []
    try:
        km = queries.get_analise_km(None, de_iso, ate_iso)["kpis"]
        vazio = km.get("retorno_vazio") or 0
        if vazio and vazio <= VAZIO_LIMITE:
            nao_e.append({
                "titulo": "Retorno vazio",
                # `%` LITERAL DENTRO DE STRING DE FORMATAÇÃO. O "20%" cru
                # fazia TypeError e o bloco inteiro caía no except — o
                # retorno vazio simplesmente não aparecia, sem erro na tela.
                # Mesma armadilha do `%` em SQL, um andar acima.
                "texto": ("Está em %s, abaixo do limite de 20%% que a casa "
                          "usa para lotação. Não é aqui." % _pct(vazio))})
    except Exception as exc:  # noqa: BLE001
        log.warning("nao consegui medir o retorno vazio: %s", type(exc).__name__)
    rec = linhas.get("RECEITA BRUTA") or []
    if len(rec) >= 2 and rec[0]:
        cresc = (rec[-1] - rec[0]) / abs(rec[0])
        if cresc > 0.05:
            nao_e.append({
                "titulo": "Receita",
                "texto": "Cresceu %s do primeiro ao último mês do período. O "
                         "problema não é vender pouco." % _pct(cresc)})

    return {
        "comp_de": comp_de, "comp_ate": comp_ate, "meses": len(meses),
        "resultado_mes": resultado_mes,
        "receita_mes": receita_mes,
        "falta_por_mes": abs(resultado_mes) if resultado_mes < 0 else 0.0,
        "alavancas": alavancas,
        "nao_e": nao_e,
        "fonte": "DRE Gerencial · Make-vs-Buy · Análise de KM — tudo medido "
                 "no período escolhido, nada é meta nem projeção",
    }

# ----------------------------------------------------------------------------
# PANORAMA CONTA A CONTA — o que melhorou, o que piorou, o que só oscila.
#
# A pergunta é "onde ser cirúrgico", e ela tem uma armadilha: conta que cresce
# junto com a receita NÃO piorou — ela acompanhou o volume. Comparar reais
# contra reais faria a lista mandar atacar o efeito de estar vendendo mais,
# que foi exatamente o erro que a lista de alavancas já corrigiu um andar
# acima.
#
# Por isso a régua é PERCENTUAL DA RECEITA LÍQUIDA do próprio mês. "Piorou"
# quer dizer FICOU MAIS CARO POR REAL FATURADO. O valor volta para reais no
# fim (multiplicado pela receita do último mês) porque ninguém decide sobre
# ponto percentual — mas a comparação acontece em percentual.
#
# E há um TERCEIRO grupo, que é o que torna a tela cirúrgica de verdade: as
# contas que OSCILAM. Uma conta que salta de mês para mês não é alvo — é
# medição instável (provisão que entra e sai, competência que atrasa), e
# atacá-la é perseguir ruído. Ela sai da lista de ataque e vai para a de
# "olhar antes de concluir".

#: Abaixo disto a variação não paga a conversa, por maior que seja o
#: percentual. Ranking por percentual sem piso de materialidade mente.
PISO_MATERIALIDADE = 15000.0

#: Coeficiente de variação (desvio ÷ média) acima do qual a conta é
#: instável demais para virar alvo. 0,5 = o desvio é metade da média.
CV_INSTAVEL = 0.5


def _desvio(vals: list[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5


def panorama(comp_de: str, comp_ate: str, nivel: str = "conta") -> dict:
    """Conta a conta: o que melhorou, o que piorou e o que só oscila.

    `nivel` é "conta" (cirúrgico) ou "agrupador" (panorâmico).
    """
    dre = queries.get_dre(comp_de, comp_ate)
    meses = dre["meses"]
    n = len(meses)
    # Recusa carrega a MESMA forma do sucesso: quem consome não deve precisar
    # saber que existem dois formatos de resposta para não quebrar.
    def _recusa(motivo: str) -> dict:
        return {"meses": meses, "erro": motivo, "nivel": nivel,
                "piorou": [], "melhorou": [], "oscila": [],
                "piso": PISO_MATERIALIDADE, "cv_instavel": CV_INSTAVEL}

    if n < 2:
        return _recusa("o panorama precisa de ao menos dois meses para comparar")

    receita = {}
    for l in dre["linhas"]:
        if l["rotulo"] == "RECEITA LIQUIDA":
            receita = {m: l["meses"].get(m, 0.0) for m in meses}
    if not receita or not any(receita.values()):
        return _recusa("sem receita líquida no período")

    itens: dict = {}
    for l in dre["linhas"]:
        for a in (l.get("detalhe") or []):
            if nivel == "agrupador":
                itens[a["agrupador"]] = {
                    "nome": a["agrupador"], "linha": l["rotulo"],
                    "meses": [a["meses"].get(m, 0.0) for m in meses]}
                continue
            for c in (a.get("contas") or []):
                chave = "%s|%s" % (c["grupo"], c["reduzido"])
                itens[chave] = {
                    "nome": c["conta"], "reduzido": c["reduzido"],
                    "grupo": c["grupo"], "linha": l["rotulo"],
                    "agrupador": a["agrupador"],
                    "estrutural": c.get("estrutural") or "",
                    "meses": [c["meses"].get(m, 0.0) for m in meses]}

    ult_mes = meses[-1]
    rec_ult = receita.get(ult_mes) or 0.0
    piorou, melhorou, oscila = [], [], []
    for x in itens.values():
        vals = x["meses"]
        # DUAS RÉGUAS, e misturá-las foi o primeiro erro deste código.
        #
        # CUSTO se mede como % da receita líquida: é assim que "ficou mais
        # caro por real faturado" se separa de "cresceu porque vendemos mais".
        #
        # RECEITA medida como % da receita é CIRCULAR — dizia que a receita de
        # agregados "melhorou R$ 432 mil" quando o que mudou foi o MIX (81%
        # para 85% do total). Receita se compara com ela mesma, em reais.
        #
        # E a conta 3 tem que ENTRAR dinheiro para valer a régua de receita:
        # "(-) ICMS SOBRE RECEITA DE TRANSPORTE" também é estrutural 3, e
        # medido em reais contra a própria média ele aparecia como a quarta
        # maior PIORA do mês (-R$ 75.390) por ter recolhido mais imposto sobre
        # um faturamento maior. Dedução de receita se comporta como custo: a
        # pergunta que decide alguma coisa é quanto da receita ela leva.
        e_receita = sum(vals) > 0 and (
            str(x.get("estrutural") or "").startswith("3")
            or nivel == "agrupador")
        # o mês só entra se houve receita nele — dividir por zero inventaria
        # percentual infinito no mês em que a competência ainda não fechou
        if e_receita:
            antes = vals[:-1]
            media = sum(antes) / len(antes) if antes else 0.0
            delta_rs = vals[-1] - media
            pct_ult = pct_med = delta_pct = None
        else:
            pcts = [(vals[i] / receita[meses[i]]) if receita.get(meses[i])
                    else None for i in range(n)]
            antes_p = [v for v in pcts[:-1] if v is not None]
            if pcts[-1] is None or not antes_p:
                continue
            media_p = sum(antes_p) / len(antes_p)
            pct_ult, pct_med = pcts[-1], media_p
            delta_pct = pcts[-1] - media_p
            # em reais do ÚLTIMO mês: é a linguagem em que se decide
            delta_rs = delta_pct * rec_ult
            antes = vals[:-1]
            media = sum(antes) / len(antes) if antes else 0.0
        cv = (_desvio(antes) / abs(media)) if media else 0.0
        item = {**x, "receita": e_receita, "pct_ultimo": pct_ult,
                "pct_medio": pct_med, "delta_pct": delta_pct,
                "delta_rs": delta_rs, "cv": cv, "valor_ultimo": vals[-1],
                "media_anterior": media,
                "regua": "reais, contra a própria média" if e_receita
                else "% da receita líquida do mês"}
        if abs(delta_rs) < PISO_MATERIALIDADE:
            continue
        if cv > CV_INSTAVEL:
            oscila.append(item)
        elif delta_rs < 0:          # custo é negativo: mais negativo = piorou
            piorou.append(item)
        else:
            melhorou.append(item)

    piorou.sort(key=lambda x: x["delta_rs"])
    melhorou.sort(key=lambda x: -x["delta_rs"])
    oscila.sort(key=lambda x: -x["cv"])
    return {
        "meses": meses, "mes_referencia": ult_mes, "nivel": nivel,
        "receita_ultimo": rec_ult,
        "piorou": piorou[:12], "melhorou": melhorou[:12], "oscila": oscila[:8],
        "piso": PISO_MATERIALIDADE, "cv_instavel": CV_INSTAVEL,
        "fonte": "DRE Gerencial · cada conta medida como % da receita líquida "
                 "do próprio mês, para volume não virar piora",
    }


def _brl(v, casas: int = 0) -> str:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "R$ 0"
    i, d = ("%%.%df" % casas % abs(n)).split(".") if casas else (
        "%.0f" % abs(n), "")
    i = "{:,}".format(int(i)).replace(",", ".")
    return "R$ " + ("-" if n < 0 else "") + i + ("," + d if d else "")


def _pct(v) -> str:
    return ("%.1f" % (100 * (v or 0))).replace(".", ",") + "%"


def _num(v) -> str:
    return "{:,}".format(int(v or 0)).replace(",", ".")