"""Orquestra a importação de extrato e monta o painel de validação.

Importação: parse -> grava (dedup) -> devolve resultado. Conta cujo vínculo com
o ERP ainda não existe grava os lançamentos e volta pedindo o mapeamento; não
perder o upload evita o usuário subir o arquivo duas vezes.

Identidade da conta CSV: diferente do OFX (que traz banco/agência/conta dentro
do próprio arquivo), o CSV não carrega a conta - só o nome do arquivo, que é
livre e costuma se repetir ("extrato.csv" é o export padrão de vários internet
bankings). Por isso a conta de um CSV NUNCA é inferida do nome do arquivo: ela
é sempre informada pelo chamador via `conta_id` (a conta já cadastrada na tela
de mapeamento - Task 6). Sem `conta_id`, `importar` não grava nada e devolve
`precisa: "conta_csv"` para o usuário escolher ou criar a conta. Quando a
Task 6 cria a conta CSV, o `ident` dela usa `ident_csv()` (a identidade real
da conta bancária no ERP - banco/agência/conta), nunca o nome do arquivo:
assim dois arquivos de bancos diferentes com o mesmo nome nunca colidem na
mesma conta (bug corrigido nesta revisão: `ident = "csv:" + nome_do_arquivo`
fazia exatamente essa colisão, aplicando o mapa de colunas e o vínculo ERP de
um banco aos lançamentos de outro, com `ok: true` e nenhum aviso).

Painel: para cada conta mapeada, lê `contacorrente_saldo` (lado ERP) e cruza
com o extrato local pela função pura de `comparacao`.
"""
from __future__ import annotations

from datetime import date, datetime

from api import db
from api.extrato import armazenamento as arm
from api.extrato import comparacao as cmp
from api.extrato import conciliacao as conc
from api.extrato.parser_csv import parse_csv, preview_csv
from api.extrato.parser_ofx import parse_ofx
from api.extrato.parser_pdf import parse_pdf

# Lado ERP da comparação. Uma linha por dia da conta; `valorsaldo` é a posição
# de fechamento do dia. Sem "-" especial na string (o banco é LATIN-1).
ERP_SALDO_SQL = """
SELECT dtmovimento::date AS dt,
       coalesce(valorcredito,0)::float8 AS credito,
       coalesce(valordebito,0)::float8  AS debito,
       coalesce(valorsaldo,0)::float8   AS saldo
FROM contacorrente_saldo
WHERE banco = %(banco)s AND agencia = %(agencia)s AND conta = %(conta)s
  AND dtmovimento BETWEEN %(dt_de)s AND %(dt_ate)s
ORDER BY dtmovimento
"""

# Contas que o ERP movimenta, para o select de mapeamento. Só as com movimento
# recente: a lista completa traz contas encerradas anos atrás.
ERP_CONTAS_SQL = """
SELECT banco, agencia, conta,
       max(dtmovimento)::date AS ultimo_movimento,
       count(*)::int AS dias
FROM contacorrente_saldo
WHERE dtmovimento >= current_date - 400
GROUP BY 1,2,3
ORDER BY max(dtmovimento) DESC, banco
"""


# Ultima posicao de saldo que o ERP tem de CADA conta, em uma consulta so.
#
# `DISTINCT ON` e' o que evita sete idas ao banco (uma por conta) na tela que o
# usuario abre todo dia. A janela de 90 dias existe para o indice servir e para
# nao ressuscitar conta encerrada anos atras; conta parada ha mais que isso
# aparece sem posicao, que e' a verdade sobre ela.
POSICAO_ERP_SQL = """
SELECT DISTINCT ON (banco, agencia, conta)
       banco, agencia, conta,
       dtmovimento::date AS dt,
       coalesce(valorsaldo,0)::float8 AS saldo
FROM contacorrente_saldo
WHERE dtmovimento >= current_date - 90
ORDER BY banco, agencia, conta, dtmovimento DESC
"""


# Razao de caixa do ERP, LINHA a linha - a contraparte da conciliacao lancamento
# a lancamento (`api/extrato/conciliacao.py`). E outra tabela e outro nivel do
# que o `contacorrente_saldo` usado acima: aquele traz uma linha POR DIA, com o
# agregado; este traz cada movimento.
#
# `semaforo = 1` pela mesma razao das outras tabelas satelites do ERP: sem ele
# entram linhas canceladas.
#
# O valor sai com SINAL (credito positivo, debito negativo) porque e assim que
# o extrato guarda, e casar credito com debito de mesmo valor esconderia
# justamente o erro de sentido que a conciliacao existe para achar.
ERP_RAZAO_SQL = """
SELECT dtmovimento::date AS dt, sequencia,
       (coalesce(valorcredito,0) - coalesce(valordebito,0))::float8 AS valor,
       coalesce(historicodescricao,'') AS historico,
       coalesce(nominal,'') AS nominal,
       dtcompensacao::date AS dtcompensacao
FROM contacorrente
WHERE banco = %(banco)s AND agencia = %(agencia)s AND conta = %(conta)s
  AND dtmovimento BETWEEN %(dt_de)s AND %(dt_ate)s
  AND semaforo = 1
ORDER BY dtmovimento, sequencia
"""


# Conciliação NATIVA do ERP, achada explorando o Avacorp ao vivo: o AVA tem
# feed automático de extrato bancário, separado do import manual desta tela, e
# hoje só UMA conta o recebe (Bradesco 237/36455/1239066). Fontes e mecanismos
# diferentes, mostrados à parte para não virarem um número só.
#
# DUAS MARCAS DE "CONCILIADO", E ELAS DISCORDAM
# ============================================
# `extratobancario.situacao` é a marca que a tela nativa grava (1 Pendente,
# 2 Conciliado, 3 Oculto; o código 4 existe no dado e não aparece no filtro
# daquela tela, então cai em "outro"). Essa marcação PAROU: os 1.604
# conciliados são todos de movimento de junho a agosto de 2023, e desde então
# não houve mais um.
#
# Só que o trabalho não parou - ele mudou de caminho. A tabela
# `extratobancario_contacorrente` liga a linha do feed ao lançamento do razão,
# e continua recebendo linhas TODO dia (132 em 2026, a última hoje). O vínculo
# é criado e a `situacao` fica em 1.
#
# Resultado medido: 2.856 linhas com vínculo com o razão contadas como
# pendentes. Lendo só a `situacao`, a tela anunciava 27.581 pendentes e
# R$ 994 milhões - inflado por essas 2.856. Por isso o pendente daqui é
# "sem situação 2 E sem vínculo", e as duas marcas viajam separadas para a
# tela poder mostrar que uma delas foi abandonada.
#
# O DISTINCT no subselect não é decoração: uma linha do feed pode ter VÁRIOS
# vínculos (um lançamento do banco casado com vários do razão), e sem ele o
# join multiplicaria a linha e todo `count`/`sum` sairia inflado.
CONCIL_SITUACAO = {1: "Pendente", 2: "Conciliado", 3: "Oculto"}

_VINC = "(SELECT DISTINCT idextratobancario FROM extratobancario_contacorrente)"

CONCIL_RESUMO_SQL = f"""
SELECT e.situacao, (v.idextratobancario IS NOT NULL) AS vinculada,
       count(*)::int AS qtd,
       coalesce(sum(CASE WHEN e.tipo='C' THEN e.valor ELSE 0 END),0)::float8 AS creditos,
       coalesce(sum(CASE WHEN e.tipo='D' THEN e.valor ELSE 0 END),0)::float8 AS debitos
FROM extratobancario e
LEFT JOIN {_VINC} v ON v.idextratobancario = e.id
GROUP BY 1,2 ORDER BY 1,2
"""

CONCIL_CONTA_SQL = f"""
SELECT e.banco, coalesce(b.nome, 'Banco '||e.banco) AS banco_nome, e.agencia, e.conta,
       count(*)::int AS total,
       sum(CASE WHEN e.situacao=1 AND v.idextratobancario IS NULL
                THEN 1 ELSE 0 END)::int AS pendentes,
       coalesce(sum(CASE WHEN e.situacao=1 AND v.idextratobancario IS NULL
                         THEN e.valor ELSE 0 END),0)::float8 AS valor_pendente,
       sum(CASE WHEN e.situacao=2 THEN 1 ELSE 0 END)::int AS marcadas,
       sum(CASE WHEN e.situacao<>2 AND v.idextratobancario IS NOT NULL
                THEN 1 ELSE 0 END)::int AS vinculadas,
       min(CASE WHEN e.situacao=1 AND v.idextratobancario IS NULL
                THEN e.dtmovimento END)::text AS pendente_mais_antigo,
       max(e.dtmovimento)::text AS ultimo_movimento
FROM extratobancario e
LEFT JOIN {_VINC} v ON v.idextratobancario = e.id
LEFT JOIN banco b ON b.codigo = e.banco
GROUP BY e.banco, b.nome, e.agencia, e.conta
ORDER BY pendentes DESC
"""

# Só os 12 meses mais recentes: o backlog desde 2023 é grande demais para um
# gráfico mensal legível, e o que importa para ação é se o atraso é CORRENTE.
CONCIL_MENSAL_SQL = f"""
SELECT to_char(e.dtmovimento,'YYYY-MM') AS mes,
       sum(CASE WHEN e.situacao=1 AND v.idextratobancario IS NULL
                THEN 1 ELSE 0 END)::int AS pendentes,
       sum(CASE WHEN e.situacao=2 THEN 1 ELSE 0 END)::int AS conciliados,
       sum(CASE WHEN e.situacao<>2 AND v.idextratobancario IS NOT NULL
                THEN 1 ELSE 0 END)::int AS vinculados,
       coalesce(sum(CASE WHEN e.situacao=1 AND v.idextratobancario IS NULL
                         THEN e.valor ELSE 0 END),0)::float8 AS valor_pendente
FROM extratobancario e
LEFT JOIN {_VINC} v ON v.idextratobancario = e.id
WHERE e.dtmovimento >= current_date - interval '12 months'
GROUP BY 1 ORDER BY 1
"""

# Quando cada uma das duas marcas foi usada pela ultima vez. E o que mostra que
# a `situacao` foi abandonada enquanto o vinculo segue vivo - sem isso, "94%
# pendente" parece desleixo geral em vez de marcacao que ninguem mais usa.
CONCIL_ATIVIDADE_SQL = """
SELECT (SELECT max(dtalt)::date::text FROM extratobancario WHERE situacao=2)
         AS ultima_marcacao,
       (SELECT max(dtinc)::date::text FROM extratobancario_contacorrente)
         AS ultimo_vinculo,
       (SELECT max(dtinc)::date::text FROM extratobancario) AS ultima_carga
"""


# Nome do banco pelo codigo COMPE, da tabela `banco` do proprio ERP - a mesma
# fonte que a Conciliacao nativa ja usa. Chumbar uma lista aqui envelheceria
# calada no dia em que a empresa abrisse conta num banco novo; a tabela tem 216.
BANCO_NOME_SQL = "SELECT codigo, coalesce(nome,'') AS nome FROM banco"

_NOMES: dict[int, str] = {}


# Palavras que ficam como estao (siglas) e as que ficam em minuscula (ligacoes).
_SIGLAS = {"S.A.", "S/A", "S.A", "IP", "TB", "ME", "EPP"}
_LIGACOES = {"do", "da", "de", "dos", "das", "e"}


def _bonito(nome: str) -> str:
    """"BANCO DO BRASIL S.A." -> "Banco do Brasil S.A."

    Normalizacao DELIBERADAMENTE timida: caixa de titulo, siglas preservadas e
    ligacoes em minuscula. NAO corta nada.

    Duas tentacoes recusadas, as duas por perderem informacao:
      - tirar o "BANCO " do inicio: em "BANCO DO BRASIL" sobraria "do Brasil";
      - cortar no " - ": em "NSTECH IP - EFRETE" sobraria "Nstech IP", e
        "EFRETE" e' exatamente o que identifica aquela pseudo-conta.
    Nome comprido a tela resolve com truncagem e tooltip; nome mutilado, nao.
    """
    n = " ".join((nome or "").split())
    saida = []
    for i, palavra in enumerate(n.split(" ")):
        u = palavra.upper()
        if u in _SIGLAS or any(c.isdigit() for c in palavra):
            saida.append(palavra)
        elif i and u.lower() in _LIGACOES:
            saida.append(u.lower())
        else:
            saida.append(palavra.capitalize())
    return " ".join(saida)


def nomes_banco() -> dict[int, str]:
    """Cache de processo. A tabela nao muda em producao, e a tela de extrato
    consulta o nome para cada conta a cada carregamento."""
    global _NOMES
    if _NOMES:
        return _NOMES
    try:
        _NOMES = {r["codigo"]: _bonito(r["nome"]) for r in db.query(BANCO_NOME_SQL)
                  if r["nome"]}
    except Exception:                      # noqa: BLE001
        # Sem ERP a tela continua funcionando com o codigo; devolver {} deixa o
        # chamador cair no rotulo antigo em vez de esconder a conta.
        return {}
    return _NOMES


def _codigo_do_ident(ident: str) -> int | None:
    """O codigo do banco que veio no ARQUIVO, extraido do `ident`.

    Serve quando a conta ainda nao foi vinculada ao ERP - que e justamente
    quando o usuario mais precisa saber de que banco ela e, para escolher o
    vinculo certo. `ident` de CSV vem com o prefixo "csv:".
    """
    bruto = (ident or "").split("/")[0].removeprefix("csv:")
    try:
        return int(bruto)
    except ValueError:
        return None


def banco_da_conta(conta: dict) -> tuple[int | None, str | None]:
    """(codigo, nome) de uma conta local. Prefere o vinculo com o ERP."""
    cod = conta.get("erp_banco")
    if cod is None:
        cod = _codigo_do_ident(conta.get("ident") or "")
    return cod, (nomes_banco().get(cod) if cod is not None else None)


def conciliacao_nativa() -> dict:
    resumo = db.query(CONCIL_RESUMO_SQL)
    contas = db.query(CONCIL_CONTA_SQL)
    mensal = db.query(CONCIL_MENSAL_SQL)
    atividade = (db.query(CONCIL_ATIVIDADE_SQL) or [{}])[0]

    total = sum(r["qtd"] for r in resumo)
    # Pendente de VERDADE: nem marcada como conciliada, nem vinculada ao razao.
    # Ler so a `situacao` contava as 2.856 linhas ja vinculadas como pendentes.
    def _soma(cond):
        alvo = [r for r in resumo if cond(r)]
        return (sum(r["qtd"] for r in alvo),
                sum(r["creditos"] + r["debitos"] for r in alvo))

    pend_qtd, pend_valor = _soma(lambda r: r["situacao"] == 1 and not r["vinculada"])
    marcadas, _ = _soma(lambda r: r["situacao"] == 2)
    vinculadas, _ = _soma(lambda r: r["situacao"] != 2 and r["vinculada"])
    pend_pela_situacao, _ = _soma(lambda r: r["situacao"] == 1)

    # o resumo por situacao continua existindo, agora somando as duas metades
    por_situacao: dict[int, dict] = {}
    for r in resumo:
        d = por_situacao.setdefault(r["situacao"], {"qtd": 0, "creditos": 0.0,
                                                    "debitos": 0.0, "vinculadas": 0})
        d["qtd"] += r["qtd"]
        d["creditos"] += r["creditos"]
        d["debitos"] += r["debitos"]
        if r["vinculada"]:
            d["vinculadas"] += r["qtd"]

    return {
        "resumo": [{"situacao": CONCIL_SITUACAO.get(s, "Outro"), **d}
                    for s, d in sorted(por_situacao.items())],
        "contas": [{**c, "rotulo": f"{c['banco_nome']} ag. {c['agencia']} cc {c['conta']}"}
                    for c in contas if c["total"] > 0],
        "mensal": mensal,
        "kpis": {
            "total": total, "pendentes": pend_qtd,
            "pct_pendente": round(100 * pend_qtd / total, 1) if total else 0.0,
            "valor_pendente": pend_valor,
            "marcadas": marcadas,
            "vinculadas": vinculadas,
            # o que a leitura ANTIGA (so `situacao=1`) diria: fica exposto para a
            # tela explicar a diferenca, em vez de o numero mudar sozinho de uma
            # versao para a outra sem ninguem entender por que
            "pendentes_pela_situacao": pend_pela_situacao,
            "ultima_marcacao": atividade.get("ultima_marcacao"),
            "ultimo_vinculo": atividade.get("ultimo_vinculo"),
            "ultima_carga": atividade.get("ultima_carga"),
            "contas_com_feed": sum(1 for c in contas if c["total"] > 0),
        },
        "fonte": ("ERP AVA - extratobancario (feed nativo do banco) cruzado com "
                  "extratobancario_contacorrente (o vinculo com o razao). Separado "
                  "do import de arquivo desta tela."),
    }


def ident_csv(erp_banco: int, erp_agencia: str, erp_conta: str) -> str:
    """Identidade de conta CSV = a conta bancária real (banco/agência/conta do
    ERP), nunca o nome do arquivo. Usada pela tela de mapeamento (Task 6) ao
    criar a conta, antes do primeiro `importar(..., conta_id=...)`."""
    return f"csv:{erp_banco}/{erp_agencia}/{erp_conta}"


def _conta_por_id(esquema, conta_id: int) -> dict | None:
    return next((c for c in arm.listar_contas(esquema) if c["id"] == conta_id), None)


def _formato(nome: str) -> str:
    n = nome.lower()
    if n.endswith((".ofx", ".qfx")):
        return "ofx"
    if n.endswith(".pdf"):
        return "pdf"
    return "csv"


def _erp_dias(conta: dict, dt_de: str, dt_ate: str) -> list[dict]:
    if conta.get("erp_banco") is None:
        return []
    rows = db.query(ERP_SALDO_SQL, {
        "banco": conta["erp_banco"], "agencia": conta["erp_agencia"],
        "conta": conta["erp_conta"], "dt_de": dt_de, "dt_ate": dt_ate})
    return [{"dt": r["dt"].isoformat() if hasattr(r["dt"], "isoformat") else str(r["dt"]),
             "credito": r["credito"], "debito": r["debito"], "saldo": r["saldo"]}
            for r in rows]


def contas_erp() -> list[dict]:
    rows = db.query(ERP_CONTAS_SQL)
    out = []
    for r in rows:
        ultimo = r["ultimo_movimento"]
        nome = nomes_banco().get(r["banco"])
        out.append({
            "banco": r["banco"], "banco_nome": nome,
            "agencia": r["agencia"], "conta": r["conta"],
            "ultimo_movimento": ultimo.isoformat() if hasattr(ultimo, "isoformat") else str(ultimo),
            "dias": r["dias"],
            # o codigo continua no rotulo: e por ele que se confere o vinculo
            "rotulo": (f"{nome} ({r['banco']}) / ag {r['agencia']} / cc {r['conta']}"
                       if nome else f"{r['banco']} / ag {r['agencia']} / cc {r['conta']}"),
        })
    return out


def importar(bruto: bytes, nome: str, esquema=None, conta_id: int | None = None) -> dict:
    arm.init_db(esquema)
    formato = _formato(nome)

    if formato in ("ofx", "pdf"):
        # OFX e PDF seguem o MESMO caminho porque os dois parsers devolvem a
        # mesma forma (ident/itens/saldos/...). O que os separa e so a extracao;
        # gravacao, deduplicacao, ancora de saldo e mapeamento sao identicos, e
        # duplicar esse trecho por formato seria criar duas regras de negocio
        # onde ha uma.
        #
        # parse_* devolve UM extrato por conta do arquivo (export consolidado
        # traz varias). Grava todas; o resultado reporta a primeira que ainda
        # precisa de mapeamento, para a tela pedir o vinculo. `conta_id` (o
        # parametro da funcao) nao se aplica aqui - o arquivo traz a propria
        # conta e sempre cria/encontra a dela; usa-se `cid` para a conta de
        # CADA extrato do arquivo, para nao sombrear o parametro.
        extratos = parse_pdf(bruto) if formato == "pdf" else parse_ofx(bruto)
        hoje = date.today().isoformat()
        resultados = []
        for d in extratos:
            rotulo = f"{d['banco'] or '?'} / cc {d['conta'] or '?'}"
            cid = arm.obter_ou_criar_conta(esquema, d["ident"], rotulo)
            conta = arm.conta_por_ident(esquema, d["ident"])

            # LANCAMENTO COM DATA FUTURA NAO E EXTRATO - e agenda, e nao entra.
            #
            # O Bradesco exporta, ao lado do extrato realizado, um arquivo de
            # COMPROMISSOS: mesma conta, mesmas tags, mesmo cabecalho OFX, sem
            # NADA na estrutura que o distinga. O de agosto/2026 trazia DARF
            # parcelado em 31/08, oito boletos em 10/09 e a conta de luz em
            # 15/09. Importados como realizados, eles (a) somam ao movimento
            # dias que ainda nao aconteceram e (b) quebram o farol: o "ultimo
            # dia com extrato" passava a ser 15/09, e `dias_sem_extrato` saia
            # NEGATIVO (-20). Como o farol so acusa atraso acima de 7 dias, a
            # conta ficava permanentemente "em dia" - um lancamento agendado
            # para o futuro desligava o alerta de extrato velho.
            #
            # Ficam de fora e sao CONTADOS: silenciar seria repetir o defeito
            # que este modulo acabou de corrigir na deduplicacao.
            futuras = [i for i in d["itens"] if i["dt"] > hoje]
            itens = [i for i in d["itens"] if i["dt"] <= hoje]

            res = arm.gravar_lancamentos(esquema, cid, itens, nome, formato,
                                         d["ignoradas"])
            # `importacao_id` amarra a âncora a ESTA importação (achado d1):
            # `res["importacao_id"]` sai 0 quando o arquivo não trouxe
            # lançamento novo nenhum (reimport 100% duplicado - a linha de
            # `ext_importacao` nem chega a ficar na trilha); nesse caso não
            # há importação nova a que amarrar, então a âncora fica sem
            # vínculo (`None`), mesmo estado das âncoras pré-migração.
            #
            # `d["saldos"]` (plural) e uma ancora POR DIA quando o banco manda
            # a linha de saldo diaria - 18 dias no Itau e no Safra, contra a
            # unica ancora de `LEDGERBAL` que existia antes. Cada dia ancorado
            # e um dia que a comparacao confere contra o ERP em vez de derivar
            # por soma a partir do ultimo saldo conhecido.
            for s in d["saldos"]:
                if s["dt"] > hoje:
                    continue
                arm.gravar_saldo_extrato(esquema, cid, s["dt"], s["saldo"],
                                         importacao_id=res["importacao_id"] or None,
                                         origem=s.get("origem") or "ledgerbal")
            datas = sorted(i["dt"] for i in itens) or [None]
            resultados.append({"conta_id": cid, "conta": conta,
                               "novas": res["novas"], "duplicadas": res["duplicadas"],
                               "ignoradas": d["ignoradas"], "futuras": len(futuras),
                               "linhas_saldo": d["linhas_saldo"],
                               "ancoras": len([s for s in d["saldos"] if s["dt"] <= hoje]),
                               # so o PDF traz - e o sinal de que o recorte de
                               # coluna continua valendo naquele layout
                               "conferencia": d.get("conferencia"),
                               "dt_de": datas[0], "dt_ate": datas[-1]})
        # agrega os totais do arquivo; contas = uma linha por conta encontrada
        total = {"novas": sum(r["novas"] for r in resultados),
                 "duplicadas": sum(r["duplicadas"] for r in resultados),
                 "ignoradas": sum(r["ignoradas"] for r in resultados),
                 "futuras": sum(r["futuras"] for r in resultados),
                 "linhas_saldo": sum(r["linhas_saldo"] for r in resultados),
                 "ancoras": sum(r["ancoras"] for r in resultados),
                 "conferencia_desvios": [dv for r in resultados
                                         for dv in ((r["conferencia"] or {}).get("desvios") or [])],
                 "contas": resultados}
        datas_todas = sorted(d for r in resultados for d in (r["dt_de"], r["dt_ate"]) if d)
        primeira = resultados[0]
        sem_mapa = [r for r in resultados if r["conta"].get("erp_banco") is None]
        base = {"conta_id": primeira["conta_id"], "conta": primeira["conta"],
                "dt_de": (datas_todas[0] if datas_todas else None),
                "dt_ate": (datas_todas[-1] if datas_todas else None),
                "pendentes": len(sem_mapa), **total}
        if sem_mapa:
            return {"ok": False, "precisa": "mapa_erp", **base,
                    "conta_id": sem_mapa[0]["conta_id"], "conta": sem_mapa[0]["conta"]}
        return {"ok": True, **base}

    # CSV: o arquivo NAO traz a conta (ao contrario do OFX), entao ela nunca e
    # inferida do nome do arquivo (achado critico: "extrato.csv" e o nome
    # padrao de varios internet bankings - dois bancos diferentes colidiriam
    # na mesma conta). A conta so pode vir do chamador, ja escolhida/criada na
    # tela de mapeamento (Task 6) com `ident_csv()`.
    if conta_id is None:
        return {"ok": False, "precisa": "conta_csv", "preview": preview_csv(bruto),
                "contas": arm.listar_contas(esquema), "novas": 0, "duplicadas": 0, "ignoradas": 0}
    conta = _conta_por_id(esquema, conta_id)
    if conta is None:
        raise ValueError(f"conta_id {conta_id} nao existe.")
    if not conta.get("mapa_csv"):
        return {"ok": False, "precisa": "mapa_csv", "conta_id": conta_id, "conta": conta,
                "preview": preview_csv(bruto), "novas": 0, "duplicadas": 0, "ignoradas": 0}
    d = parse_csv(bruto, conta["mapa_csv"])
    res = arm.gravar_lancamentos(esquema, conta_id, d["itens"], nome, "csv", d["ignoradas"])
    datas = sorted(i["dt"] for i in d["itens"]) or [None]
    base = {"conta_id": conta_id, "conta": conta, "novas": res["novas"],
            "duplicadas": res["duplicadas"], "ignoradas": d["ignoradas"],
            "dt_de": datas[0], "dt_ate": datas[-1]}
    if conta.get("erp_banco") is None:
        return {"ok": False, "precisa": "mapa_erp", **base}
    return {"ok": True, **base}


def painel(dt_de: str, dt_ate: str, conta_id: int | None = None, esquema=None) -> dict:
    arm.init_db(esquema)
    hoje = date.today().isoformat()
    contas = arm.listar_contas(esquema)
    imps = arm.listar_importacoes(esquema)   # só para a TABELA de importações da tela
    # ult_por_conta ("último dia coberto por conta") vem direto do banco, sem o
    # LIMIT 20 de `imps` acima - ele governa o farol (achado C1, crítico): usar
    # a lista limitada da tela fazia uma conta de upload pouco frequente cair
    # fora das 20 mais novas, ficar com `ultimo_upload=None` e o farol julgar
    # "desatualizado" por ausência de dado, escondendo divergência real.
    ult_por_conta = arm.ultimo_dt_por_conta(esquema)

    resumo, dias_sel = [], []
    dias_por_conta: dict[int, list[dict]] = {}
    tot_div = tot_val = 0
    pior = None
    for c in contas:
        lancs = arm.lancamentos(esquema, c["id"], dt_de, dt_ate)
        saldos = arm.saldos_extrato(esquema, c["id"])
        # _erp_dias faz a query ao ERP (atras de tunel SSH, ~284ms) - calculada
        # UMA vez aqui e reaproveitada abaixo na selecao automatica, para nunca
        # consultar o ERP duas vezes pela mesma conta na mesma chamada de painel.
        dias = cmp.comparar(lancs, saldos, _erp_dias(c, dt_de, dt_ate))
        dias_por_conta[c["id"]] = dias
        f = cmp.farol(dias, ult_por_conta.get(c["id"]), hoje,
                      mapeada=c.get("erp_banco") is not None)
        validos = [d for d in dias if d["estado"] in ("OK", "DIVERGE")]
        divergentes = [d for d in dias if d["estado"] == "DIVERGE"]
        tot_val += len(validos)
        tot_div += len(divergentes)
        for d in divergentes:
            # maior desvio real do dia: reaproveita cmp._maior_delta (mesma
            # regra do farol, Task 8 fix round 2) em vez de duplicar o "maior
            # modulo entre os tres, ignorando None" - essa duplicacao (aqui,
            # no farol, e na tabela dia a dia do front) foi o que permitiu o
            # mesmo bug (achar a diferenca errada entre saldo/credito/debito)
            # sobreviver a duas correcoes anteriores no plano (fix round 5,
            # FINDING 3). `_maior_delta` devolve o valor COM sinal; o `abs()`
            # fica aqui porque o KPI `maior_diferenca` sempre foi absoluto.
            valor, _origem = cmp._maior_delta(d)
            delta = abs(valor) if valor is not None else 0.0
            if pior is None or delta > pior["delta"]:
                # `conta_id` viaja junto com o rótulo (achado M1): duas contas
                # DISTINTAS (ex.: a mesma conta do ERP importada por OFX e por
                # CSV) podem ter o rótulo idêntico - o front comparava por
                # rótulo para decidir "a maior divergência está em outra
                # conta" e o aviso saía suprimido por engano quando a conta
                # selecionada só coincidia no TEXTO, não na identidade real.
                pior = {"delta": delta, "conta": c["rotulo"], "conta_id": c["id"],
                        "dt": d["dt"]}
        resumo.append({
            "conta_id": c["id"], "rotulo": c["rotulo"], "ident": c["ident"],
            "banco": banco_da_conta(c)[0], "banco_nome": banco_da_conta(c)[1],
            "mapeada": c.get("erp_banco") is not None,
            "erp": (f"{c['erp_banco']} / ag {c['erp_agencia']} / cc {c['erp_conta']}"
                    if c.get("erp_banco") is not None else None),
            "formato_csv": bool(c.get("mapa_csv")),
            "farol": f, "dias_validados": len(validos), "dias_divergentes": len(divergentes),
            "ultimo_extrato": ult_por_conta.get(c["id"]),
        })
        if conta_id is not None and c["id"] == conta_id:
            dias_sel = dias
    # sem conta escolhida, a tabela dia a dia abre na primeira conta com dado.
    # Reaproveita `dias_por_conta` (ja calculado no loop acima) em vez de
    # recomparar - `arm.lancamentos` aqui e so SQLite local (para achar a
    # primeira conta com extrato no periodo), zero query nova ao ERP.
    if conta_id is None:
        for c in contas:
            if arm.lancamentos(esquema, c["id"], dt_de, dt_ate):
                dias_sel = dias_por_conta[c["id"]]
                conta_id = c["id"]
                break

    return {
        "kpis": {
            "contas": len(contas),
            "contas_sem_mapa": sum(1 for r in resumo if not r["mapeada"]),
            "dias_validados": tot_val,
            "dias_divergentes": tot_div,
            "maior_diferenca": (pior or {}).get("delta"),
            "maior_diferenca_conta": (pior or {}).get("conta"),
            "maior_diferenca_conta_id": (pior or {}).get("conta_id"),
            "maior_diferenca_dt": (pior or {}).get("dt"),
            "ultimo_upload": (imps[0]["quando"] if imps else None),
        },
        "conta_selecionada": conta_id,
        "contas": resumo,
        "dias": dias_sel,
        "lancamentos_dia": (arm.lancamentos(esquema, conta_id, dt_de, dt_ate)
                            if conta_id is not None else []),
        "importacoes": imps,
        # A posicao NAO obedece ao filtro de periodo da tela, de proposito:
        # saldo e posicao, nao movimento de janela. Vai no painel (e nao num
        # endpoint proprio) porque e a primeira pergunta de quem sobe o extrato
        # todo dia - custa UMA consulta ao ERP, com DISTINCT ON.
        "posicao": posicao(esquema),
        "conciliacao_nativa": conciliacao_nativa(),
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "extrato importado (OFX/CSV) x contacorrente_saldo do ERP AVA",
    }


def conciliar(conta_id: int, dt_de: str, dt_ate: str, esquema=None) -> dict:
    """Conciliacao linha a linha de UMA conta.

    Endpoint proprio, e nao mais um campo do `painel`: o painel percorre TODAS
    as contas e ja faz uma consulta ao ERP por conta; trazer o razao inteiro de
    cada uma (a Caixa tem 622 linhas em 26 dias, o Bradesco 1.767) multiplicaria
    o custo da tela que abre por padrao para entregar um detalhe que so se olha
    numa conta por vez.
    """
    arm.init_db(esquema)
    conta = _conta_por_id(esquema, conta_id)
    if conta is None:
        raise ValueError(f"conta_id {conta_id} nao existe.")
    if conta.get("erp_banco") is None:
        return {"ok": False, "precisa": "mapa_erp", "conta": conta,
                "mensagem": "Esta conta ainda nao esta vinculada a uma conta do ERP - "
                            "sem o vinculo nao ha razao com que comparar."}

    banco = [{"dt": x["dt"], "valor": x["valor"],
              "historico": x.get("historico") or "",
              "numerodoc": x.get("numerodoc") or "",
              "ref": f"b{x['id']}"}
             for x in arm.lancamentos(esquema, conta_id, dt_de, dt_ate)]

    rows = db.query(ERP_RAZAO_SQL, {
        "banco": conta["erp_banco"], "agencia": conta["erp_agencia"],
        "conta": conta["erp_conta"], "dt_de": dt_de, "dt_ate": dt_ate})
    erp = [{"dt": r["dt"].isoformat() if hasattr(r["dt"], "isoformat") else str(r["dt"]),
            "valor": r["valor"],
            "historico": " ".join((r["historico"] or "").split()),
            "nominal": " ".join((r["nominal"] or "").split()),
            "ref": f"e{r['sequencia']}"}
           for r in rows]

    res = conc.casar(banco, erp)
    cod_banco, nome_banco = banco_da_conta(conta)
    return {
        "ok": True,
        "conta": {**conta, "banco": cod_banco, "banco_nome": nome_banco},
        "dt_de": dt_de, "dt_ate": dt_ate,
        "resumo": res["resumo"],
        "dias": res["dias"],
        # as linhas sem par dos DOIS lados sao o trabalho que sobra para a
        # pessoa; os pares casados nao vao para a tela porque sao justamente o
        # que ja nao precisa de atencao - e sao a maioria do volume.
        "sobra_banco": res["sobra_banco"],
        "sobra_erp": res["sobra_erp"],
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "fonte": "ext_lancamento (import local) x contacorrente (ERP AVA)",
    }


def posicao(esquema=None) -> dict:
    """Quanto ha em cada banco, segundo o EXTRATO, e o que o ERP diz do mesmo.

    E a pergunta da rotina diaria: subi o extrato de ontem, os saldos estao
    atualizados? Por isso ela NAO obedece ao filtro de periodo da tela - saldo
    e posicao, nao movimento de janela; filtrar por periodo devolveria o saldo
    de uma data escolhida por engano no filtro.

    O TOTAL CONSOLIDADO soma posicoes que podem ser de DIAS DIFERENTES: uma
    conta com extrato de ontem e outra parada ha uma semana entram juntas. Isso
    e o certo (e o dinheiro que se sabe ter), mas nao pode ser dito calado -
    `datas_diferentes` e `dt_mais_antiga` sobem junto para a tela declarar.

    Conta sem ancora de saldo nenhuma fica com `saldo=None` e o motivo em
    `sem_saldo_por`, nunca com zero: zero e um saldo, ausencia nao e.
    """
    arm.init_db(esquema)
    hoje = date.today().isoformat()
    contas = arm.listar_contas(esquema)

    # lado ERP: uma consulta so, indexada por (banco, agencia, conta)
    try:
        erp = {(r["banco"], str(r["agencia"]), str(r["conta"])):
               {"dt": r["dt"].isoformat() if hasattr(r["dt"], "isoformat") else str(r["dt"]),
                "saldo": r["saldo"]}
               for r in db.query(POSICAO_ERP_SQL)}
    except Exception:              # noqa: BLE001
        # A posicao do extrato e local (SQLite) e nao depende do ERP. Com o AVA
        # fora, mostrar o saldo do banco mesmo assim e melhor que esconder a
        # tela inteira - a coluna do ERP e' que fica vazia, dizendo isso.
        erp = {}

    # UMA vez, fora do laco: `ultimo_dt_por_conta` varre a tabela inteira, e
    # chama-la por conta multiplicava isso pelo numero de contas.
    ult_por_conta = arm.ultimo_dt_por_conta(esquema)

    linhas, total, base_ok = [], 0.0, []
    for c in contas:
        saldos = arm.saldos_extrato(esquema, c["id"])
        ult_lanc = ult_por_conta.get(c["id"])
        cod_banco, nome_banco = banco_da_conta(c)
        item = {"conta_id": c["id"], "rotulo": c["rotulo"], "ident": c["ident"],
                "banco": cod_banco, "banco_nome": nome_banco,
                "mapeada": c.get("erp_banco") is not None,
                "saldo": None, "dt": None, "sem_saldo_por": None,
                "erp_saldo": None, "erp_dt": None, "diferenca": None,
                "atraso_uteis": (cmp.atraso_uteis(ult_lanc, hoje) if ult_lanc else None),
                "ultimo_extrato": ult_lanc}
        if not saldos:
            item["sem_saldo_por"] = (
                "o arquivo deste banco nao traz saldo utilizavel (sem LEDGERBAL, "
                "ou com a data zerada)" if ult_lanc else
                "nenhum extrato importado ainda")
        else:
            por_dia = cmp.agregar_extrato(
                arm.lancamentos(esquema, c["id"], min(s["dt"] for s in saldos), hoje))
            der = cmp.saldo_derivado(por_dia, saldos)
            dt = max(der) if der else None
            if dt is not None:
                item["saldo"] = round(der[dt], 2)
                item["dt"] = dt
                total += der[dt]
                base_ok.append(dt)

        if c.get("erp_banco") is not None:
            e = erp.get((c["erp_banco"], str(c["erp_agencia"]), str(c["erp_conta"])))
            if e:
                item["erp_saldo"] = round(e["saldo"], 2)
                item["erp_dt"] = e["dt"]
                if item["saldo"] is not None:
                    item["diferenca"] = round(item["saldo"] - e["saldo"], 2)
        linhas.append(item)

    # o que exige acao primeiro: atrasado, depois sem saldo, depois maior valor
    linhas.sort(key=lambda x: (-(x["atraso_uteis"] or 0), x["saldo"] is not None,
                               -abs(x["saldo"] or 0)))
    return {
        "linhas": linhas,
        "total": round(total, 2),
        "contas_no_total": len(base_ok),
        "contas_sem_saldo": sum(1 for x in linhas if x["saldo"] is None),
        "datas_diferentes": len(set(base_ok)) > 1,
        "dt_mais_antiga": (min(base_ok) if base_ok else None),
        "dt_mais_nova": (max(base_ok) if base_ok else None),
        "atrasadas": sum(1 for x in linhas if (x["atraso_uteis"] or 0) > 0),
        "erp_disponivel": bool(erp),
        "hoje": hoje,
    }
