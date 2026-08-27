"""Percorre a agenda e envia o que está na hora.

Chamado pelo agendador do Windows de tempos em tempos. Ele NÃO decide nada:
quem diz se é hora é o CÓRTEX, lendo o horário configurado na tela — assim
mudar o horário vale na hora, sem reinstalar tarefa.

Uso:
  uv run --no-sync python scripts/enviar_agendados.py            # de verdade
  uv run --no-sync python scripts/enviar_agendados.py --ensaio   # não envia
  uv run --no-sync python scripts/enviar_agendados.py --forcar 3 # agora, id 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.correio import agenda, relatorios  # noqa: E402
from api.correio.envio import enviar  # noqa: E402

ORIGEM = "agenda"


def _uma(ag: dict, *, ensaio: bool, forcado: bool = False) -> str:
    """Envia UM agendamento e devolve o resultado em uma linha."""
    rel = ag.get("relatorio")
    try:
        r = relatorios.montar(rel)
    except Exception as exc:  # noqa: BLE001
        # `montar` so levanta para id desconhecido - erro de configuracao, nao
        # de dado. Vale marcar a passagem assim mesmo: sem isso a rotina
        # tentaria de novo a cada disparo e encheria o log com o mesmo erro.
        if not ensaio:
            agenda.registrar_execucao(ag["id"], f"ERRO: {exc}")
        return f"ERRO  #{ag['id']} {rel}: {exc}"

    pular = (relatorios.CATALOGO.get(rel, {}).get("pular_vazio")
             and r.get("vazio"))
    if pular:
        # Marca a passagem MESMO sem enviar: e a passagem que impede o reenvio
        # a cada disparo do agendador, nao o envio.
        if not ensaio:
            agenda.registrar_execucao(ag["id"], "sem conteúdo — não enviado")
        return f" --   #{ag['id']} {rel}: nada a relatar, não enviado"

    if ensaio:
        return (f" .    #{ag['id']} {rel}: enviaria para "
                f"{ag['destinatarios']} — “{r['assunto']}”")

    res = enviar(ag["destinatarios"], r["assunto"], r["texto"],
                 corpo_html=r["html"], usuario=ORIGEM,
                 origem=f"{ORIGEM}:{rel}" + (":forcado" if forcado else ""))
    agenda.registrar_execucao(
        ag["id"], "enviado" if res["ok"] else f"falhou: {res['erro'][:150]}")
    marca = "OK  " if res["ok"] else "FALHA"
    extra = "" if res["ok"] else f" — {res['erro'][:120]}"
    return f"{marca} #{ag['id']} {rel} → {ag['destinatarios']}{extra}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true",
                    help="percorre tudo e NÃO envia")
    ap.add_argument("--forcar", type=int, metavar="ID",
                    help="envia este agendamento agora, fora do horário")
    a = ap.parse_args()

    try:
        itens = agenda.listar()
    except Exception as exc:  # noqa: BLE001
        print(f"nao foi possivel ler a agenda: {type(exc).__name__}: {exc}")
        return 1

    if a.forcar:
        alvo = [x for x in itens if int(x["id"]) == a.forcar]
        if not alvo:
            print(f"agendamento {a.forcar} nao existe")
            return 1
        print(_uma(alvo[0], ensaio=a.ensaio, forcado=True))
        return 0

    if not itens:
        print("nenhum agendamento cadastrado")
        return 0

    enviados = falhas = 0
    for ag in itens:
        pode, porque = agenda.deve_rodar(ag)
        if not pode:
            print(f" --   #{ag['id']} {ag['relatorio']}: {porque}")
            continue
        linha = _uma(ag, ensaio=a.ensaio)
        print(linha)
        if linha.startswith("OK"):
            enviados += 1
        elif linha.startswith(("FALHA", "ERRO")):
            falhas += 1

    print(f"\n{len(itens)} agendamento(s) · {enviados} enviado(s) · "
          f"{falhas} falha(s)")
    # Sai com erro so quando houve FALHA de envio: "nao era hora" e o caso
    # normal, e marca-lo como falha encheria o historico do agendador do
    # Windows de vermelho a cada disparo.
    return 2 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
