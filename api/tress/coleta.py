# -*- coding: utf-8 -*-
"""A coleta da 3S: cadastro de veículos e última posição de cada um.

DUAS CHAMADAS, e nenhuma paginação: `ListaVeiculos` e
`ListaUltimaPosicaoVeiculos` devolvem a conta inteira de uma vez (227 veículos,
250 KB, medido em 03/09/2026). Não há cursor nem limite documentado — se um dia
houver, a ausência aparece como frota que encolhe, e o `sumiu_em` acusa.

O QUE ESTA COLETA NÃO FAZ: histórico. A 3S tem `HistoricoPosicao` próprio, sob
demanda; espelhar milhões de pontos para responder "comunicou hoje?" seria
pagar caro por uma pergunta de uma linha.

COLETA VAZIA NUNCA VIRA ESPELHO COMPLETO. Se `ListaVeiculos` voltar sem
ninguém, isso não é "a frota acabou": é falha do fornecedor com cara de
sucesso, e fechar 227 veículos como sumidos por causa dela apagaria o painel.
O fechamento só roda quando a coleta trouxe gente.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from . import armazenamento, cliente

log = logging.getLogger("cortex.tress.coleta")

#: Abaixo disto, a resposta não é uma frota — é um acidente. A conta tem 227
#: veículos; exigir ao menos um punhado evita fechar o espelho inteiro por
#: causa de uma resposta truncada.
MINIMO_PARA_FECHAR = 10


def _placa(bruto: str) -> str:
    """A PLACA é a chave (regra da casa). A 3S manda com espaço: 'AAW 5394'."""
    return re.sub(r"[^A-Z0-9]", "", (bruto or "").upper())


def _data(bruto: str):
    """`2026-09-03T13:22:20-03:00` → datetime ingênuo no horário local.

    O fuso vem na string e é sempre -03:00 nesta API; guardar o deslocamento
    não acrescenta nada e faria a coluna divergir de todas as outras do banco,
    que são ingênuas. O que NÃO se pode é descartar a hora: "comunicou hoje" a
    perde para sempre se o valor virar só data.
    """
    if not bruto:
        return None
    try:
        return datetime.fromisoformat(bruto).replace(tzinfo=None)
    except ValueError:
        return None


def _num(bruto, inteiro=False):
    try:
        v = float(str(bruto).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(v) if inteiro else v


def coletar(esquema: str | None = None) -> dict:
    """Roda a coleta inteira. Devolve o resumo; levanta só se nem falar deu."""
    inicio = datetime.now()
    xml = cliente.chamar("ListaVeiculos")
    brutos = cliente.registros(xml)
    veiculos = []
    for r in brutos:
        placa = _placa(r.get("Placa"))
        if not placa:
            continue
        veiculos.append({
            "placa": placa,
            "frota": r.get("Frota") or None,
            "modelo": r.get("Modelo") or None,
            "tipo": r.get("Tipo") or None,
            "id_equipamento": r.get("idEquipamento") or None,
            "id_veiculo": r.get("idVeiculo") or None,
            "num_serie": r.get("NumSerie") or None,
            "chassi": r.get("Chassis") or None,
        })
    if not veiculos:
        raise cliente.TressIndisponivel(
            "a 3S devolveu a lista de veículos VAZIA — não se conclui frota "
            "nenhuma disso, e o espelho fica como estava")

    armazenamento.gravar_veiculos(veiculos, inicio, esquema=esquema)

    xml = cliente.chamar("ListaUltimaPosicaoVeiculos")
    posicoes = []
    conhecidas = {v["placa"] for v in veiculos}
    for r in cliente.registros(xml):
        placa = _placa(r.get("Placa"))
        dt = _data(r.get("Data"))
        # posição de placa que não está no cadastro seria órfã (a tabela tem
        # chave estrangeira): a 3S é a mesma fonte das duas listas, então isso
        # só acontece se as respostas vierem de momentos diferentes
        if not placa or not dt or placa not in conhecidas:
            continue
        posicoes.append({
            "placa": placa,
            "id_posicao": r.get("idPosicao") or None,
            "dt": dt,
            "latitude": _num(r.get("Latitude")),
            "longitude": _num(r.get("Longitude")),
            "velocidade": _num(r.get("Velocidade"), inteiro=True),
            "ignicao": r.get("Ignicao") or None,
            "satelites": _num(r.get("Satelite"), inteiro=True),
            "uf": r.get("UF") or None,
            "cidade": r.get("Cidade") or None,
            "bairro": r.get("Bairro") or None,
            "endereco": r.get("Endereco") or None,
        })
    armazenamento.gravar_posicoes(posicoes, esquema=esquema)
    # o DIA de cada posição, que é o que a régua diária pergunta
    dias = armazenamento.marcar_vistos(posicoes, esquema=esquema)

    # O FECHAMENTO É ANCORADO NO INÍCIO da coleta: quem não foi visto por uma
    # coleta que rodou INTEIRA saiu da conta. Numa que trouxe pouco, não se
    # conclui nada — e por isso o piso.
    sumiram = 0
    if len(veiculos) >= MINIMO_PARA_FECHAR:
        sumiram = armazenamento.fechar_ausentes(inicio, esquema=esquema)

    return {"veiculos": len(veiculos), "posicoes": len(posicoes),
            "dias_marcados": dias, "sumiram": sumiram, "inicio": inicio,
            "segundos": round((datetime.now() - inicio).total_seconds(), 1)}
