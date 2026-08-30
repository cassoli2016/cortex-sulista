# -*- coding: utf-8 -*-
"""Divide uma tela do painel em sub-abas, sem perder nada no caminho.

POR QUE UMA FERRAMENTA E NAO UM RECORTE A MAO POR TELA
======================================================
Cortar `index.html` por marcador escolhido a olho ja apagou, nesta casa, 20
rotas alheias, o `loadHc`, o `loadMvb` e nove `const` que moravam na cauda de
uma regiao. Foram 23 telas divididas de uma vez em 30/08/2026: repetir o
recorte manual 23 vezes seria repetir a chance de erro 23 vezes.

Uso — sempre `listar()` antes, que e de la que saem os indices:

    uv run --no-sync python scripts/dividir_em_abas.py agr

    from scripts.dividir_em_abas import dividir, desfazer
    dividir("agr", [("vis", "Visao geral", [1, 3]),
                    ("transp", "Transportadores", [2])], cabeca=1)

Aqui o corte e ESTRUTURAL — os blocos de primeiro nivel da `<section>` sao
achados contando `<div>`/`</div>`, nunca por string escolhida — e toda troca
passa por tres conferencias que rodam SEMPRE:

  1. as declaracoes de topo do arquivo inteiro (function/const/let/var/class)
     continuam as mesmas;
  2. os `<h2>` da tela continuam os mesmos, no mesmo numero;
  3. os `id=` da tela continuam os mesmos, no mesmo numero.

A terceira e a que pega o erro que nao da erro: um card que some leva o `id`
que o loader preenche, e o sintoma e uma tela que carrega calada e nao mostra
metade dos numeros.
"""
from __future__ import annotations

import io
import re
from collections import Counter

from pathlib import Path

ARQ = str(Path(__file__).resolve().parent.parent / "api" / "static" / "index.html")
DECL = re.compile(r"^(?:async function|function|const|let|var|class)\s+(\w+)", re.M)


def _secao(s: str, view: str) -> tuple[int, int]:
    m = re.search(r'<section class="view[^"]*" id="view-%s">' % re.escape(view), s)
    if not m:
        raise SystemExit("view-%s nao encontrada" % view)
    return m.end(), s.index("</section>", m.end())


def blocos(corpo: str) -> list[tuple[int, int, str]]:
    """Os blocos de PRIMEIRO NIVEL da secao, por contagem de <div>.

    Devolve (inicio, fim, rotulo) — o rotulo e o primeiro <h2> do bloco, ou a
    classe do div, que e como a chamada os identifica.
    """
    out, i, n = [], 0, len(corpo)
    while i < n:
        j = corpo.find("<div", i)
        if j < 0:
            break
        prof, k = 0, j
        while k < n:
            a = corpo.find("<div", k)
            b = corpo.find("</div>", k)
            if b < 0:
                raise SystemExit("</div> faltando")
            if a >= 0 and a < b:
                prof += 1
                k = a + 4
            else:
                prof -= 1
                k = b + 6
                if prof == 0:
                    break
        bloco = corpo[j:k]
        h2 = re.search(r"<h2>([^<]*)", bloco)
        cls = re.search(r'class="([^"]+)"', bloco)
        rot = (h2.group(1).strip() if h2 else "") or (cls.group(1) if cls else "?")
        out.append((j, k, rot))
        i = k
    return out


def dividir(view: str, abas, grupo=None, cabeca=0, rodape=0, fora=(), seco=False):
    """`abas` = [(chave, rotulo, [indices de bloco]), …]; a PRIMEIRA nasce aberta.

    `cabeca` = quantos blocos do topo ficam FORA das abas (banda de KPI, filtros).
    Indices sao os de `blocos()` — imprima antes com `--listar`.
    """
    grupo = grupo or view
    s = io.open(ARQ, encoding="utf-8").read()
    d0 = Counter(DECL.findall(s))
    ini, fim = _secao(s, view)
    corpo = s[ini:fim]
    bs = blocos(corpo)
    t0 = Counter([" ".join(x.split()) for x in re.findall(r"<h2>([^<]*)", corpo)])
    i0 = Counter(re.findall(r'\bid="([^"]+)"', corpo))

    usados = [i for _, _, ids in abas for i in ids]
    livres = [k for k in range(cabeca, len(bs) - rodape) if k not in fora]
    if sorted(usados) != livres:
        raise SystemExit("blocos fora de aba: %s" % sorted(
            set(livres) - set(usados)))
    if len(usados) != len(set(usados)):
        raise SystemExit("bloco repetido em duas abas")

    ident = lambda t, n: "\n".join((" " * n + l) if l.strip() else l
                                   for l in t.rstrip("\n").split("\n"))
    tabs = ['        <div class="subtabs" role="tablist" data-abas="%s" '
            'aria-label="Se\u00e7\u00f5es desta tela">' % grupo]
    for p, (chave, rot, _) in enumerate(abas):
        tabs.append('          <button role="tab" id="tab%s-%s" data-aba="%s" '
                    'aria-controls="aba-%s-%s" aria-selected="%s" '
                    'onclick="abaTrocar(\'%s\',\'%s\')">%s</button>'
                    % (grupo, chave, chave, grupo, chave,
                       "true" if p == 0 else "false", grupo, chave, rot))
    tabs.append("        </div>")

    corpos = []
    for p, (chave, _, ids) in enumerate(abas):
        dentro = "\n".join(ident(corpo[bs[i][0]:bs[i][1]], 2) for i in ids)
        corpos.append('        <div class="aba" data-abas="%s" data-aba="%s" '
                      'id="aba-%s-%s" role="tabpanel" aria-labelledby="tab%s-%s"%s>\n'
                      % (grupo, chave, grupo, chave, grupo, chave,
                         "" if p == 0 else " hidden")
                      + dentro + "\n        </div>")

    novo = ((corpo[:bs[cabeca][0]] if cabeca else corpo[:bs[0][0]])
            + "".join(corpo[bs[k][0]:bs[k][1]] + "\n        "
                      for k in sorted(fora))
            + "\n".join(tabs) + "\n" + "\n".join(corpos) + "\n")
    # O RODAPE fica FORA das abas: banner de aviso que vale para a tela toda
    # nao pode depender de qual aba esta aberta.
    novo += "".join(corpo[bs[i][0]:bs[i][1]] + "\n"
                    for i in range(len(bs) - rodape, len(bs))) + "      "
    t1 = Counter([" ".join(x.split()) for x in re.findall(r"<h2>([^<]*)", novo)])
    if t0 != t1:
        raise SystemExit("h2 mudou: sumiu %s / sobrou %s" % (t0 - t1, t1 - t0))
    # O `id` so pode CRESCER: a estrutura da aba traz ids novos, de proposito.
    # O que nao pode e um id SUMIR — ele e o que o loader preenche, e a tela
    # carregaria calada, sem metade dos numeros.
    i1 = Counter(re.findall(r'\bid="([^"]+)"', novo))
    if i0 - i1:
        raise SystemExit("id sumiu: %s" % (i0 - i1))
    if any(v > 1 for v in i1.values()):
        raise SystemExit("id repetido: %s" % [k for k, v in i1.items() if v > 1])
    s2 = s[:ini] + novo + s[fim:]
    d1 = Counter(DECL.findall(s2))
    if d0 != d1:
        raise SystemExit("declaracoes mudaram: %s" % (d0 - d1))
    if not seco:
        io.open(ARQ, "w", encoding="utf-8").write(s2)
    print("%-9s %d abas · %d blocos · h2 e id conferidos · sumiram: nenhuma"
          % (view, len(abas), len(bs) - cabeca - rodape))


def listar(view: str):
    s = io.open(ARQ, encoding="utf-8").read()
    ini, fim = _secao(s, view)
    for i, (a, b, rot) in enumerate(blocos(s[ini:fim])):
        print("  [%d] %5d linhas  %s" % (i, s[ini:fim][a:b].count("\n") + 1, rot))


def desfazer(view: str):
    """Achata a tela de volta: tira `.subtabs` e desembrulha os `.aba`.

    Existe porque REBALANCEAR e o caso normal — a primeira divisao quase nunca
    acerta a altura de cada aba, e sem isto a segunda tentativa aninharia aba
    dentro de aba, que e o jeito de perder um card sem ninguem ver.
    """
    s = io.open(ARQ, encoding="utf-8").read()
    d0 = Counter(DECL.findall(s))
    ini, fim = _secao(s, view)
    corpo = s[ini:fim]
    t0 = Counter([" ".join(x.split()) for x in re.findall(r"<h2>([^<]*)", corpo)])
    novo, mexeu = [], 0
    for a, b, _ in blocos(corpo):
        bloco = corpo[a:b]
        if bloco.lstrip().startswith('<div class="subtabs"'):
            mexeu += 1
            continue
        if bloco.lstrip().startswith('<div class="aba"'):
            mexeu += 1
            dentro = bloco[bloco.index(">") + 1:bloco.rindex("</div>")]
            novo.append("\n".join(l[2:] if l.startswith("  ") else l
                                  for l in dentro.strip("\n").split("\n")))
            continue
        novo.append(bloco)
    if not mexeu:
        raise SystemExit("%s nao tem aba" % view)
    saida = corpo[:blocos(corpo)[0][0]] + "\n".join(novo) + "\n      "
    t1 = Counter([" ".join(x.split()) for x in re.findall(r"<h2>([^<]*)", saida)])
    if t0 != t1:
        raise SystemExit("h2 mudou ao achatar: %s" % (t0 - t1))
    s2 = s[:ini] + saida + s[fim:]
    if d0 != Counter(DECL.findall(s2)):
        raise SystemExit("declaracoes mudaram")
    io.open(ARQ, "w", encoding="utf-8").write(s2)
    print("%-9s achatada (%d envolucros removidos)" % (view, mexeu))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("uso: dividir_em_abas.py <view>   (lista os blocos)")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    listar(sys.argv[1])
