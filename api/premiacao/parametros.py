# -*- coding: utf-8 -*-
"""Os parâmetros da régua do GMA, por GRUPO e por versão.

Os padrões abaixo são os do modelo que quem opera desenhou (18/09/2026). Eles
valem enquanto ninguém salvar uma versão — e a regra da casa manda que
parâmetro NOVO no código caia no padrão em vez de sumir, para um deploy que
acrescenta parâmetro não parar de calcular as versões antigas.

A vigência é a MESMA de `prem_versoes` (a tabela que a premiação já usa para
dizer a partir de que competência uma régua vale). Não há segunda linha do
tempo: "a régua mudou em agosto" tem uma resposta só.
"""
from __future__ import annotations

import logging

from api import pglocal

from . import catalogo, config

log = logging.getLogger("cortex.premiacao.parametros")

ESQUEMA: str | None = None

GRUPOS = ("RODOVIARIO", "MANOBRA")

#: chave -> (padrão, rótulo, o que ela decide)
PADROES: dict[str, tuple[float, str, str]] = {
    "peso_gobrax": (40, "Peso da Gobrax (%)", "quanto a nota de condução vale na composta"),
    "peso_conduta": (40, "Peso do comportamento (%)", "quanto as ocorrências valem na composta"),
    "peso_gr": (20, "Peso do GR (%)", "quanto o gerenciamento de risco vale na composta"),
    "bonus_ciclo_limpo": (2, "Bônus por ciclo limpo", "pontos na reputação por ciclo sem desvio"),
    # 58 = o p90 do risco por viagem medido no ciclo 16/08-15/09/2026, com os
    # pesos calibrados do catálogo. Decisão de quem opera (18/09/2026): a nota
    # vai de 60 (os 10% piores) a 98 (os melhores), sem ninguém no piso. O 10
    # do modelo original valia para outra escala (tipos de exceção, não
    # contadores de evento) e punha todo mundo no piso.
    "gr_referencia": (58, "GR: risco de referência", "pontos de risco por viagem que derrubam a nota em cheio"),
    "gr_queda": (40, "GR: queda máxima", "quanto a nota cai no risco de referência"),
    "gr_piso": (20, "GR: piso da nota", "abaixo disto a nota de GR não desce"),
    "gr_minimo_viagens": (5, "GR: mínimo de viagens", "abaixo disto o ciclo não tem nota de GR"),
    "status_excelente": (92, "Status: excelente a partir de", ""),
    "status_bom": (85, "Status: bom a partir de", ""),
    "status_atencao": (75, "Status: atenção a partir de", ""),
    "status_alerta": (65, "Status: alerta a partir de", ""),
    "cat_elite": (105, "Categoria: Elite a partir de", ""),
    "cat_diamante": (95, "Categoria: Diamante a partir de", ""),
    "cat_ouro": (85, "Categoria: Ouro a partir de", ""),
    "cat_prata": (70, "Categoria: Prata a partir de", ""),
}


def defaults() -> dict[str, float]:
    return {k: float(v[0]) for k, v in PADROES.items()}


def _esq():
    return ESQUEMA


def ler(ciclo: str, grupo: str = "RODOVIARIO") -> dict:
    """Os parâmetros vigentes NESTE ciclo para ESTE grupo.

    Banco fora do ar cai nos padrões em vez de derrubar a tela — a mesma
    escolha de `servico.params_da_competencia`. O que volta diz de que versão
    veio, para a tela poder declarar a régua que está mostrando.
    """
    if grupo not in GRUPOS:
        raise ValueError(f"Grupo inválido: {grupo!r}")
    valores = defaults()
    versao = None
    try:
        versao = config.versao_de(ciclo, esquema=_esq())
        if versao:
            linhas = pglocal.query(
                "SELECT chave, valor FROM prm_param"
                " WHERE versao_id = %s AND grupo = %s", (versao["id"], grupo),
                esquema=_esq())
            for r in linhas:
                if r["chave"] in valores:
                    valores[r["chave"]] = float(r["valor"])
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: parametros do banco indisponiveis (%s)",
                    type(exc).__name__)
    return {"grupo": grupo, "ciclo": ciclo, "valores": valores,
            "versao": (versao or {}).get("id"),
            "vigente_de": (versao or {}).get("vigente_de")}


def pesos_gr(ciclo: str) -> dict[str, float]:
    """O peso de cada contador de risco do GR — padrão do catálogo, sobrescrito
    pela versão vigente quando alguém mexeu."""
    pesos = catalogo.pesos_gr_padrao()
    try:
        versao = config.versao_de(ciclo, esquema=_esq())
        if versao:
            for r in pglocal.query(
                    "SELECT contador, peso FROM prm_gr_peso WHERE versao_id = %s",
                    (versao["id"],), esquema=_esq()):
                if r["contador"] in pesos:
                    pesos[r["contador"]] = float(r["peso"])
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: pesos de GR indisponiveis (%s)", type(exc).__name__)
    return pesos


def depara() -> dict[int, str]:
    """Código do ERP -> D../M../IGNORAR. Vazio quando o banco não responde: sem
    de-para nenhuma ocorrência vira desvio, e a tela diz isso — inventar
    penalidade por falta de tabela seria pior."""
    try:
        return {int(r["codigo"]): r["alvo"] for r in pglocal.query(
            "SELECT codigo, alvo FROM prm_depara", esquema=_esq())}
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: de-para indisponivel (%s)", type(exc).__name__)
        return {}


def salvar(ciclo: str, grupo: str, valores: dict, autor: str,
           nota: str = "") -> dict:
    """Grava os parâmetros deste grupo na versão vigente a partir de `ciclo`.

    A vigência é a MESMA linha do tempo da premiação antiga (`prem_versoes`),
    para "desde quando esta régua vale" ter uma resposta só — mas a escrita é
    própria (ver `_versao_para`), porque `config.salvar` valida e apaga a
    configuração da régua que ainda está pagando.

    Os três pesos TÊM de somar 100%: a composta é média ponderada, e pesos que
    somam 90 dariam uma nota que não é comparável com a de quem somou 100 —
    sem erro nenhum, e com o ranking inteiro deslocado.
    """
    if grupo not in GRUPOS:
        raise ValueError(f"Grupo inválido: {grupo!r}")
    if not autor:
        raise ValueError("Informe quem está salvando (trilha de auditoria).")
    limpos = {}
    for chave, valor in (valores or {}).items():
        if chave not in PADROES:
            raise ValueError(f"Parâmetro desconhecido: {chave!r}")
        try:
            limpos[chave] = float(valor)
        except (TypeError, ValueError):
            raise ValueError(f"Valor inválido em {chave!r}: {valor!r}")
        if limpos[chave] < 0:
            raise ValueError(f"{chave!r} não pode ser negativo.")
    soma = sum(limpos.get(k, defaults()[k])
               for k in ("peso_gobrax", "peso_conduta", "peso_gr"))
    if abs(soma - 100) > 0.01:
        raise ValueError(
            f"Os pesos dos três pilares somam {soma:.0f}% — têm de somar 100%.")
    versao_id = _versao_para(ciclo, autor, nota)
    for chave, valor in limpos.items():
        pglocal.executar(
            "INSERT INTO prm_param(versao_id, grupo, chave, valor)"
            " VALUES(%s,%s,%s,%s)"
            " ON CONFLICT (versao_id, grupo, chave) DO UPDATE SET valor = EXCLUDED.valor",
            (versao_id, grupo, chave, valor), esquema=_esq())
    return {"ciclo": ciclo, "grupo": grupo, "versao": versao_id,
            "valores": limpos, "autor": autor}


def _versao_para(ciclo: str, autor: str, nota: str) -> int:
    """A linha de `prem_versoes` deste ciclo — criada se ainda nao existir.

    NAO passa por `config.salvar`, e isso e deliberado: aquela funcao valida a
    regra ANTIGA (exige valor por km e um eixo ativo) e APAGA os parametros e
    eixos da versao antes de regrava-los. Chamada daqui com dicionarios vazios,
    ela recusaria a gravacao — e, se nao recusasse, apagaria a configuracao da
    premiacao que ainda esta pagando. A vigencia continua sendo a mesma tabela;
    o que muda e quem escreve cada parte dela.
    """
    from datetime import datetime
    agora = datetime.now().isoformat(timespec="seconds")
    achada = pglocal.um("SELECT id FROM prem_versoes WHERE vigente_de = %s",
                        (ciclo,), esquema=_esq())
    if achada:
        if nota:
            pglocal.executar(
                "UPDATE prem_versoes SET nota = %s, criado_em = %s, criado_por = %s"
                " WHERE id = %s", (nota, agora, autor, achada["id"]), esquema=_esq())
        return int(achada["id"])
    nova = pglocal.um(
        "INSERT INTO prem_versoes(vigente_de, regra, nota, criado_em, criado_por)"
        " VALUES(%s,'gma',%s,%s,%s) RETURNING id",
        (ciclo, nota, agora, autor), esquema=_esq())
    return int(nova["id"])


def catalogo_publico() -> dict:
    """O que a tela mostra na aba de parâmetros: os padrões e o que cada um faz."""
    return {
        "parametros": [{"chave": k, "padrao": v[0], "rotulo": v[1], "explica": v[2]}
                       for k, v in PADROES.items()],
        "grupos": list(GRUPOS),
        "desvios": [dict(d) for d in catalogo.DESVIOS],
        "meritos": [dict(m) for m in catalogo.MERITOS],
        "contadores_gr": [dict(c) for c in catalogo.CONTADORES_GR],
        "so_informativos": [dict(c) for c in catalogo.informativos()],
    }
