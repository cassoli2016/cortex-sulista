# -*- coding: utf-8 -*-
"""Importa para a recolha o XML que o ERP JA TEM guardado.

    uv run python scripts/importar_xml_erp.py --de 2026-09-01 --ate 2026-09-30
    uv run python scripts/importar_xml_erp.py --de 2026-01-01 --ate 2026-12-31
    uv run python scripts/importar_xml_erp.py --de 2026-09-01 --dry-run

A TERCEIRA FONTE, E A UNICA QUE ALCANCA O PASSADO
=================================================

A SEFAZ retem cerca de 90 dias na Distribuicao de DFe: o que e mais velho que
isso nao existe mais para ser buscado, por nenhum caminho automatico. A caixa
de e-mail so tem o que as pessoas mandaram de la para ca.

O ERP tem SEIS ANOS. `public.xmldocumentoeletronico` guarda 921.606 documentos
com `chaveacesso` e `conteudoxml`, de 02/07/2020 ate hoje -- NF-e (tipo 12) e
CT-e (tipo 6), todos como `nfeProc`/`cteProc`, ou seja, COM o protocolo de
autorizacao. Ele os recebe pelo proprio importador de e-mail dele
(`public.xmlrecebido`: 258 mil mensagens, de nfe@mwm.com.br, NFE@TUPY.COM.BR,
mastersaf, WiserLog...), que e o mesmo fluxo que hoje chega em
xml@sulista.com.br.

Nao ha nada a "conseguir" da SEFAZ para 2026: **o acervo ja estava em casa.**

POR QUE ISTO E UM SCRIPT, E NAO UM MODULO DE `api/sefaz/`
--------------------------------------------------------

**A recolha nao depende do ERP, e isso e REQUISITO** (decisao de quem opera,
07/09/2026): o modulo e do TMS Cortex e vai rodar independente do AVA.
`tests/sefaz/test_independencia.py` cobra que nenhum arquivo do nucleo importe
`api.db`.

Entao este importador vive aqui fora e se comporta como mais um REMETENTE da
segunda porta: ele le o ERP e entrega o XML para `arquivo.guardar()`,
exatamente como a caixa de e-mail entrega. Apagar este script nao tira nada do
lugar -- e e assim que o modulo continua se copiando para o TMS.

O QUE ELE NAO IMPORTA
---------------------

Documento cuja chave JA ESTA guardada como completa. O mesmo XML vindo da SEFAZ
e vindo do ERP nao e byte a byte igual (formatacao, espacos), entao o `sha256`
nao os funde -- e sem esta conferencia por CHAVE a tela mostraria a mesma nota
duas vezes, uma por porta. A pergunta que importa e "eu tenho o XML autorizado
desta nota?", e ela se responde uma vez so.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from api import db, pglocal  # noqa: E402
from api.sefaz import armazenamento as arm, arquivo  # noqa: E402

#: `tipodocumento` no ERP -> o que e. Medido em 08/09/2026 lendo a RAIZ do XML
#: de uma amostra de cada tipo, e nao chutado a partir do nome: 6 abre com
#: `<cteProc>` e chave de modelo 57; 12 abre com `<nfeProc>` e modelo 55.
#: Codigo sem tabela de dominio nao vira rotulo inventado -- este veio de
#: evidencia dentro do proprio documento.
TIPOS = {6: "CT-e", 12: "NF-e", 142: "(raro)"}

#: Linhas por lote. O ERP e replica de producao de TERCEIRO e o `conteudoxml`
#: tem ~10 KB: 500 linhas sao ~5 MB por ida, que e o tamanho em que a consulta
#: responde rapido e nao segura conexao.
LOTE = 500

#: Paginacao por KEYSET (`chaveacesso > ultima`), e nao por OFFSET. Com OFFSET,
#: a consulta relê tudo o que ja passou a cada pagina -- na pagina 300 isso e
#: 150 mil linhas relidas para devolver 500.
_SQL = """
SELECT chaveacesso, tipodocumento, dataemissao, conteudoxml
  FROM xmldocumentoeletronico
 WHERE dataemissao >= %s AND dataemissao < (%s::date + 1)
   AND chaveacesso IS NOT NULL
   AND conteudoxml IS NOT NULL
   AND chaveacesso > %s
 ORDER BY chaveacesso
 LIMIT %s
"""


def _ja_completas(chaves: list[str]) -> set[str]:
    """As chaves que JA tem XML completo guardado, nas duas portas.

    UMA consulta por lote, e nao uma por documento: 500 documentos virariam
    500 idas ao banco para descobrir que nao ha nada a fazer.
    """
    if not chaves:
        return set()
    achadas: set[str] = set()
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT chave FROM dfe_documento "
                    "WHERE completo AND chave = ANY(%s)", (chaves,))
        achadas |= {r["chave"] for r in cur.fetchall()}
        if arm.tem_tabela_arquivo():
            cur.execute("SELECT DISTINCT chave FROM dfe_arquivo "
                        "WHERE completo AND chave = ANY(%s)", (chaves,))
            achadas |= {r["chave"] for r in cur.fetchall()}
    return achadas


def _arg(argv: list[str], flag: str, padrao: str = "") -> str:
    if flag not in argv:
        return padrao
    i = argv.index(flag)
    return argv[i + 1] if i + 1 < len(argv) else padrao


def main(argv: list[str]) -> int:
    de = _arg(argv, "--de", date.today().replace(day=1).isoformat())
    ate = _arg(argv, "--ate", date.today().isoformat())
    seco = "--dry-run" in argv
    try:
        teto = int(_arg(argv, "--limite", "0"))
    except ValueError:
        teto = 0

    print("importando o XML que o ERP ja tem: %s ate %s%s"
          % (de, ate, "  (DRY-RUN, nao grava)" if seco else ""))
    print()

    ultima = ""
    lidos = novos = repetidos = pulados = recusados = 0
    t0 = time.monotonic()
    while True:
        t = time.monotonic()
        linhas = db.query(_SQL, (de, ate, ultima, LOTE))
        if not linhas:
            break
        ultima = dict(linhas[-1])["chaveacesso"]
        lidos += len(linhas)

        pares = [(dict(l)["chaveacesso"] or "").strip() for l in linhas]
        completas = _ja_completas([p for p in pares if p])

        for l in linhas:
            d = dict(l)
            chave = (d["chaveacesso"] or "").strip()
            if chave in completas:
                pulados += 1
                continue
            try:
                doc = arquivo.ler(d["conteudoxml"])
            except arquivo.NaoEDocumento as exc:
                recusados += 1
                if recusados <= 5:
                    print("   recusado (%s): %s" % (chave[-6:], exc))
                continue
            if seco:
                novos += 1
                continue
            estado = arquivo.guardar(
                doc, origem="erp", arquivo_nome="ERP %s" % TIPOS.get(
                    d["tipodocumento"], d["tipodocumento"]),
                remetente="xmldocumentoeletronico",
                assunto="importado do AVA")
            if estado == "novo":
                novos += 1
            else:
                repetidos += 1

        print("   %6d lidos · %6d novos · %6d ja tinha · %6d repetidos "
              "· %d recusados   (lote em %.1fs)"
              % (lidos, novos, pulados, repetidos, recusados,
                 time.monotonic() - t))
        if teto and lidos >= teto:
            print("   teto de --limite atingido")
            break

    print()
    print("=" * 62)
    print("lidos do ERP : %d" % lidos)
    print("guardados    : %d" % novos)
    print("ja tinha     : %d (chave com XML completo nas outras portas)" % pulados)
    print("repetidos    : %d (mesmo arquivo, ja importado antes)" % repetidos)
    print("recusados    : %d (nao se declara documento fiscal na raiz)" % recusados)
    print("tempo        : %.1f min" % ((time.monotonic() - t0) / 60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
