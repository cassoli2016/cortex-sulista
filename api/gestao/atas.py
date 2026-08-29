"""Atas de reunião — o registro do que foi decidido, e por quem.

DUAS SEPARAÇÕES CARREGAM O VALOR DESTE MÓDULO:

1. **Pauta, discussão e decisões são campos DIFERENTES.** É a diferença entre
   ata e transcrição. O defeito clássico é o texto corrido em que ninguém
   consegue apontar o que foi combinado — três meses depois duas pessoas leem a
   mesma ata e discordam sobre se aquilo era uma decisão ou uma cogitação.
   Campos separados obrigam quem escreve a decidir em qual balde a frase cai,
   que é o trabalho útil de fazer uma ata.

2. **Convocado ≠ presente.** `ges_participantes.presente` guarda os dois, e a
   ausência em reunião de decisão é informação: quem faltou não pode ser
   cobrado do mesmo jeito, e quem falta sempre é um problema de governança que
   só aparece quando alguém conta.

RASCUNHO × PUBLICADA existe porque ata publicada vira documento que outras
pessoas citam. Publicar é um ato, com data e autor — não pode ser o efeito
colateral de abrir o formulário. Rascunho é editável à vontade; publicada
também é editável (erro se corrige), mas a edição fica na auditoria.

O `codigo` (ATA-2026-007) é gerado dentro da MESMA transação do INSERT, com
UNIQUE (ano, sequencia) como rede: no volume real — poucas atas por mês — a
corrida entre dois cadastros simultâneos é improvável, e se acontecer o banco
recusa em vez de gravar duas ATA-2026-007.
"""
from __future__ import annotations

from .. import pglocal
from .comum import (STATUS_ATA, TIPOS_REUNIAO, TITULO_MAX, DadoInvalido, _esq,
                    agora, data_br, escolha, init_db, iso, pessoa, texto)

_COLUNAS = """
    r.id, r.ano, r.sequencia, r.codigo, r.titulo, r.tipo, r.area, r.data,
    r.hora_inicio, r.hora_fim, r.local, r.pauta, r.discussao, r.decisoes,
    r.observacoes, r.status,
    r.criado_por, r.criado_em, r.alterado_por, r.alterado_em,
    (SELECT count(*) FROM ges_participantes p WHERE p.reuniao_id = r.id)::int
        AS participantes,
    (SELECT count(*) FROM ges_participantes p
      WHERE p.reuniao_id = r.id AND p.presente = 1)::int AS presentes,
    (SELECT count(*) FROM ges_acoes a WHERE a.reuniao_id = r.id)::int
        AS acoes,
    (SELECT count(*) FROM ges_acoes a
      WHERE a.reuniao_id = r.id AND a.status IN ('aberta','em_andamento'))::int
        AS acoes_abertas,
    (SELECT count(*) FROM ges_acoes a
      WHERE a.reuniao_id = r.id AND a.status IN ('aberta','em_andamento')
        AND a.prazo < current_date)::int AS acoes_atrasadas
"""


def _hora(valor, rotulo: str) -> str:
    """HH:MM ou vazio. Recusa 25:00 — o `<input type=time>` não manda isso,
    mas a rota aceita o que mandarem nela."""
    s = ("" if valor is None else str(valor)).strip()
    if not s:
        return ""
    partes = s.split(":")
    if len(partes) < 2 or not all(x.isdigit() for x in partes[:2]):
        raise DadoInvalido(f"{rotulo} deve estar no formato HH:MM.")
    h, m = int(partes[0]), int(partes[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise DadoInvalido(f"{rotulo} não existe no relógio.")
    return f"{h:02d}:{m:02d}"


def validar(dados: dict) -> dict:
    d = {
        "titulo": texto(dados.get("titulo"), "o título da reunião",
                        maximo=TITULO_MAX, obrigatorio=True),
        "tipo": escolha(dados.get("tipo"), TIPOS_REUNIAO, "O tipo", "outra"),
        "area": texto(dados.get("area"), "a área", maximo=80),
        "local": texto(dados.get("local"), "o local", maximo=200),
        "pauta": texto(dados.get("pauta"), "a pauta"),
        "discussao": texto(dados.get("discussao"), "a discussão"),
        "decisoes": texto(dados.get("decisoes"), "as decisões"),
        "observacoes": texto(dados.get("observacoes"), "as observações"),
        "status": escolha(dados.get("status"), STATUS_ATA, "O status",
                          "rascunho"),
        "hora_inicio": _hora(dados.get("hora_inicio"), "A hora de início"),
        "hora_fim": _hora(dados.get("hora_fim"), "A hora de término"),
    }
    d["data"] = data_br(dados.get("data"), "a data da reunião",
                        obrigatorio=True)
    if d["hora_inicio"] and d["hora_fim"] and d["hora_fim"] < d["hora_inicio"]:
        raise DadoInvalido("A reunião não pode terminar antes de começar.")
    return d


def _validar_participantes(lista, esquema: str | None) -> list[dict]:
    """Deduplica pelo par resolvido, não pelo que foi digitado.

    Mesma lição do `separar()` do WhatsApp: deduplicar pelo texto cru deixava a
    mesma pessoa entrar duas vezes — uma escolhida no seletor e outra digitada
    à mão — e o contador de presentes passava a medir digitação.
    """
    if lista is None:
        return []
    if not isinstance(lista, list):
        raise DadoInvalido("Participantes devem vir como lista.")
    vistos, saida = set(), []
    for item in lista:
        if isinstance(item, str):
            item = {"nome": item}
        if not isinstance(item, dict):
            raise DadoInvalido("Participante inválido.")
        uid, nome = pessoa(item.get("usuario_id"), item.get("nome"),
                           "Participante", esquema)
        chave = f"u{uid}" if uid else f"n{nome.casefold()}"
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append({
            "usuario_id": uid, "nome": nome,
            "papel": texto(item.get("papel"), "o papel", maximo=80),
            # ausente por omissão seria errado: quem monta a lista está
            # listando quem esteve lá, e teria de marcar todo mundo.
            "presente": 0 if str(item.get("presente", 1)) in ("0", "False",
                                                              "false") else 1,
        })
    return saida


def _proximo_codigo(cur, ano: int) -> tuple[int, str]:
    cur.execute("SELECT coalesce(max(sequencia),0)+1 AS s "
                "FROM ges_reunioes WHERE ano=%s", (ano,))
    seq = cur.fetchone()["s"]
    return seq, f"ATA-{ano}-{seq:03d}"


def listar(esquema: str | None = None, *, status: str | None = None,
           tipo: str | None = None, area: str | None = None,
           de=None, ate=None, busca: str = "", limite: int = 300) -> list[dict]:
    onde, p = ["1=1"], {}
    if status:
        onde.append("r.status = %(status)s")
        p["status"] = escolha(status, STATUS_ATA, "O status")
    if tipo:
        onde.append("r.tipo = %(tipo)s")
        p["tipo"] = escolha(tipo, TIPOS_REUNIAO, "O tipo")
    if area:
        onde.append("r.area = %(area)s")
        p["area"] = area
    if de:
        onde.append("r.data >= %(de)s")
        p["de"] = data_br(de, "a data inicial")
    if ate:
        onde.append("r.data <= %(ate)s")
        p["ate"] = data_br(ate, "a data final")
    if (busca or "").strip():
        onde.append("(r.titulo ILIKE %(q)s OR r.codigo ILIKE %(q)s "
                    "OR r.pauta ILIKE %(q)s OR r.decisoes ILIKE %(q)s)")
        p["q"] = f"%{busca.strip()}%"
    sql = (f"SELECT {_COLUNAS} FROM ges_reunioes r "
           f"WHERE {' AND '.join(onde)} "
           f"ORDER BY r.data DESC, r.id DESC LIMIT {int(limite)}")
    return [iso(r, "data") for r in pglocal.query(sql, p, esquema=_esq(esquema))]


def contar(esquema: str | None = None, **filtros) -> int:
    filtros.pop("limite", None)
    return len(listar(esquema, limite=100000, **filtros))


def participantes(reuniao_id: int, esquema: str | None = None) -> list[dict]:
    return pglocal.query(
        "SELECT p.id, p.usuario_id, "
        "       coalesce(u.nome, p.nome) AS nome, p.papel, p.presente, "
        "       u.email, coalesce(u.cargo,'') AS cargo "
        "FROM ges_participantes p LEFT JOIN usuarios u ON u.id = p.usuario_id "
        "WHERE p.reuniao_id=%s ORDER BY p.presente DESC, nome",
        (int(reuniao_id),), esquema=_esq(esquema))


def obter(reuniao_id: int, esquema: str | None = None) -> dict | None:
    r = pglocal.um(f"SELECT {_COLUNAS} FROM ges_reunioes r WHERE r.id=%s",
                   (int(reuniao_id),), esquema=_esq(esquema))
    if not r:
        return None
    from . import acoes as _acoes
    r["lista_participantes"] = participantes(reuniao_id, esquema)
    r["lista_acoes"] = _acoes.listar(esquema, reuniao_id=reuniao_id)
    return iso(r, "data")


def gravar(dados: dict, *, usuario: str = "", reuniao_id: int | None = None,
           esquema: str | None = None) -> dict:
    init_db(esquema)
    d = validar(dados)
    parts = _validar_participantes(dados.get("participantes"), esquema)
    ts = agora()
    with pglocal.get_conn(_esq(esquema)) as cx:
        cur = cx.cursor()
        if reuniao_id:
            cur.execute("SELECT id FROM ges_reunioes WHERE id=%s",
                        (int(reuniao_id),))
            if not cur.fetchone():
                raise DadoInvalido("Esta ata não existe mais.")
            cur.execute("""
                UPDATE ges_reunioes SET
                  titulo=%(titulo)s, tipo=%(tipo)s, area=%(area)s,
                  data=%(data)s, hora_inicio=%(hora_inicio)s,
                  hora_fim=%(hora_fim)s, local=%(local)s, pauta=%(pauta)s,
                  discussao=%(discussao)s, decisoes=%(decisoes)s,
                  observacoes=%(observacoes)s, status=%(status)s,
                  alterado_por=%(quem)s, alterado_em=%(ts)s
                WHERE id=%(id)s
            """, {**d, "id": int(reuniao_id), "quem": usuario, "ts": ts})
            novo_id = int(reuniao_id)
            # Substitui a lista inteira SÓ quando ela veio no payload. Chave
            # ausente = "não mexi"; lista vazia = "não havia ninguém". Sem essa
            # distinção, salvar a ata pela tela de decisões apagaria os
            # participantes — o mesmo sentinela do cadastro de usuário.
            if dados.get("participantes") is not None:
                cur.execute("DELETE FROM ges_participantes WHERE reuniao_id=%s",
                            (novo_id,))
                _inserir_participantes(cur, novo_id, parts)
        else:
            ano = d["data"].year
            seq, codigo = _proximo_codigo(cur, ano)
            cur.execute("""
                INSERT INTO ges_reunioes
                  (ano, sequencia, codigo, titulo, tipo, area, data,
                   hora_inicio, hora_fim, local, pauta, discussao, decisoes,
                   observacoes, status, criado_por, criado_em,
                   alterado_por, alterado_em)
                VALUES
                  (%(ano)s, %(seq)s, %(codigo)s, %(titulo)s, %(tipo)s,
                   %(area)s, %(data)s, %(hora_inicio)s, %(hora_fim)s,
                   %(local)s, %(pauta)s, %(discussao)s, %(decisoes)s,
                   %(observacoes)s, %(status)s, %(quem)s, %(ts)s,
                   %(quem)s, %(ts)s)
                RETURNING id
            """, {**d, "ano": ano, "seq": seq, "codigo": codigo,
                  "quem": usuario, "ts": ts})
            novo_id = cur.fetchone()["id"]
            _inserir_participantes(cur, novo_id, parts)
        cx.commit()
    return obter(novo_id, esquema)


def _inserir_participantes(cur, reuniao_id: int, parts: list[dict]) -> None:
    for p in parts:
        cur.execute(
            "INSERT INTO ges_participantes"
            "(reuniao_id, usuario_id, nome, papel, presente) "
            "VALUES (%s,%s,%s,%s,%s)",
            (reuniao_id, p["usuario_id"], p["nome"], p["papel"], p["presente"]))


def excluir(reuniao_id: int, esquema: str | None = None) -> dict | None:
    """As AÇÕES SOBREVIVEM (ON DELETE SET NULL no schema) — o compromisso
    assumido não deixa de existir porque alguém arrumou o registro da reunião.
    O retorno diz quantas ficaram órfãs, para a tela poder avisar antes."""
    r = obter(reuniao_id, esquema)
    if not r:
        return None
    pglocal.executar("DELETE FROM ges_reunioes WHERE id=%s",
                     (int(reuniao_id),), esquema=_esq(esquema))
    return r
