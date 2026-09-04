# -*- coding: utf-8 -*-
"""Avaliação de Desempenho — a matriz nine box.

Duas notas de 1 a 3, dadas pelo GESTOR: desempenho (o que a pessoa entregou) e
potencial (o que ela consegue entregar num papel maior). O cruzamento das duas
dá nove caixas, e cada caixa tem um nome e uma conduta — é a conduta que faz a
ferramenta valer alguma coisa; sem ela a matriz é um gráfico bonito onde
ninguém decide nada.

AS DUAS NOTAS SÃO DO GESTOR, e isso é decisão de quem opera. A alternativa
seria calcular o desempenho dos indicadores que o CÓRTEX já tem — km/l, multa,
jornada, premiação. Ela foi recusada por um motivo simples: esses indicadores
só existem para MOTORISTA. Metade da casa (administrativo, oficina, comercial)
ficaria sem nota, e um número calculado ao lado de um número opinado, na mesma
matriz, sugere uma objetividade que o dado não sustenta.

A HIERARQUIA É NOSSA, PORQUE O ERP NÃO A TEM. `vw_funcionarios` traz nome,
cargo, área, seção, admissão e salário — e nenhum campo de "a quem responde".
Sem inventar essa relação não existe "cada gestor vê a sua equipe". Então o RH
mapeia usuário → ÁREA ou SEÇÃO (`des_gestor`), que é como a folha já organiza
as pessoas. Mapa vazio significa VER NINGUÉM, nunca ver todos: abrir a casa
inteira por omissão de cadastro é o tipo de defeito que só se descobre depois.

QUEM VÊ TUDO tem a permissão `desrh` — tela sem menu, como o `dreexc`. Ela
libera a matriz inteira, a administração dos ciclos e o mapa de gestores. Não
é "admin": RH não é TI, e quem administra o ciclo não deveria precisar de
acesso a servidor para isso.

O QUE NÃO TEM AVALIAÇÃO NÃO É CAIXA 1. Pessoa não avaliada fica FORA da
matriz e é contada à parte, sempre — "avaliados 12 de 47". Zero que é ausência
de lançamento não é desempenho, e numa avaliação de gente essa confusão tem
nome e sobrenome.

O QUE SAI DA FOLHA, E O QUE NÃO SAI. `queries_folha` entrega agregados; este
módulo é a mesma exceção deliberada da CNH e das férias — precisa de NOME,
chapa, cargo e área, porque avaliar alguém sem saber quem é não existe. O que
continua fora: CPF, salário, dado bancário e data de nascimento. E o snapshot
do Copiloto leva só a CONTAGEM por caixa: uma matriz de desempenho com nomes
dentro de um chat é exatamente o que a regra de PII da casa existe para
impedir.

CICLO FECHADO NÃO ACEITA ESCRITA. A avaliação é uma foto de um momento; se ela
puder ser reescrita depois que as decisões foram tomadas, ela deixa de servir
para explicar por que foram tomadas.
"""
from __future__ import annotations

import logging

from . import pglocal
from .queries_folha import EMPRESA, _q

log = logging.getLogger("cortex.desempenho")

#: Esquema do banco local, injetado pelos testes (fixture `esquema_pg`).
ESQUEMA: str | None = None

#: Tamanho mínimo da justificativa. Nota sem porquê não sustenta conversa de
#: carreira: em seis meses ninguém lembra o que "bom" queria dizer.
JUSTIFICATIVA_MIN = 15

NOTAS = (1, 2, 3)
ROTULO_NOTA = {1: "baixo", 2: "médio", 3: "alto"}

#: As nove caixas. O NÚMERO é `(potencial-1)*3 + desempenho`, então a caixa 1
#: é o canto de baixo à esquerda e a 9 o de cima à direita — a leitura natural
#: da matriz desenhada.
#:
#: Cada uma traz a CONDUTA, e é isso que separa a ferramenta do enfeite: uma
#: matriz que classifica sem dizer o que fazer devolve a decisão inteira para
#: quem já não sabia o que fazer.
CAIXAS = {
    1: {"nome": "Insuficiente", "cor": "ruim",
        "conduta": "Plano de ação com prazo. Se não virar no prazo, é conversa "
                   "de desligamento — adiar isso custa mais para a pessoa do "
                   "que para a empresa."},
    2: {"nome": "Eficaz", "cor": "atencao",
        "conduta": "Entrega o combinado e é onde vai ficar. Manter, reconhecer "
                   "pelo que faz e não prometer carreira que não virá."},
    3: {"nome": "Especialista", "cor": "bom",
        "conduta": "Entrega muito no que faz e não quer (ou não consegue) sair "
                   "dali. Reter pelo domínio técnico: é quem forma os outros."},
    4: {"nome": "Em desenvolvimento", "cor": "atencao",
        "conduta": "Tem mais a dar do que está dando. Descobrir o que trava — "
                   "quase sempre é o posto, o gestor ou a clareza do que se "
                   "espera, não a pessoa."},
    5: {"nome": "Mantenedor", "cor": "atencao",
        "conduta": "O centro da casa, e é onde mora a maioria. Desenvolver com "
                   "meta concreta: daqui saem os 6 e os 8 do ano que vem."},
    6: {"nome": "Forte desempenho", "cor": "bom",
        "conduta": "Entrega acima da média e cresce. Dar desafio maior antes "
                   "que alguém de fora dê."},
    7: {"nome": "Enigma", "cor": "atencao",
        "conduta": "Potencial visível e entrega abaixo. Vale um movimento — "
                   "outro posto, outro gestor — antes de concluir qualquer "
                   "coisa sobre a pessoa."},
    8: {"nome": "Alto potencial", "cor": "bom",
        "conduta": "Prepara para o próximo papel. Precisa de sucessor no posto "
                   "atual antes de subir, ou a promoção abre um buraco."},
    9: {"nome": "Estrela", "cor": "bom",
        "conduta": "Sucessão. Nome que tem de estar num plano escrito, com "
                   "prazo — estrela sem horizonte é a que pede demissão em "
                   "janeiro."},
}


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


def caixa(desempenho: int, potencial: int) -> int:
    """O número da caixa (1 a 9) a partir das duas notas."""
    if desempenho not in NOTAS or potencial not in NOTAS:
        raise ValueError("nota fora da escala 1..3")
    return (potencial - 1) * 3 + desempenho


# ------------------------------------------------------------------ ciclos
def ciclos(esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM des_ciclo ORDER BY inicio DESC, id DESC")
        return [dict(r) for r in cur.fetchall()]


def ciclo_aberto(esquema: str | None = None) -> dict | None:
    """O ciclo em que se avalia agora.

    Estado é CAMPO e não janela de datas: derivar "aberto" de `fim >= hoje`
    faria o ciclo fechar sozinho num domingo, no meio de uma avaliação.
    """
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM des_ciclo WHERE estado = 'aberto' "
                    "ORDER BY inicio DESC LIMIT 1")
        r = cur.fetchone()
        return dict(r) if r else None


def criar_ciclo(nome: str, inicio: str, fim: str, quem: str,
                esquema: str | None = None) -> dict:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("o ciclo precisa de um nome")
    if not inicio or not fim or fim <= inicio:
        raise ValueError("o período do ciclo está invertido ou vazio")
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO des_ciclo (nome, inicio, fim, criado_por) "
            "VALUES (%s,%s,%s,%s) RETURNING *", (nome, inicio, fim, quem))
        r = dict(cur.fetchone())
        conn.commit()
    return r


def mudar_estado(ciclo_id: int, estado: str, quem: str,
                 esquema: str | None = None) -> dict:
    """Abre ou fecha um ciclo.

    UM ABERTO DE CADA VEZ. Dois ciclos abertos fariam a mesma pessoa aparecer
    em duas listas de pendência, e a matriz teria de escolher um sem dizer
    qual — número sem recorte declarado é número sem origem.
    """
    if estado not in ("rascunho", "aberto", "fechado"):
        raise ValueError("estado desconhecido")
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        if estado == "aberto":
            cur.execute("UPDATE des_ciclo SET estado = 'rascunho' "
                        "WHERE estado = 'aberto' AND id <> %s", (ciclo_id,))
        cur.execute(
            "UPDATE des_ciclo SET estado = %s,"
            " fechado_em = CASE WHEN %s = 'fechado' THEN now() ELSE NULL END,"
            " fechado_por = CASE WHEN %s = 'fechado' THEN %s ELSE NULL END "
            "WHERE id = %s RETURNING *",
            (estado, estado, estado, quem, ciclo_id))
        r = cur.fetchone()
        if not r:
            raise ValueError("ciclo não encontrado")
        conn.commit()
    return dict(r)


# ----------------------------------------------------------------- escopo
def escopos(email: str, esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM des_gestor WHERE lower(email) = lower(%s) "
                    "ORDER BY escopo_tipo, escopo_valor", (email,))
        return [dict(r) for r in cur.fetchall()]


def mapa_gestores(esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM des_gestor ORDER BY email, escopo_valor")
        return [dict(r) for r in cur.fetchall()]


def mapear(email: str, escopo_tipo: str, escopo_valor: str, quem: str,
           esquema: str | None = None) -> dict:
    email = (email or "").strip().lower()
    escopo_valor = (escopo_valor or "").strip()
    if not email or not escopo_valor:
        raise ValueError("informe o e-mail do gestor e a área ou seção")
    if escopo_tipo not in ("area", "secao"):
        raise ValueError("escopo tem de ser área ou seção")
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO des_gestor (email, escopo_tipo, escopo_valor, criado_por)"
            " VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (email, escopo_tipo, escopo_valor) DO UPDATE"
            " SET criado_por = EXCLUDED.criado_por RETURNING *",
            (email, escopo_tipo, escopo_valor, quem))
        r = dict(cur.fetchone())
        conn.commit()
    return r


def desmapear(gestor_id: int, esquema: str | None = None) -> None:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM des_gestor WHERE id = %s", (gestor_id,))
        conn.commit()


# ------------------------------------------------------------------ gente
def equipe(email: str, ver_tudo: bool = False,
           esquema: str | None = None) -> dict:
    """As pessoas que este usuário avalia.

    Lê o Globus (Oracle), não o banco da casa: quem trabalha aqui é a folha
    que diz. `situacaofunc = 'A'` é a MESMA definição do Headcount — duas telas
    de RH com noções diferentes de quem trabalha aqui é defeito por construção,
    e a tela de CNH já contou demitido como ativo uma vez.
    """
    if ver_tudo:
        onde, binds = "", {"emp": EMPRESA}
        alcance = "toda a empresa"
    else:
        es = escopos(email, esquema)
        if not es:
            # MAPA VAZIO É VER NINGUÉM. O contrário — cair para "vê todos" —
            # abriria a folha inteira por esquecimento de cadastro, e ninguém
            # descobriria porque a tela ficaria funcionando.
            return {"linhas": [], "alcance": "nenhuma área atribuída",
                    "sem_escopo": True}
        cond, binds = [], {"emp": EMPRESA}
        for i, e in enumerate(es):
            campo = "descarea" if e["escopo_tipo"] == "area" else "descsecao"
            binds["e%d" % i] = e["escopo_valor"].upper()
            cond.append("UPPER(TRIM(%s)) = :e%d" % (campo, i))
        onde = " AND (" + " OR ".join(cond) + ")"
        alcance = ", ".join(e["escopo_valor"] for e in es)
    linhas = _q(
        "SELECT codintfunc, chapafunc, nomefunc, descfuncaocompleta cargo,"
        " descarea area, descsecao secao, dtadmfunc admissao"
        " FROM vw_funcionarios"
        " WHERE codigoempresa = :emp AND situacaofunc = 'A'" + onde +
        " ORDER BY nomefunc", binds)
    # SERIALIZA NO LIMITE DO MÓDULO. `dtadmfunc` chega como `datetime` do
    # Oracle, e o `JSONResponse` da casa estoura DEPOIS do `try/except` da
    # rota, dentro do `render()` — 500 em texto puro, sem pista nenhuma.
    fora = []
    for x in linhas:
        p = dict(x)
        adm = p.get("admissao")
        p["admissao"] = adm.isoformat()[:10] if hasattr(adm, "isoformat") else adm
        p["codintfunc"] = int(p["codintfunc"])
        p["chapafunc"] = str(p.get("chapafunc") or "")
        fora.append(p)
    return {"linhas": fora, "alcance": alcance, "sem_escopo": False}


# ------------------------------------------------------------- avaliações
def avaliacoes(ciclo_id: int, esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM des_avaliacao WHERE ciclo_id = %s "
                    "ORDER BY nome", (ciclo_id,))
        return [dict(r) for r in cur.fetchall()]


def avaliar(ciclo_id: int, pessoa: dict, desempenho: int, potencial: int,
            justificativa: str, quem: str, esquema: str | None = None) -> dict:
    """Grava (ou regrava) a avaliação de uma pessoa no ciclo."""
    if desempenho not in NOTAS or potencial not in NOTAS:
        raise ValueError("as duas notas vão de 1 a 3")
    justificativa = (justificativa or "").strip()
    if len(justificativa) < JUSTIFICATIVA_MIN:
        raise ValueError(
            "escreva a justificativa (ao menos %d caracteres): a nota sem o "
            "porquê não sustenta conversa de carreira" % JUSTIFICATIVA_MIN)
    if not quem:
        raise ValueError("avaliação sem avaliador não entra")
    esq = _esq(esquema)
    with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
        cur.execute("SELECT estado FROM des_ciclo WHERE id = %s", (ciclo_id,))
        r = cur.fetchone()
        if not r:
            raise ValueError("ciclo não encontrado")
        # CICLO FECHADO NÃO ACEITA ESCRITA. A avaliação é a foto que explica as
        # decisões tomadas depois dela; reescrevível, ela deixa de explicar.
        if r["estado"] != "aberto":
            raise ValueError("este ciclo não está aberto para avaliação")
        cur.execute(
            """INSERT INTO des_avaliacao
                 (ciclo_id, codintfunc, chapa, nome, cargo, area, secao,
                  desempenho, potencial, justificativa, avaliador)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (ciclo_id, codintfunc) DO UPDATE SET
                 desempenho = EXCLUDED.desempenho,
                 potencial = EXCLUDED.potencial,
                 justificativa = EXCLUDED.justificativa,
                 avaliador = EXCLUDED.avaliador,
                 atualizado_em = now(),
                 -- a FOTO se refresca ao reavaliar: o cargo pode ter mudado
                 -- entre a primeira nota e a segunda, e a lista mostraria o
                 -- cargo velho ao lado da nota nova
                 chapa = coalesce(EXCLUDED.chapa, des_avaliacao.chapa),
                 nome = coalesce(EXCLUDED.nome, des_avaliacao.nome),
                 cargo = coalesce(EXCLUDED.cargo, des_avaliacao.cargo),
                 area = coalesce(EXCLUDED.area, des_avaliacao.area),
                 secao = coalesce(EXCLUDED.secao, des_avaliacao.secao)
               RETURNING *""",
            (ciclo_id, int(pessoa["codintfunc"]), pessoa.get("chapa"),
             pessoa.get("nome"), pessoa.get("cargo"), pessoa.get("area"),
             pessoa.get("secao"), desempenho, potencial, justificativa, quem))
        fora = dict(cur.fetchone())
        conn.commit()
    return fora


# -------------------------------------------------------------- a matriz
def matriz(ciclo_id: int, email: str, ver_tudo: bool = False,
           esquema: str | None = None) -> dict:
    """A matriz do ciclo, já recortada pelo que este usuário pode ver.

    A COBERTURA VEM JUNTO, sempre. Uma matriz com 12 de 47 avaliados e uma com
    47 de 47 se parecem na tela e dizem coisas muito diferentes; sem o
    denominador, a segunda vira a leitura da primeira.
    """
    time = equipe(email, ver_tudo, esquema)
    pessoas = {int(p["codintfunc"]): p for p in time["linhas"]}
    feitas = {int(a["codintfunc"]): a for a in avaliacoes(ciclo_id, esquema)}

    caixas = {n: [] for n in CAIXAS}
    avaliados, pendentes = [], []
    for cod, p in pessoas.items():
        a = feitas.get(cod)
        pessoa = {"codintfunc": cod, "chapa": p.get("chapafunc"),
                  "nome": p.get("nomefunc"), "cargo": p.get("cargo"),
                  "area": p.get("area"), "secao": p.get("secao")}
        if not a or a["desempenho"] is None or a["potencial"] is None:
            # NÃO AVALIADO NÃO É CAIXA 1. Ele fica FORA da matriz e conta à
            # parte: zero que é ausência de avaliação não é desempenho baixo,
            # e aqui essa confusão tem nome e sobrenome.
            pendentes.append(pessoa)
            continue
        n = caixa(a["desempenho"], a["potencial"])
        caixas[n].append({**pessoa, "desempenho": a["desempenho"],
                          "potencial": a["potencial"],
                          "justificativa": a["justificativa"],
                          "avaliador": a["avaliador"], "caixa": n})
        avaliados.append(pessoa)

    total = len(pessoas)
    return {
        "ciclo_id": ciclo_id,
        "caixas": [{"n": n, **CAIXAS[n], "pessoas": caixas[n],
                    "quantos": len(caixas[n]),
                    "pct": round(100 * len(caixas[n]) / len(avaliados), 1)
                    if avaliados else None}
                   for n in sorted(CAIXAS, reverse=True)],
        "pendentes": pendentes,
        "kpis": {"pessoas": total, "avaliados": len(avaliados),
                 "pendentes": len(pendentes),
                 "cobertura": round(100 * len(avaliados) / total, 1)
                 if total else None},
        "alcance": time["alcance"], "sem_escopo": time.get("sem_escopo", False),
        "fonte": "notas do gestor no ciclo · quadro ativo da folha (Globus)",
    }


#: O que o Copiloto lê. KPIs ESCALARES, sem nome de ninguém — uma matriz de
#: desempenho com nomes num snapshot de chat é exatamente o que a regra de PII
#: da casa existe para impedir.
def snapshot(esquema: str | None = None) -> dict:
    try:
        c = ciclo_aberto(esquema)
        if not c:
            return {"ciclo": None}
        avs = avaliacoes(c["id"], esquema)
        feitas = [a for a in avs
                  if a["desempenho"] is not None and a["potencial"] is not None]
        por = {}
        for a in feitas:
            n = caixa(a["desempenho"], a["potencial"])
            por[CAIXAS[n]["nome"]] = por.get(CAIXAS[n]["nome"], 0) + 1
        return {"ciclo": c["nome"], "avaliados": len(feitas), "por_caixa": por}
    except Exception as exc:  # noqa: BLE001
        log.warning("snapshot de desempenho falhou: %s", type(exc).__name__)
        return {"erro": type(exc).__name__}
