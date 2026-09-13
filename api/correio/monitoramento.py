# -*- coding: utf-8 -*-
"""Monitoramento de cliente por e-mail — a planilha da torre, automática.

O QUE ESTE MÓDULO SUBSTITUI
===========================
A torre mantém, por cliente, uma planilha com uma aba por dia e a manda
anexada ao cliente de duas em duas horas. Cada carga ocupa uma linha — frota,
placas, janela de carregamento, janela de entrega, chegada e saída no cliente,
total, carência, horas paradas, número do pedido, CVA — e embaixo dela a
torre vai DIGITANDO a situação: "Pátio carregado", "Em viagem, previsão às
08h", "Aguardando no Gate", "Aguardando descarga", "Retornando".

Tudo isso o CÓRTEX já sabe pelo ERP, e sabe pelo MESMO caminho da tela Minha
Operação (`api/portal_cliente`): a coleta é a espinha, os apontamentos da
operação, o manifesto eletrônico e o computador de bordo são as testemunhas da
situação, e o freetime do contrato, casado pela mercadoria, é a carência.
Medido em 12/09/2026 contra a planilha real de um cliente: o número do pedido
é o `coleta.numero`, a janela de carregamento é `dtcoletar`, a de entrega é
`dtprevisaochegadaviagem` (a mesma que já tinha batido NO MINUTO com a
planilha em 09/09), e o CVA, quando existe, está dentro de `numerofatura`. As
carências da planilha (6h30 e 3h) são as do contrato.

UMA REGRA, NÃO DUAS
===================
A consulta é o `AGORA_SQL` do portal, e a situação sai das funções dele
(`_estado`, `_macro_vence`, `em_curso`). Uma segunda grafia de "em que pé está
a carga" faria o e-mail e o portal — que o MESMO cliente lê — discordarem por
construção. O que este módulo acrescenta é só o recorte do DIA (o que a aba da
torre mostra) e as contas da planilha.

O MOTORISTA SAI PELO PRIMEIRO NOME, E SÓ ELE
============================================
O portal do cliente não mostra motorista. Este e-mail mostra, por decisão de
quem opera (12/09/2026: "vamos colocar o nome, qualquer coisa ajustamos
depois") — a planilha da torre sempre trouxe, e é por ele que a portaria do
cliente chama o veículo. Sai o PRIMEIRO NOME, como a torre escreve ("Joel",
"Marcos"), e nada além: nem sobrenome, nem telefone, nem o CPF, que é o
próprio `coleta.motorista`. A consulta traz o nome do cadastro e nunca o
código, e há teste para os três.

O LINK "VER ONDE ESTÁ A CARGA" (13/09/2026)
==========================================
Pedido de quem opera. Cada carga que já tem CT-e leva o link da página pública
de rastreio ("Onde está minha carga?", `api/rastreio`) — o MESMO link assinado
que o aviso de WhatsApp manda: HMAC sobre a chave do CT-e, 20 dias de prazo,
no fragmento da URL. Quem recebe este e-mail é gente do cliente, sem login no
CÓRTEX; a tela Minha Operação pediria um cadastro que ainda não existe.

A PONTE é coleta → `conhecimento_composicao` → CT-e, pela chave INTEIRA da
coleta (o número se repete entre filiais e séries). Medido em 13/09/2026, 45
dias de um cliente de linha: 723 de 744 coletas com um CT-e, 11 com dois (o
mesmo veículo, números seguidos — vale o mais recente), 10 sem nenhum ainda.
`tipodocumento` vale 27 em 100% da composição, então não há nota fiscal
misturada e não se filtra por um código que nunca varia.

A página mostra o que o rastreio decidiu mostrar no detalhe — inclusive
placas e o nome COMPLETO do motorista. É mais que o primeiro nome deste
e-mail, e é a mesma coisa que o link do WhatsApp já entrega ao cliente.

O LINK É ACRÉSCIMO: se a ponte falhar, o e-mail sai sem ele, e não deixa de
sair.

O QUE ACONTECE QUANDO O ERP NÃO RESPONDE
=======================================
NADA VAI PARA O CLIENTE. Os relatórios internos mandam "não consegui ler o
ERP" no próprio e-mail, porque quem lê é da casa; aqui quem lê é o cliente, e
uma mensagem de falha do nosso sistema na caixa dele não informa nada que ele
possa usar. E sem rede de leitura velha, pelo mesmo motivo do portal: esta é
a POSIÇÃO de agora, e posição de duas horas atrás com tarja continua sendo
posição errada. A rotina marca a passagem como falha, a Saúde acende, e a
rodada seguinte tenta de novo.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from .. import migracoes, pglocal
from ..agendamento import (DIAS, INTERVALOS_MIN, deve_rodar_intervalo,
                           descrever_intervalo, proxima_intervalo)
from ..agendamento import hhmm as _hhmm

log = logging.getLogger("cortex.correio.monitoramento")

ESQUEMA: str | None = None

RE_RAIZ = re.compile(r"^[0-9]{8}$")

#: O CVA vem DENTRO de `numerofatura`, grudado na ordem de frete do cliente
#: ("6100416533CIF0103984"). Medido em 30 dias de um cliente de linha: 97 de
#: 508 coletas trazem o trecho — as de um destino só, que é onde a planilha da
#: torre também o mostra. Onde ele não existe a coluna fica em branco: a torre
#: escreve à mão "CIF00" + o número do pedido para os outros destinos, e
#: fabricar esse código aqui seria inventar um documento que o ERP não tem.
RE_CVA = re.compile(r"CIF\d+", re.I)

#: Carga PROGRAMADA entra só se carrega nas próximas 24 h. A planilha da torre
#: é o dia; a programação da semana que vem numa mensagem de duas em duas
#: horas é ruído que empurra para baixo o que está acontecendo.
HORIZONTE_PROGRAMADA_H = 24

#: A mesma janela do portal (`get_agora`): as duas saídas precisam enxergar
#: o mesmo conjunto de cargas em curso, senão discordam na borda.
JANELA_DIAS = 45

#: Como a FONTE da situação aparece para o cliente. Os nomes internos
#: ("apontamento", "macro") são jargão da casa; o nome do fornecedor de
#: rastreamento não sai, pela regra do portal.
FONTES = {"apontamento": "registro da operação",
          "manifesto": "manifesto eletrônico",
          "macro": "computador de bordo",
          "programação": "programação"}

#: Em que pé está, na linguagem da planilha. A ORDEM é a de leitura do e-mail.
#: `sem_fim` é a carga que CHEGOU e saiu do ar pelo relógio (12 h depois da
#: chegada, `portal_cliente.FOLGA_DESCARGA_H`) sem o fim da descarga ter sido
#: registrado — chamá-la de "descarregada" seria afirmar um evento que
#: ninguém registrou.
GRUPOS_SITUACAO = ("no_cliente", "em_viagem", "na_origem", "programada",
                   "descarregada", "sem_fim")

_SEM = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


# ═══════════════════════════════════════════════════════════════ A REGRA ════

def _dias(valor) -> str:
    """'123456' a partir de lista, string ou números soltos. Só 1..7."""
    if isinstance(valor, (list, tuple, set)):
        valor = "".join(str(v) for v in valor)
    return "".join(sorted(set(str(valor or "")) & set("1234567")))


def validar(dados: dict) -> dict:
    """Normaliza e recusa o que não dá para agendar — na GRAVAÇÃO, não no
    envio: erro que só aparece na rotina desassistida é erro que ninguém vê."""
    from api import freetime as _ft
    from api.correio import config as cfg

    raiz = str(dados.get("cliente_raiz") or "").strip()
    if not RE_RAIZ.match(raiz):
        raise ValueError("Escolha o cliente.")
    nome = re.sub(r"\s+", " ", str(dados.get("cliente_nome") or "")).strip()[:120]

    dest = cfg.separar_destinatarios(dados.get("destinatarios") or "")
    if not dest:
        raise ValueError("Informe ao menos um destinatário.")
    ruins = [e for e in dest if not cfg.email_valido(e)]
    if ruins:
        raise ValueError("Endereço inválido: " + ", ".join(ruins[:3]))
    resp = cfg.separar_destinatarios(dados.get("responder_para") or "")
    ruins = [e for e in resp if not cfg.email_valido(e)]
    if ruins:
        raise ValueError("Endereço de resposta inválido: " + ", ".join(ruins[:3]))

    try:
        intervalo = int(dados.get("intervalo_min") or 120)
    except (TypeError, ValueError):
        raise ValueError("Intervalo ilegível.") from None
    if intervalo not in INTERVALOS_MIN:
        raise ValueError("Intervalo deve ser de "
                         + ", ".join(f"{m // 60} h" for m in INTERVALOS_MIN) + ".")

    h0, m0 = _hhmm(dados.get("hora_inicio") or "06:00")
    h1, m1 = _hhmm(dados.get("hora_fim") or "22:00")
    if (h1, m1) <= (h0, m0):
        # A faixa que atravessa a meia-noite não é aceita, e não por preguiça:
        # "22:00 às 06:00" pertence a DOIS dias da semana, e "só de segunda a
        # sábado" passaria a ter uma resposta ambígua no sábado à noite.
        raise ValueError("A faixa precisa começar antes de terminar. Para o dia "
                         "inteiro, use 00:00 às 23:59.")

    dias = _dias(dados.get("dias_semana") if dados.get("dias_semana") is not None
                 else "123456")
    if not dias:
        raise ValueError("Marque ao menos um dia da semana.")

    return {"cliente_raiz": raiz, "cliente_nome": nome,
            "mercadorias": list(_ft.canonizar(dados.get("mercadorias") or [])),
            "destinatarios": ", ".join(dest),
            "responder_para": ", ".join(resp),
            "intervalo_min": intervalo,
            "hora_inicio": f"{h0:02d}:{m0:02d}", "hora_fim": f"{h1:02d}:{m1:02d}",
            "dias_semana": dias,
            "anexar_planilha": bool(dados.get("anexar_planilha", True)),
            # PADRÃO DESLIGADO: este e-mail sai para o CLIENTE.
            "ativo": bool(dados.get("ativo"))}


_COLUNAS = ("id, cliente_raiz, cliente_nome, mercadorias, destinatarios,"
            " responder_para, intervalo_min, hora_inicio, hora_fim, dias_semana,"
            " anexar_planilha, ativo, ultima_execucao, ultimo_resultado,"
            " criado_por, criado_em, alterado_por, alterado_em")


def listar(esquema: str | None = None) -> list[dict]:
    init_db(esquema)
    linhas = pglocal.query(f"SELECT {_COLUNAS} FROM correio_monitoramento ORDER BY id",
                           (), esquema=_esq(esquema))
    for r in linhas:
        r["mercadorias"] = list(r.get("mercadorias") or [])
    return linhas


def um(ident: int, esquema: str | None = None) -> dict | None:
    return next((x for x in listar(esquema) if int(x["id"]) == int(ident)), None)


def gravar(dados: dict, quem: str, esquema: str | None = None) -> dict:
    if not quem:
        raise ValueError("Informe quem está criando o monitoramento.")
    v = validar(dados)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    init_db(esquema)
    campos = (v["cliente_raiz"], v["cliente_nome"], v["mercadorias"],
              v["destinatarios"], v["responder_para"], v["intervalo_min"],
              v["hora_inicio"], v["hora_fim"], v["dias_semana"],
              v["anexar_planilha"], v["ativo"])
    ident = dados.get("id")
    if ident:
        r = pglocal.um(
            "UPDATE correio_monitoramento SET cliente_raiz=%s, cliente_nome=%s,"
            " mercadorias=%s, destinatarios=%s, responder_para=%s, intervalo_min=%s,"
            " hora_inicio=%s, hora_fim=%s, dias_semana=%s, anexar_planilha=%s,"
            " ativo=%s, alterado_por=%s, alterado_em=%s WHERE id=%s RETURNING id",
            campos + (quem, agora, int(ident)), esquema=_esq(esquema))
        if not r:
            raise ValueError(f"Monitoramento {ident} não existe.")
    else:
        r = pglocal.um(
            "INSERT INTO correio_monitoramento(cliente_raiz, cliente_nome,"
            " mercadorias, destinatarios, responder_para, intervalo_min,"
            " hora_inicio, hora_fim, dias_semana, anexar_planilha, ativo,"
            " criado_por) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            campos + (quem,), esquema=_esq(esquema))
    return {**v, "id": int(r["id"])}


def remover(ident: int, esquema: str | None = None) -> None:
    init_db(esquema)
    pglocal.executar("DELETE FROM correio_monitoramento WHERE id=%s",
                     (int(ident),), esquema=_esq(esquema))


def registrar_execucao(ident: int, resultado: str,
                       esquema: str | None = None) -> None:
    """Marca a PASSAGEM da rodada — inclusive quando não houve envio."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pglocal.executar("UPDATE correio_monitoramento SET ultima_execucao=%s,"
                     " ultimo_resultado=%s WHERE id=%s",
                     (agora, str(resultado)[:200], int(ident)),
                     esquema=_esq(esquema))


def estado(esquema: str | None = None) -> dict:
    """Tudo que a tela precisa."""
    from api.correio import config as cfg

    itens = []
    for m in listar(esquema):
        pode, porque = deve_rodar_intervalo(m)
        itens.append({**m, "quando": descrever_intervalo(m),
                      "proxima": proxima_intervalo(m),
                      "pronto": pode, "motivo": porque})
    return {"monitoramentos": itens,
            "intervalos_min": list(INTERVALOS_MIN),
            "smtp_configurado": cfg.configurado(),
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ═══════════════════════════════════════════════════════════════ O DADO ═════

def _t(txt) -> datetime | None:
    try:
        return datetime.strptime(str(txt)[:16], "%Y-%m-%d %H:%M") if txt else None
    except ValueError:
        return None


def _primeiro_nome(nome) -> str:
    """'JOEL DA SILVA SANTOS' → 'Joel'. Só o primeiro — ver o cabeçalho."""
    partes = str(nome or "").split()
    return partes[0].capitalize() if partes else ""


def _frotas(placas: set) -> tuple[dict, bool]:
    """Placa → número de frota. Falhar aqui não derruba o e-mail: a linha
    sai só com a placa, que é a chave, e o dado diz que faltou o número."""
    if not placas:
        return {}, False
    try:
        from api import frota_identidade as fi
        m = fi.mapa()
    except Exception:  # noqa: BLE001
        log.warning("monitoramento: identidade da frota indisponivel")
        return {}, True
    fora = {}
    for p in placas:
        f = ((m.get(p) or {}).get("frota") or "").strip()
        # frota igual à placa é a placa copiada no campo, não número de frota
        # (943 cadastros assim, `api/frota_identidade`)
        if f and f.upper() != p.upper():
            fora[p] = f
    return fora, False


def _ponte_sql() -> str:
    """Coleta → CT-e, pela chave inteira da coleta. Função e não constante
    porque o filtro de cliente mora no portal, e importá-lo no carregamento
    deste módulo o amarraria ao portal a cada `import`."""
    from api import portal_cliente as pc
    return """
-- monitoramento: ponte coleta -> CT-e (o link do rastreio)
SELECT concat_ws('|', c.grupo, c.empresa, c.filial, c.unidade,
                 c.diferenciadornumero, c.serie, c.numero) AS coleta_chave,
       k.grupo, k.empresa, k.filial, k.numero, k.serie
FROM coleta c
JOIN conhecimento_composicao cc
  ON cc.grupo=c.grupo AND cc.empresa=c.empresa AND cc.filialdocumento=c.filial
 AND cc.unidadedocumento=c.unidade
 AND cc.diferenciadornumerodocumento=c.diferenciadornumero
 AND cc.seriedocumento=c.serie AND cc.numerodocumento=c.numero
JOIN conhecimento k
  ON k.grupo=cc.grupo AND k.empresa=cc.empresa AND k.filial=cc.filial
 AND k.unidade=cc.unidade AND k.diferenciadornumero=cc.diferenciadornumero
 AND k.serie=cc.serie AND k.numero=cc.numero
WHERE c.dtcancelamento IS NULL AND k.dtcancelamento IS NULL
  AND c.dtemissao >= current_date - %(dias)s
  AND """ + pc.FILTRO_CLIENTE


def _links(raiz: str, chaves: set) -> tuple[dict, bool]:
    """Chave da coleta → link do rastreio. Devolve também se a ponte FALHOU.

    Nunca levanta: o link é acréscimo (ver o cabeçalho). Dois CT-es para a
    mesma coleta são o mesmo veículo em números seguidos — vale o mais novo.
    """
    if not chaves:
        return {}, False
    try:
        from api import db
        from api.rastreio import consulta, mensagem
        melhor: dict[str, dict] = {}
        for r in db.query(_ponte_sql(), {"raiz": raiz, "dias": JANELA_DIAS}):
            k = r["coleta_chave"]
            if k in chaves and (k not in melhor or r["numero"] > melhor[k]["numero"]):
                melhor[k] = r
        return {k: mensagem.link({"link_token": consulta.link_token(
                    r["grupo"], r["empresa"], r["filial"], r["numero"], r["serie"])})
                for k, r in melhor.items()}, False
    except Exception as exc:  # noqa: BLE001
        log.warning("monitoramento: ponte coleta->CT-e falhou: %s", type(exc).__name__)
        return {}, True


def _historico(r: dict, cod: int, quando: str, fonte: str, onde) -> list[dict]:
    """A coluna "situação" da planilha, que a torre digita linha a linha,
    montada pelos registros — cada um com a hora e a testemunha."""
    from api import portal_cliente as pc
    h = []
    for c in pc.ORDEM:
        t = r.get(pc.COLUNA[c])
        if t:
            h.append({"rotulo": pc.MARCOS[c], "quando": t, "fonte": FONTES["apontamento"]})
    if r.get("mdfe_encerrado") and r.get("mdfe_em") and not r.get("t_cheg_desc"):
        h.append({"rotulo": pc.MARCOS[396], "quando": r["mdfe_em"],
                  "fonte": FONTES["manifesto"]})
    if fonte == "macro" and quando:
        h.append({"rotulo": pc.MARCOS.get(cod, ""), "quando": quando,
                  "fonte": FONTES["macro"] + (f" · {onde}" if onde else "")})
    return sorted(h, key=lambda x: x["quando"])


def dados(raiz: str, mercs=(), agora: datetime | None = None) -> dict:
    """As cargas do DIA de um cliente, com as contas da planilha da torre.

    O DIA É O DA ABA DA TORRE: o que está no ar agora (inclusive o que chegou
    e espera doca), o que carrega nas próximas 24 h, e o que DESCARREGOU hoje
    — este com o total, a carência e as horas paradas fechados. A carga que
    descarregou ontem não entra: ela está na aba de ontem.

    LEVANTA se o ERP não responder — ver o cabeçalho do módulo.
    """
    from api import db
    from api import freetime as _ft
    from api import portal_cliente as pc

    if not RE_RAIZ.match(str(raiz or "")):
        raise ValueError("cliente sem raiz de CNPJ")
    agora = agora or datetime.now()
    hoje = agora.date().isoformat()
    mercs = _ft.canonizar(mercs)

    linhas = db.query(pc._sql(pc.AGORA_SQL, mercs),
                      {"raiz": raiz, "dias": JANELA_DIAS, "merc": list(mercs)})

    # A CARÊNCIA É O CONTRATO. Falhar aqui não derruba o e-mail — a situação
    # das cargas continua valendo —, mas a coluna sai em branco e o e-mail
    # DIZ que o contrato não foi lido, em vez de publicar horas paradas
    # contra carência zero.
    try:
        contrato = pc._freetime(raiz)["linhas"]
        contrato_ok = True
    except Exception:  # noqa: BLE001
        log.warning("monitoramento: freetime indisponivel")
        contrato, contrato_ok = [], False

    from api import raster_eventos
    placas_cruas = tuple(sorted({pc.trim_placa(r) for r in linhas if pc.trim_placa(r)}))
    rast = raster_eventos.por_placa(placas_cruas, dias=raster_eventos.JANELA_MAPA_D,
                                    macros_por_placa=raster_eventos.MACROS_NO_MAPA)
    macros = rast.get("macros", {})
    rotas = pc._eta_por_rota() if linhas else {}

    cargas = []
    for r in linhas:
        cod, rotulo, quando, fonte = pc._estado(r)
        cod, rotulo, quando, fonte, onde = pc._macro_vence(
            cod, rotulo, quando, fonte, macros.get(pc.trim_placa(r)))
        no_ar = pc.em_curso(r, agora)

        # CHEGADA E SAÍDA NO CLIENTE: as colunas G e H da planilha. A chegada
        # vem do registro mais fino que houver — apontamento, depois o
        # encerramento do manifesto, depois o próprio veículo dizendo.
        chegada = r.get("t_cheg_desc") or (
            r.get("mdfe_em") if r.get("mdfe_encerrado") else None)
        if not chegada and fonte == "macro" and cod in (396, 399, 397):
            chegada = quando
        saida = r.get("t_fim_desc")
        if not saida and fonte == "macro" and cod in (397, 401):
            saida = quando
        concluida = (not no_ar) or bool(saida)

        if concluida:
            fim = saida or r.get("t_finalizada") or chegada
            if not fim or str(fim)[:10] != hoje:
                continue                         # é da aba de outro dia
            situacao = "descarregada" if saida else "sem_fim"
        elif cod in (396, 399, 397):
            situacao = "no_cliente"
        elif cod in (395, 400):
            situacao = "em_viagem"
        elif cod in (394, 398):
            situacao = "na_origem"
        else:
            jc = _t(r.get("janela_carga"))
            if jc and jc > agora + timedelta(hours=HORIZONTE_PROGRAMADA_H):
                continue
            situacao = "programada"

        # PERMANÊNCIA NO CLIENTE: SÓ COM AS DUAS PONTAS REGISTRADAS.
        #
        # A primeira versão contava o relógio do veículo que ainda está lá
        # (agora − chegada) e, com o dado real de 12/09/2026, disse ao cliente
        # que um caminhão estava "há 11h23 no cliente, 8h23 acima da
        # carência". A chegada era do manifesto; o fim da descarga é que não
        # tinha sido registrado — e ele chega com atraso (p90 de 9h20 depois
        # do encerramento, e 11,5% das cargas nunca o recebem, medido no
        # portal). Relógio correndo sobre um registro que atrasa mede o
        # ATRASO DO REGISTRO, e na caixa do cliente isso vira cobrança de
        # espera de um veículo que já foi embora.
        #
        # A planilha da torre também não conta: sem a saída, a fórmula dela
        # dá zero. Então aqui a permanência existe quando o fim da descarga
        # existe, e o veículo no cliente aparece com a chegada e a frase
        # "fim da descarga não registrado", que é o que se sabe.
        #
        # Acima do teto físico da casa é n/d contado, nunca número: é
        # pareamento atravessando dias, não veículo parado.
        ch, sa = _t(chegada), _t(saida)
        perm, perm_nd = None, False
        if ch and sa and sa >= ch:
            perm = (sa - ch).total_seconds() / 3600
        if perm is not None and perm > pc.CAP_H:
            perm, perm_nd = None, True

        cl = _ft.resolver(contrato, r.get("mercadoria"))
        carencia = (cl.get("ft_descarga_h")
                    if cl and cl.get("origem") != _ft.SEM_CLAUSULA else None)
        paradas = (max(perm - carencia, 0.0)
                   if perm is not None and carencia is not None else None)

        # PREVISÃO SÓ NO FUTURO. Ela conta da saída do carregamento pela
        # mediana da rota, e com o dado real de 12/09/2026 saiu "previsão
        # 11/09 19:56" num sábado à noite, para uma carga com entrega marcada
        # para segunda — o veículo espera o fim de semana, e a mediana não
        # sabe disso. Previsão vencida na caixa do cliente é ruído que parece
        # atraso; a janela de entrega continua na linha.
        eta = pc._eta(r, cod, rotas).get("eta")
        if eta and (_t(eta) is None or _t(eta) <= agora):
            eta = None

        m = RE_CVA.search(r.get("ref_cliente") or "")
        cargas.append({
            "coleta": r["coleta"], "_chave": r.get("coleta_chave") or "",
            "mercadoria": (r.get("mercadoria") or "").strip().upper() or "(sem mercadoria)",
            "destinatario": r.get("destinatario_nome") or "(sem destinatário)",
            "destino": r.get("destino") or "", "uf_destino": r.get("uf_destino") or "",
            "placa": pc.trim_placa(r), "carreta": (r.get("carreta") or "").strip(),
            "motorista": _primeiro_nome(r.get("motorista_nome")),
            "janela_carga": r.get("janela_carga"), "janela_entrega": r.get("janela_entrega"),
            "chegada": chegada, "saida": saida,
            "permanencia_h": perm, "permanencia_nd": perm_nd,
            "carencia_h": carencia, "paradas_h": paradas,
            "cva": m.group(0).upper() if m else "",
            "situacao": situacao,
            "marco": rotulo, "marco_cod": cod, "marco_em": quando,
            "marco_fonte": FONTES.get(fonte, fonte), "marco_onde": onde,
            "eta": eta,
            "historico": _historico(r, cod, quando, fonte, onde),
        })

    frotas, frota_falhou = _frotas({c[k] for c in cargas for k in ("placa", "carreta")
                                    if c[k]})
    links, links_falhou = _links(raiz, {c["_chave"] for c in cargas if c["_chave"]})
    for c in cargas:
        c["frota"] = " / ".join(x for x in (frotas.get(c["placa"]),
                                            frotas.get(c["carreta"])) if x)
        c["placas"] = " / ".join(x for x in (c["placa"], c["carreta"]) if x)
        c["link"] = links.get(c["_chave"])

    # GRUPOS NA ORDEM DO DICIONÁRIO, e não por volume: a mensagem chega de
    # duas em duas horas, e quem a lê aprende onde fica o seu destino. Ordem
    # que muda a cada envio obriga a procurar toda vez.
    por: dict[tuple, list] = {}
    for c in cargas:
        por.setdefault((c["mercadoria"], c["destinatario"]), []).append(c)
    grupos = []
    for (merc, dest) in sorted(por):
        lista = sorted(por[(merc, dest)], key=lambda c: (
            c["janela_entrega"] or c["janela_carga"] or "9999", c["coleta"]))
        cars = sorted({c["carencia_h"] for c in lista if c["carencia_h"] is not None})
        grupos.append({"mercadoria": merc, "destinatario": dest,
                       "carencia_h": cars[0] if len(cars) == 1 else None,
                       "cargas": lista})

    def _conta(sit, acima=False):
        return sum(1 for c in cargas if c["situacao"] == sit
                   and (not acima or (c["paradas_h"] or 0) > 0))

    resumo = {s: _conta(s) for s in GRUPOS_SITUACAO}
    resumo["descarregada_acima"] = _conta("descarregada", True)
    resumo["paradas_h_hoje"] = sum(c["paradas_h"] or 0 for c in cargas
                                   if c["situacao"] == "descarregada")
    return {
        "raiz": raiz, "cliente": pc.nome_do_cliente(raiz) or raiz,
        "mercadorias_filtro": list(mercs),
        "cargas": cargas, "grupos": grupos, "resumo": resumo,
        "agora": agora.strftime("%Y-%m-%d %H:%M"),
        "contrato_lido": contrato_ok, "frota_falhou": frota_falhou,
        "links_falhou": links_falhou,
        "bordo_indisponivel": bool(rast.get("indisponivel")),
        "fonte": ("Sistema de gestão · coleta, registros da operação, manifesto "
                  "eletrônico e computador de bordo · carência do contrato por "
                  f"mercadoria · leitura das {agora:%H:%M}"),
    }


# ═════════════════════════════════════════════════════════════ O E-MAIL ═════

def hm(h: float | None) -> str:
    """3.78 → '3h47'. Horas na unidade de quem lê a planilha."""
    if h is None:
        return "—"
    minutos = int(round(float(h) * 60))
    return f"{minutos // 60}h{minutos % 60:02d}"


def _dm(txt) -> str:
    t = _t(txt)
    return t.strftime("%d/%m %H:%M") if t else "—"


def _hh(txt) -> str:
    t = _t(txt)
    return t.strftime("%H:%M") if t else "—"


_ROTULO_SIT = {"no_cliente": ("No cliente", "warn"),
               "em_viagem": ("Em viagem", "neutro"),
               "na_origem": ("Carregando", "neutro"),
               "programada": ("Programada", "neutro"),
               "descarregada": ("Descarregada", "ok"),
               "sem_fim": ("Chegou", "neutro")}


def _celulas(c: dict) -> list:
    from api.correio import painel as p
    e = p._esc
    cinza = f"color:{p.CINZA};font:400 12px/1.5 {p.FONTE}"
    mono = f"color:{p.CINZA};font:400 12px/1.5 {p.MONO}"

    ident = (f"<b>{e(c['frota'] or c['placa'] or '—')}</b>"
             + (f'<br><span style="{mono}">{e(c["placas"])}</span>' if c["frota"] else "")
             + (f'<br><span style="{cinza}">{e(c["motorista"])}</span>'
                if c["motorista"] else "")
             + f'<br><span style="{mono}">pedido {e(c["coleta"])}'
             + (f" · {e(c['cva'])}" if c["cva"] else "") + "</span>")

    # `nowrap` na data: numa coluna de 600 px o "02:00" caía sozinho na
    # linha de baixo, e a hora solta se lê como outra informação.
    nw = "white-space:nowrap"
    janelas = (f'<span style="{cinza}">carga</span><br>'
               f'<span style="{nw}">{e(_dm(c["janela_carga"]))}</span>'
               f'<br><span style="{cinza}">entrega</span><br>'
               f'<span style="{nw}">{e(_dm(c["janela_entrega"]))}</span>')

    rot, est = _ROTULO_SIT[c["situacao"]]
    sit = str(p.chip(rot, est))
    det = c["marco"] + (f" · {_dm(c['marco_em'])}" if c["marco_em"] else "")
    sit += f'<br><span style="{cinza}">{e(det)} · {e(c["marco_fonte"])}'
    if c["marco_onde"]:
        sit += f" · {e(c['marco_onde'])}"
    sit += "</span>"
    if c["eta"]:
        sit += (f'<br><span style="{cinza}">previsão de chegada {e(_dm(c["eta"]))} '
                f'(pelo histórico da rota)</span>')
    if c.get("link"):
        sit += (f'<br><a href="{e(c["link"])}" style="font:700 12.5px/1.8 {p.FONTE};'
                f'color:{p.LARANJA};text-decoration:underline">'
                f'Ver onde está a carga →</a>')

    if not c["chegada"]:
        cli = "—"
    elif not c["saida"]:
        cli = (f"chegou {e(_dm(c['chegada']))}"
               f'<br><span style="{cinza}">fim da descarga não registrado</span>')
    else:
        cli = f"{e(_hh(c['chegada']))} → {e(_hh(c['saida']))}"
        if c["permanencia_nd"]:
            cli += f'<br><span style="{cinza}">acima de 24 h: n/d</span>'
        elif c["permanencia_h"] is not None:
            cli += (f'<br>{e(hm(c["permanencia_h"]))}'
                    f' <span style="{cinza}">de {e(hm(c["carencia_h"]))}</span>')
            if c["paradas_h"] is not None:
                if c["paradas_h"] > 0:
                    cli += "<br>" + str(p.chip(f"+{hm(c['paradas_h'])} parado", "bad"))
                else:
                    cli += "<br>" + str(p.chip("dentro da carência", "ok"))
    return [p.Html(ident), p.Html(janelas), p.Html(sit), p.Html(cli)]


def _linha_texto(c: dict) -> list[str]:
    fora = [f"  {c['frota'] + ' · ' if c['frota'] else ''}{c['placas'] or '—'} · "
            + (f"{c['motorista']} · " if c["motorista"] else "")
            + f"pedido {c['coleta']}" + (f" · {c['cva']}" if c["cva"] else ""),
            f"    Janela: carga {_dm(c['janela_carga'])} · entrega {_dm(c['janela_entrega'])}",
            f"    Situação: {c['marco']}"
            + (f" · {_dm(c['marco_em'])}" if c["marco_em"] else "")
            + f" ({c['marco_fonte']}" + (f", {c['marco_onde']}" if c["marco_onde"] else "")
            + ")"]
    if c["eta"]:
        fora.append(f"    Previsão de chegada: {_dm(c['eta'])} (pelo histórico da rota)")
    if c.get("link"):
        fora.append(f"    Onde está: {c['link']}")
    if c["chegada"] and not c["saida"]:
        fora.append(f"    No cliente: chegou {_dm(c['chegada'])} · fim da descarga "
                    "não registrado")
    elif c["chegada"]:
        linha = f"    No cliente: {_hh(c['chegada'])} → {_hh(c['saida'])}"
        if c["permanencia_nd"]:
            linha += " · acima de 24 h: n/d"
        elif c["permanencia_h"] is not None:
            linha += f" · {hm(c['permanencia_h'])} de {hm(c['carencia_h'])}"
            if c["paradas_h"]:
                linha += f" · +{hm(c['paradas_h'])} parado"
        fora.append(linha)
    return fora


def nome_arquivo(d: dict) -> str:
    t = _t(d["agora"]) or datetime.now()
    return f"Monitoramento de cargas {t:%d-%m-%Y %Hh%M}.xlsx"


def montar(raiz: str, mercs=(), *, anexar: bool = True,
           agora: datetime | None = None, dados_: dict | None = None) -> dict:
    """O e-mail de UMA rodada: assunto, HTML, texto e a planilha.

    `vazio=True` quando não há carga no dia — quem envia NÃO manda: uma
    mensagem de duas em duas horas dizendo "nada" ensina a arquivar sem ler.
    LEVANTA se o ERP não responder (ver o cabeçalho do módulo).
    """
    from api.correio import painel as p
    from api.correio import planilha_monitoramento as pm

    d = dados_ if dados_ is not None else dados(raiz, mercs, agora)
    t = _t(d["agora"]) or datetime.now()
    rs = d["resumo"]
    cliente = d["cliente"]
    filtro = (" · " + ", ".join(d["mercadorias_filtro"]).lower()
              if d["mercadorias_filtro"] else "")
    titulo = "Monitoramento de cargas"
    sub = f"{cliente} · {_SEM[t.weekday()]} {t:%d/%m} · posição das {t:%H:%M}{filtro}"

    desc_sub = (f"{rs['descarregada_acima']} acima da carência · "
                f"{hm(rs['paradas_h_hoje'])} parado além dela"
                if rs["descarregada_acima"] else
                "todas dentro da carência" if rs["descarregada"] else "nenhuma ainda")
    if rs["sem_fim"]:
        desc_sub += f" · e {rs['sem_fim']} chegou sem registro do fim da descarga"
    blocos = [p.kpis([
        {"rotulo": "No cliente agora", "valor": p.inteiro(rs["no_cliente"]),
         "estado": "neutro",
         "sub": "chegaram e aguardam o registro do fim da descarga"},
        {"rotulo": "Em viagem", "valor": p.inteiro(rs["em_viagem"]),
         "estado": "neutro", "sub": "saíram e ainda não chegaram"},
        {"rotulo": "Carregando e programadas",
         "valor": p.inteiro(rs["na_origem"] + rs["programada"]), "estado": "neutro",
         "sub": f"{rs['na_origem']} carregando · {rs['programada']} para as "
                f"próximas {HORIZONTE_PROGRAMADA_H} h"},
        {"rotulo": "Descarregadas hoje", "valor": p.inteiro(rs["descarregada"]),
         "estado": "warn" if rs["descarregada_acima"] else "ok",
         "sub": desc_sub},
    ])]

    if not d["contrato_lido"]:
        blocos.append(p.paragrafo(
            "O contrato de carência não pôde ser lido nesta rodada: as horas "
            "paradas estão em branco, e não zeradas.", destaque=True))

    for g in d["grupos"]:
        n = len(g["cargas"])
        hint = f"{n} carga{'s' if n != 1 else ''}"
        if g["carencia_h"] is not None:
            hint += f" · carência de {hm(g['carencia_h'])} na descarga"
        blocos.append(p.secao(f"{g['mercadoria']} → {g['destinatario']}", hint))
        blocos.append(p.tabela(["Veículo", "Janelas", "Situação", "No cliente"],
                               [_celulas(c) for c in g["cargas"]], alinha_dir=(3,)))

    if not d["cargas"]:
        blocos.append(p.paragrafo("Nenhuma carga no ar, programada para as "
                                  f"próximas {HORIZONTE_PROGRAMADA_H} h ou "
                                  "descarregada hoje."))

    blocos.append(p.secao("Como ler"))
    blocos.append(p.paragrafo(
        "A situação de cada carga vem do registro mais recente entre os "
        "registros da operação, o manifesto eletrônico e o computador de bordo "
        "do veículo — a fonte vai ao lado de cada horário. A janela é a "
        "combinada na programação. No cliente: da chegada ao fim da descarga, "
        "contra a carência do contrato para aquela mercadoria; horas paradas "
        "são o que passa da carência, e só são contadas quando o fim da "
        "descarga está registrado. Permanência acima de 24 h aparece como n/d. "
        "O link “Ver onde está a carga” abre a página de rastreio da Sulista, "
        "sem senha, e vale 20 dias; ele aparece quando a carga já tem CT-e."
        + (" A planilha anexa traz as mesmas cargas no formato de sempre."
           if anexar else "")))

    texto = [f"Monitoramento de cargas — {cliente} — {t:%d/%m %H:%M}{filtro}", "",
             f"No cliente: {rs['no_cliente']}"
             f" · Em viagem: {rs['em_viagem']} · Carregando: {rs['na_origem']}"
             f" · Programadas: {rs['programada']} · Descarregadas hoje: {rs['descarregada']}",
             ""]
    for g in d["grupos"]:
        texto.append(f"{g['mercadoria']} → {g['destinatario']}")
        for c in g["cargas"]:
            texto += _linha_texto(c)
        texto.append("")

    partes = [f"{rs['no_cliente']} no cliente", f"{rs['em_viagem']} em viagem",
              f"{rs['descarregada']} descarregada{'s' if rs['descarregada'] != 1 else ''}"]
    assunto = (f"Monitoramento de cargas · {cliente[:40]} · {t:%d/%m %Hh%M} — "
               + ", ".join(partes))

    anexos = []
    if anexar and d["cargas"]:
        anexos.append({"nome": nome_arquivo(d), "conteudo": pm.gerar(d)})
    return {"assunto": assunto,
            "html": p.documento(titulo, blocos, subtitulo=sub, origem=d["fonte"]),
            "texto": "\n".join(texto), "vazio": not d["cargas"],
            "anexos": anexos, "resumo": rs}


# ═══════════════════════════════════════════════════════════ A RODADA ═══════

ORIGEM = "monitoramento"


def rodar(m: dict, *, ensaio: bool = False, forcado: bool = False,
          enviar=None, montar_=None, registrar=None) -> str:
    """UMA rodada de UM monitoramento. Devolve a linha do log. Nunca levanta.

    As três respostas de todo aviso automático da casa, e nesta ordem:
    RECUSA quando não conseguiu ler (nada vai ao cliente, a passagem é falha);
    CALA quando não há carga no dia; MANDA no resto. A passagem é marcada nas
    três — sem ela a tarefa de 15 em 15 min reenviaria a mesma rodada.
    """
    from api.correio.envio import enviar as _enviar
    enviar = enviar or _enviar
    montar_ = montar_ or montar
    registrar = registrar or registrar_execucao
    rot = f"#{m['id']} {m.get('cliente_nome') or m['cliente_raiz']}"
    try:
        r = montar_(m["cliente_raiz"], tuple(m.get("mercadorias") or ()),
                    anexar=bool(m.get("anexar_planilha", True)))
    except Exception as exc:  # noqa: BLE001
        # TIPO da exceção, nunca o texto: mensagem do psycopg carrega trecho
        # da consulta, e consulta com CNPJ dentro é dado de cliente no log.
        if not ensaio:
            registrar(m["id"], f"falhou: não leu a operação ({type(exc).__name__}) "
                               "— nada enviado ao cliente")
        return f"FALHA {rot}: não leu a operação ({type(exc).__name__}) — nada enviado"
    if r["vazio"]:
        if not ensaio:
            registrar(m["id"], "sem carga no dia — não enviado")
        return f" --   {rot}: sem carga no dia, não enviado"
    if ensaio:
        return f" .    {rot}: enviaria para {m['destinatarios']} — “{r['assunto']}”"
    res = enviar(m["destinatarios"], r["assunto"], r["texto"], corpo_html=r["html"],
                 usuario=ORIGEM, origem=f"{ORIGEM}:{m['cliente_raiz']}"
                 + (":forcado" if forcado else ""),
                 anexos=r["anexos"], responder_para=m.get("responder_para") or None)
    registrar(m["id"], "enviado" if res["ok"] else f"falhou: {res['erro'][:150]}")
    if res["ok"]:
        return f"OK   {rot} → {m['destinatarios']}"
    return f"FALHA {rot} — {res['erro'][:120]}"


__all__ = ["validar", "listar", "gravar", "remover", "registrar_execucao",
           "estado", "dados", "montar", "rodar", "hm", "DIAS"]
