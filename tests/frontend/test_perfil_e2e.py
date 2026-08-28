"""Foto de perfil e cadastro do usuário, no navegador.

O backend tem teste próprio (`tests/test_usuario_cadastro.py`). O que só se
prova AQUI:

1. **A redução da imagem acontece no cliente.** É a parte que decide se uma
   foto de celular de 6 MB vai inteira pela rede ou se chegam 20 KB de JPEG
   256x256. Nenhum teste de backend distingue os dois casos — os dois passam.
2. **O avatar cai nas iniciais quando não há foto**, em vez de mostrar um
   quadrado quebrado. Foto é campo opcional; "sem foto" é estado normal.
3. **A tela de Minha Conta não oferece nome, e-mail, cargo nem setor.** O
   backend recusa esses campos nessa rota; a tela não pode convidar a
   preencher o que vai ser ignorado.
"""
from __future__ import annotations

import base64
import json
import struct
import zlib

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "id": 7, "nome": "Ana Paula Ribeiro", "email": "ana@sulista.com.br",
         "perfil": "Administrador", "admin": True, "telefone": "5547999998888",
         "telefone_fmt": "(47) 99999-8888", "cargo": "Controller",
         "setor": "Controladoria", "ramal": "204", "foto_em": "2026-08-28 10:00:00"}

SEM_FOTO = {**ADMIN, "foto_em": None, "telefone": "", "telefone_fmt": "",
            "cargo": "", "setor": "", "ramal": ""}

USUARIOS = {"usuarios": [
    {"id": 7, "nome": "Ana Paula Ribeiro", "email": "ana@sulista.com.br",
     "perfil_id": 1, "perfil": "Administrador", "perfil_admin": 1, "ativo": 1,
     "deve_trocar_senha": 0, "bloqueado_ate": None, "criado_em": "2026-01-02 08:00:00",
     "ultimo_login": "2026-08-28 09:00:00", "telefone": "5547999998888",
     "telefone_fmt": "(47) 99999-8888", "cargo": "Controller",
     "setor": "Controladoria", "ramal": "204", "foto_em": "2026-08-28 10:00:00"},
    {"id": 8, "nome": "Bruno Lima", "email": "bruno@sulista.com.br",
     "perfil_id": 2, "perfil": "Operação", "perfil_admin": 0, "ativo": 1,
     "deve_trocar_senha": 0, "bloqueado_ate": None, "criado_em": "2026-02-02 08:00:00",
     "ultimo_login": None, "telefone": None, "telefone_fmt": "", "cargo": None,
     "setor": None, "ramal": None, "foto_em": None},
]}
PERFIS = {"perfis": [{"id": 1, "nome": "Administrador", "descricao": "", "admin": 1,
                      "usuarios": 1, "telas": []},
                     {"id": 2, "nome": "Operação", "descricao": "", "admin": 0,
                      "usuarios": 1, "telas": []}]}


def _png(lado: int) -> bytes:
    """PNG grande de verdade (ruído, para não comprimir a nada): é o arquivo
    que a tela precisa reduzir."""
    import os
    linhas = b"".join(b"\x00" + os.urandom(lado) for _ in range(lado))

    def bloco(tipo, dados):
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 0, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas))
            + bloco(b"IEND", b""))


def _abrir(pg, base_url, usuario=ADMIN, gravadas=None):
    """Serve /api/** com dublês. `gravadas` recolhe os POSTs, para conferir o
    que a tela MANDA (que é o que o backend vai ver)."""
    def rota(route):
        u, req = route.request.url, route.request
        if req.method == "POST" and gravadas is not None:
            try:
                gravadas.append((u, json.loads(req.post_data or "{}")))
            except ValueError:                       # pragma: no cover
                gravadas.append((u, {}))
        if "/api/auth/me" in u or "/api/auth/perfil" in u:
            corpo = usuario
        elif "/gestao/usuarios" in u:
            corpo = USUARIOS
        elif "/gestao/perfis" in u:
            corpo = PERFIS
        elif "/gestao/telas" in u:
            corpo = {"telas": []}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    # a foto em si não passa pelo mock de /api/** (é imagem, não JSON)
    pg.route("**/api/auth/foto/**", lambda r: r.fulfill(
        status=200, content_type="image/png",
        body=base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")))
    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#home")
    pg.wait_for_selector("#avBtn", timeout=20000)
    pg.wait_for_timeout(400)
    return erros


# ------------------------------------------------------------------- avatar

def test_avatar_da_barra_mostra_a_foto_com_a_versao_na_url(pagina):
    pg, base = pagina
    assert _abrir(pg, base) == []
    src = pg.get_attribute("#avBtn img", "src")
    assert "/api/auth/foto/7" in src
    # o carimbo na URL é o que faz a troca de foto aparecer na hora
    assert "v=2026-08-28" in src


def test_sem_foto_o_avatar_sao_as_INICIAIS_e_nao_imagem_quebrada(pagina):
    pg, base = pagina
    assert _abrir(pg, base, usuario=SEM_FOTO) == []
    assert pg.query_selector("#avBtn img") is None
    assert pg.inner_text("#avBtn").strip() == "AR"


def test_menu_esconde_cargo_e_telefone_quando_nao_ha(pagina):
    """Linha vazia no menu leria como 'o campo sumiu', não como 'ninguém
    preencheu'."""
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#avBtn")                       # o menu nasce fechado (display:none)
    assert pg.is_visible("#avCargo") and "Controller" in pg.inner_text("#avCargo")
    assert "(47) 99999-8888" in pg.inner_text("#avTel")
    assert "ramal 204" in pg.inner_text("#avTel")

    _abrir(pg, base, usuario=SEM_FOTO)
    pg.click("#avBtn")
    assert not pg.is_visible("#avCargo") and not pg.is_visible("#avTel")


# -------------------------------------------------------------- minha conta

def _minha_conta(pg):
    pg.click("#avBtn")
    pg.click("text=Minha conta")
    pg.wait_for_selector("#mc-tel", timeout=5000)


def test_minha_conta_abre_com_telefone_formatado_e_leitura_do_resto(pagina):
    pg, base = pagina
    _abrir(pg, base)
    _minha_conta(pg)
    assert pg.input_value("#mc-tel") == "(47) 99999-8888"
    assert pg.input_value("#mc-ramal") == "204"
    corpo = pg.inner_text("#modalBox")
    assert "Controller" in corpo and "ana@sulista.com.br" in corpo
    # nome, e-mail, cargo e setor não têm campo editável nesta tela
    editaveis = pg.eval_on_selector_all(
        "#modalBox input:not([type=file])", "els=>els.map(e=>e.id)")
    assert sorted(editaveis) == ["mc-ramal", "mc-tel"]


def test_a_imagem_e_reduzida_no_cliente_antes_de_subir(pagina, tmp_path):
    """1200x1200 de ruído (perto de 1,4 MB) tem de virar JPEG 256x256 de
    poucas dezenas de KB — e é ISSO que vai no POST."""
    pg, base = pagina
    gravadas = []
    _abrir(pg, base, gravadas=gravadas)
    grande = tmp_path / "retrato.png"
    grande.write_bytes(_png(1200))
    assert grande.stat().st_size > 900_000

    _minha_conta(pg)
    pg.set_input_files("#fe-arq", str(grande))
    # FOTOED e `let` de topo: existe no escopo do script, NAO em window
    pg.wait_for_function("typeof FOTOED !== 'undefined' && typeof FOTOED.valor === 'string'",
                         timeout=10000)

    valor = pg.evaluate("FOTOED.valor")
    assert valor.startswith("data:image/jpeg;base64,")
    bytes_enviados = len(base64.b64decode(valor.split(",", 1)[1]))
    assert bytes_enviados < 300 * 1024, f"{bytes_enviados} bytes — passaria do limite do servidor"
    lados = pg.evaluate("""() => new Promise(ok=>{const i=new Image();
        i.onload=()=>ok([i.naturalWidth,i.naturalHeight]); i.src=FOTOED.valor;})""")
    assert lados == [256, 256]

    pg.click("#mc-salvar")
    pg.wait_for_timeout(400)
    enviado = [c for u, c in gravadas if "/api/auth/perfil" in u]
    assert enviado and enviado[0]["foto"].startswith("data:image/jpeg")
    assert enviado[0]["telefone"] == "(47) 99999-8888"


def test_remover_foto_manda_string_vazia_e_nao_omite_o_campo(pagina):
    """Omitir seria 'não mexe' no backend — a foto ficaria lá."""
    pg, base = pagina
    gravadas = []
    _abrir(pg, base, gravadas=gravadas)
    _minha_conta(pg)
    pg.click("#fe-rem")
    assert pg.query_selector("#fe-prev img") is None
    pg.click("#mc-salvar")
    pg.wait_for_timeout(400)
    enviado = [c for u, c in gravadas if "/api/auth/perfil" in u]
    assert enviado and enviado[0]["foto"] == ""


def test_sem_mexer_na_foto_o_campo_NAO_vai_no_payload(pagina):
    pg, base = pagina
    gravadas = []
    _abrir(pg, base, gravadas=gravadas)
    _minha_conta(pg)
    pg.fill("#mc-ramal", "310")
    pg.click("#mc-salvar")
    pg.wait_for_timeout(400)
    enviado = [c for u, c in gravadas if "/api/auth/perfil" in u]
    assert enviado and "foto" not in enviado[0] and enviado[0]["ramal"] == "310"


# ------------------------------------------------------------------- gestão

def _gestao(pg):
    pg.evaluate("location.hash='#gestao'")
    pg.wait_for_selector("#ges-usr tr", timeout=10000)


def test_lista_de_usuarios_traz_avatar_cargo_e_contato(pagina):
    pg, base = pagina
    _abrir(pg, base)
    _gestao(pg)
    linhas = pg.inner_text("#ges-usr")
    assert "Controller · Controladoria" in linhas
    assert "(47) 99999-8888 · ramal 204" in linhas
    # quem tem foto vem com <img>; quem não tem, com as iniciais
    assert pg.query_selector("#ges-usr tr:nth-child(1) .avmini img") is not None
    assert pg.inner_text("#ges-usr tr:nth-child(2) .avmini").strip() == "BL"


def test_modal_de_edicao_manda_os_campos_novos(pagina):
    pg, base = pagina
    gravadas = []
    _abrir(pg, base, gravadas=gravadas)
    _gestao(pg)
    pg.click("#ges-usr tr:nth-child(2) button:has-text('Editar')")
    pg.wait_for_selector("#gu-cargo", timeout=5000)
    pg.fill("#gu-cargo", "Analista de Frota")
    pg.fill("#gu-setor", "Operação")
    pg.fill("#gu-tel", "(47) 98888-7777")
    pg.fill("#gu-ramal", "115")
    pg.click("#modalBox button:has-text('Salvar')")
    pg.wait_for_timeout(400)
    enviado = [c for u, c in gravadas if "/gestao/usuarios/8" in u]
    assert enviado, "o POST de edição não saiu"
    assert enviado[0]["cargo"] == "Analista de Frota"
    assert enviado[0]["setor"] == "Operação"
    assert enviado[0]["telefone"] == "(47) 98888-7777"
    assert enviado[0]["ramal"] == "115"
