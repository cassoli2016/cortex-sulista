"""Verificacao estrutural do api/static/index.html.

MORA EM scripts/ E NAO EM scratchpad/ DE PROPOSITO: scratchpad/ esta no
.gitignore, entao por duas sessoes seguidas esta verificacao existiu apenas na
maquina de quem a escreveu -- o CLAUDE.md mandava roda-la e o arquivo nao vinha
no checkout. Agora e versionada e roda no CI.

Baseado na descricao do CLAUDE.md, secao 5:

  "Verificacao estrutural (scratchpad/estrutura.py): percorre as telas e falha
   se houver atributo cujo NOME contenha aspa, .val fora de .kpi ou aspa curva
   em class/style."

Motivo (mesma secao): um script que trocou aspas em massa converteu a aspa
DELIMITADORA de template strings de JS, jogando valor/subtitulo para fora do
card. node --check nao pega isso porque aspa curva e caractere valido dentro
de uma string; o smoke tambem nao, porque so conta KPIs.

Roda 3 checagens sobre TODO o arquivo (nao so a secao nova) para provar que a
edicao desta task nao perturbou nenhuma das outras telas:

 1. atributo HTML cujo NOME contem aspa (sinal de tag quebrada por um replace
    que comeu a aspa delimitadora).
 2. classe "val" usada fora de um elemento com classe "kpi" (o valor de KPI
    tem que estar dentro do card certo).
 3. aspas curvas/curvas-tipograficas (" " ' ') dentro do VALOR de class="..."
    ou style="..." (aspa reta e obrigatoria ali; curva so e valida dentro de
    texto visivel/tooltip).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "api" / "static" / "index.html"

CURLY = "“”‘’"


def checar(html: str) -> list[str]:
    erros: list[str] = []

    # 1. atributo cujo NOME contem aspa: sinal de que uma aspa DELIMITADORA foi
    # comida por um replace (ex.: `title="..."` vira `title="...` + o resto do
    # texto engolido ate a proxima aspa literal, e o que sobra depois cola sem
    # espaco no que era pra ser um atributo novo). HTML sempre tem espaco (ou
    # `>`/`/`) entre dois atributos; entao so acusa quando uma aspa fecha um
    # valor e, SEM nenhum espaco, vem "nome=" na sequencia — isso nunca e
    # valido em HTML de verdade. Ignora tags que contenham `${` (expressao de
    # template JS avaliada em runtime, nao e HTML literal no arquivo-fonte).
    for m in re.finditer(r"<[a-zA-Z][a-zA-Z0-9]*\b[^>]*>", html):
        tag = m.group(0)
        if "${" in tag or "`" in tag:
            continue
        for am in re.finditer(r'="[^"]*"([A-Za-z_:][-A-Za-z0-9_:.]*)=', tag):
            erros.append(f"atributo com aspa no nome, perto de: {tag[:160]!r}")

    # 2. .val fora de .kpi: acha toda ocorrencia de class="...val..." e
    # verifica se, voltando ate 400 chars, existe uma abertura de classe kpi
    # ainda nao fechada (heuristica: div mais proximo com class contendo kpi).
    for m in re.finditer(r'<div\b[^>]*class="([^"]*\bval\b[^"]*)"', html):
        antes = html[max(0, m.start() - 400) : m.start()]
        # ultima abertura de div com kpi antes desta ocorrencia
        aberturas_kpi = list(re.finditer(r'<div\b[^>]*class="[^"]*\bkpi\b[^"]*"', antes))
        if not aberturas_kpi:
            erros.append(f".val fora de .kpi, contexto: ...{antes[-120:]}{m.group(0)}")

    # 3. aspa curva dentro do VALOR de class="..." ou style="..."
    for attr in ("class", "style"):
        for m in re.finditer(rf'{attr}="([^"]*)"', html):
            valor = m.group(1)
            achou = [c for c in valor if c in CURLY]
            if achou:
                erros.append(f'aspa curva em {attr}="{valor[:80]}"')

    return erros


def main() -> int:
    html = HTML_PATH.read_text(encoding="utf-8")
    telas = re.findall(r'<section class="view" id="view-([a-zA-Z0-9]+)"', html)
    print(f"telas encontradas: {len(telas)}")
    if "extb" not in telas:
        print("FALHA: secao view-extb nao encontrada")
        return 1
    erros = checar(html)
    if erros:
        print(f"FALHA: {len(erros)} problema(s) estrutural(is):")
        for e in erros[:50]:
            print(" -", e)
        return 1
    print("OK: nenhum atributo com aspa no nome, nenhum .val fora de .kpi, nenhuma aspa curva em class/style.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
