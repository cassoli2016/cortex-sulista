# api/contrapartida/xml_email.py
"""Manda para a contabilidade o XML dos CT-e de contrapartida de PRODUÇÃO.

O QUE ESTA ROTINA FAZ, E O QUE ELA DELIBERADAMENTE NÃO FAZ
==========================================================
Cada CT-e autorizado em produção gera um `cteProc` — o XML assinado MAIS o
protocolo da SEFAZ. É esse arquivo que a contabilidade escritura; o documento
sozinho, sem protocolo, não prova autorização nenhuma. A rotina pega o que
ainda não saiu e manda por e-mail, **um XML por anexo**.

Não zipa de propósito: a caixa `xml@` costuma ser lida por um importador
automático, e importador de caixa postal procura anexo `.xml`. Um `.zip` seria
mais econômico e passaria despercebido — a mensagem chegaria, o arquivo não
entraria em lugar nenhum, e ninguém descobriria até a apuração.

**PRODUÇÃO E SÓ PRODUÇÃO.** Homologação é o ambiente de teste da SEFAZ:
documento autorizado lá não tem valor fiscal e não é escriturado. Mandar um
para quem escritura é pior que não mandar nenhum — o erro entra na
contabilidade e sai de lá por retificação.

AS QUATRO GUARDAS
-----------------
1. **PADRÃO DESLIGADO.** Ausência de decisão nunca significa "manda documento
   fiscal para fora". Ligar entra na auditoria com autor e data, como todo
   interruptor deste módulo.

2. **IDEMPOTÊNCIA POR CHAVE.** `cte_xml_email` tem a chave do CT-e como
   PRIMARY KEY. XML repetido não duplica documento, mas gera conferência
   manual toda vez que alguém tenta entender por que chegou de novo — e numa
   caixa que um robô lê, gera reimportação.

3. **CORTE.** O que já existia em produção quando a rotina nasceu fica de
   fora. Despejar o acumulado inteiro numa caixa que ninguém avisou é a melhor
   forma de o primeiro e-mail ser tratado como spam — e junto com ele os
   seguintes, que são os que importam.

4. **TETO DE TENTATIVAS.** Falha permanente (endereço errado, anexo recusado)
   pararia de ser útil e continuaria sendo retentada a cada rodada do lote. Ao
   bater o teto o documento fica PARADO e **aparece na tela com o erro** —
   nunca sai da fila em silêncio. `reenfileirar()` devolve todos para a fila
   depois que a causa foi consertada.

POR QUE O GATILHO É O LOTE, E NÃO UM HORÁRIO
--------------------------------------------
A emissão em produção já roda por uma rotina agendada (`lote.processar_lote`).
Pendurar o e-mail nela significa que o XML sai minutos depois de existir, sem
um segundo agendador para instalar, configurar e esquecer de ligar. E como a
fila é reconstruída a cada rodada — "o que ainda não saiu" —, uma falha de
SMTP se conserta sozinha na rodada seguinte, sem ninguém reprocessar nada.
"""
from __future__ import annotations

import logging
from datetime import datetime

from api.contrapartida import cadastro, emissao

log = logging.getLogger("cortex.contrapartida.xml_email")

# A caixa da contabilidade. É padrão, não constante: quem administra troca na
# tela, e a troca fica na auditoria.
DESTINO_PADRAO = "xml@sulista.com.br"

CHAVE_ATIVO = "xml_email_ativo"
CHAVE_DESTINO = "xml_email_destinatarios"
CHAVE_CORTE = "xml_email_corte"

# Anexos por mensagem. Vinte porque é onde a mensagem ainda abre rápido em
# qualquer cliente e o servidor não reclama; o teto de PRODUÇÃO do lote é 50,
# então uma rodada cheia vira três mensagens em vez de uma indigesta.
MAX_ANEXOS = 20

# Documentos por execução. O teto do lote de produção é 50 e este é maior de
# propósito: se uma rodada falhou no SMTP, a seguinte precisa poder mandar o
# atrasado E o novo, senão a fila só cresce.
MAX_POR_EXECUCAO = 100

# Tentativas antes de o documento ficar PARADO. Cinco rodadas do lote é tempo
# suficiente para um servidor voltar do ar; além disso, é problema que não se
# resolve esperando.
MAX_TENTATIVAS = 5

ORIGEM = "contrapartida:xml"


def _conn():
    return cadastro._conn()


# ------------------------------------------------------------ configuração ---

def ativo() -> bool:
    """A rotina está ligada? PADRÃO: não.

    Só a string "1" liga. Lixo na configuração — banco novo, backup restaurado,
    valor editado à mão — cai no desligado, nunca no contrário.
    """
    r = emissao.config_lida(CHAVE_ATIVO)
    return bool(r) and r["valor"] == "1"


def destinatarios() -> str:
    """Para quem vai. Sem registro, a caixa padrão da contabilidade."""
    r = emissao.config_lida(CHAVE_DESTINO)
    return ((r or {}).get("valor") or "").strip() or DESTINO_PADRAO


def corte() -> str:
    """A partir de que momento um documento entra na fila desta rotina.

    Fixado na PRIMEIRA leitura e nunca mais movido: se ele acompanhasse a data
    de hoje, um dia de rotina desligada apagaria da fila os documentos daquele
    dia — e eles são justamente os que alguém iria procurar.

    Gravado com `quem='sistema'` porque ninguém decidiu isto: é o instante em
    que a rotina passou a existir nesta instalação.
    """
    r = emissao.config_lida(CHAVE_CORTE)
    if r and (r.get("valor") or "").strip():
        return r["valor"]
    agora = datetime.now().isoformat(timespec="seconds")
    with emissao._conn_config() as c:
        # ON CONFLICT DO NOTHING e não DO UPDATE: duas execuções simultâneas
        # (o lote e a tela) não podem acabar com cortes diferentes, e a
        # primeira a gravar é a que vale.
        c.execute(
            "INSERT INTO lote_config(chave, valor, quem, quando)"
            " VALUES(%s,%s,%s,%s) ON CONFLICT(chave) DO NOTHING",
            (CHAVE_CORTE, agora, "sistema", agora))
    return (emissao.config_lida(CHAVE_CORTE) or {}).get("valor") or agora


def definir(quem: str, *, ligado: bool | None = None,
            para: str | None = None) -> dict:
    """Liga/desliga e troca o destinatário. Tudo entra na auditoria.

    Os dois campos são opcionais e independentes: a tela salva o formulário
    inteiro, e quem não mexeu no destinatário não pode ter o destinatário
    reescrito por um campo vazio que veio junto.
    """
    if not quem:
        raise ValueError("Informe quem está mudando esta configuração.")

    if para is not None:
        from api.correio import config as cfg
        lista = cfg.separar_destinatarios(para)
        if not lista:
            raise ValueError("Informe ao menos um destinatário para os XML.")
        ruins = [e for e in lista if not cfg.email_valido(e)]
        if ruins:
            raise ValueError("Endereço inválido: " + ", ".join(ruins[:3]))
        valor = ", ".join(lista)
        agora = datetime.now().isoformat(timespec="seconds")
        with emissao._conn_config() as c:
            c.execute(
                "INSERT INTO lote_config(chave, valor, quem, quando)"
                " VALUES(%s,%s,%s,%s) ON CONFLICT(chave) DO UPDATE SET"
                " valor=excluded.valor, quem=excluded.quem,"
                " quando=excluded.quando",
                (CHAVE_DESTINO, valor, quem, agora))
            cadastro._audita(c, quem, "xml_email_destino", "-", valor)

    if ligado is not None:
        # O corte é fixado ANTES de a rotina poder mandar qualquer coisa: sem
        # isto, ligar num banco que já tem produção despejaria o acumulado.
        corte()
        emissao.config_grava(CHAVE_ATIVO, ligado, quem, "xml_email")

    return estado()


# -------------------------------------------------------------------- fila ---

# DISTINCT ON pela chave: uma retransmissão da mesma chave gera OUTRA linha em
# `emissao`, e sem isto o mesmo documento apareceria duas vezes na mesma fila —
# duas leituras do banco, dois anexos idênticos, e o `ON CONFLICT` da marcação
# escondendo o problema em vez de o denunciar. Fica a mais recente.
_PENDENTES_SQL = """
SELECT DISTINCT ON (e.chave)
       e.id, e.chave, e.chave_origem, e.cnpj_emitente, e.serie, e.numero,
       e.quando, e.protocolo, e.xml, e.xml_prot
  FROM emissao e
  LEFT JOIN cte_xml_email m ON m.chave = e.chave
 WHERE e.ambiente = %s
   AND e.cstat = '100'
   AND e.xml IS NOT NULL AND e.xml_prot IS NOT NULL
   AND e.quando >= %s
   AND (m.chave IS NULL OR (m.ok = false AND m.tentativas < %s))
 ORDER BY e.chave, e.id DESC
"""


def pendentes(limite: int = MAX_POR_EXECUCAO) -> list[dict]:
    """XML de produção que ainda não foram para a contabilidade.

    Traz o `xml` e o `xml_prot` junto porque o `cteProc` se monta com os dois e
    não vale a pena voltar ao banco documento a documento — a fila inteira é
    uma consulta só.
    """
    with _conn() as c:
        linhas = [dict(r) for r in c.execute(
            _PENDENTES_SQL, (emissao.PRODUCAO, corte(), MAX_TENTATIVAS))]
    # ordenar por id devolve a ordem cronológica que o DISTINCT ON desfez
    linhas.sort(key=lambda r: r["id"])
    return linhas[:max(0, int(limite))]


def parados() -> list[dict]:
    """Os que bateram o teto de tentativas — a fila que precisa de gente.

    Sem `xml`: aqui a pergunta é "o que não saiu e por quê", e a coluna é
    grande demais para uma tela que só lista.
    """
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT chave, cnpj_emitente, serie, numero, emitido_em,"
            " tentativas, erro, enviado_em FROM cte_xml_email"
            " WHERE ok = false AND tentativas >= %s"
            " ORDER BY emitido_em DESC", (MAX_TENTATIVAS,))]


def _marcar(linhas: list[dict], *, ok: bool, erro: str, para: str) -> None:
    """Registra a tentativa de cada documento da mensagem.

    `tentativas` soma sobre o que já havia (`cte_xml_email.tentativas + 1`) —
    zerar no UPDATE faria o teto nunca ser alcançado e a retentativa virar
    eterna, que é exatamente o que o teto existe para evitar.
    """
    agora = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        for r in linhas:
            c.execute(
                "INSERT INTO cte_xml_email(chave, cnpj_emitente, serie,"
                " numero, emitido_em, tentativas, enviado_em, ok, erro,"
                " destinatarios) VALUES(%s,%s,%s,%s,%s,1,%s,%s,%s,%s)"
                " ON CONFLICT(chave) DO UPDATE SET"
                " tentativas = cte_xml_email.tentativas + 1,"
                " enviado_em = excluded.enviado_em, ok = excluded.ok,"
                " erro = excluded.erro,"
                " destinatarios = excluded.destinatarios",
                (r["chave"], r.get("cnpj_emitente"), r.get("serie"),
                 r.get("numero"), str(r.get("quando") or "")[:19], agora,
                 ok, (erro or "")[:400], para))


def reenfileirar(quem: str) -> dict:
    """Devolve à fila os documentos PARADOS, depois de a causa ser consertada.

    Zera a contagem em vez de apagar a linha: o histórico de que aquele XML já
    falhou cinco vezes é o que explica, meses depois, por que ele chegou à
    contabilidade com atraso.
    """
    if not quem:
        raise ValueError("Informe quem está reenfileirando.")
    with _conn() as c:
        n = c.execute(
            "UPDATE cte_xml_email SET tentativas = 0, erro = NULL"
            " WHERE ok = false AND tentativas >= %s",
            (MAX_TENTATIVAS,)).rowcount
        cadastro._audita(c, quem, "xml_email_reenfileirar", "-",
                         f"{n} documento(s)")
    log.warning("xml para contabilidade: %s documento(s) reenfileirados por %s",
                n, quem)
    return {"reenfileirados": int(n or 0)}


# ------------------------------------------------------------------ envio ---

def _assunto(linhas: list[dict], parte: int, partes: int) -> str:
    dia = str(linhas[0].get("quando") or "")[:10]
    n = len(linhas)
    base = (f"CT-e de contrapartida — {n} XML"
            f"{'s' if n != 1 else ''} — {dia}")
    # A parte no assunto não é enfeite: quem recebe três mensagens no mesmo
    # minuto precisa saber que são três pedaços de uma remessa, e não a mesma
    # mensagem repetida três vezes.
    return base if partes == 1 else f"{base} (parte {parte} de {partes})"


def _corpo(linhas: list[dict], para: str) -> str:
    """O corpo LISTA o que vai anexo.

    Serve para conferência do outro lado e serve à trilha: `correio_envios`
    guarda o corpo, não os anexos, e é por ele que se responde "este XML foi
    mandado?" sem precisar do arquivo.
    """
    linhas_txt = [
        "XML de CT-e de contrapartida emitidos em PRODUÇÃO pela Sulista em "
        "nome dos agregados.",
        "",
        f"Documentos nesta mensagem: {len(linhas)}",
        "Formato: cteProc (XML assinado + protocolo de autorização da SEFAZ).",
        "",
    ]
    for r in linhas:
        linhas_txt.append(
            f"  série {r.get('serie')} nº {r.get('numero')} · "
            f"CNPJ {r.get('cnpj_emitente')} · protocolo "
            f"{r.get('protocolo') or '—'}")
        linhas_txt.append(f"    chave {r['chave']}")
    linhas_txt += [
        "",
        f"Enviado automaticamente pelo CÓRTEX para {para}.",
        "Mensagem gerada por rotina — não responda a este endereço.",
    ]
    return "\n".join(linhas_txt)


def _partes(linhas: list[dict]) -> list[list[dict]]:
    return [linhas[i:i + MAX_ANEXOS]
            for i in range(0, len(linhas), MAX_ANEXOS)]


def enviar_pendentes(quem: str = emissao.IDENTIDADE_SISTEMA, *,
                     limite: int = MAX_POR_EXECUCAO,
                     ensaio: bool = False) -> dict:
    """Manda o que está pendente. NUNCA levanta — o chamador é o lote.

    Uma falha aqui não pode derrubar a emissão: o documento fiscal já existe e
    já está autorizado, e perder o retorno do lote por causa de um servidor de
    e-mail fora do ar transformaria um incômodo em incidente.
    """
    r = {"ok": True, "enviados": 0, "falhas": 0, "mensagens": 0,
         "pendentes": 0, "motivo": "", "destinatarios": "", "erros": []}

    if not ativo():
        r["motivo"] = ("envio de XML para a contabilidade DESLIGADO "
                       "(Gestão › Integrações)")
        return r

    from api.correio import config as cfg

    if not cfg.configurado():
        # Sair ANTES de tentar: uma falha de configuração queimaria uma
        # tentativa de cada documento a cada rodada e, em cinco rodadas,
        # deixaria a fila inteira parada por causa de um campo em branco.
        r["ok"] = False
        r["motivo"] = ("servidor SMTP não configurado — nenhuma tentativa foi "
                       "gasta (Gestão › E-mail)")
        return r

    try:
        fila = pendentes(limite)
    except Exception as exc:  # noqa: BLE001
        log.warning("nao foi possivel ler a fila de XML: %s", exc)
        return {**r, "ok": False, "motivo": f"falha ao ler a fila: "
                                            f"{type(exc).__name__}"}

    para = destinatarios()
    r["destinatarios"] = para
    r["pendentes"] = len(fila)
    if not fila:
        r["motivo"] = "nenhum XML novo de produção"
        return r

    partes = _partes(fila)
    if ensaio:
        r["motivo"] = (f"ensaio: mandaria {len(fila)} XML em {len(partes)} "
                       f"mensagem(ns) para {para}")
        return r

    from api.correio.envio import enviar

    for i, bloco in enumerate(partes, start=1):
        anexos = []
        for linha in bloco:
            anexos.append({
                "nome": f"{linha['chave']}-procCTe.xml",
                # montado a partir do que já veio na consulta: o XML assinado
                # não pode ser reserializado, e `montar_proc` trabalha por
                # texto justamente para não tocar na assinatura
                "conteudo": emissao.montar_proc(linha["xml"],
                                                linha["xml_prot"]),
            })
        try:
            res = enviar(para, _assunto(bloco, i, len(partes)),
                         _corpo(bloco, para), usuario=quem, origem=ORIGEM,
                         anexos=anexos)
        except Exception as exc:  # noqa: BLE001 — contrato: nunca levanta
            res = {"ok": False, "erro": f"falha inesperada: "
                                        f"{type(exc).__name__}"}
        r["mensagens"] += 1
        try:
            _marcar(bloco, ok=bool(res.get("ok")), erro=res.get("erro") or "",
                    para=para)
        except Exception as exc:  # noqa: BLE001
            # Marcar é o que impede o reenvio. Se falhar, o e-mail JÁ saiu e a
            # próxima rodada mandaria de novo — por isso o erro é ALTO no log,
            # e não um aviso perdido.
            log.error("XML enviado mas NAO marcado (risco de reenvio): %s", exc)
            r["erros"].append("envio marcado com falha no banco — pode repetir")

        if res.get("ok"):
            r["enviados"] += len(bloco)
        else:
            r["ok"] = False
            r["falhas"] += len(bloco)
            r["erros"].append(res.get("erro") or "falha desconhecida")
            # Uma mensagem que falhou quase sempre significa servidor fora do
            # ar: insistir com as partes seguintes só multiplica o mesmo erro e
            # gasta uma tentativa de cada documento restante.
            r["motivo"] = ("interrompido na parte "
                           f"{i} de {len(partes)} — as demais ficam para a "
                           "próxima rodada")
            break

    if r["ok"]:
        r["motivo"] = (f"{r['enviados']} XML em {r['mensagens']} "
                       f"mensagem(ns) para {para}")
    log.info("xml para contabilidade: %s", r["motivo"])
    return r


# ------------------------------------------------------------------ tela ---

def estado() -> dict:
    """O que a tela de Gestão mostra. Não levanta: é onde se olha justamente
    quando alguma coisa não está indo."""
    base = {"ativo": False, "destinatarios": DESTINO_PADRAO, "corte": None,
            "quem": None, "quando": None, "pendentes": 0, "parados": 0,
            "enviados": 0, "ultimo_envio": None, "erro_leitura": None,
            "max_anexos": MAX_ANEXOS, "max_tentativas": MAX_TENTATIVAS,
            "destino_padrao": DESTINO_PADRAO}
    try:
        a = emissao.config_lida(CHAVE_ATIVO) or {}
        base.update({"ativo": ativo(), "destinatarios": destinatarios(),
                     "corte": corte(), "quem": a.get("quem"),
                     "quando": a.get("quando")})
        with _conn() as c:
            t = dict(c.execute(
                "SELECT count(*) FILTER (WHERE ok) AS enviados,"
                " count(*) FILTER (WHERE NOT ok AND tentativas >= %s)"
                "     AS parados,"
                " max(enviado_em) FILTER (WHERE ok) AS ultimo"
                " FROM cte_xml_email", (MAX_TENTATIVAS,)).fetchone())
        base.update({"enviados": int(t["enviados"] or 0),
                     "parados": int(t["parados"] or 0),
                     "ultimo_envio": t["ultimo"]})
        base["pendentes"] = len(pendentes(MAX_POR_EXECUCAO))
    except Exception as exc:  # noqa: BLE001
        # o TIPO, nunca o texto: a mensagem do psycopg pode trazer o conninfo
        base["erro_leitura"] = type(exc).__name__
        log.warning("estado do envio de XML ilegivel: %s", exc)
    return base
