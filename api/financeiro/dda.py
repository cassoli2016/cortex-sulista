"""DDA — os boletos registrados contra o CNPJ da empresa, lidos do extrato do
banco e confrontados com o que o ERP já tem lançado.

O PROBLEMA QUE ELE RESOLVE
==========================

Medido nos 12 meses de vencimento fechados até ago/2026: no dia 1º do mês, o
ERP conhece 42-55% das contas a pagar que vencem NAQUELE mês; no dia 10,
65-77%; só perto do dia 30 chega a ~100%. Projetar caixa em cima do lançado é
projetar um mês barato demais, e o erro cresce com o horizonte — out/2026 tinha
R$ 3,18 mi lançados contra uma média de R$ 12,1 mi nos meses fechados.

O DDA é a metade que falta, vinda de fora do ERP: cada boleto que um
fornecedor registrou no sistema bancário contra o CNPJ da empresa, com nome,
CNPJ, valor e vencimento. Não é estimativa — é obrigação registrada.

Confrontado com `contaapagar` (09/09/2026, extrato de 03/09): dos 1.061 boletos
vivos, 540 casaram com um título lançado (R$ 4,03 mi), 172 tinham o mesmo credor
e vencimento com outro valor, 9 estavam prorrogados no banco — e **340 não
tinham título nenhum, R$ 2,10 mi**. É esse resto que dá PISO e NOME à projeção.

O QUE ESTE MÓDULO NÃO FAZ
-------------------------

Não decide pagar nada e não cria título no ERP. O DDA é leitura: ele diz o que
o banco sabe e o ERP ainda não. Quem lança é a pessoa, no ERP.

E ele não é integração automática — o extrato sai do portal do banco à mão e
sobe pela tela. Por isso a Saúde mede a IDADE da última carga (a pergunta é "o
retrato ainda vale?") e não trata ausência de carga como falha: instalação sem
DDA importado é instalação incompleta, não avaria (mesma regra da seção 7 do
CLAUDE.md).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta

from .. import migracoes, pglocal
from ..antecipacoes import valores as vl

log = logging.getLogger("cortex.dda")

# Manopla de redirecionamento para os testes (padrão da casa).
ESQUEMA: str | None = None

# Quanto o extrato pode envelhecer antes de a tela parar de tratá-lo como
# posição. Não é um limite técnico: é o intervalo em que a carteira de boletos
# muda o bastante para o retrato deixar de descrever o presente. Uma semana
# cobre o ciclo de pagamento semanal da tesouraria com folga.
IDADE_MAX_DIAS = 7

# Tolerância do casamento por valor. Um centavo é arredondamento do extrato;
# acima de R$ 1,00 já é outro título (ou o mesmo com juros, que é justamente o
# que a coluna `a_pagar` separa).
TOL_VALOR = 1.00
# Janela do casamento por data. O boleto registrado e o título lançado podem
# divergir em alguns dias quando alguém prorroga o vencimento no banco sem
# refazer o lançamento — é a "alteração/instrução por parte do beneficiário"
# que 898 das 1.061 linhas do primeiro extrato carregam na observação.
TOL_DIAS = 7
# Tolerância da SOMA DO DIA (nível 2). É por GRUPO e não por boleto: a fatura
# do fornecedor junta as parcelas de várias notas, cada uma arredondada no
# centavo, e a soma de 12 títulos contra 2 boletos chega a diferir em R$ 0,02
# (extrato de 09/09/2026). Um real cobre o arredondamento de dezenas de
# parcelas e fica abaixo de qualquer título de verdade que falte.
TOL_SOMA = 1.00


class ArquivoInvalido(Exception):
    """Erro que a TELA mostra. A mensagem tem de dizer o que fazer."""


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(esquema or ESQUEMA)


def _so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _moeda(v) -> float | None:
    """Valor do extrato: vem como "R$\xa01.234,56" — o cifrão e o espaço fino
    derrubam o `_RE_NUM` do leitor genérico, então saem antes."""
    if v is None:
        return None
    s = str(v).replace("R$", "").replace("\xa0", " ").strip()
    return vl.numero(s)


def impressao(dados: bytes) -> str:
    return hashlib.sha256(dados or b"").hexdigest()


# ---------------------------------------------------------------- leitura

# Os rótulos do extrato do portal, na ordem em que aparecem. Procurados pelo
# TEXTO e não pela posição: o portal já reordena coluna entre versões, e uma
# coluna a mais no começo deslocaria tudo em silêncio.
_COLUNAS = {
    "pagador": ("pagador", "pagador/agregado"),
    "beneficiario": ("beneficiario", "beneficiário"),
    "doc": ("cpf/cnpj", "cnpj", "cpf"),
    "vencimento": ("venc.", "vencimento", "venc"),
    "documento": ("n doc.", "nº doc.", "n° doc.", "no doc.", "numero do documento",
                  "n doc", "documento"),
    "valor": ("ate venc.", "até venc.", "ate venc", "até venc", "valor"),
    "a_pagar": ("a pagar", "valor a pagar"),
    "tipo": ("tipo de boleto", "tipo"),
    "banco": ("banco",),
    "observacao": ("observacoes", "observações", "observacao", "observação"),
    "barras": ("codigo de barras", "código de barras", "codigo barras",
               "linha digitavel", "linha digitável"),
}
# Sem estas, a linha não é um boleto que se possa projetar nem casar.
_OBRIGATORIAS = ("vencimento", "valor", "barras")

# "Data/Hora: 03/09/2026 às 17:32:10". A hora é opcional (o portal já exportou
# só a data), mas quando existe ela entra: um extrato da manhã e um da tarde do
# mesmo dia são retratos diferentes da carteira. O `\D{0,8}` cobre o " às " com
# ou sem acento e a vírgula que outras versões usam — sem `.` para o separador
# não engolir um segundo número da mesma célula.
_RE_DATAHORA = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\D{0,8}(\d{2}:\d{2}))?")


def _normal(s) -> str:
    """Rótulo sem acento, minúsculo — o extrato vem em cp1252 e a mesma coluna
    já apareceu como "Observações" e "Observacoes"."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).strip().lower()


def _celulas(dados: bytes, nome: str) -> list[list]:
    if nome.lower().endswith(".csv") or nome.lower().endswith(".txt"):
        import csv
        import io
        texto = dados.decode("utf-8", errors="replace")
        sep = ";" if texto.count(";") > texto.count(",") else ","
        return [list(r) for r in csv.reader(io.StringIO(texto), delimiter=sep)]
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - dependência declarada
        raise ArquivoInvalido("Suporte a .xlsx indisponível no servidor.") from None
    import io
    try:
        wb = openpyxl.load_workbook(io.BytesIO(dados), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ArquivoInvalido(
            "Não foi possível abrir a planilha. Confira se o arquivo é o Excel "
            "exportado pelo portal do banco e não está protegido por senha."
        ) from exc
    ws = wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _achar_cabecalho(linhas: list[list]) -> tuple[int, dict[str, int]]:
    """Linha do cabeçalho e o mapa coluna->índice.

    O extrato traz 10 linhas de preâmbulo (nome da empresa, conta, CNPJ, data
    da extração) antes da tabela. Procurar o cabeçalho pelo conteúdo, e não
    assumir a linha 10, é o que faz o leitor sobreviver a o portal acrescentar
    uma linha no topo — que é a mudança mais provável que ele vai sofrer.
    """
    melhor, melhor_i, melhor_mapa = 0, -1, {}
    for i, linha in enumerate(linhas[:30]):
        mapa: dict[str, int] = {}
        for j, cel in enumerate(linha):
            rot = _normal(cel)
            if not rot:
                continue
            for chave, aceitos in _COLUNAS.items():
                if chave in mapa:
                    continue
                if rot in aceitos or any(rot.startswith(a) for a in aceitos):
                    mapa[chave] = j
                    break
        if len(mapa) > melhor:
            melhor, melhor_i, melhor_mapa = len(mapa), i, mapa
    if melhor_i < 0 or any(c not in melhor_mapa for c in _OBRIGATORIAS):
        faltam = [c for c in _OBRIGATORIAS if c not in melhor_mapa]
        raise ArquivoInvalido(
            "A planilha não parece ser a consulta de boletos do DDA: não achei "
            + " nem ".join(f"a coluna de {c}" for c in faltam)
            + ". Exporte de novo pelo portal do banco, sem editar o arquivo.")
    return melhor_i, melhor_mapa


def _cabecalho_extrato(linhas: list[list], ate: int) -> dict:
    """CNPJ, conta e data/hora declarados no preâmbulo.

    Tudo opcional: o extrato é dado de terceiro e o preâmbulo já mudou de forma
    antes. O que ele adiciona é a IDADE do retrato — sem `extraido_em` a tela
    cai para a hora do upload, que é uma data verdadeira sobre a coisa errada.
    """
    cnpj = conta = None
    extraido = None
    for linha in linhas[:ate]:
        for cel in linha:
            t = _normal(cel)
            if not t:
                continue
            if cnpj is None and ("cpf/cnpj" in t or t.startswith("cnpj")):
                d = _so_digitos(str(cel).split(":")[-1])
                if len(d) in (11, 14):
                    cnpj = d
            if conta is None and "conta" in t and "/" in str(cel):
                conta = str(cel).split(":", 1)[-1].strip() or None
            if extraido is None and ("data/hora" in t or t.startswith("data:")):
                m = _RE_DATAHORA.search(str(cel))
                if m:
                    d = vl.data(m.group(1))
                    if d:
                        hm = m.group(2) or "00:00"
                        try:
                            extraido = datetime.combine(
                                d, datetime.strptime(hm, "%H:%M").time())
                        except ValueError:
                            extraido = datetime.combine(d, datetime.min.time())
    return {"pagador_cnpj": cnpj, "conta": conta, "extraido_em": extraido}


def ler(dados: bytes, nome: str = "dda.xlsx") -> dict:
    """Extrato -> boletos no modelo canônico. PURO: não toca o banco."""
    linhas = _celulas(dados, nome)
    if not linhas:
        raise ArquivoInvalido("A planilha está vazia.")
    i_cab, mapa = _achar_cabecalho(linhas)
    cab = _cabecalho_extrato(linhas, i_cab)

    def cel(linha, chave):
        j = mapa.get(chave)
        return linha[j] if j is not None and j < len(linha) else None

    boletos: list[dict] = []
    ignoradas = 0
    for linha in linhas[i_cab + 1:]:
        if not any(c not in (None, "") for c in linha):
            continue
        barras = _so_digitos(cel(linha, "barras"))
        venc = vl.data(cel(linha, "vencimento"))
        valor = _moeda(cel(linha, "valor"))
        a_pagar = _moeda(cel(linha, "a_pagar"))
        # Sem chave, sem vencimento ou sem valor a linha não projeta caixa nem
        # casa com o ERP. Conta como ignorada — nunca some calada: linha
        # descartada em silêncio é dinheiro que some do total.
        if not barras or venc is None or valor is None:
            ignoradas += 1
            continue
        # O código de barras tem 44 dígitos; a linha digitável, 47/48. Aceitar
        # as duas e guardar sempre a de 44 mantém a chave estável mesmo que o
        # portal troque de coluna entre versões.
        if len(barras) in (47, 48):
            barras = _barras_de_linha_digitavel(barras) or barras
        boletos.append({
            "barras": barras[:44],
            "beneficiario": vl.texto(cel(linha, "beneficiario")),
            "beneficiario_doc": _so_digitos(cel(linha, "doc"))[:14] or None,
            "vencimento": venc,
            "valor": round(valor, 2),
            "a_pagar": round(a_pagar, 2) if a_pagar is not None else None,
            "documento": vl.texto(cel(linha, "documento"))[:60] or None,
            "tipo": vl.texto(cel(linha, "tipo"))[:60] or None,
            "banco": _so_digitos(cel(linha, "banco"))[:3] or None,
            "observacao": vl.texto(cel(linha, "observacao"))[:200] or None,
        })

    # O MESMO boleto duas vezes no arquivo: o portal já exportou linha repetida
    # quando a consulta cruza duas contas. Somar as duas dobraria o valor; a
    # chave é única por construção, então a última vence e a repetição é dita.
    unicos: dict[str, dict] = {}
    repetidas = 0
    for b in boletos:
        if b["barras"] in unicos:
            repetidas += 1
        unicos[b["barras"]] = b
    return {
        **cab,
        "boletos": list(unicos.values()),
        "ignoradas": ignoradas,
        "repetidas": repetidas,
        "total": round(sum(b["valor"] for b in unicos.values()), 2),
    }


def _barras_de_linha_digitavel(ld: str) -> str | None:
    """Linha digitável (47) -> código de barras (44).

    Os dois descrevem o MESMO boleto com os mesmos dígitos em ordem diferente,
    e o portal exporta ora um ora outro. Sem a conversão, o mesmo boleto
    entraria com duas identidades e a carga seguinte marcaria uma delas como
    sumida — "R$ 6 mi de boletos foram pagos" no dia em que ninguém pagou nada.

    Só o boleto de cobrança (47 dígitos). Guia de arrecadação (48, começa com
    8) tem outro arranjo e volta None em vez de um palpite.
    """
    if len(ld) != 47 or ld.startswith("8"):
        return None
    banco, moeda = ld[0:3], ld[3]
    dv, fator, valor = ld[32], ld[33:37], ld[37:47]
    campo = ld[4:9] + ld[10:20] + ld[21:31]
    return banco + moeda + dv + fator + valor + campo


# --------------------------------------------------------------- gravação

def importar(dados: bytes, nome: str, usuario: str = "",
             completa: bool = True, esquema: str | None = None) -> dict:
    """Grava a carga e reconcilia a posição. Devolve o resumo para a tela.

    O FECHAMENTO É ANCORADO NO INÍCIO DA CARGA, e não em `now()` linha a linha:
    é o que garante que "vivo" signifique "veio nesta carga" mesmo que a
    gravação leve segundos. Com carimbo por linha, um boleto gravado depois do
    fechamento ficaria vivo e sumido ao mesmo tempo.
    """
    esq = esquema or ESQUEMA
    init_db(esq)
    lido = ler(dados, nome)
    imp = impressao(dados)

    with pglocal.get_conn(esq) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, importado_em, boletos, valor FROM dda_carga "
                    "WHERE impressao = %s", (imp,))
        ja = cur.fetchone()
        if ja:
            # Arquivo IDÊNTICO não cria carga nova nem refaz o fechamento:
            # reimportar é acidente comum (clicar duas vezes, não ter certeza
            # se pegou), e refazer marcaria como "visto agora" um retrato
            # velho, rejuvenescendo o dado sem que nada tenha chegado.
            return {"ja_existia": True, "carga_id": ja["id"],
                    "importado_em": ja["importado_em"].isoformat(),
                    "boletos": ja["boletos"], "valor": float(ja["valor"] or 0),
                    "novos": 0, "sumiram": 0,
                    "ignoradas": lido["ignoradas"], "repetidas": lido["repetidas"],
                    "extraido_em": (lido["extraido_em"].isoformat()
                                    if lido["extraido_em"] else None)}

        cur.execute("SELECT now() AS agora")
        agora = cur.fetchone()["agora"]
        cur.execute(
            "INSERT INTO dda_carga (impressao, arquivo, extraido_em, usuario,"
            " pagador_cnpj, conta, boletos, valor, completa)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (imp, nome[:200], lido["extraido_em"], usuario[:120],
             lido["pagador_cnpj"], lido["conta"], len(lido["boletos"]),
             lido["total"], completa))
        carga_id = cur.fetchone()["id"]

        novos = 0
        for b in lido["boletos"]:
            cur.execute(
                "INSERT INTO dda_boleto (barras, beneficiario, beneficiario_doc,"
                " vencimento, valor, a_pagar, documento, tipo, banco, observacao,"
                " primeiro_em, visto_em, sumiu_em, carga_id)"
                " VALUES (%(barras)s,%(ben)s,%(doc)s,%(venc)s,%(valor)s,%(apagar)s,"
                " %(documento)s,%(tipo)s,%(banco)s,%(obs)s,%(agora)s,%(agora)s,NULL,%(carga)s)"
                " ON CONFLICT (barras) DO UPDATE SET"
                "   beneficiario = EXCLUDED.beneficiario,"
                "   beneficiario_doc = EXCLUDED.beneficiario_doc,"
                "   vencimento = EXCLUDED.vencimento,"
                "   valor = EXCLUDED.valor, a_pagar = EXCLUDED.a_pagar,"
                "   documento = EXCLUDED.documento, tipo = EXCLUDED.tipo,"
                "   banco = EXCLUDED.banco, observacao = EXCLUDED.observacao,"
                "   visto_em = EXCLUDED.visto_em, sumiu_em = NULL,"
                "   carga_id = EXCLUDED.carga_id"
                " RETURNING (xmax = 0) AS inserido",
                {"barras": b["barras"], "ben": b["beneficiario"],
                 "doc": b["beneficiario_doc"], "venc": b["vencimento"],
                 "valor": b["valor"], "apagar": b["a_pagar"],
                 "documento": b["documento"], "tipo": b["tipo"],
                 "banco": b["banco"], "obs": b["observacao"],
                 "agora": agora, "carga": carga_id})
            if cur.fetchone()["inserido"]:
                novos += 1

        sumiram = 0
        if completa:
            # Fechamento: o que estava vivo e não veio nesta carga foi pago,
            # cancelado ou prorrogado para fora do filtro. `visto_em < agora`
            # é o que separa — os desta carga acabaram de receber `agora`.
            cur.execute("UPDATE dda_boleto SET sumiu_em = %s"
                        " WHERE sumiu_em IS NULL AND visto_em < %s", (agora, agora))
            sumiram = cur.rowcount
        conn.commit()

    return {"ja_existia": False, "carga_id": carga_id,
            "importado_em": agora.isoformat(),
            "extraido_em": (lido["extraido_em"].isoformat()
                            if lido["extraido_em"] else None),
            "boletos": len(lido["boletos"]), "valor": lido["total"],
            "novos": novos, "sumiram": sumiram,
            "ignoradas": lido["ignoradas"], "repetidas": lido["repetidas"],
            "pagador_cnpj": lido["pagador_cnpj"], "conta": lido["conta"]}


def posicao(esquema: str | None = None) -> list[dict]:
    """Os boletos vivos — a posição atual. Lista vazia é resposta legítima
    (ninguém importou ainda), nunca erro."""
    esq = esquema or ESQUEMA
    try:
        return [dict(r) for r in pglocal.query(
            "SELECT barras, beneficiario, beneficiario_doc, vencimento,"
            " valor::float8 AS valor, a_pagar::float8 AS a_pagar, documento,"
            " tipo, banco, observacao, visto_em"
            " FROM dda_boleto WHERE sumiu_em IS NULL ORDER BY vencimento, valor DESC",
            esquema=esq)]
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return []
        raise


def estado(esquema: str | None = None) -> dict:
    """Idade e tamanho do retrato — o que a Saúde e a tela mostram.

    `configurado=False` (nunca houve carga) NÃO é falha: é instalação
    incompleta, e vale `info` na Saúde, não alarme vermelho.
    """
    esq = esquema or ESQUEMA
    vazio = {"configurado": False, "boletos": 0, "valor": 0.0,
             "extraido_em": None, "importado_em": None, "idade_dias": None,
             "velho": False, "arquivo": None, "cargas": 0}
    try:
        linhas = pglocal.query(
            "SELECT id, arquivo, extraido_em, importado_em, boletos,"
            " valor::float8 AS valor FROM dda_carga"
            " ORDER BY importado_em DESC LIMIT 1", esquema=esq)
        total = pglocal.query("SELECT count(*)::int AS n FROM dda_carga", esquema=esq)
        vivos = pglocal.query(
            "SELECT count(*)::int AS n, coalesce(sum(valor),0)::float8 AS v"
            " FROM dda_boleto WHERE sumiu_em IS NULL", esquema=esq)
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return vazio
        raise
    if not linhas:
        return vazio
    c = linhas[0]
    # A idade é a do RETRATO (o carimbo do extrato), não a do upload: planilha
    # de duas semanas atrás importada hoje é dado de duas semanas atrás.
    ref = c["extraido_em"] or c["importado_em"]
    idade = None
    if ref:
        # DIAS DE CALENDÁRIO, não períodos de 24 h. Um extrato tirado às 17h de
        # terça e lido às 8h de quarta tem 15 horas — e `.days` diria ZERO,
        # "extrato de hoje", sobre um retrato do dia anterior. Para um cartão de
        # idade o número que a pessoa lê é o do calendário, e ele é o maior dos
        # dois: envelhecer cedo demais avisa antes, envelhecer tarde cala no dia
        # em que o dado deixou de valer.
        idade = (date.today() - ref.date()).days
    return {
        "configurado": True,
        "boletos": vivos[0]["n"], "valor": round(vivos[0]["v"], 2),
        "extraido_em": c["extraido_em"].isoformat() if c["extraido_em"] else None,
        "importado_em": c["importado_em"].isoformat() if c["importado_em"] else None,
        "idade_dias": idade,
        "velho": bool(idade is not None and idade > IDADE_MAX_DIAS),
        "arquivo": c["arquivo"], "cargas": total[0]["n"],
    }


# --------------------------------------------------------------- casamento

# Os títulos do ERP na janela do DDA. `valortitulo` (nominal) para casar com o
# valor do boleto; `valorpendente` para saber se ainda é caixa futuro.
ERP_TITULOS_SQL = """
SELECT a.cnpjcpfcodigo AS doc, a.dtvencimento::date AS venc,
       a.valortitulo::float8 AS valor, a.valorpendente::float8 AS pendente,
       a.dtpagamento::date AS pago, a.numerotitulo AS titulo,
       a.numeroparcela AS parcela,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), '') AS credor
FROM contaapagar a
LEFT JOIN cadastro c ON c.codigo = a.cnpjcpfcodigo
WHERE a.valortitulo > 0
  AND a.dtvencimento >= %(de)s::date AND a.dtvencimento <= %(ate)s::date
"""


def casar(boletos: list[dict], titulos: list[dict]) -> dict:
    """Confronta boleto do banco × título do ERP. PURO — recebe os dois lados.

    OS NÍVEIS, e a ordem importa porque cada título só pode ser consumido uma
    vez: um fornecedor com cinco boletos de R$ 350 no mesmo dia tem cinco
    títulos, e casar o mesmo cinco vezes esconderia quatro que faltam lançar.

    1. **CNPJ + vencimento + valor** — o casamento sem dúvida. Tenta o CNPJ
       completo e, em seguida, a RAIZ de 8 dígitos (ver o comentário no corpo:
       matriz × filial custou R$ 333 mil de falso "não lançado" no primeiro
       extrato real).
    2. **A SOMA DO DIA** — mesmo credor (raiz) e mesmo vencimento, a soma dos
       boletos que sobraram contra a soma dos títulos que sobraram, até
       `TOL_SOMA` no grupo. É o PARCELAMENTO: o ERP lança por nota, cada nota
       partida nas parcelas dela, e o fornecedor emite UM boleto por fatura e
       parcela juntando as parcelas de várias notas que vencem no mesmo dia.
       Medido no extrato de 09/09/2026: 75 dias de credor (117 boletos) fecham
       assim ao centavo — e caíam em "valor diferente", pareados com um título
       qualquer do dia.
    3. **CNPJ completo + valor**, vencimento a até 7 dias — prorrogação
       registrada no banco sem refazer o lançamento. 898 das 1.061 linhas do
       primeiro extrato trazem "sofreu alteração/instrução por parte do
       beneficiário". Depois dele a soma do dia roda DE NOVO: um boleto
       prorrogado no meio do dia impedia o resto de fechar.
    4. **DIVERGÊNCIA, por dia de credor** — há título no ERP naquele credor e
       dia, mas as somas não fecham. Não se pareia boleto com título: o que se
       reporta é o GRUPO (os boletos, os títulos e a diferença), que é o que
       dá para conferir.

    O que sobra é o que o ERP não tem. NÃO é "erro do financeiro": boleto pode
    ter chegado ontem. É a fila de lançamento, com nome e prazo.
    """
    from collections import defaultdict
    # DOIS ÍNDICES, e o segundo é a correção que este casamento precisou.
    #
    # O CNPJ COMPLETO NÃO BASTA: o fornecedor registra o boleto pela MATRIZ e o
    # ERP lança o título pela FILIAL que emitiu a nota (ou o contrário). Medido
    # no primeiro extrato real: a Raízen registra em 33453598/0001-23 e o ERP
    # tem 11 títulos de setembro em 33453598/0244-99, R$ 355 mil que a versão
    # anterior deste módulo declarou "sem título no ERP".
    #
    # É a mesma lição que a antecipação já tinha, espelhada para o outro lado
    # da conta — lá é o cliente que fatura por várias filiais, aqui é o
    # fornecedor. A comparação é pela RAIZ (8 dígitos), e o CNPJ completo vem
    # ANTES na ordem porque, quando ele casa, não há dúvida nenhuma.
    #
    # A raiz sozinha seria frouxa demais para casar por valor+data em janela
    # larga (dois postos do mesmo grupo, mesmo valor, dias próximos), então ela
    # só entra onde o vencimento é EXATO — que é o que a torna segura.
    por_doc_venc: dict[tuple, list[dict]] = defaultdict(list)
    por_raiz_venc: dict[tuple, list[dict]] = defaultdict(list)
    por_doc: dict[str, list[dict]] = defaultdict(list)
    for t in titulos:
        doc = _so_digitos(t.get("doc"))
        if not doc:
            continue
        item = {**t, "doc": doc, "usado": False}
        por_doc_venc[(doc, t["venc"])].append(item)
        por_raiz_venc[(doc[:8], t["venc"])].append(item)
        por_doc[doc].append(item)

    def _pegar(cands, prova) -> dict | None:
        for c in cands:
            if not c["usado"] and prova(c):
                c["usado"] = True
                return c
        return None

    def _soma(xs, campo="valor"):
        return round(sum(float(x.get(campo) or 0) for x in xs), 2)

    def _livres(chave) -> list[dict]:
        return [t for t in por_raiz_venc.get(chave, ()) if not t["usado"]]

    def _por_dia(bs) -> dict:
        g: dict[tuple, list[dict]] = defaultdict(list)
        for b in bs:
            g[(_so_digitos(b.get("beneficiario_doc"))[:8], b["vencimento"])].append(b)
        return g

    def _grupo(gb, ts) -> dict:
        """O dia de um credor, dos DOIS lados — é o que se confere."""
        sd, se = _soma(gb), _soma(ts)
        return {
            "credor": gb[0].get("beneficiario") or "",
            "erp_credor": ts[0].get("credor") or "" if ts else "",
            "beneficiario_doc": gb[0].get("beneficiario_doc"),
            "vencimento": gb[0]["vencimento"],
            "boletos": len(gb), "titulos": len(ts),
            "soma_dda": sd, "soma_erp": se, "diferenca": round(sd - se, 2),
            "itens_dda": [{"documento": b.get("documento"), "valor": float(b["valor"]),
                           "a_pagar": b.get("a_pagar"), "tipo": b.get("tipo")}
                          for b in sorted(gb, key=lambda x: -float(x["valor"]))],
            "itens_erp": [{"titulo": t.get("titulo"), "parcela": t.get("parcela"),
                           "valor": float(t["valor"]), "pendente": t.get("pendente"),
                           "pago": t.get("pago")}
                          for t in sorted(ts, key=lambda x: -float(x["valor"]))],
        }

    casados, agrupados, prorrogados, divergentes, faltantes = [], [], [], [], []
    grupos_soma, divergencias = [], []

    # 1 — sem dúvida: CNPJ (completo, depois raiz) + vencimento + valor
    resto = []
    for b in boletos:
        doc = _so_digitos(b.get("beneficiario_doc"))
        if doc:
            venc, valor = b["vencimento"], float(b["valor"])
            mesmo_valor = lambda c, v=valor: abs(c["valor"] - v) <= TOL_VALOR  # noqa: E731
            alvo = (_pegar(por_doc_venc.get((doc, venc), ()), mesmo_valor)
                    or _pegar(por_raiz_venc.get((doc[:8], venc), ()), mesmo_valor))
            if alvo:
                casados.append({**b, "erp_valor": alvo["valor"],
                                "erp_pendente": alvo["pendente"],
                                "erp_doc": alvo["doc"],
                                "nivel": "exato" if alvo["doc"] == doc else "raiz"})
                continue
        resto.append(b)
    # boleto sem CNPJ não casa por nome (quatro grafias no mesmo arquivo)
    faltantes.extend({**b, "nivel": "ausente"} for b in resto
                     if not _so_digitos(b.get("beneficiario_doc")))
    resto = [b for b in resto if _so_digitos(b.get("beneficiario_doc"))]

    def _pela_soma(bs) -> list[dict]:
        """2 — o dia do credor fecha pela SOMA: todos casam juntos."""
        sobra = []
        for chave, gb in _por_dia(bs).items():
            ts = _livres(chave)
            if ts and abs(_soma(gb) - _soma(ts)) <= TOL_SOMA:
                for t in ts:
                    t["usado"] = True
                g = _grupo(gb, ts)
                grupos_soma.append(g)
                agrupados.extend({**b, "nivel": "soma", "grupo_boletos": g["boletos"],
                                  "grupo_titulos": g["titulos"], "grupo_dda": g["soma_dda"],
                                  "grupo_erp": g["soma_erp"]} for b in gb)
            else:
                sobra.extend(gb)
        return sobra

    resto = _pela_soma(resto)

    # 3 — vencimento prorrogado no banco. Só pelo CNPJ COMPLETO: a raiz numa
    # janela de 7 dias casaria postos diferentes do mesmo grupo.
    sobra = []
    for b in resto:
        doc, venc, valor = _so_digitos(b["beneficiario_doc"]), b["vencimento"], float(b["valor"])
        alvo = _pegar(
            por_doc.get(doc, ()),
            lambda c, v=valor, d=venc: (abs(c["valor"] - v) <= TOL_VALOR
                                        and abs((c["venc"] - d).days) <= TOL_DIAS))
        if alvo:
            prorrogados.append({**b, "erp_venc": alvo["venc"].isoformat(),
                                "dias": (alvo["venc"] - venc).days,
                                "erp_pendente": alvo["pendente"],
                                "nivel": "data"})
            continue
        sobra.append(b)

    # 2 de novo: o prorrogado que estava no meio do dia impedia o resto de fechar
    sobra = _pela_soma(sobra)

    # 4 — divergência: há título no credor e dia, mas as somas não fecham
    for chave, gb in _por_dia(sobra).items():
        ts = _livres(chave)
        if not ts:
            faltantes.extend({**b, "nivel": "ausente"} for b in gb)
            continue
        for t in ts:
            t["usado"] = True
        g = _grupo(gb, ts)
        divergencias.append(g)
        divergentes.extend({**b, "nivel": "valor", "erp_valor": g["soma_erp"],
                            "erp_pendente": _soma(ts, "pendente"),
                            "diferenca": g["diferenca"], "grupo_boletos": g["boletos"],
                            "grupo_titulos": g["titulos"]} for b in gb)
    divergencias.sort(key=lambda g: -abs(g["diferenca"]))

    return {
        "casados": casados, "agrupados": agrupados, "divergentes": divergentes,
        "prorrogados": prorrogados, "faltantes": faltantes,
        "grupos_soma": grupos_soma, "divergencias": divergencias,
        "resumo": {
            "boletos": len(boletos), "valor": _soma(boletos),
            "casados": len(casados), "casados_valor": _soma(casados),
            "agrupados": len(agrupados), "agrupados_valor": _soma(agrupados),
            "grupos_soma": len(grupos_soma),
            "divergentes": len(divergentes), "divergentes_valor": _soma(divergentes),
            "divergencias": len(divergencias),
            "divergencias_banco_a_mais": round(sum(g["diferenca"] for g in divergencias
                                                   if g["diferenca"] > 0), 2),
            "divergencias_erp_a_mais": round(-sum(g["diferenca"] for g in divergencias
                                                  if g["diferenca"] < 0), 2),
            "prorrogados": len(prorrogados), "prorrogados_valor": _soma(prorrogados),
            "faltantes": len(faltantes), "faltantes_valor": _soma(faltantes),
        },
    }


def confronto(esquema: str | None = None) -> dict:
    """`casar` com os dois lados buscados: DDA local × `contaapagar` do ERP.

    Falha do ERP NÃO derruba isto — devolve o que o DDA sabe com
    `erp_indisponivel`, e quem lê decide. Zero faltante afirmaria "conferi e
    está tudo lançado", que ninguém conferiu (mesma regra da conciliação da
    SEFAZ).
    """
    boletos = posicao(esquema)
    if not boletos:
        return {"disponivel": False, "erp_indisponivel": False,
                "resumo": None, "faltantes": [], "estado": estado(esquema)}
    de = min(b["vencimento"] for b in boletos)
    ate = max(b["vencimento"] for b in boletos)
    try:
        from .. import db
        titulos = db.query(ERP_TITULOS_SQL,
                           {"de": (de - timedelta(days=TOL_DIAS)).isoformat(),
                            "ate": (ate + timedelta(days=TOL_DIAS)).isoformat()})
    except Exception as exc:  # noqa: BLE001
        log.warning("confronto do DDA sem o ERP: %s", type(exc).__name__)
        return {"disponivel": True, "erp_indisponivel": True,
                "resumo": None, "faltantes": [], "estado": estado(esquema)}
    r = casar(boletos, [dict(t) for t in titulos])
    r["disponivel"] = True
    r["erp_indisponivel"] = False
    r["estado"] = estado(esquema)
    return r


def faltantes_por_mes(conf: dict) -> dict[str, float]:
    """O que o banco tem e o ERP não, somado por mês de vencimento.

    É o piso MEDIDO do "a lançar" da projeção. Prorrogado, casado pela soma e
    divergente ficam de fora: já têm título no ERP, e somá-los contaria a mesma
    obrigação duas vezes no mesmo mês. A exceção é o EXCESSO de uma divergência
    em que o banco cobra MAIS que o ERP tem no dia: essa parte tem boleto e não
    tem título (a fatura trouxe uma nota que ninguém lançou, ou juros). O que o
    ERP tem a mais não sai do piso — o piso é só o que o banco sabe.
    """
    if not conf.get("disponivel") or conf.get("erp_indisponivel"):
        return {}
    acc: dict[str, float] = {}

    def _somar(v: date, valor: float) -> None:
        k = f"{v.year:04d}-{v.month:02d}"
        acc[k] = acc.get(k, 0.0) + valor

    for b in conf.get("faltantes", ()):
        _somar(b["vencimento"], float(b["valor"]))
    for g in conf.get("divergencias", ()):
        if g["diferenca"] > 0:
            _somar(g["vencimento"], float(g["diferenca"]))
    return {k: round(v, 2) for k, v in acc.items()}


# --------------------------------------------------------------- relatório

def _data_br(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def relatorio_xlsx(conf: dict) -> tuple[str, bytes]:
    """A planilha da conferência do DDA — as MESMAS listas que a tela mostra.

    Seis abas, na ordem em que se trabalha: o resumo; as DIVERGÊNCIAS (um dia
    de credor por linha, maior diferença primeiro); o DETALHE delas (cada
    boleto e cada título do grupo, para conferir item a item); os CASADOS PELA
    SOMA (a regra nova tem de poder ser auditada — heurística escondida vira
    verdade do sistema); os sem título no ERP; os prorrogados.

    O CNPJ sai MASCARADO, como em toda saída da casa: o cadastro do ERP mistura
    CNPJ e CPF na mesma coluna. O nome e o número do título bastam para achar
    no ERP.
    """
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from .. import queries

    mask = queries._mask_doc
    MOEDA = '"R$" #,##0.00'
    cab_fonte = Font(bold=True, color="FFFFFF")
    cab_fundo = PatternFill("solid", fgColor="942821")
    res = conf.get("resumo") or {}
    est = conf.get("estado") or {}
    wb = Workbook()

    def aba(titulo, colunas, linhas, moeda=(), datas=(), larguras=None):
        ws = wb.create_sheet(titulo)
        ws.append([c for c in colunas])
        for j in range(1, len(colunas) + 1):
            cel = ws.cell(row=1, column=j)
            cel.font, cel.fill = cab_fonte, cab_fundo
        for lin in linhas:
            ws.append(lin)
        for i in range(2, ws.max_row + 1):
            for j in moeda:
                ws.cell(row=i, column=j + 1).number_format = MOEDA
            for j in datas:
                ws.cell(row=i, column=j + 1).number_format = "dd/mm/yyyy"
        for j, w in enumerate(larguras or [], start=1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A2"
        return ws

    # 1 — resumo
    ws = wb.active
    ws.title = "Resumo"
    extr = est.get("extraido_em")
    ws.append(["Conferência do DDA × contas a pagar do ERP"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Extrato do banco de {extr[:10][8:10]}/{extr[5:7]}/{extr[:4]}"
               if extr else "Extrato do banco sem data declarada"])
    ws.append([])
    ws.append(["Situação", "Boletos", "Valor", "O que fazer"])
    for j in range(1, 5):
        c = ws.cell(row=ws.max_row, column=j)
        c.font, c.fill = cab_fonte, cab_fundo
    linhas_res = [
        ("Casados (mesmo valor e vencimento)", res.get("casados"), res.get("casados_valor"),
         "Nada."),
        ("Casados pela soma do dia", res.get("agrupados"), res.get("agrupados_valor"),
         "Nada: a fatura do fornecedor junta parcelas de várias notas do mesmo dia. "
         "Auditar na aba Casados pela soma."),
        ("Vencimento prorrogado no banco", res.get("prorrogados"), res.get("prorrogados_valor"),
         "Conferir a data do título no ERP."),
        ("Em divergência", res.get("divergentes"), res.get("divergentes_valor"),
         f"Conferir os {res.get('divergencias') or 0} dias de credor da aba Divergências."),
        ("Sem título no ERP", res.get("faltantes"), res.get("faltantes_valor"), "Lançar."),
    ]
    for lin in linhas_res:
        ws.append(list(lin))
        ws.cell(row=ws.max_row, column=3).number_format = MOEDA
    ws.append([])
    ws.append(["Divergências: o banco cobra a mais", None, res.get("divergencias_banco_a_mais")])
    ws.cell(row=ws.max_row, column=3).number_format = MOEDA
    ws.append(["Divergências: o ERP tem a mais", None, res.get("divergencias_erp_a_mais")])
    ws.cell(row=ws.max_row, column=3).number_format = MOEDA
    for col, w in zip("ABCD", (40, 10, 16, 90)):
        ws.column_dimensions[col].width = w

    def _docs(g):
        return ", ".join(str(i["documento"] or "—") for i in g["itens_dda"])

    def _tits(g):
        return ", ".join(str(i["titulo"] or "—") for i in g["itens_erp"])

    # 2 — divergências (um dia de credor por linha)
    divs = conf.get("divergencias") or []
    aba("Divergências",
        ["Credor", "CNPJ", "Vencimento", "Boletos", "Soma no banco", "Títulos",
         "Soma no ERP", "Diferença", "Leitura", "Documentos no banco", "Títulos no ERP"],
        [[g["credor"], mask(g["beneficiario_doc"]), g["vencimento"], g["boletos"],
          g["soma_dda"], g["titulos"], g["soma_erp"], g["diferenca"],
          "banco cobra a mais" if g["diferenca"] > 0 else "ERP tem a mais",
          _docs(g), _tits(g)] for g in divs],
        moeda=(4, 6, 7), datas=(2,), larguras=(34, 20, 12, 9, 15, 9, 15, 14, 20, 40, 40))

    # 3 — detalhe, item a item
    det = []
    for n, g in enumerate(divs, start=1):
        for i in g["itens_dda"]:
            det.append([n, g["credor"], g["vencimento"], "Banco", i["documento"] or "—",
                        None, i["valor"], None, None])
        for i in g["itens_erp"]:
            det.append([n, g["erp_credor"] or g["credor"], g["vencimento"], "ERP",
                        i["titulo"] or "—", i["parcela"], i["valor"], i["pendente"], i["pago"]])
    aba("Detalhe das divergências",
        ["Grupo", "Credor", "Vencimento", "Lado", "Documento / título", "Parcela",
         "Valor", "Em aberto no ERP", "Pago em"],
        det, moeda=(6, 7), datas=(2, 8), larguras=(7, 34, 12, 8, 22, 8, 14, 16, 12))

    # 4 — casados pela soma (auditoria da regra)
    aba("Casados pela soma",
        ["Credor", "CNPJ", "Vencimento", "Boletos", "Soma no banco", "Títulos",
         "Soma no ERP", "Diferença", "Documentos no banco", "Títulos no ERP"],
        [[g["credor"], mask(g["beneficiario_doc"]), g["vencimento"], g["boletos"],
          g["soma_dda"], g["titulos"], g["soma_erp"], g["diferenca"], _docs(g), _tits(g)]
         for g in sorted(conf.get("grupos_soma") or [],
                         key=lambda g: (g["vencimento"], g["credor"]))],
        moeda=(4, 6, 7), datas=(2,), larguras=(34, 20, 12, 9, 15, 9, 15, 12, 40, 40))

    # 5 — sem título no ERP
    aba("Sem título no ERP",
        ["Beneficiário", "CNPJ", "Vencimento", "Valor", "A pagar hoje", "Documento", "Tipo"],
        [[b.get("beneficiario"), mask(b.get("beneficiario_doc")), b["vencimento"],
          float(b["valor"]), b.get("a_pagar"), b.get("documento"), b.get("tipo")]
         for b in sorted(conf.get("faltantes") or [], key=lambda x: (x["vencimento"], -x["valor"]))],
        moeda=(3, 4), datas=(2,), larguras=(34, 20, 12, 14, 14, 18, 26))

    # 6 — prorrogados
    aba("Prorrogados",
        ["Beneficiário", "CNPJ", "Vencimento no banco", "Vencimento no ERP", "Dias", "Valor"],
        [[b.get("beneficiario"), mask(b.get("beneficiario_doc")), b["vencimento"],
          date.fromisoformat(b["erp_venc"]), b["dias"], float(b["valor"])]
         for b in conf.get("prorrogados") or []],
        moeda=(5,), datas=(2, 3), larguras=(34, 20, 16, 16, 8, 14))

    buf = io.BytesIO()
    wb.save(buf)
    carimbo = (extr[:10] if extr else date.today().isoformat())
    return f"DDA-conferencia-{carimbo}.xlsx", buf.getvalue()
