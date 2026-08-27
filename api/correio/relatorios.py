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

log = logging.getLogger("cortex.correio.relatorios")


def _dia_br(iso) -> str:
    t = str(iso or "")[:10].split("-")
    return f"{t[2]}/{t[1]}" if len(t) == 3 else str(iso or "—")


def _data_br(iso) -> str:
    t = str(iso or "")[:10].split("-")
    return f"{t[2]}/{t[1]}/{t[0]}" if len(t) == 3 else "—"


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


CATALOGO = {
    "contrapartida": {
        "nome": "CT-e de Contrapartida — despacho do dia",
        "descricao": "Fila do dia, estado da emissão automática e retorno "
                     "da SEFAZ.",
        "monta": contrapartida,
        # Fila vazia com tudo em ordem nao precisa virar e-mail diario.
        "pular_vazio": True,
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
