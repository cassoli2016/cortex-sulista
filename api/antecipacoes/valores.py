"""Conversão de célula de planilha para valor tipado.

Isolado num módulo próprio porque é aqui que o arquivo do portal engana. No
primeiro arquivo recebido (PORTAL MAXION 24.08.2026.xls), a MESMA planilha
traz:

- `Nominal` como número (2060.23) e `Saldo` como texto pt-BR ("2.060,23");
- `Vencimento` como data de Excel (serial 46267) e `Emissão` como texto
  "05/06/2026";
- `Nota Fiscal` como número de ponto flutuante (100226.0), que exibido cru
  vira "100226.0" e não casa com o número da nota no ERP.

Cada portal vai errar de um jeito diferente. As funções abaixo aceitam as
várias formas e devolvem sempre o mesmo tipo, para o modelo do portal só
dizer QUAL coluna é o quê.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# `1.234,56` (pt-BR) e `1,234.56` (en-US) são ambíguos olhando só o separador.
# A regra: o ÚLTIMO separador é o decimal quando sobram 1 ou 2 dígitos depois
# dele. Ponto em grupos de exatamente 3 dígitos é milhar — mesma decisão do
# numBR() do painel, e pelo mesmo motivo (1.234 é mil duzentos e trinta e
# quatro, não um vírgula dois).
_RE_NUM = re.compile(r"^-?[\d.,\s]+$")


def texto(v) -> str:
    """Célula como texto limpo. Número inteiro NÃO vira '100226.0'.

    O float do Excel é a origem do problema: a nota fiscal 100226 chega como
    100226.0 e, concatenada num identificador, nunca casaria com o ERP.
    """
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (date, datetime)):
        return v.strftime("%d/%m/%Y")
    return " ".join(str(v).split())


def numero(v) -> float | None:
    """Valor monetário vindo como float, int ou texto pt-BR/en-US."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().replace("\xa0", " ")
    if not s or not _RE_NUM.match(s):
        return None
    s = s.replace(" ", "")
    ponto, virgula = s.rfind("."), s.rfind(",")
    if ponto >= 0 and virgula >= 0:
        # o que vier por último é o decimal
        if virgula > ponto:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif virgula >= 0:
        # sozinha: decimal se sobram 1-2 dígitos ("2060,23"), senão milhar
        s = s.replace(",", "." if len(s) - virgula - 1 <= 2 else "")
    elif ponto >= 0:
        # ponto sozinho em grupo de 3 é milhar ("1.234"); senão é decimal
        if len(s) - ponto - 1 == 3 and s.count(".") >= 1 and len(s.split(".")[0]) <= 3:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# Excel conta os dias a partir de 1899-12-30 (o "bug" do ano bissexto de 1900
# está embutido no formato e é o que faz a base ser 30/12 e não 31/12).
_EPOCA = date(1899, 12, 30)
_FORMATOS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def data(v) -> date | None:
    """Data vinda como date, datetime, serial do Excel ou texto dd/mm/aaaa."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # Serial plausível: 1990-01-01 (32874) a 2100-01-01 (73051). Fora
        # disso é outro número que caiu na coluna errada — devolver uma data
        # de 1902 seria pior que devolver nada.
        n = int(v)
        if 32874 <= n <= 73051:
            from datetime import timedelta
            return _EPOCA + timedelta(days=n)
        return None
    s = str(v).strip()
    if not s:
        return None
    for f in _FORMATOS:
        try:
            return datetime.strptime(s[:10], f).date()
        except ValueError:
            continue
    return None


_SIM = {"sim", "s", "true", "1", "yes", "y", "x"}
_NAO = {"nao", "não", "n", "false", "0", "no"}


def booleano(v) -> bool | None:
    """'Sim'/'Não' do portal. None quando a célula não diz nem um nem outro —
    tratar ausência como False marcaria título antecipável como recusado."""
    if isinstance(v, bool):
        return v
    s = texto(v).strip().lower()
    if s in _SIM:
        return True
    if s in _NAO:
        return False
    return None


_RE_NAO_DIGITO = re.compile(r"\D")


def cnpj(v) -> str:
    """Só os dígitos. O portal manda formatado ('76.104.397/0020-96') e o ERP
    guarda sem máscara — comparar sem normalizar nunca casaria."""
    return _RE_NAO_DIGITO.sub("", texto(v))


def cnpj_formatado(d: str) -> str:
    d = _RE_NAO_DIGITO.sub("", d or "")
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d
