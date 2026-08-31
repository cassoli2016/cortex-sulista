"""Semeia o CRM com a carteira real: uma conta por grupo econômico do ERP.

POR QUE ISTO EXISTE. O CRM nasceu com as tabelas vazias, e uma tela de funil em
branco não é um começo neutro: ela convida o time a cadastrar cliente à mão,
digitando nome que já existe no ERP — e conta digitada à mão nasce sem o
vínculo com o `agrupamentocliente`, que é justamente o que traz a receita real.
Duas semanas assim e o CRM vira um segundo cadastro de clientes, divergente do
primeiro.

O QUE ELE FAZ, E SÓ ISSO: cria `crm_contas` com nome e `ava_agrupamento`. Não
inventa segmento, não inventa dono, não inventa CNPJ. As três razões estão
abaixo, porque cada uma foi uma tentativa descartada por evidência.

**Segmento: NÃO.** A tentativa era casar `agrupamentocliente.descricao` com
`sulista.gestaocomercial.cliente` e pegar o `cliente_segmento`. Casaram 4 de 34
— o grupo é curto ("WEG") e o lead é razão social ("CELUPA - INDUSTRIAL
CELULOSE E PAPEL GUAÍBA LTDA"). Preencher 4 e deixar 30 vazios é pior que
deixar 34 vazios: a coluna passa a PARECER preenchida e ninguém revisa as
outras. Campo em branco é uma pergunta; campo errado é uma resposta.

**Dono: "A definir".** `gestaocomercial.responsavel` é um código (3, 4, 5) sem
tabela de domínio nesta réplica, e casou nos mesmos 4. Quem sabe de quem é cada
cliente é o time comercial. O CHECK do banco exige dono, então entra o texto
que diz a verdade — e a aba de Contas filtra por responsável, então "A definir"
vira uma fila de trabalho visível em vez de um campo escondido.

**CNPJ: em branco.** Um grupo tem de 0 a 87 CNPJs (SPOT tem 87, TUPY tem 41).
Escolher um seria arbitrário, e pior: o CRM recusa conta duplicada por CNPJ, e
um CNPJ arbitrário barraria o cadastro legítimo da filial depois. O vínculo é o
`ava_agrupamento`, que é a chave desenhada para isso.

**OS BALDES FICAM DE FORA.** Cinco dos 34 "grupos" não são empresas, são
categorias operacionais do ERP: NOVOS CLIENTES, NOVO SEGMENTO, REPOSICIONAMENTO
e TEMPORARIO (zero receita e zero viagem em dois anos) e SPOT (R$ 836 mil, 164
viagens, 87 CNPJs — frete avulso de vários embarcadores). Semeá-los criaria
contas que ninguém pode ligar, atribuir ou vender, e SPOT apareceria no ranking
de concentração como se fosse cliente. `--incluir-baldes` força a inclusão.

IDEMPOTENTE: grupo já vinculado a uma conta é pulado. Rodar de novo depois de
o time cadastrar coisas não duplica nada.

    uv run python scripts/semear_crm.py              # simulação (padrão)
    uv run python scripts/semear_crm.py --aplicar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import pglocal  # noqa: E402
from api.crm import ava, contas  # noqa: E402
from api.crm.comum import init_db  # noqa: E402

# Nomes que o ERP usa como CATEGORIA, não como empresa. Lista explícita e curta
# em vez de heurística (por contagem de CNPJ, por exemplo): TUPY tem 41 CNPJs e
# é cliente, SPOT tem 87 e não é — o que separa os dois é o nome, e uma
# heurística numérica erraria justamente no maior cliente da casa.
BALDES = {"SPOT", "NOVOS CLIENTES", "NOVO SEGMENTO", "REPOSICIONAMENTO",
          "TEMPORARIO"}

DONO_PADRAO = "A definir"


def _vinculados(esquema: str | None) -> set[int]:
    return {int(r["ava_agrupamento"]) for r in pglocal.query(
        "SELECT ava_agrupamento FROM crm_contas "
        "WHERE ava_agrupamento IS NOT NULL", esquema=esquema)}


def semear(*, aplicar: bool, incluir_baldes: bool, dono: str,
           esquema: str | None = None) -> dict:
    init_db(esquema)
    grupos = ava.agrupamentos()
    ja = _vinculados(esquema)
    carteira = ava.carteira([g["codigo"] for g in grupos])

    criar, pulados, baldes = [], [], []
    for g in grupos:
        cod, nome = int(g["codigo"]), g["nome"]
        if cod in ja:
            pulados.append(g)
            continue
        if nome.upper() in BALDES and not incluir_baldes:
            baldes.append(g)
            continue
        criar.append(g)

    feitas, falhas = [], []
    if aplicar:
        for g in criar:
            try:
                c = contas.gravar(
                    {"nome": g["nome"], "ava_agrupamento": g["codigo"],
                     "dono_nome": dono,
                     "observacoes": "Conta criada pela semeadura inicial do "
                                    "CRM a partir do cadastro de grupos "
                                    "econômicos do ERP. Segmento e responsável "
                                    "ficaram em branco de propósito — o ERP "
                                    "não os tem por grupo."},
                    usuario="semeadura", esquema=esquema)
                feitas.append(c)
            except Exception as exc:  # noqa: BLE001
                falhas.append((g["nome"], f"{type(exc).__name__}: {exc}"))

    return {"grupos": grupos, "criar": criar, "pulados": pulados,
            "baldes": baldes, "feitas": feitas, "falhas": falhas,
            "carteira": carteira}


def _linha(g: dict, carteira: dict) -> str:
    d = carteira.get(int(g["codigo"])) or {}
    s = ava.situacao(g["codigo"], d or None)
    rec = d.get("receita_12m") or 0
    dias = f" · {s['dias_sem_viagem']}d sem viagem" if s["dias_sem_viagem"] is not None else ""
    return (f"  {g['codigo']:>4}  {g['nome'][:30]:30} "
            f"R$ {rec:>14,.2f}  {s['situacao']}{dias}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true",
                    help="grava de verdade (sem isto, só simula)")
    ap.add_argument("--incluir-baldes", action="store_true",
                    help="inclui SPOT, NOVOS CLIENTES e afins")
    ap.add_argument("--dono", default=DONO_PADRAO,
                    help=f"nome do responsável (padrão: {DONO_PADRAO!r})")
    ap.add_argument("--esquema", default=None)
    a = ap.parse_args()

    r = semear(aplicar=a.aplicar, incluir_baldes=a.incluir_baldes,
               dono=a.dono, esquema=a.esquema)

    print(f"grupos no ERP: {len(r['grupos'])}")
    if r["pulados"]:
        print(f"\njá vinculados a uma conta ({len(r['pulados'])}) — pulados:")
        for g in r["pulados"]:
            print(f"  {g['codigo']:>4}  {g['nome']}")
    if r["baldes"]:
        print(f"\ncategorias do ERP, NÃO são clientes ({len(r['baldes'])}) — "
              f"fora (use --incluir-baldes para forçar):")
        for g in r["baldes"]:
            print(_linha(g, r["carteira"]))
    print(f"\na criar ({len(r['criar'])}):")
    for g in sorted(r["criar"],
                    key=lambda x: -((r["carteira"].get(int(x["codigo"])) or {})
                                    .get("receita_12m") or 0)):
        print(_linha(g, r["carteira"]))

    if r["falhas"]:
        print(f"\nFALHAS ({len(r['falhas'])}):")
        for nome, erro in r["falhas"]:
            print(f"  {nome}: {erro}")

    if a.aplicar:
        print(f"\ncriadas: {len(r['feitas'])} conta(s).")
        try:
            from api import auth
            auth.audit("semeadura", "crm_semear",
                       alvo=f"{len(r['feitas'])} contas",
                       detalhe=("semeadura inicial a partir do cadastro de "
                                "grupos econômicos do ERP"))
        except Exception as exc:  # noqa: BLE001
            print(f"  (auditoria não registrada: {type(exc).__name__})")
    else:
        print("\nSIMULAÇÃO — nada foi gravado. Use --aplicar.")
    return 1 if r["falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
