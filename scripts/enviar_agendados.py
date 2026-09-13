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

from api.agendamento import deve_rodar_intervalo  # noqa: E402
from api.correio import agenda, monitoramento, relatorios  # noqa: E402
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


def _monitoramentos(ensaio: bool) -> tuple[int, int, int]:
    """Os monitoramentos de cliente (a cada N horas), na MESMA tarefa.

    Mesma tarefa e não uma nova de propósito: a tarefa já dispara de 15 em 15
    minutos, que cabe folgado numa grade de 1 a 6 horas, e uma segunda tarefa
    agendada seria uma segunda coisa para instalar, vigiar e esquecer. Quem
    decide se é a rodada é `agendamento.deve_rodar_intervalo`.

    Falhar ao LER a lista não derruba os relatórios da agenda: são dois
    cadastros, e um não pode calar o outro.
    """
    try:
        mons = monitoramento.listar()
    except Exception as exc:  # noqa: BLE001
        print(f"nao foi possivel ler os monitoramentos: {type(exc).__name__}")
        return 0, 0, 1
    enviados = falhas = 0
    for m in mons:
        pode, porque = deve_rodar_intervalo(m)
        rot = m.get("cliente_nome") or m["cliente_raiz"]
        if not pode:
            print(f" --   monitoramento #{m['id']} {rot}: {porque}")
            continue
        linha = monitoramento.rodar(m, ensaio=ensaio)
        print(linha)
        if linha.startswith("OK"):
            enviados += 1
        elif linha.startswith("FALHA"):
            falhas += 1
    return len(mons), enviados, falhas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true",
                    help="percorre tudo e NÃO envia")
    ap.add_argument("--forcar", type=int, metavar="ID",
                    help="envia este agendamento agora, fora do horário")
    ap.add_argument("--forcar-monitoramento", type=int, metavar="ID",
                    help="envia este monitoramento de cliente agora")
    a = ap.parse_args()

    # O CALENDÁRIO SE MANTÉM SOZINHO: esta rotina já roda de 15 em 15 minutos,
    # e é ela que decide "dia útil". Busca na web o ano corrente e o próximo
    # quando faltam (uma tentativa por dia); falha aqui NUNCA segura o envio —
    # sem a busca, vale a lista federal da lei.
    if not a.ensaio:
        try:
            from api import calendario
            for linha in calendario.garantir():
                print(linha)
        except Exception as exc:  # noqa: BLE001
            print(f"calendario: {type(exc).__name__}: {exc}")
    if a.forcar_monitoramento:
        m = monitoramento.um(a.forcar_monitoramento)
        if not m:
            print(f"monitoramento {a.forcar_monitoramento} nao existe")
            return 1
        print(monitoramento.rodar(m, ensaio=a.ensaio, forcado=True))
        return 0

    try:
        itens = agenda.listar()
    except Exception as exc:  # noqa: BLE001
        print(f"nao foi possivel ler a agenda: {type(exc).__name__}: {exc}")
        itens = None

    if a.forcar:
        alvo = [x for x in (itens or []) if int(x["id"]) == a.forcar]
        if not alvo:
            print(f"agendamento {a.forcar} nao existe")
            return 1
        print(_uma(alvo[0], ensaio=a.ensaio, forcado=True))
        return 0

    enviados = falhas = 0
    if itens == []:
        print("nenhum agendamento cadastrado")
    for ag in itens or []:
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

    n_mon, env_mon, fal_mon = _monitoramentos(a.ensaio)
    if itens is None:
        falhas += 1

    print(f"\n{len(itens or [])} agendamento(s) · {n_mon} monitoramento(s) · "
          f"{enviados + env_mon} enviado(s) · {falhas + fal_mon} falha(s)")
    falhas += fal_mon
    # Sai com erro so quando houve FALHA de envio: "nao era hora" e o caso
    # normal, e marca-lo como falha encheria o historico do agendador do
    # Windows de vermelho a cada disparo.
    return 2 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
