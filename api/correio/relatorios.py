"""Catálogo dos relatórios que podem ser agendados por e-mail.

Cada relatório é uma função sem argumentos que devolve
`{"assunto": str, "html": str, "texto": str, "vazio": bool}`.

`vazio=True` significa "não havia nada a dizer hoje". Quem envia decide o que
fazer com isso — e a decisão padrão é NÃO MANDAR: relatório que chega todo dia
dizendo "nada a relatar" ensina o destinatário a arquivar sem ler, e no dia em
que tiver conteúdo ele será arquivado junto. O contrário (silêncio quando há
problema) é que não pode acontecer, e é por isso que a regra é por relatório e
não global.

NENHUM RELATÓRIO LEVANTA EXCEÇÃO. Uma consulta que falha vira um bloco de
aviso dentro do próprio e-mail. O agendamento roda sem ninguém olhando: um
erro que derruba a rotina some do mundo, enquanto um e-mail que chega dizendo
"não consegui ler o ERP" é lido por uma pessoa na manhã seguinte.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from api.correio import painel as p
from api.gestao.comum import ROTULO_PRIORIDADE

log = logging.getLogger("cortex.correio.relatorios")


def _dia_br(iso) -> str:
    t = str(iso or "")[:10].split("-")
    return f"{t[2]}/{t[1]}" if len(t) == 3 else str(iso or "—")


def _data_br(iso) -> str:
    t = str(iso or "")[:10].split("-")
    return f"{t[2]}/{t[1]}/{t[0]}" if len(t) == 3 else "—"



def _pct(v) -> str:
    """Percentual em pt-BR, ou um travessão quando não há base."""
    if v is None:
        return "—"
    return f"{float(v):.1f}".replace(".", ",") + "%"


def _falhou(titulo: str, exc: Exception) -> dict:
    txt = (f"{titulo}\n\nO CÓRTEX não conseguiu montar este relatório:\n"
           f"{type(exc).__name__}: {str(exc)[:300]}\n\n"
           "O painel continua no ar — só a geração automática falhou.")
    html = p.documento(titulo, [
        p.paragrafo("O CÓRTEX não conseguiu montar este relatório.",
                    destaque=True),
        p.paragrafo(f"{type(exc).__name__}: {str(exc)[:300]}"),
        p.paragrafo("O painel continua no ar — o que falhou foi a geração "
                    "automática. Se isto se repetir amanhã, vale olhar."),
    ], subtitulo="falha na geração", origem="—")
    return {"assunto": f"[CÓRTEX] {titulo} — falha ao gerar",
            "html": html, "texto": txt, "vazio": False}


# --------------------------------------------------------------- contrapartida

def contrapartida() -> dict:
    """Despacho do dia do CT-e de contrapartida.

    Responde a pergunta da tela na ordem em que ela é feita: quanto tem para
    sair hoje, o que está travado, e o que a rotina automática já fez.
    """
    titulo = "CT-e de Contrapartida — despacho do dia"
    try:
        from api.contrapartida import emissao, lote, servico

        hoje = date.today()
        amb = emissao.ambiente_ativo()
        producao = amb == emissao.PRODUCAO
        fila = lote.resumo_fila(hoje.isoformat(),
                                (hoje + timedelta(days=1)).isoformat(), amb)
        est = lote.estado()
        aut = est.get("automacao") or {}
        tx = servico._transmissoes()

        a_emitir = int(fila.get("a_emitir") or 0)
        travados = (int(fila.get("sem_agregado_pronto") or 0)
                    + int(fila.get("sem_cadastro") or 0))
        quarentena = int(fila.get("em_quarentena") or 0)

        blocos = [
            p.kpis([
                {"rotulo": "A emitir hoje", "valor": p.inteiro(a_emitir),
                 "estado": "warn" if a_emitir else "ok",
                 "sub": f"de {p.inteiro(fila.get('ctes_no_periodo'))} CT-e de "
                        "agregado PJ emitidos hoje"},
                {"rotulo": "Já com contrapartida",
                 "valor": p.inteiro(fila.get("ja_emitidos")), "estado": "ok",
                 "sub": "documento autorizado neste ambiente"},
                {"rotulo": "Travados", "valor": p.inteiro(travados),
                 "estado": "bad" if travados else "ok",
                 "sub": "sem certificado, procuração ou inscrição estadual"},
                {"rotulo": "Em quarentena", "valor": p.inteiro(quarentena),
                 "estado": "warn" if quarentena else "ok",
                 "sub": "recusados três vezes com o mesmo retorno"},
            ]),
            p.secao("Emissão automática"),
        ]

        if not aut.get("ativa"):
            blocos.append(p.paragrafo(
                "A rotina automática está DESLIGADA — nada sai sozinho. A fila "
                "acima só anda com alguém disparando a emissão pelo painel.",
                destaque=True))
        else:
            ult = aut.get("ultima_execucao")
            blocos.append(p.tabela(
                ["", ""],
                [["Ambiente", "PRODUÇÃO — documento com valor fiscal"
                  if producao else "Homologação — sem valor fiscal"],
                 ["Intervalo", f"{aut.get('intervalo_min')} min"],
                 ["Última passagem",
                  datetime.fromisoformat(ult).strftime("%d/%m/%Y %H:%M:%S")
                  if ult else "ainda não rodou"]]))

        blocos.append(p.secao("Retorno da SEFAZ", "registro completo"))
        # DENOMINADOR = AVALIADAS. `documentos` inclui a recusa que so existe
        # em homologacao; usa-la aqui repetiria no e-mail o numero enganoso
        # que a tela ja tinha deixado de mostrar.
        docs = int(tx.get("avaliadas") or tx.get("documentos") or 0)
        esperadas = int(tx.get("esperadas_homologacao") or 0)
        ok_n = int(tx.get("autorizadas") or 0)
        taxa = tx.get("taxa_ok")
        blocos.append(p.kpis([
            {"rotulo": "Autorizadas", "valor": f"{ok_n} de {docs}",
             "estado": "ok" if taxa and taxa >= 70 else "warn",
             # virgula decimal: o e-mail sai em pt-BR como o resto do painel
             "sub": ((f"{taxa:.1f}".replace(".", ",") + "% de retorno OK"
                      + (f" · {esperadas} recusas só de homologação fora "
                         "da conta" if esperadas else ""))
                     if taxa is not None else "nenhuma transmissão ainda")},
            {"rotulo": "Em produção",
             "valor": f"{tx.get('producao_autorizadas', 0)} de "
                      f"{tx.get('producao', 0)}",
             "estado": "ok",
             "sub": "autorizadas de transmitidas — só estas valem para o fisco"},
        ]))

        # ---- ritmo dos ultimos dias -------------------------------------
        # O numero do dia sozinho nao diz se a rotina esta indo bem: 12
        # autorizados e otimo depois de 3 e ruim depois de 40. A serie responde
        # isso em duas linhas, e e a pergunta de quem acompanha um periodo de
        # teste.
        serie = (tx.get("por_dia") or [])[-7:]
        if serie:
            blocos.append(p.secao("Autorizados por dia", "últimos 7 dias"))
            def _ok(d):
                return int(d.get("homologacao_ok") or 0) + int(d.get("producao_ok") or 0)

            def _nao(d):
                return int(d.get("homologacao_nao") or 0) + int(d.get("producao_nao") or 0)

            blocos.append(p.barras([
                {"rotulo": _dia_br(d.get("dia")), "valor": _ok(d), "cor": p.VERDE}
                for d in serie]))
            recusas = [{"rotulo": _dia_br(d.get("dia")), "valor": _nao(d),
                        "cor": p.VERMELHO} for d in serie]
            if any(r["valor"] for r in recusas):
                blocos.append(p.secao("Recusados por dia"))
                blocos.append(p.barras(recusas))

        # ---- o que a SEFAZ respondeu ------------------------------------
        # A lista das ultimas trinta transmissoes nao responde "quais erros
        # aconteceram": responde "o que passou por aqui agora". Agrupado por
        # codigo, o periodo de teste vira uma lista de coisas a corrigir.
        codigos = [c for c in (tx.get("por_cstat") or []) if not c["autorizado"]]
        if codigos:
            blocos.append(p.secao("Recusas por código",
                                  "sobre todo o registro, não só as últimas"))
            blocos.append(p.tabela(
                ["Código", "Vezes", "Motivo"],
                [[p.chip(c["cstat"], "bad"), c["n"], c["xmotivo"]]
                 for c in codigos[:6]], alinha_dir=(1,)))

        # ---- quem ainda trava a fila ------------------------------------
        try:
            val = servico.validacao_completa(90)
            porc = val.get("por_categoria") or {}
            if porc:
                blocos.append(p.secao("O que trava a fila",
                                      f"{val.get('agregados')} agregados ativos"))
                blocos.append(p.barras([
                    {"rotulo": "Certificado", "valor": porc.get("certificado", 0),
                     "cor": p.VERMELHO},
                    {"rotulo": "Cadastro no ERP", "valor": porc.get("cadastro", 0),
                     "cor": p.AMBAR},
                    {"rotulo": "Não emite CT-e", "valor": porc.get("natureza", 0),
                     "cor": p.CINZA},
                ], unidade="agregados"))
                blocos.append(p.paragrafo(
                    f"{val.get('aprovados')} de {val.get('agregados')} passam em "
                    "tudo e podem emitir hoje. O resto está listado no "
                    "validador, com a ação de cada um."))
        except Exception as exc:  # noqa: BLE001
            log.warning("validacao no relatorio indisponivel: %s", exc)

        # ---- certificados a vencer --------------------------------------
        try:
            cert = (servico.get_contrapartida(hoje.isoformat(), hoje.isoformat())
                    .get("certificados") or {})
            itens = [c for c in (cert.get("itens") or [])
                     if c.get("situacao") in ("vencido", "critico", "alerta")]
            if itens:
                blocos.append(p.secao("Certificados vencidos ou vencendo"))
                blocos.append(p.tabela(
                    ["Agregado", "Validade", "Situação"],
                    [[c.get("nome") or c.get("documento"),
                      _data_br(c.get("valida_ate")),
                      p.chip(c.get("texto") or c.get("situacao"),
                             "bad" if c.get("situacao") == "vencido" else "warn")]
                     for c in itens[:8]]))
        except Exception as exc:  # noqa: BLE001
            log.warning("certificados no relatorio indisponiveis: %s", exc)

        avisos = [a for a in (servico.get_contrapartida(
            hoje.isoformat(), hoje.isoformat()).get("avisos") or [])][:3]
        if avisos:
            blocos.append(p.secao("Ler com atenção"))
            for a in avisos:
                blocos.append(p.paragrafo(a))

        # TEXTO PURO: e o que aparece na previa da caixa de entrada. Repete os
        # numeros que decidem, nao o relatorio inteiro.
        texto = (
            f"CT-e de Contrapartida — {hoje.strftime('%d/%m/%Y')}\n\n"
            f"A emitir hoje ....... {a_emitir}\n"
            f"Ja com contrapartida  {fila.get('ja_emitidos')}\n"
            f"Travados ............ {travados}\n"
            f"Em quarentena ....... {quarentena}\n"
            f"Ambiente ............ {'PRODUCAO' if producao else 'homologacao'}\n"
            f"Automacao ........... {'ligada' if aut.get('ativa') else 'DESLIGADA'}\n")

        return {
            "assunto": (f"[CÓRTEX] Contrapartida {hoje.strftime('%d/%m')} — "
                        f"{a_emitir} a emitir"
                        + (" · PRODUÇÃO" if producao else "")),
            "html": p.documento(
                titulo, blocos,
                subtitulo=hoje.strftime("%d/%m/%Y")
                + (" · PRODUÇÃO" if producao else " · homologação"),
                origem="conhecimento × veiculo × cadastro (AVA) + registro local"),
            "texto": texto,
            # Fila zerada E nada travado e o unico caso em que nao ha o que
            # dizer. Travado nao e "vazio": e trabalho parado.
            "vazio": not a_emitir and not travados and not quarentena,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("relatorio de contrapartida falhou: %s", exc)
        return _falhou(titulo, exc)


# ---------------------------------------------------------------- digest geral

def digest() -> dict:
    """Alertas do painel — o que exige ação hoje, por severidade."""
    titulo = "Alertas do painel"
    try:
        from api import alertas

        itens = alertas.build_alertas() or []
        criticos = [a for a in itens if str(a.get("nivel")) == "critico"]
        atencao = [a for a in itens if str(a.get("nivel")) == "atencao"]

        blocos = [p.kpis([
            {"rotulo": "Críticos", "valor": p.inteiro(len(criticos)),
             "estado": "bad" if criticos else "ok",
             "sub": "exigem ação hoje"},
            {"rotulo": "Atenção", "valor": p.inteiro(len(atencao)),
             "estado": "warn" if atencao else "ok",
             "sub": "acompanhar"},
        ])]
        for rotulo, grupo, estado in (("Críticos", criticos, "bad"),
                                      ("Atenção", atencao, "warn")):
            if not grupo:
                continue
            blocos.append(p.secao(rotulo, f"{len(grupo)} item(ns)"))
            blocos.append(p.tabela(
                ["", "Situação"],
                [[p.chip(str(a.get("titulo") or "")[:38], estado),
                  str(a.get("texto") or a.get("detalhe") or "")[:180]]
                 for a in grupo[:12]]))
        if not itens:
            blocos.append(p.paragrafo(
                "Nenhum alerta aberto. Os indicadores acompanhados estão "
                "dentro do esperado."))

        texto = alertas.digest_texto()
        return {
            "assunto": (f"[CÓRTEX] {len(criticos)} crítico(s) e "
                        f"{len(atencao)} em atenção"),
            "html": p.documento(titulo, blocos,
                                subtitulo=date.today().strftime("%d/%m/%Y"),
                                origem="alertas do painel"),
            "texto": texto,
            "vazio": not itens,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("digest falhou: %s", exc)
        return _falhou(titulo, exc)


# ------------------------------------------------------------------- gestão

def _rot_prazo(a: dict) -> tuple:
    """Como o prazo aparece na linha, e com que cor.

    Dizer só a data faz "05/09" e "05/07" parecerem a mesma coisa numa lista
    lida de manhã. O tempo decorrido é o que prioriza — foi a lição da tela de
    Vagas, onde a data sozinha escondia uma vaga congelada há 376 dias.
    """
    if a.get("atrasada"):
        d = a["dias_atraso"]
        return f"{_data_br(a['prazo'])} · {d} {'dia' if d == 1 else 'dias'}", "bad"
    d = a.get("dias_para_prazo")
    if d == 0:
        return f"{_data_br(a['prazo'])} · hoje", "warn"
    if d is not None and d <= 7:
        return f"{_data_br(a['prazo'])} · em {d} {'dia' if d == 1 else 'dias'}", "warn"
    return _data_br(a.get("prazo")), "neutro"


def acoes_pendentes() -> dict:
    """Planos de ação — o que venceu e o que vence esta semana.

    É o consolidado da DIRETORIA, não a lista de cada um: quem cobra precisa
    ver a fila inteira ordenada por atraso, e o responsável aparece em coluna.
    """
    titulo = "Planos de ação — pendências"
    try:
        from api.gestao import acoes as ga
        from api.gestao import painel as gp

        r = gp.resumo()
        atrasadas = [a for a in ga.listar(atrasadas=True, limite=25)]
        vencendo = [a for a in ga.listar(status="abertas", limite=200)
                    if a["vence_em_7"]][:15]
        paradas = gp.paradas(dias=21, limite=8)

        # O KPI de abertas traz a QUEBRA: "84 abertas" não diz se são 84 em dia
        # ou 60 atrasadas, e é a quebra que decide se alguém precisa agir hoje.
        blocos = [p.kpis([
            {"rotulo": "Atrasadas", "valor": p.inteiro(r["atrasadas"]),
             "estado": "bad" if r["atrasadas"] else "ok",
             "sub": (f"de {r['abertas']} abertas"
                     if r["abertas"] else "nenhuma ação aberta")},
            {"rotulo": "Vencem em 7 dias", "valor": p.inteiro(r["vence_7"]),
             "estado": "warn" if r["vence_7"] else "ok",
             "sub": "entram na semana"},
            {"rotulo": "Em dia", "valor": p.inteiro(r["em_dia"]),
             "estado": "ok", "sub": "abertas dentro do prazo"},
            {"rotulo": "Concluídas no mês", "valor": p.inteiro(r["concluidas_mes"]),
             "estado": "ok",
             # Sem base concluída o número não existe — "0 dias" em verde faria
             # parecer velocidade perfeita onde não houve conclusão nenhuma.
             "sub": (f"ciclo mediano {r['ciclo_mediano']:.0f} dias"
                     if r.get("ciclo_mediano") is not None
                     else "sem base para tempo de ciclo")},
        ])]

        if atrasadas:
            total = r["atrasadas"]
            hint = (f"{len(atrasadas)} de {total}" if total > len(atrasadas)
                    else f"{total} ação(ões)")
            blocos.append(p.secao("Atrasadas", hint))
            blocos.append(p.tabela(
                ["Prazo", "Ação", "Responsável", "Prioridade"],
                [[p.chip(*_rot_prazo(a)),
                  str(a["o_que"])[:70],
                  str(a["responsavel"] or "—")[:26],
                  p.chip(ROTULO_PRIORIDADE.get(a["prioridade"], a["prioridade"]),
                         "bad" if a["prioridade"] in ("alta", "critica")
                         else "neutro")]
                 for a in atrasadas]))

        if vencendo:
            blocos.append(p.secao("Vencem nos próximos 7 dias",
                                  f"{len(vencendo)} ação(ões)"))
            blocos.append(p.tabela(
                ["Prazo", "Ação", "Responsável", "Avanço"],
                [[p.chip(*_rot_prazo(a)),
                  str(a["o_que"])[:70],
                  str(a["responsavel"] or "—")[:26],
                  f"{a['percentual']}%"]
                 for a in vencendo]))

        if paradas:
            # O alerta que o status NÃO dá: 'em andamento' há dois meses sem
            # ninguém escrever nada não está em andamento, está esquecida.
            blocos.append(p.secao("Sem andamento há mais de 21 dias",
                                  f"{len(paradas)} ação(ões)"))
            blocos.append(p.tabela(
                ["Parada há", "Ação", "Responsável"],
                [[p.chip(f"{a['parada_dias']} dias", "warn"),
                  str(a["o_que"])[:70],
                  str(a["responsavel"] or "—")[:26]]
                 for a in paradas]))

        if not (atrasadas or vencendo or paradas):
            blocos.append(p.paragrafo(
                "Nenhuma ação atrasada, vencendo nesta semana ou parada. "
                "O plano está em dia."))

        linhas = [titulo, "",
                  f"Atrasadas: {r['atrasadas']} (de {r['abertas']} abertas)",
                  f"Vencem em 7 dias: {r['vence_7']}",
                  f"Concluídas no mês: {r['concluidas_mes']}", ""]
        for a in atrasadas[:15]:
            linhas.append(f"  [{a['dias_atraso']}d] {a['o_que'][:60]} "
                          f"— {a['responsavel']}")
        texto = "\n".join(linhas)

        return {
            "assunto": (f"[CÓRTEX] {r['atrasadas']} ação(ões) atrasada(s) e "
                        f"{r['vence_7']} vencendo"),
            "html": p.documento(titulo, blocos,
                                subtitulo=date.today().strftime("%d/%m/%Y"),
                                origem="ges_acoes · banco local"),
            "texto": texto,
            # Nada pendente NÃO é silêncio: "o plano está em dia" é justamente
            # a notícia que a diretoria quer receber, e sumir com ela faria
            # duvidar do envio. Mesma escolha do digest de alertas.
            "vazio": False,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("acoes_pendentes falhou: %s", exc)
        return _falhou(titulo, exc)



def ponto_do_dia() -> dict:
    """O ponto do ÚLTIMO DIA FECHADO, para o RH ler de manhã.

    POR QUE ESTE E-MAIL EXISTE
    ==========================
    O Globus só enxerga o ponto depois que alguém importa o AFD à mão — mediana
    de 3 dias, máximo de 18. Quem não bateu ontem aparece lá na semana que vem,
    quando não há mais o que perguntar. Pela API do Ponto Certificado a batida
    chega em 12 segundos, e a pergunta "alguém não apareceu?" passa a ter
    resposta na manhã seguinte, que é quando ela ainda serve para alguma coisa.

    ONTEM, E NÃO HOJE. Às 7h da manhã o dia de hoje tem meia dúzia de batidas e
    ninguém faltou ainda — um relatório do dia em curso seria sempre alarmante
    e sempre errado.

    NÃO É UMA LISTA DE FALTAS, e o texto diz isso em todo lugar onde pode ser
    lido depressa. Sem batida pode ser atestado que ninguém lançou, folga
    combinada, home office ou simplesmente esquecimento de bater. Quem
    transforma isso em falta é o RH, com a lista na mão — e é essa a diferença
    entre um instrumento e uma acusação automática.

    VAZIO AQUI É NOTÍCIA BOA E VAI ASSIM MESMO (`pular_vazio: False`): "as 79
    pessoas esperadas bateram" é exatamente o que o RH quer receber, e sumir
    nesse dia faria o destinatário duvidar do envio no dia seguinte.
    """
    from datetime import timedelta

    titulo = "Ponto — o dia de ontem"
    try:
        from api import frequencia
        from api.pontocertificado import painel as pc

        ontem = (date.today() - timedelta(days=1)).isoformat()
        dia = pc.do_dia(ontem)
        k = dia.get("kpis") or {}
        aus = frequencia.ausentes_do_dia(ontem)
        sem = aus.get("ausentes") or []
        atipico = bool(aus.get("atipico"))

        blocos = [p.kpis([
            {"rotulo": "Bateram", "valor": p.inteiro(k.get("pessoas")),
             "estado": "ok", "sub": f"{p.inteiro(k.get('batidas'))} batidas"},
            {"rotulo": "Sem batida", "valor": p.inteiro(len(sem)),
             "estado": "warn" if sem and not atipico else "ok",
             "sub": f"de {p.inteiro(aus.get('esperados'))} esperadas"},
            {"rotulo": "Fora de cerca", "valor": p.inteiro(k.get("fora")),
             "estado": "warn" if (k.get("fora") or 0) else "ok",
             "sub": "veja a distância antes de concluir"},
            {"rotulo": "Sem GPS", "valor": p.inteiro(k.get("sem_coordenada")),
             "estado": "neutro", "sub": "não é infração"},
        ])]

        if atipico:
            # Metade do quadro fora no mesmo dia não é ausência: é feriado,
            # parada ou coleta que não rodou. Nomear todo mundo seria acusar a
            # casa inteira de faltar.
            blocos.append(p.paragrafo(
                f"{len(sem)} das {aus.get('esperados')} pessoas esperadas não "
                "bateram. Metade do quadro ausente junto não é falta: é "
                "feriado, parada coletiva ou a própria coleta que não rodou. "
                "A lista de nomes fica de fora de propósito — se o dia era de "
                "expediente, o primeiro lugar a olhar é a coleta.",
                destaque=True))
        elif sem:
            como = ("o Globus já importou este dia e registra presença para "
                    "elas" if aus.get("modo") == "erp" else
                    f"o Globus enxerga até {_dia_br(aus.get('erp_ate'))}, "
                    f"então o esperado veio de quem trabalhou em pelo menos "
                    f"{aus.get('minimo_dias')} dos últimos dias iguais da semana")
            blocos.append(p.secao(
                "Sem batida", f"{len(sem)} de {aus.get('esperados')} esperadas"))
            blocos.append(p.paragrafo(
                "NÃO é uma lista de faltas: pode ser atestado ainda não "
                "lançado, folga combinada, home office ou esquecimento de "
                f"bater. Quem esteve de férias saiu da conta ({aus.get('ferias')} "
                f"pessoa(s)). Como se soube: {como}."))
            blocos.append(p.tabela(
                ["Pessoa", "Filial", "Função", "O que o Globus registra"],
                [[str(x.get("nome") or x.get("chapa") or "")[:38],
                  str(x.get("filial") or "")[:22],
                  # 22 cortava "APRENDIZ ( AUX ESCRITORIO )" no meio do
                  # parenteses, e cargo pela metade se le como erro de sistema.
                  str(x.get("funcao") or "")[:30],
                  str(x.get("registro_erp") or "— ainda não importado")[:24]]
                 for x in sem[:40]]))
        else:
            blocos.append(p.paragrafo(
                f"Todas as {aus.get('esperados')} pessoas esperadas bateram o "
                "ponto. Nada a conferir."))

        # DENTRO x FORA, DIA A DIA — com o SEM GPS na mesma barra.
        # A barra inteira e o movimento do dia; os pedacos sao a composicao.
        # O sem GPS entra porque ele e METADE das batidas: uma barra que
        # mostrasse so dentro+fora mentiria sobre o volume do dia, e a fatia
        # cinza e justamente o que decide se a cerca pode virar regra.
        comp = pc.composicao_por_dia(7, ate=ontem)
        if comp.get("total"):
            blocos.append(p.secao("Dentro e fora da cerca",
                                  f"{p.inteiro(comp['total'])} batidas em 7 dias"))
            blocos.append(p.medidor(
                titulo="Dentro da cerca",
                pct=comp.get("pct_dentro"),
                texto=(f"{p.inteiro(comp['dentro'])} de "
                       f"{p.inteiro(comp['com_gps'])} batidas que trouxeram "
                       f"coordenada caíram numa cerca cadastrada"),
                sub=(f"Outras {p.inteiro(comp['sem_coordenada'])} batidas "
                     f"({_pct(comp.get('pct_sem_coordenada'))}) chegaram SEM "
                     "GPS e ficam fora desta conta: elas não caíram dentro nem "
                     "fora — não se sabe. Contá-las como erro derrubaria o "
                     "número pela metade sem ninguém ter feito nada errado."),
                estado=("ok" if (comp.get("pct_dentro") or 0) >= 70
                        else "warn" if (comp.get("pct_dentro") or 0) >= 40
                        else "bad")))
            blocos.append(p.barras_empilhadas(
                [{"rotulo": d["rotulo"],
                  "valores": [d["dentro"], d["fora"], d["sem_coordenada"]],
                  "texto": (f"{d['dentro']}/{d['fora']}/{d['sem_coordenada']}")}
                 for d in comp["serie"]],
                [{"nome": "Dentro", "cor": p.VERDE},
                 {"nome": "Fora", "cor": p.VERMELHO},
                 {"nome": "Sem GPS", "cor": p.CINZA}]))
            blocos.append(p.legenda([("Dentro", p.VERDE), ("Fora", p.VERMELHO),
                                     ("Sem GPS", p.CINZA)]))

        # FORA DE CERCA, DIA A DIA E POR CERCA — e nao o total de ontem.
        # "44 batidas fora de cerca" pode ser tres coisas com providencias
        # opostas, e o que as separa e a DISTANCIA se repetindo: onze pessoas
        # a mil oitocentos e oitenta e poucos metros todo dia sao um local de
        # trabalho sem cerca cadastrada; a mesma gente com a distancia pulando
        # de 2,8 km para 100 km esta em transito, e cerca nenhuma resolve; e
        # quarenta metros e cerca apertada demais.
        ev = pc.fora_por_dia(7, ate=ontem)
        if ev.get("cercas"):
            blocos.append(p.secao(
                "Fora de cerca, por lugar",
                f"{p.inteiro(ev['total'])} batidas em 7 dias"))
            cab = ["Perto de"] + ev["rotulos"] + ["Pessoas", "Distância",
                                                  "Mesmo lugar"]
            linhas_ev = []
            for c in ev["cercas"][:10]:
                d = c.get("distancia_m")
                dist = ("—" if d is None else
                        f"{(d / 1000):.1f} km".replace(".", ",") if d >= 1000
                        else f"{d} m")
                linhas_ev.append(
                    [str(c["cerca"])[:24]]
                    + [(str(n) if n else "·") for n in c["serie"]]
                    + [p.inteiro(c["pessoas"]), dist,
                       # "5/5" e nao "5 de 5 dias": a celula quebrava em tres
                       # linhas e esticava a tabela inteira. O que significa
                       # esta no paragrafo abaixo, uma vez, em vez de em cada
                       # linha.
                       f"{c['dias_no_mesmo_lugar']}/{c['dias_com_movimento']}"])
            blocos.append(p.tabela(cab, linhas_ev,
                                   alinha_dir=tuple(range(1, len(cab)))))
            blocos.append(p.paragrafo(
                # `p.paragrafo` ESCAPA html — as tags sairiam literais no
                # e-mail, e foi o que aconteceu na primeira versao.
                "A coluna Mesmo lugar conta em quantos dos dias com "
                "movimento a distância ficou na mesma faixa (±10%): 5/5 é "
                "todo dia no mesmo ponto. Distância "
                "que se repete todo dia é ENDEREÇO: gente trabalhando num "
                "lugar que não tem cerca cadastrada — dezenas de metros é "
                "cerca apertada, um ou dois quilômetros é um local a "
                "cadastrar. Distância que pula de um dia para o outro é gente "
                "em trânsito, e aí cerca nenhuma resolve."))

        n = len(sem)
        assunto = (f"[CÓRTEX] Ponto de {_dia_br(ontem)} — "
                   + ("dia atípico, confira a coleta" if atipico
                      else f"{n} sem batida" if n
                      else "todos bateram"))
        linhas = [f"Ponto de {_dia_br(ontem)}",
                  f"{k.get('pessoas')} pessoas bateram, {k.get('batidas')} batidas.",
                  f"Sem batida: {n} de {aus.get('esperados')} esperadas."]
        linhas += [f"  - {x.get('nome')} ({x.get('filial')})" for x in sem[:40]]
        return {
            "assunto": assunto,
            "html": p.documento(titulo, blocos,
                                subtitulo=_dia_br(ontem),
                                origem="Ponto Certificado + Globus"),
            "texto": "\n".join(linhas),
            # Nunca vazio: "todos bateram" é a notícia que o RH quer receber.
            "vazio": False,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("ponto_do_dia falhou: %s", exc)
        return _falhou(titulo, exc)


# ------------------------------------------------------------ inadimplência

_SEM = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _mil(v) -> str:
    """Dinheiro na escala de quem lê de relance: R$ 698 mil, R$ 1,08 mi."""
    if v is None:
        return "—"
    v = float(v)
    s = "−" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:
        return f"{s}R$ " + f"{a / 1_000_000:.2f}".replace(".", ",") + " mi"
    if a >= 1_000:
        return f"{s}R$ {a / 1_000:.0f} mil"
    return s + p.brl(a)


def _variacao(v) -> str:
    if v is None:
        return "—"
    if abs(v) < 0.5:
        return "sem mudança"
    return ("+" if v > 0 else "") + _mil(v)


def _dia_sem(iso) -> str:
    d = date.fromisoformat(str(iso)[:10])
    return f"{_SEM[d.weekday()]} {d.strftime('%d/%m')}"


def _idade_min(iso) -> float | None:
    """Minutos desde a leitura do ERP. `resumo()` guarda a última leitura boa
    por duas horas: se o ERP cair na hora do envio, o número sai — e o e-mail
    TEM de dizer de quando ele é."""
    if not iso:
        return None
    try:
        lido = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    agora = datetime.now(lido.tzinfo) if lido.tzinfo else datetime.now()
    return (agora - lido).total_seconds() / 60


def inadimplencia() -> dict:
    """A inadimplência do dia, para as 13h de dia útil.

    RESPONDE TRÊS PERGUNTAS, NESTA ORDEM: quanto está vencido e se isso é
    muito (o estoque e a taxa); se está piorando ou melhorando (o que entrou
    em atraso contra o que foi recuperado, por dia útil); e onde agir hoje
    (maiores devedores, o atraso fresco e o que vence nos próximos dias). O
    desenho de cada número está em `api/financeiro/inadimplencia.py`.

    NUNCA VAZIO: "nada vencido" é exatamente a notícia que o financeiro quer
    receber, e sumir nesse dia faria duvidar do envio no seguinte.
    """
    titulo = "Inadimplência — o dia"
    try:
        from api.financeiro import inadimplencia as fi

        r = fi.resumo()
        hoje = date.fromisoformat(r["hoje"])
        venc, taxa, n = r["vencido"], r["taxa"], r["janela_dias_uteis"]
        taxa_pct = taxa * 100 if taxa is not None else None
        var = r.get("variacao")
        ult = r.get("ultimo_fechamento")
        conc = r.get("concentracao")
        blocos = []

        idade = _idade_min(r.get("lido_em"))
        if idade is not None and idade > 30:
            lido = datetime.fromisoformat(str(r["lido_em"]))
            blocos.append(p.paragrafo(
                f"O ERP não respondeu na hora do envio. Os números abaixo são da "
                f"última leitura boa, das {lido.strftime('%H:%M')} "
                f"({idade / 60:.1f} h atrás).".replace(".", ",", 1), destaque=True))

        av = r["a_vencer"]
        blocos.append(p.kpis([
            {"rotulo": "Vencido agora", "valor": p.brl(venc),
             "estado": r["estado_taxa"],
             "sub": f"{p.inteiro(r['titulos'])} títulos de "
                    f"{p.inteiro(r['clientes'])} clientes"},
            {"rotulo": "Taxa de inadimplência", "valor": _pct(taxa_pct),
             "estado": r["estado_taxa"],
             "sub": f"do total em aberto ({_mil(r['aberto'])}) · atenção acima "
                    "de 5%, alta acima de 10%"},
            {"rotulo": "Desde o último fechamento", "valor": _variacao(var),
             "estado": ("neutro" if var is None or abs(var) < 0.5
                        else "warn" if var > 0 else "ok"),
             "sub": (f"fechamento de {_dia_sem(ult['dia'])}: {_mil(ult['vencido'])}"
                     if ult else "sem fechamento anterior para comparar")},
            {"rotulo": "Vencido há mais de 90 dias", "valor": p.brl(r["mais_90"]),
             "estado": "warn" if r["mais_90"] else "ok",
             "sub": f"{_pct(100 * r['mais_90'] / venc if venc else None)} do "
                    f"vencido · {p.inteiro(r['titulos_mais_90'])} títulos · "
                    "risco de perda"},
            {"rotulo": f"Entrou em atraso · {n} dias úteis",
             "valor": _mil(r["entrou"]), "estado": "neutro",
             "sub": "venceu e não foi pago no dia"},
            {"rotulo": f"Recuperado · {n} dias úteis",
             "valor": _mil(r["recuperado"]),
             "estado": "ok" if r["recuperado"] >= r["entrou"] else "warn",
             "sub": "pago depois do vencimento"},
            {"rotulo": f"Vence em {n} dias úteis", "valor": _mil(av["valor"]),
             "estado": "neutro",
             "sub": f"{p.inteiro(av['titulos'])} títulos de "
                    f"{p.inteiro(av['clientes'])} clientes, até "
                    f"{_dia_br(r['a_vencer_ate'])}"},
            {"rotulo": "Concentração", "valor": _pct(conc * 100 if conc is not None else None),
             "estado": "neutro",
             "sub": f"do vencido está nos {len(r['devedores'])} maiores devedores"},
        ]))

        pontos = r.get("pontos") or []
        if pontos:
            blocos.append(p.secao("Vencido no fechamento de cada dia útil",
                                  f"últimos {len(pontos)} e agora"))
            itens = [{"rotulo": _dia_sem(x["dia"]), "valor": x["vencido"] or 0,
                      "texto": _mil(x["vencido"])} for x in pontos]
            itens.append({"rotulo": "agora", "valor": venc, "texto": _mil(venc),
                          "cor": p.MARCA})
            blocos.append(p.barras(itens))

            ult10 = pontos[-10:]
            blocos.append(p.secao("Entrou em atraso por dia útil",
                                  "venceu e não foi pago · fim de semana e feriado "
                                  "entram no dia útil seguinte"))
            blocos.append(p.barras([
                {"rotulo": _dia_sem(x["dia"]), "valor": x["entrou"],
                 "texto": _mil(x["entrou"]) if x["entrou"] else "—", "cor": p.VERMELHO}
                for x in ult10]))
            blocos.append(p.secao("Recuperado por dia útil", "pago depois do vencimento"))
            blocos.append(p.barras([
                {"rotulo": _dia_sem(x["dia"]), "valor": x["recuperado"],
                 "texto": _mil(x["recuperado"]) if x["recuperado"] else "—",
                 "cor": p.VERDE}
                for x in ult10]))
            vj = r.get("variacao_janela")
            rumo = ("" if vj is None else
                    " O vencido ficou estável no período." if abs(vj) < 0.5 else
                    f" O vencido {'subiu' if vj > 0 else 'caiu'} {_mil(abs(vj))} "
                    "no período.")
            canc = (f", e {_mil(r['cancelado'])} vencidos foram cancelados"
                    if r.get("cancelado") else "")
            blocos.append(p.paragrafo(
                f"Nos últimos {n} dias úteis entraram {_mil(r['entrou'])} em "
                f"atraso e foram recuperados {_mil(r['recuperado'])}{canc}.{rumo}"))

        blocos.append(p.secao("Por faixa de atraso",
                              f"{_mil(venc)} em {p.inteiro(r['titulos'])} títulos"))
        cores = {"2_vencido_ate_30": p.AMBAR, "3_vencido_31_90": p.LARANJA,
                 "4_vencido_91_365": p.VERMELHO, "5_vencido_mais_365": p.MARCA}
        blocos.append(p.barras([
            {"rotulo": f["rotulo"], "valor": f["valor"], "cor": cores[f["faixa"]],
             "texto": _pct(f["pct"] * 100) if f["pct"] is not None else "—"}
            for f in r["faixas"]]))
        blocos.append(p.tabela(
            ["Faixa", "Valor", "Títulos"],
            [[f["rotulo"], p.brl(f["valor"]), p.inteiro(f["titulos"])]
             for f in r["faixas"]], alinha_dir=(1, 2)))

        dev = r["devedores"]
        if dev:
            blocos.append(p.secao(
                "Maiores devedores",
                f"{len(dev)} de {r['clientes']} clientes · "
                f"{_pct(conc * 100 if conc is not None else None)} do vencido"))

            def _antigo(d):
                x = d["dias_mais_antigo"]
                if x is None:
                    return "—"
                return p.chip(f"{x} dias", "bad" if x > 90 else "warn" if x > 30 else "neutro")
            blocos.append(p.tabela(
                ["Cliente", "Vencido", "Do total", "Títulos", "Mais antigo"],
                [[d["cliente"][:30], p.brl(d["vencido"]),
                  _pct(d["pct"] * 100 if d["pct"] is not None else None),
                  p.inteiro(d["titulos"]), _antigo(d)] for d in dev],
                alinha_dir=(1, 2, 3)))

        def _residuo(lista) -> None:
            # QUEM SAIU DA LISTA SE DIZ: "10 clientes" no total e 7 linhas na
            # tabela, sem explicação, se lê como defeito do relatório.
            if lista.get("residuais"):
                blocos.append(p.paragrafo(
                    f"Fora da lista: {lista['residuais']} cliente(s) só com saldo "
                    f"abaixo de {p.brl(fi.RESIDUO, 2)} — o centavo que sobra de "
                    "pagamento parcial no ERP. Eles continuam nos totais."))

        nv = r["novos"]
        blocos.append(p.secao(
            "Entraram em atraso e continuam em aberto",
            (f"{len(nv['itens'])} de {nv['clientes']} clientes · " if nv["clientes"] > len(nv["itens"])
             else "") + f"últimos {n} dias úteis · cobrança fresca"))
        if nv["itens"]:
            blocos.append(p.tabela(
                ["Cliente", "Valor", "Títulos", "Venceu em"],
                [[c["cliente"][:30], p.brl(c["valor"]), p.inteiro(c["titulos"]),
                  _dia_br(c["data"])] for c in nv["itens"]], alinha_dir=(1, 2)))
        else:
            blocos.append(p.paragrafo(
                f"Nada que venceu nos últimos {n} dias úteis continua em aberto."))
        _residuo(nv)

        blocos.append(p.secao(
            f"Vencem nos próximos {n} dias úteis",
            (f"{len(av['itens'])} de {av['clientes']} clientes · " if av["clientes"] > len(av["itens"])
             else "") + f"até {_dia_br(r['a_vencer_ate'])} · para lembrar antes"))
        if av["itens"]:
            blocos.append(p.tabela(
                ["Cliente", "Valor", "Títulos", "Primeiro vence"],
                [[c["cliente"][:30], p.brl(c["valor"]), p.inteiro(c["titulos"]),
                  _dia_br(c["data"])] for c in av["itens"]], alinha_dir=(1, 2)))
        else:
            blocos.append(p.paragrafo(
                f"Nenhum título vence nos próximos {n} dias úteis."))
        _residuo(av)

        pf = r["pendente_faturamento"]
        if pf["valor"]:
            blocos.append(p.secao("Fora desta conta"))
            blocos.append(p.paragrafo(
                f"{p.brl(pf['valor'])} em {p.inteiro(pf['docs'])} documentos "
                "vencidos estão marcados no ERP como PENDENTES DE FATURAMENTO. "
                "Eles ficam fora do vencido e da taxa — a mesma regra das telas "
                "Contas a Receber e Régua de Cobrança, que os mostram à parte."))

        blocos.append(p.secao("Como se mede"))
        blocos.append(p.paragrafo(
            "Vencido é a regra oficial das telas Contas a Receber e Régua de "
            "Cobrança: só o faturado, pelo saldo pendente de cada documento. O "
            "fechamento de cada dia é reconstruído do ERP — o que estava vencido "
            "e em aberto ao fim daquele dia —, e o título pago depois entra pelo "
            "valor dele. Entrou e recuperado contam só dias úteis FECHADOS: às 13h "
            "boa parte dos pagamentos de hoje ainda não foi lançada. Dia útil é "
            "de segunda a sexta, fora os feriados do calendário da casa "
            "(Gestão › Feriados)."))

        linhas = [f"Inadimplência — {hoje.strftime('%d/%m/%Y')}", "",
                  f"Vencido agora ......... {p.brl(venc)} ({_pct(taxa_pct)} do aberto)",
                  f"Títulos / clientes .... {r['titulos']} / {r['clientes']}",
                  f"Desde o fechamento .... {_variacao(var)}",
                  f"Mais de 90 dias ....... {p.brl(r['mais_90'])}",
                  f"Entrou ({n} dias úteis)  {_mil(r['entrou'])}",
                  f"Recuperado ({n} d. úteis) {_mil(r['recuperado'])}",
                  f"Vence em {n} dias úteis . {_mil(av['valor'])}", ""]
        if dev:
            linhas.append("Maiores devedores:")
            linhas += [f"  {d['cliente'][:40]} — {p.brl(d['vencido'])}" for d in dev[:5]]

        assunto = (f"[CÓRTEX] Inadimplência {hoje.strftime('%d/%m')} — "
                   + (f"{_mil(venc)} vencidos ({_pct(taxa_pct)})" if venc
                      else "nada vencido"))
        if var is not None and abs(var) >= 0.5 and ult:
            assunto += f" · {_variacao(var)} desde {_dia_sem(ult['dia'])}"

        return {
            "assunto": assunto,
            "html": p.documento(titulo, blocos,
                                subtitulo=f"{_dia_sem(hoje.isoformat())} · leitura "
                                          f"das {datetime.fromisoformat(str(r['lido_em'])).strftime('%H:%M')}",
                                origem=r.get("fonte") or "ERP AVA"),
            "texto": "\n".join(linhas),
            "vazio": False,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("inadimplencia falhou: %s", exc)
        return _falhou(titulo, exc)


CATALOGO = {
    "inadimplencia": {
        "nome": "Inadimplência — o dia",
        "descricao": "Vencido agora e a taxa sobre o aberto, o que entrou em "
                     "atraso e o que foi recuperado por dia útil, faixas de "
                     "atraso, maiores devedores e o que vence nos próximos "
                     "dias. Pensado para as 13h, só em dia útil.",
        "monta": inadimplencia,
        # "Nada vencido" é a notícia que o financeiro quer receber; sumir
        # nesse dia faria duvidar do envio no dia seguinte.
        "pular_vazio": False,
    },
    "ponto_do_dia": {
        "nome": "Ponto — o dia de ontem",
        "descricao": "Quem bateu, quem não bateu e onde caíram as batidas do "
                     "último dia fechado. Para o RH ler de manhã.",
        "monta": ponto_do_dia,
        # "Todos bateram" É a notícia que o RH quer receber de manhã. Sumir
        # nesse dia ensinaria a duvidar do envio no dia seguinte.
        "pular_vazio": False,
    },
    "contrapartida": {
        "nome": "CT-e de Contrapartida — despacho do dia",
        "descricao": "Fila do dia, estado da emissão automática e retorno "
                     "da SEFAZ.",
        "monta": contrapartida,
        # Fila vazia com tudo em ordem nao precisa virar e-mail diario.
        "pular_vazio": True,
    },
    "acoes_pendentes": {
        "nome": "Planos de ação — pendências",
        "descricao": "Ações atrasadas, vencendo em 7 dias e paradas há mais "
                     "de 21 dias, com responsável.",
        "monta": acoes_pendentes,
        # "O plano está em dia" é a notícia que se quer receber — sumir com
        # ela faria o destinatário duvidar do envio.
        "pular_vazio": False,
    },
    "digest": {
        "nome": "Alertas do painel",
        "descricao": "O que exige ação hoje, separado por severidade.",
        "monta": digest,
        # Aqui o silencio informa: "nenhum alerta" e a noticia boa que se
        # quer receber, e some-la faria o destinatario duvidar do envio.
        "pular_vazio": False,
    },
}


def montar(relatorio: str) -> dict:
    """Monta pelo id. Relatório desconhecido é ERRO, não silêncio: um id
    errado gravado na agenda pararia o envio para sempre sem dizer por quê."""
    item = CATALOGO.get(relatorio)
    if not item:
        raise ValueError(
            f"Relatório desconhecido: {relatorio!r}. "
            f"Disponíveis: {', '.join(sorted(CATALOGO))}.")
    return item["monta"]()
