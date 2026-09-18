# -*- coding: utf-8 -*-
"""O catálogo do modelo: desvios, méritos e os contadores de risco do GR.

POR QUE ISTO É CÓDIGO E NÃO BANCO. A regra da casa (`config.py`) é: catálogo é
código, peso é dado. Um desvio só existe se alguém escreveu de onde ele vem —
o D12 é multa média porque há um código do ERP que significa isso. Já quanto
ele TIRA da nota muda com a mesa, e por isso os pontos vivem em `prm_param`,
versionados por competência; o que está aqui é o padrão com que a régua nasceu.

Os códigos, os nomes e as gravidades são os do modelo que quem opera desenhou
(18/09/2026). A JANELA é quantos ciclos o desvio pesa na reputação — não no
ranking do ciclo, onde todo desvio do ciclo conta igual.
"""
from __future__ import annotations

#: Desvio: (código, nome, gravidade, pontos padrão, janela em ciclos).
DESVIOS: tuple[dict, ...] = (
    {"cod": "D01", "nome": "Trânsito e acidentes", "grav": "GRAVE", "pts": 12, "janela": 6},
    {"cod": "D02", "nome": "Deixar de amarrar ou peiar carga", "grav": "GRAVE", "pts": 15, "janela": 6},
    {"cod": "D03", "nome": "Descumprir normas do cliente", "grav": "GRAVE", "pts": 12, "janela": 6},
    {"cod": "D04", "nome": "Descumprir normas internas", "grav": "MODERADA", "pts": 8, "janela": 6},
    {"cod": "D05", "nome": "Recusa de carga", "grav": "MODERADA", "pts": 10, "janela": 3},
    {"cod": "D06", "nome": "Não atender programação (no-show)", "grav": "GRAVE", "pts": 15, "janela": 3},
    {"cod": "D07", "nome": "Atraso na janela de coleta ou entrega", "grav": "MODERADA", "pts": 7, "janela": 3},
    {"cod": "D08", "nome": "Quebra de PGR", "grav": "GRAVISSIMA", "pts": 20, "janela": 12},
    {"cod": "D09", "nome": "Deixar de enviar macro", "grav": "MODERADA", "pts": 6, "janela": 3},
    {"cod": "D10", "nome": "Canhoto entregue com mais de 7 dias", "grav": "MODERADA", "pts": 8, "janela": 3},
    {"cod": "D11", "nome": "Documentação fiscal (CT-e, MDF-e, NF)", "grav": "GRAVE", "pts": 12, "janela": 6},
    {"cod": "D12", "nome": "Multa de trânsito (infração média)", "grav": "MODERADA", "pts": 8, "janela": 12},
    {"cod": "D13", "nome": "Multa de trânsito (infração grave ou gravíssima)", "grav": "GRAVE", "pts": 14, "janela": 12},
    {"cod": "D14", "nome": "Falta sem justificativa", "grav": "GRAVE", "pts": 10, "janela": 6},
)

#: Mérito: soma na REPUTAÇÃO (a categoria), nunca no ranking do ciclo — é assim
#: no modelo, e a razão é boa: o ranking do mês mede o mês; o mérito é história.
MERITOS: tuple[dict, ...] = (
    {"cod": "M01", "nome": "Ciclo sem nenhum desvio", "pts": 25},
    {"cod": "M02", "nome": "Pontualidade total nas janelas", "pts": 20},
    {"cod": "M03", "nome": "Canhotos todos no prazo", "pts": 15},
    {"cod": "M04", "nome": "Macros todas enviadas", "pts": 15},
    {"cod": "M05", "nome": "Zero recusa e zero no-show", "pts": 15},
    {"cod": "M06", "nome": "Aderência total ao PGR", "pts": 20},
    {"cod": "M07", "nome": "Elogio formal de cliente", "pts": 30},
    {"cod": "M08", "nome": "Atendimento a demanda crítica", "pts": 15},
    {"cod": "M09", "nome": "Curso ou reciclagem voluntária", "pts": 15},
    {"cod": "M10", "nome": "Melhoria operacional", "pts": 15},
)

#: OS CONTADORES DE RISCO que o RasterIntegra devolve por viagem, com o peso
#: PADRAO de cada um (o peso real e dado, em `prm_gr_peso`).
#:
#: OS PESOS SAO CALIBRADOS NO DADO REAL, e nao copiados do modelo. O modelo
#: original pesava ~70 TIPOS de excecao que vinham de planilha; aqui sao
#: CONTADORES DE EVENTO, e a frequencia deles e outra. Medido no ciclo
#: 16/08-15/09/2026 (2.500 viagens, 191 motoristas), por viagem:
#:
#:     excesso de velocidade  9,20     desvio de rota        1,62
#:     parada em area de risco 2,01    violacao de painel    0,06
#:     desengate               5,49    violacao de antena    0,09
#:
#: Com os pesos do modelo (velocidade 6, desengate 10) a mediana do risco por
#: viagem dava 57,5 contra uma referencia de 10: TODO MUNDO no piso, e a nota
#: deixava de separar quem quer que fosse. Nota que nao varia nao premia nada.
#:
#: Por isso: velocidade vale 1 POR EVENTO (sao muitos e o grave e o padrao, nao
#: o evento isolado), area de risco e desvio de rota valem 3, e as violacoes de
#: equipamento — raras e serias — valem 10.
CONTADORES_GR: tuple[dict, ...] = (
    {"campo": "eventos_velocidade", "nome": "Excesso de velocidade", "peso": 1},
    {"campo": "paradas_area_risco", "nome": "Parada em area de risco", "peso": 3},
    {"campo": "desvios_rota", "nome": "Desvio de rota", "peso": 3},
    {"campo": "violacao_painel", "nome": "Violacao de painel", "peso": 10},
    {"campo": "violacao_antena", "nome": "Violacao de antena", "peso": 10},
)

#: O QUE APARECE E NAO PESA — e o motivo de cada um. Eles ficam na linha do
#: motorista porque quem opera quer ver; nao entram na nota porque nao medem
#: conduta:
#:
#: - **desengate**: 5,49 POR VIAGEM. E a operacao de engatar e desengatar
#:   carreta, nao violacao. Decisao de quem opera (18/09/2026) depois da
#:   medicao — com peso 10 ele sozinho respondia por metade do risco de todo
#:   mundo, e a nota de GR virava "quantas vezes desengatou";
#: - **botao de panico**: e o motorista pedindo socorro. Penalizar ensina a
#:   nao apertar o botao;
#: - **rodou fora do horario** e **sem posicao**: o fornecedor NAO PREENCHE —
#:   zero e vazio em todo o periodo medido. Peso num contador que nunca chega
#:   daria a impressao de que ele pesa.
SO_INFORMATIVOS: tuple[dict, ...] = (
    {"campo": "desengate", "nome": "Desengate", "peso": 0,
     "nota": "operacao de carreta — 5,5 por viagem; nao e violacao"},
    {"campo": "botao_panico", "nome": "Botao de panico", "peso": 0,
     "nota": "acionamento de socorro — aparece na linha, nao penaliza"},
    {"campo": "rodou_fora_horario", "nome": "Rodou fora do horario", "peso": 0,
     "nota": "o fornecedor nao preenche (zero em todo o periodo medido)"},
)

PANICO = SO_INFORMATIVOS[1]

POR_COD = {d["cod"]: d for d in DESVIOS}
MERITO_POR_COD = {m["cod"]: m for m in MERITOS}
GR_POR_CAMPO = {c["campo"]: c for c in CONTADORES_GR}


def desvio(cod: str) -> dict | None:
    return POR_COD.get(str(cod or "").upper())


def merito(cod: str) -> dict | None:
    return MERITO_POR_COD.get(str(cod or "").upper())


def e_merito(alvo: str) -> bool:
    return str(alvo or "").upper().startswith("M")


def pesos_gr_padrao() -> dict[str, float]:
    return {c["campo"]: float(c["peso"]) for c in CONTADORES_GR}


def informativos() -> tuple[dict, ...]:
    """O que a tela mostra ao lado da nota, sem entrar nela."""
    return SO_INFORMATIVOS
