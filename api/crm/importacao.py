"""Importação do CRM do ERP (Avacorp) para o CRM do CÓRTEX (15/09/2026).

DECISÃO DE QUEM OPERA, com as alternativas na mesa: o CÓRTEX passa a ser o CRM
da casa. O que o time comercial lançou no ERP (`sulista.gestaocomercial`,
`pipelineprojetos`, `pipelineprojetos_repactuacoes`) vem para cá — e a
importação pode rodar de novo sem duplicar nada, para pegar o que ainda for
lançado lá até a virada. O QUE JÁ FOI IMPORTADO NUNCA É REESCRITO: a partir da
importação o registro é do CÓRTEX, e reimportar por cima apagaria o que o time
editou aqui (`crm_importados` é o rastro que garante isso).

É o oposto do que `sql/cortex/0026_crm.sql` decidiu quando o CRM nasceu ("nada
é copiado de lá"). A decisão mudou porque agora alguém pediu, e o risco que ela
apontava — duas verdades sobre o mesmo lead — se resolve deixando UMA viva: a
sub-aba do Avacorp vira histórico.

O QUE VIRA O QUÊ:
- lead → conta (prospect, ou a que já existe com o mesmo nome) + contato +
  oportunidade;
- projeto (a última versão) → projeto do CRM; cada versão → um andamento;
- repactuação → interação na conta do grupo econômico (append-only).

NADA SE PERDE NA TRADUÇÃO. Onde o vocabulário do ERP não tem equivalente exato
no do CÓRTEX (motivo de perda, resultado da negociação do projeto, temperatura,
região), o texto original do ERP vai junto — no detalhe da perda ou nas
observações — em vez de ser forçado a um código que diria outra coisa.

AS DATAS SÃO AS DO ERP. Criação, alteração e andamentos levam o carimbo de lá:
carimbar "agora" faria todo lead importado parecer mexido hoje, e "há quanto
tempo ninguém fala com este cliente" — a pergunta central do CRM — responderia
zero dias para todos.

CONTA SÓ POR NOME NORMALIZADO (caixa, acento, pontuação e espaço), nunca por
aproximação: "SUZANO" e "SUZANO PAPEL E CELULOSE S.A." viram duas contas, e o
relatório aponta a dupla para quem conhece o cliente decidir. Aproximação de
texto que decide a quem pertence um negócio é decisão comercial, não
heurística escondida numa importação.

OS NOMES DE PESSOAS NÃO ESTÃO AQUI. Responsável e solicitante são códigos no
ERP (1, 2, 3…) e o de-para para nome vive em `data/crm_importacao.json`, fora
do git — o repositório é público. Código sem de-para entra como "Responsável N
no ERP", visível, e o relatório lista quais faltam.

UMA TRANSAÇÃO SÓ, E A SIMULAÇÃO É A MESMA CONTA: `importar(aplicar=False)` faz
tudo — inclusive os CHECKs do banco — e desfaz no fim. Simulação escrita à
parte divergiria da importação exatamente onde importa. Cada registro grava
sob o próprio SAVEPOINT: um lead com dado impossível vira linha de falha no
relatório, não a importação inteira desfeita.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .. import pglocal
from ..validacao import DadoInvalido
from .comum import _esq, agora, init_db
from .comum import email as _email
from .comum import telefone as _telefone

FONTE_LEAD = "erp.gestaocomercial"
FONTE_PROJETO = "erp.pipelineprojetos"
FONTE_REPAC = "erp.pipelineprojetos_repactuacoes"
FONTE_CONTA = "erp.conta"
USUARIO = "importação do CRM do ERP"
DONO_PADRAO = "A definir"
CONFIG = Path(__file__).resolve().parents[2] / "data" / "crm_importacao.json"

# Categorias do ERP que NÃO são empresas (ver `scripts/semear_crm.py`): um lead
# chamado "SPOT" não pode ser amarrado ao balde SPOT, que junta 87 CNPJs de
# frete avulso.
BALDES = {"SPOT", "NOVOS CLIENTES", "NOVO SEGMENTO", "REPOSICIONAMENTO", "TEMPORARIO"}

# ── o vocabulário do ERP (Querys Sulista/AVACORP/COMERCIAL - *.sql) ────────
TEMPERATURA = {1: "Frio", 2: "Morno", 3: "Quente"}
# origem do lead: onde há equivalente na lista do CÓRTEX (`comum.ORIGENS`), o
# rótulo de lá; onde não há, o do ERP — `crm_contas.origem` é texto livre.
ORIGEM_LEAD = {1: "Indicação", 2: "Inbound (site)", 3: "LinkedIn / redes sociais",
               4: "Prospecção ativa", 5: "Feira ou evento", 6: "E-mail marketing",
               7: "Parceiro", 8: "Cliente antigo", 9: "Outro"}
# motivo de perda do lead: (código do CÓRTEX, rótulo do ERP). "outro" quando o
# ERP diz algo que o catálogo de cá não diz — e o rótulo vai no detalhe.
MOTIVO_LEAD = {
    "1": ("sem_orcamento", "Sem orçamento"),
    "2": ("nao_qualificado", "Fora do perfil"),
    "3": ("outro", "Sem prioridade no momento"),
    "4": ("concorrente", "Concorrente"),
    "5": ("outro", "Não avançou internamente"),
    "6": ("sem_retorno", "Não respondeu"),
    "7": ("requisito_tecnico", "Produto/escopo não atende"),
    "8": ("outro", "Sem sinergia operacional"),
    "9": ("outro", "Outros"),
}
STATUS_LEAD = {1: "Qualificado", 2: "Não qualificado", 3: "Em prospecção"}
STATUS_PROJETO = {1: "em_execucao", 2: "entregue", 3: "nao_iniciado", 4: "declinado"}
ROTULO_STATUS_ERP = {1: "Em execução", 2: "Entregue", 3: "Não iniciado", 4: "Declinado"}
NEGOCIACAO_PROJETO = {1: "Aceita", 2: "Não aceita", 3: "Em negociação",
                      4: "Declinado", 5: "Somente projeto"}
TIPO_NEGOCIO = {1: "Regular", 2: "SPOT", 3: "Reajuste", 4: "Projeto"}
ESCOPO = {1: "Transporte", 2: "Transferência", 3: "Outbound", 4: "Inbound",
          5: "Crossdocking", 6: "Outro"}
# solicitante: os códigos que NÃO são pessoas ficam aqui; os que são (3, 6, 7)
# vêm do de-para em data/, como os responsáveis
SOLICITANTE_FIXO = {1: "Cliente", 2: "Projetos", 4: "SAC", 5: "Operação"}
REPAC_STATUS = {1: "Aplicada", 2: "Não aplicada", 3: "Realizado BID",
                4: "Rota cancelada", 5: "Contrato rescindido"}

# ── as leituras do ERP (PostgreSQL 9.3: sem FILTER, sem WITHIN GROUP) ──────
LEADS_SQL = """
SELECT g.id, g.data, g.dtinclusao, g.dtalteracao, g.responsavel, g.cliente,
       g.nomecliente, g.emailcliente, g.telefonecliente, g.telefonecliente2,
       g.unidade_regiao, tc.descricao AS segmento, g.origem_lead,
       g.descricao_servico, g.potencial_receita::float8 AS potencial,
       g.temperatura, g.status_negociacao, g.previsao_fechamento,
       g.motivo_perda, g.observacoes, g.ativoinativo
FROM sulista.gestaocomercial g
LEFT JOIN tipocarga tc ON tc.codigo = g.cliente_segmento
ORDER BY g.id
"""

# TODAS as versões: a última vira o projeto, cada uma vira um andamento
PROJETOS_SQL = """
SELECT p.id, p.numeroid, p.versao, p.projeto, p.cliente, tc.descricao AS segmento,
       p.tipo_negocio, p.escopo_principal, p.detalhe_operacao, p.temperatura,
       p.status_negocio, p.status_negociacao, p.data_recebimento, p.data_inicio,
       p.deadline, p.data_entrega, p.data_aceite_declinio, p.solicitante,
       p.responsavel_projeto, p.rob_mensal::float8 AS rob, p.rol_mensal::float8 AS rol,
       p.lucro_bruto::float8 AS lucro, p.lucro_bruto_percentual AS lucro_pct,
       p.csp::float8 AS csp, p.prazocliente, p.motivo_declinio, p.motivo_perda,
       p.data_inclusao, p.data_alteracao
FROM sulista.pipelineprojetos p
LEFT JOIN tipocarga tc ON tc.codigo = p.segmento
ORDER BY p.numeroid, p.versao, p.id
"""

REPAC_SQL = """
SELECT r.id, r.cliente, trim(ac.descricao) AS grupo, r.mes_repac,
       r.porcento_aplicacao_diesel_1::float8 AS d1, r.data_aplicacao_diesel_1 AS dd1,
       r.porcento_aplicacao_diesel_2::float8 AS d2, r.data_aplicacao_diesel_2 AS dd2,
       r.porcento_aplicacao_diesel_3::float8 AS d3, r.data_aplicacao_diesel_3 AS dd3,
       r.porcento_aplicacao_negocios::float8 AS neg, r.data_aplicacao_negocios AS dneg,
       r.total_porcento::float8 AS total, r.status, r.observacao, r.dtinclusao
FROM sulista.pipelineprojetos_repactuacoes r
LEFT JOIN agrupamentocliente ac ON ac.codigo = r.cliente
ORDER BY r.id
"""


# ─────────────────────────────────────────────── peças sem banco ────────────

def normalizar_nome(valor) -> str:
    """Caixa, acento, pontuação e espaço — e só isso. "Tupy S.A." e "TUPY S A"
    são o mesmo nome; "TUPY" e "TUPY SC" não (quem decide é gente)."""
    t = unicodedata.normalize("NFD", str(valor or ""))
    t = t.encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


def _d(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _ts(v, reserva=None) -> str:
    """Carimbo ISO do ERP para os campos `*_em`, sem fuso (como os do CRM)."""
    if isinstance(v, datetime):
        return v.replace(tzinfo=None).isoformat(timespec="seconds")
    d = _d(v)
    if d:
        return d.isoformat() + "T00:00:00"
    return _ts(reserva) if reserva is not None else agora()


def _br(d) -> str:
    d = _d(d)
    return d.strftime("%d/%m/%Y") if d else ""


def _num(v, casas: int = 2) -> str:
    return f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _limpo(v) -> str:
    return str(v or "").strip()


def _linha1(v, maximo: int) -> str:
    """A primeira linha, cortada: título não carrega parágrafo."""
    t = _limpo(v).splitlines()[0].strip() if _limpo(v) else ""
    return t[:maximo]


def estagio_do_lead(r: dict) -> tuple[str, str, str]:
    """(estágio, motivo de perda do CÓRTEX, detalhe) de um lead do ERP.

    Medido em 15/09/2026 (359 leads): 185 "em prospecção" ativos, 36
    "qualificados" ativos, 76 inativados com motivo, 37 "não qualificados".
    - "Não qualificado" não tem estágio aberto no CÓRTEX: é perda com motivo
      `nao_qualificado`, que é como o funil de cá registra essa decisão.
    - Inativado no ERP (`ativoinativo = 2`) é perda, com o motivo de lá — ou
      "outro", dizendo que veio sem motivo.
    - Motivo preenchido num lead que seguia ATIVO (3 casos) não fecha nada:
      quem manda no estado é o ativo/inativo, e o motivo vai nas observações.
    """
    motivo_cod = _limpo(r.get("motivo_perda"))
    cod, rot = MOTIVO_LEAD.get(motivo_cod, ("outro", f"código {motivo_cod}")) \
        if motivo_cod else (None, None)
    if r.get("status_negociacao") == 2:
        det = "Marcado como não qualificado no ERP"
        return "perdida", "nao_qualificado", det + (f" (motivo: {rot})." if rot else ".")
    if r.get("ativoinativo") == 2:
        if cod:
            return "perdida", cod, f"Motivo no ERP: {rot}."
        return "perdida", "outro", "Inativado no ERP sem motivo informado."
    if r.get("status_negociacao") == 1:
        return "levantamento", "", ""
    return "qualificacao", "", ""


def oportunidade_do_lead(r: dict) -> dict:
    """Os campos da oportunidade (sem conta, dono e código, que dependem do banco)."""
    estagio, motivo, detalhe = estagio_do_lead(r)
    abertura = _d(r.get("data")) or _d(r.get("dtinclusao")) or date.today()
    fechada = None
    if estagio in ("ganha", "perdida"):
        fechada = _d(r.get("dtalteracao")) or _d(r.get("dtinclusao")) or abertura
        # tempo de ciclo negativo não existe: se o ERP fechou "antes" de abrir,
        # vale a abertura (a data original fica nas observações pelo carimbo)
        fechada = max(fechada, abertura)
    obs = [f"Importado do CRM do ERP (lead nº {r.get('id')})."]
    if TEMPERATURA.get(r.get("temperatura")):
        obs.append(f"Temperatura no ERP: {TEMPERATURA[r['temperatura']]}.")
    if STATUS_LEAD.get(r.get("status_negociacao")):
        obs.append(f"Status no ERP: {STATUS_LEAD[r['status_negociacao']]}.")
    if _limpo(r.get("unidade_regiao")):
        obs.append(f"Unidade/região no ERP: {_limpo(r['unidade_regiao'])}.")
    motivo_cod = _limpo(r.get("motivo_perda"))
    if estagio not in ("ganha", "perdida") and motivo_cod:
        rot = MOTIVO_LEAD.get(motivo_cod, ("", f"código {motivo_cod}"))[1]
        obs.append(f"Motivo de perda registrado no ERP ({rot}), mas o lead seguia "
                   "ativo lá — por isso entrou aberto.")
    if _limpo(r.get("observacoes")):
        obs.append("Observações no ERP: " + _limpo(r["observacoes"]))
    potencial = r.get("potencial")
    return {
        "titulo": _linha1(r.get("descricao_servico"), 200) or f"Lead {_limpo(r.get('cliente'))}",
        "tipo": "contrato", "estagio": estagio, "probabilidade": None,
        # o potencial é MENSAL (quem opera, 15/09/2026)
        "receita_mensal_manual": round(float(potencial), 2) if potencial and potencial > 0 else None,
        "abertura": abertura, "previsao_fechamento": _d(r.get("previsao_fechamento")),
        "fechada_em": fechada, "motivo_perda": motivo, "perda_detalhe": detalhe,
        "observacoes": "\n".join(obs),
        "criado_em": _ts(r.get("dtinclusao")),
        "alterado_em": _ts(r.get("dtalteracao"), r.get("dtinclusao")),
    }


def contato_do_lead(r: dict) -> dict | None:
    """O contato do lead, com e-mail e telefone pelos validadores da casa. O que
    eles não reconhecem vai nas observações do contato, em vez de sumir — e em
    vez de entrar num formato que o envio depois recusaria."""
    nome = _linha1(r.get("nomecliente"), 120)
    email_bruto = _limpo(r.get("emailcliente"))
    tel = _limpo(r.get("telefonecliente"))
    tel2 = _limpo(r.get("telefonecliente2"))
    if not (nome or email_bruto or tel):
        return None
    obs = []
    try:
        email = _email(email_bruto)
    except DadoInvalido:
        email = ""
        obs.append(f"E-mail no ERP não reconhecido: {email_bruto}")
    try:
        telefone = _telefone(tel)
    except DadoInvalido:
        telefone = ""
        obs.append(f"Telefone no ERP não reconhecido: {tel}")
    if tel2:
        obs.append(f"Segundo telefone no ERP: {tel2}")
    return {"nome": nome or email or "Contato do lead", "email": email,
            "telefone": telefone, "observacoes": "\n".join(obs)}


def _pessoa_cfg(cfg: dict, tipo: str, codigo, faltam: set) -> str:
    if codigo in (None, ""):
        return ""
    nome = (cfg.get(tipo) or {}).get(str(codigo))
    if nome:
        return nome
    faltam.add(f"{tipo} {codigo}")
    return f"{'Solicitante' if tipo == 'solicitante' else 'Responsável'} {codigo} no ERP"


def _ordem(campos: dict, obs: list) -> None:
    """As datas na ordem que o banco exige (`crm_proj_ordem_ck`). A data fora
    de ordem sai do campo e fica escrita — nunca se inventa outra no lugar."""
    for antes, depois, rot in (("recebimento", "inicio_real", "início"),
                               ("inicio_real", "entrega", "entrega"),
                               ("entrega", "aceite", "aceite")):
        a, b = campos.get(antes), campos.get(depois)
        if a and b and b < a:
            if depois == "entrega":           # entrega é obrigatória no entregue
                obs.append(f"Data de início no ERP ({_br(a)}) posterior à entrega: "
                           "fora do campo.")
                campos[antes] = None
            else:
                obs.append(f"Data de {rot} no ERP ({_br(b)}) fora de ordem: fora do campo.")
                campos[depois] = None


def projeto_do_erp(r: dict, cfg: dict, faltam: set) -> tuple[dict, str]:
    """Os campos do projeto (última versão) e o nome do responsável.

    Medido em 15/09/2026 (207 projetos): 173 "entregues" — no ERP o projeto é o
    ESTUDO/PROPOSTA, e "entregue" quer dizer proposta entregue ao cliente; o
    resultado comercial (aceita, não aceita, em negociação) é outro campo, que
    vai nas observações. E duas datas que o banco de cá recusa por desenho:
    21 projetos não entregues COM data de entrega e 2 entregues SEM ela.
    """
    status = STATUS_PROJETO.get(r.get("status_negocio"), "nao_iniciado")
    obs = [f"Importado do CRM do ERP (projeto nº {r.get('numeroid')}, "
           f"versão {r.get('versao') or 1})."]
    campos = {"recebimento": _d(r.get("data_recebimento")), "inicio_real": _d(r.get("data_inicio")),
              "deadline": _d(r.get("deadline")), "entrega": _d(r.get("data_entrega")),
              "aceite": _d(r.get("data_aceite_declinio"))}
    if status != "entregue" and campos["entrega"]:
        obs.append(f"Data de entrega no ERP: {_br(campos['entrega'])} — fora do campo "
                   "porque o projeto não está como entregue.")
        campos["entrega"] = None
    if status == "entregue" and not campos["entrega"]:
        for rot, cand in (("data de aceite/declínio", campos["aceite"]),
                          ("data da última alteração", _d(r.get("data_alteracao"))),
                          ("data de inclusão", _d(r.get("data_inclusao")))):
            if cand:
                campos["entrega"] = cand
                obs.append(f"Entregue no ERP sem data de entrega: usada a {rot} ({_br(cand)}).")
                break
    _ordem(campos, obs)
    neg = NEGOCIACAO_PROJETO.get(r.get("status_negociacao"))
    if neg:
        obs.append(f"Resultado da negociação no ERP: {neg}.")
    if TIPO_NEGOCIO.get(r.get("tipo_negocio")):
        obs.append(f"Tipo de negócio no ERP: {TIPO_NEGOCIO[r['tipo_negocio']]}.")
    if TEMPERATURA.get(r.get("temperatura")):
        obs.append(f"Temperatura no ERP: {TEMPERATURA[r['temperatura']]}.")
    if _limpo(r.get("segmento")):
        obs.append(f"Segmento no ERP: {_limpo(r['segmento'])}.")
    for rot, k in (("ROL/mês", "rol"), ("Lucro bruto/mês", "lucro"), ("CSP", "csp")):
        if r.get(k):
            obs.append(f"{rot} no ERP: R$ {_num(r[k])}.")
    if r.get("lucro_pct") not in (None, 0):
        obs.append(f"Lucro bruto no ERP: {r['lucro_pct']}%.")
    motivo_txt = _limpo(r.get("motivo_declinio")) or _limpo(r.get("motivo_perda"))
    enc, enc_det = "", ""
    if status in ("declinado", "cancelado"):
        enc, enc_det = "outro", (motivo_txt or "Declinado no ERP sem motivo informado.")
    elif motivo_txt:
        obs.append(f"Motivo informado no ERP: {motivo_txt}")
    sol = SOLICITANTE_FIXO.get(r.get("solicitante")) or _pessoa_cfg(
        cfg, "solicitante", r.get("solicitante"), faltam)
    resp = _pessoa_cfg(cfg, "responsavel_projeto", r.get("responsavel_projeto"), faltam) \
        or DONO_PADRAO
    rob = r.get("rob")
    campos.update({
        "nome": _linha1(r.get("projeto"), 200) or f"Projeto {r.get('numeroid')} do ERP",
        "escopo": ESCOPO.get(r.get("escopo_principal"), ""),
        "detalhe": _limpo(r.get("detalhe_operacao")),
        "versao": max(1, int(r.get("versao") or 1)), "status": status,
        "inicio_previsto": None, "prazo_cliente_dias": r.get("prazocliente"),
        "solicitante": sol[:120],
        "rob_mensal_manual": round(float(rob), 2) if rob and rob > 0 else None,
        "percentual": 100 if status == "entregue" else 0,
        "motivo_encerramento": enc, "encerrado_detalhe": enc_det,
        "observacoes": "\n".join(obs),
        "criado_em": _ts(r.get("data_inclusao")),
        "alterado_em": _ts(r.get("data_alteracao"), r.get("data_inclusao")),
    })
    return campos, resp


def andamento_da_versao(v: dict) -> dict:
    partes = [f"Versão {v.get('versao') or 1} no ERP — status: "
              f"{ROTULO_STATUS_ERP.get(v.get('status_negocio'), 'não informado')}"]
    if NEGOCIACAO_PROJETO.get(v.get("status_negociacao")):
        partes.append(f"negociação: {NEGOCIACAO_PROJETO[v['status_negociacao']]}")
    if v.get("rob"):
        partes.append(f"ROB/mês R$ {_num(v['rob'])}")
    motivo = _limpo(v.get("motivo_declinio")) or _limpo(v.get("motivo_perda"))
    if motivo:
        partes.append(f"motivo: {motivo}")
    return {"ts": _ts(v.get("data_alteracao"), v.get("data_inclusao")),
            "texto": "; ".join(partes) + ".",
            "status_para": STATUS_PROJETO.get(v.get("status_negocio")),
            "versao": max(1, int(v.get("versao") or 1))}


def interacao_da_repac(r: dict) -> dict:
    mes = _d(r.get("mes_repac"))
    partes = [f"Repactuação {mes.strftime('%m/%Y') if mes else '(mês não informado)'}"
              + (f" — {REPAC_STATUS[r['status']]}" if REPAC_STATUS.get(r.get("status")) else "")]
    for rot, k, kd in (("diesel 1", "d1", "dd1"), ("diesel 2", "d2", "dd2"),
                       ("diesel 3", "d3", "dd3"), ("negócios", "neg", "dneg")):
        if r.get(k):
            partes.append(f"{rot} {_num(r[k])}%" + (f" em {_br(r[kd])}" if r.get(kd) else ""))
    if r.get("total"):
        partes.append(f"total {_num(r['total'])}%")
    texto = "; ".join(partes) + "."
    if _limpo(r.get("observacao")):
        texto += " Observação no ERP: " + _limpo(r["observacao"])
    return {"ts": _ts(r.get("mes_repac"), r.get("dtinclusao")),
            "resumo": texto + f" (Importado do CRM do ERP, repactuação nº {r.get('id')}.)"}


def _por_projeto(linhas: list[dict]):
    grupos: dict = {}
    for r in linhas:
        grupos.setdefault(r.get("numeroid"), []).append(r)
    for nid in sorted(grupos, key=lambda x: (x is None, x)):
        yield nid, sorted(grupos[nid], key=lambda r: (r.get("versao") or 0, r.get("id") or 0))


# ─────────────────────────────────────────────── as leituras ────────────────

def ler_config(caminho: Path = CONFIG) -> dict:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        d = {}
    cfg = {k: {str(a): str(b) for a, b in (d.get(k) or {}).items()}
           for k in ("responsavel_lead", "responsavel_projeto", "solicitante")}
    # "este nome do ERP É aquela conta": decisão de quem conhece o cliente,
    # escrita — nunca inferida por aproximação (ver o cabeçalho)
    cfg["mesma_conta"] = {normalizar_nome(a): str(b)
                          for a, b in (d.get("mesma_conta") or {}).items()}
    return cfg


def ler_erp() -> dict:
    """As três tabelas do ERP e os grupos econômicos (para vincular pelo nome)."""
    from .. import db
    from . import ava
    return {"leads": db.query(LEADS_SQL, None), "projetos": db.query(PROJETOS_SQL, None),
            "repactuacoes": db.query(REPAC_SQL, None),
            "grupos": {normalizar_nome(g["nome"]): g for g in ava.agrupamentos()}}


# ─────────────────────────────────────────────── o importador ───────────────

class _Simulacao(Exception):
    """Desfaz a transação no fim da simulação."""


class _Importador:
    def __init__(self, c, cfg: dict, grupos: dict):
        self.c, self.cfg, self.grupos = c, cfg, grupos
        self.faltam: set = set()
        self.falhas: list = []
        self.seq: dict = {}
        self.cont: Counter = Counter()
        self.estagios: Counter = Counter()
        self.status_proj: Counter = Counter()
        self.contas_criadas: list[str] = []
        self.sem_conta_repac: list[str] = []

    def _q(self, sql, params=None):
        return self.c.execute(sql, params)

    def carregar(self) -> None:
        self.contas_nome: dict[str, int] = {}
        self.contas_ava: dict[int, int] = {}
        for r in self._q("SELECT id, nome, ava_agrupamento, ava_nome FROM crm_contas ORDER BY id"):
            for n in (r["nome"], r["ava_nome"]):
                if _limpo(n):
                    self.contas_nome.setdefault(normalizar_nome(n), r["id"])
            if r["ava_agrupamento"] is not None:
                self.contas_ava[int(r["ava_agrupamento"])] = r["id"]
        self.nomes_antes = set(self.contas_nome)
        self.importados = {(r["fonte"], r["fonte_id"], r["entidade"]) for r in
                           self._q("SELECT fonte, fonte_id, entidade FROM crm_importados")}
        self.usuarios = {normalizar_nome(r["nome"]): r["id"] for r in
                         self._q("SELECT id, nome FROM usuarios WHERE ativo=1")}
        self.contatos: dict[int, set] = {}

    def _pessoa(self, nome: str) -> tuple[int | None, str]:
        nome = nome or DONO_PADRAO
        return self.usuarios.get(normalizar_nome(nome)), nome[:120]

    def _proximo(self, tabela: str, prefixo: str, ano: int) -> tuple[int, int, str]:
        k = (tabela, ano)
        if k not in self.seq:
            self.seq[k] = int(self._q(
                f"SELECT coalesce(max(sequencia), 0) AS s FROM {tabela} WHERE ano=%s",
                (ano,)).fetchone()["s"])
        self.seq[k] += 1
        return ano, self.seq[k], f"{prefixo}-{ano}-{self.seq[k]:03d}"

    def _registrar(self, fonte: str, fonte_id, entidade: str, registro_id: int) -> None:
        self._q("INSERT INTO crm_importados(fonte, fonte_id, entidade, registro_id, importado_em)"
                " VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (fonte, str(fonte_id), entidade, int(registro_id), agora()))

    def _inserir(self, tabela: str, campos: dict) -> int:
        cols = ", ".join(campos)
        vals = ", ".join(f"%({k})s" for k in campos)
        return int(self._q(f"INSERT INTO {tabela}({cols}) VALUES({vals}) RETURNING id",
                           campos).fetchone()["id"])

    def _conta(self, nome_erp, *, dono: str, criado_em: str, segmento: str = "",
               origem: str = "") -> int:
        """A conta do cliente: a que já existe com o mesmo nome normalizado, ou
        uma nova — vinculada ao grupo econômico do ERP quando o nome é o dele e
        o grupo ainda não tem conta. Em savepoint próprio: se o lead que a pediu
        falhar depois, a conta fica, e o cache nunca aponta para linha desfeita."""
        nome = _linha1(nome_erp, 200) or "Cliente sem nome no ERP"
        n = normalizar_nome(nome)
        alvo = (self.cfg.get("mesma_conta") or {}).get(n)
        if alvo:
            na = normalizar_nome(alvo)
            if na in self.contas_nome:
                self.cont["contas_juntadas"] += 1
                return self.contas_nome[na]
            # de-para apontando para conta que não existe: diz, e segue pelo nome
            self.faltam.add(f"mesma_conta '{nome}' -> '{alvo}' (conta não encontrada)")
        if n in self.contas_nome:
            self.cont["contas_reusadas"] += 1
            return self.contas_nome[n]
        g = self.grupos.get(n)
        ava = None
        if g and normalizar_nome(g["nome"]) not in BALDES \
                and int(g["codigo"]) not in self.contas_ava:
            ava = int(g["codigo"])
        dono_id, dono_nome = self._pessoa(dono)
        with self.c.transaction():
            cid = self._inserir("crm_contas", {
                "nome": nome, "ava_agrupamento": ava, "ava_nome": g["nome"] if ava else "",
                "segmento": _limpo(segmento)[:120], "origem": origem[:120],
                "dono_id": dono_id, "dono_nome": dono_nome,
                "observacoes": ("Conta criada pela importação do CRM do ERP, a partir do nome "
                                "do cliente lá" + (", e vinculada ao grupo econômico de mesmo "
                                                   "nome." if ava else
                                                   ". Sem vínculo com grupo econômico do ERP: é "
                                                   "prospect até alguém vincular.")),
                "criado_por": USUARIO, "criado_em": criado_em,
                "alterado_por": USUARIO, "alterado_em": criado_em})
            self._registrar(FONTE_CONTA, n, "conta", cid)
        self.contas_nome[n] = cid
        if ava is not None:
            self.contas_ava[ava] = cid
            self.cont["contas_vinculadas"] += 1
        self.cont["contas_criadas"] += 1
        self.contas_criadas.append(nome)
        return cid

    def _contatos_de(self, conta_id: int) -> set:
        if conta_id not in self.contatos:
            self.contatos[conta_id] = {
                x for r in self._q("SELECT lower(email) AS e, nome FROM crm_contatos "
                                   "WHERE conta_id=%s", (conta_id,))
                for x in (r["e"], normalizar_nome(r["nome"])) if x}
        return self.contatos[conta_id]

    def lead(self, r: dict) -> None:
        chave = (FONTE_LEAD, str(r["id"]), "oportunidade")
        if chave in self.importados:
            self.cont["leads_ja"] += 1
            return
        try:
            dono = _pessoa_cfg(self.cfg, "responsavel_lead", r.get("responsavel"),
                               self.faltam) or DONO_PADRAO
            conta_id = self._conta(r.get("cliente"), dono=dono, criado_em=_ts(r.get("dtinclusao")),
                                   segmento=r.get("segmento") or "",
                                   origem=ORIGEM_LEAD.get(r.get("origem_lead"), ""))
            op = oportunidade_do_lead(r)
            ct = contato_do_lead(r)
            chaves_ct = set()
            with self.c.transaction():
                ct_id = None
                if ct:
                    chaves_ct = {x for x in (ct["email"], normalizar_nome(ct["nome"])) if x}
                    if not (chaves_ct & self._contatos_de(conta_id)):
                        ct_id = self._inserir("crm_contatos", {
                            "conta_id": conta_id, **ct, "criado_por": USUARIO,
                            "criado_em": op["criado_em"], "alterado_por": USUARIO,
                            "alterado_em": op["alterado_em"]})
                        self._registrar(FONTE_LEAD, r["id"], "contato", ct_id)
                dono_id, dono_nome = self._pessoa(dono)
                ano, seq, codigo = self._proximo("crm_oportunidades", "OPO", op["abertura"].year)
                op_id = self._inserir("crm_oportunidades", {
                    "conta_id": conta_id, "ano": ano, "sequencia": seq, "codigo": codigo,
                    **op, "dono_id": dono_id, "dono_nome": dono_nome,
                    "criado_por": USUARIO, "alterado_por": USUARIO})
                self._registrar(FONTE_LEAD, r["id"], "oportunidade", op_id)
            if ct_id:
                self._contatos_de(conta_id).update(chaves_ct)
                self.cont["contatos"] += 1
            self.importados.add(chave)
            self.cont["leads"] += 1
            self.estagios[op["estagio"]] += 1
        except Exception as exc:  # noqa: BLE001 — vira linha do relatório
            self.falhas.append(("lead", r.get("id"), f"{type(exc).__name__}: {exc}"[:300]))

    def projeto(self, numeroid, versoes: list[dict]) -> None:
        chave = (FONTE_PROJETO, str(numeroid), "projeto")
        if chave in self.importados:
            self.cont["projetos_ja"] += 1
            return
        ultima = versoes[-1]
        try:
            campos, resp = projeto_do_erp(ultima, self.cfg, self.faltam)
            conta_id = self._conta(ultima.get("cliente"), dono=DONO_PADRAO,
                                   criado_em=campos["criado_em"])
            ano_ref = campos["recebimento"] or _d(ultima.get("data_inclusao")) or date.today()
            with self.c.transaction():
                rid, rnome = self._pessoa(resp)
                ano, seq, codigo = self._proximo("crm_projetos", "PRJ", ano_ref.year)
                pid = self._inserir("crm_projetos", {
                    "conta_id": conta_id, "ano": ano, "sequencia": seq, "codigo": codigo,
                    **campos, "responsavel_id": rid, "responsavel_nome": rnome,
                    "criado_por": USUARIO, "alterado_por": USUARIO})
                self._registrar(FONTE_PROJETO, numeroid, "projeto", pid)
                n_and = 0
                for v in versoes:
                    a = andamento_da_versao(v)
                    aid = self._inserir("crm_projeto_andamentos", {
                        "projeto_id": pid, "ts": a["ts"], "usuario": USUARIO,
                        "texto": a["texto"], "status_para": a["status_para"],
                        "versao": a["versao"]})
                    self._registrar(FONTE_PROJETO, f"{numeroid}:{v.get('id')}", "andamento", aid)
                    n_and += 1
            self.importados.add(chave)
            self.cont["projetos"] += 1
            self.cont["andamentos"] += n_and
            self.status_proj[campos["status"]] += 1
        except Exception as exc:  # noqa: BLE001
            self.falhas.append(("projeto", numeroid, f"{type(exc).__name__}: {exc}"[:300]))

    def repactuacao(self, r: dict) -> None:
        chave = (FONTE_REPAC, str(r["id"]), "interacao")
        if chave in self.importados:
            self.cont["repac_ja"] += 1
            return
        cid = self.contas_ava.get(int(r["cliente"])) if r.get("cliente") is not None else None
        if cid is None and _limpo(r.get("grupo")):
            cid = self.contas_nome.get(normalizar_nome(r["grupo"]))
        if cid is None:
            self.sem_conta_repac.append(_limpo(r.get("grupo")) or f"grupo {r.get('cliente')}")
            return
        try:
            it = interacao_da_repac(r)
            with self.c.transaction():
                iid = self._inserir("crm_interacoes", {
                    "conta_id": cid, "canal": "outro", "sentido": "saida", "ts": it["ts"],
                    "usuario": USUARIO, "resumo": it["resumo"][:4000], "automatica": 1})
                self._registrar(FONTE_REPAC, r["id"], "interacao", iid)
            self.importados.add(chave)
            self.cont["repac"] += 1
        except Exception as exc:  # noqa: BLE001
            self.falhas.append(("repactuação", r.get("id"), f"{type(exc).__name__}: {exc}"[:300]))

    def duplicatas_possiveis(self) -> list[tuple[str, str]]:
        """Pares de contas cujo nome COMEÇA pela mesma palavra (4+ letras) — só
        para o relatório, nunca para juntar: quem decide é quem conhece o cliente."""
        todos = {n: n for n in self.contas_nome}
        criados = {normalizar_nome(x) for x in self.contas_criadas}
        pares = set()
        for n in criados:
            p = n.split(" ")[0] if n else ""
            if len(p) < 4:
                continue
            for m in todos:
                if m != n and m.split(" ")[0] == p:
                    pares.add(tuple(sorted((n, m))))
        return sorted(pares)


def importar(*, aplicar: bool = False, esquema: str | None = None,
             erp: dict | None = None, config: dict | None = None) -> dict:
    """Importa (ou simula, com `aplicar=False`) o CRM do ERP. Devolve o relatório."""
    esq = _esq(esquema)
    init_db(esq)
    erp = erp if erp is not None else ler_erp()
    cfg = config if config is not None else ler_config()
    leads, projetos, repacs = erp.get("leads") or [], erp.get("projetos") or [], \
        erp.get("repactuacoes") or []
    imp = None
    try:
        with pglocal.get_conn(esq) as c:
            imp = _Importador(c, cfg, erp.get("grupos") or {})
            imp.carregar()
            for r in leads:
                imp.lead(r)
            for nid, versoes in _por_projeto(projetos):
                imp.projeto(nid, versoes)
            for r in repacs:
                imp.repactuacao(r)
            relatorio = _relatorio(imp, aplicar, leads, projetos, repacs)
            if not aplicar:
                raise _Simulacao
    except _Simulacao:
        pass
    return relatorio


def _relatorio(imp: _Importador, aplicar: bool, leads, projetos, repacs) -> dict:
    n_proj = len({r.get("numeroid") for r in projetos})
    return {
        "aplicado": aplicar,
        "leads": {"lidos": len(leads), "importados": imp.cont["leads"],
                  "ja_importados": imp.cont["leads_ja"], "por_estagio": dict(imp.estagios)},
        "contatos": imp.cont["contatos"],
        "contas": {"criadas": imp.cont["contas_criadas"],
                   "vinculadas_ao_grupo": imp.cont["contas_vinculadas"],
                   "reusadas": imp.cont["contas_reusadas"],
                   "juntadas_pelo_de_para": imp.cont["contas_juntadas"],
                   "nomes_criados": list(imp.contas_criadas)},
        "projetos": {"lidos": n_proj, "linhas": len(projetos), "importados": imp.cont["projetos"],
                     "ja_importados": imp.cont["projetos_ja"], "andamentos": imp.cont["andamentos"],
                     "por_status": dict(imp.status_proj)},
        "repactuacoes": {"lidas": len(repacs), "importadas": imp.cont["repac"],
                         "ja_importadas": imp.cont["repac_ja"],
                         "sem_conta": list(imp.sem_conta_repac)},
        "responsaveis_sem_nome": sorted(imp.faltam),
        "possiveis_duplicatas": imp.duplicatas_possiveis(),
        "falhas": list(imp.falhas),
    }
