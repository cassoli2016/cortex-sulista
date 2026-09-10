# -*- coding: utf-8 -*-
"""O código mestre: abrir o app de qualquer motorista, para conferir.

═══════════════════════════════════════════════════════════════════════════
POR QUE ISTO EXISTE, E POR QUE NÃO É UMA CONCESSÃO À PREGUIÇA
═══════════════════════════════════════════════════════════════════════════
O app passou a dizer coisas sobre UMA pessoa: multas atribuídas por hipótese,
indicadores de telemetria casados por nome, ocorrências do ERP, produtividade e
jornada. Cada um desses números tem um caminho de dado com pelo menos uma
junção frágil — e o único leitor de cada tela é a pessoa que menos pode
conferir se ela está certa.

Sem um acesso de conferência, um erro nessas telas vive escondido: cada
motorista vê só a dele, ninguém vê o conjunto, e o defeito aparece meses depois
numa discussão de premiação. Quem opera pediu isto por escrito em 07/09/2026,
e a razão é essa — validar o que o app afirma.

═══════════════════════════════════════════════════════════════════════════
O QUE ELE É, EM UMA FRASE
═══════════════════════════════════════════════════════════════════════════
Um segredo da casa que abre uma SESSÃO NORMAL DE MOTORISTA na conta de quem
for escolhido, marcada como mestre, curta, e com tarja obrigatória na tela.

**Não é um perfil de administração dentro do app.** A sessão mestre lê exatamente
o que aquele motorista leria — as mesmas funções, o mesmo `sessao.exigir()`, o
mesmo escopo vindo da sessão. Não existe rota que devolva "todos os motoristas
de uma vez"; existe uma que LISTA nomes para escolher, e ela não abre sessão
nenhuma.

═══════════════════════════════════════════════════════════════════════════
AS SEIS CONTENÇÕES, E O QUE CADA UMA COBRE
═══════════════════════════════════════════════════════════════════════════
1. **O segredo não está no repo.** Vem do cofre (`credenciais.ler`) com o
   `.env` de retaguarda, como toda credencial da casa. **O repo é PÚBLICO.**
2. **Comparação em tempo constante** (`hmac.compare_digest`). Comparar string
   com `==` vaza o prefixo certo pelo tempo de resposta, e este é o único
   segredo do app que não expira em 10 minutos.
3. **Piso de tamanho.** Código curto é código que se tenta; abaixo de
   `TAMANHO_MINIMO` o módulo se recusa a funcionar e DIZ isso na Saúde do
   Servidor, em vez de aceitar um segredo fraco em silêncio.
4. **Teto por endereço** (`mot_mestre_tentativas`). O código não expira — o que
   protege contra o laço é o teto, não o prazo.
5. **Prazo curto na sessão** (`TTL_HORAS`). 30 dias deslizantes é o que faz o
   motorista não desistir do app; para um acesso de administração é uma porta
   aberta num aparelho que ninguém lembra que está logado.
6. **Trilha separada.** `motorista_mestre_entrou` no `audit_log`, com o alvo. A
   entrada normal e a mestre não podem parecer a mesma coisa depois — senão a
   auditoria de uso do app vira ficção.

**NÃO CONFIGURADO NÃO É FALHA, É INSTALAÇÃO INCOMPLETA.** Sem o segredo no
cofre, `configurado()` é falso, a rota recusa como recusaria um código errado,
e a Saúde do Servidor diz `info` — nunca vermelho. É a mesma regra da
integração sem credencial: alarme que não distingue "quebrado" de "ainda não
usado" treina todo mundo a ignorar alarme.

═══════════════════════════════════════════════════════════════════════════
A RESPOSTA É UNIFORME, MAS POR OUTRO MOTIVO QUE A DA ENTRADA
═══════════════════════════════════════════════════════════════════════════
Em `entrada.py` a resposta é única para não revelar QUEM dirige para esta
empresa. Aqui é para não revelar o ESTADO do próprio segredo: "código
inválido" e "acesso mestre não configurado" e "você estourou o teto" saem com
o mesmo texto e o mesmo código, senão a rota responde de graça se vale a pena
continuar tentando.
"""
from __future__ import annotations

import hmac
import logging
import os

from .. import pglocal

log = logging.getLogger("cortex.motorista.mestre")

#: Onde o segredo mora. Cofre da tela de Gestão primeiro, `.env` depois — a
#: mesma ordem de toda credencial da casa (`api/credenciais.py`).
CHAVE = "MOTORISTA_CODIGO_MESTRE"

#: Abaixo disto o módulo se recusa a funcionar. Não é opinião sobre entropia:
#: é o piso que impede alguém de pôr "sulista2026" num acesso que abre a PII de
#: 300 pessoas, e a Saúde do Servidor mostra a recusa em vez de ela ser muda.
TAMANHO_MINIMO = 16

#: Sessão mestre vence em horas, e não desliza. Oito é um turno: quem entrou
#: para conferir termina a conferência dentro dele, e o aparelho esquecido em
#: cima da mesa não segue aberto no dia seguinte.
TTL_HORAS = 8

#: Tentativas por endereço, por hora. Baixo de propósito, ao contrário do teto
#: de IP da entrada (20): lá o IP pode ser o NAT de uma operadora com vários
#: motoristas atrás, e barrar seria barrar gente de verdade. Aqui o universo de
#: usuários legítimos é "quem administra" — meia dúzia de tentativas por hora
#: cobre erro de digitação e nada mais.
MAX_TENTATIVAS_HORA = 6

#: Quantos nomes a lista devolve por vez. A lista inteira num celular é rolagem
#: sem fim; a busca é o caminho normal.
LIMITE_LISTA = 40

#: A recusa ÚNICA. Uma constante e não um literal repetido: literal repetido
#: diverge, e aqui divergir é o defeito — cada texto diferente é uma resposta
#: diferente sobre o estado do segredo.
RECUSA = "Código mestre inválido."


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota. Nunca 5xx: o Cloudflare troca o
    corpo de 5xx pela página dele e a mensagem não chega a ninguém."""


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
            log.warning("código mestre configurado com menos de %d caracteres — "
                        "recusado", TAMANHO_MINIMO)
        return ""
    return valor


def configurado() -> bool:
    """Para a Saúde do Servidor. Não diz o segredo, diz se existe um válido."""
    return bool(_segredo())


def _freado(ip: str, esquema: str | None) -> bool:
    """O freio conta só o que ERROU, e essa palavra é a correção de 10/09/2026.

    Ele contava TODA tentativa, acerto junto. Medido no dia: seis conferências
    seguidas do mesmo endereço, as seis ACEITAS — e a sétima recusada, com a
    mensagem "Código mestre inválido". O código estava certo o tempo inteiro;
    quem administra foi procurar defeito no código, no cofre e no gerador,
    porque a tela dizia exatamente isso.

    O teto existe contra ADIVINHAÇÃO, e adivinhação produz ERRO. Contar acerto
    junto não protege de nada: quem acertou já entrou. O que ele fazia era
    punir o uso legítimo — e a intenção estava escrita duas linhas acima do
    próprio contador ("meia dúzia por hora cobre erro de digitação"), só não
    estava no SQL.

    E O ACERTO ZERA O CONTADOR, contando só o que errou DEPOIS do último
    acerto daquele endereço. É a mesma regra do `senha_reset`: quem provou
    saber o segredo não é quem estava adivinhando, e carregar os erros
    anteriores faria a pessoa certa pagar por eles no fim da hora.

    Zera-se pela CONSULTA, nunca reescrevendo linha: marcar as tentativas
    antigas como aceitas apagaria o registro de que elas erraram, e a trilha
    de uso deste segredo é a única coisa que responde "quem abriu a conta de
    quem, e quando". Contador se recalcula; histórico, não.
    """
    r = pglocal.um(
        """SELECT count(*) AS n FROM mot_mestre_tentativas
            WHERE ip = %(ip)s AND ip <> '' AND NOT aceita
              AND quando > now() - interval '1 hour'
              AND quando > coalesce((SELECT max(quando)
                                       FROM mot_mestre_tentativas
                                      WHERE ip = %(ip)s AND aceita),
                                    '-infinity'::timestamptz)""",
        {"ip": (ip or "")[:64]}, esquema)
    return int((r or {}).get("n") or 0) >= MAX_TENTATIVAS_HORA


def _registrar(ip: str, aceita: bool, esquema: str | None) -> None:
    """A tentativa entra sempre, certa ou errada: é a trilha de uso."""
    pglocal.executar(
        "INSERT INTO mot_mestre_tentativas(ip, aceita) VALUES (%(ip)s, %(ok)s)",
        {"ip": (ip or "")[:64], "ok": bool(aceita)}, esquema)


def conferir(codigo: str, *, ip: str = "", esquema: str | None = None) -> None:
    """Levanta `Recusa` se o código não vale. Silêncio = vale.

    LEVANTA EM VEZ DE DEVOLVER BOOLEANO, pela mesma razão de
    `sessao.exigir()`: uma função que devolvesse `False` seria lida um dia num
    `if` que trata isso como "sem restrição". Não há caminho aqui que devolva
    "mais ou menos".

    A TENTATIVA É REGISTRADA ANTES DA COMPARAÇÃO. Contar depois deixaria de
    fora exatamente as que interessam — as que erram —, e o teto nunca
    chegaria. É o mesmo erro que `entrada.confirmar` já não comete.
    """
    esq = _esq(esquema)
    digitado = str(codigo or "").strip()
    if _freado(ip, esq):
        log.warning("código mestre freado por endereço")
        raise Recusa(RECUSA)
    esperado = _segredo()
    ok = bool(esperado) and hmac.compare_digest(esperado, digitado)
    _registrar(ip, ok, esq)
    if not ok:
        raise Recusa(RECUSA)


def motoristas(busca: str = "", esquema: str | None = None) -> dict:
    """Quem se pode abrir. **Só id e nome** — nunca o código do ERP.

    O `motorista_codigo` é o CPF para pessoa física, e esta lista vai para um
    navegador. Ela é exatamente a mesma disciplina da lista de escolha da
    entrada (`entrada.confirmar`), e pela mesma razão: o id opaco é o que pode
    ser dito para fora.

    O TOTAL VIAJA JUNTO DO CORTE. Top-N sem contador vira total falso — "40
    motoristas" quando são 300 é a diferença entre conferir a operação e achar
    que se conferiu.
    """
    esq = _esq(esquema)
    termo = " ".join(str(busca or "").strip().split())
    par = {"q": f"%{termo}%", "lim": LIMITE_LISTA}
    onde = "WHERE ativo"
    if termo:
        onde += " AND nome ILIKE %(q)s"
    linhas = pglocal.query(
        f"SELECT id, nome FROM mot_vinculos {onde} ORDER BY nome LIMIT %(lim)s",
        par, esq)
    total = pglocal.um(
        f"SELECT count(*) AS n FROM mot_vinculos {onde}", par, esq) or {}
    return {
        "motoristas": [{"id": int(l["id"]), "nome": l["nome"] or ""}
                       for l in linhas],
        "mostrados": len(linhas),
        "total": int(total.get("n") or 0),
        "limite": LIMITE_LISTA,
    }


def abrir(motorista_id: int, *, aparelho: str = "", ip: str = "",
          agente: str = "", esquema: str | None = None) -> dict:
    """Abre a sessão MESTRE na conta daquele motorista.

    O CÓDIGO JÁ FOI CONFERIDO PELA ROTA — esta função não confere de novo, e
    isso é uma dívida deliberada de UM nível: ela é privada do módulo, chamada
    de um lugar só, e duplicar a conferência esconderia qual das duas é a que
    manda. O guard que segura isso é o teste que varre as rotas.
    """
    from . import sessao as ses

    esq = _esq(esquema)
    alvo = pglocal.um(
        "SELECT id, motorista_codigo, nome FROM mot_vinculos "
        "WHERE id = %(id)s AND ativo",
        {"id": int(motorista_id)}, esq)
    if not alvo:
        # Recusa DIFERENTE da do código, de propósito: quem chegou aqui já
        # provou o segredo, e esconder o motivo dele só faria alguém tentar o
        # mesmo botão para sempre. Motorista desligado tem de dizer que está
        # desligado.
        raise Recusa("Motorista não encontrado ou desligado.")

    sessao_id = ses.abrir(alvo["motorista_codigo"], aparelho=aparelho, ip=ip,
                          agente=agente, mestre=True, esquema=esq)
    return {"motorista_id": int(alvo["id"]), "nome": alvo["nome"] or "",
            "sessao_id": sessao_id,
            "token": ses.emitir(int(alvo["id"]), sessao_id,
                                horas=TTL_HORAS)}
