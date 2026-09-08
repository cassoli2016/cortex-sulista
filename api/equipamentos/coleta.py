# -*- coding: utf-8 -*-
"""A coleta: sincroniza o ERP e consulta a APIBrasil dentro da cota.

A ORDEM DAS FASES É DECISÃO DE QUEM OPERA, E É A ORDEM DO CUSTO
===============================================================
Frota própria (308) → agregados (122) → terceiros (1.016). As duas primeiras
somam 430 placas; a terceira sozinha é maior que as duas juntas. Consultar na
ordem inversa gastaria a cota do mês nos veículos sobre os quais a Sulista tem
menos poder de agir.

CADA CONSULTA CUSTA, E POR ISSO A COLETA TEM TRÊS FREIOS
========================================================
1. **A cota do dia** (`APIBRASIL_COTA_DIARIA`), contada em `eqp_consulta` —
   inclusive as chamadas que falharam, porque o fornecedor também as conta.
2. **A revalidação de 12 meses**: placa consultada há menos disso não é
   consultada de novo. Marca e chassi não mudam; gastar consulta para
   reconfirmá-los é gastar por nada.
3. **O produto não confirmado**: caminho inferido não entra em carga em massa.
   Sem esse freio, 1.446 placas contra um caminho errado gastam a cota inteira
   em 404 — e o erro só apareceria na fatura.

E UM QUARTO, QUE NÃO É FREIO MAS ECONOMIA: `pular_se_a_smartec_ja_tem`. A
Smartec cobre licenciamento e IPVA de 302 placas próprias e a cor de todas
elas. Consultar o CRLV dessas na APIBrasil é pagar duas vezes pelo mesmo fato.

RETOMÁVEL POR CONSTRUÇÃO
========================
A coleta grava CADA placa assim que a resposta chega, nunca ao fim do lote. Uma
queda no meio de 1.016 terceiros não pode significar recomeçar do zero — é a
mesma lição que o NSU da SEFAZ ensinou, e lá o recomeço tinha punição do
fornecedor. Aqui a punição é a fatura.
"""
from __future__ import annotations

import logging

from ..apibrasil import cliente as apib
from . import armazenamento as arm
from . import consolidacao, erp

log = logging.getLogger("cortex.equipamentos")

#: A ordem das fases. Muda aqui e muda em todo lugar que varre a frota.
FASES: tuple[str, ...] = ("proprio", "agregado", "terceiro")

#: Meses até uma placa valer nova consulta. Cadastro é quase estático — marca,
#: chassi e ano não mudam; o que muda é licenciamento e restrição.
REVALIDAR_MESES = 12


# ────────────────────────────────────────────────────────────────── o ERP

def sincronizar_erp() -> dict:
    """Traz a frota ativa do ERP para `eqp_fonte` e reconstrói o cadastro.

    É de graça (não gasta consulta paga) e é o que dá ao cadastro a sua base.
    Roda sozinha, sem depender de credencial nenhuma da APIBrasil — instalação
    sem token ainda tem cadastro de equipamentos, só que sem a parte do Detran.
    """
    linhas = erp.ler()
    gravadas = arm.gravar_fontes(erp.FONTE, linhas)
    resultado = consolidacao.reconstruir()
    log.info("equipamentos: %d do ERP, %d consolidados",
             gravadas, resultado["equipamentos"])
    return {"lidos_do_erp": gravadas, **resultado}


# ────────────────────────────────────────────────────────────── a APIBrasil

def cota_restante() -> int | None:
    """Quantas consultas ainda cabem hoje. `None` = sem teto configurado.

    `None` e `0` são coisas MUITO diferentes e nunca podem ser confundidos:
    `None` é "não sei o teto do plano, siga"; `0` é "acabou". Um `or` no lugar
    errado transformaria "sem teto" em "esgotado" e a coleta pararia calada.
    """
    from .. import credenciais
    bruto = (credenciais.ler("APIBRASIL_COTA_DIARIA") or "").strip()
    if not bruto:
        return None
    try:
        teto = int(bruto)
    except ValueError:
        log.warning("APIBRASIL_COTA_DIARIA nao e um numero; tratando como sem teto")
        return None
    return max(0, teto - arm.gastas_hoje())


def fila(produto: str, vinculo: str | None = None, *,
         limite: int | None = None) -> list[str]:
    """As placas que valem uma consulta AGORA, na ordem das fases.

    Sai do cadastro consolidado, não do ERP: é o cadastro que é a fonte da
    verdade do módulo, e no dia em que o ERP sair esta função não muda uma
    linha.
    """
    from .. import pglocal
    sql = ("SELECT placa, vinculo FROM eqp_equipamento"
           " WHERE ativo = true")
    params: list = []
    if vinculo:
        sql += " AND vinculo = %s"
        params.append(vinculo)
    sql += " ORDER BY placa"
    linhas = pglocal.query(sql, tuple(params) or None, esquema=arm.ESQUEMA)

    ultimas = arm.ultima_consulta_por_placa(produto)
    from datetime import datetime, timedelta, timezone
    corte = datetime.now(timezone.utc) - timedelta(days=30 * REVALIDAR_MESES)

    ordem = {v: i for i, v in enumerate(FASES)}
    candidatas = []
    for r in linhas:
        anterior = (ultimas.get(r["placa"]) or {}).get(produto)
        if anterior and anterior["quando"] and anterior["quando"] > corte:
            continue          # consultada há menos de 12 meses
        candidatas.append((ordem.get(r["vinculo"], 99), r["placa"]))
    candidatas.sort()
    placas = [p for _, p in candidatas]
    return placas[:limite] if limite else placas


def coletar(produto: str, *, vinculo: str | None = None,
            limite: int | None = None) -> dict:
    """Consulta a APIBrasil placa a placa, gravando cada uma na hora.

    Devolve o que aconteceu, com as três respostas separadas — e elas PRECISAM
    ficar separadas, porque significam coisas diferentes:

      · `gravadas`  — o Detran respondeu e o cadastro melhorou;
      · `sem_dado`  — o Detran NÃO CONHECE a placa. Não é falha: é um achado,
                      e dos bons. Placa ativa no ERP que o Detran desconhece é
                      cadastro furado (há um `ABC1234` com chassi
                      'AAABBBCCCDDD' na frota, para dar um exemplo real);
      · `falhas`    — o CÓRTEX ou a APIBrasil tropeçaram. Só isto é problema.

    Somar as três num "processadas: 300" apagaria justamente a informação pela
    qual se pagou.
    """
    if produto not in apib.CATALOGO:
        raise ValueError(f"produto desconhecido: {produto}")

    restante = cota_restante()
    if restante is not None and restante <= 0:
        return {"produto": produto, "gravadas": 0, "sem_dado": 0, "falhas": 0,
                "parou_por": "cota do dia esgotada", "cota_restante": 0}

    alvo = fila(produto, vinculo, limite=limite)
    if restante is not None:
        alvo = alvo[:restante]

    fora = {"produto": produto, "vinculo": vinculo, "gravadas": 0,
            "sem_dado": 0, "falhas": 0, "parou_por": None}
    tocadas: list[str] = []
    for placa in alvo:
        r = apib.consultar(produto, placa)
        arm.registrar_consulta(placa, produto, r["ok"], erro=r["erro"],
                               ms=r["ms"])
        if r["ok"]:
            campos = normalizar(produto, r["payload"])
            arm.gravar_fonte(placa, f"apibrasil.{produto}", campos,
                             r["payload"])
            tocadas.append(placa)
            fora["gravadas"] += 1
        elif r["sem_dado"]:
            fora["sem_dado"] += 1
        else:
            fora["falhas"] += 1
            # Falha em SEQUÊNCIA é outra coisa que falha isolada: token
            # revogado, cota estourada no fornecedor ou serviço fora do ar
            # gastam a fila inteira em erro. Parar cedo é o que impede a
            # coleta de queimar 1.016 chamadas contra uma porta fechada.
            if fora["falhas"] >= 5 and fora["gravadas"] == 0:
                fora["parou_por"] = ("cinco falhas seguidas sem nenhum "
                                     "sucesso — a coleta parou para não "
                                     "gastar a cota")
                break

    if tocadas:
        consolidacao.reconstruir(tocadas)
    fora["cota_restante"] = cota_restante()
    return fora


# ──────────────────────────────────────────────────────────── normalização
#
# O DE-PARA DA APIBRASIL — E A PARTE QUE AINDA NÃO FOI MEDIDA.
#
# A documentação pública da APIBrasil não publica o corpo da resposta: diz
# "marca, modelo, versão, chassi e muito mais". Escrever o de-para a partir
# disso seria escrever a partir de suposição, e **dublê montado a partir de
# suposição testa a suposição** — foi assim que o cartão de janelas do ERP
# ficou verde para sempre.
#
# Então o de-para é por CANDIDATOS: para cada campo do cadastro, os nomes
# plausíveis que a resposta pode usar, comparados sem caixa, sem acento e sem
# separador. É uma aposta declarada, não uma afirmação — e `sondar()` no
# cliente existe justamente para trocar a aposta por medição na primeira
# consulta real. O que a busca não achar fica guardado no `payload` de
# `eqp_fonte`, inteiro, e nada se perde.

_CANDIDATOS: dict[str, dict[str, tuple[str, ...]]] = {
    "dados": {
        "chassi": ("chassi", "chassis", "numerochassi"),
        "renavam": ("renavam", "codigorenavam"),
        "numero_motor": ("motor", "numeromotor", "numeromotordoveiculo"),
        "placa_anterior": ("placaanterior", "placaantiga"),
        "marca": ("marca", "fabricante", "marcamodelo"),
        "modelo": ("modelo", "submodelo"),
        "versao": ("versao", "version"),
        "ano_fabricacao": ("anofabricacao", "ano", "anofab"),
        "ano_modelo": ("anomodelo", "anomod"),
        "cor": ("cor", "corveiculo"),
        "combustivel": ("combustivel", "tipocombustivel"),
        "potencia_cv": ("potencia", "cv", "potenciacv"),
        "cilindrada": ("cilindrada", "cilindradas"),
        "especie": ("especie", "especieveiculo"),
        "tipo": ("tipo", "tipoveiculo", "tipodeveiculo"),
        "carroceria": ("carroceria", "tipocarroceria"),
        "eixos": ("eixos", "quantidadeeixos", "qtdeixos", "numeroeixos"),
        "tara_kg": ("tara",),
        "capacidade_carga_kg": ("capacidadecarga", "capcarga", "lotacao"),
        "pbt_kg": ("pbt", "pesobrutototal"),
        "cmt_kg": ("cmt", "capacidademaximatracao"),
        "uf": ("uf", "ufemplacamento", "ufveiculo", "estado"),
        "municipio": ("municipio", "cidade", "municipioemplacamento"),
        "situacao": ("situacao", "status", "situacaoveiculo"),
        "proprietario_doc": ("documentoproprietario", "cpfcnpjproprietario",
                             "docproprietario"),
        "proprietario_nome": ("proprietario", "nomeproprietario"),
    },
    "crlv": {
        "situacao": ("situacao", "status", "situacaoveiculo"),
        "crlv_exercicio": ("exercicio", "anoexercicio", "exerciciocrlv"),
        "crlv_vencimento": ("vencimento", "datavencimento",
                            "vencimentolicenciamento"),
        "licenciado": ("licenciado", "estalicenciado"),
        "tem_restricao": ("temrestricao", "restricao", "possuirestricao"),
        "restricoes": ("restricoes", "listarestricoes"),
    },
    "fipe": {
        "fipe_codigo": ("codigofipe", "fipe", "codigo"),
        "fipe_valor": ("valor", "preco", "valorfipe", "precomedio"),
        "fipe_referencia": ("referencia", "mesreferencia", "anoreferencia"),
        "marca": ("marca",),
        "modelo": ("modelo",),
    },
    "seguranca": {
        "tem_restricao": ("temrestricao", "restricao", "possuirestricao",
                          "roubofurto", "temrouboefurto"),
        "restricoes": ("restricoes", "ocorrencias", "historico"),
        "situacao": ("situacao", "status"),
    },
}


def _simples(texto: str) -> str:
    """Nome de campo sem acento, sem caixa e sem separador.

    `Ano Fabricação`, `ano_fabricacao` e `anoFabricacao` são o mesmo campo, e
    fornecedor nenhum é coerente entre endpoints.
    """
    import unicodedata
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn")
    return "".join(c for c in sem_acento.lower() if c.isalnum())


def _achatar(payload, prefixo: str = "") -> dict:
    """Aplaina o JSON aninhado num mapa `nome_simples -> valor`.

    A APIBrasil, como quase toda API brasileira de consulta, envelopa o
    resultado (`{"response": {"dados": {...}}}`). Procurar só no topo acharia
    zero campos e o cadastro nasceria vazio — sem erro nenhum, que é o pior
    jeito de nascer vazio.
    """
    fora: dict = {}
    if isinstance(payload, dict):
        for chave, valor in payload.items():
            simples = _simples(chave)
            if isinstance(valor, (dict, list)):
                fora.update(_achatar(valor, simples))
            elif simples not in fora:
                fora[simples] = valor
    elif isinstance(payload, list):
        for item in payload[:5]:
            fora.update(_achatar(item, prefixo))
    return fora


def normalizar(produto: str, payload) -> dict:
    """Do corpo da APIBrasil para os nomes de campo do cadastro.

    O que não casar com candidato nenhum NÃO se perde: `eqp_fonte.payload`
    guarda a resposta inteira, e um campo novo vira coluna relendo o que já
    está no banco — de graça, sem reconsultar 1.446 placas.
    """
    plano = _achatar(payload)
    fora: dict = {}
    for campo, candidatos in (_CANDIDATOS.get(produto) or {}).items():
        for candidato in candidatos:
            valor = plano.get(_simples(candidato))
            if valor is not None and valor != "":
                fora[campo] = valor
                break
    # A lista de restrições é jsonb e vem inteira, do payload cru — achatá-la
    # perderia a estrutura que a tela precisa para listar uma a uma.
    if produto in ("crlv", "seguranca") and isinstance(payload, dict):
        for chave in ("restricoes", "ocorrencias"):
            for k, v in payload.items():
                if _simples(k) == chave and isinstance(v, (list, dict)):
                    fora["restricoes"] = v
    return fora


def campos_nao_mapeados(produto: str, payload) -> list[str]:
    """O que a APIBrasil mandou e o cadastro ignorou.

    É o instrumento contra a lição da Gobrax — 14 indicadores devolvidos, 3
    lidos, e os outros 11 descobertos anos depois. A sonda e a Saúde mostram
    esta lista, então "sobrou campo" tem sintoma no dia UM, e não numa
    releitura futura que pode nunca acontecer.
    """
    plano = _achatar(payload)
    usados = set()
    for candidatos in (_CANDIDATOS.get(produto) or {}).values():
        usados.update(_simples(c) for c in candidatos)
    return sorted(k for k in plano if k not in usados)
