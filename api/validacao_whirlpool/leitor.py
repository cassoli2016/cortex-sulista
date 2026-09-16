"""Lê os dois documentos que a Whirlpool manda antes da emissão.

Toda coleta da Whirlpool recebe no ERP a ocorrência 262 (PRÉ CÁLCULO) com um
PDF anexado, gerado pelo sistema de transportes DELA. Medido em 16/09/2026
sobre os 290 anexos de 90 dias:

- **Pré-Cálculo Inbound** (279): o frete que ela calculou. UMA PÁGINA POR
  FORNECEDOR, e cada página vira um CT-e nosso; a última página traz os
  totais. É daqui que sai a conferência de valor.
- **Ordem de Coleta** (5): peso, volume, itinerário e veículo — sem valor e
  sem CNPJ do fornecedor (só o nome).
- **Requisição de transporte expresso** (5) e anexos avulsos (um PNG, um
  print do Outlook): NÃO são lidos. `ler()` devolve `formato="desconhecido"`
  e a tela diz isso, em vez de fingir que conferiu.

TRÊS ARMADILHAS DO ARQUIVO REAL:

1. **O número vem em DOIS sotaques no mesmo formato de documento.** A maioria
   sai `1,776.85` (americano) e alguns `155,93` (brasileiro). Peso com três
   casas torna `51,000` ambíguo sozinho — 51 kg ou 51 toneladas. O sotaque se
   decide UMA vez por documento, pelos campos de dinheiro (duas casas depois
   do último separador), e vale para todos os números dele.
2. **O fornecedor troca de papel.** Às vezes ele é a "Coleta" e a Whirlpool a
   "Entrega", às vezes o contrário. Quem confere as partes compara o CNPJ do
   fornecedor com os DOIS lados do CT-e.
3. **Pré-Cálculo zerado existe** (valor e ICMS 0,00, sem linhas de
   componente): a Whirlpool mandou antes de calcular. Não é divergência de
   valor, é arquivo sem valor — e é assim que sai (`sem_valor=True`).
"""
from __future__ import annotations

import io
import re

# versão do LEITOR: sobe quando a leitura muda, e o cache em disco
# (`validacao.py`) relê tudo o que foi lido por uma versão anterior
VERSAO = 1

_N = r"-?[\d.,]+"
_CNPJ = r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"


def texto_pdf(conteudo: bytes) -> list[str]:
    """O texto de cada página. Import tardio: quem só valida não paga o pypdf."""
    import pypdf
    leitor = pypdf.PdfReader(io.BytesIO(conteudo))
    return [(p.extract_text() or "").replace("\r", "") for p in leitor.pages]


def _so_digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def sotaque(texto: str) -> str:
    """'br' ou 'us', decidido pelos valores em dinheiro do documento."""
    br = us = 0
    for m in re.finditer(r"R\$\s+(" + _N + r")|a Pagar\s+(" + _N + r")", texto):
        v = m.group(1) or m.group(2)
        if re.search(r",\d{2}$", v):
            br += 1
        elif re.search(r"\.\d{2}$", v):
            us += 1
    return "br" if br > us else "us"


def numero(s: str | None, sot: str) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if not re.fullmatch(_N, s):
        return None
    if sot == "br":
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def formato(paginas: list[str]) -> str:
    t = "\n".join(paginas)
    if re.search(r"Pr.-C.lculo Inbound P.gina:", t):
        return "precalculo"
    if "Ordem de Coleta:" in t:
        return "ordem_coleta"
    return "desconhecido"


# ----------------------------------------------------------------------------
# Pré-Cálculo Inbound
# ----------------------------------------------------------------------------
_LINHA_FORN = re.compile(
    r"^(?P<nome>.+?) (?P<cnpj>" + _CNPJ + r")\s+(?P<vlnf>" + _N + r")\s+(?P<frete>"
    + _N + r")\s+(?P<peso>" + _N + r")\s+(?P<vol>" + _N + r")\s*$", re.M)

_COMPONENTES = {
    "frete": r"^Valor do Frete R\$\s+(" + _N + r")",
    "taxa_coleta": r"^Taxa de Coleta/Entrega R\$\s+(" + _N + r")",
    "pedagio": r"^Ped.gio R\$\s+(" + _N + r")",
    "frete_liquido": r"^Frete Liquido R\$\s+(" + _N + r")",
    "base_icms": r"^Base Imp Despesa R\$\s+(" + _N + r")",
    "icms": r"^Valor do ICMS R\$\s+(" + _N + r")",
    "total_pagar": r"^Valor L.quido a Pagar\s+(" + _N + r")",
}


def _parte(texto: str, papel: str) -> dict | None:
    m = re.search(r"^" + papel + r": (?P<cod>\S+) (?P<nome>.+?) I\.Estadual:.*\n"
                  r"CNPJ: (?P<cnpj>" + _CNPJ + r")", texto, re.M)
    if not m:
        return None
    return {"codigo": m.group("cod"), "nome": m.group("nome").strip(),
            "cnpj": _so_digitos(m.group("cnpj"))}


def _pagina_precalculo(texto: str, sot: str) -> dict:
    p: dict = {"fornecedor": None, "cnpj": None}
    m = _LINHA_FORN.search(texto)
    if m:
        p["fornecedor"] = m.group("nome").strip()
        p["cnpj"] = _so_digitos(m.group("cnpj"))
        p["valor_nf"] = numero(m.group("vlnf"), sot)
        p["peso"] = numero(m.group("peso"), sot)
        p["volume"] = numero(m.group("vol"), sot)
    for chave, rx in _COMPONENTES.items():
        mm = re.search(rx, texto, re.M)
        p[chave] = numero(mm.group(1), sot) if mm else None
    p["coleta"] = _parte(texto, "Coleta")
    p["contratante"] = _parte(texto, "Contratante")
    p["entrega"] = _parte(texto, "Entrega")
    mm = re.search(r"P.gina: (\d+) de (\d+)", texto)
    p["pagina"] = int(mm.group(1)) if mm else None
    return p


def ler_precalculo(paginas: list[str]) -> dict:
    t = "\n".join(paginas)
    sot = sotaque(t)

    def achar(rx: str) -> str | None:
        m = re.search(rx, t, re.M)
        return m.group(1).strip() if m else None

    fornecedores = [_pagina_precalculo(pg, sot) for pg in paginas]
    fornecedores = [f for f in fornecedores if f["cnpj"]]
    transp = re.search(r"^Transportadora: (\d+) (.+?) Identificador: ?(\S*)\s*\nCNPJ: ("
                       + _CNPJ + ")", t, re.M)
    calc = re.search(r"Tipo C.lculo: (.+?)\s{2,}Tipo Viagem: (.+)$", t, re.M)
    doc = {
        "formato": "precalculo",
        "sotaque": sot,
        "transporte": achar(r"Transporte Planejado: (\d+)"),
        "precalculo": achar(r"Pr.-C.lculo: (\d+)"),
        "data_calculo": achar(r"Data-C.lculo: (\S+ \S+)"),
        "data": achar(r"^Data: (\d{2}/\d{2}/\d{4})"),
        "tipo_calculo": calc.group(1).strip() if calc else None,
        "tipo_viagem": calc.group(2).strip() if calc else None,
        "rota": achar(r"^Rota: (.+?) Meio de Transporte:"),
        "veiculo": achar(r"Meio de Transporte: (.+)$"),
        "icms_pct": numero(achar(r"% ICMS:\s+(" + _N + ")"), sot),
        "valor_tabela": numero(achar(r"Valor Tabela Frete:\s+(" + _N + ")"), sot),
        "transportadora_cnpj": _so_digitos(transp.group(4)) if transp else None,
        "placa": (transp.group(3) or None) if transp else None,
        "total_frete_liquido": numero(achar(r"^Valor Total do Frete Liqu.do\s+(" + _N + ")"), sot),
        "total_pagar": numero(achar(r"^Valor Total do Liqu.do a Pagar\s+(" + _N + ")"), sot),
        "total_peso": numero(achar(r"^Peso Total da Nota Fiscal\s+(" + _N + ")"), sot),
        "fornecedores": fornecedores,
    }
    doc["sem_valor"] = bool(fornecedores) and all(
        not (f.get("total_pagar") or 0) for f in fornecedores)
    return doc


# ----------------------------------------------------------------------------
# Ordem de Coleta
# ----------------------------------------------------------------------------
# a linha da parada é de largura fixa: nome e endereço saem truncados e colados
# ("Paranapanema S.A. (Fábrica Ut Rua Felipe…"), então o nome guarda o trecho
# inteiro e a conferência NÃO se apoia nele — só no peso
_LINHA_COLETA = re.compile(
    r"^\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}\s+(?:\d+\s+)?(?P<cod>\d{5,})\s+(?P<nome>.+?)\s+"
    r"(?P<peso>" + _N + r")\s+(?P<vol>" + _N + r")\s*$", re.M)
_LINHA_ENTREGA = re.compile(
    r"^(?:\d{2}/\d{2}/\d{4} )?\d{1,2}:\d{2}\s+\d{1,2}:\d{2}\s+(?:\d+\s+)?(?P<cod>\d{4,})\s+"
    r"(?P<nome>.+?)\s+(?P<peso>" + _N + r")_*\s*$", re.M)


def ler_ordem_coleta(paginas: list[str]) -> dict:
    t = "\n".join(paginas)
    # sem campo de dinheiro, o sotaque sai do peso: três casas depois do
    # último separador, como o próprio documento imprime
    pesos = re.findall(r"^Total:\s+(" + _N + ")", t, re.M)
    sot = "br" if pesos and re.search(r",\d{3}$", pesos[0]) else "us"
    coleta, entrega = t, ""
    if "Entregas (Inbound)" in t:
        coleta, entrega = t.split("Entregas (Inbound)", 1)
    tot_col = re.search(r"^Total:\s+(" + _N + r")(?:\s+(" + _N + r"))?\s*$", coleta, re.M)
    tot_ent = re.search(r"^Total:\s+(" + _N + r")\s*$", entrega, re.M)
    paradas = []
    for bloco, papel, rx in ((coleta, "coleta", _LINHA_COLETA), (entrega, "entrega", _LINHA_ENTREGA)):
        for m in rx.finditer(bloco):
            paradas.append({"papel": papel, "codigo": m.group("cod"),
                            "nome": re.sub(r"\s+", " ", m.group("nome")).strip(),
                            "peso": numero(m.group("peso"), sot)})
    itin = re.search(r"Itiner.rio: (.+?)\s{2,}Tipo de Ve.culo: (.+?)\s*$", t, re.M)
    placa = re.search(r"Placa do Ve.culo: (\S+)", t)
    viagem = re.search(r"Viagem: (\S+)", t)
    transp = re.search(r"Transporte: (\d+)", t)
    return {
        "formato": "ordem_coleta",
        "sotaque": sot,
        "transporte": transp.group(1) if transp else None,
        "peso_coleta": numero(tot_col.group(1), sot) if tot_col else None,
        "volume_coleta": numero(tot_col.group(2), sot) if tot_col and tot_col.group(2) else None,
        "peso_entrega": numero(tot_ent.group(1), sot) if tot_ent else None,
        "itinerario": itin.group(1).strip() if itin else None,
        "veiculo": itin.group(2).strip() if itin else None,
        "placa": placa.group(1) if placa else None,
        "tipo_viagem": viagem.group(1) if viagem else None,
        "paradas": paradas,
    }


def ler(conteudo: bytes, extensao: str | None = None) -> dict:
    """Um anexo → o documento lido, ou `formato="desconhecido"` com o motivo."""
    if (extensao or "").lower() != "pdf":
        return {"formato": "desconhecido", "motivo": "não é PDF", "versao": VERSAO}
    try:
        paginas = texto_pdf(conteudo)
    except Exception as exc:  # noqa: BLE001 — PDF corrompido não derruba a tela
        return {"formato": "desconhecido", "motivo": f"PDF ilegível ({type(exc).__name__})",
                "versao": VERSAO}
    return ler_paginas(paginas)


def ler_paginas(paginas: list[str]) -> dict:
    f = formato(paginas)
    if f == "precalculo":
        doc = ler_precalculo(paginas)
    elif f == "ordem_coleta":
        doc = ler_ordem_coleta(paginas)
    else:
        t = "\n".join(paginas)
        motivo = ("requisição de transporte expresso" if "transporte expresso" in t.lower()
                  else "formato não reconhecido")
        doc = {"formato": "desconhecido", "motivo": motivo}
    doc["versao"] = VERSAO
    return doc
