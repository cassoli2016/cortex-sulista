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


# Conciliação NATIVA do ERP (extratobancario.situacao), achada explorando o
# Avacorp ao vivo: o AVA tem feed automático de extrato bancário (29 mil
# linhas), separado do import manual OFX/CSV acima, com seu próprio farol
# (1 Pendente, 2 Conciliado, 3 Oculto - valores confirmados no <select> da
# tela nativa "Extrato Bancário - Conciliação"; código 4 existe no dado mas
# não aparece nesse filtro, cai em "outro"). Hoje só UMA conta tem esse feed
# (Bradesco 237/36455/1239066) e 93,9% do que ela recebeu desde 2023 está
# Pendente, incluindo lançamentos do mês corrente - não é só passivo
# histórico. Mostrado à parte do farol OFX/CSV: são fontes e mecanismos
# diferentes, não podem se misturar num único número.
CONCIL_SITUACAO = {1: "Pendente", 2: "Conciliado", 3: "Oculto"}

CONCIL_RESUMO_SQL = """
SELECT situacao, count(*)::int AS qtd,
       coalesce(sum(CASE WHEN tipo='C' THEN valor ELSE 0 END),0)::float8 AS creditos,
       coalesce(sum(CASE WHEN tipo='D' THEN valor ELSE 0 END),0)::float8 AS debitos
FROM extratobancario
GROUP BY 1 ORDER BY 1
"""

CONCIL_CONTA_SQL = """
SELECT e.banco, coalesce(b.nome, 'Banco '||e.banco) AS banco_nome, e.agencia, e.conta,
       count(*)::int AS total,
       sum(CASE WHEN e.situacao=1 THEN 1 ELSE 0 END)::int AS pendentes,
       coalesce(sum(CASE WHEN e.situacao=1 THEN e.valor ELSE 0 END),0)::float8 AS valor_pendente,
       min(CASE WHEN e.situacao=1 THEN e.dtmovimento END)::text AS pendente_mais_antigo,
       max(e.dtmovimento)::text AS ultimo_movimento
FROM extratobancario e
LEFT JOIN banco b ON b.codigo = e.banco
GROUP BY e.banco, b.nome, e.agencia, e.conta
ORDER BY pendentes DESC
"""

# Só os 12 meses mais recentes: o backlog desde 2023 é grande demais para um
# gráfico mensal legível, e o que importa para ação é se o atraso é CORRENTE.
CONCIL_MENSAL_SQL = """
SELECT to_char(dtmovimento,'YYYY-MM') AS mes,
       sum(CASE WHEN situacao=1 THEN 1 ELSE 0 END)::int AS pendentes,
       sum(CASE WHEN situacao=2 THEN 1 ELSE 0 END)::int AS conciliados,
       coalesce(sum(CASE WHEN situacao=1 THEN valor ELSE 0 END),0)::float8 AS valor_pendente
FROM extratobancario
WHERE dtmovimento >= current_date - interval '12 months'
GROUP BY 1 ORDER BY 1
"""


def conciliacao_nativa() -> dict:
    resumo = db.query(CONCIL_RESUMO_SQL)
    contas = db.query(CONCIL_CONTA_SQL)
    mensal = db.query(CONCIL_MENSAL_SQL)

    total = sum(r["qtd"] for r in resumo)
    pend = next((r for r in resumo if r["situacao"] == 1), None)
    pend_qtd = pend["qtd"] if pend else 0
    pend_valor = (pend["creditos"] + pend["debitos"]) if pend else 0.0

    return {
        "resumo": [{"situacao": CONCIL_SITUACAO.get(r["situacao"], "Outro"),
                     "qtd": r["qtd"], "creditos": r["creditos"], "debitos": r["debitos"]}
                    for r in resumo],
        "contas": [{**c, "rotulo": f"{c['banco_nome']} ag. {c['agencia']} cc {c['conta']}"}
                    for c in contas if c["total"] > 0],
        "mensal": mensal,
        "kpis": {
            "total": total, "pendentes": pend_qtd,
            "pct_pendente": round(100 * pend_qtd / total, 1) if total else 0.0,
            "valor_pendente": pend_valor,
            "contas_com_feed": sum(1 for c in contas if c["total"] > 0),
        },
        "fonte": "ERP AVA - extratobancario.situacao (feed nativo do banco, separado do import OFX/CSV acima)",
    }


def ident_csv(erp_banco: int, erp_agencia: str, erp_conta: str) -> str:
    """Identidade de conta CSV = a conta bancária real (banco/agência/conta do
    ERP), nunca o nome do arquivo. Usada pela tela de mapeamento (Task 6) ao
    criar a conta, antes do primeiro `importar(..., conta_id=...)`."""
    return f"csv:{erp_banco}/{erp_agencia}/{erp_conta}"


def _conta_por_id(path, conta_id: int) -> dict | None:
    return next((c for c in arm.listar_contas(path) if c["id"] == conta_id), None)


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
        out.append({
            "banco": r["banco"], "agencia": r["agencia"], "conta": r["conta"],
            "ultimo_movimento": ultimo.isoformat() if hasattr(ultimo, "isoformat") else str(ultimo),
            "dias": r["dias"],
            "rotulo": f"{r['banco']} / ag {r['agencia']} / cc {r['conta']}",
        })
    return out


def importar(bruto: bytes, nome: str, path=arm.DB_PATH, conta_id: int | None = None) -> dict:
    arm.init_db(path)
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
            cid = arm.obter_ou_criar_conta(path, d["ident"], rotulo)
            conta = arm.conta_por_ident(path, d["ident"])

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

            res = arm.gravar_lancamentos(path, cid, itens, nome, formato,
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
                arm.gravar_saldo_extrato(path, cid, s["dt"], s["saldo"],
                                         importacao_id=res["importacao_id"] or None)
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
                "contas": arm.listar_contas(path), "novas": 0, "duplicadas": 0, "ignoradas": 0}
    conta = _conta_por_id(path, conta_id)
    if conta is None:
        raise ValueError(f"conta_id {conta_id} nao existe.")
    if not conta.get("mapa_csv"):
        return {"ok": False, "precisa": "mapa_csv", "conta_id": conta_id, "conta": conta,
                "preview": preview_csv(bruto), "novas": 0, "duplicadas": 0, "ignoradas": 0}
    d = parse_csv(bruto, conta["mapa_csv"])
    res = arm.gravar_lancamentos(path, conta_id, d["itens"], nome, "csv", d["ignoradas"])
    datas = sorted(i["dt"] for i in d["itens"]) or [None]
    base = {"conta_id": conta_id, "conta": conta, "novas": res["novas"],
            "duplicadas": res["duplicadas"], "ignoradas": d["ignoradas"],
            "dt_de": datas[0], "dt_ate": datas[-1]}
    if conta.get("erp_banco") is None:
        return {"ok": False, "precisa": "mapa_erp", **base}
    return {"ok": True, **base}


def painel(dt_de: str, dt_ate: str, conta_id: int | None = None, path=arm.DB_PATH) -> dict:
    arm.init_db(path)
    hoje = date.today().isoformat()
    contas = arm.listar_contas(path)
    imps = arm.listar_importacoes(path)   # só para a TABELA de importações da tela
    # ult_por_conta ("último dia coberto por conta") vem direto do banco, sem o
    # LIMIT 20 de `imps` acima - ele governa o farol (achado C1, crítico): usar
    # a lista limitada da tela fazia uma conta de upload pouco frequente cair
    # fora das 20 mais novas, ficar com `ultimo_upload=None` e o farol julgar
    # "desatualizado" por ausência de dado, escondendo divergência real.
    ult_por_conta = arm.ultimo_dt_por_conta(path)

    resumo, dias_sel = [], []
    dias_por_conta: dict[int, list[dict]] = {}
    tot_div = tot_val = 0
    pior = None
    for c in contas:
        lancs = arm.lancamentos(path, c["id"], dt_de, dt_ate)
        saldos = arm.saldos_extrato(path, c["id"])
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
            if arm.lancamentos(path, c["id"], dt_de, dt_ate):
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
        "lancamentos_dia": (arm.lancamentos(path, conta_id, dt_de, dt_ate)
                            if conta_id is not None else []),
        "importacoes": imps,
        "conciliacao_nativa": conciliacao_nativa(),
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "extrato importado (OFX/CSV) x contacorrente_saldo do ERP AVA",
    }


def conciliar(conta_id: int, dt_de: str, dt_ate: str, path=arm.DB_PATH) -> dict:
    """Conciliacao linha a linha de UMA conta.

    Endpoint proprio, e nao mais um campo do `painel`: o painel percorre TODAS
    as contas e ja faz uma consulta ao ERP por conta; trazer o razao inteiro de
    cada uma (a Caixa tem 622 linhas em 26 dias, o Bradesco 1.767) multiplicaria
    o custo da tela que abre por padrao para entregar um detalhe que so se olha
    numa conta por vez.
    """
    arm.init_db(path)
    conta = _conta_por_id(path, conta_id)
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
             for x in arm.lancamentos(path, conta_id, dt_de, dt_ate)]

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
    return {
        "ok": True, "conta": conta, "dt_de": dt_de, "dt_ate": dt_ate,
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
