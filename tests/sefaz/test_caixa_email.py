# -*- coding: utf-8 -*-
"""A SEGUNDA PORTA da recolha: o XML que chega por e-mail.

DUBLE COPIA O CORPO REAL, e aqui isso vale em dobro porque sao DOIS formatos
externos: o XML de nota (que a SEFAZ e os ERPs escrevem) e a resposta do
Microsoft Graph. Os dois sao LITERAIS escritos aqui -- montar a resposta do
Graph a partir do codigo que a le faria sabotar o parser sabotar junto o duble,
e o teste seguiria verde.

O QUE ESTE ARQUIVO PROTEGE, em uma frase cada:

  - o filtro da porta aberta: qualquer um escreve para xml@sulista.com.br, e so
    entra o que se declara documento fiscal na RAIZ;
  - "sem protocolo" nao e "so resumo": sao duas ausencias do mesmo XML que
    pedem coisas diferentes de quem le;
  - a identidade e o ARQUIVO (sha256), porque o mesmo anexo chega tres vezes;
  - a mensagem lida fica registrada mesmo sem render documento -- senao ela e
    reaberta para sempre;
  - a EXECUCAO da coleta e o que a Saude mede, e nao a chegada de e-mail.
"""
from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest

from api.sefaz import armazenamento as arm, arquivo, busca, caixa_email

CHAVE = "41260912345678000199550010000012341000012349"
CHAVE2 = "41260912345678000199550010000012341000012350"

# --------------------------------------------------------------- os corpos
#
# O `nfeProc` REAL tem `NFe` + `protNFe`; o `NFe` cru (sem protocolo) e o que
# varios ERPs exportam, e e o caso que a tela tem de saber nomear.

PROC_NFE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
    '<NFe><infNFe Id="NFe%s" versao="4.00">'
    '<ide><cUF>41</cUF><natOp>VENDA</natOp><mod>55</mod><serie>1</serie>'
    '<nNF>1234</nNF><dhEmi>2026-09-05T14:32:00-03:00</dhEmi></ide>'
    '<emit><CNPJ>12345678000199</CNPJ><xNome>METALURGICA EXEMPLO LTDA</xNome></emit>'
    '<dest><CNPJ>98765432000188</CNPJ><xNome>CLIENTE QUE NAO E A SULISTA</xNome></dest>'
    '<total><ICMSTot><vNF>4821.55</vNF></ICMSTot></total>'
    '</infNFe></NFe>'
    '<protNFe versao="4.00"><infProt><chNFe>%s</chNFe>'
    '<nProt>141260000123456</nProt><cStat>100</cStat>'
    '<xMotivo>Autorizado o uso da NF-e</xMotivo></infProt></protNFe>'
    '</nfeProc>') % (CHAVE, CHAVE)

NFE_CRUA = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<NFe xmlns="http://www.portalfiscal.inf.br/nfe">'
    '<infNFe Id="NFe%s" versao="4.00">'
    '<ide><nNF>1234</nNF><dhEmi>2026-09-05T14:32:00-03:00</dhEmi></ide>'
    '<emit><CNPJ>12345678000199</CNPJ><xNome>METALURGICA EXEMPLO LTDA</xNome></emit>'
    '<dest><CNPJ>98765432000188</CNPJ><xNome>CLIENTE</xNome></dest>'
    '<total><ICMSTot><vNF>4821.55</vNF></ICMSTot></total>'
    '</infNFe></NFe>') % CHAVE

CANCELAMENTO = (
    '<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">'
    '<evento><infEvento><chNFe>%s</chNFe><tpEvento>110111</tpEvento>'
    '<dhEvento>2026-09-06T09:00:00-03:00</dhEvento>'
    '<detEvento><descEvento>Cancelamento</descEvento></detEvento>'
    '</infEvento></evento>'
    '<retEvento><infEvento><cStat>135</cStat>'
    '<xEvento>Cancelamento registrado</xEvento></infEvento></retEvento>'
    '</procEventoNFe>') % CHAVE


@pytest.fixture
def esquema(esquema_pg, monkeypatch):
    """Schema descartavel. NENHUM teste escreve no de producao."""
    monkeypatch.setattr(arm, "ESQUEMA", esquema_pg)
    arm._TEM_ARQUIVO.pop(esquema_pg, None)
    return esquema_pg


# ======================================================= o filtro da porta

def test_a_RAIZ_decide_o_que_e_documento_fiscal():
    """O endereco e publico: qualquer um escreve para ele.

    Sem este filtro a tabela enche de assinatura de e-mail em HTML, boleto em
    XML e resposta automatica de ferias -- e a lista de documentos da operacao
    vira caixa de entrada.
    """
    assert arquivo.esquema_do_xml(PROC_NFE) == "procNFe_v4.00"
    assert arquivo.esquema_do_xml(NFE_CRUA) == "NFe"
    assert arquivo.esquema_do_xml(CANCELAMENTO) == "procEventoNFe_v1.00"
    for lixo in ('<html><body>assinatura</body></html>',
                 '<boleto><valor>10</valor></boleto>',
                 ''):
        with pytest.raises(arquivo.NaoEDocumento):
            arquivo.esquema_do_xml(lixo)


def test_a_raiz_ignora_declaracao_comentario_e_namespace():
    """`<?xml ...?>`, comentario e prefixo de namespace vem antes da raiz no
    arquivo real -- e o primeiro `<` nao e a raiz."""
    assert arquivo.raiz('<?xml version="1.0"?>\n<!-- gerado pelo ERP -->\n'
                        '<nfe:nfeProc xmlns:nfe="x"><a/></nfe:nfeProc>') == "nfeProc"


def test_SEM_PROTOCOLO_nao_e_documento_completo():
    """A DIFERENCA QUE A TELA PRECISA DIZER.

    `<NFe>` sem `<protNFe>` e o documento sem a PROVA de que a SEFAZ o aceitou.
    Ele parece uma nota inteira -- tem emitente, itens, valor --, e a guarda de
    cinco anos e da prova. Marca-lo como completo faria a casa achar que
    cumpriu a obrigacao com um arquivo que nao a cumpre.
    """
    completo = arquivo.ler(PROC_NFE)
    cru = arquivo.ler(NFE_CRUA)
    assert completo["completo"] is True
    assert cru["completo"] is False
    assert cru["tipo"] == "nfe" and cru["chave"] == CHAVE

    # E O CASO QUE A RAIZ NAO RESOLVE, que e a razao de a conferencia existir:
    # um `<nfeProc>` SEM o `<protNFe>` dentro. Pela raiz ele se declara
    # documento autorizado; pelo conteudo, nao ha autorizacao nenhuma. Isso
    # acontece com arquivo montado a mao e com ERP que embrulha a nota antes de
    # ela ser autorizada.
    #
    # ESTE PEDACO DO GUARD NASCEU DE UMA SABOTAGEM QUE FICOU VERDE: apagar a
    # linha que confere o protocolo nao quebrava nada, porque o `<NFe>` cru ja
    # sai incompleto da tabela de esquemas. O teste media a tabela, nao a
    # conferencia.
    sem_prot = PROC_NFE[:PROC_NFE.index("<protNFe")] + "</nfeProc>"
    assert arquivo.raiz(sem_prot) == "nfeProc"
    assert arquivo.ler(sem_prot)["completo"] is False, (
        "um nfeProc sem protNFe passou por documento autorizado: a raiz diz "
        "'proc', e a prova de autorizacao nao esta la")


def test_o_destinatario_sai_do_BLOCO_dest_e_nao_do_segundo_CNPJ():
    """`<CNPJ>` aparece meia duzia de vezes num XML de NF-e (emitente,
    destinatario, transportador, autorizados) e a ordem nao e garantida entre
    versoes. Ler "o segundo" funciona ate a nota que vem sem transportador."""
    d = arquivo.ler(PROC_NFE)
    assert d["emitente"] == "12345678000199"
    assert d["destinatario"] == "98765432000188"


# ============================================== a identidade e o ARQUIVO

def test_o_MESMO_xml_em_outra_codificacao_tem_o_MESMO_sha():
    """O mesmo anexo chega tres vezes por construcao: o fornecedor manda, o
    cliente reencaminha, alguem responde a todos. E chega em UTF-8 e em
    latin-1, porque cada ERP exporta de um jeito.

    O sha e do TEXTO, e nao dos bytes recebidos, exatamente por isso -- senao
    o mesmo documento em duas codificacoes seriam duas linhas.
    """
    xml = PROC_NFE.replace("METALURGICA EXEMPLO", "METALURGICA JOSE ANTONIO")
    a = arquivo.do_arquivo("a.xml", xml.encode("utf-8"))[0][0]
    b = arquivo.do_arquivo("b.xml", ("  " + xml + "\n").encode("latin-1"))[0][0]
    assert a["sha256"] == b["sha256"]


def test_gravar_duas_vezes_nao_duplica(esquema):
    d = arquivo.ler(PROC_NFE)
    assert arquivo.guardar(d, origem="email", remetente="a@x.com") == "novo"
    assert arquivo.guardar(d, origem="email", remetente="b@y.com") == "repetido"
    assert len(arm.documentos(limite=10)) == 1


def test_dois_arquivos_DIFERENTES_da_mesma_chave_coexistem(esquema):
    """A nota e o CANCELAMENTO dela tem a mesma chave e sao dois documentos.

    Fundir pela chave apagaria um deles -- e o que a lei manda guardar por
    cinco anos e o arquivo, nao a linha de tabela.
    """
    arquivo.guardar(arquivo.ler(PROC_NFE), origem="email")
    arquivo.guardar(arquivo.ler(CANCELAMENTO), origem="email")
    linhas = arm.documentos(limite=10)
    assert {l["tipo"] for l in linhas} == {"nfe", "evento"}
    # e o evento faz a nota aparecer CANCELADA, venha ele por onde vier
    nota = [l for l in linhas if l["tipo"] == "nfe"][0]
    assert nota["cancelada"] is True


def test_XML_VAZIO_nao_se_guarda(esquema):
    """A licao dos 510 documentos vazios, do outro lado da casa: documento sem
    XML nao e documento, e a ausencia dele com aparencia de presenca."""
    with pytest.raises(ValueError):
        arquivo.guardar({"xml": "   ", "sha256": "x" * 64}, origem="email")


# ================================================================= o .zip

def _zip(**arquivos) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome.replace("__", "."), conteudo)
    return buf.getvalue()


def test_o_zip_entrega_os_xml_e_NOMEIA_o_que_ignorou():
    """Numa mensagem com quinze notas e um PDF, o PDF sai na lista de
    ignorados e as quinze entram. E a lista diz QUAL nao serviu: "nao deu
    certo" sem dizer o que veio faz a pessoa tentar o mesmo arquivo de novo.
    """
    docs, fora = arquivo.do_arquivo(
        "lote.zip", _zip(nota1__xml=PROC_NFE,
                         nota2__xml=PROC_NFE.replace(CHAVE, CHAVE2),
                         danfe__pdf="%PDF-1.4"))
    assert len(docs) == 2
    assert len(fora) == 1 and "danfe.pdf" in fora[0]


def test_zip_com_arquivo_demais_e_RECUSADO(monkeypatch):
    """Um `.zip` de 40 KB pode declarar milhoes de arquivos."""
    monkeypatch.setattr(arquivo, "MAX_NO_ZIP", 2)
    docs, fora = arquivo.do_arquivo(
        "bomba.zip", _zip(a__xml=PROC_NFE, b__xml=PROC_NFE, c__xml=PROC_NFE))
    assert docs == [] and "teto" in fora[0]


def test_zip_que_se_expande_demais_e_RECUSADO_ANTES_de_abrir(monkeypatch):
    """Conferir DEPOIS de extrair e conferir com o disco ja cheio."""
    monkeypatch.setattr(arquivo, "MAX_ZIP_ABERTO", 10)
    docs, fora = arquivo.do_arquivo("bomba.zip", _zip(a__xml=PROC_NFE))
    assert docs == [] and "descomprimido" in fora[0]


# ====================================================== as duas portas juntas

def test_a_lista_une_as_duas_portas_e_cada_linha_diz_de_onde_veio(esquema):
    arm.abrir_caixa("76104397000123", "FIL MTZ")
    arm.gravar("76104397000123", {
        "nsu": "000000000000001", "esquema": "procNFe_v4.00", "tipo": "nfe",
        "chave": CHAVE2, "xml": PROC_NFE.replace(CHAVE, CHAVE2),
        "completo": True, "emitente_nome": "DA SEFAZ"})
    arquivo.guardar(arquivo.ler(PROC_NFE), origem="email",
                    remetente="fulano@cliente.com")

    linhas = arm.documentos(limite=10)
    assert {l["origem"] for l in linhas} == {"sefaz", "email"}
    email = [l for l in linhas if l["origem"] == "email"][0]
    assert email["remetente"] == "fulano@cliente.com"
    assert email["nsu"] is None and email["sha256"]
    # e o filtro separa as duas
    assert len(arm.documentos(origem="email")) == 1
    assert len(arm.documentos(origem="sefaz")) == 1


def test_filtrar_por_FILIAL_esconde_a_porta_do_email_e_isso_e_verdade(esquema):
    """Nao e efeito colateral, e uma afirmacao: o documento que chega por
    e-mail chega porque a Sulista NAO e parte nele -- ele nao pertence a caixa
    de filial nenhuma, e dizer que pertence seria inventar um vinculo.

    O guard existe para que a decisao seja DELIBERADA: quem mudar isso um dia
    vai ter de apagar este teste, e ai le o porque.
    """
    arm.abrir_caixa("76104397000123", "FIL MTZ")
    arquivo.guardar(arquivo.ler(PROC_NFE), origem="email")
    assert len(arm.documentos()) == 1
    assert arm.documentos("76104397000123") == []


def test_a_busca_por_chave_acha_o_que_veio_por_email(esquema):
    """E aqui que a segunda porta paga o que custou: a nota que a SEFAZ nunca
    vai entregar responde na busca, e quem digitou a chave nao precisa saber
    por onde ela entrou."""
    arquivo.guardar(arquivo.ler(PROC_NFE), origem="email")
    achado = busca.local(CHAVE)
    assert achado and achado["origem"] == "email" and achado["completo"]


def test_entre_duas_linhas_da_mesma_nota_vence_a_COMPLETA(esquema):
    """A pessoa manda o `<NFe>` cru antes de a nota ser autorizada e o
    `<nfeProc>` depois. Os dois ficam guardados; quem procura recebe o que
    serve."""
    arquivo.guardar(arquivo.ler(NFE_CRUA), origem="email")
    arquivo.guardar(arquivo.ler(PROC_NFE), origem="email")
    assert busca.local(CHAVE)["completo"] is True


def test_o_resumo_conta_as_portas_SEPARADAS(esquema):
    """`pendentes` significa "a SEFAZ ainda nao entregou o XML completo, falta
    a ciencia". Um arquivo de e-mail sem protocolo NAO e isso -- somar os dois
    faria o KPI que decide a obrigacao de guarda dizer um numero que nao
    decide nada."""
    arm.abrir_caixa("76104397000123", "FIL MTZ")
    arm.gravar("76104397000123", {
        "nsu": "000000000000001", "esquema": "resNFe_v1.01", "tipo": "nfe",
        "chave": CHAVE2, "xml": "<resNFe><chNFe>%s</chNFe></resNFe>" % CHAVE2,
        "completo": False})
    arquivo.guardar(arquivo.ler(NFE_CRUA), origem="email")
    r = arm.resumo()
    assert r["total"] == 1 and r["pendentes"] == 1     # so a caixa da SEFAZ
    # E A CONTA DE FORA VEM POR ORIGEM, nao num numero so: com o acervo do ERP
    # dentro da mesma tabela, um campo unico chamado "email" faria a tela dizer
    # "189 mil por e-mail" -- verdadeiro na soma e falso na frase.
    assert r["fora_da_sefaz"] == 1
    assert r["por_origem"] == {"email": 1}
    assert r["sem_protocolo"] == 1


def test_o_pacote_zip_leva_as_DUAS_portas(esquema):
    """Quem baixa o mes para a contabilidade quer o mes inteiro."""
    arquivo.guardar(arquivo.ler(PROC_NFE), origem="email")
    docs = arm.para_pacote(de="2026-09-01", ate="2026-09-30")
    assert [d["origem"] for d in docs] == ["email"]
    assert docs[0]["chave"] == CHAVE and docs[0]["xml"]


def test_SEM_A_MIGRATION_a_tela_continua_de_pe(esquema, monkeypatch):
    """O `autodeploy.ps1` NAO roda `migrar_schema.py`.

    Entre o codigo chegar em producao e alguem aplicar a migration ha uma
    janela de minutos ou de dias -- e nela toda consulta que citasse
    `dfe_arquivo` derrubaria a tela INTEIRA, inclusive a metade que nao tem
    nada a ver com e-mail. Uma tela que ja funcionava nao pode cair por causa
    de uma porta nova que ainda nao abriu.
    """
    arm.abrir_caixa("76104397000123", "FIL MTZ")
    arm.gravar("76104397000123", {
        "nsu": "000000000000001", "esquema": "procNFe_v4.00", "tipo": "nfe",
        "chave": CHAVE, "xml": PROC_NFE, "completo": True})
    with arm.pglocal.get_conn(esquema) as c, c.cursor() as cur:
        cur.execute("DROP TABLE dfe_arquivo")
    arm._TEM_ARQUIVO.pop(esquema, None)

    assert arm.tem_tabela_arquivo() is False
    linhas = arm.documentos(limite=10)
    assert len(linhas) == 1 and linhas[0]["origem"] == "sefaz"
    assert arm.resumo()["total"] == 1
    assert busca.local(CHAVE)["origem"] == "sefaz"
    # sem recorte de data: a linha da SEFAZ deste teste nao tem `emitido_em`,
    # e o que se afirma aqui e que o PACOTE nao quebra sem a tabela nova
    assert len(arm.para_pacote()) == 1


# ==================================================== a paginacao

def _muitos(n, esquema):
    """`n` documentos com emissoes e chaves distintas."""
    for i in range(n):
        chave = "4126091234567800019955001000001234100001%04d" % i
        xml = (PROC_NFE.replace(CHAVE, chave)
               .replace("2026-09-05T14:32:00-03:00",
                        "2026-09-%02dT14:32:00-03:00" % (1 + i % 28)))
        arquivo.guardar(arquivo.ler(xml), origem="email")


def test_contar_usa_O_MESMO_filtro_da_pagina(esquema):
    """O DENOMINADOR TEM DE SER DO MESMO RECORTE QUE A PAGINA.

    Se `contar()` e `documentos()` montarem o WHERE cada um por conta, eles
    divergem no primeiro filtro novo -- e divergem em SILENCIO, porque cada um
    continua certo sozinho. O sintoma seria o rodape dizendo "1 de 12" com a
    pagina 12 vazia, e ninguem sabendo em qual dos dois acreditar.
    """
    _muitos(12, esquema)
    arquivo.guardar(arquivo.ler(CANCELAMENTO), origem="email")   # um evento

    assert arm.contar() == 13
    assert arm.contar(tipo="nfe") == 12
    assert arm.contar(tipo="evento") == 1
    assert arm.contar(origem="upload") == 0
    # e o total bate com o que a lista devolve sem recorte
    assert arm.contar(tipo="nfe") == len(arm.documentos(tipo="nfe", limite=100))


def test_as_paginas_NAO_repetem_nem_perdem_documento(esquema):
    """Percorrer as paginas devolve cada documento UMA vez."""
    _muitos(25, esquema)
    vistos, pagina, tam = [], 0, 10
    while True:
        lote = arm.documentos(limite=tam, pulando=pagina * tam)
        if not lote:
            break
        vistos += [d["sha256"] or (d["cnpj"] + d["nsu"]) for d in lote]
        pagina += 1
        assert pagina < 10, "laco sem fim"

    assert len(vistos) == 25
    assert len(set(vistos)) == 25, "documento repetido entre paginas"


def test_a_ordenacao_da_lista_e_TOTAL(esquema):
    """PAGINAR SO E SEGURO SE A ORDEM FOR TOTAL -- e a chave de acesso NAO
    torna a ordem total.

    ESTE GUARD NASCEU DE UMA SABOTAGEM QUE FICOU VERDE. Eu tinha escrito
    `ORDER BY emitido_em, recebido_em, chave` achando que a chave desempatava,
    e o teste de percorrer as paginas passou mesmo com o desempate REMOVIDO --
    porque no cenario dele as emissoes ja eram todas distintas.

    A chave nao desempata porque ela SE REPETE por construcao: a nota, o resumo
    dela e o cancelamento dela tem a mesma chave de acesso e sao tres linhas.
    Aqui o cenario e o real do import em lote -- emissao e recebimento iguais --
    e o que se afirma e que ainda assim existe um identificador que distingue
    cada linha das outras.
    """
    # a nota, o resumo (sem protocolo) e o cancelamento: TRES linhas, UMA chave
    for xml in (PROC_NFE, NFE_CRUA, CANCELAMENTO):
        arquivo.guardar(arquivo.ler(xml), origem="email")

    linhas = arm.documentos(limite=100)
    assert len({l["chave"] for l in linhas}) == 1, (
        "o cenario deste guard exige as tres linhas com a MESMA chave")
    assert len(linhas) == 3

    # e o identificador de ordenacao distingue as tres
    ident = [l["sha256"] or ((l["cnpj"] or "") + (l["nsu"] or "")) for l in linhas]
    assert len(set(ident)) == 3, (
        "duas linhas sem identificador distinto: paginar sobre elas pode "
        "repetir uma e perder a outra, sem erro nenhum")

    # a prova de que ele ESTA na ordenacao: com emissao e recebimento
    # empatados, a lista sai na ordem decrescente do identificador
    with arm.pglocal.get_conn(esquema) as c, c.cursor() as cur:
        cur.execute("UPDATE dfe_arquivo SET emitido_em = %s, recebido_em = %s",
                    ("2026-09-05T14:32:00-03:00", "2026-09-08T12:00:00-03:00"))
    linhas = arm.documentos(limite=100)
    ident = [l["sha256"] for l in linhas]
    assert ident == sorted(ident, reverse=True), (
        "com emissao e recebimento empatados a ordem ficou indefinida: falta o "
        "desempate por identificador unico no ORDER BY")


def test_pular_alem_do_fim_devolve_lista_vazia_e_nao_erro(esquema):
    """Quem clicar em "ultima pagina" e depois filtrar cai aqui."""
    _muitos(3, esquema)
    assert arm.documentos(limite=10, pulando=999) == []


# ================================================ a folha e a porta de origem

def test_a_folha_recusa_o_SEM_PROTOCOLO_falando_a_lingua_da_porta():
    """Os dois casos sao "falta o XML completo" e sao coisas diferentes: da
    SEFAZ falta a MANIFESTACAO (e ha o que fazer sobre isso); do e-mail falta o
    PROTOCOLO no arquivo que a pessoa mandou (e o que se faz e pedir o arquivo
    certo a ela).

    Dar a explicacao da caixa da SEFAZ para um arquivo de e-mail manda alguem
    procurar uma manifestacao que nao existe.
    """
    from api.sefaz import impressao
    with pytest.raises(impressao.NaoImprimivel) as e1:
        impressao.gerar({"tipo": "nfe", "completo": False, "origem": "email"},
                        NFE_CRUA)
    assert "protocolo" in str(e1.value) and "ciência" not in str(e1.value)

    with pytest.raises(impressao.NaoImprimivel) as e2:
        impressao.gerar({"tipo": "nfe", "completo": False, "origem": "sefaz"},
                        "<resNFe/>")
    assert "ciência" in str(e2.value)


# ============================================ o Microsoft Graph, com duble
#
# A RESPOSTA DO GRAPH E LITERAL, copiada da forma real: `value` + `@odata.type`
# + `contentBytes` em base64, `from.emailAddress.address`, `isInline`. Derivar
# o duble do codigo que o le testaria o duble.

def _graph(mensagens, anexos_por_id, *, status_token=200):
    """Um `http` de mentira que responde como o Graph responde."""
    chamadas = []

    def http(url, headers, timeout=60, dados=None):
        chamadas.append(url)
        if "login.microsoftonline.com" in url:
            if status_token != 200:
                return status_token, b'{"error":"invalid_client",' \
                                     b'"error_description":"segredo AQUI"}'
            return 200, json.dumps({"access_token": "T0KEN",
                                    "expires_in": 3600}).encode()
        if "/attachments" in url:
            mid = url.split("/messages/")[1].split("/")[0]
            return 200, json.dumps({"value": anexos_por_id.get(mid, [])}).encode()
        if "/messages" in url:
            return 200, json.dumps({"value": mensagens}).encode()
        return 404, b"{}"

    http.chamadas = chamadas
    return http


def _anexo(nome, conteudo: str, **kw):
    d = {"@odata.type": "#microsoft.graph.fileAttachment", "name": nome,
         "contentBytes": base64.b64encode(conteudo.encode("utf-8")).decode(),
         "size": len(conteudo)}
    d.update(kw)
    return d


MSG = [{"id": "AAA1", "subject": "XML da carga 4821",
        "receivedDateTime": "2026-09-08T11:02:00Z",
        "from": {"emailAddress": {"address": "expedicao@cliente.com.br"}},
        "hasAttachments": True}]


@pytest.fixture
def configurada(monkeypatch):
    monkeypatch.setattr(caixa_email, "_cred", lambda nome: {
        "XMLMAIL_TENANT_ID": "tenant-guid",
        "XMLMAIL_CLIENT_ID": "app-guid",
        "XMLMAIL_CLIENT_SECRET": "segredo",
        "XMLMAIL_CAIXA": "xml@sulista.com.br"}.get(nome, ""))


def test_sem_credencial_NAO_E_FALHA_e_diz_o_que_falta(monkeypatch):
    """Instalacao incompleta e `info`, nunca alarme -- a regra da casa em toda
    integracao. E a lista do que falta usa o nome que aparece na TELA."""
    monkeypatch.setattr(caixa_email, "_cred", lambda nome: "")
    assert caixa_email.configurado() is False
    assert caixa_email.falta() == ["ID do tenant", "ID do aplicativo",
                                   "segredo do aplicativo", "endereço da caixa"]
    with pytest.raises(caixa_email.NaoConfigurada):
        caixa_email.Cliente(http=lambda *a, **k: (200, b"{}"))


def test_a_coleta_guarda_o_anexo_e_registra_a_mensagem(esquema, configurada):
    http = _graph(MSG, {"AAA1": [_anexo("nota.xml", PROC_NFE)]})
    placar = caixa_email.coletar(http=http)
    assert placar["mensagens"] == 1 and placar["novas"] == 1
    assert placar["documentos"] == 1 and placar["ignorados"] == 0

    linhas = arm.documentos(limite=10)
    assert len(linhas) == 1
    assert linhas[0]["origem"] == "email"
    assert linhas[0]["remetente"] == "expedicao@cliente.com.br"

    # e o Bearer foi pedido ANTES da listagem
    assert "login.microsoftonline.com" in http.chamadas[0]


def test_a_segunda_coleta_NAO_reprocessa_a_mesma_mensagem(esquema, configurada):
    """Idempotente nos dois niveis: a mensagem e pulada pelo id, e o arquivo
    repetido cairia no sha. Rodar duas vezes seguidas e o que acontece quando
    alguem aperta "Coletar agora" enquanto a tarefa roda."""
    anexos = {"AAA1": [_anexo("nota.xml", PROC_NFE)]}
    caixa_email.coletar(http=_graph(MSG, anexos))
    http2 = _graph(MSG, anexos)
    placar = caixa_email.coletar(http=http2)
    assert placar["novas"] == 0 and placar["documentos"] == 0
    assert len(arm.documentos(limite=10)) == 1
    # nem chegou a pedir os anexos de novo
    assert not any("/attachments" in u for u in http2.chamadas)


def test_mensagem_SEM_xml_fica_registrada(esquema, configurada):
    """O caso que reabriria a caixa para sempre: uma mensagem que so tinha o
    PDF do DANFE nao deixa rastro em `dfe_arquivo` -- se ela nao ficasse
    registrada, toda coleta a leria de novo.

    E ela e a lista que alguem precisa olhar: chegou e nao virou documento.
    """
    http = _graph(MSG, {"AAA1": [_anexo("danfe.pdf", "%PDF-1.4 nao e xml")]})
    placar = caixa_email.coletar(http=http)
    assert placar["documentos"] == 0 and placar["ignorados"] == 1
    ultimas = caixa_email.ultimas()
    assert len(ultimas) == 1
    assert ultimas[0]["aproveitados"] == 0 and ultimas[0]["ignorados"] == 1
    assert caixa_email.estado()["vazias"] == 1
    # e a segunda passada nao a abre de novo
    assert caixa_email.coletar(http=_graph(MSG, {}))["novas"] == 0


def test_imagem_EMBUTIDA_da_assinatura_nao_vira_ignorado(esquema, configurada):
    """Toda mensagem traz dois ou tres PNG da assinatura de quem mandou. Sem o
    filtro de `isInline`, a lista que serve para alguem olhar vira ruido."""
    http = _graph(MSG, {"AAA1": [_anexo("logo.png", "png", isInline=True),
                                 _anexo("nota.xml", PROC_NFE)]})
    placar = caixa_email.coletar(http=http)
    assert placar["documentos"] == 1 and placar["ignorados"] == 0


def test_a_EXECUCAO_fica_marcada_mesmo_sem_mensagem_nenhuma(esquema, configurada):
    """A diferenca entre "a coleta rodou" e "chegou e-mail".

    Numa semana em que ninguem manda XML a caixa fica vazia, e um cartao que
    medisse a mensagem mais recente ficaria VERMELHO acusando uma rotina que
    rodou de meia em meia hora sem falha. Alarme que acende sem haver problema
    ensina a ignorar alarme.
    """
    caixa_email.coletar(http=_graph([], {}))
    e = caixa_email.estado()
    assert e["ultima_coleta"] and e["ultimo_sucesso"]
    assert e["ultima_mensagem"] is None
    assert e["ultimo_erro"] is None


def test_403_do_Graph_nomeia_a_POLITICA_de_acesso(esquema, configurada):
    """`Mail.Read` de aplicacao alcanca TODAS as caixas do tenant; a
    `ApplicationAccessPolicy` limita a esta. Quando ela existe e nao inclui a
    caixa, o Graph responde 403 -- e "403" sozinho manda procurar no lugar
    errado."""
    def http(url, headers, timeout=60, dados=None):
        if "login.microsoftonline.com" in url:
            return 200, b'{"access_token":"T","expires_in":3600}'
        return 403, b'{"error":{"code":"ErrorAccessDenied"}}'

    with pytest.raises(caixa_email.Indisponivel) as exc:
        caixa_email.coletar(http=http)
    assert "ApplicationAccessPolicy" in str(exc.value)
    # e a falha fica gravada: sem isso a Saude acharia que a rotina nem rodou
    e = caixa_email.estado()
    assert e["ultimo_erro"] and e["ultimo_sucesso"] is None


def test_a_recusa_do_token_NAO_ecoa_o_corpo(esquema, configurada):
    """Numa troca de credencial o endpoint de token devolve pedacos do que foi
    enviado -- e o segredo do aplicativo estaria dentro."""
    with pytest.raises(caixa_email.Indisponivel) as exc:
        caixa_email.coletar(http=_graph([], {}, status_token=401))
    assert "segredo AQUI" not in str(exc.value)
    assert "401" in str(exc.value)


def test_a_listagem_pede_so_o_que_TEM_ANEXO_e_da_janela(esquema, configurada):
    """Mensagem sem anexo nao tem XML nenhum, e pedir a caixa inteira para
    filtrar do lado de ca e trazer a caixa inteira pela rede."""
    http = _graph([], {})
    caixa_email.coletar(dias=7, http=http)
    listagem = [u for u in http.chamadas if "/messages" in u][0]
    assert "hasAttachments+eq+true" in listagem or "hasAttachments eq true" in listagem
    assert "receivedDateTime+ge" in listagem or "receivedDateTime ge" in listagem
