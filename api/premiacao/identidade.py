# -*- coding: utf-8 -*-
"""Quem é o motorista próprio — e como as quatro fontes falam dele.

O PROBLEMA QUE ESTE MÓDULO RESOLVE. A premiação nova lê quatro fontes, e cada
uma identifica a mesma pessoa de um jeito (medido em 18/09/2026):

    folha (Globus)      `cpfcnpj`        CPF, 11 dígitos
    ERP ocorrências     `cnpjcpfcodigo`  CPF, 11 dígitos — 719 de 719
    ERP programação     `motorista`      CPF, 11 dígitos — 26.795 de 26.795
    GR (RasterIntegra)  `cpf_motorista`  CPF com ZEROS À ESQUERDA: 14 dígitos
    Gobrax              `driverName`     NOME (a API não devolve documento)

O CPF atravessa quatro das cinco e por isso é a chave. **O 14 dígitos do GR não
é CNPJ**: é o CPF preenchido com zeros à esquerda, e comparado cru ele não casa
com nada — o cruzamento folha × GR dava ZERO em 15.235 viagens até alguém olhar
o tamanho do campo. `cpf()` corta os 11 dígitos finais, e é por onde todo
casamento passa.

A GOBRAX É A EXCEÇÃO e casa por NOME normalizado, com a guarda que já vale em
`api/motorista/desempenho.py`: **nome que casa com mais de uma pessoa não casa
com ninguém**. Casou uma vez, o `driver_id` fica guardado no cadastro e a
leitura seguinte não depende mais do nome.

O QUE É DA FOLHA E O QUE É DA CASA (decisão de quem opera, 18/09/2026):
a folha manda em quem existe, está ativo, quando foi admitido e onde está
lotado. Ela NÃO sabe dizer quem é rodoviário e quem é manobrista — as funções
ativas são MOT CARRETEIRO (82), MOTORISTA TRUCK (17), MOTORISTA DE ENT (2) e
MOTORISTA BITREM (1), nenhuma de manobra —, e como o tipo decide quanto a
pessoa recebe, ele é decisão registrada na tela. O CÓRTEX só SUGERE, pela
operação: quem tem viagem na programação do período é rodoviário (73 dos 83).

COBERTURA MEDIDA sobre os 83 motoristas CLT ativos, para ninguém se assustar
com buraco que já existia: programação 73 (88%), GR 69 (83%), Gobrax 56 (67%).
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import datetime

from api import db as erp
from api import pglocal

log = logging.getLogger("cortex.premiacao.identidade")

ESQUEMA: str | None = None          # os testes trocam por um schema descartável

#: A base de motoristas da folha é a MESMA da tela de CNH: ativo nas DUAS views
#: e função de motorista. A lição está em `api/queries_folha.py`: as views
#: discordam sobre quem está ativo, e usar só `vwcgs_colaboradores` inflava a
#: base de 104 para 294.
FOLHA_SQL = """
SELECT c.cpfcnpj              AS cpf,
       c.nomecompletofunc     AS nome,
       c.chapafunc            AS chapa,
       UPPER(c.descfuncao)    AS funcao,
       UPPER(f.descarea)      AS area,
       TO_CHAR(c.dtadmfunc, 'YYYY-MM') AS admissao
FROM vwcgs_colaboradores c
JOIN vw_funcionarios f ON f.codintfunc = c.codintfunc
WHERE f.situacaofunc = 'A' AND c.situacaofunc = 'A'
  AND c.codigoempresa = :emp
  AND (UPPER(c.descfuncao) LIKE 'MOT%' OR UPPER(c.descfuncao) LIKE '%CARRETEIR%')
"""

#: Quem rodou no período — a SUGESTÃO de tipo, e o código de cadastro do ERP.
#: `programacaoembarque.motorista` É o CPF (medido: 26.795 de 26.795 com 11
#: dígitos), e é ele que liga a folha à operação.
OPERACAO_SQL = """
SELECT regexp_replace(p.motorista, '[^0-9]', '', 'g') AS cpf,
       count(*)                                        AS viagens,
       max(p.dtsaida)::date::text                      AS ultima
FROM programacaoembarque p
WHERE p.dtsaida >= current_date - %(dias)s
  AND p.dtcancelamento IS NULL
  AND p.motorista IS NOT NULL
GROUP BY 1
"""

#: A lotação da folha → a filial da premiação. Medido em 18/09/2026:
#: MOT SBC 33 · MOT CRUZEIRO 25 · MOT MATRIZ 16 · MOT JOINVILLE 12 ·
#: MOT AUDI 4 · MOT POUSO ALEGRE 2, mais um punhado em áreas administrativas.
#:
#: O de-para é por PALAVRA e não por igualdade: "MOT SBC", "SBC" e "SBC (CD)"
#: são a mesma filial, e a folha escreve as três. O que não casar fica com a
#: lotação CRUA em vez de virar uma filial inventada — filial errada paga o
#: valor errado, e é melhor aparecer em branco na tela pedindo decisão.
FILIAIS = (
    ("MATRIZ", "MTZ"), ("PIRAQUARA", "MTZ"),
    ("JOINVILLE", "JOI"), ("JOI", "JOI"),
    ("SBC", "SBC"), ("SAO BERNARDO", "SBC"), ("BERNARDO", "SBC"),
    ("CRUZEIRO", "CRZ"), ("CRZ", "CRZ"),
    ("POUSO ALEGRE", "PSA"), ("PSA", "PSA"),
)

DIAS_SUGESTAO = 90


def cpf(valor) -> str:
    """Os 11 dígitos finais — a chave que atravessa folha, ERP e GR.

    O GR grava o CPF com zeros à esquerda (14 dígitos). Cortar pelos ÚLTIMOS 11
    resolve os dois formatos e não inventa nada: o que tiver menos de 11
    dígitos não é CPF e volta vazio, em vez de casar com quem tem o mesmo final.
    """
    so = "".join(ch for ch in str(valor or "") if ch.isdigit())
    return so[-11:] if len(so) >= 11 else ""


def nome_chave(valor) -> str:
    """Nome sem acento, em maiúsculas, espaços colapsados — e sem o prefixo
    numérico que a Gobrax põe em alguns cadastros ("3781 - FULANO")."""
    texto = str(valor or "")
    if " - " in texto[:12]:
        prefixo, _, resto = texto.partition(" - ")
        if prefixo.strip().isdigit():
            texto = resto
    sem = unicodedata.normalize("NFD", texto)
    sem = "".join(c for c in sem if unicodedata.category(c) != "Mn")
    return " ".join(sem.upper().split())


def filial_da_area(area: str | None) -> str | None:
    """A filial da premiação a partir da lotação da folha, ou None."""
    texto = nome_chave(area)
    for palavra, sigla in FILIAIS:
        if palavra in texto:
            return sigla
    return None


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _esq():
    return ESQUEMA


def listar(ativos: bool = True) -> list[dict]:
    """O cadastro, sem CPF: a tela fala por `cadastro_codigo`."""
    sql = ("SELECT cpf, nome, cadastro_codigo, chapa, tipo, tipo_origem, filial,"
           " filial_origem, admissao, funcao, ativo, gobrax_driver_id,"
           " sincronizado_em, atualizado_em, atualizado_por"
           " FROM prm_motorista")
    if ativos:
        sql += " WHERE ativo = 1"
    sql += " ORDER BY nome"
    return [dict(r) for r in pglocal.query(sql, esquema=_esq())]


def por_cpf() -> dict[str, dict]:
    return {r["cpf"]: r for r in listar(ativos=False)}


def sugerir_tipo(viagens: int) -> str:
    """Quem rodou é rodoviário; quem não rodou é manobrista.

    É SUGESTÃO, e a tela diz isso: um rodoviário que passou o período inteiro
    afastado cai aqui como manobrista, e é por isso que a decisão final é de
    quem opera (`tipo_origem='manual'`), nunca desta função.
    """
    return "RODOVIARIO" if viagens > 0 else "MANOBRA"


def _operacao(dias: int = DIAS_SUGESTAO) -> dict[str, dict]:
    try:
        linhas = erp.query(OPERACAO_SQL, {"dias": int(dias)})
    except Exception as exc:  # noqa: BLE001
        # O ERP fora do ar não pode impedir a sincronização da FOLHA: sem a
        # operação a gente só não sugere tipo para quem é novo.
        log.warning("premiacao: operacao indisponivel (%s)", type(exc).__name__)
        return {}
    return {cpf(r["cpf"]): dict(r) for r in linhas if cpf(r["cpf"])}


def _cadastros_erp(cpfs: list[str]) -> dict[str, str]:
    """O código do cadastro do ERP de cada CPF — é ele que sai em tela e rota.

    Vem do PRÓPRIO CADASTRO (`cadastro.codigo`), e não das ocorrências: buscar
    pelas ocorrências só acha quem teve alguma: 62 dos 83 na primeira medição
    (18/09/2026), e quem nunca teve ocorrência ficava sem código — sem código
    a tela não tem como falar daquela pessoa, e ela sumiria da premiação
    justamente por ter se comportado bem.
    """
    if not cpfs:
        return {}
    try:
        linhas = erp.query(
            "SELECT DISTINCT regexp_replace(codigo,'[^0-9]','','g') AS cpf,"
            "       codigo"
            "  FROM cadastro"
            " WHERE regexp_replace(codigo,'[^0-9]','','g') = ANY(%(cpfs)s)",
            {"cpfs": cpfs})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: cadastro do ERP indisponivel (%s)", type(exc).__name__)
        return {}
    return {cpf(r["cpf"]): str(r["codigo"]) for r in linhas if cpf(r["cpf"])}


def sincronizar(autor: str = "sistema", dias: int = DIAS_SUGESTAO) -> dict:
    """Traz a folha para o cadastro. A folha manda; o que é da casa fica.

    O que a folha atualiza SEMPRE: nome, chapa, função, admissão, situação e a
    filial (enquanto ninguém a tiver trocado à mão). O que ela NUNCA toca:
    `tipo` decidido à mão e `filial` trocada à mão — a mesma regra que protege
    a classificação de ocorrências de ser desfeita por uma sincronização.

    Quem sumiu da folha (desligado) fica com `ativo = 0` e NÃO é apagado: o
    histórico de premiação dele continua tendo dono.
    """
    inicio = _agora()
    carga = pglocal.um(
        "INSERT INTO prm_motorista_carga(iniciado_em, fonte) VALUES(%s,'folha')"
        " RETURNING id", (inicio,), esquema=_esq())
    carga_id = (carga or {}).get("id")

    def _fecha(**campos):
        sets = ", ".join(f"{k} = %({k})s" for k in campos)
        pglocal.executar(
            f"UPDATE prm_motorista_carga SET terminado_em = %(fim)s, {sets}"
            " WHERE id = %(id)s",
            {**campos, "fim": _agora(), "id": carga_id}, esquema=_esq())

    try:
        from api import queries_folha
        linhas = queries_folha._q(FOLHA_SQL, {"emp": queries_folha.EMPRESA})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: folha indisponivel (%s)", type(exc).__name__)
        _fecha(erro=f"folha indisponivel ({type(exc).__name__})")
        raise

    vistos = {}
    for r in linhas:
        chave = cpf(r.get("cpf"))
        if chave:
            vistos[chave] = r

    operacao = _operacao(dias)
    atual = por_cpf()
    codigos = _cadastros_erp(list(vistos))
    novos = atualizados = 0

    for chave, r in vistos.items():
        anterior = atual.get(chave)
        filial = filial_da_area(r.get("area"))
        viagens = int((operacao.get(chave) or {}).get("viagens") or 0)
        campos = {
            "cpf": chave,
            "nome": (r.get("nome") or "").strip(),
            "chapa": str(r.get("chapa") or "").strip() or None,
            "funcao": (r.get("funcao") or "").strip() or None,
            "admissao": r.get("admissao"),
            "cadastro_codigo": codigos.get(chave) or (anterior or {}).get("cadastro_codigo"),
            "sincronizado_em": _agora(),
        }
        if anterior is None:
            pglocal.executar(
                "INSERT INTO prm_motorista(cpf, nome, chapa, funcao, admissao,"
                " cadastro_codigo, filial, filial_origem, tipo, tipo_origem,"
                " ativo, sincronizado_em)"
                " VALUES(%(cpf)s,%(nome)s,%(chapa)s,%(funcao)s,%(admissao)s,"
                " %(cadastro_codigo)s,%(filial)s,'folha',%(tipo)s,'sugerido',1,"
                " %(sincronizado_em)s)",
                {**campos, "filial": filial, "tipo": sugerir_tipo(viagens)},
                esquema=_esq())
            novos += 1
            continue
        # A filial só vem da folha enquanto ninguém a trocou à mão.
        if (anterior.get("filial_origem") or "folha") == "folha" and filial:
            campos["filial"] = filial
            extra = ", filial = %(filial)s"
        else:
            extra = ""
        # O tipo SUGERIDO acompanha a operação; o manual fica como está.
        if (anterior.get("tipo_origem") or "sugerido") == "sugerido":
            campos["tipo"] = sugerir_tipo(viagens)
            extra += ", tipo = %(tipo)s"
        pglocal.executar(
            "UPDATE prm_motorista SET nome = %(nome)s, chapa = %(chapa)s,"
            " funcao = %(funcao)s, admissao = %(admissao)s,"
            " cadastro_codigo = %(cadastro_codigo)s, ativo = 1,"
            " sincronizado_em = %(sincronizado_em)s" + extra
            + " WHERE cpf = %(cpf)s", campos, esquema=_esq())
        atualizados += 1

    fora = [c for c in atual if c not in vistos and int(atual[c].get("ativo") or 0) == 1]
    for chave in fora:
        pglocal.executar(
            "UPDATE prm_motorista SET ativo = 0, sincronizado_em = %s WHERE cpf = %s",
            (_agora(), chave), esquema=_esq())

    _fecha(lidos=len(vistos), novos=novos, atualizados=atualizados,
           desligados=len(fora))
    log.info("premiacao: cadastro sincronizado (%s lidos, %s novos, %s desligados)",
             len(vistos), novos, len(fora))
    return {"lidos": len(vistos), "novos": novos, "atualizados": atualizados,
            "desligados": len(fora), "autor": autor}


def decidir(cadastro_codigo: str, autor: str, tipo: str | None = None,
            filial: str | None = None) -> dict:
    """A decisão de quem opera sobre tipo e filial. Vira `origem='manual'`.

    Recebe o CÓDIGO DO CADASTRO, nunca o CPF: é o que a tela tem e o que pode
    trafegar. Quem não está no cadastro é recusado com o motivo.
    """
    codigo = str(cadastro_codigo or "").strip()
    if not codigo:
        raise ValueError("Informe o motorista.")
    if tipo is not None and tipo not in ("RODOVIARIO", "MANOBRA"):
        raise ValueError("Tipo inválido: use RODOVIARIO ou MANOBRA.")
    if not autor:
        raise ValueError("Informe quem está decidindo (trilha de auditoria).")
    alvo = pglocal.um("SELECT cpf FROM prm_motorista WHERE cadastro_codigo = %s",
                      (codigo,), esquema=_esq())
    if not alvo:
        raise ValueError("Motorista fora do cadastro da premiação.")
    campos, sets = {"cpf": alvo["cpf"], "quando": _agora(), "quem": autor}, []
    if tipo is not None:
        campos["tipo"] = tipo
        sets += ["tipo = %(tipo)s", "tipo_origem = 'manual'"]
    if filial is not None:
        campos["filial"] = (filial or "").strip().upper() or None
        sets += ["filial = %(filial)s", "filial_origem = 'manual'"]
    if not sets:
        raise ValueError("Nada a mudar.")
    pglocal.executar(
        "UPDATE prm_motorista SET " + ", ".join(sets)
        + ", atualizado_em = %(quando)s, atualizado_por = %(quem)s"
        " WHERE cpf = %(cpf)s", campos, esquema=_esq())
    return {"cadastro_codigo": codigo, "tipo": tipo, "filial": campos.get("filial")}


def cpf_do_cadastro(cadastro_codigo: str) -> str | None:
    """A ponte código -> CPF, para quem escreve numa tabela que chaveia por CPF.

    A TELA NUNCA MANDA CPF: ela fala por código do cadastro, que é o que pode
    trafegar. Quem grava (o ajuste do prêmio, por exemplo) faz a ponte AQUI e
    não devolve a chave no que responde.
    """
    r = pglocal.um("SELECT cpf FROM prm_motorista WHERE cadastro_codigo = %s",
                   (str(cadastro_codigo or "").strip(),), esquema=_esq())
    return r["cpf"] if r else None


def estado() -> dict:
    """O que a Saúde e a tela precisam saber sobre o cadastro."""
    total = pglocal.um(
        "SELECT count(*) AS n,"
        " sum(CASE WHEN ativo = 1 THEN 1 ELSE 0 END) AS ativos,"
        " sum(CASE WHEN ativo = 1 AND tipo = 'MANOBRA' THEN 1 ELSE 0 END) AS manobra,"
        " sum(CASE WHEN ativo = 1 AND tipo_origem = 'manual' THEN 1 ELSE 0 END) AS decididos,"
        " sum(CASE WHEN ativo = 1 AND filial IS NULL THEN 1 ELSE 0 END) AS sem_filial,"
        " max(sincronizado_em) AS ultima"
        " FROM prm_motorista", esquema=_esq()) or {}
    carga = pglocal.um(
        "SELECT iniciado_em, terminado_em, lidos, novos, atualizados, desligados, erro"
        " FROM prm_motorista_carga ORDER BY id DESC LIMIT 1", esquema=_esq())
    return {"total": int(total.get("n") or 0),
            "ativos": int(total.get("ativos") or 0),
            "manobra": int(total.get("manobra") or 0),
            "decididos": int(total.get("decididos") or 0),
            "sem_filial": int(total.get("sem_filial") or 0),
            "ultima_sincronizacao": total.get("ultima"),
            "ultima_carga": dict(carga) if carga else None}
