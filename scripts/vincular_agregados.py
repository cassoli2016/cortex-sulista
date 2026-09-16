# -*- coding: utf-8 -*-
"""Cadastra (e desliga) o vínculo que dá acesso ao app do agregado.

O VÍNCULO É O QUE DÁ ACESSO, e ele não nasce sozinho. Ter veículo agregado no
ERP não basta: alguém da casa liga o telefone ao código do proprietário, e é
`agr_vinculos` que o login lê. Sem uma linha aqui, o app responde a um dono de
caminhão exatamente como responde a um desconhecido — de propósito.

    uv run python scripts/vincular_agregados.py                  # só MOSTRA
    uv run python scripts/vincular_agregados.py --aplicar
    uv run python scripts/vincular_agregados.py --aplicar --limite 30
    uv run python scripts/vincular_agregados.py --desligar

SEM `--aplicar` ELE NÃO ESCREVE NADA. O padrão é mostrar, porque o primeiro uso
disto é uma conversa ("são 201 donos, começamos por quem?"), não um comando.

POR QUE O `--limite` EXISTE: o WhatsApp da casa tem teto de 60 destinatários
DISTINTOS por dia, no mesmo número que fala com clientes e fornecedores.
Cadastrar 201 donos de uma vez não estoura nada aqui — o vínculo é uma linha no
banco —, mas todos eles pedindo código na mesma semana estouram. Cadastrar em
ondas é o jeito de o app entrar sem derrubar a comunicação da empresa.

O DESLIGAMENTO NÃO ACONTECE SOZINHO. Ele LISTA quem está vinculado e já não tem
veículo agregado ativo; `--desligar` age, e mesmo assim só nesses. Agregado que
vende um caminhão e compra outro passa dias sem veículo ativo no cadastro, e
tirar o acesso dele sozinho seria decidir por quem não pediu. Acesso não é
estado que envelhece: é decisão de gente.

O TELEFONE SAI DO CADASTRO DO ERP, em duas colunas e nesta ordem: `celular`
primeiro, `fone` depois. Medido em 16/09/2026: os 201 donos de veículo AGR têm
ao menos uma das duas preenchidas. O campo já traz DDI+DDD — concatenar
`dddcelular` com ele QUEBRA o número (a mesma armadilha do script do motorista,
onde isso dava 0,2% de válidos contra 96,5%).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import db, pglocal  # noqa: E402
from api.agregado.dados import UTILIZACAO  # noqa: E402
from api.whatsapp import numeros  # noqa: E402

#: Os donos, e quantos veículos cada um tem. A modalidade é a mesma constante
#: que o app lê (`api/agregado/dados.UTILIZACAO`), e não um literal repetido:
#: literal repetido diverge, e divergir aqui significa cadastrar quem o app não
#: vai atender.
CANDIDATOS_SQL = f"""
SELECT btrim(v.proprietario) AS cod,
       count(*)::int AS veiculos,
       sum(CASE WHEN v.ativoinativo = 1 THEN 1 ELSE 0 END)::int AS ativos,
       coalesce(nullif(btrim(c.razaosocial), ''),
                nullif(btrim(c.nomefantasia), ''), '') AS nome,
       coalesce(c.celular, '') AS celular,
       coalesce(c.fone, '') AS fone
  FROM veiculo v
  LEFT JOIN cadastro c ON btrim(cast(c.codigo AS text)) = btrim(v.proprietario)
 WHERE v.utilizacaoveiculo = '{UTILIZACAO}'
   AND btrim(coalesce(v.proprietario, '')) <> ''
 GROUP BY 1, 4, 5, 6
 ORDER BY 3 DESC, 2 DESC, 1
"""


def _fone(*brutos: str) -> str:
    """O primeiro telefone VÁLIDO da lista, pelo validador único da casa."""
    for bruto in brutos:
        try:
            n = numeros.normalizar(bruto or "")
            if numeros.valido(n):
                return n
        except Exception:  # noqa: BLE001
            continue
    return ""


def candidatos() -> list[dict]:
    return [{**l, "fone": _fone(l["celular"], l["fone"])}
            for l in db.query(CANDIDATOS_SQL, {})]


def existentes() -> dict[str, dict]:
    return {l["proprietario_codigo"]: l for l in pglocal.query(
        "SELECT proprietario_codigo, telefone, nome, ativo FROM agr_vinculos")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=0,
                    help="cadastra no máximo N por vez — o teto de 60 "
                         "destinatários/dia do WhatsApp mora aqui")
    ap.add_argument("--aplicar", action="store_true",
                    help="ESCREVE. Sem ele, só mostra.")
    ap.add_argument("--desligar", action="store_true",
                    help="desliga quem está vinculado e não tem mais veículo "
                         "agregado ativo")
    args = ap.parse_args()

    lista = candidatos()
    ja = existentes()
    com_veiculo_ativo = [c for c in lista if c["ativos"]]
    com_fone = [c for c in com_veiculo_ativo if c["fone"]]
    sem_fone = [c for c in com_veiculo_ativo if not c["fone"]]
    novos = [c for c in com_fone if c["cod"] not in ja]
    mudou_fone = [c for c in com_fone
                  if c["cod"] in ja and ja[c["cod"]]["telefone"] != c["fone"]]
    ativos_agora = {c["cod"] for c in com_veiculo_ativo}
    sumidos = [cod for cod, v in ja.items() if v["ativo"] and cod not in ativos_agora]

    print("ERP · proprietários de veículo agregado:")
    print(f"  donos .......................... {len(lista)}")
    print(f"  com veículo ATIVO .............. {len(com_veiculo_ativo)}")
    print(f"  com telefone válido ............ {len(com_fone)}"
          + (f"  ({100 * len(com_fone) / len(com_veiculo_ativo):.1f}%)"
             if com_veiculo_ativo else ""))
    print(f"  SEM telefone (não dá para entrar) {len(sem_fone)}")
    print()
    print(f"Vínculos hoje: {len(ja)} ({sum(1 for v in ja.values() if v['ativo'])} ativos)")
    print(f"  a criar ........................ {len(novos)}")
    print(f"  telefone MUDOU no ERP .......... {len(mudou_fone)}")
    print(f"  vinculados sem veículo ativo ... {len(sumidos)}"
          + ("  (--desligar age nestes)" if sumidos and not args.desligar else ""))

    # Um telefone servindo mais de um vínculo é o caso que o login trata
    # perguntando quem é — aqui costuma ser o dono pessoa física que também tem
    # veículo no CNPJ da empresa dele. Aparece para quem cadastra saber que não
    # é engano de digitação.
    porfone: dict[str, list[str]] = {}
    for c in com_fone:
        porfone.setdefault(c["fone"], []).append(c["cod"])
    dividido = {f: cs for f, cs in porfone.items() if len(cs) > 1}
    if dividido:
        print(f"  telefones compartilhados ....... {len(dividido)} "
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
            """INSERT INTO agr_vinculos(proprietario_codigo, telefone, nome,
                                        ativo, criado_por)
               VALUES (%(c)s, %(f)s, %(n)s, true, 'script')
               ON CONFLICT (proprietario_codigo) DO UPDATE
                  SET telefone = excluded.telefone,
                      nome = excluded.nome,
                      ativo = true,
                      desligado_em = NULL, desligado_por = ''""",
            {"c": c["cod"], "f": c["fone"], "n": (c["nome"] or "")[:120]})
    print(f"vinculados: {len(alvo)}")

    if args.desligar and sumidos:
        for cod in sumidos:
            pglocal.executar(
                """UPDATE agr_vinculos
                      SET ativo = false, desligado_em = now(),
                          desligado_por = 'script'
                    WHERE proprietario_codigo = %(c)s""", {"c": cod})
        print(f"desligados: {len(sumidos)} (a sessão deles cai na "
              "requisição seguinte)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
