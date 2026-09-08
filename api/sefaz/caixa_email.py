# -*- coding: utf-8 -*-
"""A caixa postal que recebe XML — `xml@sulista.com.br`, lida pelo Microsoft 365.

A SEGUNDA PORTA DA RECOLHA
==========================

A primeira porta (`distribuicao.py`) traz o que a SEFAZ entrega, e ela só
entrega documento em que a Sulista é PARTE. Quando não é — a nota de um cliente
que ela vai transportar, o XML que o embarcador manda antes de fechar o frete —
o documento não existe em caixa nenhuma da empresa, e as pessoas mandam por
e-mail. É essa caixa que este módulo lê.

POR QUE MICROSOFT GRAPH, E NÃO IMAP
-----------------------------------

O domínio `sulista.com.br` entrega e-mail no Exchange Online (o MX é
`sulista-com-br.mail.protection.outlook.com`, conferido em 08/09/2026), e a
**Microsoft desligou a autenticação básica de IMAP/POP no Exchange Online**, sem
caminho para reabrir. Escrever um leitor IMAP com usuário e senha seria escrever
um leitor que responde `535` para sempre — e o `535` do M365 se lê como "senha
errada", mandando a pessoa trocar uma senha que está certa. A casa já tem essa
cicatriz do lado do SMTP (`api/correio/envio.py` explica o 5.7.139).

Sobra o caminho suportado: aplicativo registrado no Entra ID, permissão de
APLICAÇÃO `Mail.Read`, token por `client_credentials`. Sem usuário, sem senha,
sem MFA para quebrar no meio da madrugada.

**E A PERMISSÃO PRECISA SER LIMITADA A ESTA CAIXA.** `Mail.Read` de aplicação
alcança TODAS as caixas do tenant — a do financeiro, a da diretoria. Quem
administra restringe com uma `ApplicationAccessPolicy` do Exchange Online:

    New-ApplicationAccessPolicy -AppId <client_id> `
      -PolicyScopeGroupId xml@sulista.com.br `
      -AccessRight RestrictAccess `
      -Description "CORTEX: so a caixa de XML"

Isso não é zelo de documentação: é a diferença entre um segredo que abre uma
caixa postal de recebimento e um segredo que abre a empresa inteira. O cartão da
Saúde do Servidor diz se a política está declarada, porque daqui não dá para
conferir — só quem tem o Exchange na mão consegue, e o que não se mede se
escreve.

O QUE ESTE MÓDULO NÃO FAZ
-------------------------

**Não mexe na caixa.** Não marca como lida, não move, não apaga. Duas razões: a
caixa é de gente também (alguém abre para conferir o que chegou), e "já
processei" é estado NOSSO — vive em `dfe_email_mensagem`, onde dá para auditar
e refazer. Estado de coleta guardado no sistema do fornecedor é estado que some
quando alguém arruma a caixa postal.

Por isso a permissão pedida é `Mail.Read`, e não `Mail.ReadWrite`: o
aplicativo não tem como estragar nada mesmo que queira.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .. import credenciais, pglocal, tls
from . import armazenamento as arm
from . import arquivo

log = logging.getLogger("cortex.sefaz.caixa_email")

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"

#: Quantos dias para trás a coleta olha. A janela existe porque a caixa pode
#: ter anos de mensagem e a primeira execução não pode tentar ler tudo; o que
#: já foi processado é pulado pelo id, então repetir a janela não custa
#: reprocessamento — custa uma listagem.
DIAS_PADRAO = 30

#: Mensagens por página na listagem. O Graph aceita até 1000; 50 mantém a
#: resposta pequena e o laço interrompível.
PAGINA = 50

TIMEOUT = 60


class NaoConfigurada(RuntimeError):
    """Falta credencial — é instalação incompleta, não falha."""


class Indisponivel(RuntimeError):
    """O provedor não respondeu, ou recusou."""


def _cred(nome: str) -> str:
    return (credenciais.ler(nome) or "").strip()


def caixa() -> str:
    return _cred("XMLMAIL_CAIXA")


def configurado() -> bool:
    """Os QUATRO campos. Três não fazem chamada nenhuma."""
    return all(_cred(c) for c in ("XMLMAIL_TENANT_ID", "XMLMAIL_CLIENT_ID",
                                 "XMLMAIL_CLIENT_SECRET", "XMLMAIL_CAIXA"))


def falta() -> list[str]:
    """O que falta configurar, com o nome que aparece na tela."""
    rotulos = {"XMLMAIL_TENANT_ID": "ID do tenant",
               "XMLMAIL_CLIENT_ID": "ID do aplicativo",
               "XMLMAIL_CLIENT_SECRET": "segredo do aplicativo",
               "XMLMAIL_CAIXA": "endereço da caixa"}
    return [r for c, r in rotulos.items() if not _cred(c)]


def _http(url: str, headers: dict, timeout: int = TIMEOUT,
          dados: bytes | None = None):
    """Uma ida à rede. Devolve `(status, bytes)` — HTTPError também é resposta.

    Sai por `tls.contexto()` como todo cliente da casa: o armazém de raízes do
    Windows num serviço SISTEMA é incompleto, e a falha aparece como
    "self-signed certificate in chain", que manda procurar no lugar errado.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "CORTEX-Sulista/1.0", **headers},
        data=dados, method="POST" if dados is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=tls.contexto()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Cliente:
    """`http` é injetável para os testes rodarem sem rede."""

    def __init__(self, http=None):
        if not configurado():
            raise NaoConfigurada("falta: " + ", ".join(falta()))
        self._http = http or _http
        self.caixa = caixa()
        self._tok = ""
        self._expira = datetime.now(timezone.utc)

    # ------------------------------------------------------------------ auth
    def token(self) -> str:
        agora = datetime.now(timezone.utc)
        if self._tok and agora < self._expira:
            return self._tok
        url = "%s/%s/oauth2/v2.0/token" % (LOGIN, _cred("XMLMAIL_TENANT_ID"))
        corpo = urllib.parse.urlencode({
            "client_id": _cred("XMLMAIL_CLIENT_ID"),
            "client_secret": _cred("XMLMAIL_CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"}).encode()
        try:
            status, resp = self._http(
                url, {"Content-Type": "application/x-www-form-urlencoded"},
                TIMEOUT, corpo)
        except Exception as exc:  # noqa: BLE001
            raise Indisponivel("rede: %s" % type(exc).__name__) from None
        if status != 200:
            # O CORPO NÃO VAI PARA O LOG. Numa troca de credencial o endpoint
            # de token devolve pedaços do que foi enviado, e o segredo do
            # aplicativo estaria dentro.
            raise Indisponivel("o Entra ID recusou o aplicativo (HTTP %d)"
                               % status)
        try:
            d = json.loads(resp)
        except json.JSONDecodeError:
            raise Indisponivel("resposta do Entra ID não é JSON") from None
        self._tok = d.get("access_token") or ""
        if not self._tok:
            raise Indisponivel("o Entra ID não devolveu token")
        # 60 s de margem: token que expira no meio de uma página de mensagens
        # vira 401 no lugar mais confuso possível.
        self._expira = (datetime.now(timezone.utc)
                        + timedelta(seconds=max(60, int(d.get("expires_in") or 3600)) - 60))
        return self._tok

    def _get(self, url: str) -> dict:
        status, resp = self._http(url, {"Authorization": "Bearer " + self.token(),
                                        "Accept": "application/json"})
        if status == 404:
            raise Indisponivel(
                "a caixa %s não foi encontrada no tenant" % self.caixa)
        if status == 403:
            raise Indisponivel(
                "o aplicativo não tem acesso à caixa %s. Se a "
                "ApplicationAccessPolicy foi criada, ela precisa INCLUIR esta "
                "caixa; se não foi, falta a permissão Mail.Read com "
                "consentimento do administrador" % self.caixa)
        if status != 200:
            raise Indisponivel("o Graph respondeu HTTP %d" % status)
        try:
            return json.loads(resp)
        except json.JSONDecodeError:
            raise Indisponivel("resposta do Graph não é JSON") from None

    # -------------------------------------------------------------- mensagens
    def mensagens(self, desde: datetime, limite: int = 500):
        """As mensagens COM ANEXO da janela, da mais nova para a mais velha."""
        filtro = ("hasAttachments eq true and receivedDateTime ge %s"
                  % desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        url = ("%s/users/%s/messages?%s" % (
            GRAPH, urllib.parse.quote(self.caixa),
            urllib.parse.urlencode({
                "$select": "id,subject,receivedDateTime,from,hasAttachments",
                "$filter": filtro,
                "$orderby": "receivedDateTime desc",
                "$top": PAGINA})))
        vistas = 0
        while url and vistas < limite:
            d = self._get(url)
            for m in d.get("value", []):
                remetente = (((m.get("from") or {}).get("emailAddress") or {})
                             .get("address") or "")
                yield {"id": m.get("id") or "",
                       "assunto": m.get("subject") or "",
                       "remetente": remetente,
                       "recebida_em": m.get("receivedDateTime")}
                vistas += 1
                if vistas >= limite:
                    return
            url = d.get("@odata.nextLink") or ""

    def anexos(self, mensagem_id: str) -> list[dict]:
        """`[{nome, bytes}]` — só anexo de ARQUIVO, e nunca o embutido.

        Imagem embutida (a logo da assinatura de quem mandou) chega como anexo
        de arquivo com `isInline`. Sem esse filtro, toda mensagem traria dois
        ou três PNGs para a lista de ignorados, e a lista que serve para
        alguém olhar viraria ruído.
        """
        url = "%s/users/%s/messages/%s/attachments" % (
            GRAPH, urllib.parse.quote(self.caixa),
            urllib.parse.quote(mensagem_id, safe=""))
        saida = []
        for a in self._get(url).get("value", []):
            if a.get("isInline"):
                continue
            if a.get("@odata.type") not in (None, "#microsoft.graph.fileAttachment"):
                # Anexo que é um item do Outlook (uma mensagem encaminhada como
                # anexo, um evento) não tem `contentBytes`. Fica registrado
                # como ignorado em vez de virar exceção.
                saida.append({"nome": a.get("name") or "(anexo)", "bytes": None})
                continue
            bruto = a.get("contentBytes")
            try:
                dados = base64.b64decode(bruto) if bruto else None
            except Exception:  # noqa: BLE001
                dados = None
            saida.append({"nome": a.get("name") or "(anexo)", "bytes": dados})
        return saida


# ================================================================== a coleta

def _ja_processadas(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM dfe_email_mensagem WHERE id = ANY(%s)",
                    (ids,))
        return {r["id"] for r in cur.fetchall()}


def _registrar(m: dict, *, anexos: int, aproveitados: int, ignorados: int,
               erro: str = "") -> None:
    """A mensagem fica registrada MESMO sem ter rendido documento.

    É o que impede a caixa de ser reprocessada para sempre por causa de uma
    mensagem que só tinha o PDF do DANFE — e é a lista que alguém precisa
    olhar: chegou, não virou documento.
    """
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dfe_email_mensagem
                   (id, caixa, remetente, assunto, recebida_em,
                    anexos, aproveitados, ignorados, erro)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                   processada_em = now(), anexos = EXCLUDED.anexos,
                   aproveitados = EXCLUDED.aproveitados,
                   ignorados = EXCLUDED.ignorados, erro = EXCLUDED.erro
        """, (m["id"], caixa(), m.get("remetente"), (m.get("assunto") or "")[:500],
              m.get("recebida_em"), anexos, aproveitados, ignorados,
              erro or None))


def _marcar_execucao(caixa_: str, *, vistas: int = 0, erro: str = "") -> None:
    """A EXECUÇÃO fica registrada, tenha achado mensagem ou não.

    É a diferença entre "a coleta rodou" e "chegou e-mail" — e confundir as
    duas faz o cartão da Saúde ficar vermelho numa semana em que ninguém
    mandou XML, acusando uma rotina que está funcionando. Alarme que acende
    sem haver problema ensina a ignorar alarme.
    """
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dfe_email_estado
                   (caixa, ultima_coleta, ultimo_sucesso, mensagens_vistas, ultimo_erro)
            VALUES (%s, now(), CASE WHEN %s THEN NULL ELSE now() END, %s, %s)
            ON CONFLICT (caixa) DO UPDATE SET
                   ultima_coleta = now(),
                   ultimo_sucesso = CASE WHEN %s THEN dfe_email_estado.ultimo_sucesso
                                         ELSE now() END,
                   mensagens_vistas = EXCLUDED.mensagens_vistas,
                   ultimo_erro = EXCLUDED.ultimo_erro
        """, (caixa_, bool(erro), int(vistas), erro or None, bool(erro)))


def coletar(dias: int = DIAS_PADRAO, limite: int = 500, http=None) -> dict:
    """Lê a caixa e guarda o que for documento fiscal. Devolve o placar.

    IDEMPOTENTE POR CONSTRUÇÃO, nos dois níveis: a mensagem já processada é
    pulada pelo id, e o arquivo repetido cai no `sha256` que já está lá. Rodar
    duas vezes seguidas é seguro — e é o que acontece quando alguém aperta
    "Coletar agora" enquanto a tarefa roda.
    """
    try:
        cli = Cliente(http=http)
    except Indisponivel as exc:
        _marcar_execucao(caixa(), erro=str(exc)[:200])
        raise
    desde = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
    placar = {"mensagens": 0, "novas": 0, "documentos": 0, "repetidos": 0,
              "ignorados": 0, "falhas": 0, "caixa": cli.caixa}

    pendentes: list[dict] = []
    try:
        for m in cli.mensagens(desde, limite=limite):
            placar["mensagens"] += 1
            pendentes.append(m)
    except Indisponivel as exc:
        # A LISTAGEM É A CHAMADA QUE PROVA O ACESSO. Falhar aqui é falhar a
        # coleta inteira, e isso precisa ficar gravado: sem a marca, a próxima
        # leitura da Saúde acharia que a rotina nem rodou.
        _marcar_execucao(cli.caixa, erro=str(exc)[:200])
        raise

    # UMA consulta para saber o que já foi visto, e não uma por mensagem.
    vistas = _ja_processadas([m["id"] for m in pendentes])
    for m in pendentes:
        if m["id"] in vistas:
            continue
        placar["novas"] += 1
        try:
            anexos = cli.anexos(m["id"])
        except Indisponivel as exc:
            placar["falhas"] += 1
            _registrar(m, anexos=0, aproveitados=0, ignorados=0,
                       erro=str(exc)[:200])
            continue
        docs: list[dict] = []
        fora: list[str] = []
        for a in anexos:
            if not a.get("bytes"):
                fora.append("%s: anexo sem conteúdo" % a.get("nome"))
                continue
            d, f = arquivo.do_arquivo(a["nome"], a["bytes"])
            docs.extend(d)
            fora.extend(f)
        r = arquivo.guardar_lote(
            docs, origem="email", remetente=m.get("remetente") or "",
            mensagem_id=m["id"], assunto=(m.get("assunto") or "")[:500],
            arquivo_nome="")
        placar["documentos"] += r["novos"]
        placar["repetidos"] += r["repetidos"]
        placar["falhas"] += r["falhas"]
        placar["ignorados"] += len(fora)
        _registrar(m, anexos=len(anexos), aproveitados=len(docs),
                   ignorados=len(fora))
    _marcar_execucao(cli.caixa, vistas=placar["mensagens"])
    return placar


def ultimas(limite: int = 30) -> list[dict]:
    """As últimas mensagens lidas — para a tela dizer o que chegou e virou o quê."""
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, remetente, assunto, recebida_em, processada_em,
                   anexos, aproveitados, ignorados, erro
              FROM dfe_email_mensagem
             ORDER BY processada_em DESC LIMIT %s""", (max(1, min(limite, 200)),))
        linhas = [dict(r) for r in cur.fetchall()]
    for l in linhas:
        for c in ("recebida_em", "processada_em"):
            if isinstance(l.get(c), datetime):
                l[c] = l[c].isoformat()
    return linhas


def estado() -> dict:
    """O que a Saúde e o cartão de Integrações precisam saber.

    Note quais são as DUAS datas, porque a diferença entre elas é a única coisa
    que separa alarme de ruído: `ultima_coleta` é a rotina ter passado por
    aqui; `ultima_mensagem` é ter chegado e-mail. Semana sem XML tem a primeira
    fresca e a segunda velha — e isso é a operação estando calma, não a
    integração estando quebrada.
    """
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) AS mensagens,
                   count(*) FILTER (WHERE aproveitados = 0) AS vazias,
                   max(processada_em) AS ultima
              FROM dfe_email_mensagem""")
        d = dict(cur.fetchone() or {})
        cur.execute("SELECT * FROM dfe_email_estado WHERE caixa = %s", (caixa(),))
        e = dict(cur.fetchone() or {})

    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else None

    return {"configurada": configurado(), "caixa": caixa(), "falta": falta(),
            "mensagens": d.get("mensagens") or 0,
            "vazias": d.get("vazias") or 0,
            "ultima_mensagem": _iso(d.get("ultima")),
            "ultima_coleta": _iso(e.get("ultima_coleta")),
            "ultimo_sucesso": _iso(e.get("ultimo_sucesso")),
            "ultimo_erro": e.get("ultimo_erro"),
            "arquivos": arquivo.resumo()}
