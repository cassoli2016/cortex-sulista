"""O painel do CRM: o que decide, numa tela.

Só LÊ, agrega e ordena por urgência. É a parte que precisa ser rápida e a que
mais vai mudar — por isso é um módulo separado, como o `painel` da Gestão.

TRÊS CUIDADOS QUE VÊM DE ERROS DA CASA:

- **Todo total traz a COMPOSIÇÃO que o desarma.** "Pipeline R$ 4,2 mi" com 70%
  em qualificação não é pipeline; é intenção. O KPI leva a quebra e o valor
  ponderado ao lado, pela mesma razão que o "Potencial R$ 36,7 mi" do CRM
  antigo teve de mostrar que 82% dos leads eram frios.
- **KPI que só pode dar zero por falta de preenchimento mostra "não
  informado", nunca R$ 0 — e jamais em verde.** Oportunidade sem lane e sem
  valor manual não é negócio de valor zero: é cadastro incompleto, e a
  cobertura é dita.
- **Série mensal é GERADA, não colhida.** `GROUP BY` não devolve o mês que não
  existe, e um mês sem fechamento nenhum some — emendando dois meses distantes
  numa linha contínua que parece tendência.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .. import pglocal
from . import ava, contratos, oportunidades
from .comum import (ESTAGIOS, PROB_PADRAO, ROTULO_ESTAGIO, ROTULO_MOTIVO,
                    _esq, hoje)

# Quantos dias sem NENHUMA interação fazem uma conta virar assunto. 45 dias é
# menos que o corte de carteira parada (90 dias sem viagem) de propósito: o
# objetivo aqui é falar ANTES de o cliente parar de rodar, não depois.
SEM_CONTATO_DIAS = 45

# Janela do histórico de conversão e ciclo. 12 meses porque menos que isso, num
# time comercial pequeno, tem meses com duas ou três oportunidades fechadas — e
# taxa de conversão sobre três casos é ruído com cara de indicador.
JANELA_MESES = 12


def tudo(*, esquema: str | None = None) -> dict:
    """A tela inteira, numa chamada.

    Vai tudo junto porque a tela não desenha nada sem o conjunto, e sete
    chamadas para montar um painel são sete chances de meia tela na rede ruim
    — o mesmo motivo do `/api/gestao/painel`.
    """
    esq = _esq(esquema)
    from . import projetos as _prj
    abertas = oportunidades.listar(esquema=esq)
    fechadas = _fechadas(esq)
    contas = _contas(esq)
    ctrs = contratos.listar(esquema=esq)
    projs = _prj.listar(esquema=esq)
    return {
        "kpis": {**_kpis(abertas, fechadas, contas, ctrs),
                 **_kpis_projetos(projs)},
        "projetos": projs,
        "funil": _funil(abertas),
        "previsao": _previsao(abertas),
        "fechamentos": _fechamentos_mensais(fechadas),
        "motivos_perda": _motivos(fechadas),
        "carteira": _carteira(contas),
        "alertas": _alertas(abertas, contas, ctrs, esq, projs),
        "corredores": _corredores(esq),
        "atualizado_em": _agora_iso(),
        "fonte": ("CÓRTEX · crm_* (banco local) × ERP AVA "
                  "(agrupamentocliente/programação de embarque, receita real) "
                  "· situação e vigência DERIVADAS na leitura"),
    }


def _agora_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _fechadas(esq: str | None) -> list[dict]:
    """Oportunidades fechadas na janela — a base de conversão e de ciclo."""
    corte = (hoje().replace(day=1) - timedelta(days=31 * JANELA_MESES))
    todas = oportunidades.listar(incluir_fechadas=True, esquema=esq)
    return [o for o in todas
            if o["estagio"] in ("ganha", "perdida") and o.get("fechada_em")
            and o["fechada_em"] >= corte.isoformat()]


def _contas(esq: str | None):
    from . import contas as mod
    return mod.listar(esquema=esq)


# --------------------------------------------------------------------- KPIs --

def _kpis(abertas: list[dict], fechadas: list[dict], contas: list[dict],
          ctrs: list[dict]) -> dict:
    com_valor = [o for o in abertas if o["receita_mes"] is not None]
    sem_valor = len(abertas) - len(com_valor)
    pipeline = sum(o["receita_mes"] for o in com_valor)
    ponderado = sum(o["valor_ponderado"] for o in com_valor)

    ganhas = [o for o in fechadas if o["estagio"] == "ganha"]
    perdidas = [o for o in fechadas if o["estagio"] == "perdida"]
    total_fech = len(ganhas) + len(perdidas)

    ciclos = [o["idade_dias"] for o in ganhas if o.get("idade_dias") is not None]
    ciclos.sort()

    ativos = [c for c in contas if c["situacao"] == "ativo"]
    parados = [c for c in contas if c["situacao"] == "parado"]

    return {
        # Pipeline com a COBERTURA ao lado: um total que ignora 8 oportunidades
        # sem valor não é o valor do pipeline, e apresentá-lo como se fosse é o
        # erro do "ROB R$ 0 em verde".
        "pipeline_mes": pipeline if com_valor else None,
        "pipeline_oportunidades": len(abertas),
        "pipeline_sem_valor": sem_valor,
        "pipeline_ponderado": ponderado if com_valor else None,
        "pipeline_anual": sum(
            (o.get("valor_total") or (o["receita_mes"] * 12))
            for o in com_valor) if com_valor else None,

        # Conversão sobre a janela, com o denominador dito. Taxa sem o número
        # de casos engana: 100% sobre uma oportunidade não é 100%.
        "conversao": (len(ganhas) / total_fech) if total_fech else None,
        "fechadas_janela": total_fech,
        "ganhas_janela": len(ganhas),
        "receita_ganha": sum(o["receita_mes"] for o in ganhas
                             if o["receita_mes"] is not None) or None,

        # MEDIANA e não média: uma negociação de 400 dias distorce a média e
        # some na mediana — a mesma escolha do time-to-fill das vagas de RH.
        "ciclo_mediano": (ciclos[len(ciclos) // 2] if ciclos else None),
        "ciclo_casos": len(ciclos),

        "contas": len(contas),
        "contas_ativas": len(ativos),
        "contas_paradas": len(parados),
        "prospects": sum(1 for c in contas if c["situacao"] == "prospect"),
        "receita_carteira_12m": sum(c["receita_12m"] or 0 for c in contas) or None,

        "contratos_vigentes": sum(1 for c in ctrs if c["situacao"] == "vigente"),
        "contratos_a_vencer": sum(1 for c in ctrs if c["situacao"] == "a_vencer"),
        "reajustes_pendentes": sum(1 for c in ctrs if c["reajuste_pendente"]),
    }


# -------------------------------------------------------------------- funil --

def _funil(abertas: list[dict]) -> list[dict]:
    """Contagem e valor por estágio, NA ORDEM do funil.

    Estágio vazio entra com zero em vez de sumir: um funil com três colunas
    quando o processo tem quatro faz parecer que a etapa não existe, quando o
    que ela está dizendo é "não há nada aqui" — que é a informação mais
    acionável do gráfico.
    """
    por = {e: {"n": 0, "valor": 0.0, "ponderado": 0.0, "sem_valor": 0}
           for e in ESTAGIOS}
    for o in abertas:
        b = por.setdefault(o["estagio"], {"n": 0, "valor": 0.0,
                                          "ponderado": 0.0, "sem_valor": 0})
        b["n"] += 1
        if o["receita_mes"] is None:
            b["sem_valor"] += 1
        else:
            b["valor"] += o["receita_mes"]
            b["ponderado"] += o["valor_ponderado"]
    return [{"estagio": e, "rotulo": ROTULO_ESTAGIO[e],
             "probabilidade_padrao": PROB_PADRAO[e], **por[e]}
            for e in ESTAGIOS]


def _previsao(abertas: list[dict], meses: int = 6) -> dict:
    """Fechamento previsto por mês, ponderado — o mês É GERADO, não colhido.

    Mês sem nenhuma previsão entra zerado. Sem isso o gráfico emenda outubro em
    janeiro e desenha uma linha contínua sobre dois meses vazios, que é a mesma
    confusão que fez a jornada emendar abril em agosto sobre quatro meses de
    coleta parada.

    O balde `sem_previsao` existe porque oportunidade sem data prevista não
    pertence a mês nenhum, e distribuí-la em algum inventaria uma previsão. Ela
    é contada à parte e a tela diz quantas são — é lacuna de cadastro, e
    lacuna dita é acionável.
    """
    hj = hoje()
    chaves: list[str] = []
    ano, mes = hj.year, hj.month
    for _ in range(meses):
        chaves.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes == 13:
            mes, ano = 1, ano + 1
    por: dict[str, dict] = {k: {"mes": k, "n": 0, "valor": 0.0,
                                "ponderado": 0.0} for k in chaves}
    sem_previsao = {"n": 0, "valor": 0.0}
    vencidas = {"n": 0, "valor": 0.0}
    for o in abertas:
        prev = o.get("previsao_fechamento")
        v = o["receita_mes"] or 0.0
        if not prev:
            sem_previsao["n"] += 1
            sem_previsao["valor"] += v
            continue
        if o.get("previsao_vencida"):
            vencidas["n"] += 1
            vencidas["valor"] += v
            continue
        k = prev[:7]
        if k in por:
            por[k]["n"] += 1
            por[k]["valor"] += v
            por[k]["ponderado"] += o["valor_ponderado"] or 0.0
        else:
            # Além do horizonte desenhado. Não some: vira a última coluna com
            # rótulo próprio, senão o total do gráfico não bate com o KPI.
            por.setdefault("adiante", {"mes": "adiante", "n": 0, "valor": 0.0,
                                       "ponderado": 0.0})
            por["adiante"]["n"] += 1
            por["adiante"]["valor"] += v
            por["adiante"]["ponderado"] += o["valor_ponderado"] or 0.0
    saida = [por[k] for k in chaves]
    if "adiante" in por:
        saida.append(por["adiante"])
    return {"meses": saida, "sem_previsao": sem_previsao, "vencidas": vencidas}


def _fechamentos_mensais(fechadas: list[dict]) -> list[dict]:
    """Ganhas × perdidas por mês, com o intervalo GERADO."""
    hj = hoje()
    chaves: list[str] = []
    ano, mes = hj.year, hj.month
    for _ in range(JANELA_MESES):
        chaves.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    chaves.reverse()
    por = {k: {"mes": k, "ganhas": 0, "perdidas": 0, "receita_ganha": 0.0}
           for k in chaves}
    for o in fechadas:
        k = (o.get("fechada_em") or "")[:7]
        if k not in por:
            continue
        if o["estagio"] == "ganha":
            por[k]["ganhas"] += 1
            por[k]["receita_ganha"] += o["receita_mes"] or 0.0
        else:
            por[k]["perdidas"] += 1
    linhas = [por[k] for k in chaves]
    # O mês corrente é PARCIAL — hachurado no gráfico e dito no rótulo. Barra
    # cheia num mês em curso faz o último ponto parecer queda, que é o erro
    # mais fácil de cometer em série mensal.
    if linhas:
        linhas[-1]["parcial"] = True
    return linhas


def _motivos(fechadas: list[dict]) -> list[dict]:
    """Por que se perde, ordenado — o dado que transforma perda em decisão."""
    por: dict[str, dict] = defaultdict(lambda: {"n": 0, "valor": 0.0})
    for o in fechadas:
        if o["estagio"] != "perdida":
            continue
        m = o.get("motivo_perda") or "outro"
        por[m]["n"] += 1
        por[m]["valor"] += o["receita_mes"] or 0.0
    total = sum(b["n"] for b in por.values())
    return sorted(
        [{"motivo": m, "rotulo": ROTULO_MOTIVO.get(m, m), "n": b["n"],
          "valor": b["valor"], "pct": (b["n"] / total) if total else None}
         for m, b in por.items()],
        key=lambda x: -x["n"])


def _carteira(contas: list[dict]) -> dict:
    """A carteira pelos olhos do ERP, não pelo cadastro do CRM.

    Ordena as PARADAS por receita dos 12 meses, e não por dias parados: um
    cliente de R$ 2 mil parado há 200 dias e um de R$ 900 mil parado há 95 são
    urgências muito diferentes, e a ordem por tempo põe o errado no topo.
    """
    parados = sorted(
        [c for c in contas if c["situacao"] == "parado"],
        key=lambda c: -(c.get("receita_12m") or 0))
    top = sorted([c for c in contas if c.get("receita_12m")],
                 key=lambda c: -(c["receita_12m"] or 0))[:15]
    receita_total = sum(c.get("receita_12m") or 0 for c in contas)
    acumulado = 0.0
    concentracao = []
    for i, c in enumerate(top, 1):
        acumulado += c["receita_12m"] or 0
        concentracao.append({"posicao": i, "conta": c["nome"],
                             "receita_12m": c["receita_12m"],
                             "pct_acumulado": (acumulado / receita_total)
                             if receita_total else None})
    return {
        "parados": [_resumo_conta(c) for c in parados[:20]],
        "parados_total": len(parados),
        "top": [_resumo_conta(c) for c in top],
        "concentracao": concentracao,
        "receita_total_12m": receita_total or None,
        "sem_historico": sum(1 for c in contas if c["situacao"] == "sem_historico"),
        "corte_parada_dias": ava.PARADA_DIAS,
    }


def _resumo_conta(c: dict) -> dict:
    return {"id": c["id"], "nome": c["nome"], "segmento": c.get("segmento"),
            "dono_nome": c.get("dono_nome"), "situacao": c["situacao"],
            "dias_sem_viagem": c.get("dias_sem_viagem"),
            "receita_12m": c.get("receita_12m"),
            "receita_90d": c.get("receita_90d"),
            "viagens_12m": c.get("viagens_12m"),
            "ultima_viagem": c.get("ultima_viagem")}


# ------------------------------------------------------------------ alertas --

def _prj_parado_dias() -> int:
    from . import projetos as _p
    return _p.PARADO_DIAS


def _kpis_projetos(projs: list[dict]) -> dict:
    """Os números do que está sendo ENTREGUE, não do que está sendo vendido.

    `rob_em_entrega` é a soma do ROB prometido dos projetos abertos — a receita
    que já foi vendida e ainda não virou regime. Fica ao lado do pipeline no
    painel porque são coisas diferentes: pipeline é o que pode entrar, isto é o
    que JÁ entrou e depende da operação para acontecer.
    """
    com_valor = [p for p in projs if p["rob_mensal"] is not None]
    return {
        "projetos_abertos": len(projs),
        "projetos_atrasados": sum(1 for p in projs if p["atrasado"]),
        "projetos_parados": sum(1 for p in projs if p["parado"]),
        "projetos_sem_valor": len(projs) - len(com_valor),
        "rob_em_entrega": (sum(p["rob_mensal"] for p in com_valor)
                           if com_valor else None),
    }


def _alertas(abertas: list[dict], contas: list[dict], ctrs: list[dict],
             esq: str | None, projs: list[dict] | None = None) -> list[dict]:
    """O que exige ação AGORA, do mais grave para o menos.

    Alerta que acende sem haver problema ensina a ignorar o alerta — a lição do
    cartão vermelho da Saúde. Por isso cada linha aqui exige uma providência
    concreta, e nenhuma acende por estado normal: contrato indeterminado não
    vence, prospect não fica "parado", e conta arquivada não aparece.
    """
    from . import atividades as at
    saida: list[dict] = []

    atrasadas = at.listar(atrasadas=True, esquema=esq)
    if atrasadas:
        saida.append({
            "nivel": "alerta", "chave": "atividades_atrasadas",
            "n": len(atrasadas),
            "titulo": f"{len(atrasadas)} atividade(s) com prazo vencido",
            "detalhe": ("Tarefa de follow-up que passou da data. É o indicador "
                        "mais barato de negócio esfriando."),
            "itens": [{"id": a["id"], "assunto": a["assunto"],
                       "conta": a.get("conta_nome"), "quando": a["quando"],
                       "dias": a["dias"],
                       "responsavel": a.get("responsavel_nome")}
                      for a in atrasadas[:10]]})

    vencidas = [o for o in abertas if o.get("previsao_vencida")]
    if vencidas:
        saida.append({
            "nivel": "alerta", "chave": "previsao_vencida", "n": len(vencidas),
            "titulo": f"{len(vencidas)} oportunidade(s) com previsão vencida",
            "detalhe": ("A data prevista de fechamento passou e o negócio "
                        "segue aberto. Ou a data era otimista, ou ele morreu e "
                        "ninguém fechou o cartão — nos dois casos o pipeline "
                        "está mentindo para cima."),
            "itens": [{"id": o["id"], "codigo": o["codigo"],
                       "titulo": o["titulo"], "conta": o.get("conta_nome"),
                       "previsao": o["previsao_fechamento"],
                       "dias": o["dias_para_previsao"],
                       "valor": o["receita_mes"]} for o in vencidas[:10]]})

    piso = _lanes_abaixo_do_piso(abertas, esq)
    if piso:
        saida.append({
            "nivel": "alerta", "chave": "abaixo_piso", "n": len(piso),
            "titulo": f"{len(piso)} lane(s) cotada(s) abaixo do piso ANTT",
            "detalhe": ("O piso mínimo da Lei 13.703/2018 é obrigatório. Frete "
                        "abaixo dele expõe a empresa a autuação e a ação do "
                        "transportador — e a hora de corrigir é antes de a "
                        "proposta sair."),
            "itens": piso[:10]})

    atrasados = [p for p in (projs or []) if p["atrasado"]]
    if atrasados:
        atrasados.sort(key=lambda p: p["dias_para_deadline"] or 0)
        saida.append({
            "nivel": "alerta", "chave": "projeto_atrasado", "n": len(atrasados),
            "titulo": f"{len(atrasados)} projeto(s) com o prazo estourado",
            "detalhe": ("O prazo combinado passou e o projeto segue aberto. É "
                        "o cliente esperando uma implantação que já deveria "
                        "estar no ar — e quem cobra é ele, não a tela."),
            "itens": [{"id": p["id"], "codigo": p["codigo"], "nome": p["nome"],
                       "conta": p.get("conta_nome"), "deadline": p["deadline"],
                       "dias": p["dias_para_deadline"],
                       "status": p["status_rotulo"],
                       "responsavel": p.get("responsavel_nome")}
                      for p in atrasados[:10]]})

    parados = [p for p in (projs or []) if p["parado"] and not p["atrasado"]]
    if parados:
        parados.sort(key=lambda p: -(p["parado_dias"] or 0))
        saida.append({
            "nivel": "aviso", "chave": "projeto_parado", "n": len(parados),
            "titulo": f"{len(parados)} projeto(s) sem andamento há mais de "
                      f"{_prj_parado_dias()} dias",
            "detalhe": ("O status diz que está andando e o histórico diz que "
                        "ninguém escreve nada há semanas. Quem desmente o "
                        "status é o último andamento — projeto em implantação "
                        "tem cadência semanal."),
            "itens": [{"id": p["id"], "codigo": p["codigo"], "nome": p["nome"],
                       "conta": p.get("conta_nome"),
                       "dias": p["parado_dias"], "status": p["status_rotulo"],
                       "percentual": p["percentual"],
                       "responsavel": p.get("responsavel_nome")}
                      for p in parados[:10]]})

    reaj = [c for c in ctrs if c["reajuste_pendente"]]
    if reaj:
        saida.append({
            "nivel": "aviso", "chave": "reajuste_pendente", "n": len(reaj),
            "titulo": f"{len(reaj)} contrato(s) com reajuste do ciclo pendente",
            "detalhe": ("O mês de reajuste passou e não há registro de "
                        "aplicação neste ciclo. É dinheiro na mesa que só "
                        "aparece quando alguém pergunta."),
            "itens": [{"id": c["id"], "codigo": c["codigo"],
                       "conta": c.get("conta_nome"),
                       "indice": c["indice_rotulo"],
                       "ciclo": c["reajuste_ciclo"],
                       "dias": c["reajuste_dias"]} for c in reaj[:10]]})

    vencer = [c for c in ctrs if c["situacao"] == "a_vencer"]
    if vencer:
        saida.append({
            "nivel": "aviso", "chave": "contrato_a_vencer", "n": len(vencer),
            "titulo": f"{len(vencer)} contrato(s) vencendo em até "
                      f"{contratos.AVISO_DIAS} dias",
            "detalhe": ("Com aviso prévio e rodada de negociação, começar no "
                        "mês do vencimento é começar tarde."),
            "itens": [{"id": c["id"], "codigo": c["codigo"],
                       "conta": c.get("conta_nome"), "fim": c["fim"],
                       "dias": c["dias_para_fim"],
                       "renovacao_automatica": c["renovacao_automatica"]}
                      for c in vencer[:10]]})

    parados = [c for c in contas if c["situacao"] == "parado"]
    if parados:
        parados.sort(key=lambda c: -(c.get("receita_12m") or 0))
        saida.append({
            "nivel": "aviso", "chave": "carteira_parada", "n": len(parados),
            "titulo": f"{len(parados)} cliente(s) sem viagem há mais de "
                      f"{ava.PARADA_DIAS} dias",
            "detalhe": ("Leitura da receita REAL do ERP, não do cadastro. "
                        "Ordenado por faturamento dos últimos 12 meses — o "
                        "cliente grande parado há 95 dias é mais urgente que o "
                        "pequeno parado há 200."),
            "itens": [_resumo_conta(c) for c in parados[:10]]})

    frias = _contas_sem_contato(contas, esq)
    if frias:
        saida.append({
            "nivel": "aviso", "chave": "sem_contato", "n": len(frias),
            "titulo": f"{len(frias)} conta(s) sem contato há mais de "
                      f"{SEM_CONTATO_DIAS} dias",
            "detalhe": ("Nenhuma interação registrada na janela. O corte é "
                        "menor que o de carteira parada de propósito: a ideia "
                        "é falar antes de o cliente parar de rodar."),
            "itens": frias[:10]})
    return saida


def _lanes_abaixo_do_piso(abertas: list[dict], esq: str | None) -> list[dict]:
    """As lanes de oportunidade aberta cujo preço está abaixo do piso legal.

    Avalia com a tabela ANTT vigente HOJE, não com a da data da proposta: a
    pergunta aqui é "se isso fechar agora, está legal?", e a tabela que vale é
    a de agora.
    """
    if not abertas:
        return []
    from . import precificacao
    ref = precificacao.referencia_ckm()
    por_opo = {o["id"]: o for o in abertas}
    todas = oportunidades.lanes_de_varias(
        [o["id"] for o in abertas if o.get("lanes")], referencia=ref,
        esquema=esq)
    achados: list[dict] = []
    for oid, lista in todas.items():
        o = por_opo.get(oid)
        if not o:
            continue
        for ln in lista:
            p = (ln.get("calc") or {}).get("piso") or {}
            if not p.get("abaixo"):
                continue
            achados.append({
                "oportunidade_id": oid, "codigo": o["codigo"],
                "conta": o.get("conta_nome"), "lane": ln["rotulo"],
                "valor_viagem": ln.get("valor_viagem"),
                "piso": p.get("valor"), "gap": p.get("gap")})
    achados.sort(key=lambda x: (x["gap"] if x["gap"] is not None else 0))
    return achados


def _contas_sem_contato(contas: list[dict], esq: str | None) -> list[dict]:
    """Contas cuja última interação passou do corte — ou que nunca tiveram.

    Uma consulta agregada para todas, não uma por conta: são dezenas de contas
    na tela de abertura.

    Prospect sem contato entra; conta ARQUIVADA não chega aqui (a lista já vem
    sem elas). Alerta sobre registro arquivado é ruído por definição.
    """
    if not contas:
        return []
    linhas = pglocal.query(
        "SELECT conta_id, max(ts) AS ultima FROM crm_interacoes "
        "GROUP BY conta_id", None, esquema=esq)
    ultima = {int(r["conta_id"]): r["ultima"] for r in linhas}
    limite = (hoje() - timedelta(days=SEM_CONTATO_DIAS)).isoformat()
    saida = []
    for c in contas:
        u = ultima.get(c["id"])
        if u and u[:10] > limite:
            continue
        # CONTA MAIS NOVA QUE O CORTE NÃO ESTÁ "SEM CONTATO HÁ 45 DIAS" — ela
        # não existe há 45 dias. A ausência aí mede a idade do CADASTRO, não a
        # do relacionamento, e sem esta guarda a semeadura inicial acendeu o
        # alerta para 29 de 29 contas no primeiro dia. Alarme que dispara para
        # 100% da base ensina a ignorar o alarme — é a mesma família do cartão
        # vermelho da Saúde por recusa normal do fornecedor, e do reajuste
        # cobrado de um contrato de dois meses.
        if not u and (c.get("criado_em") or "")[:10] > limite:
            continue
        saida.append({"id": c["id"], "nome": c["nome"],
                      "situacao": c["situacao"],
                      "dono_nome": c.get("dono_nome"),
                      "receita_12m": c.get("receita_12m"),
                      "ultimo_contato": u,
                      "dias": None if not u else
                      (hoje() - date.fromisoformat(u[:10])).days})
    # Nunca contatadas primeiro (dias None), depois as mais antigas. Uma conta
    # que nunca recebeu contato nenhum é o caso mais grave e cairia no fim de
    # uma ordenação numérica ingênua.
    saida.sort(key=lambda x: (x["dias"] is not None, -(x["dias"] or 0),
                              -(x["receita_12m"] or 0)))
    return saida


def _corredores(esq: str | None) -> list[dict]:
    """Os pares origem→destino mais presentes nas oportunidades ABERTAS.

    Responde "onde a demanda está pedindo capacidade", que é a pergunta que
    liga o comercial à operação — e que um CRM genérico não sabe fazer porque
    não tem a lane como unidade.
    """
    linhas = pglocal.query("""
        SELECT l.origem_uf, l.destino_uf,
               count(*) AS lanes,
               sum(CASE WHEN l.valor_viagem IS NOT NULL AND l.viagens_mes IS NOT NULL
                        THEN l.valor_viagem * l.viagens_mes ELSE 0 END) AS receita,
               sum(coalesce(l.viagens_mes, 0)) AS viagens_mes
        FROM crm_lanes l
        JOIN crm_oportunidades o ON o.id = l.oportunidade_id
        WHERE o.estagio NOT IN ('ganha', 'perdida')
          AND l.origem_uf <> '' AND l.destino_uf <> ''
        GROUP BY 1, 2
        ORDER BY 4 DESC
        LIMIT 12
    """, None, esquema=esq)
    return [{"origem_uf": r["origem_uf"], "destino_uf": r["destino_uf"],
             "corredor": f"{r['origem_uf']} → {r['destino_uf']}",
             "lanes": int(r["lanes"]),
             "receita": float(r["receita"] or 0),
             "viagens_mes": float(r["viagens_mes"] or 0)} for r in linhas]


def minhas(usuario_id: int | None, *, esquema: str | None = None) -> dict:
    """A fila de quem está olhando — "minha carteira", sem restringir ninguém.

    A visibilidade é aberta (todo mundo vê tudo); o dono é ATRIBUIÇÃO, e este
    recorte é conveniência de quem trabalha, não controle de acesso. Sem
    usuário identificado devolve vazio em vez de tudo: uma tela que diz "minhas
    12 atividades" mostrando as do time inteiro é pior que uma tela vazia.
    """
    if not usuario_id:
        return {"atividades": [], "oportunidades": [], "contas": 0}
    from . import atividades as at
    from . import contas as mod
    esq = _esq(esquema)
    hj = hoje().isoformat()
    ativ = at.listar(responsavel_id=usuario_id, status="aberta", esquema=esq)
    return {
        "atividades": ativ,
        "atrasadas": sum(1 for a in ativ if a["atrasada"]),
        "hoje": sum(1 for a in ativ if a.get("quando") == hj),
        "oportunidades": oportunidades.listar(dono_id=usuario_id, esquema=esq),
        "contas": len(mod.listar(dono_id=usuario_id, esquema=esq)),
    }
