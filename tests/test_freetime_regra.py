"""A regra do freetime é UMA, e os dois sotaques dizem a mesma coisa.

`api/freetime.py` existe porque duas telas leem o mesmo contrato e cada uma
tinha inventado a própria saída para o mesmo problema — o SAC sorteava uma
cláusula, a Minha Operação recusava escolher e publicava uma faixa. Elas
discordavam por construção.

Agora a regra mora num lugar só e aparece em dois sotaques: SQL (a estimativa
do SAC roda inteira no ERP, sobre milhares de linhas) e Python (na Minha
Operação as linhas vêm para casa de qualquer jeito). DUAS EXECUÇÕES DO MESMO
TEXTO — e duas execuções que divergem são pior que duas cópias declaradas,
porque ninguém procura a diferença.

Por isso o guard central aqui EXECUTA os dois lados contra o mesmo conjunto de
strings REAIS (colhidas de `sulista.sac_freetimecliente` e de
`coleta.mercadorias` em 10/09/2026) e exige o mesmo resultado. Ele roda a
expressão SQL no PostgreSQL local, que é onde há um banco que a suíte pode
usar; `translate`, `upper`, `btrim` e `regexp_replace` são os mesmos no 16 e no
9.3 do ERP, e é só isso que a expressão usa.
"""
from __future__ import annotations

import pytest

from api import freetime as ft


# Grafias REAIS dos dois lados, copiadas do banco — nunca derivadas do código
# que vai lê-las. É o par que motivou a normalização: o contrato escreve
# "ESPUMA PARA BANCOS" e a coleta "ESPUMAS PARA BANCO"; um lado tem "PEÇAS" com
# cedilha e o outro "PECAS" sem. São 196 e 6 coletas da LEAR em 90 dias que um
# `=` cru deixaria de casar.
REAIS = [
    "ESPUMA PARA BANCOS", "ESPUMAS PARA BANCO", "EMBALAGEM ESPUMA PARA BANCOS",
    "PEÇAS E PARTES AUTOMOTIVAS", "PECAS E PARTES AUTOMOTIVAS",
    "CONJUNTOS", "CONJUNTO PHEVUS", "LONGARINA PHEVUS", "LONGARINA",
    "RODAS", "ESCADAS", "CHASSI", "CHAPA DE AÇO", "EMBALAGENS", "DIVERSOS",
    "ASSENTOS", "ASSENTOS FAURECIA", "PARTES MOTORES", "PALLET", "MADEIRA",
    "  espuma  para   bancos  ", "", "   ",
]


# ────────────────────────────────────────── os dois sotaques da normalização

def test_os_dois_sotaques_da_normalizacao_dao_O_MESMO_resultado(pg_disponivel):
    """O guard que justifica o módulo existir. Executa, não lê o texto-fonte.

    Um guard que comparasse as duas IMPLEMENTAÇÕES por leitura aprovaria
    qualquer divergência de comportamento — e é justamente o comportamento que
    tem de bater, porque é ele que decide contra qual cláusula uma permanência
    é medida, e a cláusula decide cobrança.
    """
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    from api import pglocal

    expr = ft.sql_normalizar("t.v")
    sql = ("SELECT t.v AS bruto, " + expr + " AS norm FROM (VALUES "
           + ", ".join("(%s)" for _ in REAIS) + ") AS t(v)")
    # SÓ LEITURA, e nem schema precisa: a expressão é aritmética de texto.
    # Nenhuma escrita, nenhuma migration — o guard não tem como vazar para
    # produção pelo caminho que já custou 219 registros à casa.
    linhas = [(r["bruto"], r["norm"]) for r in pglocal.query(sql, tuple(REAIS))]

    assert len(linhas) == len(REAIS), "o banco não devolveu uma linha por valor"
    divergiu = [(b, n, ft.normalizar(b)) for b, n in linhas
                if n != ft.normalizar(b)]
    assert not divergiu, (
        "SQL e Python discordam em %d de %d valores: %s"
        % (len(divergiu), len(REAIS), divergiu[:5]))


def test_a_normalizacao_casa_o_que_tem_de_casar():
    """As grafias que a validação encontrou de fato, e o que elas viram.

    Sem acento, sem plural, sem espaço sobrando — e o resultado é o MESMO
    dos dois lados do casamento, que é a única coisa que interessa.
    """
    assert ft.normalizar("ESPUMA PARA BANCOS") == ft.normalizar("ESPUMAS PARA BANCO")
    assert ft.normalizar("PEÇAS E PARTES AUTOMOTIVAS") == \
        ft.normalizar("PECAS E PARTES AUTOMOTIVAS")
    assert ft.normalizar("  espuma  para   bancos  ") == ft.normalizar("ESPUMA PARA BANCOS")
    assert ft.normalizar(None) == "" and ft.normalizar("") == ""


def test_a_normalizacao_NAO_casa_o_que_e_DECISAO_COMERCIAL():
    """"CONJUNTO PHEVUS" não é "CONJUNTOS", e o código não decide que é.

    São 163 coletas da Maxion em 90 dias. Se forem a mesma mercadoria, o
    freetime de descarga passa de 3h para 6,5h e boa parte da estadia estimada
    some — o que é exatamente o motivo de a resposta não poder sair daqui. Quem
    negocia o contrato responde; a tela mostra que a pergunta existe (a coluna
    diz que respondeu a cláusula GENÉRICA) e espera.

    Este guard existe para o dia em que alguém tentar resolver a pergunta com
    um LIKE. Aproximação por prefixo casaria "CONJUNTO PHEVUS" com "CONJUNTOS"
    e também "LONGARINA PHEVUS" com nada, silenciosamente — heurística de texto
    que decide dinheiro tem de ser decisão declarada, não efeito colateral.
    """
    assert ft.normalizar("CONJUNTO PHEVUS") != ft.normalizar("CONJUNTOS")
    assert ft.normalizar("LONGARINA PHEVUS") != ft.normalizar("LONGARINA")
    for expr in (ft.sql_normalizar("x"), ft.sql_normalizar("y")):
        assert "LIKE" not in expr.upper() and "%" not in expr


def test_a_tabela_de_acentos_e_UMA(pg_disponivel):
    """Mesma tabela nos dois lados — é dela que a divergência sairia.

    Duas tabelas de acento "equivalentes" divergem na letra que uma cobre e a
    outra não, e a divergência aparece numa mercadoria só, num cliente só.
    """
    assert len(ft.DE) == len(ft.PARA)
    assert ft.DE in ft.sql_normalizar("x") and ft.PARA in ft.sql_normalizar("x")
    # e a mesma tabela chega ao SQL do SAC
    from api import queries as q
    assert q.SQL_MERC_CONTRATO == ft.sql_normalizar("observacao")
    assert q.SQL_MERC_COLETA == ft.sql_normalizar("c.mercadorias")


# ────────────────────────────────────────── a ordem de resolução

def _c(merc, carga, desc):
    return {"mercadoria": merc, "ft_carga_h": carga, "ft_descarga_h": desc}


# O contrato REAL da IOCHPE MAXION em 10/09/2026: uma genérica de 3h e três
# cláusulas de 6,5h na descarga. As quatro com o MESMO `dtinicio` — é esse
# empate que fazia o `DISTINCT ON` do SAC sortear.
MAXION = [_c("", 3.0, 3.0), _c("CONJUNTOS", 3.0, 6.5),
          _c("ESCADAS", 3.0, 6.5), _c("RODAS", 3.0, 6.5)]

# E o da LEAR: quatro cláusulas, NENHUMA genérica. É o que faz "DIVERSOS"
# (203 coletas em 90 dias) cair no último recurso.
LEAR = [_c("EMBALAGENS", 3.0, 3.0), _c("PEÇAS E PARTES AUTOMOTIVAS", 3.0, 3.0),
        _c("EMBALAGEM ESPUMA PARA BANCOS", 5.0, 5.0),
        _c("ESPUMA PARA BANCOS", 5.0, 5.0)]


def test_a_clausula_da_mercadoria_vence_a_generica():
    """6,5h de RODAS não vira 3h porque existe uma genérica.

    Invertida, a ordem faria a genérica atropelar toda cláusula específica — e
    o cliente pagaria estadia por hora que o contrato lhe dá.
    """
    r = ft.resolver(MAXION, "RODAS")
    assert r["ft_descarga_h"] == 6.5 and r["origem"] == ft.MERCADORIA


def test_sem_clausula_propria_vale_a_generica_E_A_TELA_DIZ():
    """"3h para RODAS" e "3h porque não há cláusula" são o mesmo número e
    afirmações diferentes. Só a segunda é a que alguém precisa ir resolver."""
    r = ft.resolver(MAXION, "CHASSI")
    assert r["ft_descarga_h"] == 3.0 and r["origem"] == ft.GENERICO


def test_o_casamento_atravessa_a_grafia():
    """O que a normalização serve para: 196 coletas da LEAR que casam."""
    r = ft.resolver(LEAR, "ESPUMAS PARA BANCO")
    assert r["ft_descarga_h"] == 5.0 and r["origem"] == ft.MERCADORIA
    r2 = ft.resolver(LEAR, "PECAS E PARTES AUTOMOTIVAS")
    assert r2["ft_descarga_h"] == 3.0 and r2["origem"] == ft.MERCADORIA


def test_sem_clausula_e_sem_generica_o_ultimo_recurso_e_o_MAIOR():
    """A escolha não é neutra, e o maior é a única defensável.

    Com o maior, só vira excedente a hora que excede sob QUALQUER cláusula do
    contrato: a estimativa é um PISO do que se pode afirmar. O menor inflaria a
    cobrança com horas que talvez estivessem contratadas — e estimativa que
    erra para cima é a que ninguém confere até o cliente contestar.
    """
    r = ft.resolver(LEAR, "DIVERSOS")
    assert r["origem"] == ft.SEM_CLAUSULA
    assert r["ft_descarga_h"] == 5.0, "o último recurso deixou de ser o maior"


def test_o_ultimo_recurso_NAO_depende_da_ordem_da_LISTA():
    """A regra tem de ser a mesma com as linhas em qualquer ordem.

    É o defeito original, em outra roupa: o `DISTINCT ON` do SAC devolvia uma
    cláusula ao acaso porque as datas empatavam, e a ordem que chegava era a
    ordem física da tabela. Uma resolução que dependa da ordem da lista traz o
    mesmo sorteio para dentro do Python — só que sem nem um `ORDER BY` para
    alguém olhar.
    """
    import itertools
    vistos = {ft.resolver(list(p), "DIVERSOS")["ft_descarga_h"]
              for p in itertools.permutations(LEAR)}
    assert vistos == {5.0}, "a escolha mudou com a ordem das linhas: %s" % vistos


def test_sem_contrato_a_regra_NAO_inventa_numero():
    """`None`, e a tela não classifica. Zero significaria que toda hora parada
    é excedente, e ninguém mediu isso."""
    assert ft.resolver([], "RODAS") is None


def test_mercadoria_vazia_cai_na_generica_e_nao_casa_com_a_generica_por_acaso():
    """Coleta sem mercadoria preenchida não "casa" com a cláusula genérica —
    ela CAI nela, que é outra coisa e outro rótulo.

    A distinção importa porque a cobertura medida (100% preenchida em 180
    dias) pode cair amanhã, e o dia em que cair tem de aparecer como
    "genérica", não como "a mercadoria tem cláusula própria".
    """
    r = ft.resolver(MAXION, "")
    assert r["origem"] == ft.GENERICO
    assert ft.resolver(MAXION, None)["origem"] == ft.GENERICO


# ────────────────────────────────────────── a regra alcança TODO consumidor

def test_o_snapshot_do_copiloto_leva_a_ZONA_junto_com_o_excedente():
    """O Copiloto responde perguntas com este snapshot, e um número sozinho
    mente por omissão.

    "18% das descargas acima do freetime" sugere que os outros 82% estão
    dentro. Quando parte das cargas não tem cláusula — a LEAR tem 42,5% assim
    em 90 dias —, esses 82% incluem o que NÃO SE SABE. Para um chat que pode
    cair no modelo externo e do qual sai uma frase para um gerente, a diferença
    entre "está dentro" e "não medi" é a frase inteira.

    Este guard lê o CÓDIGO, não a nota: a nota é texto escrito à mão que
    descreve o comportamento, e texto assim já sobreviveu ao comportamento
    nesta casa mais de uma vez.
    """
    import inspect
    from api import copiloto

    fonte = inspect.getsource(copiloto)
    assert "descarga_acima_do_freetime_pct" in fonte
    assert "descarga_sem_clausula_pct" in fonte, (
        "o snapshot publica o excedente sem a zona ao lado — o Copiloto passa "
        "a afirmar aderência sobre cargas que ninguém mediu")
    assert 'd.get("zona_pct")' in fonte, (
        "a zona é publicada mas não é COLHIDA da permanência: o campo sairia "
        "sempre nulo, que é pior que não existir")


def test_NENHUM_texto_da_casa_afirma_que_a_mercadoria_e_ignorada():
    """A afirmação que sobreviveu à regra, e por pouco.

    Até 10/09/2026 a estimativa do SAC de fato ignorava a mercadoria, e três
    lugares diziam isso por escrito: o ⓘ do card, o hint do cabeçalho e a
    `fonte` do payload. A regra mudou; as frases ficariam. E o ⓘ é o pior
    lugar possível para uma frase velha, porque é dele que a tela `#doc`
    extrai a documentação da casa — a mentira viraria manual.

    Não dá para conferir "o texto descreve o código" automaticamente. Dá para
    proibir a afirmação CONTRÁRIA, que é o que este guard faz: nenhuma frase
    viva pode dizer que a mercadoria não entra na conta.
    """
    import pathlib
    from api import copiloto, portal_cliente, queries

    RAIZ = pathlib.Path(queries.__file__).resolve().parent.parent
    # O COPILOTO ENTRA NA LISTA, e ele foi a lacuna que a sabotagem achou: a
    # `nota` do snapshot descrevia a regra antiga em prosa, e é dela que sai a
    # frase que um gerente lê no chat. Guard com lista escrita à mão erra por
    # omissão, e a omissão não tem sintoma.
    alvos = [RAIZ / "api" / "static" / "index.html",
             pathlib.Path(queries.__file__),
             pathlib.Path(portal_cliente.__file__),
             pathlib.Path(copiloto.__file__),
             RAIZ / "docs" / "manual.yaml"]
    # As frases que AFIRMAM o contrário da regra viva. Escritas em minúsculo e
    # sem acento no ponto que varia, para não escapar por grafia.
    PROIBIDAS = [
        "sem excecoes por mercadoria",
        "sem exceções por mercadoria",
        "nao aplica excecao por mercadoria",
        "não aplica exceção por mercadoria",
        "o apontamento nao diz qual mercadoria",
        "o apontamento não diz qual mercadoria",
    ]
    achados = []
    for arq in alvos:
        if not arq.exists():
            continue
        texto = arq.read_text(encoding="utf-8").lower()
        for frase in PROIBIDAS:
            if frase.lower() in texto:
                achados.append("%s: %r" % (arq.name, frase))
    assert not achados, (
        "texto vivo afirma que a mercadoria e ignorada, e ela nao e mais: %s"
        % achados)
    # E o guard prova que sabe olhar: os arquivos existem e tem conteudo.
    assert all(a.exists() and a.stat().st_size > 0 for a in alvos), (
        "a lista de arquivos varridos aponta para arquivo que nao existe — "
        "varredura que nao le nada aprova tudo")


# ────────────────────────────────────── a vigência, que não é `ativoinativo`

def test_clausula_VENCIDA_nao_vale_mesmo_marcada_como_ativa():
    """O defeito que estava armado, com nome e sobrenome.

    A VOLVO tem uma cláusula genérica de 1h com `dtfim = 31/08/2024` e
    `ativoinativo = 1` até hoje (medido em 11/09/2026). Ninguém a inativou —
    ela simplesmente acabou. Filtrar só por `ativoinativo` aplica contrato
    encerrado, que é a regra da casa ao contrário: estado que envelhece
    sozinho não se grava, se calcula.

    Hoje isso não move um centavo: a VOLVO teve UMA coleta em 180 dias e a
    cláusula vencida é de outra filial. É exatamente por isso que precisa de
    guard — o defeito está armado, e o dia em que disparar é o dia em que
    alguém encerrar a cláusula de um cliente com volume.
    """
    import datetime
    hoje = datetime.date(2026, 9, 11)
    volvo_vencida = {"ativoinativo": 1, "dtinicio": datetime.date(2024, 8, 1),
                     "dtfim": datetime.date(2024, 8, 31)}
    volvo_viva = {"ativoinativo": 1, "dtinicio": datetime.date(2024, 9, 1),
                  "dtfim": None}
    assert ft.vigente(volvo_vencida, hoje) is False, (
        "cláusula encerrada em 31/08/2024 continua valendo")
    assert ft.vigente(volvo_viva, hoje) is True


def test_clausula_AINDA_NAO_VIGENTE_tambem_nao_vale():
    """O outro lado da mesma régua, e ele é mais insidioso: contrato
    combinado para o mês que vem, cadastrado hoje, passaria a reger a
    permanência de ontem."""
    import datetime
    hoje = datetime.date(2026, 9, 11)
    assert ft.vigente({"ativoinativo": 1, "dtinicio": datetime.date(2027, 1, 1),
                       "dtfim": None}, hoje) is False


def test_a_vigencia_chega_ao_SQL_das_TRES_consultas():
    """A regra em Python não serve de nada se a consulta continuar trazendo a
    linha vencida — e são três consultas lendo a mesma tabela."""
    from api import portal_cliente, queries as q

    for nome, sql in (("SAC_FT_REP", q.SAC_FT_REP),
                      ("SAC_FT_MERC", q.SAC_FT_MERC),
                      ("SAC_FT_SQL", q.SAC_FT_SQL),
                      ("FREETIME_SQL_TODAS", portal_cliente.FREETIME_SQL_TODAS)):
        assert "dtfim" in sql, "%s ainda aceita cláusula vencida" % nome
        assert "dtinicio IS NULL OR" in sql, (
            "%s ainda aceita cláusula que não começou" % nome)


def test_o_filtro_de_vigencia_sabe_usar_ALIAS():
    """Uma das consultas usa `ft.` e as outras não.

    Encadear `.replace("dtinicio", "ft.dtinicio")` por fora funciona até o dia
    em que uma coluna nova contiver o nome de outra — e aí a substituição
    acerta no meio de uma palavra, sem ninguém ver.
    """
    sem = ft.sql_vigente()
    com = ft.sql_vigente("ft")
    assert "ft.ativoinativo" in com and "ft.dtfim" in com
    assert "ft.ativoinativo" not in sem and "ativoinativo = 1" in sem
    assert com.count("ft.") == 5, (
        "o alias não alcançou todas as colunas: %s" % com)


# ────────────────────────────── as DUAS fontes do ERP sobre "é genérica?"

def test_o_ERP_tem_DUAS_fontes_para_generica_e_elas_sao_conferidas():
    """`observacao` vazia e `distingueoperacao` dizem a mesma coisa.

    Medido em 11/09/2026: concordam em 24 de 24 linhas vigentes — 1 ⇔ tem
    mercadoria, 2 ⇔ genérica. A `observacao` continua sendo a PRIMÁRIA (é o
    texto que casa com a coleta), mas divergência entre as duas é cadastro
    furado, e a tela diz em vez de escolher em silêncio qual tem razão.

    É o segundo caminho para o mesmo número, que é como esta casa pega join
    quebrado e cadastro torto.
    """
    assert ft.confere_distingue({"distingueoperacao": 2, "mercadoria": ""})
    assert ft.confere_distingue({"distingueoperacao": 1, "mercadoria": "RODAS"})
    assert not ft.confere_distingue({"distingueoperacao": 2, "mercadoria": "RODAS"})
    assert not ft.confere_distingue({"distingueoperacao": 1, "mercadoria": ""})
    # sem o campo não há o que conferir, e ausência não é divergência
    assert ft.confere_distingue({"distingueoperacao": None, "mercadoria": "RODAS"})


def test_a_Minha_Operacao_publica_o_que_permite_VALIDAR_a_clausula():
    """Pedido de quem opera em 11/09/2026: "precisamos de mais detalhes para
    validar".

    Ler "RODAS 6,5h" não valida nada: valida quem vê desde quando vale, quanto
    custa a hora excedente, de qual filial é o cadastro e quem mexeu por
    último. Sem o preço, a tela mostra a régua e esconde o que ela cobra.
    """
    from api import portal_cliente

    sql = portal_cliente.FREETIME_SQL_TODAS
    for campo in ("rh_coleta", "rh_entrega", "vig_de", "vig_ate", "filial",
                  "distingue", "mexido_em", "mexido_por"):
        assert campo in sql, (
            "`%s` não sai da consulta — a tela não tem como validar" % campo)


# ──────────────────────── escolher VÁRIAS mercadorias (11/09/2026)

def test_a_ordem_da_escolha_NAO_cria_duas_perguntas():
    """["RODAS","CHASSI"] e ["CHASSI","RODAS"] são a mesma pergunta.

    E isso não é estética: a chave do cache da casa é `repr(args)`, então sem
    canonizar seriam DUAS entradas — duas idas ao ERP para o mesmo número, e
    duas cópias dele envelhecendo em ritmos diferentes. Quem abre a tela pela
    segunda vez com a mesma escolha em outra ordem espera a resposta pronta.
    """
    assert ft.canonizar(["RODAS", "CHASSI"]) == ft.canonizar(["CHASSI", "RODAS"])
    # E A SAÍDA É ORDENADA, não só igual entre si. Um `set` sozinho já faria as
    # duas chamadas baterem — as duas montam o mesmo conjunto —, e por isso a
    # igualdade acima passava com o `sorted` removido. O que o `sorted` de fato
    # garante é ordem ESTÁVEL ENTRE PROCESSOS: o hash de string do Python é
    # aleatorizado por processo, então sem ele a parede mostraria "RODAS,
    # CHASSI" hoje e "CHASSI, RODAS" depois do próximo deploy, sem nada ter
    # mudado. (Esta linha nasceu de uma sabotagem que passou verde.)
    for entrada in (["RODAS", "CHASSI"], ["CHASSI", "ESCADAS", "RODAS"]):
        saida = ft.canonizar(entrada)
        assert list(saida) == sorted(saida), "a saída não vem ordenada: %s" % (saida,)


def test_a_escolha_repetida_conta_UMA_vez():
    """Marcar duas grafias da mesma mercadoria não é escolher duas.

    "PEÇAS" e "PECAS" são a mesma carga — é o caso real da LEAR, 20 e 6
    coletas. Sem a dedupe a cláusula `= ANY` receberia a mesma chave duas
    vezes: inofensivo no resultado e enganoso no eco, que diria "2
    mercadorias" onde há uma.
    """
    assert ft.canonizar(["PEÇAS", "PECAS", "peças"]) == ("PECA",)


def test_escolha_vazia_e_TODAS_e_nao_nenhuma():
    """A diferença que inverte a tela.

    Nenhuma marcada tem de virar tupla vazia — que o montador de SQL lê como
    "sem cláusula de filtro". Se virasse uma lista com string vazia, a consulta
    passaria a pedir as coletas SEM mercadoria preenchida: o oposto de "todas",
    e um oposto plausível, porque devolveria linhas.
    """
    for vazio in (None, [], "", ["", "  "]):
        assert ft.canonizar(vazio) == (), repr(vazio)
    # E O TEXTO QUE NORMALIZA PARA NADA também: "S" sozinho vira "" pela regra
    # do plural, e entraria na cláusula como uma mercadoria chamada vazio —
    # que não casa com coleta nenhuma e devolveria a tela em branco.
    # (A sabotagem que tirava este descarte passou verde: o teste acima só
    # olhava entrada vazia, não entrada que ESVAZIA.)
    assert ft.normalizar("S") == "", "a régua do plural mudou; reveja este caso"
    assert ft.canonizar(["S"]) == ()
    assert ft.canonizar(["RODAS", "S"]) == ("RODA",)


def test_a_escolha_normaliza_pela_MESMA_regua_do_contrato():
    """Quem escolhe "PEÇAS" na lista está escolhendo as coletas escritas
    "PECAS" também — o filtro tem de concordar com a lista que ele ofereceu.
    """
    assert ft.canonizar(["ESPUMAS PARA BANCO"]) == (ft.normalizar("ESPUMA PARA BANCOS"),)


def test_canonizar_aceita_UMA_string_solta():
    """A rota pode receber `?merc=RODAS` uma vez só, e o FastAPI entrega
    string quando o parâmetro não é declarado como lista em algum caminho.
    Aceitar os dois evita um `TypeError` que só apareceria em produção."""
    assert ft.canonizar("RODAS") == ("RODA",)


def test_o_filtro_de_varias_usa_PARAMETRO_e_nao_texto_montado():
    """A lista vem do navegador. Valor de usuário não entra em texto de SQL
    nem quando parece inofensivo — e `= ANY(%(merc)s)` serve uma opção ou dez
    com a mesma cláusula e o mesmo parâmetro."""
    from api import portal_cliente

    com = portal_cliente._filtro_merc(("RODA", "CHASSI"))
    assert "ANY(%(merc)s)" in com, com
    assert "RODA" not in com, "o valor escolhido foi INTERPOLADO no SQL"
    assert portal_cliente._filtro_merc(()) == ""
