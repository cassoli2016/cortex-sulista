# -*- coding: utf-8 -*-
"""Quem participa da campanha, e por que chave.

FROTA sai do cadastro da premiação (que vem da folha). AGREGADO sai do ERP:
quem rodou veículo `AGR` no ciclo. São perguntas diferentes de propósito — o
próprio existe no cadastro mesmo parado; o agregado só existe para a campanha
se ele RODOU, porque não há vínculo de folha que o segure.
"""
from __future__ import annotations

import hashlib
import logging

from api import db
from api.premiacao import ciclo as ciclo_mod, identidade

log = logging.getLogger("cortex.campanha.base")

#: Quem rodou veículo AGREGADO no ciclo, com o nome do cadastro e as viagens.
#:
#: `utilizacaoveiculo = 'AGR'` e não `tipofrota`: é a mesma leitura que o app do
#: agregado já faz. Medido em 18/09/2026: 162 motoristas em 90 dias, 9.144
#: viagens — contra 62 de locado e 55 de terceiro, que ficam de fora.
AGREGADOS_SQL = """
SELECT p.motorista                                          AS cpf,
       coalesce(nullif(trim(c.razaosocial), ''), '(sem nome)') AS nome,
       count(*)                                             AS viagens,
       min(cc.dtvencimentocarteirahabilitacao)::date        AS venc_cnh
  FROM programacaoembarque p
  JOIN veiculo v ON v.placa = p.veiculo
  LEFT JOIN cadastro c ON c.codigo = p.motorista
  LEFT JOIN cadastro_continua cc ON cc.cnpjcpfcodigo = p.motorista
 WHERE p.dtcancelamento IS NULL
   AND p.dtsaida >= %(de)s::date AND p.dtsaida < %(ate)s::date
   AND v.utilizacaoveiculo = 'AGR'
   AND p.motorista IS NOT NULL
 GROUP BY 1, 2
"""


def chave(campanha_id: int, cpf: str) -> str:
    """A identidade do participante FORA do servidor.

    Resumo determinístico do CPF DENTRO da campanha: casa linha com linha (a
    tela, o app e a fotografia falam a mesma língua) e não serve para descobrir
    de quem é. O `campanha_id` entra para que a mesma pessoa não tenha a mesma
    chave em duas campanhas — chave estável entre campanhas viraria um
    identificador de pessoa, que é justamente o que não se quer publicar.
    """
    cru = f"{int(campanha_id)}:{''.join(ch for ch in str(cpf) if ch.isdigit())}"
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()[:12]


def participantes(campanha_id: int, ciclo: str) -> dict[str, list[dict]]:
    """{grupo: [participante]} do ciclo, com a chave opaca já montada.

    Falha de UMA fonte não derruba a outra: sem o ERP a campanha continua
    mostrando a frota, e o grupo que faltou DIZ o motivo. Um dos dois grupos em
    branco é uma resposta; os dois em branco sem motivo seria a tela mentindo
    que ninguém participa.
    """
    de, ate = ciclo_mod.limites(ciclo)
    saida: dict[str, list[dict]] = {"FROTA": [], "AGREGADO": []}
    motivos: dict[str, str] = {"FROTA": "", "AGREGADO": ""}

    try:
        for m in identidade.listar(ativos=True):
            saida["FROTA"].append({
                "cpf": m["cpf"], "nome": m["nome"], "grupo": "FROTA",
                "chave": chave(campanha_id, m["cpf"]),
                "viagens": None, "venc_cnh": None,
                "ativo": bool(m.get("ativo")),
            })
    except Exception as exc:  # noqa: BLE001
        log.warning("campanha: cadastro da frota indisponivel (%s)",
                    type(exc).__name__)
        motivos["FROTA"] = "cadastro da frota indisponível"

    try:
        for r in db.query(AGREGADOS_SQL, {"de": de, "ate": ate}):
            saida["AGREGADO"].append({
                "cpf": r["cpf"], "nome": r["nome"], "grupo": "AGREGADO",
                "chave": chave(campanha_id, r["cpf"]),
                "viagens": int(r["viagens"]),
                "venc_cnh": r["venc_cnh"].isoformat() if r["venc_cnh"] else None,
                "ativo": True,      # rodou no ciclo: é o vínculo que existe
            })
    except Exception as exc:  # noqa: BLE001
        log.warning("campanha: agregados indisponiveis (%s)", type(exc).__name__)
        motivos["AGREGADO"] = "operação dos agregados indisponível"

    return {"por_grupo": saida, "motivos": motivos}
