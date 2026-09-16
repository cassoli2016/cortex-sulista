# -*- coding: utf-8 -*-
"""O código mestre: abrir o app de qualquer agregado, para conferir.

POR QUE ISTO EXISTE. O app afirma, para uma pessoa de fora da casa, quanto ela
tem a receber: acerto fechado, acerto em aberto, desconto, adiantamento,
abastecimento. Cada um desses números atravessa uma junção do ERP — o dono
casado pelo `veiculo.proprietario`, o abastecimento casado por placa, a parcela
casada com a conta a pagar. O único leitor de cada tela é justamente quem não
pode conferir se ela está certa, e um erro aqui não é um gráfico feio: é uma
conversa sobre dinheiro com um fornecedor.

Sem acesso de conferência, o defeito vive escondido até virar reclamação. Com
ele, alguém da casa abre exatamente o que o dono vê e compara com o ERP.

O QUE ELE É, EM UMA FRASE: um segredo da casa que abre uma SESSÃO NORMAL DE
AGREGADO na conta de quem for escolhido, marcada como mestre, curta, e com
tarja obrigatória na tela. **Não é um perfil de administração dentro do app**:
a sessão mestre lê exatamente o que aquele dono leria, pelas mesmas funções e
pelo mesmo escopo vindo da sessão. Não existe rota que devolva "todos os
agregados de uma vez"; existe uma que LISTA nomes para escolher, e ela não abre
sessão nenhuma.

AS SEIS CONTENÇÕES, e o que cada uma cobre:

1. **O segredo não está no repo.** Vem do cofre (`credenciais.ler`) com o
   `.env` de retaguarda. **O repo é PÚBLICO.**
2. **Comparação em tempo constante** (`hmac.compare_digest`): comparar com `==`
   vaza o prefixo certo pelo tempo de resposta, e este é o único segredo do app
   que não expira em 10 minutos.
3. **Piso de tamanho**: abaixo de `TAMANHO_MINIMO` o módulo se recusa a
   funcionar e DIZ isso, em vez de aceitar um segredo fraco em silêncio.
4. **Teto por endereço**: o código não expira — o que protege contra o laço é o
   teto, não o prazo. E o teto conta só o que ERROU, zerando no último acerto:
   punir o uso legítimo foi um defeito real do app do motorista, corrigido em
   10/09/2026 depois de seis conferências certas serem barradas na sétima.
5. **Prazo curto na sessão** (`TTL_HORAS`): 30 dias deslizantes é o que faz o
   dono não desistir do app; num acesso de administração é uma porta aberta num
   aparelho que ninguém lembra que está logado.
6. **Trilha separada**: `agregado_mestre_entrou` no `audit_log`, com o alvo. A
   entrada normal e a mestre não podem parecer a mesma coisa depois.

**NÃO CONFIGURADO NÃO É FALHA, É INSTALAÇÃO INCOMPLETA.** Sem o segredo no
cofre, `configurado()` é falso, a rota recusa como recusaria um código errado,
e a Saúde do Servidor diz `info` — nunca vermelho.

A RESPOSTA É UNIFORME, mas por outro motivo que a da entrada: lá é para não
revelar QUEM é dono de caminhão; aqui é para não revelar o ESTADO do próprio
segredo — "código inválido", "não configurado" e "teto estourado" saem com o
mesmo texto.
"""
from __future__ import annotations

import hmac
import logging
import os

from .. import pglocal

log = logging.getLogger("cortex.agregado.mestre")

#: Onde o segredo mora. Cofre da tela de Gestão primeiro, `.env` depois — a
#: mesma ordem de toda credencial da casa (`api/credenciais.py`).
CHAVE = "AGREGADO_CODIGO_MESTRE"

#: Abaixo disto o módulo se recusa a funcionar. É o piso que impede alguém de
#: pôr "sulista2026" num acesso que abre o financeiro de 201 fornecedores.
TAMANHO_MINIMO = 16

#: Sessão mestre vence em horas, e não desliza. Oito é um turno.
TTL_HORAS = 8

#: Tentativas por endereço, por hora — e só as que ERRARAM (ver `_freado`).
MAX_TENTATIVAS_HORA = 6

#: Quantos nomes a lista devolve por vez. São 201 donos: a lista inteira num
#: celular é rolagem sem fim, e a busca é o caminho normal.
LIMITE_LISTA = 40

#: A recusa ÚNICA. Uma constante e não um literal repetido: literal repetido
#: diverge, e aqui divergir é o defeito.
RECUSA = "Código mestre inválido."


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota. Nunca 5xx."""


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _segredo() -> str:
    """O código mestre em vigor, ou "" quando não há um utilizável.

    O piso de tamanho é aplicado AQUI, e não na conferência: assim não existe
    caminho no módulo em que um segredo curto valha por acidente. Ler o cofre
    pode levantar (tabela ausente em banco novo) e isso não pode virar 500 numa
    rota pública — sem segredo, o acesso simplesmente não existe.
    """
    try:
        from .. import credenciais
        valor = (credenciais.ler(CHAVE) or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.info("cofre indisponível para o código mestre: %s", type(exc).__name__)
        valor = ""
    if not valor:
        valor = (os.environ.get(CHAVE, "") or "").strip()
    if len(valor) < TAMANHO_MINIMO:
        if valor:
            log.warning("código mestre do agregado com menos de %d caracteres — "
                        "recusado", TAMANHO_MINIMO)
        return ""
    return valor


def configurado() -> bool:
    """Para a Saúde do Servidor. Não diz o segredo, diz se existe um válido."""
    return bool(_segredo())


def _freado(ip: str, esquema: str | None) -> bool:
    """O freio conta só o que ERROU, e zera no último acerto daquele endereço.

    O teto existe contra ADIVINHAÇÃO, e adivinhação produz ERRO: contar acerto
    junto não protege de nada (quem acertou já entrou) e pune quem confere —
    foi o defeito do app do motorista, medido em 10/09/2026. Zera-se pela
    CONSULTA, nunca reescrevendo linha: contador se recalcula, histórico não.
    """
    r = pglocal.um(
        """SELECT count(*) AS n FROM agr_mestre_tentativas
            WHERE ip = %(ip)s AND ip <> '' AND NOT aceita
              AND quando > now() - interval '1 hour'
              AND quando > coalesce((SELECT max(quando)
                                       FROM agr_mestre_tentativas
                                      WHERE ip = %(ip)s AND aceita),
                                    '-infinity'::timestamptz)""",
        {"ip": (ip or "")[:64]}, esquema)
    return int((r or {}).get("n") or 0) >= MAX_TENTATIVAS_HORA


def _registrar(ip: str, aceita: bool, esquema: str | None) -> None:
    """A tentativa entra sempre, certa ou errada: é a trilha de uso."""
    pglocal.executar(
        "INSERT INTO agr_mestre_tentativas(ip, aceita) VALUES (%(ip)s, %(ok)s)",
        {"ip": (ip or "")[:64], "ok": bool(aceita)}, esquema)


def conferir(codigo: str, *, ip: str = "", esquema: str | None = None) -> None:
    """Levanta `Recusa` se o código não vale. Silêncio = vale.

    LEVANTA EM VEZ DE DEVOLVER BOOLEANO, pela mesma razão de `sessao.exigir()`:
    uma função que devolvesse `False` seria lida um dia num `if` que trata isso
    como "sem restrição". A tentativa é registrada ANTES da comparação.
    """
    esq = _esq(esquema)
    digitado = str(codigo or "").strip()
    if _freado(ip, esq):
        log.warning("código mestre do agregado freado por endereço")
        raise Recusa(RECUSA)
    esperado = _segredo()
    ok = bool(esperado) and hmac.compare_digest(esperado, digitado)
    _registrar(ip, ok, esq)
    if not ok:
        raise Recusa(RECUSA)


def agregados(busca: str = "", esquema: str | None = None) -> dict:
    """Quem se pode abrir. **Só id e nome** — nunca o código do ERP.

    O TOTAL VIAJA JUNTO DO CORTE: top-N sem contador vira total falso — "40
    agregados" quando são 201 é a diferença entre conferir a operação e achar
    que se conferiu.
    """
    esq = _esq(esquema)
    termo = " ".join(str(busca or "").strip().split())
    par = {"q": f"%{termo}%", "lim": LIMITE_LISTA}
    onde = "WHERE ativo"
    if termo:
        onde += " AND nome ILIKE %(q)s"
    linhas = pglocal.query(
        f"SELECT id, nome FROM agr_vinculos {onde} ORDER BY nome LIMIT %(lim)s",
        par, esq)
    total = pglocal.um(
        f"SELECT count(*) AS n FROM agr_vinculos {onde}", par, esq) or {}
    return {
        "agregados": [{"id": int(l["id"]), "nome": l["nome"] or ""}
                      for l in linhas],
        "mostrados": len(linhas),
        "total": int(total.get("n") or 0),
        "limite": LIMITE_LISTA,
    }


def abrir(agregado_id: int, *, aparelho: str = "", ip: str = "",
          agente: str = "", esquema: str | None = None) -> dict:
    """Abre a sessão MESTRE na conta daquele agregado.

    O CÓDIGO JÁ FOI CONFERIDO PELA ROTA — esta função não confere de novo, e
    isso é uma dívida deliberada de UM nível: ela é privada do módulo, chamada
    de um lugar só, e duplicar a conferência esconderia qual das duas manda. O
    guard que segura isso é o teste que varre as rotas.
    """
    from . import sessao as ses

    esq = _esq(esquema)
    alvo = pglocal.um(
        "SELECT id, proprietario_codigo, nome FROM agr_vinculos "
        "WHERE id = %(id)s AND ativo",
        {"id": int(agregado_id)}, esq)
    if not alvo:
        # Recusa DIFERENTE da do código, de propósito: quem chegou aqui já
        # provou o segredo, e esconder o motivo dele só faria alguém tentar o
        # mesmo botão para sempre.
        raise Recusa("Agregado não encontrado ou desligado.")

    sessao_id = ses.abrir(alvo["proprietario_codigo"], aparelho=aparelho, ip=ip,
                          agente=agente, mestre=True, esquema=esq)
    return {"agregado_id": int(alvo["id"]), "nome": alvo["nome"] or "",
            "sessao_id": sessao_id,
            "token": ses.emitir(int(alvo["id"]), sessao_id, horas=TTL_HORAS)}
