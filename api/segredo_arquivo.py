"""Restringir de verdade o acesso a um arquivo com segredo dentro.

POR QUE ISTO EXISTE
===================
O CÓRTEX guardava cinco arquivos de segredo — o cofre de credenciais, a
configuração do correio, a do WhatsApp, as senhas dos certificados A1 e os
próprios `.pfx` — e todos chamavam `Path.chmod(0o600)` depois de gravar, com
o comentário "não legível por outros usuários da máquina".

**No Windows isso não protege nada.** O `os.chmod` do NTFS só liga e desliga o
atributo SOMENTE-LEITURA; quem decide acesso é a ACL, e ela continua sendo a
que o arquivo herdou da pasta. E o servidor de produção é Windows.

O que descobri ao conferir (30/08/2026) foi melhor do que eu temia e pior do
que parecia: os arquivos ESTÃO restritos a SYSTEM e ao dono — mas por
**herança da pasta do usuário**, e não porque o código pediu. É proteção por
acidente: mover o projeto, cloná-lo noutro caminho ou alguém afrouxar a pasta
pai desfaz tudo, e o `chmod` continuaria dando a sensação de que há uma trava.
Segurança que depende de uma coincidência não é segurança — é uma frase no
comentário.

O QUE ESTE MÓDULO FAZ
=====================
`proteger(caminho)` aplica a restrição REAL da plataforma, e `estado(caminho)`
diz quem tem acesso — é ele que faz a Saúde do Servidor MOSTRAR a proteção em
vez de afirmá-la.

A REGRA MAIS IMPORTANTE DAQUI: **na dúvida, não mexer.** Se não der para
descobrir com segurança quem precisa manter acesso, a função NÃO reescreve a
ACL e devolve o motivo. Uma ACL escrita pela metade tranca o SYSTEM para fora
e derruba a API, a assinatura de CT-e e a coleta — muito pior que o problema
que ela veio resolver.

O QUE SE REMOVE, E O QUE NÃO SE TOCA
====================================
Remove-se **grupo amplo**: Usuários, Todos, Usuários autenticados, Usuários do
Domínio — as identidades que incluem gente que não administra nada.

NÃO se toca em conta nomeada, no SYSTEM nem em Administradores. A API roda
como SISTEMA e é o dono dos `.pfx`; a conta que opera o painel NÃO é
administradora. Uma versão anterior deste módulo reconstruía a ACL e teria
trancado essa conta para fora dos próprios certificados — proteção que quebra
o uso legítimo é desligada na semana seguinte, e aí não sobra proteção.

Os SIDs são usados em vez dos nomes DE PROPÓSITO: este Windows é pt-BR e o
SYSTEM se chama "AUTORIDADE NT\\SISTEMA" — `icacls` com nome em inglês falha, e
falharia calado num script que não conferisse o resultado.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"

SID_SYSTEM = "S-1-5-18"
SID_ADMINS = "S-1-5-32-544"

# O QUE CONTA COMO EXPOSIÇÃO — e a primeira versão desta régua errou.
#
# Eu comecei com "qualquer SID que não seja SYSTEM, Administradores ou o dono
# é intruso". O sensor acendeu VERMELHO em 24 certificados, e o suposto
# intruso era **a conta que opera o painel**: os `.pfx` foram gravados pela
# API rodando como SYSTEM, então o dono deles é o SYSTEM, e o usuário aparecia
# como "mais alguém". Conta nomeada com acesso é o caso NORMAL numa máquina
# administrada por uma pessoa.
#
# É o erro de denominador do painel de rastreadores, de novo: o conjunto tem
# de conter só quem pode ser um problema. Um alarme que acende sem haver
# problema ensina a ignorar o alarme — e este ia nascer com 24 falsos
# positivos, ou seja, ia nascer ignorado.
#
# A régua certa é por GRUPO AMPLO: o risco é o segredo ser legível por
# "Usuários", "Todos", "Usuários autenticados" — as identidades que incluem
# gente que não administra nada. Conta individual não entra.
_GRUPOS_AMPLOS = {
    "S-1-1-0",        # Todos / Everyone
    "S-1-5-7",        # Logon anônimo
    "S-1-5-11",       # Usuários autenticados
    "S-1-5-4",        # Interativo
    "S-1-5-32-545",   # Usuários (o grupo local)
    "S-1-5-32-546",   # Convidados
    "S-1-5-32-547",   # Usuários avançados
    "S-1-5-32-555",   # Usuários da Área de Trabalho Remota
}
# Grupos de DOMÍNIO pelo RID final: 513 Usuários do Domínio, 514 Convidados,
# 515 Computadores. O SID inteiro muda a cada domínio, então a lista fixa não
# os pegaria — e é justamente num domínio que "Usuários do Domínio" significa
# a empresa inteira.
_RIDS_AMPLOS = {"513", "514", "515"}


def _e_grupo_amplo(sid: str) -> bool:
    return sid in _GRUPOS_AMPLOS or sid.rsplit("-", 1)[-1] in _RIDS_AMPLOS


_SEMPRE_OK = {SID_SYSTEM, SID_ADMINS}


def _ps(script: str, timeout: int = 20) -> str:
    """PowerShell de leitura, sem perfil. Devolve "" em qualquer tropeço —
    quem chama trata a ausência de resposta como "não sei", nunca como "não
    tem"."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _dono_sid(caminho: Path) -> str | None:
    saida = _ps(
        "(Get-Acl -LiteralPath '" + str(caminho).replace("'", "''") + "')"
        ".GetOwner([System.Security.Principal.SecurityIdentifier]).Value")
    return saida.splitlines()[0].strip() if saida else None


def _sids_com_acesso(caminho: Path) -> list[str] | None:
    """Os SIDs que a ACL concede hoje. `None` = não consegui ler (e aí a
    Saúde diz "não verificado", que é diferente de "desprotegido")."""
    saida = _ps(
        "(Get-Acl -LiteralPath '" + str(caminho).replace("'", "''")
        + "' -ErrorAction Stop)"
        ".Access | ForEach-Object { "
        "  try { $_.IdentityReference.Translate("
        "    [System.Security.Principal.SecurityIdentifier]).Value } "
        "  catch { $_.IdentityReference.Value } }")
    if not saida:
        return None
    return [l.strip() for l in saida.splitlines() if l.strip()]


def _acessos_em_lote(caminhos: list[Path]) -> dict[str, list[str] | None]:
    """A ACL de VÁRIOS arquivos numa ÚNICA chamada de PowerShell.

    POR QUE EM LOTE: um `estado()` por arquivo dava **3,4 s** para os 28
    arquivos desta instalação (4 configs + 24 certificados), e isso entraria
    inteiro no `coletar()` da Saúde. Essa tela já foi de 5,6 s para 0,95 s
    justamente tirando dela um diagnóstico caro repetido — recolocar 3,4 s
    seria desfazer a correção com outro nome. Em lote fica em ~0,4 s.

    Devolve caminho → lista de SIDs, ou `None` para o que não deu para ler.
    Arquivo que o PowerShell não devolveu vira `None` e a tela diz "não
    verificado" — nunca "ok".
    """
    if not caminhos:
        return {}
    lista = ",".join("'" + str(c).replace("'", "''") + "'" for c in caminhos)
    saida = _ps(
        "foreach($p in @(" + lista + ")){"
        "  try{"
        # `-ErrorAction Stop` NÃO É DETALHE: sem ele, `Get-Acl` num caminho
        # ilegível emite erro NÃO-TERMINANTE, o `catch` não pega, e a linha
        # sai com a lista VAZIA. Lista vazia não tem grupo amplo, então o
        # julgamento diria "restrito" para um arquivo que não foi lido — o
        # exato "ok sem medir" que este módulo veio consertar. Um teste
        # plantando um caminho inexistente é o que pegou isto.
        "    $a=(Get-Acl -LiteralPath $p -ErrorAction Stop).Access | ForEach-Object {"
        "      try{ $_.IdentityReference.Translate("
        "        [System.Security.Principal.SecurityIdentifier]).Value }"
        "      catch{ $_.IdentityReference.Value } };"
        "    Write-Output ($p + '|' + ($a -join ','))"
        "  }catch{ }"
        "}", timeout=60)
    fora: dict[str, list[str] | None] = {str(c): None for c in caminhos}
    for linha in saida.splitlines():
        if "|" not in linha:
            continue
        cam, _, sids = linha.partition("|")
        cam = cam.strip()
        if cam in fora:
            fora[cam] = [x.strip() for x in sids.split(",") if x.strip()]
    return fora


def _julgar(sids: list[str] | None) -> dict:
    """A régua, separada da leitura — é o que deixa o lote e o avulso darem
    exatamente a mesma resposta.

    LISTA VAZIA É "NÃO SEI", NÃO "ESTÁ LIMPO". Toda ACL real tem pelo menos
    uma entrada; uma lista sem nenhuma só acontece quando a leitura falhou. É
    a segunda linha de defesa contra o mesmo erro que o `-ErrorAction Stop`
    fecha lá em cima — e a que sobra se algum dia a leitura mudar de forma.
    """
    if not sids:
        return {"protegido": None, "quem": [], "intrusos": [],
                "motivo": "não foi possível ler a ACL"}
    amplos = sorted({x for x in sids if _e_grupo_amplo(x)})
    return {"protegido": not amplos, "quem": sorted(set(sids)),
            "intrusos": amplos,
            "motivo": ("nenhum grupo amplo na lista de acesso" if not amplos
                       else "legível por grupo amplo: " + ", ".join(amplos))}


def proteger(caminho) -> dict:
    """Tira os GRUPOS AMPLOS da lista de acesso. Não mexe em mais nada.

    A PRIMEIRA VERSÃO DISTO ERA PERIGOSA, e vale registrar por quê. Ela
    reconstruía a ACL do zero (`/inheritance:r` + grant para SYSTEM,
    Administradores e o dono). Só que os `.pfx` são gravados pela API, que roda
    como SISTEMA — o dono deles é o SYSTEM. A conta que opera o painel NÃO é
    administradora, então o "endurecimento" a teria trancado para fora dos
    próprios certificados, em silêncio, no próximo upload. Uma proteção que
    quebra o uso legítimo é derrubada na semana seguinte, e aí não sobra
    proteção nenhuma.

    Então a operação é CIRÚRGICA: se houver "Usuários", "Todos" ou
    equivalente, a herança é materializada (`/inheritance:d`) e só esses são
    removidos. Conta nomeada, SYSTEM e Administradores ficam onde estão.

    E é IDEMPOTENTE: sem grupo amplo, não roda `icacls` nenhum. Gravar
    credencial é ação frequente, e reescrever ACL a cada gravação é risco sem
    contrapartida.

    Devolve `{"aplicado": bool, "motivo": str}` e NUNCA levanta: quando esta
    função é chamada o segredo já foi gravado, e estourar aqui transformaria
    "gravei mas não endureci a permissão" em "não gravei" — a pessoa tentaria
    de novo achando que falhou.
    """
    caminho = Path(caminho)
    try:
        caminho.chmod(0o600)   # no POSIX isto é a proteção inteira
    except OSError as exc:
        return {"aplicado": False, "motivo": f"chmod falhou: {type(exc).__name__}"}
    if not WINDOWS:
        return {"aplicado": True, "motivo": "modo 0600"}

    sids = _sids_com_acesso(caminho)
    if sids is None:
        # NA DÚVIDA, NÃO MEXER: sem conseguir ler a ACL, qualquer escrita é
        # às cegas — e às cegas dá para trancar o SYSTEM e derrubar a API.
        return {"aplicado": False,
                "motivo": "não consegui ler a lista de acesso — mantida como "
                          "estava, de propósito"}
    amplos = sorted({x for x in sids if _e_grupo_amplo(x)})
    if not amplos:
        return {"aplicado": True, "motivo": "nada a remover"}

    cmd = ["icacls", str(caminho), "/inheritance:d"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        if r.returncode != 0:
            return {"aplicado": False,
                    "motivo": "icacls recusou materializar a herança (%s)" % r.returncode}
        for sid in amplos:
            r = subprocess.run(["icacls", str(caminho), "/remove:g", "*" + sid],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=30)
            if r.returncode != 0:
                return {"aplicado": False,
                        "motivo": "icacls recusou remover %s (%s)" % (sid, r.returncode)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"aplicado": False,
                "motivo": f"icacls indisponível: {type(exc).__name__}"}
    return {"aplicado": True,
            "motivo": "removido(s) da lista de acesso: " + ", ".join(amplos)}


def estado(caminho) -> dict:
    """Quem tem acesso, para a tela MOSTRAR em vez de afirmar.

    Três respostas, e a do meio é a que costuma ser esquecida:
      protegido=True   — só SYSTEM, Administradores e o dono;
      protegido=False  — há outro alguém na ACL (ou modo POSIX frouxo);
      protegido=None   — **não deu para verificar**. Não é o mesmo que estar
                         desprotegido, e dizer "ok" aqui seria repetir
                         exatamente o erro que este módulo veio consertar.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return {"existe": False, "protegido": None, "quem": [],
                "motivo": "o arquivo não existe"}
    if not WINDOWS:
        modo = caminho.stat().st_mode & 0o777
        # No POSIX o equivalente de "grupo amplo" é justamente group+other.
        return {"existe": True, "protegido": (modo & 0o077) == 0,
                "quem": [oct(modo)], "motivo": "modo POSIX " + oct(modo)}
    return {"existe": True, **_julgar(_sids_com_acesso(caminho))}


def caminhos_de_segredo() -> list[tuple[str, Path]]:
    """O que a Saúde confere. Rótulo + caminho, resolvidos aqui para a tela
    não precisar conhecer cinco módulos diferentes.

    Os `.pfx` entram como GRUPO (são um por CNPJ, hoje dezenas) — listá-los um
    a um encheria o cartão de linhas idênticas, que é o jeito de ensinar
    alguém a pular o cartão.
    """
    raiz = Path(__file__).resolve().parent.parent / "data"
    fora: list[tuple[str, Path]] = [
        ("Cofre de credenciais", raiz / "credenciais.json"),
        ("Configuração do correio", raiz / "email_config.json"),
        ("Configuração do WhatsApp", raiz / "whatsapp_config.json"),
        ("Senhas dos certificados", raiz / "certificados" / "senhas.json"),
    ]
    return [(rot, p) for rot, p in fora if p.exists()]


def certificados() -> list[Path]:
    raiz = Path(__file__).resolve().parent.parent / "data" / "certificados"
    return sorted(raiz.glob("*.pfx")) if raiz.is_dir() else []


def panorama() -> dict:
    """O cartão da Saúde: um resumo e só o que está FORA do esperado em
    detalhe. Cartão que lista dez linhas dizendo "ok" ensina a não ler o
    cartão — a lição dos nove SQLite migrados.

    UMA leitura de ACL para todos os arquivos (ver `_acessos_em_lote`): por
    arquivo eram 3,4 s dentro do `coletar()` da Saúde.
    """
    nomeados = caminhos_de_segredo()
    certs = certificados()
    if not WINDOWS:
        acessos = {}
    else:
        acessos = _acessos_em_lote([p for _, p in nomeados] + certs)

    def _um(p: Path) -> dict:
        if not WINDOWS:
            return estado(p)
        return {"existe": True, **_julgar(acessos.get(str(p)))}

    itens = [{"rotulo": rot, "arquivo": p.name, **_um(p)} for rot, p in nomeados]
    if certs:
        # UMA linha para os 24: o grupo leva o PIOR estado, e listar arquivo a
        # arquivo encheria o cartão de linhas idênticas.
        est = [_um(c) for c in certs]
        pior = (False if any(e["protegido"] is False for e in est)
                else None if any(e["protegido"] is None for e in est) else True)
        amplos = sorted({x for e in est for x in e.get("intrusos") or []})
        itens.append({"rotulo": "Certificados A1 (.pfx)",
                      "arquivo": "%d arquivo(s)" % len(certs), "existe": True,
                      "protegido": pior, "quem": [], "intrusos": amplos,
                      "motivo": ("nenhum legível por grupo amplo" if pior
                                 else "legível por grupo amplo: " + ", ".join(amplos)
                                 if pior is False else "algum não verificado")})
    expostos = [i for i in itens if i["protegido"] is False]
    naoverif = [i for i in itens if i["protegido"] is None]
    estado_geral = ("alerta" if expostos else "info" if naoverif
                    else "ok" if itens else "info")
    return {"itens": itens, "expostos": len(expostos),
            "nao_verificados": len(naoverif), "total": len(itens),
            "estado": estado_geral, "plataforma": "windows" if WINDOWS else "posix"}
