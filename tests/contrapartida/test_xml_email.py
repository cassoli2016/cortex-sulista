# tests/contrapartida/test_xml_email.py
"""Envio dos XML de PRODUCAO para a contabilidade.

O que esta rotina pode errar e caro de duas formas opostas: mandar de menos
(documento fiscal que nao chega a quem escritura) e mandar demais (o mesmo XML
duas vezes, ou um documento de HOMOLOGACAO na caixa de quem escritura). Cada
teste aqui cobre uma dessas.

O SMTP e duble - nenhum teste manda e-mail. O banco e o schema descartavel da
fixture `autouse` do diretorio.
"""
from __future__ import annotations

import smtplib

import pytest

from api.contrapartida import emissao, lote, xml_email
from api.correio import config as cfg
from api.correio import registro


@pytest.fixture(autouse=True)
def _isola_correio(request, monkeypatch, tmp_path):
    """A trilha de e-mail e a config do SMTP vao para o mesmo schema do teste.

    Sem isto o `registro.gravar` do envio escreveria em `correio_envios` de
    PRODUCAO — a trilha do que saiu para fora da empresa, que nao pode ganhar
    linha de teste.
    """
    esquema = request.getfixturevalue("_isola_contrapartida")
    monkeypatch.setattr(registro, "ESQUEMA", esquema)
    monkeypatch.setattr(cfg, "CAMINHO", tmp_path / "email_config.json")
    monkeypatch.setattr(cfg, "senha", lambda: "segredo")
    return esquema


class SMTPFake:
    """Duble de smtplib.SMTP. Guarda as mensagens para os testes olharem.

    A lista e de CLASSE e nao de instancia: cada mensagem abre uma conexao
    nova, entao um `self.enviadas` guardaria so a ultima — e o teste do lote
    dividido em partes leria "parte 2 de 2" como se fosse a primeira.
    """
    ultima = None
    enviadas: list = []

    def __init__(self, *a, **k):
        SMTPFake.ultima = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, *a, **k):
        pass

    def login(self, *a, **k):
        pass

    def send_message(self, msg):
        SMTPFake.enviadas.append(msg)


def _smtp_pronto(monkeypatch):
    cfg.gravar({"host": "smtp.teste.local", "porta": 587,
                "seguranca": "starttls", "usuario": "",
                "remetente": "cortex@sulista.com.br", "remetente_nome": "CÓRTEX"})
    monkeypatch.setattr(smtplib, "SMTP", SMTPFake)
    SMTPFake.ultima = None
    SMTPFake.enviadas = []


# XML de mentira, mas com a forma que `montar_proc` espera encontrar.
_XML = '<?xml version="1.0"?><CTe xmlns="x"><infCte Id="CTe{c}"/></CTe>'
_PROT = '<protCTe versao="4.00"><infProt><nProt>135{n}</nProt></infProt></protCTe>'


def _grava(chave, *, ambiente=emissao.PRODUCAO, cstat="100", numero=1,
           cnpj="11111111111111", quando="2099-01-01T10:00:00", com_xml=True):
    """Insere uma linha em `emissao` direto, sem passar pela SEFAZ."""
    with xml_email._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo, protocolo, xml,"
            " xml_prot) VALUES(%s,'teste',%s,%s,900,%s,%s,%s,%s,'ok','135',"
            "%s,%s)",
            (quando, ambiente, cnpj, numero, chave, "origem-" + chave, cstat,
             _XML.format(c=chave) if com_xml else None,
             _PROT.format(n=numero) if com_xml else None))


def _ligar(destino="xml@sulista.com.br"):
    xml_email.definir("tester", ligado=True, para=destino)


# --- o interruptor ----------------------------------------------------------

def test_nasce_DESLIGADO():
    """Ausencia de decisao nunca significa "manda documento fiscal para fora".
    Banco novo ou backup restaurado cai no desligado."""
    assert xml_email.ativo() is False


def test_valor_estranho_na_config_tambem_e_desligado(monkeypatch):
    """So a string "1" liga. Lixo na configuracao nao vira autorizacao."""
    monkeypatch.setattr(emissao, "config_lida", lambda chave: {"valor": "sim"})
    assert xml_email.ativo() is False


def test_destinatario_padrao_e_a_caixa_da_contabilidade():
    assert xml_email.destinatarios() == "xml@sulista.com.br"
    assert xml_email.DESTINO_PADRAO == "xml@sulista.com.br"


def test_desligado_nao_manda_nada_mesmo_com_fila(monkeypatch):
    _smtp_pronto(monkeypatch)
    xml_email.corte()
    _grava("chave-a")
    r = xml_email.enviar_pendentes("teste")
    assert r["enviados"] == 0 and "DESLIGADO" in r["motivo"]
    assert SMTPFake.ultima is None


def test_endereco_invalido_e_RECUSADO_na_gravacao():
    """Recusar aqui e nao no envio: erro que so aparece na rotina
    desassistida e erro que ninguem ve."""
    with pytest.raises(ValueError, match="inválido"):
        xml_email.definir("tester", para="isso-nao-e-email")


def test_destinatario_vazio_e_recusado():
    with pytest.raises(ValueError, match="destinatário"):
        xml_email.definir("tester", para="   ")


def test_ligar_sem_mexer_no_destino_NAO_apaga_o_destino():
    """Chave ausente = nao mexe. A tela salva o formulario inteiro, e um
    `get(campo, "")` comum apagaria o endereco de quem so ligou a chave."""
    xml_email.definir("tester", para="contabil@sulista.com.br")
    xml_email.definir("tester", ligado=True)
    assert xml_email.destinatarios() == "contabil@sulista.com.br"


# --- o que entra na fila ----------------------------------------------------

def test_HOMOLOGACAO_nunca_entra():
    """Documento de teste nao tem valor fiscal. Escriturar um sai de la por
    retificacao — e pior que nao mandar nenhum."""
    _ligar()
    _grava("homolog", ambiente=emissao.HOMOLOGACAO)
    _grava("producao", ambiente=emissao.PRODUCAO)
    chaves = [x["chave"] for x in xml_email.pendentes()]
    assert chaves == ["producao"]


def test_RECUSADO_nao_entra():
    """cStat diferente de 100 significa que nada foi emitido: nao ha
    documento para escriturar."""
    _ligar()
    _grava("recusado", cstat="229")
    assert xml_email.pendentes() == []


def test_autorizado_SEM_XML_guardado_nao_entra():
    """Sem `xml` e `xml_prot` nao ha cteProc para anexar. Anexar o documento
    sem o protocolo seria mandar um arquivo com cara de valido."""
    _ligar()
    _grava("sem-arquivo", com_xml=False)
    assert xml_email.pendentes() == []


def test_documento_CANCELADO_nao_vai():
    """O cteProc de um CT-e cancelado e um arquivo com cara de valido: quem
    recebe escritura, e desfazer isso e retificacao. Aconteceu em producao — o
    900/3 de 27/08 foi autorizado, virou duplicidade e foi cancelado 14 minutos
    depois. O que a contabilidade precisaria ali e o XML do EVENTO, que e outro
    arquivo e outra conversa."""
    _ligar()
    _grava("cancelada")
    with xml_email._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo)"
            " VALUES('2099-01-02T10:00:00','teste','1','11111111111111',900,1,"
            " 'cancelada','origem-cancelada','CANC:135','evento registrado')")
    assert xml_email.pendentes() == []


def test_o_que_e_ANTERIOR_ao_corte_fica_de_fora():
    """O acumulado que ja existia quando a rotina nasceu nao vai. Despejar
    tudo numa caixa que ninguem avisou faz o primeiro e-mail virar spam — e
    com ele os seguintes, que sao os que importam."""
    _ligar()
    _grava("antigo", numero=1, quando="2000-01-01T10:00:00")
    _grava("novo", numero=2, quando="2099-01-01T10:00:00")
    assert [x["chave"] for x in xml_email.pendentes()] == ["novo"]


def test_o_corte_NAO_se_move_depois_de_fixado():
    """Se acompanhasse a data de hoje, um dia de rotina desligada apagaria da
    fila os documentos daquele dia."""
    primeiro = xml_email.corte()
    xml_email.definir("tester", ligado=True)
    assert xml_email.corte() == primeiro


# --- idempotencia -----------------------------------------------------------

def test_nao_reenvia_o_que_ja_saiu(monkeypatch):
    _smtp_pronto(monkeypatch)
    _ligar()
    _grava("chave-a")
    assert xml_email.enviar_pendentes("teste")["enviados"] == 1
    segundo = xml_email.enviar_pendentes("teste")
    assert segundo["enviados"] == 0 and segundo["pendentes"] == 0
    assert len(SMTPFake.enviadas) == 1


def test_a_mesma_chave_em_duas_linhas_nao_vira_dois_anexos(monkeypatch):
    """O DISTINCT ON da fila.

    Duas linhas AUTORIZADAS com a mesma chave viraram impossiveis quando a
    numeracao ganhou indice unico — mas a chave ainda aparece duas vezes
    sempre que ha cancelamento, porque o evento entra como linha propria na
    mesma chave. A guarda continua valendo e continua barata."""
    _smtp_pronto(monkeypatch)
    _ligar()
    _grava("repetida", numero=1)
    with xml_email._conn() as c:
        c.execute(
            "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente, serie,"
            " numero, chave, chave_origem, cstat, xmotivo)"
            " VALUES('2099-01-03T10:00:00','t','1','11111111111111',900,1,"
            " 'repetida','origem-repetida','CANC:631','duplicidade de evento')")
    # cancelada NAO vai para a contabilidade, e nao vai DUAS vezes
    assert xml_email.pendentes() == []


# --- o anexo ----------------------------------------------------------------

def test_anexo_e_o_cteProc_com_o_protocolo(monkeypatch):
    """O que a contabilidade escritura e o documento MAIS o protocolo. O
    documento sozinho nao prova autorizacao nenhuma."""
    _smtp_pronto(monkeypatch)
    _ligar()
    _grava("chave-a")
    xml_email.enviar_pendentes("teste")

    msg = SMTPFake.enviadas[0]
    anexos = list(msg.iter_attachments())
    assert len(anexos) == 1
    assert anexos[0].get_filename() == "chave-a-procCTe.xml"
    conteudo = anexos[0].get_content()
    if isinstance(conteudo, bytes):
        conteudo = conteudo.decode("utf-8")
    assert "<cteProc" in conteudo and "protCTe" in conteudo


def test_um_XML_por_anexo_e_nao_um_zip(monkeypatch):
    """A caixa `xml@` costuma ser lida por importador automatico, que procura
    anexo .xml. Um .zip chegaria e nao entraria em lugar nenhum."""
    _smtp_pronto(monkeypatch)
    _ligar()
    for i in range(3):
        _grava(f"chave-{i}", numero=i + 1)
    xml_email.enviar_pendentes("teste")

    nomes = [a.get_filename() for a in SMTPFake.enviadas[0].iter_attachments()]
    assert len(nomes) == 3
    assert all(n.endswith(".xml") for n in nomes)


def test_lote_grande_vira_VARIAS_mensagens(monkeypatch):
    """Acima de MAX_ANEXOS a remessa e dividida — e o assunto diz "parte X de
    Y", senao quem recebe tres mensagens no mesmo minuto acha que e a mesma
    repetida."""
    _smtp_pronto(monkeypatch)
    _ligar()
    n = xml_email.MAX_ANEXOS + 2
    for i in range(n):
        _grava(f"chave-{i:03d}", numero=i + 1)
    r = xml_email.enviar_pendentes("teste")

    assert r["enviados"] == n and r["mensagens"] == 2
    assuntos = [m["Subject"] for m in SMTPFake.enviadas]
    assert "parte 1 de 2" in assuntos[0] and "parte 2 de 2" in assuntos[1]


def test_corpo_LISTA_as_chaves_que_vao_anexas(monkeypatch):
    """`correio_envios` guarda o corpo, nao os anexos: e por ele que se
    responde "este XML foi mandado?" sem precisar do arquivo."""
    _smtp_pronto(monkeypatch)
    _ligar()
    _grava("chave-a")
    xml_email.enviar_pendentes("teste")
    assert "chave-a" in SMTPFake.enviadas[0].get_body(("plain",)).get_content()


# --- falha ------------------------------------------------------------------

def test_falha_de_envio_NAO_marca_como_enviado(monkeypatch):
    """O documento volta para a fila na proxima rodada do lote."""
    _ligar()
    _grava("chave-a")

    def explode(*a, **k):
        raise smtplib.SMTPConnectError(421, b"fora do ar")
    cfg.gravar({"host": "smtp.teste.local", "porta": 587,
                "seguranca": "starttls", "usuario": "",
                "remetente": "cortex@sulista.com.br"})
    monkeypatch.setattr(smtplib, "SMTP", explode)

    r = xml_email.enviar_pendentes("teste")
    assert r["ok"] is False and r["enviados"] == 0
    assert [x["chave"] for x in xml_email.pendentes()] == ["chave-a"]


def test_falha_repetida_PARA_no_teto_e_fica_visivel(monkeypatch):
    """Falha permanente nao pode virar retentativa eterna — e nao pode sumir
    da fila em silencio."""
    _ligar()
    _grava("chave-a")

    def explode(*a, **k):
        raise smtplib.SMTPConnectError(421, b"fora do ar")
    cfg.gravar({"host": "smtp.teste.local", "porta": 587,
                "seguranca": "starttls", "usuario": "",
                "remetente": "cortex@sulista.com.br"})
    monkeypatch.setattr(smtplib, "SMTP", explode)

    for _ in range(xml_email.MAX_TENTATIVAS):
        xml_email.enviar_pendentes("teste")

    assert xml_email.pendentes() == []
    parados = xml_email.parados()
    assert len(parados) == 1 and parados[0]["chave"] == "chave-a"
    assert xml_email.estado()["parados"] == 1


def test_reenfileirar_devolve_o_parado_a_fila(monkeypatch):
    _ligar()
    _grava("chave-a")

    def explode(*a, **k):
        raise smtplib.SMTPConnectError(421, b"fora do ar")
    cfg.gravar({"host": "smtp.teste.local", "porta": 587,
                "seguranca": "starttls", "usuario": "",
                "remetente": "cortex@sulista.com.br"})
    monkeypatch.setattr(smtplib, "SMTP", explode)
    for _ in range(xml_email.MAX_TENTATIVAS):
        xml_email.enviar_pendentes("teste")

    assert xml_email.reenfileirar("tester")["reenfileirados"] == 1
    assert [x["chave"] for x in xml_email.pendentes()] == ["chave-a"]


def test_SMTP_nao_configurado_NAO_queima_tentativa():
    """Um campo em branco na configuracao deixaria a fila inteira PARADA em
    cinco rodadas — por um problema que nao e do documento."""
    _ligar()
    _grava("chave-a")
    # nada de `cfg.gravar({"host": ""})`: a config RECUSA host vazio, e com
    # razao. O arquivo do tmp_path simplesmente nao existe — que e o estado
    # real de quem nunca configurou o SMTP.
    assert cfg.configurado() is False

    r = xml_email.enviar_pendentes("teste")
    assert r["ok"] is False and "SMTP" in r["motivo"]
    assert [x["chave"] for x in xml_email.pendentes()] == ["chave-a"]
    assert xml_email.estado()["parados"] == 0


def test_a_primeira_falha_INTERROMPE_as_partes_seguintes(monkeypatch):
    """Servidor fora do ar nao melhora na segunda mensagem: insistir so
    multiplica o mesmo erro e gasta uma tentativa de cada documento."""
    _ligar()
    for i in range(xml_email.MAX_ANEXOS + 2):
        _grava(f"chave-{i:03d}", numero=i + 1)

    def explode(*a, **k):
        raise smtplib.SMTPConnectError(421, b"fora do ar")
    cfg.gravar({"host": "smtp.teste.local", "porta": 587,
                "seguranca": "starttls", "usuario": "",
                "remetente": "cortex@sulista.com.br"})
    monkeypatch.setattr(smtplib, "SMTP", explode)

    r = xml_email.enviar_pendentes("teste")
    assert r["mensagens"] == 1 and "interrompido" in r["motivo"]
    # Todos continuam PENDENTES (falha nao marca como enviado), mas so o
    # primeiro bloco GASTOU tentativa — os dois de tras seguem sem linha
    # nenhuma na trilha, esperando a proxima rodada.
    assert len(xml_email.pendentes()) == xml_email.MAX_ANEXOS + 2
    with xml_email._conn() as c:
        marcados = c.execute("SELECT count(*) n FROM cte_xml_email").fetchone()
    assert marcados["n"] == xml_email.MAX_ANEXOS


def test_ensaio_nao_manda_e_nao_marca(monkeypatch):
    _smtp_pronto(monkeypatch)
    _ligar()
    _grava("chave-a")
    r = xml_email.enviar_pendentes("teste", ensaio=True)
    assert r["enviados"] == 0 and SMTPFake.ultima is None
    assert len(xml_email.pendentes()) == 1


# --- o gancho no lote -------------------------------------------------------

def test_o_lote_de_HOMOLOGACAO_nao_dispara_o_envio(monkeypatch):
    """Producao e so producao — a guarda mora no gancho, alem de na fila."""
    chamou = []
    monkeypatch.setattr(xml_email, "enviar_pendentes",
                        lambda **k: chamou.append(k) or {})
    monkeypatch.setattr(lote.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(lote.cadastro, "mapa", lambda: {})
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: set())

    lote.processar_lote("2026-08-01", "2026-08-27", None, quem="x", limite=5,
                        ambiente=emissao.HOMOLOGACAO)
    assert chamou == []


def test_o_lote_de_PRODUCAO_dispara_mesmo_sem_ter_autorizado_nada(monkeypatch):
    """A fila e "o que ainda nao saiu": gatear por `autorizados` deixaria o
    atrasado da rodada anterior preso ate haver documento novo."""
    chamou = []
    monkeypatch.setattr(xml_email, "enviar_pendentes",
                        lambda **k: chamou.append(k) or {})
    monkeypatch.setattr(lote.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(lote.cadastro, "mapa", lambda: {})
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: set())

    r = lote.processar_lote("2026-08-01", "2026-08-27", None, quem="x",
                            limite=5, ambiente=emissao.PRODUCAO)
    assert len(chamou) == 1 and "xml_email" in r


def test_falha_no_envio_de_XML_NAO_derruba_o_lote(monkeypatch):
    """O documento fiscal ja existe e ja esta autorizado. Perder o retorno do
    lote por causa de um servidor de e-mail transformaria incomodo em
    incidente."""
    def explode(**k):
        raise RuntimeError("smtp explodiu")
    monkeypatch.setattr(xml_email, "enviar_pendentes", explode)
    monkeypatch.setattr(lote.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(lote.cadastro, "mapa", lambda: {})
    monkeypatch.setattr(lote, "_ja_emitidas", lambda ambiente: set())

    r = lote.processar_lote("2026-08-01", "2026-08-27", None, quem="x",
                            limite=5, ambiente=emissao.PRODUCAO)
    assert r["xml_email"]["ok"] is False
    assert "RuntimeError" in r["xml_email"]["motivo"]
