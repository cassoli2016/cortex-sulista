"""Foto de perfil: o que o servidor aceita como imagem — e por que ele mesmo
precisa conferir, se quem manda é a nossa própria tela.

A tela reduz a imagem a 256x256 e reencoda em JPEG antes de subir, então na
prática só chega arquivo pequeno e bem-comportado. Isso é conveniência do
usuário, NÃO é validação: o `POST` é uma rota como outra qualquer e aceita o
que mandarem nela. Quem decide o que entra no banco é este módulo.

TRÊS COISAS SÃO CONFERIDAS, E A TERCEIRA É A QUE NÃO É ÓBVIA:

1. **O tipo sai dos BYTES, não do que o cliente disse que é.** Um `data:` URL
   traz o mime escrito pelo remetente; confiar nele é deixar o remetente
   escolher o `Content-Type` com que a imagem volta para o navegador de todo
   mundo — e `image/svg+xml` (ou qualquer coisa que o navegador resolva
   interpretar) vira script rodando na origem do painel. Aceita-se PNG, JPEG e
   WEBP, reconhecidos pela assinatura do arquivo. SVG NÃO ENTRA, de propósito:
   é XML com script dentro, não é formato de foto de perfil.
2. **O tamanho em bytes tem teto** — 300 KB, folgado para um avatar de 256px e
   apertado o suficiente para o campo não virar depósito de arquivo.
3. **A DIMENSÃO tem teto separado, e é ela que evita a bomba.** Um PNG de
   180 KB pode declarar 25000x25000: são 2,5 GB de bitmap na hora em que o
   navegador for desenhar — não no nosso servidor, que nunca decodifica a
   imagem, mas no de quem abrir a lista de usuários. Por isso a largura e a
   altura são lidas do CABEÇALHO do arquivo (barato, não decodifica nada) e
   recusadas acima de 1024px. Ler o cabeçalho de três formatos custa as ~60
   linhas abaixo; a alternativa era o Pillow, uma dependência C de produção
   inteira para conferir dois inteiros.

Nada aqui redimensiona ou reencoda imagem — este módulo só diz sim ou não.
"""
from __future__ import annotations

import base64
import binascii
import struct

MAX_BYTES = 300 * 1024
LADO_MAX = 1024
LADO_MIN = 16

MIMES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


class FotoInvalida(ValueError):
    """A mensagem vai direto para a tela de quem está com o cadastro aberto."""


def _formato(b: bytes) -> str | None:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


def _dim_png(b: bytes) -> tuple[int, int] | None:
    # IHDR é obrigatoriamente o primeiro chunk: largura e altura em big-endian
    # logo depois da assinatura + tamanho + tipo do chunk.
    if len(b) < 24 or b[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", b[16:24])


def _dim_jpeg(b: bytes) -> tuple[int, int] | None:
    # Percorre os segmentos até um SOF (start of frame), que é onde o JPEG diz
    # o tamanho. SOF0..SOF15, tirando C4 (Huffman), C8 (extensão) e CC (aritm.).
    i, n = 2, len(b)
    while i + 9 < n:
        if b[i] != 0xFF:
            i += 1
            continue
        marca = b[i + 1]
        if marca in (0xD8, 0x01) or 0xD0 <= marca <= 0xD7:
            i += 2
            continue
        tam = struct.unpack(">H", b[i + 2:i + 4])[0]
        if 0xC0 <= marca <= 0xCF and marca not in (0xC4, 0xC8, 0xCC):
            alt, lar = struct.unpack(">HH", b[i + 5:i + 9])
            return lar, alt
        i += 2 + tam
    return None


def _dim_webp(b: bytes) -> tuple[int, int] | None:
    tipo = b[12:16]
    if tipo == b"VP8 " and len(b) >= 30 and b[23:26] == b"\x9d\x01\x2a":
        lar, alt = struct.unpack("<HH", b[26:30])
        return lar & 0x3FFF, alt & 0x3FFF
    if tipo == b"VP8L" and len(b) >= 25 and b[20] == 0x2F:
        bits = int.from_bytes(b[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if tipo == b"VP8X" and len(b) >= 30:
        lar = int.from_bytes(b[24:27], "little") + 1
        alt = int.from_bytes(b[27:30], "little") + 1
        return lar, alt
    return None


def dimensoes(b: bytes, formato: str) -> tuple[int, int] | None:
    return {"png": _dim_png, "jpeg": _dim_jpeg, "webp": _dim_webp}[formato](b)


def _bytes_do_payload(valor: str) -> bytes:
    """Aceita `data:image/jpeg;base64,AAA…` (o que o `canvas.toDataURL()` da
    tela produz) e também base64 puro."""
    texto = (valor or "").strip()
    if texto.startswith("data:"):
        _, _, texto = texto.partition(",")
    try:
        return base64.b64decode("".join(texto.split()), validate=True)
    except (binascii.Error, ValueError):
        raise FotoInvalida("Não foi possível ler a imagem enviada.") from None


def validar(valor: str) -> tuple[bytes, str, int, int]:
    """`(bytes, mime, largura, altura)` ou `FotoInvalida` com o motivo."""
    dados = _bytes_do_payload(valor)
    if not dados:
        raise FotoInvalida("Imagem vazia.")
    if len(dados) > MAX_BYTES:
        raise FotoInvalida(
            f"A imagem tem {len(dados) // 1024} KB — o limite é "
            f"{MAX_BYTES // 1024} KB.")
    formato = _formato(dados)
    if not formato:
        raise FotoInvalida("Envie uma imagem PNG, JPEG ou WEBP.")
    dim = dimensoes(dados, formato)
    if not dim:
        raise FotoInvalida("Arquivo de imagem corrompido ou incompleto.")
    lar, alt = dim
    if lar > LADO_MAX or alt > LADO_MAX:
        raise FotoInvalida(
            f"A imagem tem {lar}x{alt} px — o limite é "
            f"{LADO_MAX}x{LADO_MAX} px.")
    if lar < LADO_MIN or alt < LADO_MIN:
        raise FotoInvalida(f"A imagem tem {lar}x{alt} px — pequena demais.")
    return dados, MIMES[formato], lar, alt
