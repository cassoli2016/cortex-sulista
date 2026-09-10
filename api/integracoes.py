# -*- coding: utf-8 -*-
"""A Central de Integrações — um lugar por fornecedor, e não três.

POR QUE ESTA TELA EXISTE
========================

Hoje a resposta para "a integração X está bem?" mora em três lugares, e nenhum
deles responde a pergunta inteira:

1. **Gestão › Integrações** (`api/credenciais.py`) diz se está CONFIGURADA —
   qual modo de autenticação está completo, o que falta preencher. Não sabe se
   chegou dado.
2. **Saúde do Servidor** (`api/servidor.py`) diz se está CHEGANDO DADO — última
   coleta, idade, volume. Mas os cartões dos fornecedores dividem a tela com
   CPU, disco, GPU, bancos e túnel, e ali a pergunta é "o servidor está bem?".
3. **O código** sabe o que cada uma alimenta, e ninguém mais.

Uma integração pode estar configurada e parada há cinco dias. Pode estar
chegando dado com a credencial da premiação faltando. Nenhuma das duas telas
mostra as duas metades juntas, e é a JUNÇÃO que responde se dá para confiar no
número que a tela de Telemetria está mostrando agora.

Este módulo é a junção. Ele não coleta nada e não guarda estado: lê as duas
fontes que já existem e as casa por fornecedor.

O QUE ELE NÃO FAZ, DE PROPÓSITO
-------------------------------

**Não mostra segredo, e ESTA ROTA não edita nada.** Desde 07/09/2026 o ajuste
acontece no modal do cartão, e é um administrador que o faz — mas por OUTRA
rota, `/api/gestao/credenciais`, que sempre foi admin e continua sendo. As duas
não se fundiram, e a separação não é herança: é ela que mantém esta tela de
RBAC normal, aberta a quem opera.

O que este módulo publica sobre um campo de credencial é `_campo_publico()`:
que ele existe, se é obrigatório, se está preenchido, se é segredo. Nunca o
valor, nunca o mascarado — nem para o campo NÃO-segredo (ambiente, URL base,
filiais), que `credenciais.status()` devolve com valor porque lá é tela de
admin. Quem não é administrador abre o mesmo modal, lê o estado inteiro e vê a
lista de campos com a marca de preenchido, sem formulário e sem conteúdo.

Sem isso a tela teria de virar de administrador, e a razão dela existir
separada da Gestão — quem opera descobrir que a coleta parou sem depender de
alguém — ia junto.

**Não dispara coleta.** A pergunta é sobre o que JÁ aconteceu. Uma tela de
monitoramento que bate no fornecedor a cada pintura vira carga, e a casa já tem
a regra: fonte de painel jamais dispara coleta externa.

A PONTE ENTRE AS DUAS FONTES
----------------------------

`CARTAO_DA_SAUDE` casa a chave do fornecedor (a do cofre de credenciais) com o
NOME do cartão na Saúde. É um mapa escrito à mão, e mapa escrito à mão foi o
que já deixou dois guards cegos nesta casa esta semana — por isso
`tests/test_integracoes.py` confere os DOIS lados: todo nome mapeado existe
entre os cartões da Saúde, e todo fornecedor EXTERNO do cofre está mapeado.
Renomear um cartão lá derruba a suíte aqui, com o nome antigo no erro.
"""
from __future__ import annotations

import logging

log = logging.getLogger("cortex.integracoes")

#: Fornecedor externo × nome do cartão na Saúde do Servidor.
#:
#: Ausente aqui = fornecedor sem medição de chegada. Não é erro: o TomTom é
#: consultado sob demanda (não há coleta que possa "parar"), e o SMTP só se
#: prova no envio. O cartão diz isso em vez de fingir um semáforo.
CARTAO_DA_SAUDE: dict[str, str] = {
    "pontocertificado": "Ponto Certificado (batidas)",
    "gobrax": "Gobrax (telemetria)",
    "smartec": "Smartec (infrações e licenças)",
    "rasterjor": "Jornada (RasterJOR)",
    "rasterintegra": "RasterIntegra (ger. de risco)",
    "prolog": "Prolog (pneus)",
    "monkey": "Monkey (antecipação Tupy)",
    "zapi": "Z-API (WhatsApp)",
    "tress": "3S (rastreamento das carretas)",
    "tomtom": "TomTom (trânsito)",
    "xmlmail": "Caixa de XML (e-mail)",
}

#: O que está no cofre de credenciais mas NÃO é fornecedor externo.
#: `cortex` é o endereço do próprio painel; `motorista_mestre` é um segredo
#: NOSSO. Os dois estão lá porque é lá que a tela de configuração lê — e sem
#: esta lista eles entrariam no semáforo como integrações que nunca respondem.
#:
#: ELES NÃO SÃO DESCARTADOS, e essa é a correção de 10/09/2026: até aqui o
#: `panorama` fazia `continue` neles, e como a tela `integ` só monta cartão a
#: partir desta lista — e o modal só abre a partir de um cartão —, o
#: formulário dos dois ficou SEM PORTA DE ENTRADA quando a aba Gestão ›
#: Integrações foi aposentada (0260501, v1.6.0). O gerador do código mestre do
#: app do motorista, que abre a PII de ~300 pessoas, existia e não era
#: alcançável por ninguém. Defeito sem sintoma: nada dá erro, o botão
#: simplesmente não aparece. Agora eles saem em `proprios`, com cartão e modal
#: próprios, e fora do semáforo e das contas do resumo.
NAO_SAO_FORNECEDOR = frozenset({"cortex", "motorista_mestre"})

#: Por que estes não têm metade de CHEGADA — e por que isso não é "sem
#: medição". Não há fornecedor do outro lado: não existe coleta que possa
#: parar, então um cinza permanente ali seria alarme que ninguém pode apagar,
#: que é como se ensina a ignorar cinza.
SEM_CHEGADA = {
    "motorista_mestre": ("segredo da casa — não há coleta. Ele só é usado "
                         "quando alguém abre o app de um motorista para "
                         "conferência, e esse uso fica na auditoria"),
    "cortex": ("endereço do próprio painel — não há fornecedor do outro lado "
               "para responder"),
}

#: Fornecedor sem coleta periódica: não há "última coleta" para envelhecer.
#: Dizer "sem dado" deles seria alarme falso todo dia.
SOB_DEMANDA: dict[str, str] = {
    "tomtom": "consultado na hora, por viagem — não há coleta que possa parar",
    "qualp": "consultado na hora, por rota — não há coleta que possa parar",
    "smtp": "só se prova no envio; a falha aparece na fila do Correio",
}

#: Ordem do semáforo, do pior para o melhor. O cartão vale o PIOR dos dois
#: lados: configuração ativa com coleta parada há cinco dias não é "ok".
_PESO = {"erro": 0, "alerta": 1, "info": 2, "ok": 3}


def _pior(*estados: str | None) -> str:
    validos = [e for e in estados if e in _PESO]
    return min(validos, key=lambda e: _PESO[e]) if validos else "info"


def _cartoes_por_nome(cartoes: list[dict]) -> dict[str, dict]:
    return {c.get("nome", ""): c for c in cartoes}


# ------------------------------------------------ o detalhe que o modal abre
#
# O cartao responde "esta bem?"; o modal responde "o que exatamente falta?".
# Para isso ele precisa saber QUAIS campos a integracao tem e quais estao
# preenchidos -- e nao pode saber o que esta escrito neles.
#
# `credenciais.status()` devolve o VALOR de campo nao-segredo (ambiente, URL
# base, filiais). La isso e correto: e tela de admin, atras de /api/gestao, e
# conferir o que esta valendo sem abrir o arquivo no servidor era o ponto.
# Aqui seria vazamento, porque esta rota e de RBAC normal.
#
# Por isso o resumo se monta por LISTA DE PERMISSAO, escolhendo chave por
# chave, e nunca copiando o dicionario para apagar as ruins: campo novo no
# catalogo de credenciais entra invisivel por padrao. Copiar-e-apagar tem o
# defeito oposto -- a chave nova entra VISIVEL, e a falha nao tem sintoma.

def _campo_publico(campo: dict) -> dict:
    """O que uma tela sem privilegio pode saber de um campo de credencial:
    que ele existe, se e obrigatorio, se esta preenchido e se e segredo."""
    return {
        "rotulo": campo.get("rotulo") or campo.get("nome", ""),
        "obrigatorio": bool(campo.get("obrigatorio", True)),
        "configurado": bool(campo.get("configurado")),
        "segredo": bool(campo.get("segredo")),
    }


def _modos_publicos(svc: dict) -> list[dict]:
    """As formas de autenticacao do fornecedor, sem o conteudo dos campos.

    Um fornecedor pode aceitar mais de uma (a Prolog aceita tres) e o cliente
    usa a PRIMEIRA completa -- por isso `completo` viaja: sem ele o modal
    diria "tres formas disponiveis" sem dizer qual esta valendo.
    """
    return [{
        "chave": m.get("chave"),
        "rotulo": m.get("rotulo", ""),
        "completo": bool(m.get("completo")),
        "campos": [_campo_publico(c) for c in m.get("campos", [])],
    } for m in svc.get("modos", [])]


def _extras() -> list[dict]:
    """Integrações que NÃO autenticam por token, e por isso não estão no cofre.

    O cofre de `api/credenciais.py` é um cadastro de CAMPOS — token, usuário,
    senha, URL. A SEFAZ não cabe nele: quem autentica é um certificado A1 em
    arquivo, com validade de um ano e senha própria, e o "está configurada?"
    dela é uma pergunta diferente (o `.pfx` existe? abre? é do CNPJ certo? ainda
    vale?).

    Forçar isso para dentro do cofre criaria um campo mentiroso ("caminho do
    certificado") e faria a tela de Gestão oferecer a edição de uma coisa que
    não se edita por lá. A junção é aqui, que é o lugar dela.
    """
    saida = []
    try:
        from api.sefaz import painel as sefaz_painel
    except Exception as exc:  # noqa: BLE001
        log.warning("integracoes: painel da SEFAZ indisponivel: %s",
                    type(exc).__name__)
        return saida
    try:
        saida.append(sefaz_painel.cartao_de_integracao())
    except Exception as exc:  # noqa: BLE001
        # Uma integração que falha ao SE DESCREVER não pode derrubar a tela das
        # outras dez — mas também não pode sumir dela em silêncio.
        log.warning("integracoes: cartao da SEFAZ falhou: %s", type(exc).__name__)
        saida.append({
            "chave": "sefaz", "nome": "SEFAZ (recolha de NF)",
            "resumo": "Documentos fiscais emitidos contra a Sulista.",
            "alimenta": "Central de Documentos", "estado": "erro",
            "configuracao": {"estado": "desconhecida", "status": "erro",
                             "falta": ["não foi possível ler o estado"],
                             "modo": None, "regime": None},
            "chegada": {"regime": "coleta", "status": "erro",
                        "detalhe": "não foi possível ler o estado da recolha"},
        })
    return saida


def panorama(cartoes: list[dict] | None = None) -> dict:
    """Uma linha por fornecedor, com as duas metades casadas.

    `cartoes` é a saída de `servidor._servicos()`. Entra por parâmetro para o
    teste poder montar o caso sem subir a Saúde inteira — e para a rota poder
    reaproveitar uma coleta que já tenha em mãos.
    """
    from api import credenciais

    if cartoes is None:
        from api import servidor
        try:
            cartoes = servidor._servicos()
        except Exception as exc:  # noqa: BLE001
            log.warning("integracoes: a Saude nao respondeu: %s", type(exc).__name__)
            cartoes = []
    por_nome = _cartoes_por_nome(cartoes)

    linhas: list[dict] = []
    proprios: list[dict] = []
    for svc in credenciais.panorama():
        chave = svc["chave"]
        proprio = chave in NAO_SAO_FORNECEDOR

        nome_cartao = None if proprio else CARTAO_DA_SAUDE.get(chave)
        cartao = por_nome.get(nome_cartao) if nome_cartao else None

        # A CHEGADA TEM QUATRO RESPOSTAS, e "não sei" é uma delas.
        #
        # Sem esta separação, fornecedor sob demanda e fornecedor com coleta
        # parada cairiam no mesmo cinza — e é a diferença entre "está certo
        # assim" e "alguém precisa olhar hoje".
        if proprio:
            chegada = {"regime": "nao_se_aplica", "status": "info",
                       "detalhe": SEM_CHEGADA.get(
                           chave, "não é fornecedor externo")}
        elif chave in SOB_DEMANDA:
            chegada = {"regime": "sob_demanda", "status": "info",
                       "detalhe": SOB_DEMANDA[chave]}
        elif cartao is not None:
            chegada = {"regime": "coleta", "status": cartao.get("status", "info"),
                       "detalhe": cartao.get("detalhe", "")}
        else:
            chegada = {"regime": "sem_medicao", "status": "info",
                       "detalhe": "esta integração ainda não tem medição de "
                                  "chegada na Saúde do Servidor"}

        # A CONFIGURAÇÃO VIRA SEMÁFORO AQUI, e "desligada" NÃO é vermelho:
        # integração que ninguém contratou não é defeito, é recurso que não
        # existe nesta instalação. Pintar de vermelho o que está certo é como
        # se ensina a ignorar vermelho.
        conf = {"ativa": "ok", "incompleta": "alerta",
                "desligada": "info"}.get(svc["estado"], "info")

        # O ROTULO do modo ativo, e nao so a chave. A chave (`oauth`, `basic`)
        # e nome de codigo; quem opera reconhece "OAuth2 (password + refresh)".
        modos = _modos_publicos(svc)
        ativo = next((m for m in modos if m["chave"] == svc["modo_ativo"]), None)

        (proprios if proprio else linhas).append({
            "chave": chave,
            "nome": svc["nome"],
            "resumo": svc["resumo"],
            "alimenta": svc["alimenta"],
            # O ESTADO DE UM SEGREDO DA CASA É SÓ O DA CONFIGURAÇÃO. Passar
            # pelo `_pior` junto com a chegada rebaixaria "ok" para "info",
            # porque `info` pesa menos que `ok` — um cofre preenchido apareceria
            # cinza para sempre por causa de uma metade que não existe.
            "proprio": proprio,
            "estado": conf if proprio else _pior(conf, chegada["status"]),
            "configuracao": {"estado": svc["estado"], "status": conf,
                             "falta": svc["falta"], "modo": svc["modo_ativo"],
                             "modo_rotulo": (ativo or {}).get("rotulo"),
                             "regime": svc.get("regime"),
                             "modos": modos,
                             "ajustes": [_campo_publico(c)
                                         for c in svc.get("ajustes", [])]},
            "chegada": chegada,
            # ONDE SE MEDE E ONDE SE EDITA -- as duas pontas que o modal
            # precisa nomear para nao ser mais uma tela que diz "confie".
            # `aba` so existe para quem se configura em OUTRO lugar (o SMTP na
            # aba de E-mail, a Z-API na de WhatsApp): editar a mesma senha em
            # dois lugares e o que fazia salvar num e conferir no outro.
            "cartao_saude": nome_cartao,
            "aba": svc.get("aba"),
        })

    for extra in _extras():
        extra.setdefault("proprio", False)
        linhas.append(extra)

    linhas.sort(key=lambda l: (_PESO.get(l["estado"], 9), l["nome"].lower()))
    proprios.sort(key=lambda l: (_PESO.get(l["estado"], 9), l["nome"].lower()))
    return {
        "integracoes": linhas,
        # SEGREDOS DA CASA, em lista separada de propósito. Eles não entram no
        # `resumo` porque os KPIs da tela dizem "fornecedores externos que a
        # casa usa" — somar aqui um código que ninguém do lado de fora conhece
        # faria a conta responder outra pergunta.
        "proprios": proprios,
        "resumo": {
            "total": len(linhas),
            "ok": sum(1 for l in linhas if l["estado"] == "ok"),
            "atencao": sum(1 for l in linhas if l["estado"] in ("alerta", "erro")),
            "sem_medicao": sum(1 for l in linhas
                               if l["chegada"]["regime"] == "sem_medicao"),
        },
    }
