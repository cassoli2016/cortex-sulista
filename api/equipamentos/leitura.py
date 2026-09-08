# -*- coding: utf-8 -*-
"""O que a tela pergunta ao cadastro.

Converte no LIMITE do módulo: `Decimal` vira `float` e `date` vira ISO AQUI, e
não na rota. O `JSONResponse` da casa é a rede — um `Decimal` que chega lá
estoura dentro do `render()`, DEPOIS do `try/except` da rota, e vira 500 em
`text/plain` sem pista nenhuma de qual campo.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .. import pglocal
from . import armazenamento as arm
from . import consolidacao
from . import smartec as _smt
from .campos import CAMPOS, GRUPOS, POR_NOME, ROTULO_FONTE
from .campos import pendencias_da_independencia

#: Os vínculos, na ordem das fases da coleta.
VINCULOS = ("proprio", "agregado", "terceiro")

ROTULO_VINCULO = {"proprio": "Próprio", "agregado": "Agregado",
                  "terceiro": "Terceiro"}
ROTULO_CATEGORIA = {"tracao": "Tração", "implemento": "Implemento"}


def _limpo(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _limpo(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpo(v) for v in valor]
    return valor


def _linha(row: dict) -> dict:
    return {k: _limpo(v) for k, v in row.items()}


# ────────────────────────────────────────────────────────────────── a lista

def listar(*, vinculo: str | None = None, categoria: str | None = None,
           busca: str | None = None, limite: int = 500) -> dict:
    """A tabela da tela. TODO filtro que a tela oferece é aplicado aqui.

    Filtro que a consulta ignora sai da tela: campo que aceita valor e não
    muda nada é pior que campo nenhum, porque quem filtra acredita no
    resultado.
    """
    sql = ["SELECT * FROM eqp_equipamento WHERE ativo = true"]
    params: list = []
    if vinculo:
        sql.append("AND vinculo = %s")
        params.append(vinculo)
    if categoria:
        sql.append("AND categoria = %s")
        params.append(categoria)
    if busca:
        # Placa, frota, chassi, renavam, marca e modelo — os seis campos por
        # que uma pessoa procura um equipamento. Sem acento no LIKE porque
        # todos eles são alfanuméricos de documento.
        sql.append("AND (placa ILIKE %s OR coalesce(numero_frota,'') ILIKE %s"
                   " OR coalesce(chassi,'') ILIKE %s"
                   " OR coalesce(renavam,'') ILIKE %s"
                   " OR coalesce(marca,'') ILIKE %s"
                   " OR coalesce(modelo,'') ILIKE %s)")
        alvo = f"%{busca.strip()}%"
        params.extend([alvo] * 6)
    sql.append("ORDER BY placa")

    total = pglocal.um(
        "SELECT count(*) AS n FROM (" + " ".join(sql) + ") q",
        tuple(params) or None, esquema=arm.ESQUEMA) or {}
    linhas = pglocal.query(" ".join(sql) + " LIMIT %s",
                           tuple([*params, limite]), esquema=arm.ESQUEMA)
    return {
        "equipamentos": [_linha(r) for r in linhas],
        # TOP-N LEVA CONTADOR: sem ele, "500 equipamentos" vira total falso.
        "mostrando": len(linhas),
        "total": int(total.get("n") or 0),
        "limite": limite,
    }


# ──────────────────────────────────────────────────────────────── o detalhe

def detalhe(placa: str) -> dict | None:
    """Um equipamento, com TODAS as fontes lado a lado.

    É a tela que responde "de onde veio este número?" sem sair dela — e a que
    mostra a divergência em vez de escondê-la atrás do vencedor.
    """
    placa = (placa or "").strip().upper()
    row = pglocal.um("SELECT * FROM eqp_equipamento WHERE placa = %s",
                     (placa,), esquema=arm.ESQUEMA)
    if not row:
        return None

    fontes = arm.fontes_da_placa(placa)
    edicoes = {e["campo"]: e for e in arm.edicoes_da_placa(placa)}
    origem = row.get("origem") or {}

    grupos = []
    for grupo in GRUPOS:
        itens = []
        for campo in CAMPOS:
            if campo["grupo"] != grupo:
                continue
            nome = campo["nome"]
            fonte = origem.get(nome)
            itens.append({
                "campo": nome,
                "rotulo": campo["rotulo"],
                "valor": _limpo(row.get(nome)),
                "fonte": fonte,
                "fonte_rotulo": ROTULO_FONTE.get(fonte) if fonte else None,
                "ajuda": campo["ajuda"] or None,
                "so_erp": campo["so_erp"],
                "editado": nome in edicoes,
                # O que CADA fonte disse deste campo — inclusive as que
                # perderam. É isto que permite conferir sem abrir o banco.
                "por_fonte": {
                    f: _limpo((d.get("campos") or {}).get(nome))
                    for f, d in fontes.items()
                    if (d.get("campos") or {}).get(nome) not in (None, "")
                },
            })
        if itens:
            grupos.append({"grupo": grupo, "campos": itens})

    return {
        "placa": placa,
        "resumo": _linha(row),
        "grupos": grupos,
        "divergencias": consolidacao.divergencias(
            fontes, {k: v["valor"] for k, v in edicoes.items()}),
        "fontes": [{"fonte": f, "rotulo": ROTULO_FONTE.get(f, f),
                    "visto_em": _limpo(d.get("visto_em"))}
                   for f, d in sorted(fontes.items())],
        "edicoes": [_linha(e) for e in edicoes.values()],
    }


# ─────────────────────────────────────────────────────────────── o panorama

def _cob_smartec() -> dict:
    """Quanto da frota a Smartec alcanca. Ver `smartec.cobertura`."""
    return _smt.cobertura()


def panorama() -> dict:
    """A linha de status da tela: o que o cadastro tem e o que falta.

    Cada número aqui responde a uma pergunta de decisão, não é enfeite:
    quantos equipamentos existem, quanto deles o Detran já confirmou, quanto
    ainda depende só do ERP, e quanto custa terminar.
    """
    por_vinculo = pglocal.query(
        "SELECT vinculo, categoria, count(*) AS n FROM eqp_equipamento"
        " WHERE ativo = true GROUP BY 1, 2 ORDER BY 1, 2", esquema=arm.ESQUEMA)
    total = sum(r["n"] for r in por_vinculo)

    # COBERTURA DA FONTE OFICIAL: quantas placas a Smartec (Detran) alcanca.
    # Contado em `eqp_fonte`, e nao por coluna preenchida em
    # `eqp_equipamento`: uma placa pode estar na Smartec e ter perdido todos
    # os campos na precedencia -- ela FOI alcancada, e some da conta se o
    # criterio for a coluna.
    cobertura = pglocal.query(
        "SELECT e.vinculo,"
        "       count(*) AS total,"
        "       count(f.placa) AS com_detran"
        "  FROM eqp_equipamento e"
        "  LEFT JOIN (SELECT DISTINCT placa FROM eqp_fonte"
        "              WHERE fonte = 'smartec') f ON f.placa = e.placa"
        " WHERE e.ativo = true"
        " GROUP BY 1 ORDER BY 1", esquema=arm.ESQUEMA)

    # A DEPENDÊNCIA DO ERP, MEDIDA. Quantos campos do cadastro ainda saem do
    # Avacorp — a resposta de "o que quebra se o AVA sair amanhã?".
    dependencia = pglocal.um(
        "SELECT count(*) AS equipamentos,"
        "       sum((SELECT count(*) FROM jsonb_each_text(origem) o"
        "             WHERE o.value = 'erp')) AS campos_do_erp,"
        "       sum((SELECT count(*) FROM jsonb_each_text(origem))) AS campos"
        "  FROM eqp_equipamento WHERE ativo = true",
        esquema=arm.ESQUEMA) or {}

    campos_erp = int(dependencia.get("campos_do_erp") or 0)
    campos_tot = int(dependencia.get("campos") or 0)

    return {
        "total": total,
        "por_vinculo": [
            {"vinculo": v, "rotulo": ROTULO_VINCULO.get(v, v or "—"),
             "total": sum(r["n"] for r in por_vinculo if r["vinculo"] == v),
             "tracao": sum(r["n"] for r in por_vinculo
                           if r["vinculo"] == v and r["categoria"] == "tracao"),
             "implemento": sum(r["n"] for r in por_vinculo
                               if r["vinculo"] == v
                               and r["categoria"] == "implemento")}
            for v in VINCULOS],
        "cobertura_detran": [
            {"vinculo": r["vinculo"],
             "rotulo": ROTULO_VINCULO.get(r["vinculo"], r["vinculo"] or "—"),
             "total": r["total"], "com_detran": r["com_detran"],
             "falta": r["total"] - r["com_detran"]}
            for r in cobertura],
        "dependencia_do_erp": {
            "campos_do_erp": campos_erp,
            "campos_no_total": campos_tot,
            # Percentual sai da unidade de ORIGEM, e só existe com base.
            "percentual": (round(100 * campos_erp / campos_tot, 1)
                           if campos_tot else None),
            # Os campos que HOJE morrem com o Avacorp, nomeados. Aviso
            # genérico não se conserta; campo nomeado, sim.
            "campos_sem_alternativa": [
                {"campo": c["nome"], "rotulo": c["rotulo"], "ajuda": c["ajuda"]}
                for c in pendencias_da_independencia()],
        },
        "cobertura_smartec": _limpo(_cob_smartec()),
    }


def divergencias_gerais(limite: int = 200) -> dict:
    """Onde o Detran e o ERP discordam — o achado que paga a integração.

    Só existe depois da primeira coleta: sem fonte do Detran não há com o que
    discordar, e a tela DIZ isso em vez de mostrar uma lista vazia que se lê
    como "está tudo certo". Lista vazia por falta de medição e lista vazia por
    ausência de problema são a mesma imagem e o oposto em significado.
    """
    fontes = arm.todas_as_fontes()
    edicoes = arm.edicoes()
    com_detran = [p for p, f in fontes.items() if "smartec" in f]
    fora = []
    for placa in sorted(com_detran):
        for d in consolidacao.divergencias(fontes[placa], edicoes.get(placa)):
            fora.append({"placa": placa, **d})
            if len(fora) >= limite:
                break
        if len(fora) >= limite:
            break
    return {
        "divergencias": fora,
        "placas_conferidas": len(com_detran),
        "placas_no_cadastro": len(fontes),
        # Sem esta linha a tela não sabe distinguir "conferi e está tudo
        # certo" de "não conferi nada ainda".
        "conferencia_comecou": bool(com_detran),
    }


def catalogo() -> dict:
    """O catálogo de campos, para a tela montar o formulário e a ajuda.

    A tela NÃO tem lista de campos escrita à mão: ela lê daqui. Lista escrita à
    mão que descreve o código é lista que envelhece calada — foi como a
    varredura de agendadores passou a procurar uma thread com o nome errado.
    """
    return {
        "grupos": [
            {"grupo": g,
             "campos": [{"campo": c["nome"], "rotulo": c["rotulo"],
                         "tipo": c["tipo"], "so_erp": c["so_erp"],
                         "ajuda": c["ajuda"] or None,
                         "fontes": [ROTULO_FONTE.get(f, f)
                                    for f in c["precedencia"]]}
                        for c in CAMPOS if c["grupo"] == g]}
            for g in GRUPOS],
        "vinculos": [{"chave": v, "rotulo": ROTULO_VINCULO[v]}
                     for v in VINCULOS],
        "categorias": [{"chave": k, "rotulo": v}
                       for k, v in ROTULO_CATEGORIA.items()],
    }
