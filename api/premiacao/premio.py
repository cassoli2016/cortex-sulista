# -*- coding: utf-8 -*-
"""O que se PAGA: valor base × nota do ciclo, com teto de 100%.

    prêmio = base × min(100, nota) / 100

A conta é essa e tem uma linha. O que custa caro é de onde sai o `base`, e são
quatro caminhos, nesta ordem de precedência:

1. AJUSTE do ciclo — alguém decidiu à mão, com motivo e autor (`prm_premio_ajuste`);
2. ESCADA de tempo de casa — para as filiais marcadas com `usa_escada`;
3. TABELA por grupo e filial (`prm_premio_base`);
4. NADA — e aí a linha NÃO paga zero: ela diz "filial sem valor na tabela".

O item 4 é a regra da casa sobre zero: zero que é ausência de cadastro não é
prêmio de R$ 0,00, é um número que ninguém decidiu. O mesmo vale para quem está
sem nota no ciclo (fonte fora do ar, ninguém rodou a coleta da Gobrax, motorista
novo sem viagem): sem nota não se paga e a linha diz por quê.

O DINHEIRO NÃO ESTÁ AQUI. Nenhum valor em reais aparece neste arquivo nem nas
migrations — o repositório é público. As tabelas nascem vazias e quem opera
preenche na tela; sem isso o módulo calcula tudo e não paga nada, dizendo o que
falta. É o que permite este código ser lido por quem não pode ver a folha.
"""
from __future__ import annotations

import logging
from datetime import datetime

from api import pglocal

from . import ciclo as ciclo_mod, config, identidade, ranking

log = logging.getLogger("cortex.premiacao.premio")

ESQUEMA: str | None = None

#: De onde veio o valor base — a linha da tela DIZ qual foi, porque "R$ 600"
#: vindo da tabela e "R$ 600" vindo de um ajuste manual são o mesmo número e
#: afirmações diferentes, e só a segunda pode ser revista.
ORIGENS = {
    "ajuste": "ajuste do ciclo",
    "escada": "escada de tempo de casa",
    "tabela": "tabela por filial",
    "sem_tabela": "filial sem valor na tabela",
    "sem_filial": "motorista sem filial no cadastro",
}


def _esq():
    return ESQUEMA


# --------------------------------------------------------------- a tabela
def tabela(ciclo: str) -> dict:
    """Os valores vigentes NESTE ciclo: base por grupo/filial e a escada.

    Banco fora do ar não inventa valor — volta vazio com o motivo, e cada linha
    do pagamento sai sem valor dizendo isso. Pagar por padrão de código seria a
    pior falha possível aqui: um número plausível, em reais, que ninguém
    decidiu.
    """
    saida = {"base": {}, "escada": {}, "versao": None, "vigente_de": None,
             "motivo": ""}
    try:
        versao = config.versao_de(ciclo, esquema=_esq())
        if not versao:
            saida["motivo"] = "nenhuma versão de régua vigente neste ciclo"
            return saida
        saida["versao"] = versao["id"]
        saida["vigente_de"] = versao["vigente_de"]
        for r in pglocal.query(
                "SELECT grupo, filial, valor, usa_escada, nota FROM prm_premio_base"
                " WHERE versao_id = %s", (versao["id"],), esquema=_esq()):
            saida["base"].setdefault(r["grupo"], {})[r["filial"]] = {
                "valor": float(r["valor"]), "usa_escada": bool(r["usa_escada"]),
                "nota": r["nota"] or ""}
        for r in pglocal.query(
                "SELECT grupo, ate_meses, valor FROM prm_premio_escada"
                " WHERE versao_id = %s ORDER BY grupo, ate_meses",
                (versao["id"],), esquema=_esq()):
            saida["escada"].setdefault(r["grupo"], []).append(
                {"ate_meses": int(r["ate_meses"]), "valor": float(r["valor"])})
        if not saida["base"]:
            saida["motivo"] = "nenhum valor base cadastrado nesta versão"
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: tabela de premio indisponivel (%s)",
                    type(exc).__name__)
        saida["motivo"] = "tabela de valores indisponível"
    return saida


def ajustes(ciclo: str) -> dict[str, dict]:
    """Os ajustes manuais deste ciclo, por CPF."""
    try:
        return {r["cpf"]: {"valor": float(r["valor"]), "motivo": r["motivo"],
                           "autor": r["autor"], "criado_em": r["criado_em"]}
                for r in pglocal.query(
                    "SELECT cpf, valor, motivo, autor, criado_em"
                    " FROM prm_premio_ajuste WHERE ciclo = %s", (ciclo,),
                    esquema=_esq())}
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: ajustes indisponiveis (%s)", type(exc).__name__)
        return {}


# ------------------------------------------------------------- a conta
def meses_de_casa(admissao: str | None, ciclo: str) -> int | None:
    """Meses entre a admissão e o ciclo. Sem admissão, `None` — e quem usa isso
    fica no PRIMEIRO degrau, nunca no último: na dúvida sobre tempo de casa, a
    casa não paga a mais por um dado que não tem."""
    if not admissao or len(str(admissao)) < 7:
        return None
    try:
        ay, am = int(str(admissao)[:4]), int(str(admissao)[5:7])
        ry, rm = int(ciclo[:4]), int(ciclo[5:7])
    except (TypeError, ValueError):
        return None
    return max(0, (ry - ay) * 12 + (rm - am))


def valor_da_escada(degraus: list[dict], meses: int | None) -> float | None:
    """O degrau em que o tempo de casa cai. Sem degrau cadastrado, `None`."""
    if not degraus:
        return None
    ordenados = sorted(degraus, key=lambda d: d["ate_meses"])
    if meses is None:
        return float(ordenados[0]["valor"])
    for d in ordenados:
        if meses <= d["ate_meses"]:
            return float(d["valor"])
    return float(ordenados[-1]["valor"])


def base_de(linha: dict, cpf: str | None, ciclo: str, tab: dict, ajs: dict) -> dict:
    """O valor base deste motorista e DE ONDE ELE VEIO.

    O CPF entra por FORA da linha: a linha do ranking não o carrega (é PII, e
    ela vai inteira para a tela), mas o ajuste manual é gravado por CPF, que é
    a chave do cadastro. Quem chama faz a ponte e não devolve a chave.
    """
    aj = ajs.get(cpf or "")
    if aj:
        return {"base": aj["valor"], "origem": "ajuste", "motivo": aj["motivo"],
                "meses_casa": meses_de_casa(linha.get("admissao"), ciclo)}
    filial = linha.get("filial")
    if not filial:
        return {"base": None, "origem": "sem_filial", "motivo": "",
                "meses_casa": None}
    do_grupo = (tab["base"].get(linha.get("tipo")) or {})
    ficha = do_grupo.get(filial)
    if not ficha:
        return {"base": None, "origem": "sem_tabela", "motivo": "",
                "meses_casa": None}
    if ficha["usa_escada"]:
        meses = meses_de_casa(linha.get("admissao"), ciclo)
        valor = valor_da_escada(tab["escada"].get(linha.get("tipo")) or [], meses)
        if valor is None:
            return {"base": None, "origem": "sem_tabela", "motivo": "",
                    "meses_casa": meses}
        return {"base": valor, "origem": "escada", "motivo": "",
                "meses_casa": meses}
    return {"base": ficha["valor"], "origem": "tabela", "motivo": "",
            "meses_casa": None}


def valor_do_premio(base: float | None, nota: float | None) -> dict:
    """base × nota, com teto de 100% e piso de zero.

    O TETO É O PONTO: a reputação passa de 100 de propósito (é o que faz a
    categoria ELITE existir), mas o PAGAMENTO não acompanha. Sem o teto, nota
    106 pagaria 6% a mais sem que ninguém tivesse decidido isso.

    O arredondamento é em CENTAVOS e sobre o produto — arredondar o percentual
    antes moveria o valor de quem está na fronteira.
    """
    if base is None:
        return {"pct": None, "valor": None}
    if nota is None:
        return {"pct": None, "valor": None}
    pct = max(0.0, min(100.0, float(nota)))
    return {"pct": round(pct, 1), "valor": round(base * pct / 100.0, 2)}


# ------------------------------------------------------------ o pagamento
def montar(ciclo: str | None = None, dir_snapshots=None,
           ranking_pronto: dict | None = None) -> dict:
    """O ciclo com o valor a pagar em cada linha.

    `ranking_pronto` existe para quem já montou o ciclo (a tela mostra as duas
    coisas) não pagar duas vezes pela leitura das quatro fontes.
    """
    r = ranking_pronto or ranking.montar(ciclo, dir_snapshots=dir_snapshots)
    alvo = r["ciclo"]
    tab = tabela(alvo)
    ajs = ajustes(alvo)
    # A ponte código do cadastro -> CPF fica AQUI dentro e não sai no payload.
    cpf_de = {m["cadastro_codigo"]: m["cpf"] for m in identidade.listar()}

    linhas = []
    for x in r["linhas"]:
        b = base_de(x, cpf_de.get(x["motorista"]), alvo, tab, ajs)
        conta = valor_do_premio(b["base"], x["nota"])
        linhas.append({
            "motorista": x["motorista"], "nome": x["nome"], "tipo": x["tipo"],
            "filial": x["filial"], "meses_casa": b["meses_casa"],
            # As notas dos três pilares viajam junto porque o FECHAMENTO as
            # guarda: seis meses depois a pergunta não é "quanto ele recebeu",
            # é "por que ele recebeu isto".
            "gobrax": x["gobrax"], "conduta": x["conduta"], "gr": x["gr"],
            "nota": x["nota"], "status": x["status"], "categoria": x["categoria"],
            "base": b["base"], "base_origem": b["origem"],
            "base_rotulo": ORIGENS[b["origem"]],
            "ajuste_motivo": b["motivo"],
            "pct": conta["pct"], "valor": conta["valor"],
            "motivo": _motivo(b["origem"], x["nota"]),
        })
    # Por VALOR, do maior para o menor: esta tela é a da folha — quem confere
    # pagamento começa pelo que pesa. (O ranking, que existe para tratar quem
    # está mal, ordena ao contrário; são perguntas diferentes.)
    linhas.sort(key=lambda x: (x["valor"] is None, -(x["valor"] or 0), x["nome"]))
    return {
        "ciclo": alvo, "rotulo": r["rotulo"],
        "linhas": linhas,
        "tabela": tab,
        "kpis": _kpis(linhas),
        "fontes": r["fontes"], "pendencias": r["pendencias"],
    }


def _motivo(origem: str, nota: float | None) -> str:
    if origem in ("sem_tabela", "sem_filial"):
        return ORIGENS[origem]
    if nota is None:
        return "sem nota no ciclo"
    return ""


def _kpis(linhas: list[dict]) -> dict:
    com_valor = [x for x in linhas if x["valor"] is not None]
    return {
        "motoristas": len(linhas),
        "a_pagar": round(sum(x["valor"] for x in com_valor), 2),
        # O "se todos tirassem 100%" é o teto do desenho, e a diferença para o
        # a_pagar é o que a régua deixou de pagar neste ciclo — o número que a
        # mesa pergunta primeiro.
        "teto": round(sum(x["base"] for x in linhas if x["base"] is not None), 2),
        "pagos": len(com_valor),
        "sem_valor": len(linhas) - len(com_valor),
        "sem_nota": sum(1 for x in linhas if x["nota"] is None),
        "sem_tabela": sum(1 for x in linhas
                          if x["base_origem"] in ("sem_tabela", "sem_filial")),
        "ajustados": sum(1 for x in linhas if x["base_origem"] == "ajuste"),
    }


# --------------------------------------------------------------- escrita
def salvar_tabela(ciclo: str, grupo: str, filiais: dict, autor: str,
                  nota: str = "") -> dict:
    """Grava os valores base deste grupo na versão vigente a partir de `ciclo`.

    `filiais` é {filial: {"valor": n, "usa_escada": bool, "nota": str}}.
    """
    from . import parametros
    if grupo not in parametros.GRUPOS:
        raise ValueError(f"Grupo inválido: {grupo!r}")
    if not autor:
        raise ValueError("Informe quem está salvando (trilha de auditoria).")
    limpos = {}
    for filial, ficha in (filiais or {}).items():
        if not str(filial).strip():
            raise ValueError("Filial sem nome.")
        try:
            valor = float((ficha or {}).get("valor"))
        except (TypeError, ValueError):
            raise ValueError(f"Valor inválido na filial {filial!r}.")
        if valor < 0:
            raise ValueError(f"O valor da filial {filial!r} não pode ser negativo.")
        limpos[str(filial).strip().upper()] = (
            valor, bool((ficha or {}).get("usa_escada")),
            str((ficha or {}).get("nota") or ""))
    versao_id = parametros._versao_para(ciclo, autor, nota)
    for filial, (valor, escada, obs) in limpos.items():
        pglocal.executar(
            "INSERT INTO prm_premio_base(versao_id, grupo, filial, valor,"
            " usa_escada, nota) VALUES(%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (versao_id, grupo, filial) DO UPDATE SET"
            " valor = EXCLUDED.valor, usa_escada = EXCLUDED.usa_escada,"
            " nota = EXCLUDED.nota",
            (versao_id, grupo, filial, valor, escada, obs), esquema=_esq())
    return {"ciclo": ciclo, "grupo": grupo, "versao": versao_id,
            "filiais": sorted(limpos)}


def salvar_escada(ciclo: str, grupo: str, degraus: list[dict], autor: str,
                  nota: str = "") -> dict:
    """Grava a escada de tempo de casa deste grupo.

    A escada é SUBSTITUÍDA por inteiro: degrau que sai do formulário tem de sair
    do banco, senão um degrau removido continuaria pagando calado.
    """
    from . import parametros
    if grupo not in parametros.GRUPOS:
        raise ValueError(f"Grupo inválido: {grupo!r}")
    if not autor:
        raise ValueError("Informe quem está salvando (trilha de auditoria).")
    limpos = []
    for d in (degraus or []):
        try:
            meses, valor = int(d["ate_meses"]), float(d["valor"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Degrau inválido: {d!r}")
        if meses <= 0:
            raise ValueError("O degrau tem de ser de pelo menos um mês.")
        if valor < 0:
            raise ValueError("Valor do degrau não pode ser negativo.")
        limpos.append((meses, valor))
    if len({m for m, _ in limpos}) != len(limpos):
        raise ValueError("Há dois degraus com o mesmo limite de meses.")
    versao_id = parametros._versao_para(ciclo, autor, nota)
    pglocal.executar("DELETE FROM prm_premio_escada WHERE versao_id = %s"
                     " AND grupo = %s", (versao_id, grupo), esquema=_esq())
    for meses, valor in sorted(limpos):
        pglocal.executar(
            "INSERT INTO prm_premio_escada(versao_id, grupo, ate_meses, valor)"
            " VALUES(%s,%s,%s,%s)", (versao_id, grupo, meses, valor),
            esquema=_esq())
    return {"ciclo": ciclo, "grupo": grupo, "versao": versao_id,
            "degraus": len(limpos)}


def ajustar(ciclo: str, cpf: str, valor: float, motivo: str, autor: str) -> dict:
    """Decide à mão o valor base de uma pessoa NESTE ciclo."""
    if not ciclo_mod.valido(ciclo):
        raise ValueError(f"Ciclo inválido: {ciclo!r}. Use 'AAAA-MM'.")
    if not str(motivo or "").strip():
        raise ValueError("Informe o motivo do ajuste.")
    if not autor:
        raise ValueError("Informe quem está ajustando (trilha de auditoria).")
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"Valor inválido: {valor!r}")
    if valor < 0:
        raise ValueError("O valor não pode ser negativo.")
    pglocal.executar(
        "INSERT INTO prm_premio_ajuste(ciclo, cpf, valor, motivo, autor, criado_em)"
        " VALUES(%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (ciclo, cpf) DO UPDATE SET valor = EXCLUDED.valor,"
        " motivo = EXCLUDED.motivo, autor = EXCLUDED.autor,"
        " criado_em = EXCLUDED.criado_em",
        (ciclo, cpf, valor, motivo.strip(), autor,
         datetime.now().isoformat(timespec="seconds")), esquema=_esq())
    return {"ciclo": ciclo, "cpf": cpf, "valor": valor}


def limpar_ajuste(ciclo: str, cpf: str) -> dict:
    """Volta o motorista para a tabela (ou para a escada)."""
    pglocal.executar("DELETE FROM prm_premio_ajuste WHERE ciclo = %s AND cpf = %s",
                     (ciclo, cpf), esquema=_esq())
    return {"ciclo": ciclo, "cpf": cpf, "valor": None}
