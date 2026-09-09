"""O que está acontecendo AGORA na jornada — a fonte do painel de TV.

O QUE É "AGORA" AQUI, E O QUE NÃO É
===================================
A RasterJOR entrega a jornada APURADA só até ONTEM: pedir uma janela que
alcance hoje devolve HTTP 400, "são permitidas apenas consultas retroativas
(D-1)". Nenhuma cadência de coleta muda isso — não é escolha nossa, é regra do
fornecedor. Então **horas trabalhadas, hora extra e repouso faltante não
existem em tempo real, e este módulo não os inventa.**

O que existe agora é `/external-api/vehicles/`: por veículo, o motorista
associado, o EVENTO ATUAL (EM DIREÇÃO, PARADO EM JORNADA, EM REPOUSO), há
quanto tempo ele está nesse evento, e a última posição. Medido em 08/09/2026: a
mediana da idade da posição é de **4 minutos**. Isso é tempo real de verdade, e
é sobre isso que o painel fala.

O PAINEL NÃO SERVE LEITURA VELHA, E ISSO É REQUISITO
====================================================
Ele publica MINUTOS. A regra da casa para tela dessa resolução é a mesma da
torre, da portaria e da programação: `cached(velha_ate=)` está PROIBIDO aqui —
a tarja avisa, mas a decisão tomada sobre uma posição de vinte minutos atrás já
foi tomada. Tela vazia é a resposta honesta. Guard em
`tests/test_leitura_velha.py`, na lista `TEMPO_REAL`.

O DENOMINADOR É QUEM ESTÁ REPORTANDO, NÃO A FROTA
=================================================
São 175 veículos no cadastro da RasterJOR e, medido às 23h de uma terça, **21
com motorista associado e 20 com evento atual**. A idade da posição é bimodal:
p50 de 4 minutos e p90 de 169 DIAS — ou seja, há um grupo reportando e outro
que parou há meses (implemento, veículo vendido, equipamento removido).

Misturar os dois daria "12% da frota em direção", que é um número falso sobre
uma frota que não está toda em operação. O painel separa: quem reporta é o
denominador, e quem não reporta é um número à parte, dito com a idade.

A RÉGUA DA LEI 13.103 EM TEMPO REAL
===================================
É a única coisa aqui que vira ALERTA, e ela cabe: direção contínua tem teto de
**5h30** antes da parada de 30 minutos, e `actual_event_duration` diz há quanto
tempo o motorista está EM DIREÇÃO. Um motorista chegando nesse limite é uma
infração se formando AGORA, que é exatamente o que uma tela de monitoramento
deve mostrar — e a única coisa que dá para fazer a respeito é antes de ela
acontecer.

O amarelo abre uma hora antes (4h30) porque é o tempo que alguém precisa para
falar com o motorista. Fora do evento EM DIREÇÃO a régua não se aplica e a
linha sai sem cor: repouso longo não é violação, é folga.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from .. import pglocal
from . import normalizar_nome

log = logging.getLogger(__name__)

ESQUEMA: str | None = None       # os testes redirecionam

# Lei 13.103/2015: direção contínua máxima antes da parada obrigatória.
DIRECAO_CONTINUA_MAX_MIN = 5 * 60 + 30          # 5h30
# O amarelo abre uma hora antes: é o tempo de alguém falar com o motorista.
# Alerta que acende junto com a infração não serve para evitá-la.
DIRECAO_CONTINUA_AVISO_MIN = 4 * 60 + 30        # 4h30

# Acima disto a posição não é "agora". 30 minutos é generoso de propósito: o
# rastreador transmite a cada poucos minutos, e um veículo em área sem sinal
# não deve sumir do painel na primeira falha de transmissão.
FRESCO_MAX_MIN = 30

# A hora vem embutida no texto livre da posição, que o fornecedor monta assim:
#   "08/09/2026 23:08:00 - 0.02 km de TRANSPORTADORA SULISTA - SAO BERNARDO/SP"
# Não há campo de data separado. O texto é guardado CRU (o formato é dele e
# pode mudar); daqui sai só a hora, e quando ela não casa o veículo entra como
# "sem hora de posição" em vez de sumir.
_RE_POSICAO = re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})")

# `actual_event_duration` vem como "HH:MM" e passa de 24 horas sem virar dia:
# medido, um motorista EM REPOUSO aparecia como "101:32". Tratar isso como
# hora de relógio devolveria lixo.
_RE_DURACAO = re.compile(r"^(\d+):(\d{2})$")

VEICULOS_SQL = """
SELECT placa, motorista, ultima_posicao, latitude, longitude,
       evento_atual, evento_duracao, coletado_em
  FROM jor_veiculos
"""

# A filial não vem no recurso de veículos — vem do cadastro de motoristas, e a
# ligação é o NOME, porque `/vehicles/` devolve `current_associated_driver`
# como texto e nenhum documento. É o mesmo elo fraco das exceções, e por isso
# quem não casar aparece com a filial em branco em vez de sumir.
MOTORISTAS_SQL = """
SELECT documento, nome, filial, escala FROM jor_motoristas WHERE ativo = 1
"""

EXCECOES_SQL = """
SELECT gerada_em, nome, tipo, veiculo, status, nivel
  FROM jor_excecoes
 WHERE gerada_em >= %(desde)s
 ORDER BY gerada_em DESC
 LIMIT 60
"""


def _minutos(txt: str) -> int | None:
    """"HH:MM" em minutos. Aceita mais de 24 horas, que é o caso real."""
    m = _RE_DURACAO.match((txt or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _quando(posicao: str) -> datetime | None:
    m = _RE_POSICAO.match((posicao or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None


def _lugar(posicao: str) -> str:
    """O texto da posição sem a hora — o que sobra é o lugar."""
    t = (posicao or "").strip()
    m = _RE_POSICAO.match(t)
    if not m:
        return t
    resto = t[m.end():].lstrip()
    return resto[1:].lstrip() if resto.startswith("-") else resto


def _semaforo(evento: str, minutos: int | None) -> str:
    """A cor da linha. SÓ a direção contínua tem régua; o resto não tem cor.

    Pintar repouso de vermelho por ser longo seria transformar folga em alarme,
    e num painel que fica ligado o dia inteiro toda cor que não significa nada
    ensina a ignorar as que significam.
    """
    if "DIRE" not in (evento or "").upper() or minutos is None:
        return ""
    if minutos >= DIRECAO_CONTINUA_MAX_MIN:
        return "ruim"
    if minutos >= DIRECAO_CONTINUA_AVISO_MIN:
        return "atencao"
    return "bom"


def agora(esquema: str | None = None) -> dict:
    """O estado da frota neste momento, a partir do último snapshot coletado."""
    esq = esquema or ESQUEMA
    veiculos = [dict(r) for r in pglocal.query(VEICULOS_SQL, {}, esquema=esq)]
    motoristas = [dict(r) for r in pglocal.query(MOTORISTAS_SQL, {}, esquema=esq)]
    por_nome = {normalizar_nome(m["nome"]): m for m in motoristas}

    agora_ = datetime.now()
    linhas, mudos = [], []
    for v in veiculos:
        nome = (v["motorista"] or "").strip()
        quando = _quando(v["ultima_posicao"])
        idade = int((agora_ - quando).total_seconds() // 60) if quando else None
        minutos = _minutos(v["evento_duracao"])
        cad = por_nome.get(normalizar_nome(nome)) if nome else None
        linha = {
            "placa": v["placa"],
            "motorista": nome or None,
            "filial": (cad or {}).get("filial") or None,
            "evento": (v["evento_atual"] or "").strip() or None,
            "minutos": minutos,
            "idade_min": idade,
            "lugar": _lugar(v["ultima_posicao"]) or None,
            "lat": float(v["latitude"]) if v["latitude"] is not None else None,
            "lon": float(v["longitude"]) if v["longitude"] is not None else None,
            "semaforo": _semaforo(v["evento_atual"], minutos),
        }
        # QUEM ESTÁ REPORTANDO É O DENOMINADOR. Sem evento atual e sem posição
        # fresca, o veículo não está em operação monitorada — entra na conta
        # dos mudos, com a idade, em vez de diluir a dos que estão.
        if linha["evento"] and idade is not None and idade <= FRESCO_MAX_MIN:
            linhas.append(linha)
        elif nome or linha["evento"]:
            mudos.append(linha)

    ordem = {"ruim": 0, "atencao": 1, "bom": 2, "": 3}
    linhas.sort(key=lambda x: (ordem[x["semaforo"]], -(x["minutos"] or 0)))
    mudos.sort(key=lambda x: -(x["idade_min"] or 0))

    dirigindo = [x for x in linhas if x["semaforo"]]
    return {
        "linhas": linhas,
        "mudos": mudos[:12],
        "mudos_total": len(mudos),
        "kpis": {
            "reportando": len(linhas),
            "frota": len(veiculos),
            "em_direcao": sum(1 for x in linhas if "DIRE" in (x["evento"] or "").upper()),
            "parado": sum(1 for x in linhas if "PARADO" in (x["evento"] or "").upper()),
            "repouso": sum(1 for x in linhas if "REPOUSO" in (x["evento"] or "").upper()),
            "no_limite": sum(1 for x in dirigindo if x["semaforo"] == "ruim"),
            "perto_do_limite": sum(1 for x in dirigindo if x["semaforo"] == "atencao"),
            "mudos": len(mudos),
            # A IDADE DO PRÓPRIO PAINEL. Num painel de TV ninguém clica para
            # descobrir se o dado é de agora; ele precisa dizer sozinho.
            "idade_maxima_min": max((x["idade_min"] or 0 for x in linhas),
                                    default=None),
            "coletado_em": max((v["coletado_em"] for v in veiculos), default=""),
        },
        "limite_min": DIRECAO_CONTINUA_MAX_MIN,
        "aviso_min": DIRECAO_CONTINUA_AVISO_MIN,
        "fresco_max_min": FRESCO_MAX_MIN,
    }


def excecoes_recentes(desde: datetime, esquema: str | None = None) -> list[dict]:
    """As exceções abertas mais recentes — o rodapé do painel.

    Vêm com o nome do tipo EM INGLÊS, como o fornecedor manda ("Daily Over
    Driving", "Uninterrupted Driving"), e o `status` como NÚMERO: não há tabela
    de domínio no contrato, e código sem domínio não vira rótulo inventado.
    """
    return [dict(r) for r in pglocal.query(
        EXCECOES_SQL, {"desde": desde}, esquema=esquema or ESQUEMA)]
