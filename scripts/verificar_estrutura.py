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

    # 0. BYTE DE CONTROLE no arquivo. Custou um commit inteiro em 31/08/2026:
    # um script de edicao deixou um `\x00` onde devia haver um espaco, dentro
    # de uma string de JavaScript. O estrago tem tres camadas, e nenhuma
    # aparece como erro:
    #
    #   - o `node --check` ACEITA NUL dentro de string, entao passou;
    #   - com NUL, o git classifica o arquivo como BINARIO (`ls-files --eol`
    #     diz `i/-text`) e para de normalizar quebra de linha -- foi assim que
    #     o `index.html` entrou em CRLF com `core.autocrlf=true` ligado, e toda
    #     branch aberta antes disso conflitou no arquivo INTEIRO;
    #   - o valor VIAJAVA: aquela string virava `chapa=%00sem-correspondencia`
    #     na query string do `fetch`. O backend aguentou (medido: mesmo
    #     resultado com e sem o NUL), mas null byte em URL e padrao classico de
    #     ataque e WAF costuma barrar -- e ai o proxy responde no lugar da API,
    #     que e a familia de defeito mais cara de diagnosticar nesta casa.
    #
    # Uma linha de guarda contra as tres. `\t`, `\n` e `\r` sao legitimos.
    for i, ch in enumerate(html):
        if ch in "\t\n\r" or ord(ch) >= 32:
            continue
        erros.append(
            "byte de controle U+%04X na posicao %d — o git passa a tratar o "
            "arquivo como BINARIO (sem normalizar quebra de linha) e o valor "
            "ainda viaja para a URL. Contexto: %r"
            % (ord(ch), i, html[max(0, i - 40):i + 40]))
        if len(erros) > 5:      # cinco bastam para achar a origem
            break

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

    # 4. LITERAL DE COR onde o tema precisa virar.
    #
    # A auditoria de tema (`scripts/auditar_tema.py`) so enxerga o que esta NA
    # TELA, e la a API e dublada: linha de tabela, chip e badge desenhados por
    # JavaScript a partir de dado nao existem no momento da varredura. Foi
    # exatamente ali que passou o `background:#FFF7E6` da linha "a decidir" da
    # classificacao de ocorrencia — creme quase branco no tema escuro, sob
    # texto claro, linha inteira ilegivel.
    #
    # Entao o literal e proibido por LEITURA DO FONTE, que enxerga o que a
    # varredura nao alcanca. Duas excecoes, e as duas sao deliberadas:
    #   - o painel de TV, escuro nos dois temas de proposito;
    #   - cor com transparencia (`rgba`), que TINGE o fundo em vez de
    #     substitui-lo e por isso funciona nos dois.
    fora = [m.start() for m in re.finditer(r"#view-tv|tv-|painel de TV", html)]
    for m in re.finditer(r'style="([^"]*background:\s*#[0-9A-Fa-f]{3,8}[^"]*)"', html):
        trecho = html[max(0, m.start() - 260):m.start()]
        if "class=\"sw" in html[m.start() - 40:m.start()]:
            erros.append("cor literal no quadradinho de legenda (a serie do "
                         "grafico vira com o tema e ele nao): %s" % m.group(1)[:70])
        elif "tv-" not in trecho and "tvw" not in trecho:
            erros.append("cor literal em style= fora do painel de TV — use o "
                         "token, senao o tema escuro nao vira: %s" % m.group(1)[:70])

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
    print("OK: nenhum byte de controle, nenhum atributo com aspa no nome, "
          "nenhum .val fora de .kpi, nenhuma aspa curva em class/style.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
