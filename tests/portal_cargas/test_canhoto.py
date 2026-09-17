# -*- coding: utf-8 -*-
"""O canhoto do CT-e: cofre, Drive e a recusa legivel.

Nada aqui vai a rede nem ao banco: `urlopen`, `db.query` e o cofre entram por
substituicao. O que se segura:

- SEM CREDENCIAL NAO E FALHA, e a frase diz onde configurar;
- o token vem do modo configurado (conta de servico ou OAuth), fica guardado
  ate perto de expirar, e o SEGREDO nunca sai numa mensagem de erro;
- o arquivo que o ERP guardou no proprio banco NAO vai ao Drive;
- a autorizacao do documento vale para o canhoto — chave de outro cliente e
  404, e o Drive nem chega a ser consultado.
"""
from __future__ import annotations

import json
import types
from types import SimpleNamespace

import pytest

from api.portal_cargas import canhoto as c
from api.portal_cargas import documentos as d

CHAVE = "3" * 44
RAIZ = "11222333"


@pytest.fixture(autouse=True)
def _limpa_token():
    c._TOKEN.update({"valor": "", "expira": 0.0})
    yield
    c._TOKEN.update({"valor": "", "expira": 0.0})


def _cofre(monkeypatch, valores: dict):
    monkeypatch.setattr(c, "ler", lambda nome: valores.get(nome))


# ------------------------------------------------------------------ o cofre
def test_sem_credencial_nao_e_falha_e_a_frase_diz_ONDE_configurar(monkeypatch):
    _cofre(monkeypatch, {})
    assert c.configurado() is False and c.modo() == ""
    falta = c.o_que_falta()
    assert "Integrações › Canhotos" in falta and "conta de serviço" in falta


def test_os_DOIS_modos_sao_reconhecidos(monkeypatch):
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CONTA_SERVICO": '{"client_email":"x"}'})
    assert c.modo() == "conta_servico"
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CLIENT_ID": "id",
                         "CANHOTO_DRIVE_CLIENT_SECRET": "seg",
                         "CANHOTO_DRIVE_REFRESH_TOKEN": "ref"})
    assert c.modo() == "oauth"


def test_oauth_incompleto_NAO_conta_como_configurado(monkeypatch):
    """Meia credencial ligaria o botao para uma chamada que sempre falha."""
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CLIENT_ID": "id",
                         "CANHOTO_DRIVE_CLIENT_SECRET": "seg"})
    assert c.modo() == "" and c.configurado() is False


def test_o_campo_da_credencial_EXISTE_no_cofre_e_o_cartao_esta_declarado():
    """A tela de Integracoes so mostra o que esta no catalogo — foi por faltar
    aqui que o codigo mestre do app do motorista ficou sem porta de entrada."""
    from api import credenciais, integracoes
    servico = [s for s in credenciais.SERVICOS if s["chave"] == "canhoto"]
    assert servico, "o cartao 'canhoto' nao esta no cofre"
    campos = [ca for m in servico[0]["modos"] for ca in m["campos"]]
    assert "CANHOTO_DRIVE_CONTA_SERVICO" in campos
    assert all(ca in credenciais.CAMPOS for ca in campos)
    assert credenciais.CAMPOS["CANHOTO_DRIVE_CONTA_SERVICO"]["segredo"] is True
    assert credenciais.CAMPOS["CANHOTO_DRIVE_CLIENT_ID"]["segredo"] is False
    assert "canhoto" in integracoes.SOB_DEMANDA


# ------------------------------------------------------------------ o token
def test_o_token_do_OAUTH_vem_do_refresh_e_fica_guardado(monkeypatch):
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CLIENT_ID": "id",
                         "CANHOTO_DRIVE_CLIENT_SECRET": "seg",
                         "CANHOTO_DRIVE_REFRESH_TOKEN": "ref"})
    chamadas = []
    monkeypatch.setattr(c, "_post_token",
                        lambda dados: chamadas.append(dados) or
                        {"access_token": "tok", "expires_in": 3600})
    assert c._token() == "tok"
    assert c._token() == "tok"
    assert len(chamadas) == 1, "pediu token duas vezes para a mesma janela"
    assert chamadas[0]["grant_type"] == "refresh_token"


def test_token_perto_de_expirar_e_RENOVADO(monkeypatch):
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CLIENT_ID": "id",
                         "CANHOTO_DRIVE_CLIENT_SECRET": "seg",
                         "CANHOTO_DRIVE_REFRESH_TOKEN": "ref"})
    monkeypatch.setattr(c, "_post_token",
                        lambda dados: {"access_token": "novo", "expires_in": 3600})
    c._TOKEN.update({"valor": "velho", "expira": c.time.time() + 30})
    assert c._token() == "novo"


def test_conta_de_servico_invalida_RECUSA_sem_derrubar(monkeypatch):
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CONTA_SERVICO": "nao é json"})
    with pytest.raises(c.SemCredencial, match="JSON"):
        c._token()


def test_a_recusa_do_Google_NAO_leva_o_segredo(monkeypatch):
    """A mensagem vai para a tela do cliente: ela diz o motivo do Google e o
    caminho de conserto, nunca o corpo da requisicao (que leva o segredo)."""
    _cofre(monkeypatch, {"CANHOTO_DRIVE_CLIENT_ID": "id",
                         "CANHOTO_DRIVE_CLIENT_SECRET": "segredo-secretissimo",
                         "CANHOTO_DRIVE_REFRESH_TOKEN": "ref-secreto"})
    import urllib.error

    def explode(req, timeout=None, context=None):
        raise urllib.error.HTTPError(
            c.URL_TOKEN, 400, "Bad Request", {},
            SimpleNamespace(read=lambda: json.dumps({"error": "invalid_grant"}).encode()))
    monkeypatch.setattr(c.urllib.request, "urlopen", explode)
    with pytest.raises(c.DriveIndisponivel) as exc:
        c._token()
    texto = str(exc.value)
    assert "invalid_grant" in texto and "Integrações" in texto
    assert "segredo-secretissimo" not in texto and "ref-secreto" not in texto


# ------------------------------------------------------------------ o Drive
def test_a_chamada_ao_drive_leva_o_token_e_pede_o_CONTEUDO(monkeypatch):
    vistos = {}

    def urlopen(req, timeout=None, context=None):
        vistos["url"] = req.full_url
        vistos["auth"] = req.get_header("Authorization")
        class Resp:
            def read(self):
                return b"%PDF-1.4"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return Resp()
    monkeypatch.setattr(c, "_token", lambda: "tok")
    monkeypatch.setattr(c.urllib.request, "urlopen", urlopen)
    assert c.baixar_do_drive("1AbC") == b"%PDF-1.4"
    assert vistos["auth"] == "Bearer tok"
    assert "alt=media" in vistos["url"] and "supportsAllDrives=true" in vistos["url"]
    assert vistos["url"].endswith("files/1AbC?alt=media&supportsAllDrives=true")


def test_drive_sem_permissao_explica_o_COMPARTILHAMENTO(monkeypatch):
    import urllib.error
    monkeypatch.setattr(c, "_token", lambda: "tok")

    def explode(req, timeout=None, context=None):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    monkeypatch.setattr(c.urllib.request, "urlopen", explode)
    with pytest.raises(c.DriveIndisponivel, match="compartilhada"):
        c.baixar_do_drive("x")


# ------------------------------------------------------------------ o arquivo
def _linha(**k):
    base = {"id": 1, "nomearquivo": "84933", "extensao": "pdf", "tamanho": 10,
            "tipoarmazenamento": 2, "caminhoarmazenamento": "1AbC",
            "anexado_em": "2026-09-12 08:00", "conteudoarquivo": None}
    return {**base, **k}


def test_o_que_o_ERP_guardou_no_BANCO_nao_vai_ao_Drive(monkeypatch):
    monkeypatch.setattr(c.db, "query", lambda *a, **k: [_linha(conteudoarquivo=b"%PDF-no-banco")])
    monkeypatch.setattr(c, "baixar_do_drive",
                        lambda *a: pytest.fail("foi ao Drive tendo o arquivo em casa"))
    nome, midia, corpo = c.arquivo(CHAVE)
    assert corpo == b"%PDF-no-banco" and midia == "application/pdf"
    assert nome == "canhoto-%s.pdf" % CHAVE


def test_sem_anexo_no_ERP_a_resposta_e_SEM_CANHOTO(monkeypatch):
    monkeypatch.setattr(c.db, "query", lambda *a, **k: [])
    with pytest.raises(c.SemCanhoto, match="ainda não tem canhoto"):
        c.arquivo(CHAVE)


def test_o_mais_RECENTE_manda_e_a_imagem_sai_com_o_tipo_certo(monkeypatch):
    monkeypatch.setattr(c.db, "query", lambda *a, **k: [_linha(extensao="jpg"), _linha()])
    monkeypatch.setattr(c, "baixar_do_drive", lambda i: b"\xff\xd8jpeg")
    nome, midia, _ = c.arquivo(CHAVE)
    assert midia == "image/jpeg" and nome.endswith(".jpg")


def test_a_consulta_do_anexo_e_do_CANHOTO_do_CTe(monkeypatch):
    """Tipo de anexo e tipo de documento fixos: sem eles a mesma chave traria
    qualquer arquivo pendurado no CT-e (boleto, pre-calculo, laudo)."""
    vistos = {}
    monkeypatch.setattr(c.db, "query", lambda sql, p: vistos.update(sql=sql, p=p) or [])
    c.do_cte(CHAVE)
    assert vistos["p"] == {"chave": CHAVE, "tipodoc": 6, "tipo": 105}
    assert "chaveacessocte" in vistos["sql"]


# ------------------------------------------------------------------ a rota
def _req(raiz=None):
    return SimpleNamespace(state=SimpleNamespace(sessao={"cliente_cnpj_raiz": raiz}))


def test_rota_do_canhoto_404_para_chave_de_outro_cliente_SEM_ir_ao_drive(monkeypatch):
    from api import main as m

    def fora(raiz, chave):
        raise d.ForaDoEscopo("x")
    monkeypatch.setattr(d, "autorizar", fora)
    monkeypatch.setattr(c, "arquivo", lambda *a: pytest.fail("consultou o Drive"))
    r = m.portal_cargas_canhoto(_req(RAIZ), chave=CHAVE)
    assert r.status_code == 404


def test_rota_do_canhoto_recusa_chave_de_NOTA(monkeypatch):
    """O canhoto pende do CT-e. Chave de NF-e autorizada nao pode virar busca
    de anexo com os 7 campos de outro documento."""
    from api import main as m
    monkeypatch.setattr(d, "autorizar", lambda raiz, chave: "nfe")
    monkeypatch.setattr(c, "arquivo", lambda *a: pytest.fail("buscou canhoto de nota"))
    r = m.portal_cargas_canhoto(_req(RAIZ), chave="4" * 44)
    assert r.status_code == 404


def test_rota_do_canhoto_entrega_o_arquivo(monkeypatch):
    from api import main as m
    monkeypatch.setattr(d, "autorizar", lambda raiz, chave: "cte")
    monkeypatch.setattr(c, "arquivo", lambda chave: ("canhoto-x.pdf", "application/pdf", b"%PDF"))
    r = m.portal_cargas_canhoto(_req(RAIZ), chave=CHAVE)
    assert r.status_code == 200 and r.body == b"%PDF"
    assert r.headers["content-disposition"] == 'attachment; filename="canhoto-x.pdf"'


@pytest.mark.parametrize("erro", ["SemCanhoto", "SemCredencial", "DriveIndisponivel"])
def test_as_TRES_recusas_do_canhoto_sao_409_com_motivo(monkeypatch, erro):
    from api import main as m
    monkeypatch.setattr(d, "autorizar", lambda raiz, chave: "cte")

    def explode(chave):
        raise getattr(c, erro)("motivo legivel")
    monkeypatch.setattr(c, "arquivo", explode)
    r = m.portal_cargas_canhoto(_req(RAIZ), chave=CHAVE)
    assert r.status_code == m.HTTP_RECUSA
    assert json.loads(r.body)["mensagem"] == "motivo legivel"
