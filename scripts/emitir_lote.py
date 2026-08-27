# scripts/emitir_lote.py
"""Emite EM LOTE os CT-e de contrapartida de um periodo. So HOMOLOGACAO.

Roda em ENSAIO por padrao: percorre a fila, aplica todas as guardas e NAO
transmite. Para valer, passe --valendo - explicito de proposito, porque a
diferenca entre listar e assinar em nome de terceiro nao pode ser um descuido
de linha de comando.

Uso:
  uv run --no-sync python scripts/emitir_lote.py                 # ensaio, hoje
  uv run --no-sync python scripts/emitir_lote.py --de 2026-08-01 --ate 2026-08-26
  uv run --no-sync python scripts/emitir_lote.py --valendo --limite 5
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.contrapartida import emissao, lote  # noqa: E402
from scripts.emitir_homologacao import ENQUADRAMENTO  # noqa: E402


def main() -> int:
    hoje = date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", default=hoje.isoformat())
    ap.add_argument("--ate", default=hoje.isoformat())
    ap.add_argument("--limite", type=int, default=10)
    ap.add_argument("--quem", default=emissao.IDENTIDADE_SISTEMA)
    ap.add_argument("--valendo", action="store_true",
                    help="transmite de verdade (sem isto, e ensaio)")
    ap.add_argument("--desassistido", action="store_true",
                    help="modo da rotina agendada: exige a automacao LIGADA")
    ap.add_argument("--agendado", action="store_true",
                    help="chamado pelo agendador: so roda se estiver na hora")
    ap.add_argument("--ligar-automacao", action="store_true")
    ap.add_argument("--desligar-automacao", action="store_true")
    ap.add_argument("--producao", action="store_true",
                    help="emite em PRODUCAO (exige liberacao previa)")
    ap.add_argument("--liberar-producao", metavar="CONFIRMACAO",
                    help=f"destrava producao; confirme com "
                         f"'{emissao.CONFIRMACAO_PRODUCAO}'")
    ap.add_argument("--travar-producao", action="store_true")
    a = ap.parse_args()

    if a.liberar_producao is not None or a.travar_producao:
        try:
            r = emissao.liberar_producao(
                not a.travar_producao, a.quem,
                confirmacao=a.liberar_producao or "")
        except PermissionError as exc:
            print(f"RECUSADO: {exc}")
            return 2
        print(f"producao {'LIBERADA' if r['ativa'] else 'travada'} "
              f"por {r['quem']} em {r['quando']}")
        return 0

    ambiente = emissao.PRODUCAO if a.producao else emissao.HOMOLOGACAO

    # O AGENDADOR dispara em intervalo fixo e curto; quem decide se e hora e o
    # proprio CORTEX, lendo o intervalo configurado na tela. Sair com 0 quando
    # nao e hora e de proposito: para o Windows a tarefa foi bem-sucedida, e o
    # historico do agendador nao enche de "falha" a cada cinco minutos.
    if a.agendado:
        a.desassistido = True
        a.valendo = True
        ambiente = emissao.ambiente_ativo()
        pode, porque = lote.deve_rodar()
        if not pode:
            print(f"nada a fazer: {porque}")
            return 0
        print(f"na hora: {porque}")
        # PILHA FISCAL ANTES DE TUDO. Sem ela cada documento morre com
        # "No module named 'erpbrasil'" DEPOIS de a passagem ter sido
        # registrada - de fora, "nada a emitir" e "perdi a capacidade de
        # emitir" ficam iguais. Aqui a rotina sai com erro, o agendador do
        # Windows guarda a falha, a passagem NAO e marcada e o cronometro da
        # tela passa a acusar atraso.
        ok, motivo = lote.pilha_fiscal()
        if not ok:
            print(f"PILHA FISCAL AUSENTE: {motivo}")
            print("  a emissao esta parada. Reinstale com: uv sync")
            return 3
        # MARCA A PASSAGEM ANTES DE EMITIR, e nao depois. O intervalo
        # configurado na tela so existe se alguem gravar quando a rotina
        # passou: sem isto `ultima_execucao` fica sempre vazia, `deve_rodar`
        # responde "primeira execucao" toda vez e o lote emite a CADA TIQUE do
        # agendador - de 5 em 5 minutos - qualquer que seja o intervalo
        # escolhido. Antes e nao depois porque lote que trava ou morre no meio
        # nao pode voltar a disparar em cinco minutos: a proxima passagem tem
        # de esperar o intervalo inteiro de qualquer jeito.
        lote.registrar_execucao(emissao.IDENTIDADE_SISTEMA)

    if a.ligar_automacao or a.desligar_automacao:
        r = lote.definir_automacao(bool(a.ligar_automacao), a.quem)
        print(f"automacao {'LIGADA' if r['ativa'] else 'desligada'} "
              f"por {r['quem']} em {r['quando']}")
        return 0
    ate = (date.fromisoformat(a.ate) + timedelta(days=1)).isoformat()

    r = lote.resumo_fila(a.de, ate, ambiente)
    print(f"FILA de {a.de} a {a.ate}")
    print(f"  CT-e de agregado PJ no periodo .. {r['ctes_no_periodo']}")
    print(f"  ja com contrapartida ............ {r['ja_emitidos']}")
    print(f"  agregado sem certificado ........ {r['sem_agregado_pronto']}")
    print(f"  agregado sem IE no cadastro ..... {r.get('sem_cadastro', 0)}")
    print(f"  envio desligado ................. {r.get('envio_desligado', 0)}")
    print(f"  A EMITIR ........................ {r['a_emitir']}")
    print()

    modo = "VALENDO (homologacao)" if a.valendo else "ENSAIO - nada sera transmitido"
    print(f"MODO: {modo} · teto {a.limite}\n")

    try:
        res = lote.processar_lote(a.de, ate, ENQUADRAMENTO, quem=a.quem,
                                  limite=a.limite, ambiente=ambiente,
                                  dry_run=not a.valendo,
                                  desassistido=a.desassistido)
    except PermissionError as exc:
        print(f"RECUSADO: {exc}")
        return 2
    for it in res["itens"]:
        marca = {"autorizado": "OK ", "recusado": "NAO", "erro": "ERR",
                 "ensaio": " . "}.get(it["situacao"], "?")
        extra = ""
        if it.get("cstat"):
            extra = f" [{it['cstat']}] {(it.get('xmotivo') or '')[:60]}"
        elif it.get("xmotivo"):
            extra = f" {it['xmotivo'][:70]}"
        print(f"  {marca} {it['dtemissao']} {(it['nome'] or '')[:28]:<28}"
              f" R$ {it['valor']:>10,.2f}{extra}")

    print(f"\nfila {res['fila']} · autorizados {res['autorizados']}"
          f" · recusados {res['recusados']} · erros {res['erros']}"
          f" · restante {res['restante']}")
    if res["interrompido"]:
        print(f"\nINTERROMPIDO: {res['interrompido']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
