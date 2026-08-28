"""Cadastro de usuário: telefone, cargo/setor/ramal e foto de perfil.

Três coisas aqui não são detalhe, e cada uma tem teste próprio:

1. **Campo ausente não é campo vazio.** A tela de Minha Conta manda dois
   campos; se o backend lesse os que ela não manda como "", o cargo posto pelo
   administrador sumiria em silêncio na primeira vez que alguém trocasse o
   próprio telefone.
2. **O telefone é guardado normalizado.** É o que faz `(47) 99999-8888` e
   `5547999998888` serem a mesma pessoa para qualquer contagem futura.
3. **A foto é validada pelos BYTES.** O mime que o cliente escreve no `data:`
   URL não decide nada, e a dimensão declarada no cabeçalho é conferida — um
   arquivo pequeno pode declarar 25000x25000 e estourar o navegador de quem
   abrir a lista de usuários.
"""
from __future__ import annotations

import base64
import os
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from api import auth, fotos


# ------------------------------------------------------------------ imagens

def png(largura: int, altura: int, ruido: bool = False) -> bytes:
    """PNG cinza válido, montado à mão — a suíte não tem Pillow (e a produção
    também não: ver o cabeçalho de `api/fotos.py`).

    `ruido=True` enche de bytes aleatórios: cinza chapado comprime a quase
    nada, e o teste do teto de TAMANHO precisa de um arquivo que realmente
    pese (700x700 chapado dá 3 KB)."""
    pixel = (lambda n: os.urandom(n)) if ruido else (lambda n: b"\x80" * n)
    linhas = b"".join(b"\x00" + pixel(largura) for _ in range(altura))

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 0, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas))
            + bloco(b"IEND", b""))


def data_url(dados: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(dados).decode()


def test_png_do_teste_e_lido_corretamente():
    assert fotos._formato(png(64, 48)) == "png"
    assert fotos.dimensoes(png(64, 48), "png") == (64, 48)


def test_webp_dos_tres_sabores_tem_dimensao_lida():
    """VP8 (lossy), VP8L (lossless) e VP8X (estendido) guardam o tamanho em
    lugares e codificações diferentes — o navegador gera qualquer um dos três."""
    def riff(tipo: bytes, corpo: bytes) -> bytes:
        dados = b"WEBP" + tipo + struct.pack("<I", len(corpo)) + corpo
        return b"RIFF" + struct.pack("<I", len(dados)) + dados

    lossy = riff(b"VP8 ", b"\x00\x00\x00" + b"\x9d\x01\x2a"
                 + struct.pack("<HH", 300, 200) + b"\x00" * 8)
    assert fotos.dimensoes(lossy, "webp") == (300, 200)

    bits = (300 - 1) | ((200 - 1) << 14)
    lossless = riff(b"VP8L", b"\x2f" + struct.pack("<I", bits) + b"\x00" * 4)
    assert fotos.dimensoes(lossless, "webp") == (300, 200)

    estendido = riff(b"VP8X", b"\x00" * 4
                     + (300 - 1).to_bytes(3, "little") + (200 - 1).to_bytes(3, "little")
                     + b"\x00" * 8)
    assert fotos.dimensoes(estendido, "webp") == (300, 200)


def test_svg_nao_e_foto_de_perfil():
    """SVG é XML com script dentro. Devolvido como `image/svg+xml` na origem do
    painel, vira execução de código — não é enfeite de formato aceito."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(fotos.FotoInvalida, match="PNG, JPEG ou WEBP"):
        fotos.validar(data_url(svg, "image/png"))   # mime mentido de propósito


def test_dimensao_absurda_e_recusada_mesmo_com_arquivo_pequeno():
    """A bomba de descompressão: o cabeçalho declara 25000x25000 e o arquivo
    tem poucos KB — quem paga é o navegador que for desenhar."""
    bomba = bytearray(png(16, 16))
    bomba[16:24] = struct.pack(">II", 25000, 25000)
    with pytest.raises(fotos.FotoInvalida, match="25000x25000"):
        fotos.validar(data_url(bytes(bomba)))


def test_arquivo_acima_do_teto_e_recusado():
    with pytest.raises(fotos.FotoInvalida, match="limite"):
        fotos.validar(base64.b64encode(png(700, 700, ruido=True)).decode())


def test_base64_puro_tambem_serve():
    dados, mime, lar, alt = fotos.validar(base64.b64encode(png(64, 64)).decode())
    assert (mime, lar, alt) == ("image/png", 64, 64)
    assert dados.startswith(b"\x89PNG")


def test_lixo_no_lugar_da_imagem_da_mensagem_em_portugues():
    with pytest.raises(fotos.FotoInvalida, match="ler a imagem"):
        fotos.validar("isto não é base64 !!!")


# ------------------------------------------------------- cadastro ponta a ponta

SENHA = "senha-de-teste-123"


@pytest.fixture
def cliente(esquema_pg, monkeypatch):
    """API de pé com um administrador logado, sobre um schema descartável."""
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES('Chefe','chefe@sulista.com.br',%s,%s,1,0,%s)""",
            (auth._ph.hash(SENHA), perfil["id"], auth._agora()))
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": "chefe@sulista.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def _criar(cli: TestClient, **campos):
    with auth._conn() as c:
        perfil = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
    corpo = {"nome": "Maria Souza", "email": "maria@sulista.com.br",
             "senha_temporaria": "temporaria-123", "perfil_id": perfil["id"]}
    corpo.update(campos)
    return cli.post("/api/gestao/usuarios", json=corpo)


def test_criar_com_campos_novos_guarda_telefone_normalizado(cliente):
    r = _criar(cliente, telefone="(47) 99999-8888", cargo="Analista  Fiscal",
               setor="Controladoria", ramal="204")
    assert r.status_code == 200, r.text
    lista = cliente.get("/api/gestao/usuarios").json()["usuarios"]
    maria = next(u for u in lista if u["email"] == "maria@sulista.com.br")
    assert maria["telefone"] == "5547999998888"        # normalizado no banco
    assert maria["telefone_fmt"] == "(47) 99999-8888"  # formatado para a tela
    assert maria["cargo"] == "Analista Fiscal"         # espaço duplo normalizado
    assert maria["setor"] == "Controladoria"
    assert maria["ramal"] == "204"
    assert maria["foto_em"] is None


def test_cadastro_sem_nenhum_campo_novo_continua_valendo(cliente):
    """Os campos são opcionais — a base de produção já tinha gente cadastrada
    quando eles nasceram."""
    assert _criar(cliente).status_code == 200
    lista = cliente.get("/api/gestao/usuarios").json()["usuarios"]
    maria = next(u for u in lista if u["email"] == "maria@sulista.com.br")
    assert maria["telefone"] is None and maria["cargo"] is None


def test_ddd_inexistente_e_recusado_com_a_mensagem_do_validador(cliente):
    r = _criar(cliente, telefone="(20) 99999-8888")
    assert r.status_code == 422
    assert "DDD 20" in r.json()["mensagem"]


def test_cargo_longo_demais_e_recusado(cliente):
    r = _criar(cliente, cargo="x" * 61)
    assert r.status_code == 422 and "cargo" in r.json()["mensagem"]


def _id_da_maria(cli: TestClient) -> int:
    lista = cli.get("/api/gestao/usuarios").json()["usuarios"]
    return next(u["id"] for u in lista if u["email"] == "maria@sulista.com.br")


def test_editar_sem_mandar_o_campo_nao_apaga_o_campo(cliente):
    """A regra do sentinela: chave ausente = não mexe; chave vazia = limpa."""
    _criar(cliente, cargo="Analista Fiscal", telefone="47999998888")
    uid = _id_da_maria(cliente)

    cliente.post(f"/api/gestao/usuarios/{uid}", json={"nome": "Maria S. Souza"})
    lista = cliente.get("/api/gestao/usuarios").json()["usuarios"]
    maria = next(u for u in lista if u["id"] == uid)
    assert maria["cargo"] == "Analista Fiscal" and maria["telefone"] == "5547999998888"

    cliente.post(f"/api/gestao/usuarios/{uid}", json={"cargo": ""})
    lista = cliente.get("/api/gestao/usuarios").json()["usuarios"]
    assert next(u for u in lista if u["id"] == uid)["cargo"] is None


def test_foto_sobe_e_e_servida_com_etag(cliente):
    _criar(cliente, foto=data_url(png(120, 120)))
    uid = _id_da_maria(cliente)
    lista = cliente.get("/api/gestao/usuarios").json()["usuarios"]
    assert next(u for u in lista if u["id"] == uid)["foto_em"]

    r = cliente.get(f"/api/auth/foto/{uid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content.startswith(b"\x89PNG")
    etag = r.headers["etag"]
    assert cliente.get(f"/api/auth/foto/{uid}",
                       headers={"If-None-Match": etag}).status_code == 304


def test_usuario_sem_foto_da_404_e_nao_500(cliente):
    _criar(cliente)
    assert cliente.get(f"/api/auth/foto/{_id_da_maria(cliente)}").status_code == 404


def test_foto_invalida_nao_deixa_usuario_criado_pela_metade(cliente):
    """O INSERT do usuário e a foto estão na MESMA transação: recusar a foto
    depois de gravar o usuário criaria alguém pela metade sem avisar."""
    r = _criar(cliente, foto=data_url(b"nem imagem e"))
    assert r.status_code == 422
    emails = [u["email"] for u in cliente.get("/api/gestao/usuarios").json()["usuarios"]]
    assert "maria@sulista.com.br" not in emails


def test_excluir_usuario_leva_a_foto_junto(cliente):
    """Sem o ON DELETE CASCADE isto viraria erro de chave estrangeira — e só
    apareceria no dia em que alguém fosse excluir alguém."""
    _criar(cliente, foto=data_url(png(64, 64)))
    uid = _id_da_maria(cliente)
    assert cliente.post(f"/api/gestao/usuarios/{uid}/excluir").status_code == 200
    with auth._conn() as c:
        n = c.execute("SELECT count(*) AS n FROM usuario_fotos WHERE usuario_id=%s",
                      (uid,)).fetchone()["n"]
    assert n == 0


# --------------------------------------------------------------- minha conta

def test_proprio_usuario_edita_telefone_ramal_e_foto(cliente):
    r = cliente.post("/api/auth/perfil", json={
        "telefone": "47 3333-4444", "ramal": "101", "foto": data_url(png(80, 80))})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["telefone"] == "554733334444"      # fixo, 10 dígitos + DDI
    assert corpo["telefone_fmt"] == "(47) 3333-4444"
    assert corpo["ramal"] == "101" and corpo["foto_em"]
    assert cliente.get("/api/auth/me").json()["telefone_fmt"] == "(47) 3333-4444"


def test_minha_conta_nao_muda_nome_email_cargo_nem_setor(cliente):
    """Nome e e-mail assinam a trilha de auditoria; cargo e setor são estrutura
    da empresa. Mandar no payload não pode surtir efeito."""
    with auth._conn() as c:
        c.execute("UPDATE usuarios SET cargo='Diretor', setor='Diretoria' "
                  "WHERE email='chefe@sulista.com.br'")
    cliente.post("/api/auth/perfil", json={
        "nome": "Outro Nome", "email": "outro@sulista.com.br",
        "cargo": "Presidente", "setor": "Conselho", "ramal": "9"})
    eu = cliente.get("/api/auth/me").json()
    assert eu["nome"] == "Chefe" and eu["email"] == "chefe@sulista.com.br"
    assert eu["cargo"] == "Diretor" and eu["setor"] == "Diretoria"
    assert eu["ramal"] == "9"


def test_remover_a_propria_foto(cliente):
    cliente.post("/api/auth/perfil", json={"foto": data_url(png(64, 64))})
    assert cliente.get("/api/auth/me").json()["foto_em"]
    cliente.post("/api/auth/perfil", json={"foto": ""})
    assert cliente.get("/api/auth/me").json()["foto_em"] is None


def test_foto_exige_sessao():
    from api.main import app
    assert TestClient(app).get("/api/auth/foto/1").status_code == 401
