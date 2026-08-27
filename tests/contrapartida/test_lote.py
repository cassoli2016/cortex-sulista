# tests/contrapartida/test_lote.py
"""Emissao em lote — as guardas que so existem no caminho automatico.

Emitir a mao tem um humano lendo o retorno. Uma rotina que assina em nome de
terceiro milhares de vezes por mes nao tem, e os erros dela chegam
multiplicados. Cada teste aqui cobre uma dessas guardas.

Nenhum vai a rede nem ao banco: `db.query`, o cadastro e a transmissao entram
por substituicao.
"""
from __future__ import annotations

import dataclasses

import pytest

from api.contrapartida import lote
from tests.contrapartida.test_documento import ENQ

CHAVES = ["3526...A", "3526...B", "3526...C", "3526...D"]


def _linhas(n=4):
    return [{"chave": CHAVES[i], "dtemissao": "2026-08-20",
             "cnpj": "111", "nome": "AGREGADO", "valor": 100.0 * (i + 1)}
            for i in range(n)]


@pytest.fixture
def base(monkeypatch):
    """Banco com 4 CT-e, um agregado pronto, nada emitido ainda."""
    monkeypatch.setattr(lote.db, "query", lambda *a, **k: _linhas())
    monkeypatch.setattr(lote.cadastro, "mapa",
                        lambda: {"111": {"prontidao": {"pronto": True}}})
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: set())
    monkeypatch.setattr(lote, "automacao_ativa", lambda: False)


# --- a chave da automacao ---------------------------------------------------

def test_automacao_nasce_DESLIGADA(monkeypatch):
    """Ausencia de registro significa desligado, nunca o contrario: um padrao
    ligado faria a rotina comecar a emitir por causa de um banco novo ou de
    uma restauracao de backup."""
    monkeypatch.setattr(lote.emissao, "config_lida", lambda chave: None)
    assert lote.automacao_ativa() is False


def test_valor_desconhecido_tambem_conta_como_DESLIGADO(monkeypatch):
    """So a string "1" liga. Lixo na configuracao nao pode virar autorizacao
    para emitir sozinho."""
    monkeypatch.setattr(lote.emissao, "config_lida",
                        lambda chave: {"valor": "talvez"})
    assert lote.automacao_ativa() is False


def test_desassistido_com_automacao_desligada_e_RECUSADO(base):
    """A rotina agendada nao roda se ninguem ligou."""
    with pytest.raises(PermissionError, match="DESLIGADA"):
        lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="rotina",
                            limite=5, desassistido=True)


def test_MANUAL_funciona_com_a_automacao_desligada(base):
    """O ponto do desenho: manual sempre; automatico so se alguem ligar."""
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="fulano",
                            limite=5, dry_run=True)
    assert r["fila"] == 4 and r["dry_run"] is True


def test_ligar_a_automacao_exige_autor():
    """E a decisao que define quem responde por um documento emitido as tres
    da manha."""
    with pytest.raises(ValueError, match="Informe quem"):
        lote.definir_automacao(True, "")


# --- idempotencia -----------------------------------------------------------

def test_chave_ja_AUTORIZADA_nao_volta_para_a_fila(base, monkeypatch):
    """Documento fiscal duplicado nao se apaga: cancela-se, dentro de prazo,
    com justificativa."""
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: {CHAVES[0],
                                                                CHAVES[2]})
    fila = lote.pendentes("2026-08-01", "2026-08-27")
    assert [x["chave"] for x in fila] == [CHAVES[1], CHAVES[3]]


def test_so_a_AUTORIZADA_conta_como_feita():
    """Tentativa recusada nao emitiu nada - o CT-e de origem continua
    pendente. A consulta filtra por cStat 100."""
    import inspect
    fonte = inspect.getsource(lote._ja_emitidas)
    assert "cstat='100'" in fonte


def test_agregado_sem_certificado_fica_FORA_da_fila(base, monkeypatch):
    """Fila que inclui quem nao pode emitir promete trabalho que vai falhar."""
    monkeypatch.setattr(lote.cadastro, "mapa",
                        lambda: {"111": {"prontidao": {"pronto": False}}})
    assert lote.pendentes("2026-08-01", "2026-08-27") == []


# --- disjuntor e teto -------------------------------------------------------

def test_o_lote_PARA_depois_de_falhas_seguidas(base, monkeypatch):
    """Falha sistemica rejeita tudo. Sem disjuntor, um lote de mil queima mil
    numeros de serie antes de alguem perceber."""
    def explode(*a, **k):
        raise RuntimeError("SEFAZ fora")

    monkeypatch.setattr(lote.emissao, "transmitir", explode)
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                            limite=10)
    assert r["erros"] == lote.MAX_FALHAS_SEGUIDAS
    assert r["interrompido"] and "queimar" in r["interrompido"]
    assert r["restante"] == 4 - lote.MAX_FALHAS_SEGUIDAS


def test_sucesso_no_meio_ZERA_o_contador(base, monkeypatch):
    """Duas recusas separadas por um sucesso nao sao falha sistemica."""
    chamadas = {"n": 0}

    def alterna(chave, enq, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            return {"autorizado": True, "cStat": "100", "chave": "nova"}
        raise RuntimeError("recusa isolada")

    monkeypatch.setattr(lote.emissao, "transmitir", alterna)
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                            limite=10)
    assert r["autorizados"] == 1
    assert r["interrompido"] is None, "o sucesso do meio zerou o contador"


def test_o_teto_e_obrigatorio_e_positivo(base):
    for ruim in (0, -1):
        with pytest.raises(ValueError, match="teto positivo"):
            lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                                limite=ruim)


def test_o_lote_exige_autor(base):
    with pytest.raises(ValueError, match="Informe quem"):
        lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="",
                            limite=5)


def test_o_teto_absoluto_limita_ate_um_pedido_maior(base):
    """Existe para `limite` vindo de configuracao errada, nao para limitar o
    uso legitimo."""
    assert lote.TETO_ABSOLUTO <= 500
    fila = lote.pendentes("2026-08-01", "2026-08-27", limite=10_000)
    assert len(fila) <= lote.TETO_ABSOLUTO


# --- ensaio -----------------------------------------------------------------

def test_ensaio_NAO_transmite(base, monkeypatch):
    def nao_deveria(*a, **k):
        raise AssertionError("ensaio transmitiu")

    monkeypatch.setattr(lote.emissao, "transmitir", nao_deveria)
    r = lote.processar_lote("2026-08-01", "2026-08-27", ENQ, quem="x",
                            limite=10, dry_run=True)
    assert r["fila"] == 4
    assert all(i["situacao"] == "ensaio" for i in r["itens"])


def test_o_lote_NAO_DECIDE_o_ambiente(base):
    """Ele atende os dois, mas quem recusa producao nao liberada e
    `emissao.transmitir`. O lote repassa - e o padrao segue homologacao."""
    import inspect
    assert inspect.signature(
        lote.processar_lote).parameters["ambiente"].default == "2"
    fonte = inspect.getsource(lote.processar_lote)
    assert "liberar_producao" not in fonte, (
        "o lote nao pode destravar producao por conta propria")


def test_producao_tem_teto_MENOR_que_homologacao():
    """Lote errado em homologacao custa tempo; em producao custa cancelamento
    e retificacao, documento a documento."""
    assert lote.teto_do(lote.emissao.PRODUCAO) < lote.teto_do("2")
    assert lote.teto_do(lote.emissao.PRODUCAO) == lote.TETO_ABSOLUTO_PRODUCAO


def test_a_fila_de_producao_respeita_o_teto_menor(base):
    fila = lote.pendentes("2026-08-01", "2026-08-27",
                          ambiente=lote.emissao.PRODUCAO, limite=10_000)
    assert len(fila) <= lote.TETO_ABSOLUTO_PRODUCAO


# --- os dois ambientes ------------------------------------------------------

def test_producao_nasce_TRAVADA(monkeypatch):
    """Nasce assim e nao destrava sozinha."""
    monkeypatch.setattr(lote.emissao, "config_lida", lambda chave: None)
    assert lote.emissao.producao_liberada() is False


def test_liberar_producao_EXIGE_a_frase_de_confirmacao():
    """`--producao` numa linha de comando e facil demais de digitar por
    engano, e o engano aqui custa cancelamento e retificacao."""
    with pytest.raises(PermissionError, match="confirme com a frase"):
        lote.emissao.liberar_producao(True, "fulano", confirmacao="sim")
    with pytest.raises(PermissionError):
        lote.emissao.liberar_producao(True, "fulano", confirmacao="")


def test_VOLTAR_para_homologacao_nao_pede_frase(monkeypatch):
    """Voltar e sempre seguro e nao pode depender de lembrar de uma frase no
    meio de um problema."""
    gravado = {}

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, par=()):
            gravado["par"] = par
            return self

    monkeypatch.setattr(lote.emissao, "_conn_config", lambda: _C())
    monkeypatch.setattr(lote.emissao.cadastro, "_audita",
                        lambda *a, **k: None)
    monkeypatch.setattr(lote.emissao, "config_lida", lambda chave: None)
    r = lote.emissao.definir_ambiente(lote.emissao.HOMOLOGACAO, "fulano")
    assert r["producao"] is False
    assert gravado["par"][1] == lote.emissao.HOMOLOGACAO


def test_ambiente_ativo_nasce_em_HOMOLOGACAO(monkeypatch):
    """Banco novo, backup restaurado ou configuracao corrompida caem no
    ambiente que NAO emite documento de verdade."""
    monkeypatch.setattr(lote.emissao, "config_lida", lambda chave: None)
    assert lote.emissao.ambiente_ativo() == lote.emissao.HOMOLOGACAO
    monkeypatch.setattr(lote.emissao, "config_lida",
                        lambda chave: {"valor": "lixo"})
    assert lote.emissao.ambiente_ativo() == lote.emissao.HOMOLOGACAO


def test_intervalo_padrao_e_os_limites():
    """Abaixo do piso a rotina vira carga constante sem emitir mais rapido: a
    fila so cresce quando um CT-e novo e digitado."""
    assert lote.INTERVALO_MIN >= 5 and lote.INTERVALO_MAX <= 1440
    for ruim in (0, 1, lote.INTERVALO_MAX + 1, "muito"):
        with pytest.raises(ValueError):
            lote.definir_intervalo(ruim, "fulano")


def test_intervalo_corrompido_cai_no_padrao_em_vez_de_derrubar(monkeypatch):
    monkeypatch.setattr(lote.emissao, "config_lida",
                        lambda chave: {"valor": "abacaxi"})
    assert lote.intervalo_min() == lote.INTERVALO_PADRAO_MIN


def test_intervalo_exige_autor():
    with pytest.raises(ValueError, match="Informe quem"):
        lote.definir_intervalo(60, "")


def test_transmitir_em_producao_TRAVADA_e_recusado(monkeypatch):
    monkeypatch.setattr(lote.emissao, "producao_liberada", lambda: False)
    with pytest.raises(PermissionError, match="PRODUÇÃO está travada"):
        lote.emissao._guardas("111", {"emit_cnpj": "111"},
                              lote.emissao.PRODUCAO)


def test_ambiente_inexistente_e_recusado():
    with pytest.raises(ValueError, match="não existe"):
        lote.emissao._guardas("111", {"emit_cnpj": "111"}, "9")


# --- a tela de configuracao -------------------------------------------------

def test_a_rota_de_configuracao_e_de_ADMINISTRADOR():
    """Estes dois interruptores decidem se o sistema emite documento fiscal
    real e se faz isso sem ninguem olhando. `/api/gestao/*` ja e restrito a
    admin pelo AuthMiddleware - o teste garante que a rota nasceu nesse
    prefixo, e nao num caminho aberto a qualquer logado."""
    fonte = open("api/main.py", encoding="utf-8").read()
    assert '@app.get("/api/gestao/contrapartida")' in fonte
    assert '@app.post("/api/gestao/contrapartida")' in fonte
    assert "/api/contrapartida/config" not in fonte


def test_o_autor_sai_da_SESSAO_e_nao_do_corpo():
    """Quem responde por ligar producao nao pode ser um campo que o proprio
    cliente preenche."""
    fonte = open("api/main.py", encoding="utf-8").read()
    trecho = fonte[fonte.index("async def gestao_contrapartida_salvar"):]
    trecho = trecho[:trecho.index("return JSONResponse(lote.estado())")]
    assert 'req.state, "sessao"' in trecho
    assert 'body.get("quem")' not in trecho and 'body["quem"]' not in trecho


def test_estado_devolve_o_que_a_tela_precisa():
    e = lote.estado()
    assert set(e) >= {"ambiente", "automacao", "teto", "falhas_para_parar"}
    assert set(e["automacao"]) >= {"ativa", "intervalo_min", "intervalo_limites"}
    # a frase vai para a tela para ela poder INSTRUIR, nao para validar no
    # cliente: quem valida e o servidor
    assert e["ambiente"]["confirmacao_exigida"]


# --- a rotina agendada ------------------------------------------------------

def test_automacao_desligada_faz_a_rotina_NAO_rodar(monkeypatch):
    monkeypatch.setattr(lote, "automacao_ativa", lambda: False)
    pode, porque = lote.deve_rodar()
    assert pode is False and "desligada" in porque


def test_primeira_execucao_roda(monkeypatch):
    monkeypatch.setattr(lote, "automacao_ativa", lambda: True)
    monkeypatch.setattr(lote, "ultima_execucao", lambda: None)
    pode, porque = lote.deve_rodar()
    assert pode is True and "primeira" in porque


def test_antes_do_intervalo_NAO_roda(monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(lote, "automacao_ativa", lambda: True)
    monkeypatch.setattr(lote, "intervalo_min", lambda: 60)
    monkeypatch.setattr(lote, "ultima_execucao",
                        lambda: (datetime.now() - timedelta(minutes=10)
                                 ).isoformat(timespec="seconds"))
    pode, porque = lote.deve_rodar()
    assert pode is False and "faltam" in porque


def test_depois_do_intervalo_roda(monkeypatch):
    from datetime import datetime, timedelta
    monkeypatch.setattr(lote, "automacao_ativa", lambda: True)
    monkeypatch.setattr(lote, "intervalo_min", lambda: 60)
    monkeypatch.setattr(lote, "ultima_execucao",
                        lambda: (datetime.now() - timedelta(minutes=61)
                                 ).isoformat(timespec="seconds"))
    assert lote.deve_rodar()[0] is True


def test_carimbo_ilegivel_roda_em_vez_de_travar_para_sempre(monkeypatch):
    """Um valor corrompido nao pode deixar a rotina parada indefinidamente."""
    monkeypatch.setattr(lote, "automacao_ativa", lambda: True)
    monkeypatch.setattr(lote, "ultima_execucao", lambda: "ontem de tarde")
    pode, porque = lote.deve_rodar()
    assert pode is True and "ilegível" in porque


def test_o_modo_agendado_sai_LIMPO_quando_nao_e_hora():
    """Sair com 0 e de proposito: para o Windows a tarefa foi bem-sucedida, e
    o historico do agendador nao enche de 'falha' a cada cinco minutos."""
    fonte = open("scripts/emitir_lote.py", encoding="utf-8").read()
    trecho = fonte[fonte.index("if a.agendado:"):]
    assert 'print(f"nada a fazer' in trecho and "return 0" in trecho


def test_a_tarefa_agendada_NAO_escolhe_ambiente():
    """O ambiente e decisao da TELA. Deixa-lo no argumento da tarefa criaria
    uma segunda fonte da verdade que ninguem lembraria de conferir."""
    ps1 = open("scripts/instalar_tarefa_contrapartida.ps1",
               encoding="utf-8-sig").read()
    # so a LINHA DA ACAO importa: o comentario logo acima cita --producao
    # justamente para explicar por que ele nao esta no argumento.
    # `-ArgumentList` da auto-elevacao tambem casa com "-Argument": pega a
    # linha do -Argument do New-ScheduledTaskAction, que e a que executa.
    acao = [l for l in ps1.splitlines()
            if "-Argument " in l and "$alvo" in l]
    assert len(acao) == 1, acao
    assert "--agendado" in acao[0] and "--producao" not in acao[0]
    assert "Minutes 5" in ps1, "o disparo tem de bater com o piso do intervalo"


# --- exportacao para o ERP --------------------------------------------------

CTE_ASSINADO = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<CTe xmlns="http://www.portalfiscal.inf.br/cte">'
                '<infCte Id="CTe123"/><Signature>xxx</Signature></CTe>')
PROT = '<protCTe versao="4.00"><infProt><nProt>135</nProt></infProt></protCTe>'


def test_o_proc_envelopa_documento_E_protocolo():
    """O documento sozinho nao prova autorizacao: o que o ERP importa e o
    `cteProc`, que carrega os dois."""
    proc = lote.emissao.montar_proc(CTE_ASSINADO, PROT)
    assert proc.startswith('<?xml version="1.0" encoding="UTF-8"?><cteProc')
    assert "<infCte" in proc and "<nProt>135</nProt>" in proc
    assert proc.rstrip().endswith("</cteProc>")


def test_o_xml_assinado_entra_INTACTO():
    """Reserializar quebraria a assinatura: qualquer mudanca de espaco em
    branco ou de ordem de atributo faz o arquivo ser recusado por quem for
    validar. Por isso o envelope e montado por TEXTO."""
    proc = lote.emissao.montar_proc(CTE_ASSINADO, PROT)
    corpo = CTE_ASSINADO[CTE_ASSINADO.index("<CTe"):]
    assert corpo in proc, "o documento assinado foi alterado no caminho"


def test_a_declaracao_do_documento_interno_e_removida():
    """Dois '<?xml ...?>' no mesmo arquivo nao e XML valido."""
    proc = lote.emissao.montar_proc(CTE_ASSINADO, PROT)
    assert proc.count("<?xml") == 1


def test_so_documento_AUTORIZADO_vira_proc(monkeypatch):
    """`cteProc` montado com documento recusado seria um arquivo com cara de
    valido. A consulta filtra por cStat 100."""
    import inspect
    fonte = inspect.getsource(lote.emissao.proc_de)
    assert "cstat='100'" in fonte
    assert "xml_prot IS NOT NULL" in fonte


def test_exportacao_separa_os_ambientes(tmp_path, monkeypatch):
    """Misturar homologacao com producao na mesma pasta e o caminho mais curto
    para alguem importar documento de teste como se valesse."""
    monkeypatch.setattr(lote.emissao, "_conn", lambda: _ConnFake([]))
    r = lote.emissao.exportar(str(tmp_path), ambiente=lote.emissao.HOMOLOGACAO)
    assert r["pasta"].endswith("homologacao")
    r = lote.emissao.exportar(str(tmp_path), ambiente=lote.emissao.PRODUCAO)
    assert r["pasta"].endswith("producao")


class _ConnFake:
    """Conexao minima: devolve as linhas dadas e um contador zerado."""

    def __init__(self, linhas): self._linhas = linhas

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, par=()):
        if "count(*)" in sql:
            return _Um({"n": 0})
        return iter(self._linhas)


class _Um:
    """Cursor de uma linha só: `count(*)` e lido com fetchone()."""

    def __init__(self, r): self._r = r
    def fetchone(self): return self._r


def test_exportacao_grava_um_arquivo_por_CHAVE(tmp_path, monkeypatch):
    linhas = [{"chave": "3526AAA", "quando": "2026-08-27",
               "xml": CTE_ASSINADO, "xml_prot": PROT},
              {"chave": "3526BBB", "quando": "2026-08-27",
               "xml": CTE_ASSINADO, "xml_prot": PROT}]
    monkeypatch.setattr(lote.emissao, "_conn", lambda: _ConnFake(linhas))
    r = lote.emissao.exportar(str(tmp_path))
    assert r["exportados"] == 2
    nomes = sorted(p.name for p in (tmp_path / "homologacao").iterdir())
    assert nomes == ["3526AAA-procCTe.xml", "3526BBB-procCTe.xml"]
    conteudo = (tmp_path / "homologacao" / "3526AAA-procCTe.xml").read_text(
        encoding="utf-8")
    assert "<cteProc" in conteudo and "<nProt>135</nProt>" in conteudo


def test_arquivos_NAO_vao_para_o_controle_de_versao():
    """Documento fiscal carrega CNPJ, valor e chave - e o repositorio do
    codigo e PUBLICO."""
    import inspect
    fonte = inspect.getsource(lote.emissao)
    assert 'DIR_EXPORTACAO = cadastro.ROOT / "data"' in fonte
    # o .gitignore usa `data/*` e nao `data/` de proposito, para conseguir
    # reexcluir um arquivo especifico depois com `!data/...`
    gitignore = open(".gitignore", encoding="utf-8").read()
    assert "data/*" in gitignore
    assert "!data/cte_contrapartida" not in gitignore, (
        "documento fiscal reexcluido do ignore iria para o repositorio, que "
        "e PUBLICO")


def test_a_rota_de_download_segue_o_prefixo_da_TELA():
    """`/api/*` fora de ROTA_TELAS e 403 para nao-admin (fail-closed). A rota
    tem de nascer sob o prefixo da tela, e a mais ESPECIFICA vem antes da
    generica - ROTA_TELAS casa por prefixo."""
    from api import auth
    main = open("api/main.py", encoding="utf-8").read()
    assert '"/api/fiscal/contrapartida/documento/{chave}"' in main

    rotas = [r for r, _ in auth.ROTA_TELAS
             if r.startswith("/api/fiscal/contrapartida")]
    assert "/api/fiscal/contrapartida/documento" in rotas
    assert (rotas.index("/api/fiscal/contrapartida/documento")
            < rotas.index("/api/fiscal/contrapartida")), (
        "a generica casaria primeiro e engoliria a especifica")


def test_download_de_documento_recusado_devolve_404():
    """Documento recusado nao tem processo. Devolver um XML vazio seria pior
    que a ausencia: um arquivo com cara de valido."""
    main = open("api/main.py", encoding="utf-8").read()
    i = main.index("def contrapartida_documento")
    trecho = main[i:main.index("Content-Disposition", i)]
    assert "status_code=404" in trecho
    assert "sem_documento" in trecho
