# -*- coding: utf-8 -*-
"""O canhoto (comprovante de entrega) de um CT-e — do Drive onde o ERP guarda.

ONDE O ARQUIVO ESTÁ, medido em 17/09/2026
=========================================
O ERP registra o anexo em `arquivo.arquivobinario` (`tipoarquivo = 105`,
`tipodocumento = 6`, chaveado pelas 7 colunas do CT-e) — 10.424 em 60 dias, e
~68% dos CT-e de 15 a 30 dias têm o seu. Mas o CONTEÚDO não está no banco:
`tipoarmazenamento = 2` guarda o arquivo FORA, e `caminhoarmazenamento` é o id
de um arquivo no **Google Drive** de uma conta Workspace da casa (a
configuração do ERP aponta a pasta `AvacorpI_comprovantes`). Só 3 anexos em 60
dias têm o binário no próprio banco, e esses saem daqui sem ir à rede.

POR QUE A CREDENCIAL É DO CÓRTEX, E NÃO A DO ERP
================================================
A configuração do ERP guarda a conta de serviço dele (certificado e senha) numa
tabela que qualquer leitor da réplica enxerga. **Não usamos essa**: credencial
de terceiro lida de dentro de outro sistema é credencial que ninguém sabe que
está em uso — não se revoga, não se rotaciona, e no dia em que o ERP a trocar a
falha aparece aqui sem explicação. O CÓRTEX usa uma credencial PRÓPRIA, no
cofre, com acesso de LEITURA à mesma pasta.

DOIS MODOS, PORQUE O GOOGLE NÃO ACEITA SENHA
============================================
Usuário e senha não abrem o Drive por API — o Google desligou isso. O que
abre é:

1. **conta de serviço** (o modo recomendado): um JSON com chave privada; quem
   administra o Workspace compartilha a pasta com o e-mail da conta de serviço,
   em modo leitura. Não expira e não depende de ninguém continuar na empresa.
2. **autorização OAuth** de uma conta de pessoa: id e segredo do cliente mais um
   `refresh_token` gerado UMA vez com a conta que enxerga a pasta. Serve quando
   não dá para criar conta de serviço — e morre junto com a conta da pessoa.

Sem nenhum dos dois o portal continua dizendo QUANDO o canhoto foi anexado e
recusa o download com o motivo: **sem credencial não é falha, é instalação
incompleta**.

NADA DE DEPENDÊNCIA NOVA: o token sai de uma chamada HTTPS ao endpoint de
OAuth do Google (`urllib` + `api/tls.contexto()`), e a assinatura RS256 da
conta de serviço usa a `cryptography`, que já vem com a pilha fiscal.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from api import db, tls
from api.credenciais import ler

log = logging.getLogger("cortex.portal_cargas.canhoto")

TIPO_CANHOTO = 105
TIPODOC_CTE = 6

#: Leitura, e só. O escopo mais estreito que serve: `drive.readonly` não
#: permite apagar nem alterar nada, e é o que se pede a quem compartilha a
#: pasta. Um escopo amplo aqui seria pedir poder que este módulo não exerce.
ESCOPO = "https://www.googleapis.com/auth/drive.readonly"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_ARQUIVO = "https://www.googleapis.com/drive/v3/files/"
TEMPO_LIMITE_S = 30

MIME = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "tif": "image/tiff", "tiff": "image/tiff"}


class SemCredencial(RuntimeError):
    """Instalação incompleta: ninguém configurou o acesso ao Drive."""


class DriveIndisponivel(RuntimeError):
    """O Google respondeu erro. A mensagem já vem limpa de segredo."""


class SemCanhoto(LookupError):
    """O CT-e é do cliente, mas não tem canhoto anexado."""


def modo() -> str:
    """'conta_servico', 'oauth' ou '' — o que está configurado no cofre."""
    if ler("CANHOTO_DRIVE_CONTA_SERVICO"):
        return "conta_servico"
    if (ler("CANHOTO_DRIVE_CLIENT_ID") and ler("CANHOTO_DRIVE_CLIENT_SECRET")
            and ler("CANHOTO_DRIVE_REFRESH_TOKEN")):
        return "oauth"
    return ""


def configurado() -> bool:
    return bool(modo())


def o_que_falta() -> str:
    """A frase que a tela mostra — dizendo QUAL caminho seguir, não só que
    falta algo. Quem lê isto está em Integrações procurando onde preencher."""
    if configurado():
        return ""
    return ("Falta o acesso ao Drive onde o ERP guarda os canhotos "
            "(Administração › Integrações › Canhotos): o JSON de uma conta de "
            "serviço com a pasta compartilhada em leitura, ou o par "
            "id/segredo do cliente OAuth mais o refresh token.")


# ------------------------------------------------------------------ o token
_TOKEN: dict = {"valor": "", "expira": 0.0}
_TRAVA = threading.Lock()


def _post_token(dados: dict) -> dict:
    corpo = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(URL_TOKEN, data=corpo, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE_S,
                                    context=tls.contexto()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # O CORPO do erro do Google traz o motivo ("invalid_grant") e NÃO traz
        # o segredo — mas ele vai pelo corpo da requisição, então o que sai
        # daqui é só o campo `error`, nunca a exceção crua.
        try:
            erro = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001
            erro = ""
        raise DriveIndisponivel(
            "O Google recusou a credencial do Drive (%s). Reveja o acesso em "
            "Administração › Integrações › Canhotos." % (erro or exc.code))
    except Exception as exc:  # noqa: BLE001
        raise DriveIndisponivel(
            "Não foi possível falar com o Google (%s)." % type(exc).__name__)


def _jwt_conta_servico(cred: dict) -> str:
    """O assertion RS256 da conta de serviço. `sub` personifica a conta que
    enxerga a pasta, quando ela for informada (delegação do Workspace)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(x: bytes) -> bytes:
        return base64.urlsafe_b64encode(x).rstrip(b"=")

    agora = int(time.time())
    corpo = {"iss": cred.get("client_email"), "scope": ESCOPO,
             "aud": URL_TOKEN, "iat": agora, "exp": agora + 3600}
    usuario = (ler("CANHOTO_DRIVE_USUARIO") or "").strip()
    if usuario:
        corpo["sub"] = usuario
    partes = b".".join([b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()),
                        b64(json.dumps(corpo).encode())])
    chave = serialization.load_pem_private_key(
        (cred.get("private_key") or "").encode(), password=None)
    assinatura = chave.sign(partes, padding.PKCS1v15(), hashes.SHA256())
    return (partes + b"." + b64(assinatura)).decode()


def _token() -> str:
    """Token de acesso, guardado em memória até um minuto antes de expirar.

    A trava existe porque duas pessoas baixando canhoto ao mesmo tempo pediriam
    dois tokens — e o Google conta isso.
    """
    with _TRAVA:
        if _TOKEN["valor"] and _TOKEN["expira"] > time.time() + 60:
            return _TOKEN["valor"]
        qual = modo()
        if qual == "conta_servico":
            bruto = ler("CANHOTO_DRIVE_CONTA_SERVICO") or ""
            try:
                cred = json.loads(bruto)
            except ValueError:
                raise SemCredencial(
                    "O conteúdo da conta de serviço não é um JSON válido — "
                    "cole o arquivo inteiro que o Google gerou.")
            resp = _post_token({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": _jwt_conta_servico(cred)})
        elif qual == "oauth":
            resp = _post_token({
                "grant_type": "refresh_token",
                "client_id": ler("CANHOTO_DRIVE_CLIENT_ID"),
                "client_secret": ler("CANHOTO_DRIVE_CLIENT_SECRET"),
                "refresh_token": ler("CANHOTO_DRIVE_REFRESH_TOKEN")})
        else:
            raise SemCredencial(o_que_falta())
        token = resp.get("access_token") or ""
        if not token:
            raise DriveIndisponivel("O Google não devolveu token de acesso.")
        _TOKEN["valor"] = token
        _TOKEN["expira"] = time.time() + float(resp.get("expires_in") or 3600)
        return token


def baixar_do_drive(id_arquivo: str) -> bytes:
    """O conteúdo de UM arquivo do Drive, por id.

    `supportsAllDrives`: a pasta do ERP pode estar num drive compartilhado, e
    sem esta marca o Google responde 404 para um arquivo que existe — erro que
    se lê como "id errado" e manda procurar no lugar certo.
    """
    url = (URL_ARQUIVO + urllib.parse.quote(id_arquivo, safe="")
           + "?alt=media&supportsAllDrives=true")
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + _token())
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE_S,
                                    context=tls.contexto()) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise DriveIndisponivel(
                "O Drive recusou o acesso a este arquivo. A pasta dos canhotos "
                "precisa estar compartilhada, em leitura, com a conta "
                "configurada em Integrações › Canhotos.")
        if exc.code == 404:
            raise DriveIndisponivel(
                "O ERP aponta um arquivo que o Drive não devolve. Ele pode ter "
                "sido movido ou apagado de lá.")
        raise DriveIndisponivel("O Drive respondeu HTTP %s." % exc.code)
    except Exception as exc:  # noqa: BLE001
        raise DriveIndisponivel(
            "Não foi possível baixar do Drive (%s)." % type(exc).__name__)


# ------------------------------------------------------------------ o ERP
#: Os anexos de canhoto de UM CT-e, do mais novo para o mais velho. O conteúdo
#: vem junto quando o ERP o guardou no banco (raro, mas existe) — nesse caso
#: não se vai à rede.
PONTEIRO_SQL = """
SELECT a.id, a.nomearquivo, lower(coalesce(a.extensao,'')) AS extensao,
       a.tamanho, a.tipoarmazenamento, a.caminhoarmazenamento,
       to_char(a.dtinc,'YYYY-MM-DD HH24:MI') AS anexado_em,
       a.conteudoarquivo
FROM conhecimento k
JOIN arquivo.arquivobinario a
  ON a.tipodocumento = %(tipodoc)s AND a.tipoarquivo = %(tipo)s
 AND a.grupo = k.grupo AND a.empresa = k.empresa AND a.filial = k.filial
 AND a.unidade = k.unidade AND a.diferenciadornumero = k.diferenciadornumero
 AND a.serie = k.serie AND a.numerosequencia = k.numero
WHERE trim(k.chaveacessocte) = %(chave)s
ORDER BY a.dtinc DESC
"""


def do_cte(chave: str) -> list[dict]:
    """Os anexos de canhoto de um CT-e. NÃO decide escopo: quem chama já
    autorizou a chave (`documentos.autorizar`), e ter as duas decisões no mesmo
    lugar é o que faz o escopo ser uma regra só."""
    return db.query(PONTEIRO_SQL, {"chave": (chave or "").strip(),
                                   "tipodoc": TIPODOC_CTE, "tipo": TIPO_CANHOTO})


def arquivo(chave: str) -> tuple[str, str, bytes]:
    """(nome, tipo de mídia, bytes) do canhoto mais recente do CT-e."""
    linhas = do_cte(chave)
    if not linhas:
        raise SemCanhoto("Este CT-e ainda não tem canhoto anexado.")
    a = linhas[0]
    ext = a["extensao"] or "pdf"
    nome = "canhoto-%s.%s" % ((chave or "").strip(), ext)
    midia = MIME.get(ext, "application/octet-stream")
    if a["conteudoarquivo"]:
        return nome, midia, bytes(a["conteudoarquivo"])
    id_drive = (a["caminhoarmazenamento"] or "").strip()
    if not id_drive:
        raise SemCanhoto(
            "O ERP registrou o canhoto sem dizer onde o arquivo está.")
    return nome, midia, baixar_do_drive(id_drive)
