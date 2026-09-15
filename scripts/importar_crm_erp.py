"""Importa o CRM do ERP (Avacorp) para o CRM do CÓRTEX.

Leads, projetos e repactuações de `sulista.gestaocomercial`,
`pipelineprojetos` e `pipelineprojetos_repactuacoes`. As regras — o que vira o
quê, o que nunca é reescrito, por que a conta casa só por nome normalizado —
estão em `api/crm/importacao.py`.

SIMULA POR PADRÃO, e a simulação é a importação de verdade desfeita no fim:
mesmas regras, mesmos CHECKs do banco, mesmos números. Só `--aplicar` grava.

PODE RODAR DE NOVO: o que já foi importado é pulado (nunca reescrito — a partir
da importação o registro é do CÓRTEX). Serve para trazer o que ainda for
lançado no ERP até o time parar de usar o CRM de lá.

Os nomes dos responsáveis vêm de `data/crm_importacao.json` (fora do git).

    uv run python scripts/importar_crm_erp.py            # simulação
    uv run python scripts/importar_crm_erp.py --aplicar
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.crm import importacao  # noqa: E402


def _imprimir(r: dict) -> None:
    L, P, R, C = r["leads"], r["projetos"], r["repactuacoes"], r["contas"]
    print("SIMULAÇÃO — nada foi gravado" if not r["aplicado"] else "IMPORTAÇÃO APLICADA")
    print(f"\nleads: {L['lidos']} lidos · {L['importados']} importados · "
          f"{L['ja_importados']} já importados antes")
    print(f"  por estágio: {L['por_estagio']}")
    print(f"  contatos criados: {r['contatos']}")
    print(f"contas: {C['criadas']} criadas ({C['vinculadas_ao_grupo']} vinculadas a grupo "
          f"econômico) · {C['reusadas']} vezes reaproveitada uma conta que já existia")
    print(f"projetos: {P['lidos']} ({P['linhas']} linhas com as versões) · {P['importados']} "
          f"importados · {P['ja_importados']} já importados · {P['andamentos']} andamentos")
    print(f"  por status: {P['por_status']}")
    print(f"repactuações: {R['lidas']} lidas · {R['importadas']} importadas · "
          f"{R['ja_importadas']} já importadas")
    if R["sem_conta"]:
        print(f"  sem conta no CRM (não importadas): {sorted(set(R['sem_conta']))}")
    if r["responsaveis_sem_nome"]:
        print(f"\ncódigos de pessoa SEM nome em data/crm_importacao.json: "
              f"{r['responsaveis_sem_nome']}")
    if r["possiveis_duplicatas"]:
        print(f"\npossíveis contas duplicadas — conferir com quem conhece o cliente "
              f"({len(r['possiveis_duplicatas'])}):")
        for a, b in r["possiveis_duplicatas"][:60]:
            print(f"  {a}  ×  {b}")
    if r["falhas"]:
        print(f"\nFALHAS ({len(r['falhas'])}):")
        for tipo, ident, erro in r["falhas"]:
            print(f"  {tipo} {ident}: {erro}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="grava de verdade")
    ap.add_argument("--esquema", default=None, help="schema do banco (testes)")
    ap.add_argument("--json", action="store_true", help="relatório em JSON")
    a = ap.parse_args()
    r = importacao.importar(aplicar=a.aplicar, esquema=a.esquema)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        _imprimir(r)
    if a.aplicar and a.esquema is None:
        # a trilha: quem importou o quê, e quando (auditoria antes de acabar)
        from api import auth
        auth.audit(importacao.USUARIO, "crm_importacao_erp", alvo="crm",
                   detalhe=json.dumps({"leads": r["leads"]["importados"],
                                       "projetos": r["projetos"]["importados"],
                                       "repactuacoes": r["repactuacoes"]["importadas"],
                                       "contas": r["contas"]["criadas"],
                                       "falhas": len(r["falhas"])}))
    return 1 if r["falhas"] else 0


if __name__ == "__main__":
    sys.exit(main())
