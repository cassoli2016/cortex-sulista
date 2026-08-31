"""Cliente da API REST da Smartec (https://sistema.smartec.com.br).

DE ONDE VEIO O CONTRATO
=======================
Da própria spec do fornecedor, em `/swagger/docs/v1` — a página
`/swagger/ui/index` é só o shell da SPA e devolve o título, como na RasterJOR.

E aqui vale uma lição que custou quatro rodadas de adivinhação: **o campo
`Tipo`, que escolhe a operação de cada endpoint, NÃO está no schema.** O schema
diz apenas `Tipo: string, "Tipo de requisição que será feita"`. Os valores
válidos estão no campo `description` do PATH, em markdown, e eu fiquei
chutando ("Listar", "Consultar", "1".."10") com o arquivo já baixado no disco.
Ao ler spec de fornecedor, ler `description` de path e de operação ANTES de
inferir qualquer coisa — o schema é o que a ferramenta gerou, a descrição é o
que a pessoa escreveu.

TRÊS COISAS QUE SÓ APARECEM CHAMANDO
====================================
1. **HTTP 403 sem `User-Agent`.** O `curl` passa e o `urllib` não, porque o
   `urllib` se anuncia como `Python-urllib/3.13` e algo no caminho recusa. O
   sintoma é cruel: a mesma requisição funciona no terminal e falha no código,
   o que manda procurar defeito no código. `CABECALHOS` abaixo resolve, e não
   é enfeite — sem ele a integração inteira não sobe.

2. **`IdErro 2000 "NENHUM DADO ENCONTRADO"` chega como HTTP 400.** É VAZIO, não
   é falha: foi assim que CIV, EMTU e RNTRC responderam nesta conta, que
   simplesmente não usa esses produtos. Um cliente que trata 400 como erro faz
   o painel acusar integração quebrada em três recursos que estão perfeitos, e
   isso é a mesma família do `error` descritivo da Z-API — a regra que
   sobrevive é ler o CORPO, não o status. Ver `VAZIO`.

3. **O token vai no CORPO de cada requisição, não em cabeçalho.** Isso é melhor
   que a Z-API (a URL não é a credencial, então registrar a URL é inofensivo),
   mas exige o cuidado inverso: o corpo NUNCA pode ser logado inteiro, e
   `_sanitizar` varre o token de qualquer texto que saia daqui.

O QUE O ERP JÁ FAZ, E O QUE ELE DEIXA NA MESA
=============================================
O AVA tem a integração cadastrada (`integracao.cadastrointegracao` id=3,
`tipointegracao` 32) com UM processo habilitado: o 8, "Importar Infração".
Ele traz a multa para `infracaotransito_registro` e para por aí. Medido em
31/08/2026, das 212 multas em aberto na Smartec:

  - 206 já estavam no ERP e 6 não;
  - **64 estavam no ERP SEM VALOR**, e a Smartec sabe o valor de todas;
  - **28 a Smartec dá como PAGAS e o ERP tem `dtliquidacao` em ZERO delas.**

O último item é a explicação do "pagas em 0" que a tela de Multas exibia e que
se lia como "ninguém paga multa aqui": a baixa não volta para o ERP. E os
outros onze recursos da API (CNH e toxicológico, licenciamento, IPVA,
restrições, cronotacógrafo, ANTT, licenças) o ERP não lê de forma alguma.

SOMENTE LEITURA, POR DECISÃO
============================
O catálogo abaixo tem `escreve: True` em `INDICAR`, `EXCLUIR INDICACAO`,
`CADASTRAR` e afins, e `chamar()` os RECUSA. Não é que sejam difíceis: indicar
condutor atinge o órgão autuador e o prontuário de uma pessoa, e uma ação
dessas não entra junto com a estreia de um conector de leitura. Deixá-los
listados e bloqueados (em vez de fora do catálogo) é deliberado — é o catálogo
que documenta o que existe, e apagar o que não se usa faz o próximo achar que
não existe.
"""
from __future__ import annotations

import json as _json
import logging
import ssl
import time
import urllib.error
import urllib.request

from api import tls as _tls

from .. import credenciais

log = logging.getLogger(__name__)

BASE = "https://sistema.smartec.com.br"
TIMEOUT = 90

# Sem isto a API devolve 403. Ver o cabeçalho do módulo.
CABECALHOS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Cortex-Sulista/1.0",
}

# `IdErro` que significa AUSÊNCIA DE DADO, não falha. Chega com HTTP 400.
VAZIO = 2000
# `IdErro` de tipo não reconhecido — quase sempre erro de programação nosso.
TIPO_INVALIDO = 1080


class SmartecErro(RuntimeError):
    """Falha ao falar com a Smartec. A mensagem já vem sanitizada."""


class SmartecNaoConfigurado(SmartecErro):
    """Falta o token. Instalação incompleta, não falha de integração."""


class SmartecRecusa(SmartecErro):
    """A Smartec respondeu e disse NÃO, com um motivo que a pessoa precisa ler.

    Separada de `SmartecErro` porque o conserto é outro: aqui o CÓRTEX
    funcionou e o fornecedor recusou (documento inválido, órgão sem adesão ao
    SNE, acesso expirado). Vira 4xx na rota, nunca 5xx — o Cloudflare troca o
    corpo das respostas 5xx da origem pela página de erro dele, e a mensagem
    que a pessoa precisava ler nunca cruzaria o túnel.
    """


# ─────────────────────────────────────────────────────────── catálogo
#
# `Tipo` × endpoint, LIDOS DAS DESCRIÇÕES da spec (não do schema — ver o
# cabeçalho). `chave` é o nome curto que o resto do CÓRTEX usa; `frota: True`
# marca o que devolve a frota inteira numa chamada só, que é o que permite
# varrer sem multiplicar requisição por veículo.
CATALOGO: dict[str, dict] = {
    # ---- infrações -------------------------------------------------------
    "veiculos_com_multa": {
        "endpoint": "Infracoes", "tipo": "VEICULOS MULTAS SNE DETRAN",
        "frota": True,
        "doc": "Veículos com multa em aberto (SNE + DETRAN)."},
    "veiculos_com_notificacao": {
        "endpoint": "Infracoes", "tipo": "VEICULOS NOTIFICACOES SNE DETRAN",
        "frota": True, "campos": ("DataPesquisa",),
        "doc": "Veículos com notificação a partir da data de pesquisa."},
    "multas": {
        "endpoint": "Infracoes", "tipo": "MULTAS SNE DETRAN",
        "campos": ("Renavam",),
        "doc": "Multas em aberto de um renavam."},
    "notificacoes": {
        "endpoint": "Infracoes", "tipo": "NOTIFICACOES SNE DETRAN",
        "campos": ("Renavam", "DataPesquisa"),
        "doc": "Notificações de um renavam a partir da data."},
    # ---- veículos --------------------------------------------------------
    "veiculos": {
        "endpoint": "Veiculo", "tipo": "CADASTRADOS", "frota": True,
        "doc": "Todos os veículos cadastrados na Smartec."},
    "veiculo": {
        "endpoint": "Veiculo", "tipo": "CONSULTAR",
        "campos": ("Renavam", "DataBase"),
        "doc": "Características de um veículo (chassi, cor, licenciamento)."},
    # ---- consultas de referência ----------------------------------------
    "orgaos": {
        "endpoint": "Consultas", "tipo": "ORGAO", "frota": True,
        "doc": "Catálogo de órgãos autuadores."},
    "infracoes_ctb": {
        "endpoint": "Consultas", "tipo": "INFRACOES", "frota": True,
        "doc": "Catálogo de infrações do CTB com valor, pontos e gravidade."},
    "orgaos_sne": {
        "endpoint": "Consultas", "tipo": "ORGAOS ADESOS SNE", "frota": True,
        "doc": "Órgãos adesos ao SNE — só eles aceitam boleto e indicação."},
    "acessos_sne": {
        "endpoint": "Consultas", "tipo": "CADASTROS SNE", "frota": True,
        "doc": "Status e VENCIMENTO do acesso de cada CNPJ ao SENATRAN/SNE."},
    "acessos_antt": {
        "endpoint": "Consultas", "tipo": "CADASTROS ANTT", "frota": True,
        "doc": "Status e vencimento do acesso ANTT por CNPJ."},
    # ---- documentação da frota ------------------------------------------
    "licencas": {
        "endpoint": "Licencas", "tipo": "RESUMO", "frota": True,
        "campos": ("Pagina",), "pagina": True,
        "doc": "Vencimento de cronotacógrafo, EMTU, CSV, CIV e CIPP/CTPP."},
    "licenciamento_calendario": {
        "endpoint": "Licenciamento", "tipo": "CALENDARIO", "frota": True,
        "doc": "Mês de licenciamento de cada veículo."},
    "licenciamento_valor": {
        "endpoint": "Licenciamento", "tipo": "VALOR",
        "campos": ("Renavam", "DataBase"),
        "doc": "Taxa de licenciamento em aberto (sem IPVA e DPVAT)."},
    "ipva": {
        "endpoint": "Ipva", "tipo": "CONSULTA",
        "campos": ("Renavam", "DataBase"),
        "doc": "Cota única do IPVA."},
    "restricoes": {
        "endpoint": "Restricoes", "tipo": None,
        "campos": ("Renavam", "DataBase"),
        "doc": "Bloqueios e restrições (Renajud, Senatran, roubo, recall)."},
    "cronotacografo": {
        "endpoint": "Cronotacografo", "tipo": "CONSULTAR",
        "campos": ("Renavam",),
        "doc": "Certificado do cronotacógrafo no INMETRO."},
    "antt": {
        "endpoint": "Antt", "tipo": "CONSULTAR", "frota": True,
        "campos": ("DataEmissao", "Pagina"), "pagina": True,
        "doc": "Autuações da ANTT por data de emissão do PDF."},
    # ---- ESCRITA: listados de propósito, e bloqueados --------------------
    "indicar_condutor": {
        "endpoint": "Infracoes", "tipo": "INDICAR", "escreve": True,
        "doc": "Indica o condutor ao órgão autuador."},
    "excluir_indicacao": {
        "endpoint": "Infracoes", "tipo": "EXCLUIR INDICACAO", "escreve": True,
        "doc": "Desfaz a indicação de condutor."},
    "gerar_fici": {
        "endpoint": "Infracoes", "tipo": "GERAR FICI", "escreve": True,
        "doc": "PDF do Formulário de Indicação do Condutor Infrator."},
    "cadastrar_veiculo": {
        "endpoint": "Veiculo", "tipo": "CADASTRAR", "escreve": True,
        "doc": "Cadastra veículo na Smartec."},
    "cadastrar_cnh": {
        "endpoint": "Cnh", "tipo": "CADASTRAR", "escreve": True,
        "doc": "Cadastra condutor para monitoramento de CNH."},
    "consultar_cnh": {
        "endpoint": "Cnh", "tipo": "CONSULTAR",
        "campos": ("Cpf", "DataBase"),
        "doc": "Vencimento da CNH e do exame toxicológico."},
}


def _token() -> str:
    """O token da Smartec, lido do cofre. Sem valor padrão.

    HOJE ELE É O MESMO DO ERP, e isso é decisão declarada do usuário
    (31/08/2026), não descuido. Vale saber a consequência, que é operacional e
    não técnica: **a credencial é um ponto único**. Se este token for revogado
    ou expirar, cai junto a importação de infrações do AVA
    (`integracao.cadastrointegracao` id=3), que é a fonte da tela de Multas —
    e o sintoma lá vai ser "parou de chegar multa", não "token inválido".

    Trocar por um token próprio depois é só colar outro valor no cofre; não há
    nada em código amarrado a isso. O módulo nunca LÊ o token do ERP: quem o
    fornece é `data/credenciais.json`, e o fato de os dois valores coincidirem
    hoje é configuração, não acoplamento.
    """
    tok = (credenciais.ler("SMARTEC_TOKEN") or "").strip()
    if not tok:
        raise SmartecNaoConfigurado(
            "Token da Smartec não configurado. Gestão › Credenciais › "
            "SMARTEC_TOKEN.")
    return tok


def configurado() -> bool:
    """Ausência de token NÃO é falha: é instalação incompleta.

    A Saúde marca `info` e diz o campo que falta, em vez de vermelho — alarme
    que acende sem haver problema ensina a ignorar o alarme.
    """
    try:
        _token()
        return True
    except SmartecNaoConfigurado:
        return False


def _sanitizar(texto: str) -> str:
    """Tira o token de qualquer texto que saia deste módulo.

    O token vai no CORPO, então ele não aparece em URL de exceção como na
    Z-API — mas aparece se alguém logar o payload, e o payload é a primeira
    coisa que se loga ao depurar. A limpeza é aqui, no limite do módulo, para
    não depender de cada chamador lembrar.
    """
    if not texto:
        return texto
    try:
        tok = _token()
    except SmartecNaoConfigurado:
        return texto
    if tok:
        texto = texto.replace(tok, "***")
    return texto


def _ctx() -> ssl.SSLContext:
    return _tls.contexto()


def _corpo_erro(payload) -> tuple[bool, str]:
    """Lê a resposta de erro da Smartec. Devolve (é_vazio, mensagem).

    O formato é `[{"IdErro": 2000, "Message": "NENHUM DADO ENCONTRADO"}]` —
    uma LISTA de erros, porque a API valida tudo de uma vez e devolve todos os
    problemas juntos. Isso é bom: a mensagem diz os cinco campos errados em
    vez de um por vez.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return False, str(payload)[:300]
    ids = {e.get("IdErro") for e in payload if isinstance(e, dict)}
    msgs = [str(e.get("Message") or "").strip()
            for e in payload if isinstance(e, dict)]
    msgs = [m for m in msgs if m]
    if ids == {VAZIO}:
        return True, "; ".join(msgs)
    return False, "; ".join(msgs) or str(payload)[:300]


def chamar(chave: str, **campos) -> list | dict:
    """Executa uma operação do catálogo.

    Devolve o corpo já decodificado. Resposta que significa "não há dado"
    volta como LISTA VAZIA, nunca como exceção — ver `VAZIO`.
    """
    op = CATALOGO.get(chave)
    if op is None:
        raise SmartecErro(f"Operação desconhecida: {chave}")
    if op.get("escreve"):
        raise SmartecRecusa(
            f"A operação '{chave}' escreve no sistema da Smartec e no órgão "
            f"autuador. O conector do CÓRTEX é somente leitura.")

    corpo = {"Token": _token()}
    if op.get("tipo"):
        corpo["Tipo"] = op["tipo"]
    corpo.update({k: v for k, v in campos.items() if v is not None})

    url = f"{BASE}/api/{op['endpoint']}"
    dados = _json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(url, data=dados, headers=CABECALHOS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx()) as r:
            bruto = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        texto = ""
        try:
            texto = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        try:
            payload = _json.loads(texto) if texto else None
        except ValueError:
            payload = None
        if payload is not None:
            vazio, msg = _corpo_erro(payload)
            if vazio:
                # "NENHUM DADO ENCONTRADO" não é falha. Ver o cabeçalho.
                return []
            raise SmartecRecusa(_sanitizar(msg)) from None
        raise SmartecErro(
            f"HTTP {exc.code} da Smartec em {op['endpoint']}") from None
    except urllib.error.URLError as exc:
        raise SmartecErro(
            f"Não foi possível falar com a Smartec: "
            f"{_sanitizar(str(exc.reason))}") from None
    except TimeoutError:
        raise SmartecErro(
            f"A Smartec não respondeu em {TIMEOUT}s ({op['endpoint']}).") from None

    try:
        payload = _json.loads(bruto) if bruto.strip() else []
    except ValueError:
        raise SmartecErro(
            f"A Smartec devolveu resposta ilegível em {op['endpoint']}."
        ) from None

    # 200 com corpo de erro dentro: acontece, e a regra da casa é ler o CORPO.
    if isinstance(payload, list) and payload and isinstance(payload[0], dict) \
            and "IdErro" in payload[0]:
        vazio, msg = _corpo_erro(payload)
        if vazio:
            return []
        raise SmartecRecusa(_sanitizar(msg))
    return payload


def paginar(chave: str, teto: int = 200, **campos) -> list:
    """Percorre um recurso paginado até acabar.

    Dois envelopes diferentes na MESMA API, e por isso os dois são tratados:
    `Licencas` devolve `{"HaMais": "NÃO", "Quantidade": n, "Valores": [...]}`
    (com o "NÃO" acentuado, em texto) e `Antt` devolve
    `{"HaMais": false, "Contagem": n, "Tabela": [...]}` (booleano). Assumir um
    formato só faria metade dos recursos parar na primeira página em silêncio.

    `teto` existe para que um `HaMais` que nunca vira falso não vire laço
    infinito puxando a mesma página para sempre.
    """
    itens: list = []
    pagina = 0
    while pagina < teto:
        campos["Pagina"] = str(pagina)
        resp = chamar(chave, **campos)
        if isinstance(resp, list):
            itens.extend(resp)
            break  # array puro: não pagina
        if not isinstance(resp, dict):
            break
        lote = resp.get("Valores") or resp.get("Tabela") or []
        itens.extend(lote)
        mais = resp.get("HaMais")
        if isinstance(mais, str):
            mais = mais.strip().upper() not in ("NÃO", "NAO", "N", "FALSE", "")
        if not mais or not lote:
            break
        pagina += 1
        time.sleep(0.15)
    return itens
