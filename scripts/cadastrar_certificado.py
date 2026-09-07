# -*- coding: utf-8 -*-
"""Cadastra o certificado A1 da SULISTA no cofre da casa.

COMO USAR (a senha nunca aparece na tela nem em log nenhum):

    uv run python scripts/cadastrar_certificado.py data/certificados/76104397000123.pfx

POR QUE ISTO E UM SCRIPT DE TERMINAL, E NAO UMA TELA
====================================================

A tela de cadastro que existe (`api/contrapartida/`) e dos AGREGADOS: ela
carrega o .pfx pelo navegador porque quem cadastra e quem opera, de qualquer
maquina. Este certificado e outro caso:

  - e o certificado da PROPRIA empresa, cadastrado UMA vez;
  - a maquina do painel E a maquina onde o arquivo ja esta;
  - subir um .pfx por HTTP para cadastra-lo na mesma maquina em que ele mora e
    passear com o segredo por um caminho a mais sem ganho nenhum.

A SENHA NAO PASSA POR ARGUMENTO, e isso e deliberado: argumento de linha de
comando entra no historico do shell, aparece na lista de processos e vaza para
qualquer coisa que audite comandos.

DOIS CAMINHOS, e nenhum dos dois e o argumento:

  1. TERMINAL DE VERDADE -> `getpass`, que nao ecoa. E o caminho normal.

  2. TERMINAL SEM TTY (o `!` do Claude Code, um pipe, uma tarefa agendada) ->
     `--senha-arquivo CAMINHO`. O script LE e APAGA o arquivo na mesma
     execucao, antes de qualquer outra coisa.

     Isto existe porque `getpass` sem TTY nao da erro: ele PENDURA, esperando
     para sempre um teclado que nao existe. "Ta dando erro" era isso -- e um
     travamento mudo e pior que uma mensagem, porque nao diz o que fazer.

O QUE ELE CONFERE ANTES DE GRAVAR
---------------------------------

Reusa `api/contrapartida/certificado.py` inteiro -- e nao reimplementa nada.
Aquele modulo ja aprendeu, com arquivos reais, a diferenca entre "senha errada"
e ".p12 em RC2 de 1998 que esta maquina nao abre nem com a senha certa", entre
"arquivo truncado" e "voce mandou o .cer publico". Errar aqui custaria a mesma
noite de novo.

Alem disso confere o que so importa para a recolha de NF: se o CNPJ DENTRO do
certificado bate com o do nome do arquivo, e se o certificado ainda vale.
Certificado errado consulta a caixa de entrada de outra empresa -- e isso nao
aparece em conferencia nenhuma depois.
"""
from __future__ import annotations

import getpass
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from api.contrapartida import certificado as cert  # noqa: E402
from api import segredo_arquivo  # noqa: E402

DIR_CERT = RAIZ / "data" / "certificados"
SENHAS = DIR_CERT / "senhas.json"


def _so_digitos(t: str) -> str:
    return re.sub(r"[^0-9]", "", t or "")


def _senha_de_arquivo(caminho: Path) -> str:
    """Le a senha do arquivo e o APAGA. Le em BYTES e decodifica na mao: um
    arquivo salvo pelo Bloco de Notas vem com BOM, e o BOM colado na senha faz
    o `.pfx` recusar com "senha incorreta" de um jeito invisivel."""
    bruto = caminho.read_bytes()
    try:
        caminho.unlink()
    except OSError as exc:  # pragma: no cover
        print("AVISO: nao consegui apagar %s (%s) — apague a mao."
              % (caminho, type(exc).__name__))
    for cod in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return bruto.decode(cod).strip("\r\n")
        except UnicodeDecodeError:
            continue
    return bruto.decode("utf-8", errors="replace").strip("\r\n")


def _pedir_senha(argv: list[str]) -> str | None:
    if "--senha-arquivo" in argv:
        i = argv.index("--senha-arquivo")
        if i + 1 >= len(argv):
            print("ERRO: --senha-arquivo precisa do caminho do arquivo.")
            return None
        arq = Path(argv[i + 1])
        if not arq.exists():
            print("ERRO: nao achei o arquivo da senha: %s" % arq)
            return None
        return _senha_de_arquivo(arq)

    if "--digitar" in argv:
        return getpass.getpass("Senha do certificado (nao aparece): ")

    # DIGITAR NAO E O PADRAO, e a razao e concreta: no Windows o `getpass` le
    # do CONSOLE por `msvcrt`, ignorando o stdin redirecionado -- e
    # `sys.stdin.isatty()` responde True mesmo com `< /dev/null`. Ou seja: nao
    # da para DETECTAR de forma confiavel se ha teclado, e a falha nao e um
    # erro, e um travamento MUDO esperando para sempre.
    #
    # Entre "pendura sem dizer nada" e "pede uma bandeira a mais", a segunda
    # perde dois segundos e a primeira perde a tarde.
    print("ERRO: falta dizer de onde vem a senha.")
    print()
    print("  Terminal SEM teclado (o `!` do Claude Code, pipe, tarefa)")
    print("  -- o script LE e APAGA o arquivo:")
    print()
    print("      printf %s 'SUA_SENHA' > /tmp/s.txt")
    print("      <este script> <o .pfx> --senha-arquivo /tmp/s.txt")
    print()
    print("  Terminal de verdade:")
    print()
    print("      <este script> <o .pfx> --digitar")
    print()
    print("Nao existe opcao de passar a senha por argumento: ela ficaria no")
    print("historico do shell e na lista de processos.")
    return None


def main(argv: list[str]) -> int:
    posicionais = [a for a in argv[1:] if not a.startswith("--")]
    if "--senha-arquivo" in argv:
        i = argv.index("--senha-arquivo")
        if i + 1 < len(argv) and argv[i + 1] in posicionais:
            posicionais.remove(argv[i + 1])
    if len(posicionais) != 1:
        print(__doc__.split("POR QUE")[0].strip())
        return 2

    caminho = Path(posicionais[0])
    if not caminho.is_absolute():
        caminho = (RAIZ / caminho).resolve()
    if not caminho.exists():
        print("ERRO: nao achei o arquivo: %s" % caminho)
        print("      Copie o .pfx para %s com o nome sendo o CNPJ de 14"
              % DIR_CERT)
        print("      digitos, sem pontuacao. Ex.: 76104397000123.pfx")
        return 1

    cnpj_do_nome = _so_digitos(caminho.stem)
    if len(cnpj_do_nome) != 14:
        print("ERRO: o nome do arquivo tem de ser o CNPJ de 14 digitos.")
        print("      Achei %r em %s" % (cnpj_do_nome, caminho.name))
        return 1

    bruto = caminho.read_bytes()
    print("arquivo   : %s (%d KB)" % (caminho.name, len(bruto) // 1024))
    print("CNPJ (nome): %s" % cnpj_do_nome)
    print()

    # A SENHA NAO ECOA, e nao vem de argumento. Ver o docstring.
    senha = _pedir_senha(argv)
    if senha is None:
        return 1
    if not senha:
        print("ERRO: senha vazia.")
        return 1

    try:
        meta = cert.ler(bruto, senha)
    except cert.CertificadoInvalido as exc:
        print()
        print("ERRO: %s" % exc)
        return 1

    boa = cert.senha_que_abre(bruto, senha)
    if boa is None:  # pragma: no cover - `ler` ja teria levantado
        print("ERRO: o certificado abriu mas a senha nao foi identificada.")
        return 1
    if boa != senha:
        # AVISAR QUAL VARIANTE ABRIU, em vez de so aceitar: um espaco colado ao
        # copiar do e-mail e invisivel, e gravar a DIGITADA faria a consulta
        # falhar meses depois, longe da causa.
        print("AVISO: a senha digitada tinha espaco ou codificacao diferente; "
              "gravando a variante que ABRE o arquivo.")

    # OS NOMES DOS CAMPOS SAO OS DE `certificado.ler()`, e nao um chute com
    # `or` em cima de tres variantes. A primeira versao aqui tentava
    # `valido_ate`/`nao_depois`/`validade` -- nenhum dos tres existe (o campo e
    # `valida_ate`) e o script imprimiu "valido ate : None" sem reclamar de
    # nada. Chute encadeado com `or` NAO falha: ele so mente mais baixo.
    cnpj_cert = _so_digitos(str(meta.get("cnpj") or ""))
    titular = meta.get("titular") or "?"
    ate = meta.get("valida_ate")
    dias = meta.get("dias")

    print()
    print("titular    : %s" % titular)
    print("CNPJ (cert): %s" % (cnpj_cert or "(nao encontrado)"))
    print("validade   : %s a %s" % (meta.get("valida_de"), ate))

    if cnpj_cert and cnpj_cert != cnpj_do_nome:
        print()
        print("ERRO: o CNPJ DENTRO do certificado (%s) nao e o do nome do "
              "arquivo (%s)." % (cnpj_cert, cnpj_do_nome))
        print("      Renomeie o arquivo para %s.pfx, ou confira se este e "
              "mesmo o certificado certo." % cnpj_cert)
        print("      Certificado errado consulta a caixa de entrada de outra "
              "empresa, e isso nao aparece em conferencia nenhuma depois.")
        return 1

    if meta.get("vencido"):
        print()
        print("ERRO: este certificado VENCEU em %s." % ate)
        return 1
    if isinstance(dias, int) and dias <= 30:
        # AVISO, e nao recusa: um certificado com 22 dias funciona hoje, e
        # travar o cadastro por isso seria impedir a recolha de comecar. O que
        # nao pode e ele vencer em SILENCIO -- certificado vencido para a
        # recolha sem dar erro em lugar nenhum.
        print()
        print("AVISO: vence em %d dia(s) (%s). Peca a renovacao agora — quando"
              % (dias, ate))
        print("       ele vencer, a recolha para e nao ha erro que aponte para")
        print("       ca. A Saude do Servidor tambem passa a avisar.")

    DIR_CERT.mkdir(parents=True, exist_ok=True)
    destino = DIR_CERT / ("%s.pfx" % cnpj_do_nome)
    if caminho.resolve() != destino.resolve():
        destino.write_bytes(bruto)
        print()
        print("copiado   : %s" % destino)
    segredo_arquivo.proteger(destino)

    import json
    d = {}
    if SENHAS.exists():
        try:
            d = json.loads(SENHAS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            d = {}
    d[cnpj_do_nome] = {"valor": boa,
                       "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    SENHAS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    # `chmod` sozinho NAO protege no Windows (so liga o somente-leitura; quem
    # decide acesso e a ACL). A Saude do Servidor MEDE essa ACL num cartao.
    segredo_arquivo.proteger(SENHAS)

    print()
    print("OK: certificado e senha no cofre, fora do git.")
    # O CAMINHO ABSOLUTO, e nao "data/certificados/". `data/` NAO e
    # compartilhado entre worktrees: cadastrar numa arvore de trabalho nao leva
    # nada para producao, e a tela de la continua dizendo "senha nao
    # cadastrada" sem explicar por que. Aconteceu em 07/09/2026 -- o caminho
    # relativo escondia exatamente a informacao que resolveria.
    print("    %s" % DIR_CERT)
    if RAIZ.name != "cortex-sulista":
        print()
        print("ATENCAO: esta NAO e a arvore de producao (%s)." % RAIZ.name)
        print("         A API de producao le de")
        print("         C:\\Users\\inteligencia\\Documents\\cortex-sulista\\data\\certificados")
        print("         Rode este mesmo comando LA, ou a tela vai dizer")
        print("         'senha nao cadastrada' para um certificado que existe.")
    print()
    print("    A senha entra e NAO volta: nenhum endpoint a expoe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
