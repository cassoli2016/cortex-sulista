# -*- coding: utf-8 -*-
"""Cadastra (e desliga) o vínculo que dá acesso ao app do motorista.

O VÍNCULO É O QUE DÁ ACESSO, e ele não nasce sozinho. Ter dirigido para a
empresa não basta: alguém da casa liga o telefone ao código do motorista, e é
`mot_vinculos` que o login lê. Sem uma linha aqui, o app responde exatamente
como responde a um desconhecido — de propósito.

    uv run python scripts/vincular_motoristas.py                  # só MOSTRA
    uv run python scripts/vincular_motoristas.py --aplicar
    uv run python scripts/vincular_motoristas.py --aplicar --limite 40
    uv run python scripts/vincular_motoristas.py --dias 90 --frota proprio

SEM `--aplicar` ELE NÃO ESCREVE NADA. O padrão é mostrar, porque o primeiro uso
disto é uma conversa ("são 162 agregados, começamos por quem?"), não um
comando.

POR QUE O `--limite` EXISTE, e é a razão de operação mais concreta deste
arquivo: o WhatsApp da casa tem teto de 60 destinatários DISTINTOS por dia, no
mesmo número que fala com clientes e fornecedores. Cadastrar 300 motoristas de
uma vez não estoura nada aqui — o vínculo é uma linha no banco —, mas todos
eles pedindo código na mesma semana estouram. Cadastrar em ondas é o jeito de
o app entrar sem derrubar a comunicação da empresa.

O DESLIGAMENTO NÃO ACONTECE SOZINHO, e este script NÃO o faz por conta própria.
Ele LISTA quem está vinculado e não roda há muito tempo (`--desligar` age, e
mesmo assim só nesses). Motorista agregado some por semanas e volta; desligar
por inatividade sem alguém decidir seria tirar o acesso de quem está de férias
e devolvê-lo sem ninguém saber. Estado que envelhece sozinho não se grava — mas
acesso não é estado que envelhece: é decisão de gente.

O TELEFONE SAI DE `cadastro.celular` E SÓ DELE. O campo já traz DDI+DDD (13
dígitos em 524 dos 606 medidos em 05/09/2026); concatenar `dddcelular` com ele
QUEBRA o número — dá 0,2% de válidos contra 96,5%. Quem vier mexer aqui e achar
que está faltando o DDD, não está.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, pglocal  # noqa: E402
from api.whatsapp import numeros  # noqa: E402

#: 1 = frota própria, 2 = terceiro, 3 = agregado (`veiculo.tipofrota`).
FROTA = {"proprio": 1, "terceiro": 2, "agregado": 3}

CANDIDATOS_SQL = """
WITH viagens AS (
  SELECT trim(cast(p.motorista AS text)) AS cod,
         v.tipofrota,
         count(*) AS n,
         max(coalesce(p.dtsaida, p.dtemissao)) AS ultima
    FROM programacaoembarque p
    LEFT JOIN veiculo v ON v.placa = p.veiculo
   WHERE p.motorista IS NOT NULL
     AND p.dtcancelamento IS NULL
     AND coalesce(p.dtsaida, p.dtemissao) >= current_date - %(dias)s
   GROUP BY 1, 2
),
predominante AS (
  -- O motorista roda em mais de uma modalidade; a frota DELE é aquela em que
  -- ele mais rodou. Somar as modalidades daria um total certo com uma
  -- classificação errada, e é a classificação que decide o que ele vê.
  SELECT DISTINCT ON (cod) cod, tipofrota
    FROM viagens ORDER BY cod, n DESC
),
total AS (
  SELECT cod, sum(n)::int AS viagens, max(ultima) AS ultima
    FROM viagens GROUP BY cod
)
SELECT t.cod, t.viagens, t.ultima, pr.tipofrota,
       coalesce(nullif(trim(c.razaosocial),''),
                nullif(trim(c.nomefantasia),''), '') AS nome,
       coalesce(c.celular,'') AS celular
  FROM total t
  JOIN predominante pr ON pr.cod = t.cod
  LEFT JOIN cadastro c ON trim(cast(c.codigo AS text)) = t.cod
 WHERE (%(frota)s::int IS NULL OR pr.tipofrota = %(frota)s::int)
 ORDER BY t.viagens DESC, t.cod
"""


def _rotulo_frota(t) -> str:
    return {1: "proprio", 2: "terceiro", 3: "agregado"}.get(t, "?")


def _fone(bruto: str) -> str:
    try:
        n = numeros.normalizar(bruto or "")
        return n if numeros.valido(n) else ""
    except Exception:  # noqa: BLE001
        return ""


def candidatos(dias: int, frota: int | None) -> list[dict]:
    linhas = db.query(CANDIDATOS_SQL, {"dias": dias, "frota": frota})
    fora = []
    for l in linhas:
        fora.append({**l, "fone": _fone(l["celular"]),
                     "frota": _rotulo_frota(l["tipofrota"])})
    return fora


def existentes() -> dict[str, dict]:
    return {l["motorista_codigo"]: l for l in pglocal.query(
        "SELECT motorista_codigo, telefone, nome, ativo FROM mot_vinculos")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dias", type=int, default=90,
                    help="janela de atividade no ERP (padrão: 90)")
    ap.add_argument("--frota", choices=sorted(FROTA), default=None,
                    help="só esta modalidade (padrão: todas)")
    ap.add_argument("--limite", type=int, default=0,
                    help="cadastra no máximo N por vez — o teto de 60 "
                         "destinatários/dia do WhatsApp mora aqui")
    ap.add_argument("--aplicar", action="store_true",
                    help="ESCREVE. Sem ele, só mostra.")
    ap.add_argument("--desligar", action="store_true",
                    help="desliga quem está vinculado e não roda na janela")
    args = ap.parse_args()

    lista = candidatos(args.dias, FROTA.get(args.frota or ""))
    ja = existentes()

    com_fone = [c for c in lista if c["fone"]]
    sem_fone = [c for c in lista if not c["fone"]]
    novos = [c for c in com_fone if c["cod"] not in ja]
    mudou_fone = [c for c in com_fone
                  if c["cod"] in ja and ja[c["cod"]]["telefone"] != c["fone"]]
    sumidos = [cod for cod, v in ja.items()
               if v["ativo"] and cod not in {c["cod"] for c in lista}]

    print(f"ERP · {args.dias} dias"
          + (f" · frota {args.frota}" if args.frota else "") + ":")
    print(f"  motoristas que rodaram .......... {len(lista)}")
    print(f"  com celular válido .............. {len(com_fone)}"
          + (f"  ({100 * len(com_fone) / len(lista):.1f}%)" if lista else ""))
    print(f"  SEM celular (não dá para entrar)  {len(sem_fone)}")
    for f in sorted({c['frota'] for c in lista}):
        n = len([c for c in lista if c["frota"] == f])
        print(f"    {f:9s} {n:4d}")
    print()
    print(f"Vínculos hoje: {len(ja)} ({sum(1 for v in ja.values() if v['ativo'])} ativos)")
    print(f"  a criar ......................... {len(novos)}")
    print(f"  telefone MUDOU no ERP ........... {len(mudou_fone)}")
    print(f"  vinculados que não rodam na janela {len(sumidos)}"
          + ("  (--desligar age nestes)" if sumidos and not args.desligar else ""))

    # Um telefone servindo mais de um motorista é o caso medido (5 em 585) que
    # o login trata perguntando quem é. Aparece aqui para quem cadastra saber
    # que não é engano de digitação.
    porfone: dict[str, list[str]] = {}
    for c in com_fone:
        porfone.setdefault(c["fone"], []).append(c["cod"])
    dividido = {f: cs for f, cs in porfone.items() if len(cs) > 1}
    if dividido:
        print(f"  telefones compartilhados ........ {len(dividido)} "
              f"(o login pergunta quem é)")

    if not args.aplicar:
        print("\n(nada foi escrito — rode com --aplicar)")
        return 0

    alvo = novos + mudou_fone
    if args.limite:
        alvo = alvo[:args.limite]
        print(f"\nlimite de {args.limite}: {len(alvo)} nesta onda")

    for c in alvo:
        pglocal.executar(
            """INSERT INTO mot_vinculos(motorista_codigo, telefone, nome,
                                        ativo, criado_por)
               VALUES (%(c)s, %(f)s, %(n)s, true, 'script')
               ON CONFLICT (motorista_codigo) DO UPDATE
                  SET telefone = excluded.telefone,
                      nome = excluded.nome,
                      ativo = true,
                      desligado_em = NULL, desligado_por = ''""",
            {"c": c["cod"], "f": c["fone"], "n": c["nome"][:120]})
    print(f"vinculados: {len(alvo)}")

    if args.desligar and sumidos:
        for cod in sumidos:
            pglocal.executar(
                """UPDATE mot_vinculos
                      SET ativo = false, desligado_em = now(),
                          desligado_por = 'script'
                    WHERE motorista_codigo = %(c)s""", {"c": cod})
        print(f"desligados: {len(sumidos)} (a sessão deles cai na "
              "requisição seguinte)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
