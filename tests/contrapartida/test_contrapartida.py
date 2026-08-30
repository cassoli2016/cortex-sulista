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


def test_homologacao_NAO_entra_na_contagem_de_emitidas():
    """`emitidas` era zero declarado enquanto nada havia sido transmitido.
    Agora ha transmissoes de verdade - mas so em HOMOLOGACAO, que e ambiente
    de teste e nao tem valor fiscal. Somar as duas faria a tela anunciar uma
    fila resolvida que nao foi, que e pior do que o zero antigo."""
    with open(servico.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        src = f.read()
    assert '"emitidas": _tx["producao"]' in src
    assert '"emitidas_homologacao": _tx["homologacao"]' in src


def test_a_contagem_separa_ambiente_e_resultado(monkeypatch):
    """Producao x homologacao, e autorizada x recusada: quatro numeros, porque
    documento recusado tambem nao emitiu nada.

    A contagem sai de `totais`, que le o registro INTEIRO, e nao de
    `historico`, que devolve so a ultima pagina - contar na pagina fazia o
    limite da consulta passar por universo.
    """
    monkeypatch.setattr("api.contrapartida.emissao.historico",
                        lambda limite=30: [])
    monkeypatch.setattr("api.contrapartida.emissao.por_dia", lambda n=30: [])
    monkeypatch.setattr("api.contrapartida.emissao.totais", lambda: {
        "documentos": 3, "autorizados": 2, "producao": 1, "producao_ok": 1,
        "homologacao": 2, "com_xml": 0, "autorizados_sem_xml": 2})
    t = servico._transmissoes()
    assert (t["producao"], t["homologacao"]) == (1, 2)
    assert (t["autorizadas"], t["recusadas"]) == (2, 1)


def test_registro_indisponivel_nao_derruba_a_tela(monkeypatch):
    """O resto da conciliacao nao depende do historico de transmissoes."""
    def explode(limite=30):
        raise RuntimeError("banco fora")
    monkeypatch.setattr("api.contrapartida.emissao.historico", explode)
    t = servico._transmissoes()
    assert t["ultimas"] == [] and t["producao"] == 0


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
    av = servico._avisos(_pj(3), [], [], [])
    assert any("Nenhuma contrapartida emitida" in a for a in av)


def test_aviso_do_TAC_explica_que_e_do_DOCUMENTO_e_nao_do_certificado():
    """O usuario disse ter certificado de todos. Para o TAC isso nao resolve:
    ele nao e sujeito passivo do CT-e."""
    av = servico._avisos(_pj(53), [{"documento": "1"}] * 30, [], [])
    texto = " ".join(av)
    assert "CIOT" in texto and "certificado" in texto


def test_o_passivo_historico_SAIU_da_tela():
    """CT-e nao se emite retroativo, entao o acumulado nunca virava trabalho -
    so ocupava espaco numa tela cuja pergunta e "o que preciso emitir agora".
    O numero segue registrado no documento da contabilidade, que e onde ele
    serve: decisao de contabilidade e juridico.

    Tirar tambem removeu uma consulta que varria desde 2022."""
    import inspect
    fonte = inspect.getsource(servico)
    assert "PASSIVO_SQL" not in fonte
    av = servico._avisos(_pj(1), [], [], [])
    assert not any("Passivo" in a for a in av)


def test_prontidao_separa_os_DOIS_portoes():
    """Cadastro completo e autorizacao sao coisas diferentes: um agregado pode
    ter o cadastro impecavel e nao emitir nada por falta de certificado."""
    pj = [
        {"documento": "1", "ie": "123", "falta": [], "ctes": 10, "valor": 100.0,
         "prontidao": {"pronto": True}},
        {"documento": "2", "ie": "123", "falta": [], "ctes": 20, "valor": 200.0,
         "prontidao": {"pronto": False}},
        {"documento": "3", "ie": "ISENTO", "ind_ie": 1, "falta": ["x"],
         "ctes": 30, "valor": 300.0, "prontidao": {"pronto": False}},
        {"documento": "4", "ie": "ISENTO", "ind_ie": 9, "falta": ["x"],
         "ctes": 40, "valor": 400.0, "prontidao": {"pronto": False}},
    ]
    r = servico._prontidao_fila(pj)
    assert r["autorizados"]["agregados"] == 1
    assert r["cadastro_ok_sem_certificado"]["agregados"] == 1
    assert r["sem_ie_contribuinte"]["agregados"] == 1
    assert r["sem_ie_nao_contribuinte"]["agregados"] == 1
    # o volume acompanha o agregado, nao a contagem
    assert r["autorizados"]["ctes"] == 10 and r["total"]["ctes"] == 100


def test_pendencia_cadastral_nomeia_o_campo_que_falta():
    av = servico._avisos(_pj(1), [], [],
                         [{"documento": "9", "nome": "ACME", "falta": ["RNTRC"]}])
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

from pathlib import Path

from api.contrapartida import cadastro as cad

ROOT = Path(__file__).resolve().parents[2]  # noqa: E402

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
    assert "SENHAS_PATH" in src


def test_o_arquivo_de_senha_nasce_RESTRITO(tmp_path, monkeypatch):
    """Este teste afirmava `"0o600" in src` — o LITERAL no texto-fonte. Ele
    quebrou sem haver defeito no dia em que o `chmod` virou
    `segredo_arquivo.proteger()`, e o pior é que a afirmação nunca foi
    verdadeira no servidor: `chmod` no Windows só liga o somente-leitura, e
    quem decide acesso é a ACL. Procurar a string era procurar a promessa, não
    a proteção.

    Agora se pergunta ao arquivo."""
    from api import segredo_arquivo
    alvo = tmp_path / "s.json"
    monkeypatch.setattr(cad, "SENHAS_PATH", alvo)
    cad.gravar_senha("1", "abc")
    assert segredo_arquivo.estado(alvo)["protegido"] is not False


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
    ddl = (ROOT / "sql" / "cortex" / "0010_contrapartida.sql").read_text(
        encoding="utf-8")
    # só as linhas de DDL: os comentários FALAM de senha de propósito, para
    # explicar por que ela não está aqui — e essa explicação tem de continuar
    # podendo ser escrita
    codigo = chr(10).join(l for l in ddl.splitlines()
                          if not l.strip().startswith("--"))
    assert "senha" not in codigo.lower()


def test_ha_trilha_de_auditoria():
    """Quem autorizou emitir em nome de quem, e quando, tem de ser respondivel
    meses depois - inclusive contra o proprio CORTEX."""
    ddl = (ROOT / "sql" / "cortex" / "0010_contrapartida.sql").read_text(
        encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS auditoria" in ddl
    for campo in ("quando", "quem", "acao", "cnpj"):
        assert campo in ddl


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
          "falta": ["inscrição estadual (ISENTO)"]}])
    assert any("ISENTO" in a for a in av)


def test_aviso_de_IE_diz_o_TAMANHO_REAL_da_fila():
    """O numero que decide: se os 17 nao emitem, a fila e de 36 e nao de 53."""
    pj = [{"documento": str(i), "nome": "X", "ie": "" if i < 17 else "123",
           "rntrc": "9", "cidade": "C"} for i in range(53)]
    av = servico._avisos(pj, [], [], [])
    alvo = [a for a in av if "inscrição" in a][0]
    assert "17 de 53" in alvo and "36" in alvo and "SINTEGRA" in alvo


def test_a_lista_de_pendencias_vai_PRONTA_para_a_tela():
    """A coluna Cadastro recalculava a regra em JavaScript e divergiu no mesmo
    dia em que "ISENTO" passou a contar: o servidor dizia 17 pendencias e a
    tabela mostrava "completo" nas mesmas linhas. Duplicata de regra escrita a
    mao diverge."""
    fonte = servico.__file__.replace(".pyc", ".py")
    with open(fonte, encoding="utf-8") as f:
        src = f.read()
    assert 'x["falta"] = (_por_doc.get' in src
    raiz = __import__("pathlib").Path(fonte).parent.parent.parent
    html = (raiz / "api" / "static" / "index.html").read_text(encoding="utf-8")
    # o front nao pode montar a lista de novo
    assert "['razão social',x.nome]" not in html
    assert "const falta=(x.falta||[]);" in html


def test_a_MONTAGEM_INTEIRA_roda_e_serializa(monkeypatch):
    """Guarda de integracao, e ela existe porque faltou.

    Um NameError dentro de `get_contrapartida` foi para producao e quem
    encontrou foi o usuario, com a tela dizendo "Erro ao montar a
    conciliacao". A suite passava: os testes exercitavam `_serial`, `_br`,
    `_avisos` — cada peca — e NENHUM chamava a funcao que a tela chama.

    Este roda o caminho todo com o banco mockado e serializa o resultado, que
    e exatamente o que a rota faz.
    """
    import json

    monkeypatch.setattr(servico.db, "query", lambda *a, **k: [])
    monkeypatch.setattr("api.contrapartida.cadastro.mapa", lambda: {})
    monkeypatch.setattr("api.contrapartida.emissao.historico",
                        lambda limite=30: [])
    r = servico.get_contrapartida()
    assert {"periodo", "kpis", "emissoes", "por_agregado"} <= set(r)
    json.dumps(r)


def test_a_montagem_sobrevive_ao_historico_fora_do_ar(monkeypatch):
    """O registro de transmissoes e acessorio: se ele cair, a conciliacao —
    que e o motivo da tela existir — tem de continuar aparecendo."""
    import json

    def explode(limite=30):
        raise RuntimeError("registro fora")

    monkeypatch.setattr(servico.db, "query", lambda *a, **k: [])
    monkeypatch.setattr("api.contrapartida.cadastro.mapa", lambda: {})
    monkeypatch.setattr("api.contrapartida.emissao.historico", explode)
    r = servico.get_contrapartida()
    assert r["emissoes"] == [] and r["kpis"]["emitidas"] == 0
    json.dumps(r)


def test_a_trilha_nao_grava_email_pessoal_por_padrao():
    """Quem roda o script na bancada varia; a trilha tem de dizer que foi o
    CORTEX. E-mail pessoal de quem por acaso executou nao identifica o ator."""
    import inspect

    from api.contrapartida import emissao
    assert emissao.IDENTIDADE_SISTEMA.endswith("@sulista.com.br")
    fonte = inspect.getsource(emissao)
    assert "gmail" not in fonte.lower()
    # emissao pela TELA continua exigindo o usuario logado
    assert inspect.signature(
        emissao.transmitir).parameters["quem"].default is inspect.Parameter.empty


def test_o_script_de_operacao_usa_a_identidade_do_sistema():
    fonte = open("scripts/emitir_homologacao.py", encoding="utf-8").read()
    assert "emissao.IDENTIDADE_SISTEMA" in fonte
    assert "gmail" not in fonte.lower()


def test_o_historico_nao_carrega_o_xml_inteiro():
    """O XML e grande e a tela nao o usa: a listagem devolve so se EXISTE."""
    import inspect

    from api.contrapartida import emissao
    fonte = inspect.getsource(emissao.historico)
    assert "tem_xml" in fonte and "SELECT *" not in fonte


def test_autorizada_sem_xml_e_contada_a_parte(monkeypatch):
    """Documento autorizado sem arquivo guardado nao se importa no ERP nem se
    arquiva - a chave prova que existe, o arquivo e que serve."""
    monkeypatch.setattr("api.contrapartida.emissao.historico",
                        lambda limite=30: [])
    monkeypatch.setattr("api.contrapartida.emissao.por_dia", lambda n=30: [])
    monkeypatch.setattr("api.contrapartida.emissao.totais", lambda: {
        "documentos": 3, "autorizados": 2, "producao": 0, "producao_ok": 0,
        "homologacao": 3, "com_xml": 1, "autorizados_sem_xml": 1})
    t = servico._transmissoes()
    assert t["com_xml"] == 1 and t["autorizadas_sem_xml"] == 1


# --- vencimento de certificado ----------------------------------------------

def test_semaforo_do_certificado_e_GRADUADO():
    """"Vence em 2 dias" e "vence em 29" pedem acoes diferentes; chip igual
    para os dois nao prioriza nada."""
    assert servico._situacao_cert(-1, "A1")[0] == "vencido"
    assert servico._situacao_cert(0, "A1")[0] == "critico"
    assert servico._situacao_cert(15, "A1")[0] == "critico"
    assert servico._situacao_cert(16, "A1")[0] == "alerta"
    assert servico._situacao_cert(30, "A1")[0] == "alerta"
    assert servico._situacao_cert(31, "A1")[0] == "atencao"
    assert servico._situacao_cert(60, "A1")[0] == "atencao"
    assert servico._situacao_cert(61, "A1")[0] == "ok"


def test_validade_ausente_NAO_e_ok():
    """Tratar validade ausente como boa noticia e o erro que faz a emissao
    parar em silencio: o certificado vence, ninguem e avisado, e a empresa
    descobre pelo agregado."""
    assert servico._situacao_cert(None, "A1")[0] == "desconhecido"


def test_A3_e_impedimento_e_nao_prazo():
    """A3 mora em token fisico: nao se resolve esperando nem renovando data."""
    situacao, texto = servico._situacao_cert(400, "A3")
    assert situacao == "impedido" and "token" in texto


def test_um_dia_no_singular():
    assert "1 dia" in servico._situacao_cert(1, "A1")[1]
    assert "2 dias" in servico._situacao_cert(2, "A1")[1]


def test_a_ordem_poe_URGENCIA_antes_e_VOLUME_dentro_dela():
    """Um certificado que vence em 40 dias e sustenta metade da fila urge mais
    que um vencendo em 10 que nunca emitiu nada - mas so DENTRO da mesma
    situacao: urgencia continua vindo primeiro."""
    from datetime import date, timedelta
    hoje = date.today()

    def _cert(dias):
        return (hoje + timedelta(days=dias)).isoformat()

    pj = [
        {"documento": "1", "nome": "POUCO VOLUME", "ctes": 1, "valor": 1.0},
        {"documento": "2", "nome": "MUITO VOLUME", "ctes": 900, "valor": 90.0},
        {"documento": "3", "nome": "TRANQUILO", "ctes": 500, "valor": 50.0},
    ]
    pront = {
        "1": {"certificado": {"tipo": "A1", "valida_ate": _cert(5)},
              "tem_senha": True},
        "2": {"certificado": {"tipo": "A1", "valida_ate": _cert(10)},
              "tem_senha": True},
        "3": {"certificado": {"tipo": "A1", "valida_ate": _cert(300)},
              "tem_senha": True},
    }
    r = servico._certificados(pj, pront)
    # os dois criticos vem antes do tranquilo; entre eles, o de maior volume
    assert [i["nome"] for i in r["itens"]] == [
        "MUITO VOLUME", "POUCO VOLUME", "TRANQUILO"]
    assert r["ate_30"]["certificados"] == 2
    assert r["ate_30"]["ctes"] == 901, "o alerta carrega o VOLUME em risco"


def test_agregado_sem_certificado_fica_fora_deste_card():
    """Quem nem tem certificado e pendencia de outro cartao - misturar faria
    o controle de VENCIMENTO virar lista de cadastro."""
    r = servico._certificados([{"documento": "9", "nome": "X", "ctes": 5}], {})
    assert r["itens"] == [] and r["total"] == 0


def test_o_controle_de_certificado_NAO_segue_o_filtro_de_periodo():
    """O defeito que isto trava: a tela abre no DIA DE HOJE, e a lista saia
    dos agregados com CT-e no periodo. Num dia sem movimento o agregado sumia
    do controle - e sumiu justamente o certificado que vencia PRIMEIRO.

    Certificado vence no calendario, nao na janela que a tela mostra.
    """
    from datetime import date, timedelta
    venc = (date.today() + timedelta(days=20)).isoformat()
    pront = {
        "111": {"certificado": {"tipo": "A1", "valida_ate": venc,
                                "titular": "QUEM NAO RODOU HOJE"},
                "tem_senha": True},
    }
    r = servico._certificados([], pront)      # nenhum CT-e no periodo
    assert r["total"] == 1, "sumiu do controle por nao ter rodado no recorte"
    assert r["itens"][0]["no_periodo"] is False
    assert r["itens"][0]["nome"] == "QUEM NAO RODOU HOJE", (
        "sem CT-e no periodo nao ha razao social na consulta - o titular do "
        "certificado e o ultimo recurso para a linha nao sair anonima")
    assert r["ignora_periodo"] is True


def test_volume_zero_fora_do_periodo_nao_se_confunde_com_volume_zero():
    """"0 CT-e" e "nao rodou no recorte" sao coisas diferentes, e a tela
    precisa do sinal para nao mostrar um zero que engana."""
    from datetime import date, timedelta
    venc = (date.today() + timedelta(days=90)).isoformat()
    pj = [{"documento": "222", "nome": "RODOU", "ctes": 7, "valor": 70.0}]
    pront = {
        "111": {"certificado": {"tipo": "A1", "valida_ate": venc}, "tem_senha": True},
        "222": {"certificado": {"tipo": "A1", "valida_ate": venc}, "tem_senha": True},
    }
    por_doc = {i["documento"]: i for i in servico._certificados(pj, pront)["itens"]}
    assert por_doc["222"]["no_periodo"] is True and por_doc["222"]["ctes"] == 7
    assert por_doc["111"]["no_periodo"] is False


def test_aviso_de_emissao_SAI_DA_CONTAGEM_e_nao_de_texto_fixo():
    """O primeiro aviso de "Ler com atencao" era um TEXTO FIXO: "nenhuma
    contrapartida emitida ate hoje". Era verdade quando foi escrito e continuou
    na tela depois das primeiras emissoes, inclusive a de PRODUCAO - o cartao
    passou a afirmar o contrario dos cartoes ao lado. Aviso que nao sai de uma
    contagem envelhece calado, e no dia em que erra ninguem desconfia dos
    outros numeros da tela."""
    from api.contrapartida import servico

    zero = servico._avisos([], [], [], [], {"producao": 0, "homologacao": 0})
    assert "Nenhuma contrapartida emitida" in zero[0]

    homo = servico._avisos([], [], [], [], {"producao": 0, "homologacao": 4})
    assert "Nenhuma contrapartida emitida" not in homo[0]
    assert "HOMOLOGA" in homo[0].upper()
    assert "4" in homo[0]

    prod = servico._avisos([], [], [], [], {"producao": 2, "homologacao": 4})
    assert "PRODU" in prod[0].upper()
    assert "2" in prod[0]


def test_aviso_sem_transmissoes_nao_quebra_sem_o_argumento():
    """A tela nao pode cair se o registro de transmissoes estiver indisponivel:
    o resto da conciliacao nao depende dele."""
    from api.contrapartida import servico
    assert servico._avisos([], [], [], [])[0].startswith("Nenhuma")


def test_rota_do_cronometro_e_alcancavel_por_quem_ve_a_tela():
    """`AuthMiddleware` e fail-closed: rota /api/* fora de ROTA_TELAS devolve
    403 para nao-admin. O cronometro apareceria vazio so para o administrador
    e ninguem perceberia."""
    from api import auth

    casadas = [t for p, t in auth.ROTA_TELAS
               if "/api/fiscal/contrapartida/automacao".startswith(p)]
    assert casadas, "rota do cronometro fora de ROTA_TELAS"
    assert "ctecp" in casadas[0], "o primeiro prefixo que casa manda"


def test_prefixo_especifico_vem_ANTES_do_generico():
    """A busca e por prefixo, na ordem da lista. Se o generico
    /api/fiscal/contrapartida vier primeiro, ele engole todas as rotas
    especificas - e o erro so aparece quando alguem restringe a tela."""
    from api import auth

    ordem = [p for p, _ in auth.ROTA_TELAS if p.startswith("/api/fiscal/contrapartida")]
    generico = ordem.index("/api/fiscal/contrapartida")
    assert generico == len(ordem) - 1, f"o prefixo generico nao e o ultimo: {ordem}"


def test_o_cronometro_nao_expoe_quem_mexeu_na_configuracao():
    """A rota de gestao diz quem ligou a automacao e quem liberou producao -
    isso e de administrador. A da tela leva so o relogio."""
    import inspect

    from api import main

    fonte = inspect.getsource(main.contrapartida_automacao)
    assert '"quem"' not in fonte and "'quem'" not in fonte
    for campo in ("ativa", "intervalo_min", "ultima_execucao",
                  "passo_agendador_min"):
        assert campo in fonte


def _ag(doc, nome="AG", ie="9120970051", ind="1", rntrc="1", cidade="X",
        uf="PR", ctes=10, pronto=True, faltas=(), alertas=()):
    return {"documento": doc, "nome": nome, "ie": ie, "ind_ie": ind,
            "rntrc": rntrc, "cidade": cidade, "uf": uf, "ctes": ctes,
            "valor": 100.0,
            "prontidao": {"pronto": pronto, "faltas": list(faltas),
                          "alertas": list(alertas)}}


def test_validador_separa_CADASTRO_de_CERTIFICADO():
    """Sao filas de pessoas diferentes: cadastro se corrige digitando no ERP,
    certificado depende do agregado entregar o arquivo. Sem a separacao, os 76
    achados de certificado afogam os 9 de cadastro e a lista fica inutil."""
    from api.contrapartida import servico

    v = servico._validacao([
        _ag("1", ie="ISENTO"),
        _ag("2", pronto=False, faltas=["sem certificado cadastrado"]),
    ])
    cats = v["por_categoria"]
    assert cats.get("cadastro") == 1
    assert cats.get("certificado") == 1


def test_contradicao_de_cadastro_cita_a_rejeicao_MEDIDA():
    """229 foi medida na transmissao. Os outros campos NAO ganham codigo
    inventado - dar numero a um palpite e o que faz a tela parecer mais certa
    do que e."""
    from api.contrapartida import servico

    v = servico._validacao([_ag("1", ie="ISENTO"), _ag("2", rntrc=None)])
    por_defeito = {a["defeito"]: a for a in v["achados"]}
    ie = [a for a in v["achados"] if "contribuinte" in a["defeito"]][0]
    assert ie["rejeicao"] and "229" in ie["rejeicao"]
    assert por_defeito["sem RNTRC"]["rejeicao"] is None


def test_nao_contribuinte_nao_e_pendencia_a_corrigir():
    """Marcado como nao contribuinte e coerente: ele nao emite CT-e. Sai da
    fila por natureza do documento, e nao entra na conta de impedimento -
    senao vira pendencia eterna que ninguem consegue resolver."""
    from api.contrapartida import servico

    v = servico._validacao([_ag("1", ie="ISENTO", ind="9")])
    assert v["achados"][0]["categoria"] == "natureza"
    assert v["achados"][0]["grave"] is False
    assert v["com_impedimento"] == 0


def test_a_contradicao_INVERSA_tambem_aparece():
    """IE valida com o indicador de NAO contribuinte: um dos dois campos esta
    errado. Nao trava a emissao hoje, mas decide se ele entra na fila - e
    passava despercebido porque so se olhava para a falta de IE."""
    from api.contrapartida import servico

    v = servico._validacao([_ag("1", ie="9101585112", ind="9")])
    assert v["achados"], "a contradicao inversa sumiu"
    a = v["achados"][0]
    assert a["categoria"] == "cadastro" and a["grave"] is False


def test_agregado_sem_defeito_nao_gera_achado():
    from api.contrapartida import servico
    v = servico._validacao([_ag("1")])
    assert v["achados"] == []
    assert v["aprovados"] == 1 and v["com_impedimento"] == 0


def test_UMA_LINHA_por_agregado_em_cada_categoria():
    """Cada falta virava uma linha propria e o mesmo agregado aparecia duas e
    tres vezes - 34 dos 38 repetidos. "Sem procuracao" e "sem certificado" sao
    o MESMO item de trabalho: junta-los e o que faz a lista voltar a ser lista
    de trabalho em vez de lista de campos."""
    from api.contrapartida import servico

    v = servico._validacao([
        _ag("1", nome=None, rntrc=None, cidade=None, pronto=False,
            faltas=["sem procuração cadastrada", "sem certificado cadastrado"]),
    ])
    por_cat = {}
    for a in v["achados"]:
        por_cat.setdefault(a["categoria"], []).append(a)
    for cat, linhas in por_cat.items():
        docs = [a["documento"] for a in linhas]
        assert len(docs) == len(set(docs)), f"{cat} repetiu o agregado"
    assert len(por_cat["certificado"]) == 1
    assert "procuração" in por_cat["certificado"][0]["defeito"]
    assert "certificado" in por_cat["certificado"][0]["defeito"]


def test_campos_faltantes_saem_JUNTOS_e_a_acao_lista_todos():
    from api.contrapartida import servico
    v = servico._validacao([_ag("1", rntrc=None, cidade=None)])
    a = [x for x in v["achados"] if x["categoria"] == "cadastro"][0]
    assert "RNTRC" in a["defeito"] and "município" in a["defeito"]
    assert "RNTRC" in a["acao"] and "município" in a["acao"]


def test_a_acao_do_certificado_sai_da_NATUREZA_da_falta():
    """Vencido se renova, ausente se coleta, senha se cadastra. Um texto unico
    para os tres mandaria pedir ao agregado o que ja esta com a gente."""
    from api.contrapartida import servico

    venc = servico._validacao([_ag("1", pronto=False,
                                   faltas=["certificado vencido há 86 dias"])])
    assert "Renovar" in venc["achados"][0]["acao"]

    senha = servico._validacao([_ag("2", pronto=False,
                                    faltas=["senha ausente no cofre"])])
    assert "cofre" in senha["achados"][0]["acao"]

    sem = servico._validacao([_ag("3", pronto=False,
                                  faltas=["sem certificado cadastrado"])])
    assert "do agregado" in sem["achados"][0]["acao"]


def test_varredura_completa_IGNORA_o_filtro_da_tela():
    """A tela abre no dia de hoje e o validador seguia esse recorte: quem nao
    rodou hoje nao era validado. Defeito de cadastro nao pertence a uma janela
    de datas - mesma licao do cartao de vencimento de certificado. Com o
    filtro do dia viam-se 18 agregados; a varredura completa encontra 46, e as
    duas contradicoes mais caras estavam fora do recorte."""
    import inspect

    from api.contrapartida import servico

    fonte = inspect.getsource(servico.validacao_completa)
    assert "date.today()" in fonte and "timedelta(days=d)" in fonte
    assert "de" in fonte and "ate" in fonte


def test_a_varredura_declara_o_proprio_escopo():
    """Os mesmos numeros significam coisas diferentes conforme a lista tenha
    vindo do filtro da tela ou da varredura completa, e nao da para distinguir
    olhando."""
    import inspect
    from api.contrapartida import servico
    fonte = inspect.getsource(servico.validacao_completa)
    assert '"escopo"' in fonte and '"janela_dias"' in fonte
    assert "não segue o filtro" in fonte


def test_janela_da_varredura_e_limitada():
    """A janela nao e filtro de validacao: e a definicao de agregado ATIVO.
    Validar quem nao roda ha um ano encheria a lista de trabalho que ninguem
    vai fazer - e um `dias` absurdo vindo da URL nao pode virar consulta
    infinita no ERP."""
    import inspect
    from api.contrapartida import servico
    fonte = inspect.getsource(servico.validacao_completa)
    assert "min(int(dias), 730)" in fonte and "max(1," in fonte


def test_rota_da_varredura_e_alcancavel_e_vem_antes_do_generico():
    from api import auth
    alvo = "/api/fiscal/contrapartida/validacao"
    casadas = [t for p, t in auth.ROTA_TELAS if alvo.startswith(p)]
    assert casadas and "ctecp" in casadas[0]
    ordem = [p for p, _ in auth.ROTA_TELAS
             if p.startswith("/api/fiscal/contrapartida")]
    assert ordem.index(alvo) < ordem.index("/api/fiscal/contrapartida")


def test_as_contagens_NAO_saem_da_pagina_do_historico(monkeypatch):
    """O card contava em cima de `historico(30)` e apresentava o LIMITE como
    universo: "5 de 30 autorizadas · 0 em producao", quando eram 30
    autorizadas em 99 documentos e 2 delas em producao - que sumiam por serem
    mais antigas que as trinta ultimas linhas. Um KPI dizendo que nunca
    emitimos em producao no dia seguinte a termos emitido."""
    from api.contrapartida import emissao, servico

    # a PAGINA e pequena e so tem homologacao recusada; o REGISTRO tem mais
    monkeypatch.setattr(emissao, "historico", lambda limite=50: [
        {"chave": "A", "cstat": "748", "ambiente": "2", "tem_xml": 0},
        {"chave": "B", "cstat": "748", "ambiente": "2", "tem_xml": 0},
    ])
    monkeypatch.setattr(emissao, "por_dia", lambda n=30: [])
    monkeypatch.setattr(emissao, "totais", lambda: {
        "documentos": 99, "autorizados": 30, "producao": 4, "producao_ok": 2,
        "homologacao": 95, "com_xml": 73, "autorizados_sem_xml": 12})

    tx = servico._transmissoes()
    assert tx["autorizadas"] == 30 and tx["recusadas"] == 69
    assert tx["documentos"] == 99
    assert tx["producao"] == 4 and tx["producao_autorizadas"] == 2
    assert tx["taxa_ok"] == 30.3
    assert len(tx["ultimas"]) == 2, "a LISTA continua sendo a pagina"


def test_totais_ignoram_o_evento_de_cancelamento():
    """Evento nao e transmissao de documento: conta-lo estragaria a taxa nos
    dois sentidos."""
    import inspect
    from api.contrapartida import emissao
    assert "CANC:%" in inspect.getsource(emissao.totais)


def test_taxa_e_None_sem_nenhuma_transmissao(monkeypatch):
    """"0% de acerto" sem tentativa nenhuma e um numero que acusa alguem."""
    from api.contrapartida import emissao, servico
    monkeypatch.setattr(emissao, "historico", lambda limite=50: [])
    monkeypatch.setattr(emissao, "por_dia", lambda n=30: [])
    monkeypatch.setattr(emissao, "totais", lambda: {"documentos": 0})
    assert servico._transmissoes()["taxa_ok"] is None


def test_o_aviso_de_producao_conta_AUTORIZADOS_e_nao_tentativas():
    """O aviso dizia "N autorizados em PRODUCAO" usando o total de tentativas:
    com 4 transmissoes e 2 autorizacoes, afirmava 4 enquanto o cartao logo
    acima dizia "producao 2 de 4". Dois numeros para a mesma coisa na mesma
    tela, e o texto era o errado."""
    from api.contrapartida import servico

    av = servico._avisos([], [], [], [], {"producao": 4, "homologacao": 110,
                                          "producao_autorizadas": 2})
    assert "2 documento(s) AUTORIZADO(S) em produção" in av[0]
    assert "de 4 transmitido" in av[0]


def test_motivo_da_quarentena_nao_corta_no_meio_da_palavra(monkeypatch):
    """"...inexistente na bas" faz o aviso parecer truncado por defeito."""
    from api.contrapartida import lote, servico

    monkeypatch.setattr(lote, "_quarentena", lambda amb: {
        "X": {"cstat": "748",
              "xmotivo": ("CTe referenciado em documentos anteriores "
                          "inexistente na base de dados da SEFAZ. "
                          "[chCTe:41260876104397000123]")}})
    av = servico._avisos([], [], [], [], {"producao": 0, "homologacao": 1})
    texto = " ".join(av)
    assert "SEFAZ" in texto
    assert "na bas " not in texto and not texto.rstrip().endswith("na bas")
    assert "[chCTe" not in texto, "a chave nao acrescenta nada ao aviso"
