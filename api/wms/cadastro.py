# -*- coding: utf-8 -*-
"""Os cadastros do armazém — tela `wmscad`: armazéns, endereços, depositantes
e produtos.

EDIÇÃO PARCIAL: chave AUSENTE não mexe; chave VAZIA limpa (regra da casa).

O ENDEREÇO SE GERA EM LOTE. Ninguém cadastra 1.200 posições de porta-palete
uma a uma, e um armazém sem endereço não recebe nada — então o cadastro nasce
de uma faixa (ruas A–C, prédios 1–20, níveis 1–5, posições 1–4) e o código
sai sempre no mesmo formato, `A-01-02-03`. Ordenar por código é ordenar pela
rota de separação.
"""
from __future__ import annotations

import re
import string

from . import comum
from .comum import (TIPOS_ENDERECO, TIPOS_GUARDA, ROTULO_TIPO, auditar, ler,
                    limpar, limpar_todas, transacao)
from ..validacao import DadoInvalido, escolha, inteiro, quantidade_br, texto

LOTE_MAX = 3000          # endereços por geração — o maior armazém da casa cabe em poucas


def _uf(v) -> str:
    s = re.sub(r"[^A-Z]", "", str(v or "").upper())
    if s and len(s) != 2:
        raise DadoInvalido("A UF tem duas letras.")
    return s


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "sim", "s", "on")


# ═══════════════════════════════════════════════════════════════ armazéns
ARMAZENS_SQL = """
SELECT a.id, a.codigo, a.nome, a.filial_erp, a.cidade, a.uf, a.ativo, a.criado_em,
       count(e.id) FILTER (WHERE e.ativo) AS enderecos,
       count(e.id) FILTER (WHERE e.ativo AND e.tipo IN ('porta_palete','picking','blocado')) AS enderecos_guarda,
       count(e.id) FILTER (WHERE e.ativo AND e.tipo = 'doca') AS docas,
       count(e.id) FILTER (WHERE e.ativo AND e.tipo = 'expedicao') AS areas_expedicao,
       count(e.id) FILTER (WHERE e.ativo AND e.tipo = 'avaria') AS areas_avaria
  FROM wms_armazem a
  LEFT JOIN wms_endereco e ON e.armazem_id = a.id
 GROUP BY a.id
 ORDER BY a.ativo DESC, a.codigo
"""


def listar_armazens(esquema: str | None = None) -> list[dict]:
    return limpar_todas(ler(ARMAZENS_SQL, None, esquema))


def armazem(armazem_id: int, esquema: str | None = None) -> dict:
    for a in listar_armazens(esquema):
        if a["id"] == armazem_id:
            return a
    raise DadoInvalido("Armazém não encontrado.")


def criar_armazem(dados: dict, usuario: str, esquema: str | None = None) -> dict:
    codigo = re.sub(r"[^A-Z0-9]", "", str(dados.get("codigo") or "").upper())
    if not 2 <= len(codigo) <= 10:
        raise DadoInvalido("O código do armazém tem de 2 a 10 letras ou números (ex.: JVE1).")
    nome = texto(dados.get("nome"), "o nome do armazém", maximo=80, obrigatorio=True)
    filial = dados.get("filial_erp")
    filial = None if filial in (None, "") else inteiro(filial, "a filial do ERP", minimo=1, maximo=9999)
    cidade = texto(dados.get("cidade"), "a cidade", maximo=60)
    uf = _uf(dados.get("uf"))
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wms_armazem(codigo, nome, filial_erp, cidade, uf, criado_por)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (codigo, nome, filial, cidade, uf, usuario or ""))
        novo = cur.fetchone()["id"]
        auditar(cur, usuario, "wms_armazem_criar", codigo, nome)
    return armazem(novo, esquema)


def editar_armazem(armazem_id: int, dados: dict, usuario: str,
                   esquema: str | None = None) -> dict:
    sets, vals = [], []
    if "nome" in dados:
        sets.append("nome = %s")
        vals.append(texto(dados["nome"], "o nome do armazém", maximo=80, obrigatorio=True))
    if "cidade" in dados:
        sets.append("cidade = %s")
        vals.append(texto(dados["cidade"], "a cidade", maximo=60))
    if "uf" in dados:
        sets.append("uf = %s")
        vals.append(_uf(dados["uf"]))
    if "filial_erp" in dados:
        f = dados["filial_erp"]
        sets.append("filial_erp = %s")
        vals.append(None if f in (None, "") else inteiro(f, "a filial do ERP", minimo=1, maximo=9999))
    ativo = None
    if "ativo" in dados:
        ativo = _bool(dados["ativo"])
        sets.append("ativo = %s")
        vals.append(ativo)
    if not sets:
        return armazem(armazem_id, esquema)
    with transacao(esquema) as conn, conn.cursor() as cur:
        if ativo is False:
            cur.execute("""SELECT count(*) AS n FROM wms_saldo s
                             JOIN wms_endereco e ON e.id = s.endereco_id
                            WHERE e.armazem_id = %s""", (armazem_id,))
            if cur.fetchone()["n"]:
                raise DadoInvalido("Há mercadoria guardada neste armazém — esvazie antes de inativar.")
        cur.execute(f"UPDATE wms_armazem SET {', '.join(sets)} WHERE id = %s",
                    (*vals, armazem_id))
        if not cur.rowcount:
            raise DadoInvalido("Armazém não encontrado.")
        auditar(cur, usuario, "wms_armazem_editar", str(armazem_id),
                ", ".join(s.split(" ")[0] for s in sets))
    return armazem(armazem_id, esquema)


# ═══════════════════════════════════════════════════════════════ endereços
ENDERECOS_SQL = """
SELECT * FROM (
  SELECT e.id, e.codigo, e.tipo, e.rua, e.capacidade_paletes, e.bloqueado,
         e.motivo_bloqueio, e.bloqueado_em, e.bloqueado_por, e.ativo,
         coalesce(s.itens, 0) AS itens, coalesce(s.qtd, 0) AS qtd,
         coalesce(t.tarefas, 0) AS tarefas_pendentes,
         i.inventario_id,
         CASE WHEN NOT e.ativo THEN 'inativo'
              WHEN e.bloqueado THEN 'bloqueado'
              WHEN coalesce(s.itens, 0) > 0 THEN 'ocupado'
              ELSE 'livre' END AS situacao
    FROM wms_endereco e
    LEFT JOIN (SELECT endereco_id, count(*) AS itens, sum(qtd) AS qtd
                 FROM wms_saldo GROUP BY endereco_id) s ON s.endereco_id = e.id
    LEFT JOIN (SELECT endereco_id, count(*) AS tarefas
                 FROM wms_tarefa WHERE status = 'pendente'
                GROUP BY endereco_id) t ON t.endereco_id = e.id
    LEFT JOIN (SELECT ie.endereco_id, max(ie.inventario_id) AS inventario_id
                 FROM wms_inventario_endereco ie
                 JOIN wms_inventario iv ON iv.id = ie.inventario_id AND iv.status = 'aberto'
                GROUP BY ie.endereco_id) i ON i.endereco_id = e.id
   WHERE e.armazem_id = %(a)s
) x
 WHERE (%(tipo)s::text IS NULL OR x.tipo = %(tipo)s)
   AND (%(situacao)s::text IS NULL OR x.situacao = %(situacao)s)
   AND (%(busca)s::text IS NULL OR x.codigo ILIKE %(busca)s)
 ORDER BY x.codigo
"""

RESUMO_ENDERECOS_SQL = """
SELECT e.tipo,
       count(*) FILTER (WHERE e.ativo) AS ativos,
       count(*) FILTER (WHERE e.ativo AND e.bloqueado) AS bloqueados,
       count(*) FILTER (WHERE e.ativo AND s.endereco_id IS NOT NULL) AS ocupados
  FROM wms_endereco e
  LEFT JOIN (SELECT DISTINCT endereco_id FROM wms_saldo) s ON s.endereco_id = e.id
 WHERE e.armazem_id = %s
 GROUP BY e.tipo
"""


def listar_enderecos(armazem_id: int, *, tipo: str | None = None,
                     situacao: str | None = None, busca: str | None = None,
                     limite: int = 1500, esquema: str | None = None) -> dict:
    if tipo and tipo not in TIPOS_ENDERECO:
        raise DadoInvalido("Tipo de endereço desconhecido.")
    if situacao and situacao not in ("livre", "ocupado", "bloqueado", "inativo"):
        raise DadoInvalido("Situação desconhecida.")
    todos = ler(ENDERECOS_SQL, {"a": armazem_id, "tipo": tipo or None,
                                "situacao": situacao or None,
                                "busca": comum.curinga(busca)}, esquema)
    resumo = {r["tipo"]: {k: int(r[k] or 0) for k in ("ativos", "bloqueados", "ocupados")}
              for r in ler(RESUMO_ENDERECOS_SQL, (armazem_id,), esquema)}
    lim = max(1, min(int(limite), 5000))
    return {"enderecos": limpar_todas(todos[:lim]), "total": len(todos),
            "mostrando": min(len(todos), lim), "resumo": resumo,
            "tipos": [{"chave": t, "rotulo": ROTULO_TIPO[t]} for t in TIPOS_ENDERECO]}


def _codigo_endereco(v) -> str:
    c = re.sub(r"\s+", "", str(v or "").upper())
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,23}", c):
        raise DadoInvalido("O código do endereço usa letras, números e hífen (ex.: A-01-02-03 ou DOCA1).")
    return c


def criar_endereco(armazem_id: int, dados: dict, usuario: str,
                   esquema: str | None = None) -> dict:
    codigo = _codigo_endereco(dados.get("codigo"))
    tipo = escolha(dados.get("tipo"), TIPOS_ENDERECO, "O tipo do endereço")
    cap = dados.get("capacidade_paletes")
    cap = None if cap in (None, "") else inteiro(cap, "a capacidade em paletes", minimo=1, maximo=999)
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM wms_armazem WHERE id = %s AND ativo", (armazem_id,))
        if not cur.fetchone():
            raise DadoInvalido("Armazém não encontrado ou inativo.")
        cur.execute(
            "INSERT INTO wms_endereco(armazem_id, codigo, tipo, rua, capacidade_paletes)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (armazem_id, codigo, tipo, codigo.split("-")[0], cap))
        novo = cur.fetchone()["id"]
        auditar(cur, usuario, "wms_endereco_criar", codigo, tipo)
    return {"id": novo, "codigo": codigo, "tipo": tipo}


def _faixa(dados: dict, de: str, ate: str, rotulo: str, minimo: int, maximo: int) -> list[int]:
    a = inteiro(dados.get(de), f"o {rotulo} inicial", minimo=minimo, maximo=maximo)
    b = inteiro(dados.get(ate), f"o {rotulo} final", minimo=minimo, maximo=maximo, padrao=a)
    if b < a:
        raise DadoInvalido(f"O {rotulo} final é menor que o inicial.")
    return list(range(a, b + 1))


def _ruas(texto_ruas) -> list[str]:
    """'A-C' → A, B, C · 'A,B,F' · '1-3' → 01, 02, 03 · 'M1'."""
    t = re.sub(r"\s+", "", str(texto_ruas or "").upper())
    if not t:
        raise DadoInvalido("Informe as ruas (ex.: A-C, ou A,B,F).")
    out: list[str] = []
    for tok in t.split(","):
        if not tok:
            continue
        m = re.fullmatch(r"([A-Z])-([A-Z])", tok)
        n = re.fullmatch(r"(\d{1,3})-(\d{1,3})", tok)
        if m:
            i, j = string.ascii_uppercase.index(m[1]), string.ascii_uppercase.index(m[2])
            if j < i:
                raise DadoInvalido(f"Faixa de ruas invertida: {tok}.")
            out += list(string.ascii_uppercase[i:j + 1])
        elif n:
            i, j = int(n[1]), int(n[2])
            if j < i:
                raise DadoInvalido(f"Faixa de ruas invertida: {tok}.")
            out += [f"{k:02d}" for k in range(i, j + 1)]
        elif re.fullmatch(r"[A-Z0-9]{1,4}", tok):
            out.append(tok)
        else:
            raise DadoInvalido(f"Rua {tok!r} não se entende — use letras ou números, ex.: A-C.")
    if len(out) > 60:
        raise DadoInvalido("No máximo 60 ruas por geração.")
    return list(dict.fromkeys(out))


def gerar_enderecos(armazem_id: int, dados: dict, usuario: str,
                    esquema: str | None = None) -> dict:
    ruas = _ruas(dados.get("ruas"))
    predios = _faixa(dados, "predio_de", "predio_ate", "prédio", 1, 999)
    niveis = _faixa(dados, "nivel_de", "nivel_ate", "nível", 0, 99)
    posicoes = _faixa(dados, "posicao_de", "posicao_ate", "posição", 1, 99)
    tipo = escolha(dados.get("tipo"), TIPOS_GUARDA, "O tipo dos endereços", padrao="porta_palete")
    cap = dados.get("capacidade_paletes")
    cap = None if cap in (None, "") else inteiro(cap, "a capacidade em paletes", minimo=1, maximo=999)
    total = len(ruas) * len(predios) * len(niveis) * len(posicoes)
    if total > LOTE_MAX:
        raise DadoInvalido(f"Isso gera {total} endereços; o limite por vez é {LOTE_MAX}. "
                           "Divida por rua.")
    codigos = [f"{r}-{p:02d}-{n:02d}-{a:02d}"
               for r in ruas for p in predios for n in niveis for a in posicoes]
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM wms_armazem WHERE id = %s AND ativo", (armazem_id,))
        if not cur.fetchone():
            raise DadoInvalido("Armazém não encontrado ou inativo.")
        cur.execute(
            """INSERT INTO wms_endereco(armazem_id, codigo, tipo, rua, capacidade_paletes)
               SELECT %s, c, %s, split_part(c, '-', 1), %s FROM unnest(%s::text[]) AS c
               ON CONFLICT (armazem_id, codigo) DO NOTHING""",
            (armazem_id, tipo, cap, codigos))
        criados = cur.rowcount
        auditar(cur, usuario, "wms_endereco_gerar", str(armazem_id),
                f"{criados} de {total} ({codigos[0]} a {codigos[-1]})")
    return {"pedidos": total, "criados": criados, "ja_existiam": total - criados,
            "primeiro": codigos[0], "ultimo": codigos[-1]}


def editar_endereco(endereco_id: int, dados: dict, usuario: str,
                    esquema: str | None = None) -> dict:
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM wms_endereco WHERE id = %s FOR UPDATE", (endereco_id,))
        e = cur.fetchone()
        if not e:
            raise DadoInvalido("Endereço não encontrado.")
        cur.execute("SELECT count(*) AS n FROM wms_saldo WHERE endereco_id = %s", (endereco_id,))
        ocupado = cur.fetchone()["n"] > 0
        cur.execute("SELECT count(*) AS n FROM wms_tarefa WHERE endereco_id = %s AND status = 'pendente'",
                    (endereco_id,))
        com_tarefa = cur.fetchone()["n"] > 0
        sets, vals = [], []
        if "tipo" in dados:
            tipo = escolha(dados["tipo"], TIPOS_ENDERECO, "O tipo do endereço")
            if tipo != e["tipo"] and (ocupado or com_tarefa):
                raise DadoInvalido(f"O endereço {e['codigo']} tem mercadoria — esvazie antes de mudar o tipo.")
            sets.append("tipo = %s")
            vals.append(tipo)
        if "capacidade_paletes" in dados:
            cap = dados["capacidade_paletes"]
            sets.append("capacidade_paletes = %s")
            vals.append(None if cap in (None, "") else
                        inteiro(cap, "a capacidade em paletes", minimo=1, maximo=999))
        if "ativo" in dados:
            ativo = _bool(dados["ativo"])
            if not ativo and (ocupado or com_tarefa):
                raise DadoInvalido(f"O endereço {e['codigo']} tem mercadoria ou separação pendente — "
                                   "não dá para inativar.")
            sets.append("ativo = %s")
            vals.append(ativo)
        if sets:
            cur.execute(f"UPDATE wms_endereco SET {', '.join(sets)} WHERE id = %s",
                        (*vals, endereco_id))
            auditar(cur, usuario, "wms_endereco_editar", e["codigo"],
                    ", ".join(s.split(" ")[0] for s in sets))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════ depositantes
DEPOSITANTES_SQL = """
SELECT d.cnpj, d.razao_social, d.nome_fantasia, d.cidade, d.uf, d.origem, d.ativo, d.criado_em,
       coalesce(p.produtos, 0) AS produtos, coalesce(s.posicoes, 0) AS posicoes
  FROM wms_depositante d
  LEFT JOIN (SELECT depositante_cnpj, count(*) AS produtos FROM wms_produto
              GROUP BY depositante_cnpj) p ON p.depositante_cnpj = d.cnpj
  LEFT JOIN (SELECT pr.depositante_cnpj, count(*) AS posicoes
               FROM wms_saldo s JOIN wms_produto pr ON pr.id = s.produto_id
              GROUP BY pr.depositante_cnpj) s ON s.depositante_cnpj = d.cnpj
 ORDER BY d.ativo DESC, d.razao_social
"""


def listar_depositantes(esquema: str | None = None) -> list[dict]:
    return limpar_todas(ler(DEPOSITANTES_SQL, None, esquema))


def _dados_depositante(dados: dict) -> tuple:
    return (comum.cnpj(dados.get("cnpj")),
            texto(dados.get("razao_social"), "a razão social", maximo=120, obrigatorio=True),
            texto(dados.get("nome_fantasia"), "o nome fantasia", maximo=80),
            texto(dados.get("cidade"), "a cidade", maximo=60),
            _uf(dados.get("uf")))


def criar_depositante(dados: dict, usuario: str, *, origem: str = "manual",
                      esquema: str | None = None) -> dict:
    cnpj, razao, fantasia, cidade, uf = _dados_depositante(dados)
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wms_depositante(cnpj, razao_social, nome_fantasia, cidade, uf, origem, criado_por)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (cnpj, razao, fantasia, cidade, uf, origem, usuario or ""))
        auditar(cur, usuario, "wms_depositante_criar", cnpj, origem)
    return {"cnpj": cnpj, "razao_social": razao}


def garantir_depositante(cur, dados: dict, usuario: str) -> str:
    """Cadastra a partir do ERP se ainda não existir; nunca sobrescreve — o
    cadastro do CÓRTEX, uma vez feito, vence a cópia."""
    cnpj, razao, fantasia, cidade, uf = _dados_depositante(
        {**dados, "razao_social": dados.get("razao_social") or dados.get("cnpj")})
    cur.execute(
        "INSERT INTO wms_depositante(cnpj, razao_social, nome_fantasia, cidade, uf, origem, criado_por)"
        " VALUES (%s, %s, %s, %s, %s, 'erp', %s) ON CONFLICT (cnpj) DO NOTHING",
        (cnpj, razao, fantasia, cidade, uf, usuario or ""))
    return cnpj


def editar_depositante(cnpj_: str, dados: dict, usuario: str,
                       esquema: str | None = None) -> dict:
    cnpj = comum.cnpj(cnpj_)
    sets, vals = [], []
    if "nome_fantasia" in dados:
        sets.append("nome_fantasia = %s")
        vals.append(texto(dados["nome_fantasia"], "o nome fantasia", maximo=80))
    if "ativo" in dados:
        sets.append("ativo = %s")
        vals.append(_bool(dados["ativo"]))
    if sets:
        with transacao(esquema) as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE wms_depositante SET {', '.join(sets)} WHERE cnpj = %s",
                        (*vals, cnpj))
            if not cur.rowcount:
                raise DadoInvalido("Depositante não encontrado.")
            auditar(cur, usuario, "wms_depositante_editar", cnpj,
                    ", ".join(s.split(" ")[0] for s in sets))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════ produtos
# DISPONÍVEL = o que está GUARDADO em endereço não bloqueado, menos o que já
# está reservado por tarefa de separação pendente. Doca, expedição e avaria
# têm saldo, mas não são disponíveis para um pedido novo.
PRODUTOS_SQL = """
SELECT p.id, p.depositante_cnpj, p.codigo, p.descricao, p.unidade, p.ean, p.peso_kg,
       p.controla_lote, p.controla_validade, p.origem, p.ativo,
       d.razao_social, d.nome_fantasia,
       coalesce(s.qtd, 0) AS saldo,
       coalesce(s.posicoes, 0) AS posicoes,
       coalesce(s.guardado, 0) - coalesce(r.reservado, 0) AS disponivel
  FROM wms_produto p
  JOIN wms_depositante d ON d.cnpj = p.depositante_cnpj
  LEFT JOIN (SELECT s.produto_id, sum(s.qtd) AS qtd, count(*) AS posicoes,
                    sum(s.qtd) FILTER (WHERE e.tipo IN ('porta_palete','picking','blocado')
                                         AND NOT e.bloqueado AND e.ativo) AS guardado
               FROM wms_saldo s JOIN wms_endereco e ON e.id = s.endereco_id
              WHERE (%(a)s::int IS NULL OR e.armazem_id = %(a)s)
              GROUP BY s.produto_id) s ON s.produto_id = p.id
  LEFT JOIN (SELECT t.produto_id, sum(t.qtd) AS reservado
               FROM wms_tarefa t JOIN wms_endereco e ON e.id = t.endereco_id
              WHERE t.status = 'pendente' AND (%(a)s::int IS NULL OR e.armazem_id = %(a)s)
              GROUP BY t.produto_id) r ON r.produto_id = p.id
 WHERE (%(dep)s::text IS NULL OR p.depositante_cnpj = %(dep)s)
   AND (%(busca)s::text IS NULL OR p.codigo ILIKE %(busca)s OR p.descricao ILIKE %(busca)s
        OR p.ean = %(exata)s)
   AND (%(ativos)s::boolean IS NOT TRUE OR p.ativo)
 ORDER BY d.razao_social, p.codigo
"""


def listar_produtos(*, depositante: str | None = None, busca: str | None = None,
                    armazem_id: int | None = None, so_ativos: bool = False,
                    limite: int = 500, esquema: str | None = None) -> dict:
    dep = comum.cnpj(depositante) if depositante else None
    linhas = ler(PRODUTOS_SQL, {"dep": dep, "busca": comum.curinga(busca),
                                "exata": (busca or "").strip() or None,
                                "a": armazem_id, "ativos": so_ativos}, esquema)
    lim = max(1, min(int(limite), 3000))
    return {"produtos": limpar_todas(linhas[:lim]), "total": len(linhas),
            "mostrando": min(len(linhas), lim)}


def _ean(v) -> str:
    d = "".join(ch for ch in str(v or "") if ch.isdigit())
    if d and len(d) not in (8, 12, 13, 14):
        raise DadoInvalido("O EAN/GTIN tem 8, 12, 13 ou 14 dígitos.")
    return d


def _unidade(v) -> str:
    u = re.sub(r"[^A-Z0-9]", "", str(v or "").upper())[:6]
    return u or "UN"


def criar_produto(dados: dict, usuario: str, esquema: str | None = None) -> dict:
    dep = comum.cnpj(dados.get("depositante_cnpj"))
    codigo = texto(dados.get("codigo"), "o código do produto", maximo=60, obrigatorio=True)
    descricao = texto(dados.get("descricao"), "a descrição", maximo=200, obrigatorio=True)
    peso = quantidade_br(dados.get("peso_kg"), "o peso")
    if peso is not None and peso < 0:
        raise DadoInvalido("O peso não pode ser negativo.")
    with transacao(esquema) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM wms_depositante WHERE cnpj = %s", (dep,))
        if not cur.fetchone():
            raise DadoInvalido("Cadastre o depositante antes do produto.")
        cur.execute(
            """INSERT INTO wms_produto(depositante_cnpj, codigo, descricao, unidade, ean, peso_kg,
                                       controla_lote, controla_validade, origem)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual') RETURNING id""",
            (dep, codigo, descricao, _unidade(dados.get("unidade")), _ean(dados.get("ean")), peso,
             _bool(dados.get("controla_lote", False)), _bool(dados.get("controla_validade", False))))
        novo = cur.fetchone()["id"]
        auditar(cur, usuario, "wms_produto_criar", f"{dep}:{codigo}", descricao[:80])
    return {"id": novo, "codigo": codigo}


def garantir_produto(cur, depositante: str, codigo: str, descricao: str,
                     unidade: str) -> int:
    """O produto que veio na nota do ERP. Se já existe, vale o cadastro daqui
    — a descrição da nota muda de uma emissão para outra, e o `DO UPDATE` que
    não mexe em nada é só para o `RETURNING` devolver o id nos dois casos."""
    cur.execute(
        """INSERT INTO wms_produto(depositante_cnpj, codigo, descricao, unidade, origem)
           VALUES (%s, %s, %s, %s, 'erp')
           ON CONFLICT (depositante_cnpj, codigo) DO UPDATE SET codigo = EXCLUDED.codigo
           RETURNING id""",
        (depositante, codigo.strip()[:60], (descricao or codigo).strip()[:200] or codigo,
         _unidade(unidade)))
    return cur.fetchone()["id"]


def editar_produto(produto_id: int, dados: dict, usuario: str,
                   esquema: str | None = None) -> dict:
    sets, vals = [], []
    if "descricao" in dados:
        sets.append("descricao = %s")
        vals.append(texto(dados["descricao"], "a descrição", maximo=200, obrigatorio=True))
    if "unidade" in dados:
        sets.append("unidade = %s")
        vals.append(_unidade(dados["unidade"]))
    if "ean" in dados:
        sets.append("ean = %s")
        vals.append(_ean(dados["ean"]))
    if "peso_kg" in dados:
        peso = quantidade_br(dados["peso_kg"], "o peso")
        if peso is not None and peso < 0:
            raise DadoInvalido("O peso não pode ser negativo.")
        sets.append("peso_kg = %s")
        vals.append(peso)
    for campo in ("controla_lote", "controla_validade", "ativo"):
        if campo in dados:
            sets.append(f"{campo} = %s")
            vals.append(_bool(dados[campo]))
    if sets:
        with transacao(esquema) as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE wms_produto SET {', '.join(sets)} WHERE id = %s",
                        (*vals, produto_id))
            if not cur.rowcount:
                raise DadoInvalido("Produto não encontrado.")
            auditar(cur, usuario, "wms_produto_editar", str(produto_id),
                    ", ".join(s.split(" ")[0] for s in sets))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════ catálogo
def catalogo(esquema: str | None = None) -> dict:
    """O que as telas precisam para montar seletores — uma ida só."""
    arms = ler("SELECT id, codigo, nome FROM wms_armazem WHERE ativo ORDER BY codigo",
               None, esquema)
    esp = ler("""SELECT id, armazem_id, codigo, tipo FROM wms_endereco
                  WHERE ativo AND tipo IN ('doca','expedicao','avaria') ORDER BY codigo""",
              None, esquema)
    por_arm: dict[int, dict] = {a["id"]: {**a, "docas": [], "expedicao": [], "avaria": []}
                                for a in arms}
    for e in esp:
        a = por_arm.get(e["armazem_id"])
        if a is not None:
            a[e["tipo"] if e["tipo"] != "doca" else "docas"].append(
                {"id": e["id"], "codigo": e["codigo"]})
    deps = ler("""SELECT cnpj, razao_social, nome_fantasia FROM wms_depositante
                   WHERE ativo ORDER BY razao_social""", None, esquema)
    return {"armazens": list(por_arm.values()),
            "depositantes": limpar_todas(deps),
            "tipos": [{"chave": t, "rotulo": ROTULO_TIPO[t]} for t in TIPOS_ENDERECO],
            "tipos_guarda": list(TIPOS_GUARDA),
            "motivos_bloqueio": list(comum.MOTIVOS_BLOQUEIO)}
