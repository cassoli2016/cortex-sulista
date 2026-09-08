# -*- coding: utf-8 -*-
"""A caixa e os documentos no banco da casa — e as regras que os protegem.

Este módulo é PURO sobre o banco: nada aqui fala com a SEFAZ. Quem fala é
`distribuicao.py`, e a separação é o que permite testar as duas regras difíceis
(o resumo que vira documento, e o NSU que só avança) sem rede nenhuma.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .. import pglocal

log = logging.getLogger("cortex.sefaz")

# Redirecionado pelos testes para o schema descartável (fixture `esquema_pg`).
# Um ponto só para esquecer — e esquecer aqui escreve em PRODUÇÃO.
ESQUEMA: str | None = None

#: NSU tem 15 dígitos, zero à esquerda. Comparar como TEXTO só funciona porque
#: o zero à esquerda é obrigatório — e é por isso que ele nunca é guardado como
#: inteiro: `'000000000000012' < '000000000000100'` é verdade, `12 < 100`
#: também, mas `'12' < '100'` é FALSO. Um `int()` no meio do caminho e a
#: varredura passa a achar que já leu o que não leu.
NSU_ZERO = "0" * 15


def _esq() -> str | None:
    return ESQUEMA


def nsu(valor) -> str:
    """Normaliza para os 15 dígitos com zero à esquerda."""
    d = re.sub(r"[^0-9]", "", str(valor or ""))
    return d.rjust(15, "0")[-15:] if d else NSU_ZERO


# ------------------------------------------------------------------ a caixa

def caixa(cnpj: str) -> dict | None:
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM dfe_caixa WHERE cnpj = %s", (cnpj,))
        r = cur.fetchone()
        return dict(r) if r else None


def caixas(so_ativas: bool = True) -> list[dict]:
    sql = "SELECT * FROM dfe_caixa"
    if so_ativas:
        sql += " WHERE ativo"
    sql += " ORDER BY cnpj"
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def abrir_caixa(cnpj: str, apelido: str = "", uf: str = "") -> dict:
    """Registra um CNPJ na recolha. Idempotente: reabrir NÃO zera o NSU.

    Zerar seria reler meses de documento e queimar a cota do serviço por um
    clique repetido — e o `DO NOTHING` é o que impede isso.
    """
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dfe_caixa (cnpj, apelido, uf) VALUES (%s, %s, %s) "
            "ON CONFLICT (cnpj) DO UPDATE SET apelido = EXCLUDED.apelido, "
            "uf = coalesce(EXCLUDED.uf, dfe_caixa.uf), ativo = true",
            (cnpj, apelido or None, (uf or "").upper()[:2] or None))
        conn.commit()
    return caixa(cnpj)


def marcar_consulta(cnpj: str, *, ultimo_nsu: str | None = None,
                    max_nsu: str | None = None, cstat: str = "",
                    motivo: str = "") -> None:
    """Grava o resultado de UM lote. Chamado a cada lote, não no fim.

    O NSU SÓ AVANÇA. Um lote que volte com NSU menor (a SEFAZ repetindo, uma
    resposta fora de ordem, um retry) não pode fazer a varredura andar para
    trás — seria reler o que já está guardado e, pior, ficar em laço. A guarda
    é aqui, no `greatest`, e não em quem chama: quem chama esquece.
    """
    campos = ["ultima_consulta = now()", "ultimo_cstat = %s", "ultimo_motivo = %s"]
    args: list = [cstat or None, (motivo or None)]
    # O CONTADOR DE REINCIDENCIA, no MESMO update: o castigo da SEFAZ cresce a
    # cada 656 seguido, e a espera da casa precisa crescer junto. Zera em
    # qualquer resposta que nao seja 656 -- inclusive no 137 ("nada novo"),
    # porque ele prova que a porta voltou a abrir.
    campos.append("freios_seguidos = CASE WHEN %s THEN freios_seguidos + 1 ELSE 0 END")
    args.append(cstat == "656")
    if ultimo_nsu is not None:
        campos.append("ultimo_nsu = greatest(ultimo_nsu, %s)")
        args.append(nsu(ultimo_nsu))
    if max_nsu is not None:
        # O FIM DA FILA TAMBEM NAO ANDA PARA TRAS, e isto custou uma medicao
        # errada em 08/09/2026: numa REJEICAO (656) a SEFAZ devolveu
        # `maxNSU` = `ultNSU` = o nosso proprio ponteiro, e a gravacao direta
        # apagou o valor bom (1.144.085 virou 1.109.412). A tela passou a dizer
        # "falta 0" com 35 mil documentos na fila -- e "falta 0" e a frase que
        # faz alguem parar de olhar.
        #
        # E o mesmo defeito do ponteiro, um campo ao lado: CAMPO VINDO DE
        # RESPOSTA DE ERRO DESCREVE O SERVIDOR, NAO O QUE VOCE CONSUMIU. A
        # correcao de ontem tratou `ultimo_nsu` e deixou este passar.
        campos.append("max_nsu = greatest(coalesce(max_nsu, %s), %s)")
        args.extend([nsu(max_nsu), nsu(max_nsu)])
    args.append(cnpj)
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("UPDATE dfe_caixa SET " + ", ".join(campos)
                    + " WHERE cnpj = %s", tuple(args))
        conn.commit()


# ------------------------------------------------------------- documentos

def gravar(cnpj: str, doc: dict) -> str:
    """Grava um documento do lote. Devolve 'novo', 'completado' ou 'repetido'.

    DUAS REGRAS, E AS DUAS JÁ CUSTARIAM CARO SEM TESTE:

    1. **Idempotente por (cnpj, nsu).** Reler um trecho da sequência é normal —
       recomeço depois de perder o controle, varredura manual de um NSU
       específico. Sem a chave, a segunda leitura duplicaria a nota inteira e o
       total de compras do mês dobraria de um jeito PLAUSÍVEL.

    2. **Resumo NUNCA sobrescreve documento completo.** O mesmo NSU chega como
       `resNFe` (chave, emitente, valor) antes da manifestação e como `procNFe`
       (a nota inteira) depois dela. Se uma releitura anterior à manifestação
       chegasse por cima da posterior, a casa perderia o XML — que é
       exatamente o que ela tem obrigação de guardar por cinco anos. O
       `WHERE NOT dfe_documento.completo OR EXCLUDED.completo` é essa regra.
    """
    d = dict(doc)
    d["nsu"] = nsu(d.get("nsu"))
    # ÚLTIMA TRINCHEIRA: documento sem XML não entra. `leitura.descomprimir()`
    # já recusa vazio, e esta linha existe porque a de lá já falhou uma vez —
    # 510 linhas com `xml = ''` em 07/09/2026, com contagem certa e tela cheia.
    # A guarda mais barata contra "ausência com aparência de presença" é a
    # que fica no lugar onde a ausência viraria permanente.
    if not (d.get("xml") or "").strip():
        raise ValueError(
            "documento sem XML (cnpj %s, NSU %s, esquema %r) — gravar isto "
            "criaria uma linha que PARECE guardada e não está"
            % (cnpj, d["nsu"], d.get("esquema")))
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT completo FROM dfe_documento WHERE cnpj=%s AND nsu=%s",
                    (cnpj, d["nsu"]))
        antes = cur.fetchone()
        cur.execute(
            """INSERT INTO dfe_documento
                 (cnpj, nsu, esquema, tipo, chave, emitente, emitente_nome,
                  destinatario, valor, emitido_em, situacao, completo, xml,
                  descricao, evento_tipo)
               VALUES (%(cnpj)s, %(nsu)s, %(esquema)s, %(tipo)s, %(chave)s,
                       %(emitente)s, %(emitente_nome)s, %(destinatario)s,
                       %(valor)s, %(emitido_em)s, %(situacao)s, %(completo)s,
                       %(xml)s, %(descricao)s, %(evento_tipo)s)
               ON CONFLICT (cnpj, nsu) DO UPDATE SET
                 esquema = EXCLUDED.esquema, tipo = EXCLUDED.tipo,
                 chave = coalesce(EXCLUDED.chave, dfe_documento.chave),
                 emitente = coalesce(EXCLUDED.emitente, dfe_documento.emitente),
                 emitente_nome = coalesce(EXCLUDED.emitente_nome,
                                          dfe_documento.emitente_nome),
                 destinatario = coalesce(EXCLUDED.destinatario,
                                         dfe_documento.destinatario),
                 valor = coalesce(EXCLUDED.valor, dfe_documento.valor),
                 emitido_em = coalesce(EXCLUDED.emitido_em,
                                       dfe_documento.emitido_em),
                 situacao = coalesce(EXCLUDED.situacao, dfe_documento.situacao),
                 descricao = coalesce(EXCLUDED.descricao, dfe_documento.descricao),
                 evento_tipo = coalesce(EXCLUDED.evento_tipo, dfe_documento.evento_tipo),
                 completo = dfe_documento.completo OR EXCLUDED.completo,
                 xml = EXCLUDED.xml,
                 recebido_em = now()
               WHERE NOT dfe_documento.completo OR EXCLUDED.completo""",
            {"cnpj": cnpj, "nsu": d["nsu"], "esquema": d.get("esquema"),
             "tipo": d.get("tipo") or "desconhecido", "chave": d.get("chave"),
             "emitente": d.get("emitente"),
             "emitente_nome": d.get("emitente_nome"),
             "destinatario": d.get("destinatario"), "valor": d.get("valor"),
             "emitido_em": d.get("emitido_em"), "situacao": d.get("situacao"),
             "completo": bool(d.get("completo")), "xml": d.get("xml") or "",
             "descricao": d.get("descricao"),
             "evento_tipo": d.get("evento_tipo")})
        conn.commit()
    if antes is None:
        return "novo"
    return "completado" if (not antes["completo"] and d.get("completo")) else "repetido"


#: Eventos que MUDAM a validade da nota. O `110111` é o cancelamento; o
#: `110112` é a carta de correção, que altera o documento mas não o derruba.
#:
#: SEM ISTO A TELA MOSTRA COMO VÁLIDA UMA NOTA CANCELADA. O cancelamento chega
#: como documento SEPARADO, com NSU próprio, e a nota original continua no
#: banco exatamente como estava — nada nela muda. Quem olhasse a linha da nota
#: veria "Autorizada" para sempre.
# =============================== as DUAS portas, numa lista só na LEITURA
#
# `dfe_documento` é a caixa da SEFAZ; `dfe_arquivo` é o XML que chega por fora
# (hoje, o e-mail `xml@sulista.com.br`). Elas são tabelas separadas porque o
# que as identifica é diferente — lá é o cursor `(cnpj, nsu)`, aqui é o
# `sha256` do arquivo —, e enfiar as duas numa só corromperia o cursor da
# recolha com números inventados.
#
# Mas quem opera não faz duas perguntas. Ele faz uma: **quais documentos eu
# tenho?** Por isso a união vive na leitura, e toda linha diz de ONDE veio: o
# que a SEFAZ entregou vale o que a SEFAZ garante; o que chegou por e-mail vale
# o que vale quem mandou, e a tela não pode apagar essa diferença.
_UNIAO = """
  SELECT cnpj, nsu, esquema, tipo, chave, emitente, emitente_nome,
         destinatario, valor::float8 AS valor, emitido_em, situacao, completo,
         recebido_em, descricao, evento_tipo,
         'sefaz'::text AS origem, NULL::text AS sha256, NULL::text AS remetente
    FROM dfe_documento
  UNION ALL
  SELECT NULL::varchar(14), NULL::varchar(15), esquema, tipo, chave, emitente,
         emitente_nome, destinatario, valor::float8, emitido_em, situacao,
         completo, recebido_em, descricao, evento_tipo,
         origem, sha256, remetente
    FROM dfe_arquivo
"""

_SO_SEFAZ = """
  SELECT cnpj, nsu, esquema, tipo, chave, emitente, emitente_nome,
         destinatario, valor::float8 AS valor, emitido_em, situacao, completo,
         recebido_em, descricao, evento_tipo,
         'sefaz'::text AS origem, NULL::text AS sha256, NULL::text AS remetente
    FROM dfe_documento
"""

#: A resposta é por SCHEMA, e não por processo: a suíte troca de schema a cada
#: teste (`esquema_pg`), e uma memória global diria "a tabela existe" dentro de
#: um schema onde ela não existe.
_TEM_ARQUIVO: dict = {}


def tem_tabela_arquivo() -> bool:
    """A tabela `dfe_arquivo` já existe NESTE schema?

    POR QUE ISTO EXISTE, e não é excesso de cuidado: **o `autodeploy.ps1` NÃO
    roda `migrar_schema.py`** (conferido em 05/09/2026, e há um `tem_coluna_*`
    em `api/auth.py` pela mesma razão). Entre o código chegar em produção e
    alguém aplicar a migration há uma janela de minutos ou de dias — e nela
    toda consulta que citasse `dfe_arquivo` derrubaria a tela de Notas de
    Entrada INTEIRA, inclusive a metade que não tem nada a ver com e-mail.

    Uma tela que já funcionava não pode cair por causa de uma porta nova que
    ainda não abriu.
    """
    esq = _esq()
    if esq not in _TEM_ARQUIVO:
        try:
            with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM dfe_arquivo LIMIT 1")
                cur.fetchall()
            _TEM_ARQUIVO[esq] = True
        except Exception as exc:  # noqa: BLE001
            if not pglocal.sem_tabela(exc):
                # Banco fora do ar não é "tabela não existe": não se memoiza,
                # senão a resposta errada sobrevive ao problema.
                raise
            _TEM_ARQUIVO[esq] = False
    return _TEM_ARQUIVO[esq]


def fonte() -> str:
    return _UNIAO if tem_tabela_arquivo() else _SO_SEFAZ


EVENTO_CANCELA = "110111"
EVENTO_CARTA = "110112"


def _filtros(cnpj: str | None = None, *, so_incompletos: bool = False,
             tipo: str = "", de: str = "", ate: str = "", busca: str = "",
             so_completos: bool = False, origem: str = "") -> tuple[str, list]:
    """O WHERE da lista, em UM lugar só.

    Ele nasceu dentro de `documentos()` e saiu quando a paginação chegou: a
    contagem tem de usar EXATAMENTE o mesmo recorte que a página, senão o
    rodapé diz "1 de 12" e a página 12 vem vazia. Dois WHEREs escritos à mão
    para a mesma pergunta divergem no primeiro filtro novo — e divergem em
    silêncio, porque cada um continua certo sozinho.
    """
    onde, args = [], []
    if cnpj:
        # FILTRAR POR FILIAL TIRA O QUE VEIO POR E-MAIL, e isso é uma
        # afirmação verdadeira, não um efeito colateral: o documento que chega
        # por e-mail chega justamente porque a Sulista NÃO é parte nele — ele
        # não pertence à caixa de filial nenhuma, e dizer que pertence seria
        # inventar um vínculo. A tela avisa disso no ⓘ do card.
        onde.append("cnpj = %s")
        args.append(cnpj)
    if origem:
        onde.append("origem = %s")
        args.append(origem)
    if so_incompletos:
        onde.append("NOT completo")
    if so_completos:
        onde.append("completo")
    if tipo:
        onde.append("tipo = %s")
        args.append(tipo)
    if de:
        onde.append("emitido_em >= %s::date")
        args.append(de)
    if ate:
        # `< ate + 1 dia`: com timestamp, `<= '2026-09-30'` para na meia-noite
        # e perde o dia 30 inteiro.
        onde.append("emitido_em < (%s::date + 1)")
        args.append(ate)
    if busca:
        alvo = re.sub(r"[^0-9]", "", busca)
        if len(alvo) == 44:
            # CHAVE COLADA INTEIRA: casa exato, e não por `LIKE`. Chave é
            # identidade, e `%chave%` num índice de 44 dígitos varre a tabela
            # para achar exatamente uma linha.
            onde.append("chave = %s")
            args.append(alvo)
        else:
            onde.append("(emitente_nome ILIKE %s OR chave ILIKE %s "
                        "OR descricao ILIKE %s)")
            args.extend(["%%%s%%" % busca] * 3)
    return (" WHERE " + " AND ".join(onde)) if onde else "", args


def contar(cnpj: str | None = None, **kw) -> int:
    """Quantos documentos o filtro alcança — o denominador da paginação.

    MEDIDO antes de escolher: `count(*)` sobre a união inteira custa 95 ms com
    201 mil linhas, e 14 ms com um mês de recorte. É barato o bastante para o
    rodapé poder dizer "de quantos" — que é a informação que transforma uma
    lista cortada em silêncio numa lista que se sabe percorrer.
    """
    onde, args = _filtros(cnpj, **kw)
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*)::int AS n FROM (" + fonte() + ") d" + onde,
                    tuple(args))
        return dict(cur.fetchone() or {}).get("n") or 0


def documentos(cnpj: str | None = None, *, limite: int = 200, pulando: int = 0,
               so_incompletos: bool = False, tipo: str = "",
               de: str = "", ate: str = "", busca: str = "",
               so_completos: bool = False, origem: str = "") -> list[dict]:
    """Os documentos, SEM o XML. O XML sai por `xml_de()`, um a um.

    Não é economia de bytes: é que uma lista de 200 notas com o XML dentro são
    ~2 MB numa resposta que a tela usa só para desenhar linhas — e a serialização
    disso é o tipo de custo que vira lentidão sem ninguém saber de onde veio.

    `busca` procura no NOME do emitente e na CHAVE. Chave se cola inteira do
    e-mail ou do romaneio; nome se digita pela metade. As duas entram no mesmo
    campo porque quem procura não separa as duas coisas na cabeça.
    """
    onde, args = _filtros(cnpj, so_incompletos=so_incompletos, tipo=tipo,
                          de=de, ate=ate, busca=busca,
                          so_completos=so_completos, origem=origem)
    sql = "SELECT * FROM (" + fonte() + ") d" + onde
    # A SEGUNDA CHAVE DE ORDEM É `recebido_em`, e não o NSU: metade das linhas
    # não tem NSU nenhum. Ordenar por uma coluna que é NULL para uma das portas
    # embaralharia justamente o empate que a ordenação existe para desfazer.
    #
    # E A TERCEIRA É UM IDENTIFICADOR ÚNICO, que é o que torna a ordem TOTAL.
    # Sem ela, dois documentos com a mesma emissão e o mesmo recebimento podem
    # trocar de lugar entre uma página e outra — e aí um aparece duas vezes e o
    # outro some, sem erro nenhum. Com 201 mil linhas importadas no mesmo lote
    # (mesmo `recebido_em` até o microssegundo) isso deixa de ser hipótese.
    #
    # NÃO É A CHAVE DE ACESSO, e essa distinção custou uma sabotagem verde: a
    # nota, o resumo dela e o cancelamento dela têm a MESMA chave — são três
    # linhas com o mesmo valor, e um desempate que empata não desempata. O que
    # distingue é a chave primária de cada lado: `sha256` no arquivo,
    # `(cnpj, nsu)` na caixa da SEFAZ.
    sql += (" ORDER BY emitido_em DESC NULLS LAST, recebido_em DESC, "
            "coalesce(sha256, cnpj || nsu) DESC LIMIT %s OFFSET %s")
    args.append(max(1, min(int(limite), 2000)))
    args.append(max(0, int(pulando)))
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        linhas = [dict(r) for r in cur.fetchall()]
        # OS EVENTOS DE CADA NOTA, numa consulta só. Um `SELECT` por linha
        # seriam 200 idas ao banco para desenhar uma tela.
        chaves = [l["chave"] for l in linhas if l.get("chave")]
        eventos: dict[str, list[dict]] = {}
        if chaves:
            # OS EVENTOS TAMBÉM VÊM DAS DUAS PORTAS. Um cancelamento
            # reencaminhado por e-mail cancela a nota do mesmo jeito — ignorá-lo
            # deixaria a tela mostrando "Autorizada" numa nota que não existe
            # mais, que é o defeito que esta parte do código existe para evitar.
            cur.execute(
                "SELECT chave, evento_tipo, descricao, emitido_em FROM ("
                + fonte() + ") d WHERE tipo = 'evento' AND chave = ANY(%s) "
                "ORDER BY emitido_em", (chaves,))
            for e in cur.fetchall():
                eventos.setdefault(e["chave"], []).append(dict(e))
        saida = []
        for x in linhas:
            evs = eventos.get(x.get("chave") or "", [])
            # A SITUAÇÃO EFETIVA vem do EVENTO, e não do campo da nota. O
            # cancelamento chega como documento separado e não muda nada na
            # linha original — sem isto a tela mostra "Autorizada" para sempre
            # numa nota cancelada.
            x["cancelada"] = any(e["evento_tipo"] == EVENTO_CANCELA for e in evs)
            x["tem_carta"] = any(e["evento_tipo"] == EVENTO_CARTA for e in evs)
            x["eventos"] = [{"tipo": e["evento_tipo"], "descricao": e["descricao"],
                             "em": e["emitido_em"].isoformat()
                                   if isinstance(e["emitido_em"], datetime) else None}
                            for e in evs]
            # Serialização converte no LIMITE do módulo: `datetime` estoura no
            # `render()` do JSONResponse, DEPOIS do try/except da rota.
            for c in ("emitido_em", "recebido_em"):
                if isinstance(x.get(c), datetime):
                    x[c] = x[c].isoformat()
            saida.append(x)
        return saida


def xml_de(cnpj: str, nsu_: str) -> str | None:
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT xml FROM dfe_documento WHERE cnpj=%s AND nsu=%s",
                    (cnpj, nsu(nsu_)))
        r = cur.fetchone()
        return r["xml"] if r else None


#: Teto do pacote. Nao e limite de banda: e que um ZIP de 50 mil XML leva
#: minutos para montar, e a rota e sincrona -- quem pediu fica olhando a tela
#: parada sem saber se travou. Um mes de operacao cabe folgado aqui.
MAX_PACOTE = 5000


def _fonte_com_xml() -> str:
    """A união COM o XML dentro — só o pacote precisa disso.

    `documentos()` de propósito NÃO traz o XML: uma lista de 200 notas com o
    documento inteiro em cada linha são ~2 MB numa resposta que a tela usa só
    para desenhar linhas.
    """
    if not tem_tabela_arquivo():
        return ("SELECT cnpj, nsu, tipo, chave, emitido_em, xml, completo, "
                "'sefaz'::text AS origem, NULL::text AS sha256 "
                "FROM dfe_documento")
    return ("SELECT cnpj, nsu, tipo, chave, emitido_em, xml, completo, "
            "'sefaz'::text AS origem, NULL::text AS sha256 FROM dfe_documento "
            "UNION ALL "
            "SELECT NULL::varchar(14), NULL::varchar(15), tipo, chave, "
            "emitido_em, xml, completo, origem, sha256 FROM dfe_arquivo")


def para_pacote(cnpj: str | None = None, de: str = "", ate: str = "",
                so_completos: bool = True) -> list[dict]:
    """Os documentos de um periodo COM o XML, para virar pacote .zip.

    `so_completos=True` por padrao, e e a decisao que importa: um pacote com
    resumo dentro seria um arquivo que PARECE a nota e nao e. Quem abre um zip
    de XML espera documento fiscal, nao ficha de tres linhas -- e o contador
    que receber isso vai descobrir na hora de escriturar.

    A data de corte e a de EMISSAO, nao a de recebimento: e por competencia que
    a contabilidade pede, e nota emitida dia 30 que chegou dia 2 pertence ao
    mes 30.
    """
    onde, args = ["coalesce(xml,'') <> ''"], []
    if cnpj:
        onde.append("cnpj = %s")
        args.append(cnpj)
    if so_completos:
        onde.append("completo")
    if de:
        onde.append("emitido_em >= %s::date")
        args.append(de)
    if ate:
        # `< ate + 1 dia` e nao `<= ate`: com timestamp, `<= '2026-09-30'`
        # significa ate a MEIA-NOITE do dia 30 e perde o dia inteiro.
        onde.append("emitido_em < (%s::date + 1)")
        args.append(ate)
    # O PACOTE LEVA AS DUAS PORTAS. Quem baixa o mês para a contabilidade
    # quer o mês inteiro — e um XML que chegou por e-mail é documento fiscal
    # igual. O nome do arquivo dentro do zip é a CHAVE, que é a mesma dos dois
    # lados: a origem não muda o que o contador precisa escriturar.
    sql = ("SELECT cnpj, nsu, tipo, chave, emitido_em, xml, origem, sha256 "
           "FROM (" + _fonte_com_xml() + ") d WHERE " + " AND ".join(onde)
           + " ORDER BY emitido_em, chave LIMIT %s")
    args.append(MAX_PACOTE)
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(args))
        return [dict(r) for r in cur.fetchall()]


def resumo(cnpj: str | None = None) -> dict:
    """Os escalares da tela e do Copiloto — sem chave, sem CNPJ de fornecedor.

    `pendentes` é o número que decide alguma coisa: documento que ainda está só
    no resumo é XML que a casa NÃO tem e tem obrigação de guardar.
    """
    # `FILTER (WHERE ...)` aqui É PERMITIDO: este é o banco da CASA
    # (PostgreSQL 16). A proibição do `FILTER` vale para o AVA, que é 9.3 —
    # confundir os dois bancos custa caro nos dois sentidos.
    onde, args = ("WHERE cnpj = %s", (cnpj,)) if cnpj else ("", ())
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*)::int AS total, "
            "  count(*) FILTER (WHERE NOT completo)::int AS pendentes, "
            "  count(*) FILTER (WHERE tipo = 'nfe')::int AS nfe, "
            "  count(*) FILTER (WHERE tipo = 'cte')::int AS cte, "
            "  count(*) FILTER (WHERE tipo = 'evento')::int AS eventos, "
            "  max(recebido_em) AS ultimo_recebido "
            "FROM dfe_documento " + onde, args)
        d = dict(cur.fetchone() or {})
        # A CONTA DA OUTRA PORTA VEM SEPARADA, e não somada. `pendentes`
        # significa "a SEFAZ ainda não entregou o XML completo, falta a
        # ciência" — um arquivo de e-mail sem protocolo não é isso, é outra
        # coisa (documento que a pessoa mandou antes de a nota ser autorizada,
        # ou exportado sem o protocolo). Somar os dois faria o KPI que decide
        # a obrigação de guarda dizer um número que não decide nada.
        d["fora_da_sefaz"] = 0
        d["por_origem"] = {}
        if tem_tabela_arquivo():
            # POR ORIGEM, e nao um numero so. Enquanto eram duas portas
            # (e-mail e envio na tela) um total bastava; com o acervo do ERP
            # dentro, um campo chamado `email` contando a tabela inteira faria
            # o KPI dizer "189 mil por e-mail" -- verdadeiro na soma e falso
            # na frase.
            cur.execute("SELECT origem, count(*)::int AS n, "
                        "  count(*) FILTER (WHERE NOT completo)::int AS sem_prot "
                        "FROM dfe_arquivo GROUP BY origem")
            for linha in cur.fetchall():
                e = dict(linha)
                d["por_origem"][e["origem"]] = e["n"]
                d["fora_da_sefaz"] += e["n"]
                d["sem_protocolo"] = (d.get("sem_protocolo") or 0) + (e["sem_prot"] or 0)
    if isinstance(d.get("ultimo_recebido"), datetime):
        d["ultimo_recebido"] = d["ultimo_recebido"].isoformat()
    return d
