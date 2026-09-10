# -*- coding: utf-8 -*-
"""Ponto Certificado — o REP-P em nuvem onde a batida nasce.

POR QUE ESTE MÓDULO EXISTE
==========================
O Globus lê este mesmo fornecedor, mas SÓ pelo AFD (`GeraAFDmodeloREPP`), e o
AFD é o formato legal da Portaria 671: NSR, data/hora, CPF, hash. Ele não tem
coordenada, não tem local, não tem atividade — por desenho, porque existe para
ser inviolável, não para ser rico.

E a importação do AFD no Globus é MANUAL: mediana de 3 dias entre execuções,
máximo de 18, uma única pessoa executando. Medido em 09/09/2026.

Aqui a batida chega em **10 segundos** (mediana medida entre `DataMarcacao` e
`DataInsercao`, 875 marcações de 7 dias), com coordenada, local e cerca. É
outro contrato do mesmo fornecedor, não outro fornecedor.

O QUE FOI MEDIDO CONTRA O SERVIÇO REAL (09/09/2026, API 3.0.2.0)
================================================================
875 marcações de 02/09 a 08/09, 30 cercas, 378 relógios cadastrados:

    GPS presente ......... 414 de 875 (47%)
    latência .............  10 s (mediana) · 64 s (p90)
    página do cursor ..... 1.000 marcações, devolvidas em 0,8 s

SEIS ARMADILHAS, TODAS VISTAS NO CORPO REAL
===========================================
1. **`FlagForaCerca` é SEMPRE `false`** — nas 875, sem exceção, inclusive nas
   679 que o próprio fornecedor rotula "FORA DE CERCA" em `DescricaoLocal`.
   O booleano não é usado; quem carrega a resposta é o TEXTO. Confiar no flag
   daria "nenhuma batida fora" para sempre, que é o pior tipo de verde.
2. **Sem GPS o fornecedor rotula "FORA DE CERCA"** — e isso é ausência, não
   infração. Onde o local É identificado, o GPS está presente em 100% dos
   casos; nas "fora de cerca", em 32%. Por isso `situacao()` tem TRÊS estados,
   e `SEM_COORDENADA` nunca vira alarme.
3. **Data vem em formato .NET**: `/Date(1788878539000-0300)/` — epoch em
   milissegundos mais o deslocamento. `datetime.fromisoformat` não lê.
4. **O cursor NÃO aceita zero.** `SelecionaMarcacoesPosteriorIdInformado(0)`
   devolve lista VAZIA (não o histórico), e `SelecionaMarcacaoPorIDLimite(0,3)`
   estoura o tempo limite. Carga inicial se faz por `marcacoes_por_periodo`;
   o cursor serve do segundo ciclo em diante.
5. **A página tem teto de 1.000** — `ultIdImportado=191476207` devolveu
   exatamente 1000. Quem parar na primeira página perde o resto em silêncio.
6. **A senha viaja no CORPO** de `StartSession`. Qualquer exceção que carregue
   o pedido vaza a credencial para o log — por isso `_limpar()` existe e todo
   erro passa por ele.

A CREDENCIAL
============
A ordem é: cofre da casa primeiro; e, enquanto não houver uma própria, a que o
Globus já usa (autorizada pelo dono em 09/09/2026). `credencial()` diz qual
está em uso — e a Saúde do Servidor mostra, porque credencial emprestada é
estado temporário que precisa aparecer, não sumir.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

BASE = "https://integrar.pontocertificado.com.br/Api.SVC"

# O token de sessão dura horas, mas o fornecedor não publica o prazo. Renovar a
# cada 50 min é barato (a chamada custa ~1 s) e evita descobrir a expiração no
# meio de uma coleta.
TTL_TOKEN = 50 * 60

# Teto de página do cursor, medido: uma chamada devolveu exatamente 1000.
PAGINA = 1000

# Os três estados de uma batida. O terceiro é o mais comum e o que o sistema
# antigo tratava como o segundo.
DENTRO, FORA, SEM_COORDENADA = "dentro", "fora", "sem_coordenada"

# O texto com que o fornecedor marca o que não caiu em cerca nenhuma.
ROTULO_FORA = "FORA DE CERCA"

_sessao: dict = {"token": None, "em": 0.0, "origem": None}
_trava = threading.Lock()


class PontoCertificadoIndisponivel(RuntimeError):
    """O fornecedor não respondeu, ou respondeu o que não sabemos ler."""


class NaoConfigurado(RuntimeError):
    """Sem credencial. Não é falha: é instalação incompleta."""


# ── credencial ──────────────────────────────────────────────────────────────
def _do_cofre() -> dict | None:
    try:
        from api import credenciais
        chave = credenciais.ler("PONTOCERT_CHAVE_EMPRESA")
        usuario = credenciais.ler("PONTOCERT_USUARIO")
        senha = credenciais.ler("PONTOCERT_SENHA")
        if chave and usuario and senha:
            return {"chave": chave, "usuario": usuario, "senha": senha,
                    "origem": "cofre"}
    except Exception:  # noqa: BLE001
        pass
    return None


def _do_globus() -> dict | None:
    """A credencial que o Globus já usa.

    EMPRESTADA, e de propósito visível: ela está em texto claro na tabela do
    ERP e no log de requisição dele. Vale enquanto não há uma própria, e a
    Saúde diz que é esta que está em uso para que a troca não seja esquecida.
    """
    try:
        from api import db_folha
        if not db_folha.configured():
            return None
        r = db_folha.query(
            """SELECT chaveempresa, usuario, senha FROM globus729.frq_pontocertificado
                WHERE codigoempresa = 1 AND tokengerado IS NOT NULL
                ORDER BY codigofg FETCH FIRST 1 ROWS ONLY""")
        if r:
            return {"chave": r[0]["chaveempresa"], "usuario": r[0]["usuario"],
                    "senha": r[0]["senha"], "origem": "globus"}
    except Exception as exc:  # noqa: BLE001
        log.warning("ponto certificado: credencial do Globus indisponivel: %s",
                    type(exc).__name__)
    return None


def credencial() -> dict | None:
    return _do_cofre() or _do_globus()


def configurado() -> bool:
    return credencial() is not None


def o_que_falta() -> str:
    if configurado():
        return ""
    return ("Falta a credencial do Ponto Certificado (PONTOCERT_CHAVE_EMPRESA, "
            "PONTOCERT_USUARIO e PONTOCERT_SENHA, em Integrações) — e o banco "
            "da folha, de onde sai a credencial emprestada, também não respondeu.")


# ── o que nunca pode vazar ──────────────────────────────────────────────────
def _limpar(texto: str) -> str:
    """Tira credencial e token de qualquer texto que vá para log ou tela.

    A senha viaja no corpo de `StartSession` e o token tem 1.216 caracteres —
    os dois cabem inteiros numa mensagem de exceção.
    """
    t = str(texto)
    t = re.sub(r'("senha"\s*:\s*)"[^"]*"', r'\1"***"', t)
    t = re.sub(r'("usuario"\s*:\s*)"[^"]*"', r'\1"***"', t)
    t = re.sub(r'("chaveEmpresa"\s*:\s*)"[^"]*"', r'\1"***"', t)
    t = re.sub(r'("?tokenAcesso"?\s*[:=]\s*)"?[A-Za-z0-9+/=]{40,}"?', r'\1"***"', t)
    t = re.sub(r"[A-Za-z0-9+/=]{200,}", "<token>", t)
    return t[:400]


# ── a data que o .NET escreve ───────────────────────────────────────────────
_DATA = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")


def data_dotnet(bruto: str | None) -> datetime | None:
    """`/Date(1788878539000-0300)/` → datetime no fuso declarado.

    O deslocamento vem no próprio valor e NÃO se aplica ao epoch (que já é
    UTC): ele diz em que fuso o registro foi feito. Somar o offset ao epoch
    deslocaria toda a série em três horas — e ninguém repara, porque continua
    parecendo hora de trabalho.
    """
    if not bruto:
        return None
    m = _DATA.search(str(bruto))
    if not m:
        return None
    quando = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
    if m.group(2):
        sinal = 1 if m.group(2)[0] == "+" else -1
        fuso = timezone(sinal * timedelta(hours=int(m.group(2)[1:3]),
                                          minutes=int(m.group(2)[3:5])))
        return quando.astimezone(fuso)
    return quando


# ── a conversa ──────────────────────────────────────────────────────────────
def _post(metodo: str, corpo: dict, timeout: int = 90) -> object:
    from api import tls
    dados = json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/{metodo}", data=dados, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=tls.contexto()) as r:
            texto = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise PontoCertificadoIndisponivel(
            f"{metodo}: HTTP {exc.code}") from None
    except Exception as exc:  # noqa: BLE001
        # O TIPO da exceção, nunca o texto: ele carrega a URL e o corpo.
        raise PontoCertificadoIndisponivel(
            f"{metodo}: {type(exc).__name__}") from None
    if not texto.strip():
        return None
    try:
        return json.loads(texto).get("d")
    except (ValueError, AttributeError):
        # HTML de erro do IIS, tipicamente. O corpo pode conter o pedido.
        raise PontoCertificadoIndisponivel(
            f"{metodo}: resposta ilegível — {_limpar(texto[:120])}") from None


def token() -> str:
    """Token de sessão, renovado sob trava (uma renovação por processo)."""
    with _trava:
        agora = time.time()
        if _sessao["token"] and agora - _sessao["em"] < TTL_TOKEN:
            return _sessao["token"]
        cred = credencial()
        if not cred:
            raise NaoConfigurado(o_que_falta())
        t = _post("StartSession", {"chaveEmpresa": cred["chave"],
                                   "usuario": cred["usuario"],
                                   "senha": cred["senha"]}, timeout=60)
        if not t or not isinstance(t, str):
            raise PontoCertificadoIndisponivel("StartSession nao devolveu token")
        _sessao.update(token=t, em=agora, origem=cred["origem"])
        return t


def _chamar(metodo: str, corpo: dict, timeout: int = 90) -> object:
    return _post(metodo, dict(corpo, tokenAcesso=token()), timeout=timeout)


# ── a leitura da batida ─────────────────────────────────────────────────────
def situacao(m: dict) -> str:
    """DENTRO, FORA ou SEM_COORDENADA — nesta ordem de decisão.

    NÃO usa `FlagForaCerca`: medido nas 875 marcações de 7 dias, ele é `false`
    em 100% delas, inclusive nas 679 que o próprio fornecedor rotula
    "FORA DE CERCA". Quem responde é o texto de `DescricaoLocal`.

    E a ausência de coordenada vem ANTES de "fora": sem GPS o fornecedor
    rotula "FORA DE CERCA" por padrão, e chamar isso de infração foi o que
    encheu o alarme antigo — 53% das batidas não trazem coordenada.
    """
    lat, lon = (m.get("GPSLatitude") or "").strip(), (m.get("GPSLongitude") or "").strip()
    if lat in ("", "0") or lon in ("", "0"):
        return SEM_COORDENADA
    local = (m.get("DescricaoLocal") or "").strip().upper()
    return FORA if local == ROTULO_FORA or not local else DENTRO


#: A chapa do ERP tem 6 dígitos. `zfill` não trunca: matrícula maior passa
#: inteira, e é isso que se quer — o dia em que o cadastro crescer, o
#: casamento continua valendo.
TAMANHO_MATRICULA = 6


def _matricula(bruto) -> str | None:
    """Zeros à esquerda, para casar com a `chapafunc` do ERP."""
    t = (bruto or "").strip()
    if not t:
        return None
    return t.zfill(TAMANHO_MATRICULA) if t.isdigit() else t


def normalizar(m: dict) -> dict:
    """O corpo do fornecedor no formato da casa, com a situação já decidida."""
    lat, lon = (m.get("GPSLatitude") or "").strip(), (m.get("GPSLongitude") or "").strip()
    sit = situacao(m)
    marcada = data_dotnet(m.get("DataMarcacao"))
    inserida = data_dotnet(m.get("DataInsercao"))
    return {
        "id": int(m.get("id") or 0),
        "nsr": int(m.get("NSR") or 0),
        "cpf": (m.get("CPF") or "").strip() or None,
        "pis": (m.get("PIS") or "").strip() or None,
        # MATRICULA NORMALIZADA COM ZEROS A ESQUERDA. O fornecedor devolve os
        # dois formatos: medido em 09/09/2026, 54 pessoas vinham como "003792"
        # e 31 como "3878" — 36% do quadro. A chapa do ERP tem 6 dígitos, e sem
        # o `zfill` o casamento falha JUSTAMENTE para essas 31: a batida entra,
        # o nome não aparece, e a tela mostra "(não encontrado)" sem erro nenhum.
        "matricula": _matricula(m.get("MatriculaFuncionario")),
        "trabalhador_id": m.get("TrabalhadorId"),
        "marcada_em": marcada.isoformat() if marcada else None,
        "inserida_em": inserida.isoformat() if inserida else None,
        "latencia_s": int((inserida - marcada).total_seconds())
                      if (marcada and inserida) else None,
        # `Atividade` vem VAZIA em 65% das marcações (570 de 875): entrada,
        # saída e intervalo só aparecem quando o app pergunta. Vazio é vazio,
        # não "entrada".
        "atividade": (m.get("Atividade") or "").strip() or None,
        "relogio": (m.get("NumSerieRelogio") or "").strip() or None,
        "situacao": sit,
        "local": (m.get("NomeLocal") or "").strip() or None,
        "local_descricao": (m.get("DescricaoLocal") or "").strip() or None,
        "id_local": int(m.get("IdLocal") or 0) or None,
        "lat": float(lat) if sit != SEM_COORDENADA else None,
        "lon": float(lon) if sit != SEM_COORDENADA else None,
    }


# ── as chamadas que a casa usa ──────────────────────────────────────────────
def marcacoes_desde(ultimo_id: int, timeout: int = 180) -> list[dict]:
    """Marcações com id MAIOR que `ultimo_id`, já normalizadas.

    O CURSOR NÃO ACEITA ZERO: `ultIdImportado=0` devolve lista vazia — não o
    histórico. Quem chamar com 0 acha que não há nada e grava um cursor que
    nunca anda. A carga inicial é `marcacoes_por_periodo`.

    Devolve no máximo `PAGINA` por chamada; quem consome repete enquanto vier
    página cheia.
    """
    if not ultimo_id:
        raise ValueError(
            "marcacoes_desde exige um id real: o fornecedor devolve vazio para "
            "0. Para a primeira carga use marcacoes_por_periodo().")
    bruto = _chamar("SelecionaMarcacoesPosteriorIdInformado",
                    {"ultIdImportado": int(ultimo_id)}, timeout=timeout) or []
    return [normalizar(m) for m in bruto]


def marcacoes_por_periodo(inicio: str, fim: str, relogio: str = "",
                          matricula: str = "", timeout: int = 180) -> list[dict]:
    """Marcações de um período. Datas em DD/MM/AAAA — o formato do fornecedor.

    É o caminho da PRIMEIRA carga, porque o cursor não parte do zero.
    """
    bruto = _chamar("SelecionaMarcacoes",
                    {"numSerieRelogio": relogio, "matriculaFuncionario": matricula,
                     "dataInicio": inicio, "dataFim": fim}, timeout=timeout) or []
    return [normalizar(m) for m in bruto]


def cercas(timeout: int = 60) -> list[dict]:
    """As cercas cadastradas no fornecedor.

    DUAS FORMAS, e a diferença importa: `Tipo` "1" é CÍRCULO e usa `Raio`;
    `Tipo` "2" é POLÍGONO, vem com `Raio` "0" e várias linhas com o mesmo
    `IdCerca` — cada linha é um vértice. Tratar polígono como círculo de raio
    zero reprova toda batida da unidade.
    """
    bruto = cercas_brutas(timeout=timeout)
    saida = []
    for c in bruto:
        try:
            lat, lon = float(c.get("Latitude")), float(c.get("Longitude"))
        except (TypeError, ValueError):
            continue
        saida.append({
            "id_cerca": int(c.get("IdCerca") or 0),
            "id_local": int(c.get("IdLocal") or 0),
            "nome": (c.get("NomeCerca") or "").strip(),
            "descricao": (c.get("DescricaoCerca") or "").strip(),
            "endereco": (c.get("Local") or "").strip(),
            "forma": "poligono" if str(c.get("Tipo")) == "2" else "circulo",
            "raio_m": float(c.get("Raio") or 0),
            "lat": lat, "lon": lon,
            # "False"/"True" chegam como TEXTO, não booleano.
            "ativa": str(c.get("StatusCerca")).strip().lower() == "true",
            "local_ativo": str(c.get("StatusLocal")).strip().lower() == "true",
        })
    return saida


def cercas_brutas(timeout: int = 60) -> list[dict]:
    return _chamar("ListarCercas", {}, timeout=timeout) or []


def versao_api(timeout: int = 30) -> str | None:
    """Não exige token — serve de ping honesto do fornecedor."""
    try:
        req = urllib.request.Request(f"{BASE}/VersionApi",
                                     headers={"Accept": "application/json"})
        from api import tls
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=tls.contexto()) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("VersionApiResult")
    except Exception as exc:  # noqa: BLE001
        log.warning("ponto certificado: ping falhou: %s", type(exc).__name__)
        return None


def diagnostico() -> dict:
    """Para a Saúde do Servidor. Nunca levanta, e nunca imprime credencial."""
    cred = credencial()
    d = {"configurado": bool(cred),
         "origem_credencial": (cred or {}).get("origem"),
         "versao_api": None, "erro": None}
    if not cred:
        d["erro"] = o_que_falta()
        return d
    try:
        d["versao_api"] = versao_api()
    except Exception as exc:  # noqa: BLE001
        d["erro"] = _limpar(f"{type(exc).__name__}")
    return d
