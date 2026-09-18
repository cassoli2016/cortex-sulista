"""O web service XML da TrucksControl — três requisições, medidas no ar.

O MANUAL DIZ O CORPO, NÃO O CAMINHO, e o caminho é a raiz: o POST do XML vai
em `https://webservice.newrastreamentoonline.com.br/` (conferido em
17/09/2026 com credencial inválida, que devolveu o `<ErrorRequest>` abaixo).
Adivinhar caminho de fornecedor é a regra que a casa já pagou para aprender.

TRÊS ARMADILHAS DESTE FORNECEDOR:

1. **A CREDENCIAL VIAJA NO CORPO.** `<login>` e `<senha>` vão dentro do XML
   de toda requisição. Por isso NADA daqui devolve o corpo cru: exceção, log e
   mensagem passam por `_limpar()`. É a mesma regra do Ponto Certificado, e
   pela mesma razão — lá a senha também vai no corpo.
2. **ERRO VEM COM HTTP 200.** Login errado responde
   `<ErrorRequest><erro>Atributos para leitura de requisição inválidos…`
   com status 200. Quem olhar só o código HTTP conclui que deu certo e grava
   uma coleta vazia como se fosse "nenhum dado".
3. **O CURSOR É DE MÃO ÚNICA e não aceita zero.** A caixa preta se pede por
   `cpId`, e o manual manda usar SEMPRE O MAIOR recebido na chamada seguinte.
   O `<dt>` é a hora do evento e o `<dtinc>` a da gravação no servidor — a
   diferença entre os dois é o atraso do satélite, e é por `dtinc` que se
   mede se a coleta está em dia.

O QUE CADA REQUISIÇÃO DEVOLVE (manual de 17/09/2026):

MEDIDO NO AR EM 17/09/2026, com credencial válida — e nada disso está no
manual: a resposta vem ZIPADA (um `<guid>.txt` dentro), o erro traz um
`<codigo>` (7 = cadência), e a `distancia` do relatório vem em QUILÔMETROS, e
não em metros como o manual diz — ela bate exatamente com a diferença entre
`odmIni` e `odmFim`.

- `RequestTelemetriaRelatorio` (tID sempre 1): o resumo de ONTEM (D-1) de
  todos os veículos que tiveram informação — distância em METROS, horímetro e
  utilização em MINUTOS, consumo médio, consumo por hora de motor, RPM médio e
  máximo, temperatura média e máxima, e os quatro tempos de motor. Uma ou duas
  vezes por dia; não há janela para trás.
- `RequestCaixaPreta` (cpId): mensagens de 30 em 30 s com velocidade, RPM,
  força G (negativa à esquerda, positiva à direita) e `estID` — as violações
  daquela mensagem, separadas por `;`, ausentes quando não houve violação.
- `RequestTelemetriaEstatistica`: o de-para `estID` → descrição. Sem ele a
  violação é um número sem significado.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from xml.etree import ElementTree as ET

import httpx

from api import credenciais, tls

log = logging.getLogger(__name__)

URL = "https://webservice.newrastreamentoonline.com.br/"
TIMEOUT = 60.0
# o manual: "passar sempre 1"
TELEMETRIA_TID = "1"


class TrucksControlErro(Exception):
    """Falha do fornecedor, já sem credencial na mensagem."""


class SemCredencial(TrucksControlErro):
    """Instalação incompleta — não é falha de coleta."""


class Freio(TrucksControlErro):
    """O fornecedor recusou por CADÊNCIA (código 7), não por erro.

    Cada requisição tem o seu ritmo — caixa preta 30 s, estatísticas 5 min,
    telemetria uma ou duas vezes ao dia — e pedir antes devolve
    "Nao atingiu o tempo minimo para reenvio da requisicao" com HTTP 200.
    Quem tratar isso como falha vai acender alarme por estar apressado; quem
    tratar como sucesso vazio vai gravar "nenhum dado" por cima do que havia.
    """

    codigo = 7


def _limpar(texto: str) -> str:
    """Tira login e senha de qualquer texto que vá para log, tela ou exceção."""
    return re.sub(r"<(login|senha)>.*?</\1>", r"<\1>…</\1>", texto or "",
                  flags=re.S | re.I)


def credencial() -> tuple[str, str]:
    login = (credenciais.ler("TRUCKSCONTROL_LOGIN") or "").strip()
    senha = (credenciais.ler("TRUCKSCONTROL_SENHA") or "").strip()
    if not login or not senha:
        raise SemCredencial(
            "TrucksControl sem credencial: cadastre login e senha de integração "
            "em Administração › Integrações.")
    return login, senha


def _esc(v: str) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _pedir(raiz: str, esperado: str, extra: str = "") -> ET.Element:
    """Monta, envia e lê. Devolve a raiz do XML de resposta.

    `esperado` é a raiz que a resposta TEM de ter: uma página de erro em
    HTML é XML válido, cai sem `<Mensagem>` dentro e viraria coleta VAZIA —
    indistinguível de "não há dado novo"."""
    login, senha = credencial()
    corpo = (f"<{raiz}><login>{_esc(login)}</login><senha>{_esc(senha)}</senha>"
             f"{extra}</{raiz}>")
    try:
        with httpx.Client(timeout=TIMEOUT, verify=tls.contexto()) as c:
            r = c.post(URL, content=corpo.encode("utf-8"),
                       headers={"Content-Type": "text/xml; charset=utf-8"})
    except httpx.HTTPError as exc:      # a URL não tem segredo; a mensagem pode
        raise TrucksControlErro(
            f"TrucksControl não respondeu ({type(exc).__name__}).") from None
    if r.status_code >= 400:
        raise TrucksControlErro(f"TrucksControl devolveu HTTP {r.status_code}.")
    texto = _desempacotar(r.content or b"", r.text or "")
    try:
        raiz_xml = ET.fromstring(texto)
    except ET.ParseError:
        raise TrucksControlErro(
            "TrucksControl devolveu uma resposta que não é XML "
            f"({_limpar(texto)[:200]!r}).") from None
    # ERRO COM HTTP 200: quem lê só o código acha que a coleta veio vazia
    if raiz_xml.tag.lower() == "errorrequest":
        erro = (raiz_xml.findtext("erro") or "sem detalhe").strip()
        codigo = (raiz_xml.findtext("codigo") or "").strip()
        if codigo == str(Freio.codigo):
            raise Freio(f"TrucksControl pediu para esperar: {_limpar(erro)}")
        raise TrucksControlErro(f"TrucksControl recusou: {_limpar(erro)}")
    if raiz_xml.tag.lower() != esperado.lower():
        raise TrucksControlErro(
            f"TrucksControl respondeu <{raiz_xml.tag}> onde o manual diz "
            f"<{esperado}> — resposta não reconhecida.")
    return raiz_xml


def _desempacotar(bruto: bytes, texto: str) -> str:
    """A RESPOSTA VEM ZIPADA, e o manual não diz (medido em 17/09/2026, com
    credencial válida: `PK` seguido dos dois bytes mágicos do ZIP e um `<guid>.txt` dentro). Quem trata a
    resposta como texto lê "PK…" e conclui "não é XML" — que foi o que este
    cliente fez na primeira medição. Resposta sem o ZIP continua valendo: o
    fornecedor pode responder erro em XML puro."""
    if not bruto[:2] == b"PK":
        return texto
    try:
        with zipfile.ZipFile(io.BytesIO(bruto)) as z:
            nomes = z.namelist()
            if not nomes:
                raise TrucksControlErro("TrucksControl devolveu um ZIP vazio.")
            return z.read(nomes[0]).decode("utf-8", "replace")
    except zipfile.BadZipFile:
        raise TrucksControlErro(
            "TrucksControl devolveu algo que começa como ZIP e não abre.") from None


def _txt(no: ET.Element, tag: str) -> str | None:
    v = no.findtext(tag)
    v = (v or "").strip()
    return v or None


def _num(no: ET.Element, tag: str) -> float | None:
    """Número do fornecedor: decimal com VÍRGULA (lat/lon vêm '-27,6261')."""
    v = _txt(no, tag)
    if v is None:
        return None
    try:
        return float(v.replace(".", "").replace(",", ".") if "," in v else v)
    except ValueError:
        return None


def _int(no: ET.Element, tag: str) -> int | None:
    v = _num(no, tag)
    return None if v is None else int(v)


def estatisticas() -> list[dict]:
    """O de-para `estID` → descrição das violações de telemetria."""
    raiz = _pedir("RequestTelemetriaEstatistica", "ResponseTelemetriaEstatistica")
    return [{"est_id": _int(n, "estID"), "descricao": _txt(n, "descricao")}
            for n in raiz.findall(".//TelemetriaEstatistica")
            if _int(n, "estID") is not None]


def caixa_preta(cp_id: int) -> list[dict]:
    """As mensagens a partir do cursor. O manual manda mandar de volta o MAIOR
    `cpId` recebido — quem reenvia o mesmo anda em círculo."""
    raiz = _pedir("RequestCaixaPreta", "ResponseCaixaPreta", f"<cpId>{int(cp_id)}</cpId>")
    out = []
    for n in raiz.findall(".//Mensagem"):
        if _int(n, "cpId") is None:
            continue
        est = _txt(n, "estID") or ""
        out.append({
            "cp_id": _int(n, "cpId"), "veiculo_id": _int(n, "veiID"),
            "dt": _txt(n, "dt"), "dtinc": _txt(n, "dtinc"),
            "lat": _num(n, "lat"), "lon": _num(n, "lon"),
            "velocidade": _int(n, "vel"), "rpm": _int(n, "rpm"),
            "forca_g": _int(n, "ForcaG"),
            # violações separadas por ';' — ausentes quando não houve
            "estatisticas": [int(x) for x in re.findall(r"\d+", est)],
        })
    return out


def telemetria_relatorio() -> dict:
    """O resumo de D-1 de todos os veículos com informação.

    As unidades ficam COMO VIERAM, e o nome do campo diz a medida: a
    `distancia` chega em QUILÔMETROS (medido: bate com `odmFim - odmIni`),
    apesar de o manual dizer metros; horímetro e utilização em minutos."""
    raiz = _pedir("RequestTelemetriaRelatorio", "ResponseTelemetriaRelatorio",
                  f"<tID>{TELEMETRIA_TID}</tID>")
    data = None
    dh = raiz.find(".//DataHoraRelatorio")
    if dh is not None:
        data = _txt(dh, "dtHr")
    linhas = []
    for n in raiz.findall(".//Relatorio"):
        if _int(n, "veiID") is None:
            continue
        linhas.append({
            "veiculo_id": _int(n, "veiID"),
            "distancia_km": _num(n, "distancia"),
            "vel_media": _num(n, "velMedia"), "vel_max": _num(n, "velMax"),
            "horimetro_ini_min": _int(n, "horIni"), "horimetro_fim_min": _int(n, "horFim"),
            "utilizacao_min": _int(n, "utilizacao"),
            "odometro_ini": _num(n, "odmIni"), "odometro_fim": _num(n, "odmFim"),
            "media_consumo": _num(n, "mediaConsumo"),
            "consumo_hora_motor": _num(n, "consHoraMotor"),
            "rpm_medio": _int(n, "rpmMedio"), "rpm_max": _int(n, "rpmMax"),
            "temp_media": _num(n, "tempMedia"), "temp_max": _num(n, "tempMax"),
            "motor_ligado_min": _int(n, "totalMotorLig"),
            "motor_desligado_min": _int(n, "totalMotorDeslig"),
            "motor_ligado_movimento_min": _int(n, "totalMotorLigMov"),
            "motor_ligado_parado_min": _int(n, "totalMotorLigPar"),
        })
    return {"data": data, "veiculos": linhas}
