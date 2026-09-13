# -*- coding: utf-8 -*-
"""A leitura do armazém — uma consulta para três públicos: a tela `wmspan`,
o cartão da Saúde do Servidor e o snapshot do Copiloto.

Um número, uma fonte: se a tela, a Saúde e o chat calculassem "pedidos
atrasados" cada um do seu jeito, discordariam no primeiro dia, e os três
estariam certos.

Tudo aqui é CALCULADO na leitura. Mercadoria parada na doca há mais de 24 h,
pedido atrasado, lote vencido: nenhum desses é status gravado, porque estado
que envelhece sozinho precisaria de uma rotina para virar — e no dia em que
ela não rodasse, o painel diria que está tudo em dia.
"""
from __future__ import annotations

from datetime import datetime

from .. import pglocal
from .comum import ler, limpar, limpar_todas

# `%(a)s` nulo = todos os armazéns (Saúde e Copiloto); preenchido = a tela.
KPIS_SQL = """
WITH e AS (SELECT * FROM wms_endereco WHERE (%(a)s::int IS NULL OR armazem_id = %(a)s)),
     s AS (SELECT s.*, e.tipo, e.bloqueado, e.ativo AS end_ativo
             FROM wms_saldo s JOIN e ON e.id = s.endereco_id)
SELECT
  (SELECT count(*) FROM wms_armazem WHERE ativo AND (%(a)s::int IS NULL OR id = %(a)s)) AS armazens,
  (SELECT count(*) FROM e WHERE ativo AND tipo IN ('porta_palete','picking','blocado')) AS enderecos_guarda,
  (SELECT count(DISTINCT endereco_id) FROM s
    WHERE end_ativo AND tipo IN ('porta_palete','picking','blocado')) AS enderecos_ocupados,
  (SELECT count(*) FROM e WHERE ativo AND bloqueado) AS enderecos_bloqueados,
  (SELECT count(*) FROM s) AS posicoes,
  (SELECT count(DISTINCT produto_id) FROM s) AS produtos_em_estoque,
  (SELECT count(*) FROM s WHERE tipo = 'doca') AS doca_posicoes,
  (SELECT count(*) FROM s WHERE tipo = 'doca'
     AND primeira_entrada < now() - interval '24 hours') AS doca_24h,
  (SELECT round(max(extract(epoch FROM now() - primeira_entrada))::numeric / 3600, 1)
     FROM s WHERE tipo = 'doca') AS doca_idade_max_h,
  (SELECT count(*) FROM s WHERE tipo = 'avaria') AS avaria_posicoes,
  (SELECT count(*) FROM s WHERE validade < current_date) AS vencidos,
  (SELECT count(*) FROM s WHERE validade BETWEEN current_date AND current_date + 30) AS vencendo_30d,
  (SELECT count(*) FROM wms_recebimento
    WHERE status = 'aberto' AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS rec_abertos,
  (SELECT count(*) FROM wms_recebimento
    WHERE status = 'aberto' AND criado_em < now() - interval '24 hours'
      AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS rec_abertos_24h,
  (SELECT count(*) FROM wms_recebimento
    WHERE status = 'conferido' AND conferido_em::date = current_date
      AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS rec_hoje,
  (SELECT count(*) FROM wms_pedido
    WHERE status = 'aberto' AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS ped_a_liberar,
  (SELECT count(*) FROM wms_pedido p
    WHERE p.status = 'liberado' AND (%(a)s::int IS NULL OR p.armazem_id = %(a)s)
      AND EXISTS (SELECT 1 FROM wms_tarefa t WHERE t.pedido_id = p.id
                                             AND t.status = 'pendente')) AS ped_em_separacao,
  (SELECT count(*) FROM wms_pedido p
    WHERE p.status = 'liberado' AND (%(a)s::int IS NULL OR p.armazem_id = %(a)s)
      AND NOT EXISTS (SELECT 1 FROM wms_tarefa t WHERE t.pedido_id = p.id
                                                 AND t.status = 'pendente')) AS ped_aguardando_expedicao,
  (SELECT count(*) FROM wms_pedido
    WHERE status = 'expedido' AND expedido_em::date = current_date
      AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS ped_expedidos_hoje,
  (SELECT count(*) FROM wms_pedido
    WHERE status IN ('aberto','liberado') AND previsto_para < current_date
      AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS ped_atrasados,
  (SELECT count(*) FROM wms_tarefa t JOIN wms_pedido p ON p.id = t.pedido_id
    WHERE t.status = 'pendente' AND (%(a)s::int IS NULL OR p.armazem_id = %(a)s)) AS tarefas_pendentes,
  (SELECT count(*) FROM wms_inventario
    WHERE status = 'aberto' AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS inventarios_abertos,
  (SELECT count(*) FROM wms_inventario
    WHERE status = 'aberto' AND criado_em < now() - interval '3 days'
      AND (%(a)s::int IS NULL OR armazem_id = %(a)s)) AS inventarios_abertos_3d,
  (SELECT max(m.criado_em) FROM wms_movimento m JOIN e ON e.id = m.endereco_id) AS ultimo_movimento
"""

INVENTARIO_SQL = """
SELECT iv.id, iv.fechado_em, count(ie.endereco_id) AS enderecos,
       (SELECT count(DISTINCT m.endereco_id) FROM wms_movimento m
         WHERE m.doc_tipo = 'inventario' AND m.doc_id = iv.id) AS divergentes
  FROM wms_inventario iv
  JOIN wms_inventario_endereco ie ON ie.inventario_id = iv.id
 WHERE iv.status = 'fechado' AND (%(a)s::int IS NULL OR iv.armazem_id = %(a)s)
 GROUP BY iv.id
 ORDER BY iv.fechado_em DESC
 LIMIT 1
"""

# O intervalo de dias é GERADO, não colhido: `GROUP BY` não devolve o dia sem
# linha, e o gráfico emendaria segunda com quinta.
SERIE_SQL = """
SELECT d::date AS dia,
       (SELECT count(*) FROM wms_recebimento r
         WHERE r.status = 'conferido' AND r.conferido_em::date = d::date
           AND r.armazem_id = %(a)s) AS recebimentos,
       (SELECT count(*) FROM wms_pedido p
         WHERE p.status = 'expedido' AND p.expedido_em::date = d::date
           AND p.armazem_id = %(a)s) AS expedicoes
  FROM generate_series(current_date - 29, current_date, interval '1 day') AS d
 ORDER BY d
"""

RUAS_SQL = """
SELECT e.rua, count(*) AS ativos, count(o.endereco_id) AS ocupados,
       count(*) FILTER (WHERE e.bloqueado) AS bloqueados
  FROM wms_endereco e
  LEFT JOIN (SELECT DISTINCT endereco_id FROM wms_saldo) o ON o.endereco_id = e.id
 WHERE e.armazem_id = %(a)s AND e.ativo AND e.tipo IN ('porta_palete','picking','blocado')
 GROUP BY e.rua
 ORDER BY e.rua
"""

DEPOSITANTES_SQL = """
SELECT d.cnpj, d.razao_social, d.nome_fantasia,
       count(*) AS posicoes, count(DISTINCT s.produto_id) AS produtos,
       count(DISTINCT s.endereco_id) AS enderecos
  FROM wms_saldo s
  JOIN wms_endereco e ON e.id = s.endereco_id
  JOIN wms_produto p ON p.id = s.produto_id
  JOIN wms_depositante d ON d.cnpj = p.depositante_cnpj
 WHERE e.armazem_id = %(a)s
 GROUP BY d.cnpj
 ORDER BY count(DISTINCT s.endereco_id) DESC, d.razao_social
"""


def _pct(parte, todo) -> float | None:
    return round(100.0 * parte / todo, 1) if todo else None


def kpis(armazem_id: int | None = None, esquema: str | None = None) -> dict:
    # contagem volta como int; idade como float; data como texto ISO
    k = limpar(ler(KPIS_SQL, {"a": armazem_id}, esquema)[0])
    k["ocupacao_pct"] = _pct(k["enderecos_ocupados"], k["enderecos_guarda"])
    inv = ler(INVENTARIO_SQL, {"a": armazem_id}, esquema)
    if inv:
        i = inv[0]
        k["acuracia_inventario"] = _pct(int(i["enderecos"]) - int(i["divergentes"]),
                                        int(i["enderecos"]))
        k["inventario_fechado_em"] = i["fechado_em"].isoformat() if i["fechado_em"] else None
    else:
        k["acuracia_inventario"] = None
        k["inventario_fechado_em"] = None
    return k


def alertas(k: dict) -> list[dict]:
    """O que pede ação AGORA, com a tela onde se resolve. `alerta` é vermelho
    (já passou do ponto), `atencao` é amarelo (vai passar)."""
    a = []

    def add(nivel, n, texto, tela):
        if n:
            a.append({"nivel": nivel, "n": n, "texto": texto, "tela": tela})

    add("alerta", k["ped_atrasados"], "pedido(s) com data prevista vencida e não expedidos", "wmsexp")
    add("alerta", k["vencidos"], "posição(ões) de estoque com lote VENCIDO", "wmsest")
    add("alerta", k["doca_24h"], "posição(ões) paradas na doca há mais de 24 h", "wmsrec")
    add("atencao", k["rec_abertos_24h"], "recebimento(s) aberto(s) há mais de 24 h sem conferência", "wmsrec")
    add("atencao", k["vencendo_30d"], "posição(ões) com validade nos próximos 30 dias", "wmsest")
    add("atencao", k["inventarios_abertos_3d"], "inventário(s) aberto(s) há mais de 3 dias — "
        "os endereços seguem bloqueados", "wmsest")
    add("atencao", k["avaria_posicoes"], "posição(ões) na área de avaria aguardando destino", "wmsest")
    return a


def panorama(armazem_id: int, esquema: str | None = None) -> dict:
    k = kpis(armazem_id, esquema)
    serie = limpar_todas(ler(SERIE_SQL, {"a": armazem_id}, esquema))
    deps = limpar_todas(ler(DEPOSITANTES_SQL, {"a": armazem_id}, esquema))
    return {
        "armazem_id": armazem_id,
        "kpis": k,
        "alertas": alertas(k),
        "serie": [{"dia": s["dia"][:10], "recebimentos": int(s["recebimentos"]),
                   "expedicoes": int(s["expedicoes"])} for s in serie],
        "ruas": limpar_todas(ler(RUAS_SQL, {"a": armazem_id}, esquema)),
        # TOP-N LEVA CONTADOR: a tela diz "8 de 23"
        "depositantes": deps[:8],
        "depositantes_total": len(deps),
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def diagnostico(esquema: str | None = None) -> dict:
    """O que a Saúde do Servidor mede — todos os armazéns juntos."""
    try:
        return {"ok": True, **kpis(None, esquema)}
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"ok": False, "sem_tabela": True}
        raise


def resumo_copiloto(esquema: str | None = None) -> dict:
    """Só ESCALARES — nenhum nome de depositante, CNPJ, produto ou placa. O
    snapshot vai para modelo externo quando o Ollama local não responde, e é
    isso, não um filtro mágico, que permite o fallback."""
    k = kpis(None, esquema)
    chaves = ("armazens", "enderecos_guarda", "enderecos_ocupados", "ocupacao_pct",
              "enderecos_bloqueados", "posicoes", "produtos_em_estoque",
              "doca_posicoes", "doca_24h", "doca_idade_max_h", "vencidos", "vencendo_30d",
              "rec_abertos", "rec_hoje", "ped_a_liberar", "ped_em_separacao",
              "ped_aguardando_expedicao", "ped_expedidos_hoje", "ped_atrasados",
              "tarefas_pendentes", "inventarios_abertos", "acuracia_inventario")
    return {c: k.get(c) for c in chaves}
