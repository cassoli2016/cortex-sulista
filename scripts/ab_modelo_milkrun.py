# scripts/ab_modelo_milkrun.py
"""A/B de modelos locais no chat do Milk Run.

Roda as MESMAS perguntas, com o MESMO contexto, contra dois modelos do Ollama
e mostra resposta e tempo lado a lado.

Por que existe: a escolha de modelo estava saindo de impressao. Aqui cada
pergunta tem um GABARITO calculado em Python a partir do proprio contexto, e o
script confere se a resposta contem os fatos certos - nao se ela "parece boa".
Modelo que escreve bonito e erra a placa e pior que modelo seco e certo.

Uso:
  uv run python scripts/ab_modelo_milkrun.py [--de AAAA-MM-DD] [--ate AAAA-MM-DD]
                                             [--modelos a,b]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from api import copiloto as cop            # noqa: E402
from api.milkrun import copiloto as mk     # noqa: E402


def _pergunta_ao(modelo: str, msgs: list[dict], timeout: int = 300) -> tuple[str, float]:
    corpo = json.dumps({"model": modelo, "messages": msgs, "stream": False,
                        "options": cop._OLLAMA_OPTS,
                        "keep_alive": cop._OLLAMA_KEEP}).encode()
    req = urllib.request.Request(f"{cop.ollama_url()}/api/chat", data=corpo,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return (d.get("message") or {}).get("content", ""), time.time() - t


def _gabaritos(ctx: dict) -> list[dict]:
    """Perguntas + os FATOS que a resposta certa tem de conter.

    Os fatos saem do proprio contexto, entao o gabarito nunca envelhece junto
    com o dado - o que estaria errado e conferir contra numero escrito a mao.
    """
    rk = ctx.get("ranking_fornecedores_por_permanencia") or []
    pts = [(p, c) for c in ctx.get("coletas", []) for p in c.get("pontos", [])]
    atrasos = [(p.get("atraso_min"), c["coleta"], c["placa"])
               for p, c in pts if p.get("atraso_min") is not None]
    pior = max(atrasos)[1:] if atrasos else None
    perms = [(p.get("permanencia_min"), p.get("local"))
             for p, _ in pts if p.get("permanencia_min") is not None]
    maior_perm = max(perms)[1] if perms else None

    casos = []
    if rk:
        casos.append({
            "pergunta": "Top 5 fornecedores em tempo médio parado para coletar",
            "fatos": [x["local"].split("-")[0].strip()[:18] for x in rk[:3]],
            "nota": "os 3 primeiros do ranking, na ordem",
        })
    if pior:
        casos.append({
            "pergunta": "Qual coleta teve o maior atraso e de quanto foi?",
            "fatos": [str(pior[0]), str(pior[1])],
            "nota": "numero da coleta e placa",
        })
    if maior_perm:
        casos.append({
            "pergunta": "Em qual ponto o veículo ficou mais tempo parado?",
            "fatos": [maior_perm.split("-")[0].strip()[:18]],
            "nota": "o fornecedor da maior permanencia",
        })
    casos.append({
        "pergunta": "Qual foi o faturamento da empresa no mês passado?",
        "fatos": ["Copiloto"],
        "nota": "FORA DE ESCOPO: tem de recusar e apontar o Copiloto Cortex",
    })
    return casos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--de")
    ap.add_argument("--ate")
    ap.add_argument("--modelos", default="gemma4,qwen2.5:7b-instruct")
    a = ap.parse_args()
    modelos = [m.strip() for m in a.modelos.split(",") if m.strip()]

    ctx = mk.contexto(a.de, a.ate)
    tam = len(json.dumps(ctx, ensure_ascii=False, default=str))
    casos = _gabaritos(ctx)
    print(f"contexto: {tam} chars · periodo {ctx['periodo']} · "
          f"{ctx.get('pontos_com_permanencia_medida')} pontos com medida")
    print(f"modelos : {', '.join(modelos)}")
    print("=" * 100)

    placar = {m: {"acertos": 0, "total": 0, "seg": 0.0} for m in modelos}
    for caso in casos:
        print(f"\nPERGUNTA: {caso['pergunta']}")
        print(f"  gabarito ({caso['nota']}): {caso['fatos']}")
        msgs = mk.mensagens([{"role": "user", "content": caso["pergunta"]}], ctx)
        for m in modelos:
            try:
                txt, seg = _pergunta_ao(m, msgs)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{m}] ERRO: {exc}")
                continue
            norm = txt.lower()
            faltando = [f for f in caso["fatos"] if f.lower() not in norm]
            ok = not faltando
            placar[m]["total"] += 1
            placar[m]["acertos"] += 1 if ok else 0
            placar[m]["seg"] += seg
            print(f"  [{m}] {seg:5.1f}s  {'OK ' if ok else 'ERROU'}"
                  + (f"  (faltou: {faltando})" if faltando else ""))
            print("      " + " ".join(txt.split())[:260])

    print("\n" + "=" * 100)
    print(f"{'modelo':<28}{'acertos':>10}{'tempo medio':>14}")
    for m, p in placar.items():
        if p["total"]:
            print(f"{m:<28}{p['acertos']}/{p['total']:>8}"
                  f"{p['seg']/p['total']:>13.1f}s")


if __name__ == "__main__":
    main()
