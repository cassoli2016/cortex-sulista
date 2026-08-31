"""A tela do CRM no navegador.

O backend tem 44 testes próprios. O que só se prova AQUI:

1. **A tela não estoura no boot.** `pageerror` vazio: o `index.html` é um
   script só, e um erro na avaliação derruba o app INTEIRO, não só esta tela.
   É a armadilha do `const` de topo lendo `CC` (TDZ) e a do `JSON.stringify`
   dentro de atributo, que dá "Unexpected end of input" com a tela em branco.
2. **A base do Avacorp continua viva, e numa aba SEPARADA.** É o pedido que
   originou a tela: o CRM novo abre no Painel, e a base do ERP fica onde
   estava — a um clique, intocada.
3. **Prospect não mostra "R$ 0" de receita.** Zero que é ausência de vínculo
   com o ERP não é desempenho: é `n/d`. Um prospect com R$ 0 cairia no fim de
   um ranking como se faturasse zero — a lição do "0% de retorno vazio em
   verde" da Análise de KM.
4. **Lane abaixo do piso da ANTT grita, e em pt-BR.** É o número que torna a
   cotação diferente de um CRM genérico, e ele já saiu formatado como
   `R$ 4.550.48` (dois pontos, nenhuma vírgula) uma vez.
5. **O cartão do kanban cai na coluna do estágio dele.**
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

USER = {**USUARIO, "admin": False, "perfil": "Comercial",
        "telas": ["crm"], "id": 7}

_HOJE = "2026-08-30"


def _kpis():
    return {"pipeline_mes": 114600.0, "pipeline_oportunidades": 3,
            "pipeline_sem_valor": 1, "pipeline_ponderado": 57300.0,
            "pipeline_anual": 2750400.0, "conversao": 0.4,
            "fechadas_janela": 5, "ganhas_janela": 2,
            "receita_ganha": 88000.0, "ciclo_mediano": 47, "ciclo_casos": 2,
            "contas": 3, "contas_ativas": 1, "contas_paradas": 1,
            "prospects": 1, "receita_carteira_12m": 9800000.0,
            "contratos_vigentes": 1, "contratos_a_vencer": 1,
            "reajustes_pendentes": 1, "projetos_abertos": 3,
            "projetos_atrasados": 1, "projetos_parados": 1,
            "projetos_sem_valor": 0, "rob_em_entrega": 1286250.0}


FUNIL = [
    {"estagio": "qualificacao", "rotulo": "Qualificação", "n": 1,
     "valor": 0.0, "ponderado": 0.0, "sem_valor": 1, "probabilidade_padrao": 10},
    {"estagio": "levantamento", "rotulo": "Levantamento", "n": 0,
     "valor": 0.0, "ponderado": 0.0, "sem_valor": 0, "probabilidade_padrao": 25},
    {"estagio": "proposta", "rotulo": "Proposta", "n": 1, "valor": 105600.0,
     "ponderado": 52800.0, "sem_valor": 0, "probabilidade_padrao": 50},
    {"estagio": "negociacao", "rotulo": "Negociação", "n": 1, "valor": 9000.0,
     "ponderado": 4500.0, "sem_valor": 0, "probabilidade_padrao": 75},
]

PREVISAO = {"meses": [{"mes": "2026-08", "n": 0, "valor": 0.0, "ponderado": 0.0},
                      {"mes": "2026-09", "n": 1, "valor": 105600.0, "ponderado": 52800.0},
                      {"mes": "2026-10", "n": 0, "valor": 0.0, "ponderado": 0.0},
                      {"mes": "2026-11", "n": 1, "valor": 9000.0, "ponderado": 4500.0},
                      {"mes": "2026-12", "n": 0, "valor": 0.0, "ponderado": 0.0},
                      {"mes": "2027-01", "n": 0, "valor": 0.0, "ponderado": 0.0}],
            "sem_previsao": {"n": 1, "valor": 0.0},
            "vencidas": {"n": 0, "valor": 0.0}}

ALERTAS = [
    {"nivel": "alerta", "chave": "abaixo_piso", "n": 1,
     "titulo": "1 lane(s) cotada(s) abaixo do piso ANTT",
     "detalhe": "O piso mínimo da Lei 13.703/2018 é obrigatório.",
     "itens": [{"oportunidade_id": 1, "codigo": "OPO-2026-001",
                "conta": "TUPY FUNDIÇÕES", "lane": "Joinville/SC → Betim/MG",
                "valor_viagem": 4800.0, "piso": 9350.48, "gap": -4550.48}]},
    {"nivel": "aviso", "chave": "carteira_parada", "n": 1,
     "titulo": "1 cliente(s) sem viagem há mais de 90 dias",
     "detalhe": "Leitura da receita REAL do ERP.",
     "itens": [{"id": 2, "nome": "FORVIA", "segmento": "Automotivo",
                "dono_nome": "Ana", "situacao": "parado",
                "dias_sem_viagem": 140, "receita_12m": 2400000.0,
                "receita_90d": 0.0, "viagens_12m": 310,
                "ultima_viagem": "2026-04-12"}]},
]

FECHAMENTOS = [{"mes": f"2026-{m:02d}", "ganhas": (m % 3),
                "perdidas": (m % 2), "receita_ganha": 12000.0 * (m % 3)}
               for m in range(1, 13)]
FECHAMENTOS[-1]["parcial"] = True

MOTIVOS = [{"motivo": "preco", "rotulo": "Preço", "n": 4, "valor": 48000.0,
            "pct": 0.5},
           {"motivo": "capacidade", "rotulo": "Capacidade", "n": 2,
            "valor": 21000.0, "pct": 0.25},
           {"motivo": "sem_retorno", "rotulo": "Cliente parou de responder",
            "n": 2, "valor": 9000.0, "pct": 0.25}]

CONCENTRACAO = [{"posicao": 1, "conta": "TUPY FUNDIÇÕES",
                 "receita_12m": 7400000.0, "pct_acumulado": 0.755},
                {"posicao": 2, "conta": "FORVIA", "receita_12m": 2400000.0,
                 "pct_acumulado": 1.0}]

CORREDORES = [{"origem_uf": "SC", "destino_uf": "MG", "corredor": "SC → MG",
               "lanes": 2, "receita": 105600.0, "viagens_mes": 22.0},
              {"origem_uf": "PR", "destino_uf": "SP", "corredor": "PR → SP",
               "lanes": 1, "receita": 9000.0, "viagens_mes": 10.0}]

PAINEL = {"kpis": _kpis(), "funil": FUNIL, "previsao": PREVISAO,
          "fechamentos": FECHAMENTOS, "motivos_perda": MOTIVOS,
          "carteira": {"parados": [], "parados_total": 1, "top": [],
                       "concentracao": CONCENTRACAO,
                       "receita_total_12m": 9800000.0,
                       "sem_historico": 0, "corte_parada_dias": 90},
          "alertas": ALERTAS, "corredores": CORREDORES,
          "minhas": {"atividades": [], "atrasadas": 0, "hoje": 0,
                     "oportunidades": [], "contas": 1},
          "atualizado_em": _HOJE + "T20:00:00", "fonte": "CÓRTEX"}

CATALOGO = {
    "segmentos": ["Automotivo", "Siderurgia e metalurgia"],
    "origens": ["Prospecção ativa", "Indicação"],
    "papeis": [{"valor": "decisor", "rotulo": "Decisor"},
               {"valor": "comprador", "rotulo": "Comprador"},
               {"valor": "operacional", "rotulo": "Operacional"}],
    "estagios": [{"valor": f["estagio"], "rotulo": f["rotulo"],
                  "probabilidade": f["probabilidade_padrao"]} for f in FUNIL],
    "estagios_fechados": [{"valor": "ganha", "rotulo": "Ganha"},
                          {"valor": "perdida", "rotulo": "Perdida"}],
    "tipos": [{"valor": "contrato", "rotulo": "Contrato"},
              {"valor": "spot", "rotulo": "Spot"}],
    "motivos_perda": [{"valor": "preco", "rotulo": "Preço"},
                      {"valor": "capacidade", "rotulo": "Capacidade"}],
    "cargas": [{"valor": "carga_geral", "rotulo": "Carga geral"}],
    "veiculos": [{"nome": "Carreta LS (3 eixos)", "eixos": 6}],
    "atividades": {"tipos": [{"valor": "ligacao", "rotulo": "Ligação"},
                             {"valor": "cotacao", "rotulo": "Cotação"}],
                   "canais": [{"valor": "ligacao", "rotulo": "Ligação"},
                              {"valor": "email", "rotulo": "E-mail"}],
                   "sentidos": [{"valor": "saida", "rotulo": "Nós procuramos"},
                                {"valor": "entrada", "rotulo": "O cliente procurou"}]},
    "contratos": {"indices": [{"valor": "ipca", "rotulo": "IPCA"}],
                  "aviso_dias": 90},
    "projetos": {"status": [{"valor": "nao_iniciado", "rotulo": "Não iniciado"},
                            {"valor": "implantacao", "rotulo": "Em implantação"},
                            {"valor": "em_execucao", "rotulo": "Em execução"},
                            {"valor": "entregue", "rotulo": "Entregue"},
                            {"valor": "declinado", "rotulo": "Declinado"},
                            {"valor": "cancelado", "rotulo": "Cancelado"}],
                 "status_abertos": ["nao_iniciado", "implantacao", "em_execucao"],
                 "motivos": [{"valor": "prazo", "rotulo": "Prazo inexequível"}],
                 "escopos": ["Transporte FTL", "Milk run"],
                 "parado_dias": 21},
    "usuarios": [{"id": 7, "nome": "Ana Souza", "email": "ana@x",
                  "cargo": "", "setor": ""}],
    "agrupamentos": [{"codigo": 7, "nome": "TUPY"}],
    "erp_indisponivel": None,
    "canais": {"whatsapp": {"disponivel": True, "motivo": ""},
               "email": {"disponivel": False,
                         "motivo": "Servidor SMTP não configurado."}},
}


def _conta(i, nome, situacao, **kw):
    d = {"id": i, "nome": nome, "nome_fantasia": "", "cnpj": "",
         "cnpj_fmt": "", "ava_agrupamento": None, "ava_nome": "",
         "segmento": "Automotivo", "origem": "", "cidade": "", "uf": "",
         "site": "", "dono_id": 7, "dono_nome": "Ana Souza",
         "observacoes": "", "arquivada": False, "situacao": situacao,
         "dias_sem_viagem": None, "receita_12m": None, "receita_90d": None,
         "viagens_12m": None, "km_12m": None, "ultima_viagem": None,
         "dias_sem_contato": None, "criado_por": "", "criado_em": "",
         "alterado_por": "", "alterado_em": ""}
    d.update(kw)
    return d


CONTAS = [
    _conta(1, "TUPY FUNDIÇÕES", "ativo", ava_agrupamento=7, ava_nome="TUPY",
           receita_12m=7400000.0, viagens_12m=980, dias_sem_viagem=3,
           ultima_viagem="2026-08-27", dias_sem_contato=2,
           cnpj_fmt="84.683.374/0001-49"),
    _conta(2, "FORVIA", "parado", ava_agrupamento=9, ava_nome="FORVIA",
           receita_12m=2400000.0, viagens_12m=310, dias_sem_viagem=140,
           ultima_viagem="2026-04-12", dias_sem_contato=60),
    _conta(3, "NOVA INDÚSTRIA", "prospect"),
]


def _opo(i, titulo, estagio, **kw):
    d = {"id": i, "conta_id": 1, "conta_nome": "TUPY FUNDIÇÕES",
         "conta_ava": 7, "ano": 2026, "sequencia": i,
         "codigo": f"OPO-2026-{i:03d}", "titulo": titulo, "tipo": "contrato",
         "tipo_rotulo": "Contrato", "estagio": estagio,
         "estagio_rotulo": dict((f["estagio"], f["rotulo"]) for f in FUNIL)
         .get(estagio, estagio),
         "probabilidade": None, "probabilidade_efetiva": 50,
         "probabilidade_padrao": True, "receita_mensal_manual": None,
         "receita_mes": None, "origem_receita": None, "valor_ponderado": None,
         "valor_total": None, "meses_contrato": None, "dono_id": 7,
         "dono_nome": "Ana Souza", "abertura": "2026-06-01",
         "previsao_fechamento": None, "fechada_em": None, "motivo_perda": "",
         "motivo_rotulo": None, "perda_detalhe": "", "concorrente": "",
         "observacoes": "", "aberta": estagio not in ("ganha", "perdida"),
         "lanes": 0, "lanes_sem_preco": 0, "km_mes": None,
         "dias_para_previsao": None, "previsao_vencida": False,
         "idade_dias": 90, "criado_por": "", "criado_em": "",
         "alterado_por": "", "alterado_em": ""}
    d.update(kw)
    return d


OPOS = [
    _opo(1, "Contrato 2027 — eixo sul", "proposta", receita_mes=105600.0,
         origem_receita="lanes", valor_ponderado=52800.0, lanes=2,
         meses_contrato=24, valor_total=2534400.0,
         previsao_fechamento="2026-09-30"),
    _opo(2, "Spot setembro", "negociacao", receita_mes=9000.0,
         origem_receita="manual", valor_ponderado=4500.0,
         probabilidade_efetiva=75, previsao_fechamento="2026-11-15"),
    _opo(3, "Sondagem NOVA", "qualificacao", conta_id=3,
         conta_nome="NOVA INDÚSTRIA", probabilidade_efetiva=10),
]

LANE_RUIM = {
    "id": 1, "oportunidade_id": 1, "contrato_id": None,
    "origem_cidade": "Joinville", "origem_uf": "SC",
    "destino_cidade": "Betim", "destino_uf": "MG", "km": 1180.0,
    "km_vazio": 1180.0, "tipo_veiculo": "Carreta LS (3 eixos)", "eixos": 6,
    "tipo_carga": "carga_geral", "carga_rotulo": "Carga geral",
    "viagens_mes": 22.0, "valor_viagem": 4800.0, "pedagio": None,
    "observacoes": "", "ordem": 0, "rotulo": "Joinville/SC → Betim/MG",
    "calc": {"km_total_viagem": 2360.0, "receita_mes": 105600.0,
             "km_mes": 51920.0, "rkm": 4.0678, "rkm_total": 2.0339,
             "retorno_vazio": 0.5,
             "piso": {"estado": "calculado", "valor": 9350.48, "ccd": 7.5,
                      "cc": 500.0, "resolucao": "5.867/2020",
                      "gap": -4550.48, "abaixo": True, "motivo": None,
                      "por_km": 7.924},
             "pedagio_mes": None, "ckm_marginal": 3.5, "ckm_cheio": 5.2,
             "ckm_bruto": 2.45, "ckm_bruto_cheio": 3.64,
             "custo_viagem": 5782.0, "resultado_viagem": -982.0,
             "resultado_viagem_cheio": -3790.4,
             "margem_km": -0.416, "margem_mes": -21604.0, "margem_pct": -0.2046,
             "alerta": {"nivel": "alerta",
                        "texto": "abaixo do piso ANTT em R$ 4.550,48",
                        "detalhe": "O piso mínimo é obrigatório."}},
}

OPO_FICHA = {**OPOS[0], "conta_segmento": "Automotivo",
             "lanes_detalhe": [LANE_RUIM],
             "resumo_lanes": {"lanes": 1, "receita_mes": 105600.0,
                              "km_mes": 51920.0, "margem_mes": -76115.0,
                              "margem_pct": -0.72, "rkm_medio": 2.03,
                              "lanes_sem_preco": 0, "lanes_abaixo_piso": 1,
                              "lanes_sem_piso": 0},
             "referencia_ckm": {"disponivel": True, "ckm_marginal": 3.5,
                                "ckm_cheio": 5.2, "fonte": "Make vs Buy"}}

ATIVS = [{"id": 1, "conta_id": 1, "conta_efetiva": 1,
          "conta_nome": "TUPY FUNDIÇÕES", "oportunidade_id": 1,
          "oportunidade_codigo": "OPO-2026-001",
          "oportunidade_titulo": "Contrato 2027", "contato_id": None,
          "contato_nome": None, "tipo": "ligacao", "tipo_rotulo": "Ligação",
          "assunto": "Retornar sobre a proposta", "detalhe": "",
          "quando": "2026-08-20", "hora": "", "responsavel_id": 7,
          "responsavel_nome": "Ana Souza", "status": "aberta",
          "concluida_em": None, "atrasada": True, "dias": -10, "hoje": False,
          "criado_por": "", "criado_em": "", "alterado_por": "",
          "alterado_em": ""}]

CTRS = [{"id": 1, "conta_id": 1, "conta_nome": "TUPY FUNDIÇÕES",
         "conta_ava": 7, "oportunidade_id": None,
         "oportunidade_codigo": None, "ano": 2026, "sequencia": 1,
         "codigo": "CTR-2026-001", "objeto": "Transporte FTL eixo sul",
         "inicio": "2025-01-01", "fim": "2026-10-31",
         "renovacao_automatica": True, "aviso_previo_dias": 30,
         "indice_reajuste": "ipca", "indice_rotulo": "IPCA",
         "mes_reajuste": 1, "ultimo_reajuste": "2025-01-01",
         "percentual_ultimo": 6.5, "prazo_pagamento_dias": 30, "dono_id": 7,
         "dono_nome": "Ana Souza", "cancelado_em": None,
         "cancelado_motivo": "", "observacoes": "", "situacao": "a_vencer",
         "dias_para_fim": 62, "indeterminado": False,
         "reajuste_pendente": True, "reajuste_ciclo": "2026-01-01",
         "reajuste_dias": 242, "lanes": 2, "receita_lanes": 105600.0,
         "criado_por": "", "criado_em": "", "alterado_por": "",
         "alterado_em": ""}]

def _proj(i, nome, status, **kw):
    d = {"id": i, "conta_id": 1, "conta_nome": "TUPY FUNDIÇÕES",
         "conta_ava": 7, "oportunidade_id": 1,
         "oportunidade_codigo": "OPO-2026-001", "contrato_id": None,
         "contrato_codigo": None, "ano": 2026, "sequencia": i,
         "codigo": f"PRJ-2026-{i:03d}", "nome": nome, "escopo": "Transporte FTL",
         "detalhe": "", "versao": 1, "status": status,
         "status_rotulo": {"nao_iniciado": "Não iniciado",
                           "implantacao": "Em implantação",
                           "em_execucao": "Em execução",
                           "entregue": "Entregue"}.get(status, status),
         "motivo_encerramento": "", "motivo_rotulo": None,
         "aberto": status not in ("entregue", "declinado", "cancelado"),
         "recebimento": "2026-05-01", "inicio_previsto": "2026-06-01",
         "deadline": "2026-09-30", "inicio_real": "2026-06-05",
         "entrega": None, "aceite": None, "prazo_cliente_dias": None,
         "solicitante": "Compras", "responsavel_id": 7,
         "responsavel_nome": "Ana Souza", "rob_mensal_manual": None,
         "rob_mensal": 428750.0, "origem_rob": "lanes", "percentual": 40,
         "lanes": 1, "lanes_sem_preco": 0, "observacoes": "",
         "dias_para_deadline": 30, "atrasado": False, "dias_de_atraso": None,
         "no_prazo": None, "duracao_dias": None, "idade_dias": 120,
         "ultimo_andamento": "2026-08-29T10:00:00", "andamentos": 3,
         "parado_dias": 2, "parado": False, "criado_por": "", "criado_em": "",
         "alterado_por": "", "alterado_em": ""}
    d.update(kw)
    return d


PROJS = [
    _proj(1, "Implantação eixo sul", "implantacao"),
    _proj(2, "Milk run MWM", "em_execucao", deadline="2026-08-01",
          dias_para_deadline=-30, atrasado=True, percentual=70),
    _proj(3, "Dedicado FORVIA", "implantacao", parado=True, parado_dias=45,
          ultimo_andamento="2026-07-16T10:00:00", percentual=10),
    _proj(4, "Transferência WEG", "entregue", entrega="2026-08-20",
          deadline="2026-08-31", dias_para_deadline=None, atrasado=False,
          dias_de_atraso=-11, no_prazo=True, duracao_dias=76, percentual=100),
]

PROJ_FICHA = {**PROJS[0], "oportunidade_titulo": "Contrato 2027",
              "lanes_detalhe": [LANE_RUIM],
              "resumo_lanes": {"lanes": 1, "receita_mes": 428750.0,
                               "km_mes": 35700.0, "margem_mes": 64020.0,
                               "margem_pct": 0.149, "rkm_medio": 12.0,
                               "lanes_sem_preco": 0, "lanes_abaixo_piso": 0,
                               "lanes_sem_piso": 0},
              "referencia_ckm": {"disponivel": True, "ckm_marginal": 13.28,
                                 "ckm_cheio": 24.93, "ckm_bruto": 10.22,
                                 "fonte": "Make vs Buy"},
              "historico": [
                  {"id": 3, "ts": "2026-08-29T10:00:00", "usuario": "ana",
                   "texto": "Doca confirmada pelo cliente.",
                   "status_de": None, "status_para": None, "percentual": 40,
                   "versao": None},
                  {"id": 1, "ts": "2026-05-01T09:00:00", "usuario": "ana",
                   "texto": "Projeto criado.", "status_de": None,
                   "status_para": "nao_iniciado", "percentual": 0,
                   "versao": 1}],
              "realizado": {"disponivel": True, "motivo": "",
                            "prometido": 428750.0, "atribuivel": True,
                            "projetos_na_conta": 1, "meses": [],
                            "media_antes": 1832952.31,
                            "media_depois": 2105887.37,
                            "variacao": 272935.06, "atingimento": 0.6365,
                            "desde": "2026-06", "meses_antes": 22,
                            "meses_depois": 2}}


# A base do Avacorp — a tela ANTIGA, que continua na sub-aba dela.
BASE_AVA = {
    "kpis": {"leads": 2, "potencial_total": 3600000.0, "leads_quentes": 1,
             "projetos_execucao": 1, "rob_pipeline": 0.0},
    "leads": [{"cliente": "ALFA LOGÍSTICA", "segmento": "Automotivo",
               "temperatura": "Quente", "status": "Qualificado",
               "potencial": 2400000.0, "rob_previsto": 0.0,
               "previsao": "2026-10-01"},
              {"cliente": "BETA QUÍMICA", "segmento": "Química",
               "temperatura": "Frio", "status": "Em prospecção",
               "potencial": 1200000.0, "rob_previsto": 0.0,
               "previsao": None}],
    "projetos": [{"numeroid": 4, "versao": 1, "projeto": "P4",
                  "cliente": "ALFA LOGÍSTICA", "segmento": "Automotivo",
                  "tipo": "Projeto", "status": "Em execução", "rob": 0.0,
                  "lucro_pct": None, "aging": 40, "deadline": None}],
    "repactuacoes": [{"cliente": "ALFA LOGÍSTICA", "mes": "2026-05-01",
                      "total_pct": 7.5, "pct_negocios": None,
                      "status": "Aplicada", "obs": None}],
    "atualizado_em": _HOJE + "T20:00:00", "fonte": "ERP AVA",
}


def _rota(posts=None):
    def rota(route):
        u, req = route.request.url, route.request
        if req.method == "POST" and posts is not None:
            try:
                posts.append((u, json.loads(req.post_data or "{}")))
            except ValueError:                       # pragma: no cover
                posts.append((u, {}))
        # A ORDEM IMPORTA: `/api/comercial/crm` é prefixo de todas as rotas
        # novas, e testá-lo primeiro devolveria a base do Avacorp para o painel.
        if "/api/auth/me" in u:
            corpo = USER
        elif "/crm/painel" in u:
            corpo = PAINEL
        elif "/crm/catalogo" in u:
            corpo = CATALOGO
        elif "/crm/contas/" in u:
            corpo = {**CONTAS[0], "contatos": [], "oportunidades": [],
                     "atividades": [], "interacoes": [], "contratos": [],
                     "serie_mensal": [], "rotas_erp": []}
        elif "/crm/contas" in u:
            corpo = {"contas": CONTAS, "total": len(CONTAS)}
        elif "/crm/projetos/" in u:
            corpo = PROJ_FICHA
        elif "/crm/projetos" in u:
            corpo = {"projetos": PROJS, "total": len(PROJS)}
        elif "/crm/oportunidades/" in u and u.endswith("/projeto"):
            corpo = {**PROJ_FICHA, "lanes_copiadas": 1}
        elif "/crm/oportunidades/" in u:
            corpo = OPO_FICHA
        elif "/crm/oportunidades" in u:
            corpo = {"oportunidades": OPOS, "total": len(OPOS)}
        elif "/crm/atividades" in u:
            corpo = {"atividades": ATIVS, "mostrando": len(ATIVS),
                     "total": len(ATIVS)}
        elif "/crm/contratos" in u:
            corpo = {"contratos": CTRS, "total": len(CTRS)}
        elif "/crm/interacoes" in u:
            corpo = {"interacoes": []}
        elif u.rstrip("/").endswith("/api/comercial/crm"):
            corpo = BASE_AVA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    return rota


def _abrir(pg, base_url, posts=None):
    pg.route("**/api/**", _rota(posts))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#crm")
    pg.wait_for_selector("#view-crm.on", timeout=15000)
    pg.wait_for_selector("#kpis-crm .kpi", timeout=15000)
    return erros


# ------------------------------------------------------------------- boot

def test_tela_abre_sem_estourar(pagina):
    """`pageerror` vazio. Um erro na avaliação do script derruba o app inteiro,
    não só esta tela — e o sintoma é a tela de login que não some."""
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert erros == [], erros


def test_abre_no_painel_e_a_base_avacorp_fica_em_aba_separada(pagina):
    """O pedido que originou a tela: CRM novo na frente, base do ERP preservada
    a um clique — não misturada, não apagada."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.is_visible("#aba-crm-pnl")
    assert not pg.is_visible("#aba-crm-ava")
    assert pg.get_attribute("#tabcrm-pnl", "aria-selected") == "true"

    pg.click("#tabcrm-ava")
    pg.wait_for_selector("#aba-crm-ava:not([hidden])", timeout=5000)
    # a tela ANTIGA continua desenhando: leads, projetos e repactuações
    assert "ALFA LOGÍSTICA" in pg.inner_text("#crm-leads")
    assert "ALFA LOGÍSTICA" in pg.inner_text("#crm-projetos")
    assert "7,5" in pg.inner_text("#crm-repac")
    assert pg.query_selector_all("#kpis-crmava .kpi")


def test_kpi_do_pipeline_diz_quantas_ficaram_de_fora(pagina):
    """Total que ignora oportunidade sem valor não é o valor do pipeline —
    a mesma armadilha do "ROB R$ 0 em verde" do CRM antigo."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    txt = pg.inner_text("#kpis-crm")
    assert "1 sem valor" in txt


# ---------------------------------------------------------------- pipeline

def test_cartao_cai_na_coluna_do_estagio(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcol", timeout=5000)
    cols = pg.query_selector_all("#crm-kanban .kcol")
    assert len(cols) == 4, "o funil tem quatro estágios abertos"
    prop = pg.query_selector('#crm-kanban .kcol[data-est="proposta"]')
    assert "Contrato 2027" in prop.inner_text()
    qual = pg.query_selector('#crm-kanban .kcol[data-est="qualificacao"]')
    assert "Sondagem NOVA" in qual.inner_text()
    assert "Contrato 2027" not in qual.inner_text()


def test_oportunidade_sem_lane_diz_que_o_valor_e_estimado(pagina):
    """Um número que muda de fonte sem avisar é um número em que ninguém
    confia: o cartão marca o que veio do valor estimado do cadastro."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcol", timeout=5000)
    neg = pg.query_selector('#crm-kanban .kcol[data-est="negociacao"]')
    assert "estimado" in neg.inner_text().lower()


# ------------------------------------------------------------------ contas

def test_prospect_nao_mostra_receita_zero(pagina):
    """Zero que é ausência de VÍNCULO não é desempenho: é `n/d`.

    Com R$ 0 o prospect cairia no fim de um ranking de receita como se
    faturasse zero — e "cliente que não fatura" é leitura de negócio, não de
    cadastro.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-ctas")
    pg.wait_for_selector("#crm-contas table tbody tr", timeout=5000)
    linhas = pg.query_selector_all("#crm-contas table tbody tr")
    alvo = [l for l in linhas if "NOVA INDÚSTRIA" in l.inner_text()]
    assert alvo, "a conta prospect tem de aparecer na lista"
    txt = alvo[0].inner_text()
    assert "n/d" in txt
    assert "R$ 0" not in txt


def test_conta_sem_contato_nunca_e_diferente_de_hoje(pagina):
    """None (nunca falaram) e 0 (falaram hoje) são estados muito diferentes."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-ctas")
    pg.wait_for_selector("#crm-contas table tbody tr", timeout=5000)
    linhas = pg.query_selector_all("#crm-contas table tbody tr")
    prospect = [l for l in linhas if "NOVA INDÚSTRIA" in l.inner_text()][0]
    assert "nunca" in prospect.inner_text().lower()


# ------------------------------------------------------------- piso da ANTT

def test_lane_abaixo_do_piso_grita_no_alerta_do_painel(pagina):
    """O número que torna a cotação diferente de um CRM genérico."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    txt = pg.inner_text("#crm-alertas")
    assert "piso ANTT" in txt


def test_valor_do_piso_sai_em_pt_br(pagina):
    """Já saiu como `R$ 4.550.48` — dois pontos, nenhuma vírgula, e o número
    some da leitura. A troca ingênua de separador é a causa."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcard", timeout=5000)
    pg.click('#crm-kanban .kcol[data-est="proposta"] .kcard')
    pg.wait_for_selector("#modalBg.aberto .lane", timeout=5000)
    lane = pg.inner_text("#modalBg .lane")
    assert "abaixo do piso ANTT em R$ 4.550,48" in lane
    assert "4.550.48" not in lane


def test_ficha_da_lane_mostra_os_dois_rkm(pagina):
    """A diferença entre R$/km carregado e total É o custo do retorno vazio.

    Sem os dois lado a lado, a lane de 1.180 km de ida com 1.180 de volta vazia
    parece tão boa quanto a que tem carga nos dois sentidos.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcard", timeout=5000)
    pg.click('#crm-kanban .kcol[data-est="proposta"] .kcard')
    pg.wait_for_selector("#modalBg.aberto .lane", timeout=5000)
    txt = pg.inner_text("#modalBg .lane")
    assert "R$/KM CARREGADO" in txt.upper()
    assert "R$/KM TOTAL" in txt.upper()
    assert "50%" in txt          # retorno vazio


def test_ckm_e_dito_como_consolidado_e_nao_vira_coluna(pagina):
    """Coluna repetindo o mesmo CKM em N linhas passa a impressão de cálculo
    por rota — foi o que a Make vs Buy fez e teve de desfazer."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcard", timeout=5000)
    pg.click('#crm-kanban .kcol[data-est="proposta"] .kcard')
    pg.wait_for_selector("#modalBg.aberto .lane", timeout=5000)
    ficha = pg.inner_text("#modalBg .crm-ficha")
    assert "não por rota" in ficha
    # e o rodapé diz POR QUE o par de CKM é esse — foi errar isso que fez toda
    # lane com retorno vazio sair deficitária
    assert "duas vezes" in ficha
    # e a margem, que VARIA por lane, continua na grade da lane
    assert "RESULTADO/VIAGEM" in pg.inner_text("#modalBg .lane").upper()


# -------------------------------------------------------------- atividades

def test_atividade_atrasada_mostra_o_tempo_decorrido(pagina):
    """"20/08" e "20/06" parecem a mesma coisa numa lista lida de manhã."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-ativ")
    pg.wait_for_selector("#crm-atividades table tbody tr", timeout=5000)
    txt = pg.inner_text("#crm-atividades")
    assert "10 dias" in txt


# --------------------------------------------------------------- contratos

def test_contrato_diz_que_o_reajuste_do_ciclo_esta_pendente(pagina):
    """Reajuste esquecido é dinheiro na mesa que só aparece quando alguém
    pergunta — a tela pergunta sozinha."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-ctr")
    pg.wait_for_selector("#crm-contratos table tbody tr", timeout=5000)
    txt = pg.inner_text("#crm-contratos")
    assert "pendente" in txt.lower()
    assert "A vencer" in txt


# ------------------------------------------------------------------ escrita

def test_mover_cartao_manda_o_estagio_e_perda_pede_motivo(pagina):
    """Perda sem motivo não vira aprendizado nenhum — a tela pede na única
    hora em que alguém lembra."""
    pg, base_url = pagina
    posts = []
    _abrir(pg, base_url, posts)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcard", timeout=5000)
    pg.click('#crm-kanban .kcol[data-est="proposta"] .kcard')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    pg.select_option("#of-est", "perdida")
    pg.click("#modalBg .m-foot button:has-text('Mover')")
    # NÃO enviou nada ainda: abriu o formulário de motivo
    pg.wait_for_selector("#cp-motivo", timeout=5000)
    assert not [p for p in posts if "mover" in p[0]]
    pg.select_option("#cp-motivo", "preco")
    pg.click("#modalBg .m-foot button:has-text('Marcar perdida')")
    pg.wait_for_timeout(400)
    envios = [p for p in posts if "mover" in p[0]]
    assert envios, "o motivo escolhido tem de disparar o envio"
    assert envios[0][1]["estagio"] == "perdida"
    assert envios[0][1]["motivo_perda"] == "preco"


# --------------------------------------------------------------- desempenho

def test_aba_desempenho_desenha_os_quatro_blocos(pagina):
    """Eram quatro agregados que o backend calculava e a tela não mostrava.

    Payload sem consumidor apodrece: ninguém percebe quando ele quebra, e
    alguém acaba "otimizando" a consulta que o produz.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-desemp")
    pg.wait_for_selector("#aba-crm-desemp:not([hidden])", timeout=5000)
    pg.wait_for_selector("#crm-concentracao table tbody tr", timeout=5000)

    conc = pg.inner_text("#crm-concentracao")
    assert "TUPY" in conc and "75,5%" in conc
    corr = pg.inner_text("#crm-corredores")
    assert "SC → MG" in corr
    # os dois gráficos mediram largura de verdade mesmo nascendo escondidos
    for cid in ("chartCrmFech", "chartCrmMot"):
        caixa = pg.query_selector(f"#{cid}").bounding_box()
        assert caixa["width"] > 300, f"{cid} mediu {caixa['width']}px — o "
        "ResizeObserver do echartsRegistrar não pegou a aba ao aparecer"


def test_motivo_de_perda_mostra_o_percentual(pagina):
    """"Perdemos por preço" só decide alguma coisa com o quanto ao lado."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-desemp")
    pg.wait_for_selector("#aba-crm-desemp:not([hidden])", timeout=5000)
    assert "8 perdidas com motivo catalogado" in pg.inner_text("#crm-mot-hint")


# ------------------------------------------------------------ régua de altura

def test_cada_aba_cabe_numa_tela_com_dado_de_verdade(pagina):
    """A régua da casa: painel de BI cabe em UMA tela, e o que não couber vai
    para sub-aba — nunca empilhado abaixo.

    Duas diferenças em relação ao `test_uma_tela.py`, que mede as 68 telas:

    1. **Aqui o payload é REALISTA**, não `{}`. Lá a altura é o PISO (piso acima
       da régua é defeito certo; piso abaixo não prova que cabe com dado), e a
       régua precisa ser comparável entre telas. O CRM é justamente a tela onde
       o volume é o problema — foi ela que produziu a página de 16.000px —,
       então vale medi-la cheia.
    2. **A aba `ava` está fora da régua, de propósito.** Ela não é um painel
       que alguém desenhou: é a tela ANTIGA inteira, preservada como arquivo
       somente leitura a pedido de quem usa. Encolhê-la para caber em 900px
       significaria cortar conteúdo que existe justamente para ser mantido —
       trocar a instrução que criou a aba por um número. O que protege contra
       o crescimento sem fim ali é o `.tabroll` em toda tabela, que o teste
       seguinte cobra, e o teto local de 280px do CSS.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.set_viewport_size({"width": 1440, "height": 900})
    alturas = {}
    for chave in ("pnl", "pipe", "ctas", "ativ", "ctr", "desemp", "ava"):
        pg.click(f"#tabcrm-{chave}")
        pg.wait_for_selector(f"#aba-crm-{chave}:not([hidden])", timeout=5000)
        pg.wait_for_timeout(120)
        alturas[chave] = pg.query_selector(f"#aba-crm-{chave}").bounding_box()["height"]
    proprias = {k: round(v) for k, v in alturas.items()
                if k != "ava" and v > 900}
    assert not proprias, f"abas acima da régua de 900px: {proprias}"
    # e o arquivo, ainda que isento, não pode virar página quilométrica
    assert alturas["ava"] < 1400, round(alturas["ava"])


def test_toda_tabela_do_crm_rola_dentro_do_card(pagina):
    """Lista longa rola DENTRO do card (`.tabroll`), nunca na página — é o que
    impediu a página de 16.000px de voltar."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    soltas = pg.eval_on_selector_all(
        "#view-crm table",
        "ts => ts.filter(t => !t.closest('.tabroll') && !t.closest('.modal'))"
        "     .map(t => t.parentElement.className || t.parentElement.id)")
    assert soltas == [], f"tabelas sem .tabroll: {soltas}"


# ------------------------------------------------------------------ projetos

def test_aba_projetos_separa_o_combinado_do_acontecido(pagina):
    """Projeto entregue mostra SE cumpriu; projeto aberto mostra quanto falta.

    Guardar só a entrega faz projeto atrasado três meses parecer entregue em
    dia — a coluna de prazo é o lugar onde essa diferença aparece.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-proj")
    pg.wait_for_selector("#crm-projetos2 table tbody tr", timeout=5000)
    # o chip padrão é "Abertos"; o projeto ENTREGUE só aparece em "Todos"
    pg.click('#crm-proj-chips2 .chip[data-f=""]')
    pg.wait_for_timeout(200)

    def linha(nome):
        for tr in pg.query_selector_all("#crm-projetos2 table tbody tr"):
            t = tr.inner_text()
            if nome in t:
                return t
        raise AssertionError(f"linha de {nome!r} não encontrada")

    assert "30d estourado" in linha("Milk run MWM")
    assert "no prazo" in linha("Transferência WEG")
    assert "em 30d" in linha("Implantação eixo sul")


def test_projeto_parado_e_marcado_mesmo_com_status_andando(pagina):
    """"Em implantação" há 45 dias sem ninguém escrever nada não está em
    implantação — quem desmente o status é o último andamento."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-proj")
    pg.wait_for_selector("#crm-projetos2 table tbody tr", timeout=5000)
    linhas = pg.query_selector_all("#crm-projetos2 table tbody tr")
    alvo = [l for l in linhas if "Dedicado FORVIA" in l.inner_text()][0]
    assert "parado 45d" in alvo.inner_text()


def test_ficha_do_projeto_mostra_VARIACAO_e_nao_receita_do_cliente(pagina):
    """A conta que dividia a receita do cliente pelo prometido dava 480% com
    dado real. O que se mostra é a variação, e o rótulo diz isso."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-proj")
    pg.wait_for_selector("#crm-projetos2 table tbody tr", timeout=5000)
    pg.click("#crm-projetos2 table tbody tr")
    pg.wait_for_selector("#modalBg.aberto .crm-ficha", timeout=5000)
    txt = pg.inner_text("#modalBg .crm-ficha")
    assert "Variação no cliente" in txt
    assert "64% do prometido" in txt
    # e as duas metades das datas aparecem lado a lado
    assert "Início previsto" in txt and "Início real" in txt


def test_oportunidade_ganha_oferece_abrir_projeto(pagina):
    """O caminho normal de criação — e ele só existe na venda GANHA."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabcrm-pipe")
    pg.wait_for_selector("#crm-kanban .kcard", timeout=5000)
    pg.click('#crm-kanban .kcol[data-est="proposta"] .kcard')
    pg.wait_for_selector("#modalBg.aberto", timeout=5000)
    # a oportunidade do dublê está em PROPOSTA: o botão não pode aparecer
    assert "Abrir projeto" not in pg.inner_text("#modalBg .m-foot")
