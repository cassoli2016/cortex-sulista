# api/contrapartida/documento.py
"""Montagem do CT-e de contrapartida do agregado — esqueleto.

O QUE ESTE MÓDULO FAZ, E O QUE ELE SE RECUSA A FAZER
====================================================
Dado o CT-e que a **Sulista** emitiu com veículo de agregado, este módulo
reúne, do ERP, tudo que o CT-e **do agregado contra a Sulista** exige, e monta
o objeto do schema 4.0. Ele **não assina e não transmite** — há guarda de
árvore sintática no teste, como já existe para `servico.py`.

E ele **não decide fiscalidade**. Seis respostas não estão no banco e não são
decisão de software; sem elas o documento sairia plausível e errado, que é o
pior resultado possível num documento fiscal. Por isso `Enquadramento` é um
dataclass **sem um único valor padrão**: não existe caminho de código que monte
um CT-e sem alguém ter respondido as seis. Esquecer é impossível; responder
errado continua sendo humano.

O QUE O ERP RESPONDE SOZINHO (medido em 26/08/2026)
---------------------------------------------------
  emitente (o agregado)  `cadastro`: razão social, IE, RNTRC, endereço, CEP
  tomador (a Sulista)    `filial`: CNPJ, IE, endereço da filial do CT-e
  origem/destino         `conhecimento`: ufcoleta/cidadecoleta, ufentrega/…
  carga                  peso, valor da mercadoria, km
  referência             `conhecimento.chaveacessocte` — a chave do CT-e da
                         Sulista, que é o elo que faz este documento ser
                         contrapartida e não prestação solta
  valor pago ao agregado `programacaoembarque.valorfretecompra`

DUAS ARMADILHAS DO DADO, JÁ TRATADAS AQUI
-----------------------------------------
  1. **CEP é INTEIRO no ERP.** O de Santo André volta `9280200`: o zero à
     esquerda foi comido pelo tipo numérico. Em SP isso vale para o estado
     inteiro. Emitir com 7 dígitos é rejeição na validação de schema.
  2. **Não existe código IBGE no cadastro.** O município vem por NOME, e a
     tabela `cidade_ibge` guarda com acento (`SANTO ANDRÉ`) enquanto o
     `cadastro` guarda sem (`SANTO ANDRE`): por nome exato casam 34 das 51
     cidades dos agregados; **sem acento, casam 51 de 51**. Quando não casar,
     este módulo LEVANTA ERRO nomeando a cidade — jamais chuta o código de um
     município, que é campo de identificação da prestação.

O QUE O CT-e DA SULISTA JÁ ENSINA SOBRE O ENQUADRAMENTO
-------------------------------------------------------
Não é resposta, é evidência para levar à contabilidade: em 90 dias, 30 CT-e da
Sulista têm `tiposervico = 2` e CFOP **6351** ("prestação de serviço de
transporte para execução de serviço da mesma natureza") e tomador que não é
nem remetente nem destinatário — ou seja, **a própria Sulista já emite, hoje,
o documento com esta exata forma quando presta para outra transportadora.**
O documento do agregado contra a Sulista é o espelho desse caso.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from api import db

# UTC−3 sem depender do relógio da máquina: `dhEmi` do CT-e exige o offset
# explícito, e um servidor em UTC mandaria o documento uma hora fora.
FUSO = timezone(timedelta(hours=-3))

# O tomador é sempre a Sulista neste documento — mas o CNPJ da FILIAL varia,
# e é o da filial que emitiu o CT-e original.
MODELO_CTE = "57"

# Em homologação o nome do destinatário/tomador é fixado por norma. Sem isso o
# documento é rejeitado mesmo estando tudo o mais correto.
# SEM hífen em "CTE", e é literal: a SEFAZ compara caractere a caractere.
# "CT-E EMITIDO..." (a grafia que o resto do mundo usa, e a que a NF-e pede)
# leva rejeição 646 — a mesma que se leva sem carimbo nenhum, o que faz a
# tentativa parecer não ter surtido efeito.
XNOME_HOMOLOGACAO = "CTE EMITIDO EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"


# ------------------------------------------------------------ enquadramento --

@dataclass(frozen=True)
class Enquadramento:
    """As seis respostas que a contabilidade tem de dar. Sem padrão nenhum.

    `cfop`        CFOP do documento do agregado. A evidência do próprio ERP
                  aponta a família 5.351/6.351 (prestação a outro transportador),
                  que é a que a Sulista usa quando ela é a subcontratada.
    `tp_serv`     `ide/tpServ` do schema: '0' normal · '1' subcontratação ·
                  '2' redespacho · '3' redespacho intermediário · '4' multimodal.
                  ATENÇÃO: o ERP guarda esse domínio em base 1 (`tiposervico`
                  1 = normal, 2 = subcontratação); aqui vale o do SCHEMA.
    `grupo_icms`  qual grupo do `imp/ICMS` usar: 'ICMS00' (tributado integral),
                  'ICMS90' (outros), 'ICMSSN' (Simples Nacional). O Parizotto
                  está com `optantesimples = 1` no cadastro, o que lido pela
                  distribuição do próprio campo (728 de 8.293) significa SIM —
                  mas inferir regime tributário de código de ERP para gravar em
                  documento fiscal é exatamente o que este módulo não faz.
    `cst_icms`    a CST do grupo escolhido.
    `p_icms`      alíquota, quando o grupo pedir (ICMSSN não pede).
    `base_valor`  'prestacao'   = o que a Sulista cobrou do cliente
                  'fretecompra' = o que a Sulista paga ao agregado
                  São números diferentes: no CT-e de teste, R$ 1.494,02 contra
                  R$ 1.066,32. É base de ICMS, então não é escolha de software.
    `toma`        quem é o tomador no documento do agregado: '0' remetente ·
                  '1' expedidor · '2' recebedor · '3' destinatário · '4' outros
                  (com CNPJ informado — é o caso se o tomador for a Sulista).
    `referenciar_original`
                  se o CT-e da Sulista entra como documento anterior
                  (`infCTeNorm/docAnt`). É o elo que caracteriza a contrapartida.
    """
    cfop: str
    tp_serv: str
    grupo_icms: str
    cst_icms: str
    p_icms: Decimal | None
    base_valor: str
    toma: str
    referenciar_original: bool

    def __post_init__(self) -> None:
        if self.base_valor not in ("prestacao", "fretecompra"):
            raise ValueError("base_valor: use 'prestacao' ou 'fretecompra'.")
        if self.grupo_icms not in ("ICMS00", "ICMS90", "ICMSSN"):
            raise ValueError("grupo_icms: use 'ICMS00', 'ICMS90' ou 'ICMSSN'.")
        if self.toma not in ("0", "1", "2", "3", "4"):
            raise ValueError("toma: use '0'..'4' conforme o schema.")
        if self.tp_serv not in ("0", "1", "2", "3", "4"):
            raise ValueError("tp_serv: use '0'..'4' conforme o schema (NÃO o "
                             "código do ERP, que é base 1).")
        if self.grupo_icms in ("ICMS00", "ICMS90") and self.p_icms is None:
            raise ValueError(f"{self.grupo_icms} exige alíquota (p_icms).")

        # As duas combinações que a SEFAZ recusa, medidas em homologação em
        # 26/08/2026. Não são preferência de projeto: são regra de validação
        # do órgão, e sem esta guarda cada uma custa uma transmissão e um
        # número de série queimado para ser redescoberta.
        if self.tp_serv == "0" and self.toma == "4":
            raise ValueError(
                "Prestação NORMAL não aceita tomador 'outros' (rejeição 746 — "
                "'Tipo de Serviço inválido para o tomador informado'). Em "
                "prestação normal o tomador tem de ser uma das partes da "
                "carga (remetente, expedidor, recebedor ou destinatário), ou "
                "seja: o documento seria emitido contra o CLIENTE, não contra "
                "a Sulista. Tomador 'outros' exige subcontratação ou "
                "redespacho.")
        if self.tp_serv == "0" and self.referenciar_original:
            raise ValueError(
                "Prestação NORMAL não aceita vínculo com o CT-e anterior "
                "(rejeição 747 — 'Documentos anteriores informados para Tipo "
                "de Serviço Normal'). O grupo de documentos anteriores é "
                "exclusivo de subcontratação e redespacho: em prestação "
                "normal NADA no documento o liga ao CT-e da Sulista.")


# ------------------------------------------------------------------ o dado --

# `programacaoembarque_composicao` é o que liga documento a embarque. Importa
# saber que a relação NÃO é 1:1 — em 90 dias, 6.578 CT-e de agregado PJ vieram
# de 3.834 embarques (1,7 por embarque). Quando o embarque tem mais de um
# documento, `valorfretecompra` é do EMBARQUE INTEIRO e ratear entre os CT-e é
# decisão fiscal, não aritmética; por isso a contagem volta no resultado.
DADOS_SQL = """
SELECT k.filial, k.serie, k.numero, k.dtemissao, k.chaveacessocte,
       k.veiculo, k.naturezaoperacao, k.tiposervico AS tiposervico_erp,
       k.tomadorservico AS tomadorservico_erp,
       k.valortotalprestacao, k.valortotalmercadoria, k.pesobruto, k.kmfrete,
       k.ufcoleta, k.cidadecoleta, k.ufentrega, k.cidadeentrega,
       k.situacaotributariaicms AS cst_erp, k.percaliquotaicms AS aliq_erp,
       -- emitente do documento novo: o AGREGADO
       cd.codigo AS emit_cnpj, cd.razaosocial AS emit_nome,
       cd.nomefantasia AS emit_fantasia, cd.inscricaoestadual AS emit_ie,
       cd.numerorntrc AS emit_rntrc, cd.optantesimples AS emit_optante_simples,
       cd.endereco AS emit_logradouro, cd.numero AS emit_numero,
       cd.complemento AS emit_complemento, cd.bairro AS emit_bairro,
       cd.cidade AS emit_cidade, cd.uf AS emit_uf, cd.cep AS emit_cep,
       cd.dddfone AS emit_ddd, cd.fonesemddd AS emit_fone,
       -- tomador do documento novo: a FILIAL da Sulista que emitiu o original
       f.cnpj AS toma_cnpj, f.apelido AS toma_apelido,
       f.inscricaoestadual AS toma_ie, f.endereco AS toma_logradouro,
       f.numero AS toma_numero, f.complemento AS toma_complemento,
       f.bairro AS toma_bairro, f.cidade AS toma_cidade, f.uf AS toma_uf,
       f.cep AS toma_cep,
       -- REMETENTE e DESTINATARIO: os mesmos da carga, copiados do CT-e da
       -- Sulista. Nao e escolha: nos 30 CT-e em que a propria Sulista e a
       -- subcontratada, ela mantem o remetente e o destinatario REAIS e poe a
       -- transportadora contratante como tomador "outros". A SEFAZ recusa com
       -- cStat 469 se o remetente faltar.
       re.codigo AS rem_cnpj, re.razaosocial AS rem_nome,
       re.inscricaoestadual AS rem_ie, re.endereco AS rem_logradouro,
       re.numero AS rem_numero, re.complemento AS rem_complemento,
       re.bairro AS rem_bairro, re.cidade AS rem_cidade, re.uf AS rem_uf,
       re.cep AS rem_cep,
       de.codigo AS dest_cnpj, de.razaosocial AS dest_nome,
       de.inscricaoestadual AS dest_ie, de.endereco AS dest_logradouro,
       de.numero AS dest_numero, de.complemento AS dest_complemento,
       de.bairro AS dest_bairro, de.cidade AS dest_cidade, de.uf AS dest_uf,
       de.cep AS dest_cep,
       -- o que a Sulista PAGA pela viagem, e quantos documentos dividem isso
       p.numero AS embarque, p.valorfretecompra, p.valorpedagiocompra,
       (SELECT count(*)::int FROM programacaoembarque_composicao c
         WHERE c.numero = p.numero
           AND c.diferenciadornumero = p.diferenciadornumero)
         AS documentos_no_embarque
  FROM conhecimento k
  JOIN veiculo v   ON v.placa = k.veiculo
  JOIN cadastro cd ON cd.codigo = v.proprietario
  JOIN filial f    ON f.codigo = k.filial
  LEFT JOIN cadastro re ON re.codigo = k.remetente
  LEFT JOIN cadastro de ON de.codigo = k.destinatario
  LEFT JOIN programacaoembarque_composicao pc
         ON pc.filialdocumento = k.filial AND pc.seriedocumento = k.serie
        AND pc.numerodocumento = k.numero
  LEFT JOIN programacaoembarque p
         ON p.numero = pc.numero
        AND p.diferenciadornumero = pc.diferenciadornumero
 WHERE k.chaveacessocte = %(chave)s
"""

# As NOTAS TRANSPORTADAS. A SEFAZ rejeita com cStat 693 ("Grupo Documentos
# Transportados deve ser informado") todo CT-e cujo tpServ não seja redespacho
# intermediário nem vinculado a multimodal — ou seja, praticamente todos. O
# XSD deixa o grupo OPCIONAL: quem o exige é a regra de negócio, então isto
# nunca apareceria numa validação local.
# Medido: o CT-e piloto carrega DUAS notas, então nunca foi campo único.
NOTAS_SQL = """
SELECT nf.chaveacessonfe AS chave, nf.modelo,
       nf.numeronotafiscal AS numero, nf.serienotafiscal AS serie,
       nf.cnpjcpfcodigoemissor AS emissor,
       nf.valormercadoria::float8 AS valor, nf.pesobruto::float8 AS peso
  FROM conhecimento k
  JOIN conhecimento_notafiscal nf
    ON nf.filial = k.filial AND nf.serie = k.serie AND nf.numero = k.numero
   AND nf.diferenciadornumero = k.diferenciadornumero
 WHERE k.chaveacessocte = %(chave)s
 ORDER BY nf.sequencianotafiscal
"""

# O acento é a única diferença entre as duas grafias; `unaccent` não está
# instalado na réplica, então o translate faz o trabalho nos dois lados.
_SEM_ACENTO = ("translate(upper({}),"
               "'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ','AAAAAEEEEIIIIOOOOOUUUUC')")

IBGE_SQL = f"""
SELECT codigoibge, municipio FROM cidade_ibge
 WHERE uf = %(uf)s
   AND {_SEM_ACENTO.format('municipio')} = {_SEM_ACENTO.format('%(cidade)s')}
"""


def ibge(uf: str, cidade: str) -> tuple[int, str]:
    """Código IBGE do município, ou erro nomeando quem não casou.

    Devolve também a grafia OFICIAL (com acento): é ela que vai no XML, não a
    do cadastro — `xMun` e `cMun` têm de descrever o mesmo município.
    """
    uf = (uf or "").strip().upper()
    cidade = " ".join((cidade or "").split())
    if not (uf and cidade):
        raise ValueError("Município ou UF ausentes no cadastro.")
    r = db.query(IBGE_SQL, {"uf": uf, "cidade": cidade})
    if not r:
        raise ValueError(
            f"Município sem código IBGE: {cidade}/{uf}. O CT-e identifica a "
            f"prestação por esse código — corrija o cadastro em vez de chutar.")
    return int(r[0]["codigoibge"]), r[0]["municipio"]


def cep(valor) -> str:
    """CEP do ERP é INTEIRO: `9280200` é `09280200`. Todo SP começa com zero."""
    if valor in (None, "", 0):
        raise ValueError("CEP ausente no cadastro.")
    texto = "".join(c for c in str(valor) if c.isdigit()).zfill(8)
    if len(texto) != 8:
        raise ValueError(f"CEP fora do padrão: {valor!r}")
    return texto


def _fone(ddd, numero) -> str | None:
    d = "".join(c for c in f"{ddd or ''}{numero or ''}" if c.isdigit())
    return d if 6 <= len(d) <= 14 else None


def dados(chave: str) -> dict:
    """Tudo que o documento novo precisa, a partir da chave do CT-e original."""
    chave = "".join(c for c in (chave or "") if c.isdigit())
    if len(chave) != 44:
        raise ValueError("Chave de CT-e tem 44 dígitos.")
    linhas = db.query(DADOS_SQL, {"chave": chave})
    if not linhas:
        raise ValueError(f"CT-e não encontrado na réplica: {chave}")
    d = dict(linhas[0])

    for papel in ("rem", "dest"):
        if not d.get(f"{papel}_cnpj"):
            raise ValueError(
                f"O CT-e {chave} não tem {papel} no cadastro do ERP. A SEFAZ "
                f"recusa (cStat 469) CT-e sem remetente para este tipo de "
                f"serviço.")
        d[f"{papel}_cmun"], d[f"{papel}_xmun"] = ibge(
            d[f"{papel}_uf"], d[f"{papel}_cidade"])
        d[f"{papel}_cep8"] = cep(d[f"{papel}_cep"])

    d["emit_cmun"], d["emit_xmun"] = ibge(d["emit_uf"], d["emit_cidade"])
    d["ini_cmun"], d["ini_xmun"] = ibge(d["ufcoleta"], d["cidadecoleta"])
    d["fim_cmun"], d["fim_xmun"] = ibge(d["ufentrega"], d["cidadeentrega"])
    d["emit_cep8"] = cep(d["emit_cep"])
    d["toma_cep8"] = cep(d["toma_cep"])
    d["chave_original"] = chave

    # Rateio é decisão fiscal: o módulo mede e avisa, não divide sozinho.
    n = d.get("documentos_no_embarque") or 0
    d["exige_rateio"] = n > 1

    # Só NF-e (modelo 55) entra em `infNFe`; nota em papel tem grupo PRÓPRIO
    # (`infNF`) e chave nenhuma. Misturar os dois produz um XML que valida no
    # schema e é rejeitado pela SEFAZ.
    notas = db.query(NOTAS_SQL, {"chave": chave})
    d["notas"] = [x for x in notas
                  if str(x.get("modelo") or "") == "55" and x.get("chave")]
    d["notas_sem_chave"] = [x for x in notas if not x.get("chave")]
    return d


def valor(d: dict, enq: Enquadramento) -> Decimal:
    """O valor da prestação do documento novo, segundo a base escolhida."""
    if enq.base_valor == "prestacao":
        v = d.get("valortotalprestacao")
    else:
        v = d.get("valorfretecompra")
        if v is None:
            raise ValueError(
                "Este CT-e não tem embarque com valor de frete de compra "
                "(vale para 535 dos 6.578 do trimestre) — não dá para usar "
                "'fretecompra' como base aqui.")
        if d.get("exige_rateio"):
            raise ValueError(
                f"O embarque {d['embarque']} tem {d['documentos_no_embarque']} "
                f"documentos e um único valor de frete de compra. Ratear entre "
                f"eles é definição fiscal, não aritmética — resolva antes.")
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


# --------------------------------------------------------------- o esqueleto --

def montar(d: dict, enq: Enquadramento, *, numero: int, serie: int = 1,
           ambiente: str = "2", homologacao_forca_xnome: bool = True):
    """Monta o objeto do CT-e 4.0. NÃO assina e NÃO transmite.

    `ambiente` '2' é homologação. Produção não tem atalho aqui, pela mesma
    razão de `sefaz.py`: trocar de ambiente é decisão explícita de quem chama.
    """
    from erpbrasil.base.fiscal.edoc import ChaveEdoc
    from nfelib.cte.bindings.v4_0 import Cte

    I = Cte.InfCte
    emitido_em = datetime.now(FUSO).replace(microsecond=0)
    v = valor(d, enq)

    chave = ChaveEdoc(
        codigo_uf=_cuf(d["emit_uf"]), ano_mes=emitido_em.strftime("%y%m"),
        cnpj_cpf_emitente=d["emit_cnpj"], modelo_documento=MODELO_CTE,
        numero_serie=serie, numero_documento=numero, forma_emissao=1,
        validar=False)

    ide = I.Ide(
        cUF=str(_cuf(d["emit_uf"])), cCT=chave.codigo_aleatorio,
        CFOP=enq.cfop, natOp=_natop(enq),
        mod=MODELO_CTE, serie=str(serie), nCT=str(numero),
        dhEmi=emitido_em.isoformat(), tpImp="1", tpEmis="1",
        cDV=str(chave.digito_verificador), tpAmb=str(ambiente),
        tpCTe="0", procEmi="0", verProc="CORTEX",
        # o município de ENVIO é o do emitente — o agregado
        cMunEnv=str(d["emit_cmun"]), xMunEnv=d["emit_xmun"],
        UFEnv=d["emit_uf"], modal="01", tpServ=enq.tp_serv,
        cMunIni=str(d["ini_cmun"]), xMunIni=d["ini_xmun"], UFIni=d["ufcoleta"],
        cMunFim=str(d["fim_cmun"]), xMunFim=d["fim_xmun"], UFFim=d["ufentrega"],
        retira="1", indIEToma="1")

    if enq.toma == "4":
        toma4 = _tipo(I.Ide, "toma4")
        toma_cmun, toma_xmun = ibge(d["toma_uf"], d["toma_cidade"])
        ide.toma4 = toma4(
            toma="4", CNPJ=_so_digitos(d["toma_cnpj"]),
            IE=_so_digitos(d["toma_ie"]),
            # O tomador fica com o nome REAL: a rejeição 646 fala do
            # remetente, e carimbar os dois trocaria um erro por outro.
            xNome=_nome_sulista(d),
            enderToma=_tipo(toma4, "enderToma")(
                xLgr=d["toma_logradouro"], nro=str(d["toma_numero"] or "S/N"),
                xCpl=d["toma_complemento"] or None, xBairro=d["toma_bairro"],
                cMun=str(toma_cmun), xMun=toma_xmun,
                CEP=d["toma_cep8"], UF=d["toma_uf"], cPais="1058",
                xPais="BRASIL"))
    else:
        ide.toma3 = _tipo(I.Ide, "toma3")(toma=enq.toma)

    emit = I.Emit(
        CNPJ=_so_digitos(d["emit_cnpj"]), IE=_so_digitos(d["emit_ie"]),
        xNome=d["emit_nome"], xFant=d["emit_fantasia"] or None,
        # CRT vem do enquadramento: ler regime tributário de código de ERP
        # para gravar em documento fiscal é o erro que este módulo evita.
        CRT="1" if enq.grupo_icms == "ICMSSN" else "3",
        enderEmit=_tipo(I.Emit, "enderEmit")(
            xLgr=d["emit_logradouro"], nro=str(d["emit_numero"] or "S/N"),
            xCpl=d["emit_complemento"] or None, xBairro=d["emit_bairro"],
            cMun=str(d["emit_cmun"]), xMun=d["emit_xmun"],
            CEP=d["emit_cep8"], UF=d["emit_uf"],
            fone=_fone(d["emit_ddd"], d["emit_fone"])))

    # Remetente e destinatário são os da CARGA, iguais aos do CT-e da Sulista.
    # O nome de homologação NÃO vem para cá: a norma fixa o nome do TOMADOR,
    # e carimbá-lo também aqui trocaria um erro por outro.
    homolog = ambiente == "2" and homologacao_forca_xnome
    rem_cls = _tipo(I, "rem")
    rem = rem_cls(
        CNPJ=_so_digitos(d["rem_cnpj"]), IE=_so_digitos(d["rem_ie"]),
        # É o REMETENTE que a norma carimba em homologação, não o tomador —
        # descoberto por rejeição 646, depois de eu ter apostado no tomador.
        # O CNPJ e o endereço continuam os reais; só a razão social troca.
        xNome=(XNOME_HOMOLOGACAO if homolog else d["rem_nome"]),
        enderReme=_tipo(rem_cls, "enderReme")(
            xLgr=d["rem_logradouro"], nro=str(d["rem_numero"] or "S/N"),
            xCpl=d["rem_complemento"] or None, xBairro=d["rem_bairro"],
            cMun=str(d["rem_cmun"]), xMun=d["rem_xmun"],
            CEP=d["rem_cep8"], UF=d["rem_uf"], cPais="1058", xPais="BRASIL"))

    dest_cls = _tipo(I, "dest")
    dest = dest_cls(
        CNPJ=_so_digitos(d["dest_cnpj"]), IE=_so_digitos(d["dest_ie"]),
        xNome=(XNOME_HOMOLOGACAO if homolog else d["dest_nome"]),
        enderDest=_tipo(dest_cls, "enderDest")(
            xLgr=d["dest_logradouro"], nro=str(d["dest_numero"] or "S/N"),
            xCpl=d["dest_complemento"] or None, xBairro=d["dest_bairro"],
            cMun=str(d["dest_cmun"]), xMun=d["dest_xmun"],
            CEP=d["dest_cep8"], UF=d["dest_uf"], cPais="1058", xPais="BRASIL"))

    vprest = I.VPrest(
        vTPrest=_dec(v), vRec=_dec(v),
        comp=[_tipo(I.VPrest, "comp")(xNome="FRETE PESO", vComp=_dec(v))])

    imp = I.Imp(ICMS=_icms(I, enq, v))

    norm_cls = _tipo(I, "infCTeNorm")
    carga_cls = _tipo(norm_cls, "infCarga")
    norm = norm_cls(
        infCarga=carga_cls(
            vCarga=_dec(Decimal(str(d.get("valortotalmercadoria") or 0))),
            proPred="DIVERSOS",
            infQ=[_tipo(carga_cls, "infQ")(
                cUnid="01", tpMed="PESO BRUTO",
                qCarga=_dec(Decimal(str(d.get("pesobruto") or 0)), casas=4))]),
    )
    # As notas transportadas. Sem elas a SEFAZ devolve cStat 693, e a mensagem
    # é clara — mas só aparece na TRANSMISSÃO: o XSD deixa o grupo opcional.
    if not d.get("notas"):
        sem = len(d.get("notas_sem_chave") or [])
        raise ValueError(
            f"O CT-e {d['chave_original']} não tem NF-e com chave na réplica"
            + (f" ({sem} nota(s) sem chave de acesso)" if sem else "")
            + " — a SEFAZ exige o grupo de Documentos Transportados.")
    inf_doc = _tipo(norm_cls, "infDoc")
    norm.infDoc = inf_doc(
        infNFe=[_tipo(inf_doc, "infNFe")(chave=n["chave"])
                for n in d["notas"]])

    if enq.referenciar_original:
        # É AQUI que o documento vira contrapartida: sem este grupo ele é uma
        # prestação solta e nada o liga ao CT-e que a Sulista já emitiu.
        doc_ant = _tipo(norm_cls, "docAnt")
        emi_ant = _tipo(doc_ant, "emiDocAnt")
        id_ant = _tipo(emi_ant, "idDocAnt")
        norm.docAnt = doc_ant(
            emiDocAnt=[emi_ant(
                CNPJ=_so_digitos(d["toma_cnpj"]), IE=_so_digitos(d["toma_ie"]),
                UF=d["toma_uf"], xNome=_nome_sulista(d),
                idDocAnt=[id_ant(idDocAntEle=[
                    _tipo(id_ant, "idDocAntEle")(
                        chCTe=d["chave_original"])])])])

    # O modal entra como elemento à parte no schema (`infModal/any_element`),
    # com versão PRÓPRIA — é um XSD separado do CT-e e as duas versões não
    # andam juntas. O RNTRC do agregado é obrigatório no rodoviário; sem ele a
    # rejeição vem documento a documento, que é o erro que para a operação.
    from nfelib.cte.bindings.v4_0.cte_modal_rodoviario_v4_00 import Rodo
    if not _so_digitos(d["emit_rntrc"]):
        raise ValueError(
            f"O agregado {d['emit_nome']} está sem RNTRC no cadastro — o "
            f"modal rodoviário do CT-e o exige.")
    norm.infModal = _tipo(norm_cls, "infModal")(
        versaoModal="4.00", any_element=Rodo(RNTRC=_so_digitos(d["emit_rntrc"])))

    # A versão mora em `infCte`, não na raiz: `Cte` só tem infCte, infCTeSupl
    # e a assinatura — que este módulo deixa vazia de propósito.
    inf = I(ide=ide, emit=emit, rem=rem, dest=dest, vPrest=vprest, imp=imp,
            infCTeNorm=norm, versao="4.00", Id=f"CTe{chave.chave}")
    return Cte(infCte=inf)


def serializar(cte) -> str:
    """XML do documento, sem assinatura. Serializar não é assinar: o que sai
    daqui não vale como documento fiscal e não é transmitido por este módulo."""
    from xsdata.formats.dataclass.serializers import XmlSerializer
    from xsdata.formats.dataclass.serializers.config import SerializerConfig
    # `indent` e nao `pretty_print`: o segundo esta depreciado no xsdata desta
    # versao. O remendo de `sefaz.py` continua com o nome antigo de proposito —
    # la ele reproduz a chamada da biblioteca, aqui a chamada e nossa.
    cfg = SerializerConfig(indent="  ", xml_declaration=False)
    return XmlSerializer(config=cfg).render(
        cte, ns_map={None: "http://www.portalfiscal.inf.br/cte"})


def _natop(enq: Enquadramento) -> str:
    return {"0": "PRESTACAO DE SERVICO DE TRANSPORTE",
            "1": "SUBCONTRATACAO",
            "2": "REDESPACHO",
            "3": "REDESPACHO INTERMEDIARIO",
            "4": "SERVICO VINCULADO A MULTIMODAL"}[enq.tp_serv]


def _tipo(cls, campo):
    """A classe aninhada por trás de um campo do binding.

    O gerador do xsdata batiza a classe interna com a grafia do ELEMENTO
    (`enderToma`, `idDocAntEle`), que não é a grafia do atributo Python nem
    segue CamelCase — `Toma4.EnderToma` não existe. Resolver pela anotação
    dispensa adivinhar o nome, e quebra alto se o schema mudar de forma.
    """
    import typing
    anot = typing.get_type_hints(cls)[campo]
    args = [a for a in typing.get_args(anot) if isinstance(a, type)
            and a is not type(None)]
    return args[0] if args else anot


def _icms(I, enq: Enquadramento, v: Decimal):
    icms_cls = _tipo(I.Imp, "ICMS")
    grupo = _tipo(icms_cls, enq.grupo_icms)
    if enq.grupo_icms == "ICMSSN":
        # Simples Nacional não destaca ICMS no CT-e: o grupo tem só CST e a
        # marca de que o emitente é optante.
        return icms_cls(ICMSSN=grupo(CST=enq.cst_icms, indSN="1"))
    icms = (v * (enq.p_icms or Decimal(0)) / Decimal(100)).quantize(
        Decimal("0.01"))
    campos = {"CST": enq.cst_icms, "vBC": _dec(v), "pICMS": _dec(enq.p_icms),
              "vICMS": _dec(icms)}
    return icms_cls(**{enq.grupo_icms: grupo(**campos)})


def _nome_sulista(d: dict) -> str:
    return " ".join(str(d.get("toma_apelido") or "SULISTA").split())


def _so_digitos(v) -> str | None:
    d = "".join(c for c in str(v or "") if c.isdigit())
    return d or None


def _dec(v, casas: int = 2) -> str:
    return str(Decimal(str(v or 0)).quantize(Decimal(10) ** -casas))


def _cuf(uf: str) -> int:
    """Código IBGE da UF. `ESTADOS_IBGE` é {codigo: [sigla, nome]} — indexado
    pelo código, não pela sigla, então a busca é pelo valor."""
    from erpbrasil.base.fiscal.edoc import ESTADOS_IBGE
    alvo = (uf or "").strip().upper()
    for codigo, (sigla, _nome) in ESTADOS_IBGE.items():
        if sigla == alvo:
            return int(codigo)
    raise ValueError(f"UF desconhecida: {uf!r}")
