# -*- coding: utf-8 -*-
"""A busca e o detalhe da carga, para a página pública.

REGRA DE OURO DESTE ARQUIVO: nada sai daqui que não possa ser lido por um
desconhecido. Cada `SELECT` lista as colunas uma a uma — nunca `*` — porque
`SELECT *` numa tela pública é uma coluna nova do ERP virando vazamento no dia
em que alguém a criar, sem ninguém rever nada.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import pathlib
import re
import secrets
import time
from datetime import datetime, timezone

from .. import db

log = logging.getLogger("cortex.rastreio")

#: Quantas consultas um mesmo IP pode fazer por janela. Não é conforto: sem
#: freio, o segundo campo (os 4 dígitos do CNPJ) cai por força bruta — são
#: 10.000 combinações, que um script tenta em minutos.
FREIO_MAX = 20
FREIO_JANELA_S = 300

#: O freio mora em memória de propósito. Ele protege contra varredura, não
#: contra um adversário paciente com mil IPs — para esse, o que vale é o
#: segundo fator e o teto de resultados. Persistir isso no banco custaria uma
#: escrita por consulta pública e daria a impressão de uma garantia que ele não
#: dá.
_TENTATIVAS: dict[str, list[float]] = {}

#: Teto de cargas por busca. Documento em mãos devolve uma carga, ou poucas
#: quando a nota foi dividida. Um número alto aqui significaria que a busca
#: virou varredura — e o teto é o que impede que ela sirva para isso.
TETO = 20

RE_DIGITOS = re.compile(r"\D+")


def _so_digitos(s: str) -> str:
    return RE_DIGITOS.sub("", s or "")


def freio_livre(ip: str) -> bool:
    agora = time.time()
    janela = [t for t in _TENTATIVAS.get(ip, []) if agora - t < FREIO_JANELA_S]
    _TENTATIVAS[ip] = janela + [agora]
    if len(_TENTATIVAS) > 5000:          # não vira vazamento de memória
        for k in [k for k, v in _TENTATIVAS.items()
                  if not v or agora - v[-1] > FREIO_JANELA_S]:
            _TENTATIVAS.pop(k, None)
    return len(janela) < FREIO_MAX


#: Onde a chave dos tokens mora quando não veio do ambiente. Arquivo, e não
#: constante no código: este repo é PÚBLICO, e chave em commit é chave
#: publicada.
SEGREDO_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "rastreio_segredo.txt"

_SEGREDO_CACHE: dict = {}


def _segredo() -> bytes:
    """A chave que assina os tokens do rastreio.

    ELA PRECISA SOBREVIVER AO REINÍCIO, e essa foi a lição cara aqui. Enquanto
    o token só identificava a carga DENTRO de uma busca, uma chave por processo
    bastava — a pessoa buscava e abria no mesmo minuto. O link do WhatsApp
    mudou a exigência sem mudar o código: ele vale 20 dias e já está no celular
    do cliente, e o AutoDeploy reinicia a API várias vezes por dia. Com chave
    por processo, TODO link enviado morria no deploy seguinte — em silêncio,
    virando "este link expirou" para quem clicasse.

    A ordem é: variável de ambiente (o jeito certo em produção), depois um
    arquivo protegido em `data/` gerado na primeira vez, e só então — se nem
    gravar der certo — a chave por processo, que ao menos não é constante fixa
    no código de um repo público.
    """
    s = (os.environ.get("RASTREIO_TOKEN_SEGREDO")
         or os.environ.get("SECRET_KEY") or "").strip()
    if s:
        return s.encode("utf-8")

    if _SEGREDO_CACHE.get("v"):
        return _SEGREDO_CACHE["v"]
    try:
        if SEGREDO_PATH.exists():
            s = SEGREDO_PATH.read_text(encoding="utf-8").strip()
        if not s:
            s = secrets.token_urlsafe(48)
            SEGREDO_PATH.parent.mkdir(parents=True, exist_ok=True)
            SEGREDO_PATH.write_text(s, encoding="utf-8")
            # NO NTFS QUEM MANDA É A ACL (`os.chmod` é ficção nesta casa).
            from .. import segredo_arquivo
            segredo_arquivo.proteger(SEGREDO_PATH)
            log.info("rastreio: chave de token criada em data/")
    except Exception as exc:  # noqa: BLE001
        # NUNCA LEVANTA: sem a chave persistida o rastreio ainda funciona
        # dentro do processo; o que não pode é a página inteira cair porque o
        # disco estava cheio.
        log.warning("rastreio: chave em arquivo indisponivel (%s)",
                    type(exc).__name__)
        s = ""
    if not s:
        s = repr(id(_TENTATIVAS))
    _SEGREDO_CACHE["v"] = s.encode("utf-8")
    return _SEGREDO_CACHE["v"]


def token(grupo, empresa, filial, numero, serie) -> str:
    """Identificador opaco da carga, para o detalhe não repetir o documento na
    URL. URL vaza — em log de proxy, no histórico do navegador, no grupo de
    WhatsApp para onde alguém a encaminha."""
    cru = "%s|%s|%s|%s|%s" % (grupo, empresa, filial, numero, serie)
    assinatura = hmac.new(_segredo(), cru.encode("utf-8"),
                          hashlib.sha256).hexdigest()[:16]
    return "%s-%s" % (hashlib.sha256(cru.encode()).hexdigest()[:16], assinatura)


#: Quanto tempo o link do WhatsApp vale. Ele carrega a carga inteira, entao
#: nao pode viver para sempre: mensagem encaminhada num grupo dura anos, e o
#: link nao pode durar junto.
LINK_DIAS = 20


def link_token(grupo, empresa, filial, numero, serie) -> str:
    """Token do link direto, assinado e com prazo.

    VAI NO FRAGMENTO da URL (`#c=`), nunca na query: o que vem depois do `#`
    nao chega ao servidor nem ao log do proxy. E o mesmo caminho do
    "esqueci minha senha" da casa.

    Ele carrega a carga porque o link tem de abrir SEM a pessoa digitar nada —
    era esse o pedido. Em troca, expira: link com prazo encaminhado num grupo
    para de funcionar sozinho.
    """
    ate = int(time.time()) + LINK_DIAS * 86400
    cru = "%s|%s|%s|%s|%s|%s" % (grupo, empresa, filial, numero, serie, ate)
    ass = hmac.new(_segredo(), cru.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    dados = base64.urlsafe_b64encode(cru.encode("utf-8")).decode().rstrip("=")
    return "%s.%s" % (dados, ass)


def link_abrir(token: str) -> dict | None:
    """As chaves da carga de um token de link, ou None. Nunca levanta."""
    try:
        dados, _, ass = (token or "").partition(".")
        if not dados or not ass:
            return None
        pad = "=" * (-len(dados) % 4)
        cru = base64.urlsafe_b64decode(dados + pad).decode("utf-8")
        esperado = hmac.new(_segredo(), cru.encode("utf-8"),
                            hashlib.sha256).hexdigest()[:20]
        if not hmac.compare_digest(ass, esperado):
            return None
        g, e, f, n, sr, ate = cru.split("|")
        if int(ate) < time.time():
            return None
        return {"g": int(g), "e": int(e), "f": int(f), "n": int(n),
                "s": int(sr)}
    except Exception:  # noqa: BLE001
        return None


def _confere_token(t: str, grupo, empresa, filial, numero, serie) -> bool:
    return hmac.compare_digest(t or "", token(grupo, empresa, filial, numero,
                                              serie))


# ---------------------------------------------------------------------------
# a busca
# ---------------------------------------------------------------------------
#: `cadastro.codigo` E o CNPJ/CPF — nao ha coluna `cnpjcpf` nesta base, e e
#: por isso que as chaves estrangeiras do ERP se chamam `cnpjcpfcodigo...`.
#: Quem ler `cd.codigo` esperando um id sequencial erra o filtro em silencio.
#:
#: O CT-e pelo número, pela série ou pela chave de acesso, SEMPRE com o
#: segundo fator. `cnpj4` casa contra o tomador, o pagador OU o destinatário:
#: quem recebe raramente é quem paga, e exigir o CNPJ certo dos três faria a
#: pessoa certa não achar a própria carga.
CTE_SQL = """
SELECT c.grupo, c.empresa, c.filial, c.numero, c.serie,
       c.dtemissao,
       trim(c.veiculo)            AS placa,
       c.cidadecoleta, c.ufcoleta,
       c.dtprevisaoentrega, c.dtentrega, c.dtagendamentoentrega,
       c.dtiniciodescarga,
       cd.nomefantasia            AS destinatario_nome,
       cd.cidade                  AS destinatario_cidade,
       cd.uf                      AS destinatario_uf
FROM conhecimento c
LEFT JOIN cadastro cd ON cd.codigo = c.destinatario
WHERE c.dtcancelamento IS NULL
  AND (%(num)s::text IS NULL OR c.numero::text = %(num)s)
  AND (%(chave)s::text IS NULL OR trim(c.chaveacessocte) = %(chave)s)
  AND (
        strpos(coalesce(cast(c.cnpjcpfcodigotomadorservico AS text),''), %(cnpj4)s) = 1
     OR strpos(coalesce(cast(c.cnpjcpfcodigopagadorfrete   AS text),''), %(cnpj4)s) = 1
     OR strpos(coalesce(cast(cd.codigo                    AS text),''), %(cnpj4)s) = 1
  )
ORDER BY c.dtemissao DESC
LIMIT %(teto)s
"""

#: A NOTA da carga: `coleta_notafiscal` -> `conhecimento_composicao` -> CT-e.
#:
#: DOIS CAMINHOS ERRADOS ANTES DESTE, e vale registrar para ninguem repetir:
#: (1) copiar o padrao do `programacaoembarque` nao serve — o CT-e nao tem
#: `filialdocumentoorigem`; (2) `conhecimento_composicao_notafiscal`, que o
#: nome promete, esta VAZIA nesta instalacao (0 linhas). O dado vive em
#: `coleta_notafiscal` (602.238 linhas), e quem amarra a coleta ao CT-e e a
#: `conhecimento_composicao`.
#:
#: Este e o caminho que mais importa: quem recebe a carga conhece o numero da
#: NOTA, quase nunca o do CT-e.
NF_SQL = """
SELECT c.grupo, c.empresa, c.filial, c.numero, c.serie,
       c.dtemissao,
       trim(c.veiculo)            AS placa,
       c.cidadecoleta, c.ufcoleta,
       c.dtprevisaoentrega, c.dtentrega, c.dtagendamentoentrega,
       c.dtiniciodescarga,
       cd.nomefantasia            AS destinatario_nome,
       cd.cidade                  AS destinatario_cidade,
       cd.uf                      AS destinatario_uf
FROM coleta_notafiscal cn
JOIN conhecimento_composicao cc
  ON cc.grupo = cn.grupo AND cc.empresa = cn.empresa
 AND cc.filialdocumento = cn.filial AND cc.unidadedocumento = cn.unidade
 AND cc.diferenciadornumerodocumento = cn.diferenciadornumero
 AND cc.seriedocumento = cn.serie AND cc.numerodocumento = cn.numero
JOIN conhecimento c
  ON c.grupo = cc.grupo AND c.empresa = cc.empresa AND c.filial = cc.filial
 AND c.unidade = cc.unidade AND c.diferenciadornumero = cc.diferenciadornumero
 AND c.serie = cc.serie AND c.numero = cc.numero
LEFT JOIN cadastro cd ON cd.codigo = c.destinatario
WHERE c.dtcancelamento IS NULL
  AND (%(num)s::text IS NULL OR cn.numeronotafiscal::text = %(num)s)
  AND (%(chave)s::text IS NULL OR trim(cn.chaveacessonfe) = %(chave)s)
  AND (
        strpos(coalesce(cast(c.cnpjcpfcodigotomadorservico AS text),''), %(cnpj4)s) = 1
     OR strpos(coalesce(cast(c.cnpjcpfcodigopagadorfrete   AS text),''), %(cnpj4)s) = 1
     OR strpos(coalesce(cast(cd.codigo                     AS text),''), %(cnpj4)s) = 1
  )
ORDER BY c.dtemissao DESC
LIMIT %(teto)s
"""


def _estado(r: dict) -> tuple[str, str]:
    """Em que pé está a carga, e a frase que a explica.

    ESTADO VEM DO CAMPO, não da ausência de data — é a regra da casa, e aqui
    ela vale dobrado: "sem data de entrega" pode ser carga a caminho ou
    lançamento atrasado, e a página pública não pode chamar as duas de a mesma
    coisa.
    """
    if r.get("dtentrega"):
        return "entregue", "Entregue"
    if r.get("dtiniciodescarga"):
        return "descarregando", "Chegou ao destino, em descarga"
    if r.get("placa"):
        return "em_viagem", "Em viagem"
    return "preparando", "Coletada, aguardando embarque"


def _limpo(r: dict) -> dict:
    """Uma carga, com SÓ o que pode ser lido por um desconhecido.

    A montagem é por lista explícita e não por cópia do registro: copiar o
    registro faria toda coluna nova do ERP entrar na página pública sozinha.
    """
    estado, rotulo = _estado(r)
    return {
        "id": token(r["grupo"], r["empresa"], r["filial"], r["numero"],
                    r["serie"]),
        "documento": "CT-e %s" % r["numero"],
        "emitido_em": _iso(r.get("dtemissao")),
        "origem": _lugar(r.get("cidadecoleta"), r.get("ufcoleta")),
        "destino": _lugar(r.get("destinatario_cidade"),
                          r.get("destinatario_uf")),
        "destinatario": (r.get("destinatario_nome") or "").strip() or None,
        "previsao": _iso(r.get("dtprevisaoentrega")),
        "agendamento": _iso(r.get("dtagendamentoentrega")),
        "entregue_em": _iso(r.get("dtentrega")),
        "estado": estado,
        "estado_rotulo": rotulo,
    }


def _lugar(cidade, uf) -> str | None:
    c = (cidade or "").strip().title()
    u = (uf or "").strip().upper()
    if not c:
        return None
    return "%s/%s" % (c, u) if u else c


def _iso(v) -> str | None:
    if not v:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def buscar_cru(termo: str, cnpj4: str) -> tuple[list, str | None]:
    """Os registros CRUS das cargas. **NUNCA vai para o navegador.**

    Existe porque o detalhe precisa das chaves internas do documento, e a
    alternativa — devolvê-las dentro do payload de `buscar()` — poria os
    registros do ERP a um `JSONResponse` de distância da página pública. Aqui
    a separação é estrutural: quem chama `buscar()` não tem como vazar o cru
    nem por descuido.

    Devolve `(linhas, motivo_da_recusa)`.
    """
    t = _so_digitos(termo)
    c4 = _so_digitos(cnpj4)
    if len(t) < 3:
        return {"ok": False, "motivo": "informe o número do CT-e ou da nota"}
    if len(c4) != 4:
        return {"ok": False,
                "motivo": "informe os 4 primeiros dígitos do CNPJ"}

    chave = t if len(t) == 44 else None
    num = None if chave else t
    params = {"num": num, "chave": chave, "cnpj4": c4, "teto": TETO}

    vistos: dict[str, dict] = {}
    for sql in (CTE_SQL, NF_SQL):
        try:
            for r in db.query(sql, params):
                d = dict(r)
                chave = token(d["grupo"], d["empresa"], d["filial"],
                              d["numero"], d["serie"])
                vistos.setdefault(chave, d)
        except Exception as exc:  # noqa: BLE001
            log.warning("rastreio: consulta falhou: %s", type(exc).__name__)
            return [], "não foi possível consultar agora"
    return list(vistos.values()), None


def buscar(termo: str, cnpj4: str) -> dict:
    """Acha cargas pelo documento em mãos, JÁ LIMPAS. Nunca levanta.

    `termo` é o número do CT-e, o número da nota ou a chave de acesso de
    qualquer um dos dois. `cnpj4` são os quatro primeiros dígitos do CNPJ.
    """
    if len(_so_digitos(termo)) < 3:
        return {"ok": False, "motivo": "informe o número do CT-e ou da nota"}
    if len(_so_digitos(cnpj4)) != 4:
        return {"ok": False,
                "motivo": "informe os 4 primeiros dígitos do CNPJ"}
    linhas, motivo = buscar_cru(termo, cnpj4)
    if motivo:
        return {"ok": False, "motivo": motivo}
    lista = sorted((_limpo(r) for r in linhas),
                   key=lambda x: x.get("emitido_em") or "", reverse=True)
    return {"ok": True, "cargas": lista, "total": len(lista),
            # A MESMA RESPOSTA para "não existe" e "não é sua": dizer "existe,
            # mas o CNPJ não confere" transformaria a página num confirmador de
            # números de CT-e.
            "consultado_em": datetime.now(timezone.utc).isoformat()}
