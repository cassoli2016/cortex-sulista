"""Modelos de planilha de antecipação, um por portal.

Cada cliente grande tem seu portal de antecipação (risco sacado / forfait) e
cada portal exporta um layout diferente. O núcleo — abrir o arquivo, achar o
cabeçalho, converter tipos, reconciliar o total — é o mesmo para todos; o que
muda é o mapa de colunas.

Portal novo = uma entrada em `MODELOS`. Nenhuma alteração no leitor. É o mesmo
princípio dos conectores da Central de Integrações: o núcleo é estável e o
fornecedor entra como plugin.

A DETECÇÃO é por cabeçalho, não pelo nome do arquivo: "PORTAL MAXION
24.08.2026.xls" identifica hoje, mas o analista renomeia arquivo o tempo todo
e o mesmo portal pode exportar com outro nome. O cabeçalho é o que o sistema
que gerou o arquivo escreveu.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def normalizar(s: str) -> str:
    """Cabeçalho comparável: sem acento, sem pontuação, minúsculo.

    'Nro. Título' e 'NRO TITULO' têm de casar — o portal muda a grafia entre
    exportações e o modelo não pode quebrar por causa de um ponto.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in s).split()).lower()


@dataclass
class Modelo:
    """Mapa de colunas de um portal.

    `colunas` liga o campo canônico aos cabeçalhos aceitos (o primeiro que
    aparecer vence). `obrigatorias` são os campos sem os quais o arquivo não é
    deste modelo — é o que a detecção pontua.
    """
    nome: str
    rotulo: str
    colunas: dict[str, tuple[str, ...]]
    obrigatorias: tuple[str, ...] = ()
    # Colunas que existem no arquivo mas não viram campo canônico. Declaradas
    # para o leitor poder avisar "coluna nova no arquivo" — mudança silenciosa
    # de layout do portal é como o parser começa a mentir.
    ignorar: tuple[str, ...] = field(default_factory=tuple)

    def mapear(self, cabecalho: list[str]) -> dict[str, int]:
        """Campo canônico -> índice da coluna no arquivo."""
        norm = [normalizar(c) for c in cabecalho]
        mapa: dict[str, int] = {}
        for campo, aceitos in self.colunas.items():
            for a in aceitos:
                na = normalizar(a)
                if na in norm:
                    mapa[campo] = norm.index(na)
                    break
        return mapa

    def pontuar(self, cabecalho: list[str]) -> float:
        """0 a 1. Quantos campos ESPERADOS o cabeçalho tem.

        Exige todas as obrigatórias: sem elas o arquivo pode até ter colunas
        parecidas e ser outra coisa (um extrato, um relatório de títulos).
        """
        mapa = self.mapear(cabecalho)
        if any(o not in mapa for o in self.obrigatorias):
            return 0.0
        return len(mapa) / max(1, len(self.colunas))


MAXION = Modelo(
    nome="maxion",
    rotulo="Portal Iochpe Maxion",
    obrigatorias=("titulo", "vencimento", "valor_nominal", "cnpj_sacado"),
    colunas={
        "situacao": ("Situação", "Situacao", "Status"),
        "titulo": ("Nro. Título", "Nro Titulo", "Número do Título"),
        "documento": ("Nota Fiscal", "NF", "Documento"),
        "emissao": ("Emissão", "Data Emissão"),
        "vencimento": ("Vencimento", "Data Vencimento", "Vencto"),
        "valor_nominal": ("Nominal", "Valor Nominal", "Valor"),
        "valor_saldo": ("Saldo", "Valor Saldo", "Saldo Devedor"),
        "antecipavel": ("Antecipável", "Antecipavel"),
        "cnpj_cedente": ("CPF/CNPJ Favorecido", "CNPJ Favorecido"),
        "nome_cedente": ("Nome Favorecido", "Favorecido"),
        "cnpj_sacado": ("CPF/CNPJ Pagador", "CNPJ Pagador"),
        "nome_sacado": ("Nome Pagador", "Pagador", "Sacado"),
        "chave": ("Chave Identificador", "Chave"),
        "id_portal": ("Id Portal", "ID Portal", "Identificador"),
    },
)

# Registro. Portal novo entra AQUI e em lugar nenhum mais.
MODELOS: tuple[Modelo, ...] = (MAXION,)

# Campos que todo modelo precisa produzir para o resto do CÓRTEX funcionar.
# Um modelo novo que não mapeie algum destes é detectado no teste, não em
# produção com o arquivo do cliente na mão.
CANONICOS = ("titulo", "documento", "emissao", "vencimento", "valor_nominal",
             "valor_saldo", "antecipavel", "cnpj_cedente", "nome_cedente",
             "cnpj_sacado", "nome_sacado", "situacao", "chave", "id_portal")


def escolher(cabecalho: list[str]) -> tuple[Modelo | None, float]:
    """Modelo com maior pontuação. Empate resolve pela ordem do registro."""
    melhor, nota = None, 0.0
    for m in MODELOS:
        p = m.pontuar(cabecalho)
        if p > nota:
            melhor, nota = m, p
    return melhor, nota
