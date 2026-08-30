"""Classificação dos tipos de ocorrência de motorista para a premiação.

O ERP tem 41 tipos e 563 ocorrências em 2026, e o mais frequente NÃO É
DEMÉRITO: "pontos de contratação novo agregado" são 187 (33%), com 182
motoristas distintos — é registro de entrada. Uma contagem ingênua penalizaria
todo agregado por ter sido contratado.

O QUE ESTE MÓDULO NÃO FAZ: decidir. A classe de cada tipo é decisão da
operação, porque ela define quem ganha e quem perde dinheiro. O que ele faz é
**propor** o óbvio e **expor** o resto:

- multa, colisão, acidente, atraso, recusa → demérito (com grupo)
- mérito e elogio → mérito
- pontos de contratação e retorno de férias → neutro
- o resto nasce `nao_classificado` e APARECE na tela pedindo decisão

`nao_classificado` não é o mesmo que `neutro`, e a diferença é o ponto: o ERP
ganha tipo novo sem avisar, e um tipo novo entrando como neutro sumiria da
tela — a premiação seguiria ignorando algo que talvez devesse contar.
"""
from __future__ import annotations

from datetime import datetime

from .. import db, pglocal

ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


# ── proposta de classificação, por palavra no nome do tipo ───────────────────
#
# A ordem IMPORTA: "multa de trânsito (infração grave)" casa em `multa` antes
# de casar em qualquer outra coisa. Regra mais específica primeiro.
#
# O peso é PROPOSTA e sai da gravidade que o próprio nome carrega — a operação
# ajusta na tela. Onde o nome não diz a gravidade, o peso fica 1 e a decisão
# fica visível em vez de escondida num número inventado.
_REGRAS: list[tuple[str, str, str, float, int]] = [
    # (trecho no nome, classe, grupo, peso, bloqueia)
    ("MULTA DE TRANSITO (INFRACAO GRAVISSIMA)", "demerito", "multa", 8, 0),
    ("MULTA DE TRANSITO (INFRACAO GRAVE)", "demerito", "multa", 5, 0),
    ("MULTA DE TRANSITO (INFRACAO MEDIA)", "demerito", "multa", 3, 0),
    ("MULTA DE TRANSITO (INFRACAO LEVE)", "demerito", "multa", 1, 0),
    ("MULTA", "demerito", "multa", 3, 0),

    ("ACIDENTE DE TRANSITO", "demerito", "sinistro", 8, 0),
    ("QUASE ACIDENTE", "demerito", "sinistro", 2, 0),
    ("COLISAO", "demerito", "sinistro", 5, 0),

    ("MERITO", "merito", "reconhecimento", 3, 0),
    ("ELOGIO", "merito", "reconhecimento", 3, 0),

    # registro de cadastro, não conduta — 33% das linhas de 2026
    ("PONTOS DE CONTRATACAO", "neutro", "cadastro", 0, 0),
    ("RETORNO ANTECIPADO FERIAS", "neutro", "cadastro", 0, 0),

    ("ATRASO", "demerito", "prazo", 2, 0),
    ("ATRASAR", "demerito", "prazo", 2, 0),
    ("NAO PREVENIR ATRASO", "demerito", "prazo", 2, 0),
    ("NAO INFORMAR ATRASO", "demerito", "prazo", 2, 0),

    ("RECUSA", "demerito", "recusa", 3, 0),
    ("DEIXAR DE VIAJAR", "demerito", "recusa", 3, 0),
    ("DEIXOU DE REALIZAR COLETA", "demerito", "recusa", 3, 0),

    ("NAO ENVIAR MACROS", "demerito", "processo", 1, 0),
    ("NAO ENVIAR AS NOTAS", "demerito", "processo", 1, 0),
    ("SEM DOCUMENTOS OBRIGATORIOS", "demerito", "processo", 3, 0),

    ("RECLAMACAO DO CLIENTE", "demerito", "cliente", 3, 0),
    ("NAO RESPEITAR NORMAS DO CLIENTE", "demerito", "cliente", 3, 0),

    ("FALTA DE ZELO", "demerito", "ativo", 3, 0),
    ("QUEBRA DE CARRETA", "demerito", "ativo", 5, 0),
    ("EPIS", "demerito", "seguranca", 2, 0),
    ("QUEBRA DE PGR", "demerito", "seguranca", 5, 0),
    ("EXCESSO DE VELOCIDADE", "demerito", "conducao", 3, 0),
    ("ESTACIONAR EM LOCAL PROIBIDO", "demerito", "conducao", 2, 0),

    ("MAU COMPORTAMENTO", "demerito", "conduta", 4, 0),
    ("FALTA SEM JUSTIFICATIVA", "demerito", "conduta", 3, 0),

    # CNH vencida não é demérito de grau: o motorista não pode dirigir. É
    # bloqueio, e por isso vem marcado — mas quem confirma é a operação.
    ("DEIXAR VENCER A CNH", "demerito", "habilitacao", 5, 1),
]


def _sem_acento(t: str) -> str:
    """MÉRITO e MERITO têm de casar com a mesma regra.

    O ERP escreve com acento e as regras aqui estão sem; comparar cru fazia
    "MÉRITO POR AJUDAR À OPERAÇÃO" não casar com `MERITO` e cair em não
    classificado.
    """
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t or "")
                   if not unicodedata.combining(c))


def propor(descricao: str) -> tuple[str, str, float, int]:
    """(classe, grupo, peso, bloqueia) para um nome de ocorrência."""
    nome = " ".join(_sem_acento(descricao or "").upper().split())
    for trecho, classe, grupo, peso, bloq in _REGRAS:
        if trecho in nome:
            return classe, grupo, float(peso), bloq
    return "nao_classificado", "", 1.0, 0


# ── leitura do catálogo do ERP ───────────────────────────────────────────────
#
# O AVA é LATIN1 e uma das descrições tem uma aspa tipográfica UTF-8 (U+2019)
# que NÃO CONVERTE: a consulta quebrava com `UntranslatableCharacter` só ao
# listar tudo, passando com LIMIT 10.
#
# A PRIMEIRA VERSÃO DESTE FILTRO TIRAVA TODO NÃO-ASCII, e isso quebrou a
# classificação em silêncio: "MÉRITO" virou "MRITO" e "COLISÃO" virou
# "COLISO" — o acento sumia junto com a letra, e as regras que procuram
# MERITO/COLISAO deixavam de casar. Três tipos caíram em "não classificado"
# por causa disso, e nada acusou.
#
# O filtro certo é só o que está FORA do LATIN1 (acima de U+00FF): acento é
# representável e fica. A normalização para casar palavra acontece no Python,
# onde `unicodedata` faz isso direito.
_CATALOGO_SQL = """
SELECT m.ocorrenciamotorista AS codigo,
       regexp_replace(coalesce(max(o.descricao), ''), '[^ -ÿ]', '', 'g') AS descricao,
       count(*)::int AS ocorrencias,
       count(DISTINCT m.cnpjcpfcodigo)::int AS motoristas,
       max(m.dt)::date AS ultima
FROM cadastro_vinculo_motoristaocorrencia m
LEFT JOIN ocorrenciamotorista o ON o.codigo = m.ocorrenciamotorista
WHERE m.dt >= %(de)s::date
GROUP BY 1 ORDER BY 3 DESC
"""


def catalogo_do_erp(desde: str = "2025-01-01") -> list[dict]:
    """Os tipos que APARECERAM, com quanto cada um pesa no volume.

    Não é o cadastro inteiro de propósito: tipo que existe e nunca foi usado
    não precisa de decisão, e enche a tela de linha morta.
    """
    return [dict(r) for r in db.query(_CATALOGO_SQL, {"de": desde})]


def sincronizar(desde: str = "2025-01-01", autor: str = "",
                esquema: str | None = None) -> dict:
    """Traz o catálogo do ERP e propõe a classe dos tipos AINDA NÃO decididos.

    NUNCA sobrescreve decisão humana. Um tipo já classificado só tem a
    descrição atualizada — o que a operação decidiu vale mais que a proposta
    deste módulo, e reescrever isso a cada sincronização apagaria o trabalho
    de quem classificou.
    """
    tipos = catalogo_do_erp(desde)
    agora = datetime.now().isoformat(timespec="seconds")
    novos = atualizados = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        cur = cx.cursor()
        for t in tipos:
            cod = t["codigo"]
            if cod is None:
                continue
            classe, grupo, peso, bloq = propor(t["descricao"])
            r = cur.execute(
                "SELECT classe FROM prem_ocorrencia_classe WHERE codigo=%s",
                (cod,)).fetchone()
            if r is None:
                cur.execute(
                    """INSERT INTO prem_ocorrencia_classe
                       (codigo, descricao, classe, grupo, peso, bloqueia,
                        atualizado_em, atualizado_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (cod, t["descricao"], classe, grupo, peso, bloq,
                     agora, autor or "proposta automática"))
                novos += 1
            else:
                # só a descrição: a classe é de quem decidiu
                cur.execute(
                    "UPDATE prem_ocorrencia_classe SET descricao=%s WHERE codigo=%s",
                    (t["descricao"], cod))
                atualizados += 1
        cx.commit()
    return {"tipos": len(tipos), "novos": novos, "atualizados": atualizados}


def listar(esquema: str | None = None) -> list[dict]:
    """A tabela para a tela, com o volume de cada tipo ao lado.

    O VOLUME É O QUE ORDENA. Classificar 41 tipos é trabalho; começar pelos
    que respondem por 90% das ocorrências transforma isso em dez minutos.
    """
    linhas = [dict(r) for r in pglocal.query(
        """SELECT codigo, descricao, classe, grupo, peso, bloqueia,
                  atualizado_em, atualizado_por
             FROM prem_ocorrencia_classe ORDER BY codigo""",
        esquema=_esq(esquema))]
    try:
        vol = {t["codigo"]: t for t in catalogo_do_erp()}
    except Exception:  # noqa: BLE001 — sem o AVA a tela ainda abre
        vol = {}
    for l in linhas:
        v = vol.get(l["codigo"]) or {}
        l["ocorrencias"] = v.get("ocorrencias") or 0
        l["motoristas"] = v.get("motoristas") or 0
        l["ultima"] = (v["ultima"].isoformat()
                       if v.get("ultima") else None)
    linhas.sort(key=lambda x: (-x["ocorrencias"], x["descricao"]))
    return linhas


def salvar(codigo: int, classe: str, *, peso: float = 1.0, grupo: str = "",
           bloqueia: int = 0, autor: str = "",
           esquema: str | None = None) -> None:
    """Grava a decisão da operação sobre um tipo."""
    if classe not in ("demerito", "neutro", "merito", "nao_classificado"):
        raise ValueError("Classe inválida.")
    if peso < 0:
        raise ValueError("O peso não pode ser negativo.")
    pglocal.executar(
        """UPDATE prem_ocorrencia_classe
              SET classe=%s, peso=%s, grupo=%s, bloqueia=%s,
                  atualizado_em=%s, atualizado_por=%s
            WHERE codigo=%s""",
        (classe, peso, grupo, 1 if bloqueia else 0,
         datetime.now().isoformat(timespec="seconds"), autor, codigo),
        esquema=_esq(esquema))


def pendentes(esquema: str | None = None) -> int:
    """Quantos tipos ainda esperam decisão. Vai para a tela e para a Saúde:
    premiação calculada com tipo não classificado está incompleta, e isso não
    pode ser descoberto depois de pagar."""
    r = pglocal.um(
        "SELECT count(*)::int AS n FROM prem_ocorrencia_classe "
        "WHERE classe = 'nao_classificado'", esquema=_esq(esquema))
    return (r or {}).get("n") or 0
