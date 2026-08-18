# ANTT Fase 2 — RNTRC (compliance dos contratados) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar quais transportadores contratados pela Sulista estão com o RNTRC fora de "ATIVO", quanto já se pagou a eles, e alertar disso na tela de Agregados.

**Architecture:** O AVA já guarda o RNTRC de cada transportador (`cadastro.numerorntrc`, cobertura de 100%). A base aberta da ANTT entra só para dizer a SITUAÇÃO de cada registro. O casamento é pelo número, não pelo documento — o que dispensa CNPJ, dispensa CPF e funciona igual para empresa e autônomo. Só as linhas dos transportadores contratados são guardadas, em SQLite local.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3 (PG 9.3 read-only), SQLite (WAL), pytest + Playwright, SPA vanilla em `api/static/index.html`.

**Spec:** `docs/superpowers/specs/2026-08-18-antt-design.md` (§5), com as premissas revistas pela validação de 18/08/2026 — ver Global Constraints.

## Global Constraints

- **Normalizar zeros à esquerda DOS DOIS LADOS.** O AVA guarda `07600540`; a ANTT publica `007600540`. Comparar sem normalizar gerou 20 falsos "não encontrados" em vez de 1 e quase dobrou o risco reportado. Em compliance, falso positivo é o pior defeito: acusa quem está em ordem.
- **Nenhum CPF sai do banco nem entra no SQLite.** O casamento é por número de registro; documento de pessoa física não é necessário em lugar nenhum deste módulo.
- **A base aberta só publica ATIVO e PENDENTE.** Registro baixado ou cancelado não aparece — "não encontrado" é estado a investigar, nunca "sem problema".
- **Sync vazia ou com erro nunca sobrescreve base boa** (regra herdada da Premiação, que já custou um mês de dados).
- **A tela mede 12 meses fixos** no KPI; o filtro de período vale só para o detalhe de viagens.
- **PG 9.3**: sem `FILTER (WHERE ...)`. Todo SQL passa em `sql.encode("latin-1")`.
- **Rodar**: `uv run pytest tests/antt/ -v`. Versão corrente 0.4.0 → esta entrega sobe para 0.5.0.

---

### Task 1: Armazenamento local da base RNTRC

**Files:**
- Create: `api/antt/armazenamento.py`
- Test: `tests/antt/test_armazenamento.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `DB_PATH: Path` — `data/antt.db`
  - `init_db(path: Path | None = None) -> None`
  - `gravar_lote(linhas: list[dict], competencia: str, path=None) -> int` — substitui a base inteira numa transação; devolve quantas gravou. Lote vazio levanta `BaseVazia` sem tocar no que está gravado.
  - `situacao(rntrc: str, path=None) -> dict | None`
  - `todas(path=None) -> dict[str, dict]` — indexado pelo rntrc normalizado
  - `ultima_sync(path=None) -> dict | None` — `{competencia, quando, linhas}`
  - `normalizar_rntrc(valor: str | None) -> str` — só dígitos, sem zeros à esquerda
  - `class BaseVazia(Exception)`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_armazenamento.py
"""Base local do RNTRC: normalização, substituição atômica e a guarda da sync vazia."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from api.antt import armazenamento as arm


@pytest.fixture
def base():
    p = Path(tempfile.mkdtemp()) / "antt.db"
    arm.init_db(p)
    return p


def _linha(rntrc, situacao="ATIVO", nome="TRANSP", categoria="ETC", uf="SP"):
    return {"rntrc": rntrc, "nome": nome, "situacao": situacao,
            "categoria": categoria, "uf": uf, "municipio": "SBC",
            "data_situacao": "01/07/2026"}


def test_normalizar_tira_zeros_a_esquerda_e_nao_digitos():
    assert arm.normalizar_rntrc("007600540") == "7600540"
    assert arm.normalizar_rntrc("07600540") == "7600540"
    assert arm.normalizar_rntrc(" 7.600.540 ") == "7600540"
    assert arm.normalizar_rntrc(None) == ""


def test_o_lado_do_ava_e_o_da_antt_viram_a_mesma_chave(base):
    """O defeito que este teste trava: o AVA guarda 8 dígitos e a ANTT 9. Sem
    normalizar os dois lados, 19 transportadores em ordem foram acusados de
    não existir na base."""
    arm.gravar_lote([_linha("007600540")], "2026-07", base)
    assert arm.situacao(arm.normalizar_rntrc("07600540"), base) is not None


def test_gravar_lote_substitui_a_base_inteira(base):
    arm.gravar_lote([_linha("111"), _linha("222")], "2026-06", base)
    arm.gravar_lote([_linha("333")], "2026-07", base)
    todas = arm.todas(base)
    assert set(todas) == {"333"}


def test_lote_vazio_nao_apaga_a_base_boa(base):
    """Regra herdada da Premiação: coleta vazia já apagou um mês de dados."""
    arm.gravar_lote([_linha("111")], "2026-06", base)
    with pytest.raises(arm.BaseVazia):
        arm.gravar_lote([], "2026-07", base)
    assert set(arm.todas(base)) == {"111"}
    assert arm.ultima_sync(base)["competencia"] == "2026-06"


def test_ultima_sync_registra_competencia_e_contagem(base):
    arm.gravar_lote([_linha("111"), _linha("222")], "2026-07", base)
    s = arm.ultima_sync(base)
    assert s["competencia"] == "2026-07"
    assert s["linhas"] == 2
    assert s["quando"]


def test_base_nunca_sincronizada_devolve_none(base):
    assert arm.ultima_sync(base) is None
    assert arm.todas(base) == {}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_armazenamento.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt.armazenamento'`

- [ ] **Step 3: Implementar**

Espelhe `api/previsao/armazenamento.py` (conexão curta, WAL, `with c:` para transação).

```python
# api/antt/armazenamento.py
"""Base local da situação do RNTRC — SQLite, como todo dado nosso.

Guarda SÓ os transportadores que a Sulista contrata (222 hoje), não a base
nacional: o casamento é por número de registro, então não há razão para trazer
1,1 milhão de linhas para dentro. Nenhum documento de pessoa é gravado aqui.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "antt.db"

_SO_DIGITOS = re.compile(r"\D")


class BaseVazia(Exception):
    """Sync que não trouxe nenhuma linha. Nunca sobrescreve o que está gravado."""


def normalizar_rntrc(valor: str | None) -> str:
    """Chave de casamento: só dígitos, sem zeros à esquerda.

    O AVA guarda 8 dígitos ('07600540') e a ANTT publica 9 ('007600540'). Os
    dois lados passam por aqui — normalizar só um deles cria falso 'não
    encontrado', que num módulo de compliance acusa quem está em ordem.
    """
    if not valor:
        return ""
    return _SO_DIGITOS.sub("", str(valor)).lstrip("0")


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path | None = None) -> None:
    with _conn(path or DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS rntrc_transportador(
            rntrc         TEXT PRIMARY KEY,
            nome          TEXT,
            situacao      TEXT NOT NULL,
            categoria     TEXT,
            uf            TEXT,
            municipio     TEXT,
            data_situacao TEXT
        );
        CREATE TABLE IF NOT EXISTS rntrc_sync(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            competencia TEXT NOT NULL,
            quando      TEXT NOT NULL,
            linhas      INTEGER NOT NULL
        );
        """)


def gravar_lote(linhas: list[dict], competencia: str,
                path: Path | None = None) -> int:
    if not linhas:
        raise BaseVazia(f"sync de {competencia} não trouxe nenhuma linha")
    p = path or DB_PATH
    init_db(p)
    with _conn(p) as c:
        c.execute("DELETE FROM rntrc_transportador")
        c.executemany(
            """INSERT OR REPLACE INTO rntrc_transportador
               (rntrc, nome, situacao, categoria, uf, municipio, data_situacao)
               VALUES(:rntrc, :nome, :situacao, :categoria, :uf, :municipio,
                      :data_situacao)""",
            [{**l, "rntrc": normalizar_rntrc(l["rntrc"])} for l in linhas])
        c.execute("INSERT INTO rntrc_sync(competencia, quando, linhas) "
                  "VALUES(?,?,?)",
                  (competencia, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   len(linhas)))
    return len(linhas)


def situacao(rntrc: str, path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute("SELECT * FROM rntrc_transportador WHERE rntrc=?",
                        (normalizar_rntrc(rntrc),)).fetchone()
    return dict(row) if row else None


def todas(path: Path | None = None) -> dict[str, dict]:
    p = path or DB_PATH
    if not Path(p).exists():
        return {}
    with _conn(p) as c:
        return {r["rntrc"]: dict(r)
                for r in c.execute("SELECT * FROM rntrc_transportador")}


def ultima_sync(path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute("SELECT competencia, quando, linhas FROM rntrc_sync "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_armazenamento.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Commit**

```bash
git add api/antt/armazenamento.py tests/antt/test_armazenamento.py
git commit -m "feat(antt): base local da situacao do RNTRC"
```

---

### Task 2: Ingestão do CSV aberto da ANTT

**Files:**
- Create: `api/antt/rntrc.py`
- Test: `tests/antt/test_rntrc_ingestao.py`

**Interfaces:**
- Consumes: `armazenamento.normalizar_rntrc`, `armazenamento.gravar_lote`.
- Produces:
  - `URL_PACOTE: str` — endpoint CKAN do dataset
  - `descobrir_recurso(timeout=60) -> tuple[str, str]` — `(url_csv, competencia)` do mês mais recente
  - `varrer(fonte, interessantes: set[str]) -> list[dict]` — lê linha a linha um iterável de texto e devolve só as que interessam
  - `sincronizar(interessantes: set[str], baixar=None) -> dict` — orquestra e grava; devolve `{competencia, lidas, gravadas}`
  - `class LayoutInesperado(Exception)`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_rntrc_ingestao.py
"""Varredura do CSV aberto: filtro, layout e normalização."""
from __future__ import annotations

import io

import pytest

from api.antt import rntrc

CABECALHO = ("nome_transportador;numero_rntrc;data_primeiro_cadastro;"
             "situacao_rntrc;cpfcnpjtransportador;categoria_transportador;"
             "cep;municipio;uf;equiparado;data_situacao_rntrc")

LINHAS = [
    '"TRANSPORTES ALFA";"007600540";"23/05/2017";"ATIVO";"11.193.322/0001-10";'
    '"ETC";"14095-290";"RIBEIRAO PRETO";"SP";"Sim";"23/10/2024"',
    '"JOAO DA SILVA";"006242260";"24/05/2005";"PENDENTE";"820.***.***-00";'
    '"TAC";"97000-000";"SAO SEPE";"RS";"Nao";"28/08/2025"',
    '"NAO INTERESSA LTDA";"000999999";"01/01/2020";"ATIVO";"00.000.000/0001-00";'
    '"ETC";"00000-000";"OUTRA";"MG";"Nao";"01/01/2020"',
]


def _fonte(linhas=None):
    return io.StringIO("\n".join([CABECALHO] + (linhas or LINHAS)))


def test_varre_e_devolve_so_os_interessantes():
    achadas = rntrc.varrer(_fonte(), {"7600540", "6242260"})
    assert {l["rntrc"] for l in achadas} == {"7600540", "6242260"}


def test_zero_a_esquerda_do_csv_casa_com_a_chave_normalizada():
    achadas = rntrc.varrer(_fonte(), {"7600540"})
    assert achadas and achadas[0]["rntrc"] == "7600540"


def test_traz_situacao_categoria_e_uf():
    achadas = rntrc.varrer(_fonte(), {"6242260"})
    l = achadas[0]
    assert l["situacao"] == "PENDENTE"
    assert l["categoria"] == "TAC"
    assert l["uf"] == "RS"
    assert l["nome"] == "JOAO DA SILVA"


def test_nunca_guarda_documento_de_pessoa():
    """CPF vem mascarado na origem e não tem uso aqui: o casamento é por
    registro. Documento não entra no banco local em hipótese nenhuma."""
    l = rntrc.varrer(_fonte(), {"6242260"})[0]
    assert not any("cpf" in k.lower() or "cnpj" in k.lower() for k in l)
    assert "820" not in repr(l)


def test_layout_diferente_do_esperado_aborta_com_mensagem():
    """Se a ANTT mudar as colunas, parar é melhor que gravar lixo por cima."""
    fonte = io.StringIO("coluna_a;coluna_b\n1;2")
    with pytest.raises(rntrc.LayoutInesperado):
        rntrc.varrer(fonte, {"7600540"})


def test_conjunto_vazio_de_interessantes_nao_varre_nada():
    assert rntrc.varrer(_fonte(), set()) == []


def test_sincronizar_grava_e_relata(tmp_path):
    from api.antt import armazenamento as arm
    base = tmp_path / "antt.db"
    arm.init_db(base)
    r = rntrc.sincronizar({"7600540", "6242260"},
                          baixar=lambda: (_fonte(), "2026-07"), path=base)
    assert r["gravadas"] == 2
    assert r["competencia"] == "2026-07"
    assert arm.situacao("7600540", base)["situacao"] == "ATIVO"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_rntrc_ingestao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'api.antt.rntrc'`

- [ ] **Step 3: Implementar**

```python
# api/antt/rntrc.py
"""Ingestão da base aberta do RNTRC (dados.antt.gov.br, CC-BY).

O arquivo mensal tem ~158 MB e 1,16 milhão de linhas. Ele é varrido em
streaming e 99,98% das linhas são descartadas na hora: só interessam os
transportadores que a Sulista contrata, identificados pelo número de registro
que o próprio AVA já guarda.

Nenhuma credencial é usada — a fonte é aberta.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

from api.antt.armazenamento import gravar_lote, normalizar_rntrc

URL_PACOTE = "https://dados.antt.gov.br/api/3/action/package_show?id=rntrc"

# colunas que o layout precisa ter para a varredura fazer sentido
_OBRIGATORIAS = {"nome_transportador", "numero_rntrc", "situacao_rntrc",
                 "categoria_transportador", "uf", "municipio",
                 "data_situacao_rntrc"}


class LayoutInesperado(Exception):
    """O CSV mudou de formato. Melhor parar do que gravar lixo por cima."""


def descobrir_recurso(timeout: int = 60) -> tuple[str, str]:
    """URL e competência do CSV mais recente publicado."""
    with urllib.request.urlopen(URL_PACOTE, timeout=timeout) as r:
        pacote = json.load(r)
    csvs = [x for x in pacote["result"]["resources"]
            if (x.get("format") or "").upper() == "CSV"]
    if not csvs:
        raise LayoutInesperado("o dataset do RNTRC não expõe nenhum CSV")
    recurso = csvs[-1]
    nome = recurso.get("name") or ""
    return recurso["url"], nome


def varrer(fonte, interessantes: set[str]) -> list[dict]:
    if not interessantes:
        return []
    leitor = csv.DictReader(fonte, delimiter=";")
    campos = set(leitor.fieldnames or [])
    if not _OBRIGATORIAS <= campos:
        raise LayoutInesperado(
            f"colunas ausentes no CSV do RNTRC: {sorted(_OBRIGATORIAS - campos)}")
    achadas = []
    for linha in leitor:
        num = normalizar_rntrc(linha.get("numero_rntrc"))
        if num not in interessantes:
            continue
        achadas.append({
            "rntrc": num,
            "nome": (linha.get("nome_transportador") or "").strip().strip('"'),
            "situacao": (linha.get("situacao_rntrc") or "").strip().strip('"').upper(),
            "categoria": (linha.get("categoria_transportador") or "").strip().strip('"'),
            "uf": (linha.get("uf") or "").strip().strip('"'),
            "municipio": (linha.get("municipio") or "").strip().strip('"'),
            "data_situacao": (linha.get("data_situacao_rntrc") or "").strip().strip('"'),
        })
    return achadas


def _baixar_padrao():
    url, competencia = descobrir_recurso()
    req = urllib.request.Request(url, headers={"User-Agent": "cortex-sulista"})
    resposta = urllib.request.urlopen(req, timeout=900)
    return io.TextIOWrapper(resposta, encoding="latin-1", newline=""), competencia


def sincronizar(interessantes: set[str], baixar=None,
                path: Path | None = None) -> dict:
    """Baixa, varre e grava. Devolve o que aconteceu, para a tela mostrar."""
    fonte, competencia = (baixar or _baixar_padrao)()
    achadas = varrer(fonte, interessantes)
    gravadas = gravar_lote(achadas, competencia, path)   # BaseVazia se vier 0
    return {"competencia": competencia, "gravadas": gravadas,
            "procurados": len(interessantes)}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_rntrc_ingestao.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 5: Provar contra o arquivo real**

Este passo não é opcional: a Fase 1 mostrou que layout suposto e layout real divergem.

```bash
uv run python -c "
from api.antt import rntrc
url, comp = rntrc.descobrir_recurso()
print('competencia:', comp)
print('url:', url[:90])
"
```

Expected: a competência do mês corrente e uma URL de `dados.antt.gov.br`. Se o nome do recurso não indicar mês/ano, ajuste `descobrir_recurso` para extrair a competência do nome do arquivo (`transportadores_rntrc_MM_AAAA.csv`) e refaça o teste.

- [ ] **Step 6: Commit**

```bash
git add api/antt/rntrc.py tests/antt/test_rntrc_ingestao.py
git commit -m "feat(antt): ingestao em streaming da base aberta do RNTRC"
```

---

### Task 3: Transportadores contratados, do AVA

**Files:**
- Modify: `api/antt/sql.py`
- Test: `tests/antt/test_sql_rntrc.py`

**Interfaces:**
- Consumes: nada.
- Produces: `RNTRC_TRANSPORTADORES_SQL: str` — parâmetros `%(dt_de)s`, `%(dt_ate)s`. Colunas: `codigo, rntrc, nome, pessoa, viagens, pago, ultima_viagem`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_sql_rntrc.py
"""Guardas do SQL dos transportadores contratados."""
from __future__ import annotations

from api.antt.sql import RNTRC_TRANSPORTADORES_SQL as S


def test_sem_recursos_ausentes_no_pg93():
    assert "FILTER (WHERE" not in S.upper()


def test_somente_latin1():
    S.encode("latin-1")


def test_le_o_rntrc_do_proprio_cadastro():
    """A cobertura é de 100% em produção; não há por que descobrir o registro
    na base aberta."""
    assert "numerorntrc" in S
    assert "cadastro" in S


def test_usa_a_fonte_canonica_do_frete_de_compra():
    assert "programacaoembarque" in S
    assert "v.utilizacaoveiculo IN ('AGR','TER')" in S
    assert "p.semaforo = 1" in S


def test_classifica_pessoa_sem_expor_documento():
    """Só o COMPRIMENTO do documento sai do banco, para distinguir empresa de
    autônomo. O documento em si não é selecionado."""
    assert "length(regexp_replace" in S
    assert "AS pessoa" in S


def test_traz_valor_e_contagem_para_dimensionar_o_risco():
    for campo in ("viagens", "pago", "ultima_viagem"):
        assert campo in S
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_sql_rntrc.py -v`
Expected: FAIL com `ImportError: cannot import name 'RNTRC_TRANSPORTADORES_SQL'`

- [ ] **Step 3: Implementar**

Acrescente ao fim de `api/antt/sql.py`:

```python
# ---------------------------------------------------------------- RNTRC

# Transportadores que receberam frete no periodo, com o RNTRC do proprio
# cadastro do AVA (cadastro.numerorntrc, cobertura de 100% da frota AGR/TER
# medida em 18/08/2026). O documento NAO e selecionado: so o comprimento, para
# separar empresa de autonomo na tela.
RNTRC_TRANSPORTADORES_SQL = """
SELECT p.cnpjcpfcodigoveiculo AS codigo,
       regexp_replace(coalesce(nullif(trim(c.numerorntrc),''),''),'[^0-9]','','g')
         AS rntrc,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''),
                '(sem cadastro)') AS nome,
       CASE WHEN length(regexp_replace(p.cnpjcpfcodigoveiculo,'[^0-9]','','g')) = 14
            THEN 'PJ' ELSE 'PF' END AS pessoa,
       count(*)::int AS viagens,
       coalesce(sum(p.valorfretecompra),0)::float8 AS pago,
       to_char(max(p.dtemissao),'YYYY-MM-DD') AS ultima_viagem
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
LEFT JOIN cadastro c ON c.codigo = p.cnpjcpfcodigoveiculo
WHERE p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
  AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.numero < 1000000
  AND p.cnpjcpfcodigoveiculo IS NOT NULL
GROUP BY 1,2,3,4
ORDER BY 6 DESC
"""
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_sql_rntrc.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Conferir contra o banco**

Com o túnel aberto:

```bash
uv run python -c "
import os
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api import db
from api.antt.sql import RNTRC_TRANSPORTADORES_SQL
with db.get_conn() as c, c.cursor() as cur:
    cur.execute(RNTRC_TRANSPORTADORES_SQL,
                {'dt_de':'2025-08-18','dt_ate':'2026-08-18'})
    linhas = cur.fetchall()
print('transportadores:', len(linhas))
print('sem rntrc:', sum(1 for l in linhas if not l['rntrc']))
"
```

Expected: ~222 transportadores e **0 sem rntrc**. Se aparecer algum sem registro, ele precisa de estado próprio na Task 4 — não pode virar "não encontrado", que significa outra coisa.

- [ ] **Step 6: Commit**

```bash
git add api/antt/sql.py tests/antt/test_sql_rntrc.py
git commit -m "feat(antt): SQL dos transportadores contratados com RNTRC do cadastro"
```

---

### Task 4: Serviço de conferência

**Files:**
- Create: `api/antt/rntrc_servico.py`
- Test: `tests/antt/test_rntrc_servico.py`

**Interfaces:**
- Consumes: `armazenamento.todas/ultima_sync/normalizar_rntrc`, `sql.RNTRC_TRANSPORTADORES_SQL`, `rntrc.sincronizar`.
- Produces:
  - `SITUACOES: tuple[str, ...]` = `("ativo", "pendente", "nao_encontrado", "sem_registro")`
  - `conferir(contratados: list[dict], base: dict[str, dict]) -> list[dict]`
  - `resumir(conferidos: list[dict]) -> dict`
  - `get_rntrc(dt_de: str, dt_ate: str) -> dict`
  - `atualizar_base(dt_de: str, dt_ate: str) -> dict` — descobre os RNTRCs contratados no período e sincroniza só eles

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_rntrc_servico.py
"""Conferência do RNTRC — pura, sem banco e sem rede."""
from __future__ import annotations

from api.antt.rntrc_servico import conferir, resumir


def _contratado(rntrc="7600540", nome="ALFA", pessoa="PJ", viagens=10,
                pago=100000.0):
    return {"codigo": "C1", "rntrc": rntrc, "nome": nome, "pessoa": pessoa,
            "viagens": viagens, "pago": pago, "ultima_viagem": "2026-08-01"}


def _base(**kw):
    padrao = {"7600540": {"rntrc": "7600540", "situacao": "ATIVO",
                          "categoria": "ETC", "uf": "SP", "nome": "ALFA",
                          "data_situacao": "01/07/2026"}}
    padrao.update(kw)
    return padrao


def test_registro_ativo_fica_regular():
    r = conferir([_contratado()], _base())[0]
    assert r["situacao"] == "ativo"
    assert r["risco"] is False


def test_registro_pendente_e_risco_com_valor_ao_lado():
    base = _base(**{"7600540": {"rntrc": "7600540", "situacao": "PENDENTE",
                                "categoria": "TAC", "uf": "RS", "nome": "X",
                                "data_situacao": "01/07/2026"}})
    r = conferir([_contratado(pago=1058578.0)], base)[0]
    assert r["situacao"] == "pendente"
    assert r["risco"] is True
    assert r["pago"] == 1058578.0


def test_zero_a_esquerda_no_cadastro_nao_vira_falso_alarme():
    """O defeito que custou 19 falsos positivos na validação."""
    r = conferir([_contratado(rntrc="07600540")], _base())[0]
    assert r["situacao"] == "ativo"


def test_ausente_da_base_nao_e_o_mesmo_que_sem_registro():
    """A base aberta só publica ATIVO e PENDENTE: quem não aparece pode estar
    baixado. É risco, mas de natureza diferente de quem nem tem registro no
    cadastro."""
    fora = conferir([_contratado(rntrc="9999999")], _base())[0]
    sem = conferir([_contratado(rntrc="")], _base())[0]
    assert fora["situacao"] == "nao_encontrado"
    assert sem["situacao"] == "sem_registro"
    assert fora["risco"] is True and sem["risco"] is True


def test_resumo_separa_regular_de_risco_e_soma_o_exposto():
    base = _base(**{"111": {"rntrc": "111", "situacao": "PENDENTE",
                            "categoria": "TAC", "uf": "SP", "nome": "B",
                            "data_situacao": "01/07/2026"}})
    conf = conferir([_contratado(pago=50000.0),
                     _contratado(rntrc="111", nome="B", pago=30000.0),
                     _contratado(rntrc="9999999", nome="C", pago=20000.0)], base)
    k = resumir(conf)
    assert k["transportadores"] == 3
    assert k["ativos"] == 1
    assert k["em_risco"] == 2
    assert k["pago_em_risco"] == 50000.0
    assert k["pago_total"] == 100000.0


def test_resumo_de_lista_vazia_nao_divide_por_zero():
    k = resumir([])
    assert k["transportadores"] == 0
    assert k["pct_risco"] is None


def test_base_nunca_sincronizada_nao_acusa_ninguem():
    """Sem base local, todo mundo pareceria irregular. A tela precisa dizer
    'base ausente', não 'todos irregulares'."""
    conf = conferir([_contratado()], {})
    assert conf[0]["situacao"] == "sem_base"
    assert conf[0]["risco"] is False
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_rntrc_servico.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```python
# api/antt/rntrc_servico.py
"""Confere os transportadores contratados contra a situação do RNTRC.

conferir e resumir são puros; só get_rntrc toca no AVA e só atualizar_base
toca na rede.
"""
from __future__ import annotations

from api import db
from api.antt import rntrc as ingestao
from api.antt.armazenamento import normalizar_rntrc, todas, ultima_sync
from api.antt.sql import RNTRC_TRANSPORTADORES_SQL

SITUACOES: tuple[str, ...] = ("ativo", "pendente", "nao_encontrado",
                              "sem_registro", "sem_base")


def conferir(contratados: list[dict], base: dict[str, dict]) -> list[dict]:
    saida = []
    for t in contratados:
        item = dict(t)
        chave = normalizar_rntrc(t.get("rntrc"))
        if not base:
            # Sem base local nada pode ser afirmado. Acusar todo mundo de
            # irregular por falta de sincronização seria pior que não medir.
            item.update(situacao="sem_base", risco=False, categoria=None,
                        uf=None, data_situacao=None)
        elif not chave:
            item.update(situacao="sem_registro", risco=True, categoria=None,
                        uf=None, data_situacao=None)
        else:
            achado = base.get(chave)
            if achado is None:
                item.update(situacao="nao_encontrado", risco=True,
                            categoria=None, uf=None, data_situacao=None)
            else:
                ativo = (achado.get("situacao") or "").upper() == "ATIVO"
                item.update(situacao="ativo" if ativo else "pendente",
                            risco=not ativo,
                            categoria=achado.get("categoria"),
                            uf=achado.get("uf"),
                            data_situacao=achado.get("data_situacao"))
        saida.append(item)
    return saida


def resumir(conferidos: list[dict]) -> dict:
    risco = [c for c in conferidos if c["risco"]]
    pago_total = sum(float(c.get("pago") or 0) for c in conferidos)
    pago_risco = sum(float(c.get("pago") or 0) for c in risco)
    return {
        "transportadores": len(conferidos),
        "ativos": sum(1 for c in conferidos if c["situacao"] == "ativo"),
        "pendentes": sum(1 for c in conferidos if c["situacao"] == "pendente"),
        "nao_encontrados": sum(1 for c in conferidos
                               if c["situacao"] == "nao_encontrado"),
        "sem_registro": sum(1 for c in conferidos
                            if c["situacao"] == "sem_registro"),
        "em_risco": len(risco),
        "viagens_em_risco": sum(int(c.get("viagens") or 0) for c in risco),
        "pago_total": pago_total,
        "pago_em_risco": pago_risco,
        "pct_risco": (pago_risco / pago_total) if pago_total else None,
    }


def get_rntrc(dt_de: str, dt_ate: str) -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(RNTRC_TRANSPORTADORES_SQL, {"dt_de": dt_de, "dt_ate": dt_ate})
        contratados = [dict(r) for r in cur.fetchall()]
    conferidos = conferir(contratados, todas())
    conferidos.sort(key=lambda c: (not c["risco"], -float(c.get("pago") or 0)))
    sync = ultima_sync()
    return {
        "kpis": resumir(conferidos),
        "transportadores": conferidos,
        "sync": sync,
        "dt_de": dt_de, "dt_ate": dt_ate,
        "fonte": ("ERP AVA · cadastro.numerorntrc × base aberta do RNTRC "
                  "(dados.antt.gov.br, CC-BY) · casamento pelo número de registro"),
    }


def atualizar_base(dt_de: str, dt_ate: str) -> dict:
    """Baixa a competência mais recente, guardando só quem a Sulista contrata."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(RNTRC_TRANSPORTADORES_SQL, {"dt_de": dt_de, "dt_ate": dt_ate})
        alvos = {normalizar_rntrc(r["rntrc"]) for r in cur.fetchall()}
    alvos.discard("")
    return ingestao.sincronizar(alvos)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/test_rntrc_servico.py -v`
Expected: PASS, 7 testes.

- [ ] **Step 5: Commit**

```bash
git add api/antt/rntrc_servico.py tests/antt/test_rntrc_servico.py
git commit -m "feat(antt): servico de conferencia do RNTRC"
```

---

### Task 5: Endpoints e RBAC

**Files:**
- Modify: `api/main.py` (dois endpoints, junto do bloco ANTT)
- Modify: `api/auth.py` (`TELAS`, `ROTA_TELAS`, seed v23)
- Test: `tests/antt/test_rntrc_endpoint.py`

**Interfaces:**
- Produces: `GET /api/operacao/antt/rntrc?dt_de=&dt_ate=` e `POST /api/operacao/antt/rntrc/atualizar`

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_rntrc_endpoint.py
"""Contrato dos endpoints e a permissão da tela."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from api import auth

PERFIS_COM_ACESSO = {"Controladoria", "Diretoria"}


def _base_semeada():
    tmp = Path(tempfile.mkdtemp()) / "auth.db"
    original = auth.DB_PATH
    try:
        auth.DB_PATH = tmp
        auth.init_db()
    finally:
        auth.DB_PATH = original
    c = sqlite3.connect(tmp)
    c.row_factory = sqlite3.Row
    return c


def test_tela_registrada():
    assert auth.TELAS["anrntrc"] == ("RNTRC dos Transportadores", "ANTT")


def test_rotas_mapeadas_para_a_tela():
    for rota in ("/api/operacao/antt/rntrc", "/api/operacao/antt/rntrc/atualizar"):
        achado = [t for p, t in auth.ROTA_TELAS if p == rota]
        assert achado and achado[0] == frozenset({"anrntrc"})


def test_rota_de_atualizar_vem_antes_da_rota_de_leitura():
    """Prefixo mais específico primeiro, senão a de leitura captura o POST."""
    pos = {p: i for i, (p, _) in enumerate(auth.ROTA_TELAS)}
    assert pos["/api/operacao/antt/rntrc/atualizar"] < pos["/api/operacao/antt/rntrc"]


def test_tela_e_restrita_como_a_do_piso():
    c = _base_semeada()
    perfis = {r["nome"] for r in c.execute("""
        SELECT p.nome FROM perfis p JOIN perfil_telas t ON t.perfil_id = p.id
        WHERE t.tela = 'anrntrc'""")}
    assert perfis == PERFIS_COM_ACESSO


def test_endpoints_existem_no_app():
    from api.main import app
    caminhos = {getattr(r, "path", None) for r in app.routes}
    assert "/api/operacao/antt/rntrc" in caminhos
    assert "/api/operacao/antt/rntrc/atualizar" in caminhos
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_rntrc_endpoint.py -v`
Expected: FAIL com `KeyError: 'anrntrc'`

- [ ] **Step 3: Registrar no RBAC**

Em `api/auth.py`, no dict `TELAS`, logo abaixo da linha de `anpiso`:

```python
    "anrntrc": ("RNTRC dos Transportadores", "ANTT"),
```

Em `ROTA_TELAS`, **a mais específica primeiro**, junto da rota do piso:

```python
    ("/api/operacao/antt/rntrc/atualizar", frozenset({"anrntrc"})),
    ("/api/operacao/antt/rntrc",           frozenset({"anrntrc"})),
```

Acrescente `"anrntrc"` às listas de Controladoria e Diretoria em `_PERFIS_MODELO`, e crie o seed incremental no fim de `_semear_perfis`, espelhando o bloco v22:

```python
    # v23 (RNTRC 2026-08-18): mesma restricao da v22. A tela nomeia
    # transportadores contratados com registro fora de ATIVO e o valor pago a
    # cada um -- informacao de compliance, nao operacional.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v23'").fetchone():
        for nome_perfil in ("Controladoria", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=?", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT OR IGNORE INTO perfil_telas(perfil_id, tela) VALUES(?,?)",
                          (row["id"], "anrntrc"))
        c.execute("INSERT OR IGNORE INTO config(chave, valor) VALUES('perfis_modelo_v23', '1')")
```

- [ ] **Step 4: Escrever os endpoints**

Em `api/main.py`, logo depois do endpoint `antt_piso`:

```python
@app.get("/api/operacao/antt/rntrc")
def antt_rntrc(dt_de: str | None = None, dt_ate: str | None = None) -> JSONResponse:
    """Situação do RNTRC dos transportadores contratados no período."""
    from datetime import timedelta

    from api.antt.rntrc_servico import get_rntrc
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=365)).isoformat()   # 12 meses
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    try:
        return JSONResponse(get_rntrc(dt_de, dt_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("antt_rntrc falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao conferir o RNTRC dos transportadores.",
        })


@app.post("/api/operacao/antt/rntrc/atualizar")
async def antt_rntrc_atualizar(req: Request) -> JSONResponse:
    """Baixa a competência mais recente da base aberta da ANTT (~158 MB)."""
    from datetime import timedelta

    from api.antt.armazenamento import BaseVazia
    from api.antt.rntrc import LayoutInesperado
    from api.antt.rntrc_servico import atualizar_base
    hoje = date.today()
    try:
        return JSONResponse(atualizar_base(
            (hoje - timedelta(days=365)).isoformat(), hoje.isoformat()))
    except BaseVazia as exc:
        log.warning("sync do rntrc veio vazia: %s", exc)
        return JSONResponse(status_code=502, content={
            "erro": "sync_vazia",
            "mensagem": ("A base da ANTT não trouxe nenhum dos transportadores "
                         "procurados. A base anterior foi mantida."),
        })
    except LayoutInesperado as exc:
        log.warning("layout do csv do rntrc mudou: %s", exc)
        return JSONResponse(status_code=502, content={
            "erro": "layout_inesperado",
            "mensagem": f"O arquivo da ANTT mudou de formato: {exc}",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("antt_rntrc_atualizar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_sync",
            "mensagem": "Não foi possível atualizar a base do RNTRC.",
        })
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/antt/ -v`
Expected: PASS, incluindo os 5 novos.

- [ ] **Step 6: Provar contra o banco e a rede**

```bash
uv run python -c "
import os, json
from pathlib import Path
for l in Path('.env').read_text().splitlines():
    if l.strip() and not l.startswith('#') and '=' in l:
        k,v=l.split('=',1); os.environ.setdefault(k.strip(), v.strip())
from api.antt.rntrc_servico import atualizar_base, get_rntrc
from datetime import date, timedelta
hoje = date.today(); ano = (hoje - timedelta(days=365)).isoformat()
print('sync:', atualizar_base(ano, hoje.isoformat()))
d = get_rntrc(ano, hoje.isoformat())
print('kpis:', json.dumps(d['kpis'], indent=1))
"
```

Expected: a sincronização baixa ~158 MB e grava ~222 linhas; os KPIs mostram cerca de 205 ativos, 16 pendentes e 1 não encontrado, com aproximadamente R$ 2,5 milhões em risco. **Se o número de "não encontrados" vier alto (dezenas), a normalização de zeros quebrou** — é o defeito conhecido desta fase, não um achado de compliance.

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/auth.py tests/antt/test_rntrc_endpoint.py
git commit -m "feat(antt): endpoints de RNTRC com RBAC restrito"
```

---

### Task 6: Tela `#anrntrc`

**Files:**
- Modify: `api/static/index.html`
- Test: `tests/antt/test_rntrc_tela_e2e.py`

**Interfaces:**
- Consumes: os dois endpoints da Task 5.
- Produces: view `anrntrc` em `VIEWS`, `DATAMAP`, `LOADMAP`; `loadAnrntrc()`, `renderAnrntrc(d)`, `anrntrcAtualizar()`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/antt/test_rntrc_tela_e2e.py
"""A tela do RNTRC contra o index.html real, com payload do serviço."""
from __future__ import annotations

import json
from pathlib import Path

from api.antt.rntrc_servico import conferir, resumir
from tests.frontend.conftest import USUARIO

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")

BASE = {"7600540": {"rntrc": "7600540", "situacao": "ATIVO", "categoria": "ETC",
                    "uf": "SP", "nome": "ALFA", "data_situacao": "01/07/2026"},
        "6242260": {"rntrc": "6242260", "situacao": "PENDENTE", "categoria": "TAC",
                    "uf": "RS", "nome": "JOAO", "data_situacao": "28/08/2025"}}

CONTRATADOS = [
    {"codigo": "C1", "rntrc": "07600540", "nome": "TRANSPORTES ALFA",
     "pessoa": "PJ", "viagens": 320, "pago": 525863.0, "ultima_viagem": "2026-08-01"},
    {"codigo": "C2", "rntrc": "006242260", "nome": "JOAO DA SILVA",
     "pessoa": "PF", "viagens": 603, "pago": 1058578.0, "ultima_viagem": "2026-08-10"},
    {"codigo": "C3", "rntrc": "9999999", "nome": "SUMIDO LTDA",
     "pessoa": "PJ", "viagens": 85, "pago": 184169.0, "ultima_viagem": "2026-07-20"},
]


def test_view_registrada_no_roteador_e_nos_mapas():
    bloco = S.split("const VIEWS = {", 1)[1].split("};", 1)[0]
    assert "anrntrc:" in bloco
    assert "anrntrc:loadAnrntrc" in S
    assert "anrntrc:DATAANRNTRC" in S


def test_tela_entra_no_menu_e_na_gaveta():
    assert 'data-view="anrntrc"' in S
    drawer = S.split('<div class="drawer"', 1)[1]
    assert 'href="#anrntrc"' in drawer


def _abrir(pg, base_url):
    conf = conferir(CONTRATADOS, BASE)
    dados = {"kpis": resumir(conf), "transportadores": conf,
             "sync": {"competencia": "Jul26 - RNTRC", "quando": "2026-08-18 10:00",
                      "linhas": 3},
             "dt_de": "2025-08-18", "dt_ate": "2026-08-18", "fonte": "teste"}

    def rota(route):
        u = route.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            dados if "antt/rntrc" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#anrntrc")
    pg.wait_for_selector("#kpis-anrntrc .kpi", timeout=20000)
    return dados, erros


def test_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_transportador_pendente_aparece_no_topo_com_valor(pagina):
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#anrntrc-lista")
    assert "JOAO DA SILVA" in texto
    primeira = pg.inner_text("#anrntrc-lista tr")
    assert "JOAO" in primeira or "SUMIDO" in primeira  # risco primeiro


def test_kpi_declara_o_valor_em_risco(pagina):
    pg, base = pagina
    dados, _ = _abrir(pg, base)
    texto = pg.inner_text("#kpis-anrntrc")
    assert "2" in texto  # dois em risco
    assert pg.eval_on_selector_all("#kpis-anrntrc .kpi", "e=>e.length") == 4


def test_tela_mostra_a_competencia_da_base(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert "Jul26" in pg.inner_text("#anrntrc-sync")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/antt/test_rntrc_tela_e2e.py -v`
Expected: FAIL — `anrntrc:` ausente de `VIEWS`.

- [ ] **Step 3: Registrar a view**

Repita para `anrntrc` exatamente os cinco pontos que `anpiso` ocupa em `api/static/index.html`:

1. `const VIEWS = {...}` — acrescente `anrntrc:'RNTRC dos Transportadores'`. **Sem isto a tela não abre**: `currentView()` cai em `home` e o menu leva para a Visão Geral sem erro nenhum.
2. `let DATAANRNTRC = null;` junto das outras globais.
3. `DATAMAP` e `LOADMAP`: `anrntrc:DATAANRNTRC` e `anrntrc:loadAnrntrc`.
4. Menu lateral, dentro de `#subsAntt`, depois do link do piso:

```html
        <a href="#anrntrc" class="sub" data-view="anrntrc" title="RNTRC — situação do registro dos transportadores contratados"><span class="ic" data-ic="qualic"></span><span>RNTRC dos Transportadores</span></a>
```

5. Gaveta mobile, ao lado de "Piso ANTT":

```html
        <a href="#anrntrc" onclick="fecharDrawer()"><span class="ic" data-ic="qualic"></span>RNTRC</a>
```

Esta tela **não usa a barra de filtros** (o período é fixo em 12 meses), então acrescente `anrntrc` à lista de `semFilterbar(v)` — procure a função e siga o padrão das telas sem filtro, como `veicf` e `mprev`.

- [ ] **Step 4: Escrever a marcação da view**

Depois de `view-anpiso`:

```html
      <!-- ===================== RNTRC ===================== -->
      <section class="view" id="view-anrntrc">
        <div class="kpis" id="kpis-anrntrc"></div>
        <div class="card">
          <div class="head">
            <h2>Transportadores contratados <span class="ihelp" tabindex="0" role="img" aria-label="fonte do dado" title="Transportadores com frete de compra nos últimos 12 meses (programacaoembarque, não cancelada, semáforo = 1, veículo AGR/TER), cruzados com a base aberta do RNTRC (dados.antt.gov.br, CC-BY) pelo número de registro guardado em cadastro.numerorntrc. A base da ANTT publica apenas os registros ATIVO e PENDENTE: quem não aparece pode estar baixado, e por isso conta como risco a investigar, não como regular.">i</span></h2>
            <span class="hint" id="anrntrc-sync">base não sincronizada</span>
          </div>
          <div style="padding:0 14px 12px">
            <button class="btn" id="btnAnrntrcSync" onclick="anrntrcAtualizar()">Atualizar base da ANTT</button>
            <span class="hint" style="margin-left:10px">baixa ~158 MB e guarda só os transportadores contratados</span>
          </div>
          <div class="tablewrap tabroll"><table><thead><tr>
            <th>Transportador</th><th>Tipo</th><th>RNTRC</th><th>Categoria</th><th>UF</th><th>Situação</th><th class="num">Viagens</th><th class="num">Pago (12m)</th><th class="num">Última viagem</th>
          </tr></thead><tbody id="anrntrc-lista"></tbody></table></div>
        </div>
      </section>
```

Confira a classe real do botão (`grep -n 'class="btn' api/static/index.html | head`) e use a da casa.

- [ ] **Step 5: Escrever loader, render e o botão de sync**

Espelhe `loadAnpiso` para o loader. O render monta quatro KPIs e a tabela:

```javascript
const ANRNTRC_SIT = {
  ativo:          '<span class="badge b-ok">ativo</span>',
  pendente:       '<span class="badge b-warn">pendente</span>',
  nao_encontrado: '<span class="badge b-warn">fora da base</span>',
  sem_registro:   '<span class="badge b-warn">sem RNTRC no cadastro</span>',
  sem_base:       '<span class="badge">base não sincronizada</span>'
};
let anrntrcSeq = 0;
async function loadAnrntrc(){
  skelKpis('kpis-anrntrc',4);
  const seq = ++anrntrcSeq;
  const btn=document.getElementById('btnRefresh');
  btn.disabled=true;
  document.getElementById('content').classList.add('loading');
  try{
    const r=await fetch('/api/operacao/antt/rntrc',{cache:'no-store'});
    const d=await r.json();
    if(seq!==anrntrcSeq) return;
    if(!r.ok){ showBanner(d.mensagem||'Erro ao conferir o RNTRC.', d.detalhe); return; }
    hideBanner(); DATAANRNTRC=d; renderAnrntrc(d); LOADEDQS.anrntrc='';
  }catch(e){ if(seq===anrntrcSeq) showBanner('Não foi possível falar com a API.', e.message); }
  finally{
    if(seq===anrntrcSeq){ btn.disabled=false; document.getElementById('content').classList.remove('loading'); }
  }
}
function renderAnrntrc(d){
  if(!d) return;
  const k=d.kpis;
  document.getElementById('kpis-anrntrc').innerHTML=[
    kpi('Transportadores', k.transportadores.toLocaleString('pt-BR'),
        'com frete de compra nos últimos 12 meses',''),
    kpi('Com registro ativo', k.ativos.toLocaleString('pt-BR'),
        k.transportadores? Math.round(100*k.ativos/k.transportadores)+'% dos contratados':'—',''),
    kpi('Em risco', k.em_risco.toLocaleString('pt-BR'),
        k.pendentes+' pendentes · '+k.nao_encontrados+' fora da base · '+k.sem_registro+' sem RNTRC',
        k.em_risco>0?'alerta':''),
    kpi('Pago a quem está em risco', BRL.format(k.pago_em_risco),
        k.pct_risco==null?'—':(Math.round(1000*k.pct_risco)/10)+'% do pago a terceiros · '+k.viagens_em_risco+' viagens',
        k.pago_em_risco>0?'alerta':'')
  ].join('');
  const s=d.sync;
  document.getElementById('anrntrc-sync').textContent = s
    ? ('base da ANTT: '+s.competencia+' · sincronizada em '+s.quando+' · '+s.linhas+' registros')
    : 'base não sincronizada — clique em Atualizar';
  document.getElementById('anrntrc-lista').innerHTML=(d.transportadores||[]).map(t=>`<tr>
      <td><div style="font-weight:600">${esc(t.nome||'')}</div></td>
      <td>${esc(t.pessoa||'')}</td>
      <td class="num" style="font-family:var(--mono)">${esc(t.rntrc||'—')}</td>
      <td>${esc(t.categoria||'—')}</td>
      <td>${esc(t.uf||'—')}</td>
      <td>${ANRNTRC_SIT[t.situacao]||esc(t.situacao)}</td>
      <td class="num">${(t.viagens||0).toLocaleString('pt-BR')}</td>
      <td class="num" style="font-weight:600">${BRL.format(t.pago||0)}</td>
      <td class="num">${fmtD(t.ultima_viagem)}</td>
    </tr>`).join('') || '<tr><td colspan="9" style="color:var(--n500)">sem transportadores no período</td></tr>';
}
async function anrntrcAtualizar(){
  const b=document.getElementById('btnAnrntrcSync');
  b.disabled=true; const rotulo=b.textContent; b.textContent='baixando da ANTT…';
  try{
    const r=await fetch('/api/operacao/antt/rntrc/atualizar',{method:'POST'});
    const d=await r.json();
    if(!r.ok){ showBanner(d.mensagem||'Erro ao atualizar a base.', d.detalhe); return; }
    hideBanner(); await loadAnrntrc();
  }catch(e){ showBanner('Não foi possível falar com a API.', e.message); }
  finally{ b.disabled=false; b.textContent=rotulo; }
}
```

- [ ] **Step 6: Rodar e olhar a tela**

Run: `uv run pytest tests/antt/ -v`
Expected: PASS.

Suba a API, abra `#anrntrc`, clique em "Atualizar base da ANTT" e confirme: o botão fica desabilitado durante o download, a competência aparece no rodapé do card, e os pendentes ficam no topo da lista.

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/antt/test_rntrc_tela_e2e.py
git commit -m "feat(antt): tela do RNTRC dos transportadores"
```

---

### Task 7: Gancho em Agregados, versão e documentação

**Files:**
- Modify: `api/static/index.html` (coluna na tela Agregados)
- Modify: `pyproject.toml`, `docs/versoes.yaml`, `docs/manual.yaml`, `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: Gancho na tela Agregados**

Acrescente a coluna "RNTRC" à tabela de transportadores, ao lado da coluna "vs piso ANTT" que a Fase 1 criou. Mesma regra: **não dispara consulta**, só usa `DATAANRNTRC` se já estiver em memória.

```javascript
function anrntrcDoTransportador(codigo){
  const d = DATAANRNTRC;
  if(!d) return '<span style="color:var(--n500)" title="Abra ANTT › RNTRC dos Transportadores para conferir">—</span>';
  const t = (d.transportadores||[]).find(x=>x.codigo===codigo);
  if(!t) return '<span style="color:var(--n500)">—</span>';
  return ANRNTRC_SIT[t.situacao] || esc(t.situacao);
}
```

Acrescente `<th class="num">RNTRC</th>` ao cabeçalho, a célula na linha, e **incremente o colspan de 12 para 13** nos dois lugares (linha de detalhe e mensagem de tabela vazia).

- [ ] **Step 2: Subir a versão**

`pyproject.toml`: `version = "0.5.0"`. No topo de `docs/versoes.yaml`:

```yaml
- versao: "0.5.0"
  data: "2026-08-18"
  adicionado:
    - >-
      Tela RNTRC dos Transportadores: mostra quais transportadores contratados
      nos últimos 12 meses estão com o registro na ANTT fora de "ativo", e
      quanto já foi pago a cada um.
    - >-
      Botão "Atualizar base da ANTT" busca a competência mais recente do
      cadastro nacional e guarda apenas os transportadores que a Sulista
      contrata.
    - >-
      A tela de Agregados e Terceiros ganhou a coluna RNTRC, com a situação do
      registro de cada transportador.
```

- [ ] **Step 3: Gerar o CHANGELOG**

Run: `uv run python scripts/gerar_changelog.py`
Expected: seção 0.5.0 no topo do `CHANGELOG.md`.

- [ ] **Step 4: Documentação**

Em `docs/manual.yaml`, acrescente `anrntrc` ao grupo ANTT (`telas: [anpiso, anrntrc]`) — **o teste `test_toda_tela_do_painel_esta_em_algum_grupo` falha se esquecer**. Acrescente ao glossário:

```yaml
  - termo: RNTRC
    definicao: >-
      Registro Nacional de Transportadores Rodoviários de Cargas. Todo
      transportador que faz frete por conta de terceiros precisa dele ativo;
      contratar quem está irregular é infração. As categorias são ETC (empresa),
      CTC (cooperativa) e TAC (autônomo). O CÓRTEX cruza o número guardado no
      cadastro do ERP com a base aberta da ANTT, atualizada mensalmente.
```

Em `CLAUDE.md`, seção 3, complemente a linha do módulo `antt` com a conferência de RNTRC.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `uv run pytest -q`
Expected: tudo verde, incluindo os testes pré-existentes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(antt): gancho de RNTRC em Agregados, versao 0.5.0 e documentacao"
```

---

## Fora do escopo desta fase

**A sincronização automática que a spec previa (§5.1) não entra aqui, e é uma
escolha, não esquecimento.** Baixar 158 MB na subida da API atrasaria o boot e
tornaria o restart dependente da rede; e a base da ANTT muda uma vez por mês, o
que não justifica verificação a cada 24 h. O botão manual cobre o caso real, e a
tela mostra a competência carregada — se estiver velha, quem abrir vê. Se a
frente crescer, o lugar certo para automatizar é o `scripts/digest_diario.sh`,
que já roda agendado, não o processo da API.

Autos de infração (Fase 3) e mercado/pedágio (Fase 4). Bloqueio de contratação também fica fora: o CÓRTEX lê o AVA, não escreve nele — a tela alerta, a decisão de contratar continua no ERP.
