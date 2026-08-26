# tests/contrapartida/test_contrapartida.py
"""CT-e de contrapartida: o que NAO pode ser somado e o que NAO pode ser feito.

O risco desta tela nao e errar um total - e juntar duas populacoes fiscais
diferentes. O TAC (pessoa fisica) nao emite CT-e por forca da Lei 11.442:
somar os 6.020 CT-e dele aos 12.482 do PJ produziria um passivo 48% maior, com
documento que nao pode existir, e mandaria a operacao atras dele.
"""
from __future__ import annotations

import ast

from api.contrapartida import servico
from api.contrapartida.sql import (FROTA_AGR_SQL, PASSIVO_SQL,
                                   POR_AGREGADO_SQL, POR_MES_SQL)

TODAS = (POR_MES_SQL, POR_AGREGADO_SQL, FROTA_AGR_SQL, PASSIVO_SQL)


def test_sql_respeita_pg93_e_latin1():
    for sql in TODAS:
        assert "FILTER (WHERE" not in sql.upper()
        assert "percentile_cont" not in sql.lower()
        sql.encode("latin-1")


def test_classifica_por_TAMANHO_do_documento():
    """14 digitos = CNPJ (emite), 11 = CPF (nao emite). E o unico criterio
    disponivel: nao ha flag de "e TAC" no cadastro."""
    for sql in (POR_MES_SQL, POR_AGREGADO_SQL, FROTA_AGR_SQL, PASSIVO_SQL):
        assert "= 14 THEN 'pj'" in sql and "= 11 THEN 'tac'" in sql


def test_documento_fora_do_padrao_nao_vira_PJ_por_default():
    """Cair no 'pj' por omissao poria na fila de emissao alguem que talvez nao
    emita. O terceiro caso e explicito e sai num aviso proprio."""
    for sql in TODAS:
        assert "ELSE 'indefinido' END" in sql


def test_cancelado_fora_do_passivo():
    """Passivo que conta documento cancelado e passivo inventado."""
    for sql in TODAS:
        if "conhecimento" in sql:
            assert "coalesce(k.semaforo, 1) = 1" in sql
            assert "k.dtcancelamento IS NULL" in sql


def test_agregado_sem_cadastro_NAO_some_da_fila():
    """LEFT e nao INNER: sumir da fila por falta de cadastro esconderia
    exatamente o caso que precisa de acao."""
    assert "LEFT JOIN cadastro cd" in POR_AGREGADO_SQL


def test_traz_o_que_a_EMISSAO_exige():
    """RNTRC, IE e municipio ausentes viram rejeicao documento a documento -
    com 3 mil CT-e/mes, e o erro que para a operacao."""
    for campo in ("numerorntrc", "inscricaoestadual", "razaosocial", "cidade"):
        assert campo in POR_AGREGADO_SQL


# --- o servico --------------------------------------------------------------

def test_a_tela_e_SO_LEITURA():
    """Guarda de codigo (arvore sintatica, nao texto): emissao em nome de
    terceiro depende de procuracao, certificado e enquadramento fiscal, e
    nenhuma das tres e decisao de software."""
    with open(servico.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    nomes = {n.attr for n in ast.walk(arvore) if isinstance(n, ast.Attribute)}
    nomes |= {n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)}
    assert not (nomes & {"assinar", "transmitir", "emitir", "certificado",
                         "pfx", "sign", "post"})


def test_emitidas_e_zero_declarado_e_nao_calculado():
    """Zero por confirmacao da operacao, nao por consulta que devolveu vazio.
    A diferenca importa: consulta vazia pode ser bug."""
    with open(servico.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        src = f.read()
    assert '"emitidas": 0' in src


def test_pt_br_formata_SO_o_numero():
    """Aplicar replace(",", ".") na frase inteira comeu as virgulas do texto -
    a armadilha da substituicao em massa, em miniatura."""
    assert servico._br(108713961.0, 0) == "108.713.961"
    assert servico._br(1234.5) == "1.234,50"
    assert servico._br(0, 0) == "0"


def test_janela_endireita_e_inclui_o_dia_final():
    de, ate = servico._janela("2026-08-26", "2026-03-01")
    assert de == "2026-03-01" and ate == "2026-08-27"


# --- os avisos --------------------------------------------------------------

def _pj(n): return [{"documento": str(i), "nome": "X", "ie": "1",
                     "rntrc": "2", "cidade": "C"} for i in range(n)]


def test_avisa_SEMPRE_que_nada_foi_emitido():
    av = servico._avisos(_pj(3), [], [], [], [])
    assert any("Nenhuma contrapartida emitida" in a for a in av)


def test_aviso_do_TAC_explica_que_e_do_DOCUMENTO_e_nao_do_certificado():
    """O usuario disse ter certificado de todos. Para o TAC isso nao resolve:
    ele nao e sujeito passivo do CT-e."""
    av = servico._avisos(_pj(53), [{"documento": "1"}] * 30, [], [], [])
    texto = " ".join(av)
    assert "CIOT" in texto and "certificado" in texto


def test_passivo_historico_NAO_vira_fila_de_trabalho():
    """CT-e nao se emite retroativo: a SEFAZ recusa data fora da janela."""
    av = servico._avisos(_pj(1), [], [], [], [
        {"ano": "2025", "classe": "pj", "ctes": 34188, "valor": 108713961.0}])
    alvo = [a for a in av if "Passivo" in a][0]
    assert "108.713.961" in alvo and "retroativo" in alvo
    assert "34.188" in alvo


def test_pendencia_cadastral_nomeia_o_campo_que_falta():
    av = servico._avisos(_pj(1), [], [],
                         [{"documento": "9", "nome": "ACME", "falta": ["RNTRC"]}], [])
    assert any("ACME" in a and "RNTRC" in a for a in av)


# --- RBAC -------------------------------------------------------------------

def test_rota_registrada_e_restrita():
    from api.auth import ROTA_TELAS, TELAS
    assert "ctecp" in TELAS
    assert any(r[0] == "/api/fiscal/contrapartida" and "ctecp" in r[1]
               for r in ROTA_TELAS)


# --- serializacao -----------------------------------------------------------

def test_resposta_e_JSON_serializavel():
    """O JSONResponse nao serializa datetime.date e devolve 500. As colunas
    `primeiro`/`ultimo` do SQL vem como date - e o teste anterior, que so
    olhava os KPIs, nunca chegava na serializacao: o defeito so apareceu
    quando a tela abriu."""
    import json
    from datetime import date
    linhas = [{"mes": "2026-08", "primeiro": date(2026, 8, 1),
               "ultimo": date(2026, 8, 26), "ctes": 3}]
    saida = servico._serial(linhas)
    assert saida[0]["primeiro"] == "2026-08-01"
    json.dumps(saida)          # explode se sobrar date


def test_serial_preserva_o_resto_dos_campos():
    from datetime import date
    r = servico._serial([{"a": 1, "b": "x", "c": None, "d": date(2026, 1, 2)}])[0]
    assert r["a"] == 1 and r["b"] == "x" and r["c"] is None and r["d"] == "2026-01-02"


# --- procuracao e certificado -----------------------------------------------
"""Emitir com o certificado do agregado e ASSINAR COMO ELE. Por isso a
autorizacao e estrutura de dados, nao recomendacao: sem procuracao vigente e
certificado A1 valido, o agregado nao fica pronto - e o motivo vai junto."""

from api.contrapartida import cadastro as cad  # noqa: E402

PROC_OK = {"valida_de": "2026-01-01", "valida_ate": "2027-01-01"}
CERT_OK = {"tipo": "A1", "valida_ate": "2027-06-01", "arquivo": "x.pfx"}


def test_sem_nada_nao_esta_pronto_e_DIZ_o_que_falta():
    """"Nao pronto" sem motivo obriga a abrir tres telas para descobrir."""
    r = cad.prontidao("X", None, None, False)
    assert not r["pronto"]
    assert any("autorização" in f for f in r["faltas"])
    assert any("certificado" in f for f in r["faltas"])


def test_A3_e_impedimento_e_nao_pendencia():
    """A3 mora em token fisico e exige presenca a cada assinatura. Nao se
    resolve preenchendo campo - falhar so na transmissao seria pior."""
    r = cad.prontidao("X", PROC_OK, {"tipo": "A3"}, True)
    assert not r["pronto"]
    assert any("A3" in f and "automatiza" in f for f in r["faltas"])


def test_procuracao_vencida_bloqueia():
    r = cad.prontidao("X", {"valida_de": "2020-01-01", "valida_ate": "2021-01-01"},
                      CERT_OK, True)
    assert not r["pronto"] and any("vencida" in f for f in r["faltas"])


def test_procuracao_futura_bloqueia():
    r = cad.prontidao("X", {"valida_de": "2099-01-01", "valida_ate": "2099-12-31"},
                      CERT_OK, True)
    assert not r["pronto"]


def test_senha_ausente_bloqueia():
    """Sem senha no cofre o .pfx nao abre: descobrir isso na transmissao custa
    uma rejeicao por documento."""
    r = cad.prontidao("X", PROC_OK, CERT_OK, False)
    assert not r["pronto"] and any("senha" in f for f in r["faltas"])


def test_vencimento_proximo_e_ALERTA_e_nao_bloqueio():
    """Certificado A1 vale um ano. Avisar antes da hora e o que evita a rotina
    parar em silencio; bloquear antes de vencer pararia sem motivo."""
    from datetime import date, timedelta
    perto = (date.today() + timedelta(days=10)).isoformat()
    r = cad.prontidao("X", PROC_OK, dict(CERT_OK, valida_ate=perto), True)
    assert r["pronto"] and any("vence em 10 dias" in a for a in r["alertas"])


def test_tudo_certo_fica_pronto():
    assert cad.prontidao("X", PROC_OK, CERT_OK, True)["pronto"]


def test_o_cofre_de_senha_e_PROPRIO_e_nao_o_geral():
    """api/credenciais.py recusa chave fora da lista CONHECIDAS - e com razao:
    ele existe para credenciais NOMEADAS e FIXAS que a tela de Gestao edita uma
    a uma. Senha de certificado e uma POR AGREGADO, dinamica. Empurrar para la
    quebrava a premissa do modulo e foi o erro de gravacao que apareceu na
    tela."""
    with open(cad.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        src = f.read()
    assert "from api import credenciais" not in src
    assert "SENHAS_PATH" in src and "0o600" in src


def test_cofre_de_senha_grava_le_e_apaga(tmp_path, monkeypatch):
    monkeypatch.setattr(cad, "SENHAS_PATH", tmp_path / "s.json")
    assert not cad.tem_senha("1")
    cad.gravar_senha("1", "abc")
    assert cad.tem_senha("1") and cad.ler_senha("1") == "abc"
    cad.gravar_senha("1", "")          # apagar
    assert not cad.tem_senha("1")


def test_cofre_ilegivel_nao_derruba_a_tela(tmp_path, monkeypatch):
    """Arquivo corrompido nao pode virar 500 na conciliacao inteira: o pior
    caso e o agregado aparecer como sem senha, que ja e o estado normal."""
    alvo = tmp_path / "s.json"
    alvo.write_text("{isto nao e json", encoding="utf-8")
    monkeypatch.setattr(cad, "SENHAS_PATH", alvo)
    assert cad.tem_senha("1") is False


def test_so_existe_UM_caminho_de_saida_para_a_senha():
    """`ler_senha` e o unico, de proposito, e nenhum endpoint o expoe. O teste
    garante que nao surja um SEGUNDO caminho - e que `mapa()`, que a tela
    consome, devolva apenas o booleano `tem_senha`."""
    with open(cad.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        src = f.read()
        arvore = ast.parse(src)
    fn = [n.name for n in ast.walk(arvore)
          if isinstance(n, ast.FunctionDef) and "senha" in n.name]
    assert sorted(fn) == ["_senhas", "gravar_senha", "ler_senha", "tem_senha"], fn
    # o que a tela recebe nunca carrega o valor
    i = src.index("def mapa(")
    assert "ler_senha" not in src[i:]


def test_senha_nao_entra_na_tabela():
    """DDL sem coluna de senha: banco com senha, mesmo local, e vazamento
    permanente esperando backup errado."""
    assert "senha" not in cad._DDL.lower()


def test_ha_trilha_de_auditoria():
    """Quem autorizou emitir em nome de quem, e quando, tem de ser respondivel
    meses depois - inclusive contra o proprio CORTEX."""
    assert "CREATE TABLE IF NOT EXISTS auditoria" in cad._DDL
    for campo in ("quando", "quem", "acao", "cnpj"):
        assert campo in cad._DDL


def test_certificado_recusa_tipo_invalido():
    import pytest as _pt
    with _pt.raises(ValueError):
        cad.gravar_certificado("1", "A2", "eu")


def test_procuracao_recusa_validade_invertida():
    import pytest as _pt
    with _pt.raises(ValueError):
        cad.gravar_autorizacao("1", "emitir CT-e", "2027-01-01", "2026-01-01", "eu")


def test_sem_filtro_a_tela_abre_no_DIA_DE_HOJE():
    """A fila e trabalho DIARIO: o CT-e sai hoje e o documento do agregado tem
    de sair junto. Abrir em seis meses respondia "quanto acumulou" quando a
    pergunta do dia e "o que preciso emitir agora"."""
    from datetime import date, timedelta
    de, ate = servico._janela(None, None)
    assert de == date.today().isoformat()
    assert ate == (date.today() + timedelta(days=1)).isoformat()


# --- inscricao estadual -----------------------------------------------------

def test_ISENTO_nao_e_inscricao_estadual():
    """CT-e e documento de ICMS: emitente precisa ser inscrito. O teste antigo
    (`if not ie`) dava "ISENTO" por COMPLETO, porque e string nao vazia - e
    isso e pior que nao validar: da confianca falsa sobre um terco da fila."""
    assert not servico._ie_utilizavel("ISENTO")
    assert not servico._ie_utilizavel("")
    assert not servico._ie_utilizavel(None)
    assert not servico._ie_utilizavel("-")
    assert servico._ie_utilizavel("5256749740076")
    assert servico._ie_utilizavel("123.456.789")


def test_pendencia_de_IE_mostra_O_VALOR_encontrado():
    """"inscricao estadual" sozinho parece campo em branco; o operador iria
    preencher em vez de conferir no SINTEGRA."""
    av = servico._avisos(
        [{"documento": "1", "nome": "ACME", "ie": "ISENTO", "rntrc": "9",
          "cidade": "X"}], [], [],
        [{"documento": "1", "nome": "ACME",
          "falta": ["inscrição estadual (ISENTO)"]}], [])
    assert any("ISENTO" in a for a in av)


def test_aviso_de_IE_diz_o_TAMANHO_REAL_da_fila():
    """O numero que decide: se os 17 nao emitem, a fila e de 36 e nao de 53."""
    pj = [{"documento": str(i), "nome": "X", "ie": "" if i < 17 else "123",
           "rntrc": "9", "cidade": "C"} for i in range(53)]
    av = servico._avisos(pj, [], [], [], [])
    alvo = [a for a in av if "inscrição" in a][0]
    assert "17 de 53" in alvo and "36" in alvo and "SINTEGRA" in alvo
