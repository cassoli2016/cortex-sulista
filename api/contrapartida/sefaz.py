# api/contrapartida/sefaz.py
"""Camada de compatibilidade entre o CÓRTEX e a biblioteca de e-documentos.

POR QUE ESTE MÓDULO EXISTE
==========================
`erpbrasil.edoc` resolve a parte difícil (schema, SOAP, endereços das SEFAZ),
mas o caminho de **CT-e** dela não está exercitado: a NF-e é o percurso
maduro. Provar isso custou quatro correções só para o "olá mundo" da
integração — a consulta de status do serviço, que não emite documento nenhum.

As quatro estão aqui, isoladas e nomeadas, em vez de espalhadas por scripts.
Todas são de INFRAESTRUTURA, não de regra fiscal: uma vez resolvidas, não
voltam. E quando a biblioteca corrigir qualquer uma delas, o remendo
correspondente vira no-op sozinho — cada um checa antes de agir.

  1. ENDEREÇO DA SEFAZ. `get_service_url` só resolve os grupos SVRS e SVSP.
     Estado com SEFAZ própria (PR, MG, MS, MT) cai no `else`, recebe a STRING
     da sigla no lugar do dicionário de configuração e quebra na linha
     seguinte. A configuração do estado EXISTE no módulo; a função nunca
     chega nela. O primeiro agregado cadastrado é do PR.

  2. SERIALIZAÇÃO. O módulo de CT-e usa classes geradas por **xsdata**
     (`nfelib.cte.bindings.v4_0`), mas a base serializa chamando `.export()`,
     que é a API do **generateDS**. Inconsistência interna da própria
     biblioteca.

  3. CONFIANÇA TLS. As SEFAZ usam certificado de servidor sob ICP-Brasil, cuja
     raiz não está no pacote de certificados que o Python traz. `truststore`
     passa a usar o cofre de raízes do sistema operacional.

  4. LEITURA DA RESPOSTA. Mesmo descasamento do item 2, do lado da volta — e o
     nome do elemento no XML não segue o da classe (`retConsStatServCTe`, com
     "TE" maiúsculo, contra `RetConsStatServCte`).

O QUE ISTO **NÃO** RESOLVE
--------------------------
Montar e assinar o CT-e. O que está provado é que certificado, mTLS, endereço,
envio e leitura funcionam — a infraestrutura. A montagem do documento é código
bem mais exercitado do lado da NF-e e bem menos do lado do CT-e, e deve pedir
mais correções deste tipo.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger("cortex.contrapartida.sefaz")

_APLICADO = False


def _endereco(m) -> None:
    """(1) Estado com SEFAZ propria nao e resolvido."""
    if getattr(m.get_service_url, "_cortex", False):
        return
    _orig = m.get_service_url

    def resolvido(sigla, service, ambiente):
        cfg = getattr(m, sigla, None)
        if (isinstance(cfg, dict) and sigla not in m.SVSP_STATES
                and sigla not in m.SVRS_STATES):
            amb = (m.AMBIENTE_PRODUCAO if ambiente == 1
                   else m.AMBIENTE_HOMOLOGACAO)
            return "https://" + cfg[amb]["servidor"] + "/" + cfg[amb][service]
        return _orig(sigla, service, ambiente)

    resolvido._cortex = True
    m.get_service_url = resolvido


def _serializacao(base) -> None:
    """(2) Classes xsdata serializadas pela API do generateDS."""
    alvo = base.DocumentoEletronico
    if getattr(alvo._generateds_to_string_etree, "_cortex", False):
        return
    _orig = alvo._generateds_to_string_etree

    def serializa(self, ds, pretty_print=False):
        if hasattr(ds, "export"):           # generateDS: caminho da biblioteca
            return _orig(self, ds, pretty_print)
        from lxml import etree
        from xsdata.formats.dataclass.serializers import XmlSerializer
        from xsdata.formats.dataclass.serializers.config import SerializerConfig
        cfg = SerializerConfig(pretty_print=pretty_print, xml_declaration=False)
        ns = {None: self._namespace} if getattr(self, "_namespace", None) else None
        txt = XmlSerializer(config=cfg).render(ds, ns_map=ns)
        return txt, etree.fromstring(txt.encode("utf-8"))

    serializa._cortex = True
    alvo._generateds_to_string_etree = serializa


def _confianca_tls() -> None:
    """(3) Raiz ICP-Brasil nao esta no pacote de certificados do Python."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception as exc:  # noqa: BLE001
        log.warning("truststore indisponivel - o TLS com a SEFAZ pode falhar "
                    "por raiz ICP-Brasil desconhecida: %s", exc)


def _leitura(*modulos) -> None:
    """(4) Resposta lida pela API do generateDS, e nome do elemento diferente
    do nome da classe."""
    from erpbrasil.edoc import resposta as resp
    if getattr(resp.analisar_retorno_raw, "_cortex", False):
        return
    _orig = resp.analisar_retorno_raw

    def analisa(operacao, raiz, xml_string, retorno, classe):
        if hasattr(classe, "parseString"):   # generateDS: caminho da biblioteca
            return _orig(operacao, raiz, xml_string, retorno, classe)
        from lxml import etree
        from xsdata.formats.dataclass.parsers import XmlParser
        corpo = retorno.text if hasattr(retorno, "text") else retorno
        if isinstance(corpo, bytes):
            corpo = corpo.decode("utf-8", errors="replace")
        doc = etree.fromstring(corpo.encode("utf-8"))
        # Ret<Algo> na classe, ret<Algo> no XML - e o CTe vira CTE. Compara em
        # minusculas em vez de montar o nome, que erraria a caixa.
        esperado = classe.__name__.lower()
        alvo = None
        for el in doc.iter():
            if etree.QName(el).localname.lower() == esperado:
                alvo = el
                break
        if alvo is None:
            # sem o elemento, parsear o envelope inteiro produz erro obscuro
            # ("Unknown property ... Header") em vez de dizer o que faltou
            raise ValueError(
                f"A SEFAZ respondeu sem o elemento <{esperado}>. "
                f"Resposta: {corpo[:300]}")
        return XmlParser().parse(io.BytesIO(etree.tostring(alvo)), classe)

    analisa._cortex = True
    resp.analisar_retorno_raw = analisa
    for m in modulos:                # o modulo base importou o nome direto
        if hasattr(m, "analisar_retorno_raw"):
            m.analisar_retorno_raw = analisa


def compatibilizar():
    """Aplica as quatro correcoes e devolve o modulo de CT-e pronto para uso.

    Idempotente: cada remendo checa antes de agir, entao chamar duas vezes nao
    empilha camadas - e se a biblioteca corrigir o defeito, o remendo some.
    """
    global _APLICADO
    import erpbrasil.edoc.cte as cte
    import erpbrasil.edoc.edoc as base
    if not _APLICADO:
        _confianca_tls()
        _APLICADO = True
    _endereco(cte)
    _serializacao(base)
    _leitura(base)
    return cte


# AMBIENTE. '2' = homologacao. Producao NAO tem atalho neste modulo de
# proposito: trocar de ambiente tem de ser decisao explicita de quem chama, e
# nao uma constante que alguem sobrescreve sem perceber.
HOMOLOGACAO = "2"


def status_servico(cnpj: str, uf: str, ambiente: str = HOMOLOGACAO) -> dict:
    """Consulta se a SEFAZ da UF esta no ar. NAO emite documento nenhum.

    A UF e a do EMITENTE (o agregado), nao a da Sulista: cada SEFAZ so atende
    os seus contribuintes.
    """
    from erpbrasil.assinatura.certificado import Certificado
    from erpbrasil.transmissao import TransmissaoSOAP

    from api.contrapartida import cadastro

    cte = compatibilizar()
    reg = (cadastro.mapa().get(cnpj) or {}).get("certificado") or {}
    senha = cadastro.ler_senha(cnpj)
    arq = cadastro.DIR_CERT / (reg.get("arquivo") or "")
    if not (senha and arq.exists()):
        raise FileNotFoundError(
            f"Certificado ou senha ausentes para {cnpj} — cadastre pela tela.")
    if uf not in cte.SIGLA_ESTADO:
        raise ValueError(f"UF desconhecida: {uf}")

    doc = cte.CTe(TransmissaoSOAP(Certificado(str(arq), senha)),
                  cte.SIGLA_ESTADO[uf], ambiente=ambiente)
    r = doc.status_servico()
    def _v(campo):
        v = getattr(r, campo, None)
        # xsdata devolve enum: o `.value` e o codigo que a SEFAZ mandou
        return getattr(v, "value", v)
    return {"cStat": _v("cStat"), "xMotivo": _v("xMotivo"),
            "tpAmb": _v("tpAmb"), "cUF": _v("cUF"),
            "verAplic": _v("verAplic"), "dhRecbto": str(_v("dhRecbto") or ""),
            "em_operacao": str(_v("cStat")) == "107"}
