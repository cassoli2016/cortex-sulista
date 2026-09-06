# -*- coding: utf-8 -*-
"""Entrar no app: telefone, código no WhatsApp, sessão no aparelho.

POR QUE NÃO É SENHA. O leitor está na cabine, não vai decorar senha e não vai
abrir chamado quando esquecer — vai ligar para a torre, que é o custo que este
app existe para tirar. O telefone ele tem na mão, e a cobertura foi MEDIDA
antes de a decisão ser tomada: 285 dos 299 motoristas ativos em 90 dias
(95,3%) têm celular válido em `cadastro.celular`, todos distintos entre si.

O FORMULÁRIO PÚBLICO RESPONDE IGUAL PARA NÚMERO QUE EXISTE E QUE NÃO EXISTE.
Mesmo texto, mesmo código de status — inclusive quando o envio falha, quando o
número está fora do cadastro e quando o freio já cortou o pedido. É a mesma
regra do "esqueci minha senha" da casa, pela mesma razão: um formulário aberto
que responde diferente vira uma máquina de descobrir quem dirige para esta
empresa, e daí a lista de placas e rotas de quem tiver paciência.

Isso tem um preço honesto: o motorista que digita o número errado não é
avisado. Ele vê "se o número estiver cadastrado, o código chegou" e liga para a
torre — que é o caminho certo, porque quem conserta cadastro é gente.

AS CINCO CONTENÇÕES, e o que cada uma cobre — nenhuma cobre a do lado:

1. **Prazo curto** (10 min). Código que vive uma hora é código que sobra na
   tela de bloqueio do celular emprestado.
2. **Tentativas contadas** (5 por código). Seis dígitos são um milhão de
   combinações; sem teto, um laço acerta em minutos.
3. **Pedidos por hora, POR TELEFONE** (3). Sem isso a rota vira um jeito
   confortável de encher o WhatsApp de alguém — e o freio de destinatários da
   casa não veria problema nenhum, porque é sempre o MESMO número.
4. **Pedidos por hora, POR ENDEREÇO** (20). O teto por telefone não segura
   VOLUME: quem tivesse a lista de números pediria 3 para cada um. É teto de
   script, não de pessoa — por isso alto, já que um IP pode ser o NAT da
   operadora com vários motoristas atrás.
5. **O código nunca é gravado.** Só o SHA-256. Quem lê a tabela (backup, dump,
   consulta de diagnóstico) não entra na conta de ninguém.

E o código NÃO VAI PARA O LOG, em lugar nenhum, nem em `debug`. Log de
autenticação com o segredo dentro é o vazamento que ninguém procura porque
"é só o log".

═══════════════════════════════════════════════════════════════════════════
O FREIO DO WHATSAPP DA CASA, E O QUE FOI MEXIDO NELE
═══════════════════════════════════════════════════════════════════════════
`whatsapp.envio.enviar()` tem três freios: interruptor geral, JANELA de
horário (08:00–20:00 por padrão) e TETO de destinatários distintos por dia (60).
Eles existem para a mensagem de empresa não virar reclamação e para o número
não ser banido.

**A janela é aberta aqui, e só ela.** Um código de entrada não é mensagem de
empresa: é resposta a alguém que está com o celular na mão esperando por ela,
às 03:40, na fila de uma doca. Manter a janela significaria um app que não
abre à noite — que é exatamente quando o motorista está na estrada. A abertura
é explícita, é só deste caminho (`regras=`), e não muda a configuração da casa.

**O teto do dia NÃO é mexido**, e o que fazer com ele deixou de ser adivinhação
em 06/09/2026: medido em `zap_envios`, a casa gasta MEDIANA DE 2 destinatários
distintos por dia (pior dia dos últimos 28: 3) contra um teto de 60. Sobram ~58
vagas por dia. A frase que estava aqui antes — "cadastrar 300 motoristas de uma
vez não cabe" — foi escrita olhando o teto e não o consumo, e estava errada na
prática: o gargalo real é de dias de calendário (~300 ÷ 58 ≈ 6 dias de ondas),
e mesmo isso é teórico, porque ninguém instala um app todo no mesmo dia.

═══════════════════════════════════════════════════════════════════════════
POR QUE O NÚMERO PRINCIPAL, E NÃO A RESERVA (decidido em 06/09/2026)
═══════════════════════════════════════════════════════════════════════════
As duas instâncias existem e estão configuradas. A escolha é a principal, por
três razões — e a primeira é a única que não é opinião:

1. **A capacidade não é o problema** (a medição acima). A reserva resolveria um
   aperto de cota que não existe.
2. **A reserva existe para NÃO ser gasta.** `whatsapp/cliente.py` diz isso
   explicitamente ao recusar troca automática: disparar pela reserva quando a
   principal cai "queimaria o segundo número também, que é justamente o que não
   se pode perder". Um fluxo automático, recorrente e crescente — todo login de
   todo motorista, para sempre — é exatamente o que gasta reputação. Pôr o app
   ali transformaria o pneu step em pneu de rodagem.
3. **O código precisa CHEGAR e ser ACREDITADO.** O motorista já recebe recado
   da torre pelo número principal: o código chega numa conversa que ele
   reconhece. Vindo de um número desconhecido, "seu código é 123456" tem a
   forma exata de um golpe — e um código ignorado é um login que não acontece,
   que é o único jeito de este app falhar por inteiro.

`MOTORISTA_ZAP_INSTANCIA` continua existindo como escape: se um dia o app
sozinho passar a responder por parcela grande do envio diário, mudar de número
é uma linha de `.env`. A decisão de hoje é qual é o PADRÃO, não uma amarra.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets

from ..whatsapp import config as zcfg
from ..whatsapp import envio as wa
from ..whatsapp import numeros
from .. import pglocal

log = logging.getLogger("cortex.motorista.entrada")

#: Quanto tempo o código vale.
VALIDADE_MIN = 10

#: Quantas vezes se pode errar o MESMO código antes de ele morrer.
MAX_TENTATIVAS = 5

#: Quantos códigos um telefone pode PEDIR por hora. Não se anuncia: passar do
#: teto responde igual a tudo o mais, senão o próprio freio vira o oráculo que
#: a resposta uniforme existe para fechar.
MAX_PEDIDOS_HORA = 3

#: O mesmo teto pela outra ponta: quantos pedidos saem de UM ENDEREÇO por hora.
#:
#: O teto por telefone sozinho não segura volume — quem tivesse a lista de
#: números pediria 3 para cada um, e a única coisa entre isso e centenas de
#: mensagens seria o teto diário do WhatsApp da casa, que é uma proteção do
#: NÚMERO DELA, não deste app (e que, gasto aqui, deixaria de valer para
#: clientes e fornecedores no mesmo dia).
#:
#: 20 e não 3 porque um IP não é uma pessoa: o tráfego chega pelo tunnel do
#: Cloudflare e vários motoristas podem sair pelo mesmo NAT de operadora. Teto
#: baixo aqui barraria motorista de verdade, que é o oposto do que se quer —
#: este número freia SCRIPT, e é o telefone que freia pessoa.
MAX_PEDIDOS_HORA_IP = 20

#: A resposta ÚNICA do pedido. Uma constante e não um literal em três lugares:
#: é literal repetido que diverge, e aqui divergir é o defeito. O prazo é
#: DERIVADO de `VALIDADE_MIN` pelo mesmo motivo — prazo escrito à mão numa
#: frase é a primeira coisa a mentir quando alguém mexe na constante.
RESPOSTA_PEDIDO = ("Se este número estiver cadastrado, o código de entrada "
                   "chegou no seu WhatsApp. Ele vale por %d minutos."
                   % VALIDADE_MIN)

#: A recusa ÚNICA da confirmação. Também uma só: "código errado" e "código
#: expirado" separados diriam a quem tenta em laço se vale a pena continuar.
RECUSA_CODIGO = ("Código inválido ou expirado. Peça um novo código.")

TEXTO = ("Seu codigo de entrada no app do motorista e {codigo}.\n"
         "Ele vale por %d minutos.\n\n"
         "Se nao foi voce que pediu, ignore esta mensagem — ninguem entra "
         "sem este codigo." % VALIDADE_MIN)


class Recusa(Exception):
    """Recusa legível, para virar 4xx na rota. Nunca 5xx: o Cloudflare troca o
    corpo de 5xx pela página dele e a mensagem não chega a ninguém."""


def _esq(esquema: str | None = None) -> str | None:
    """O schema em vigor, lido NA CHAMADA e nunca na importação.

    `from . import ESQUEMA` no topo COPIA o valor: o teste que redireciona
    `motorista.ESQUEMA` para um schema descartável não alcançaria esta cópia, e
    o módulo escreveria em PRODUÇÃO com a suíte toda verde. Foi assim que os
    testes da Monkey puseram recebíveis de dublê dentro de `cortex.mky_*` em
    01/09/2026, e o sintoma apareceu numa tela, não na suíte.
    """
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def _instancia() -> str | None:
    return (os.environ.get("MOTORISTA_ZAP_INSTANCIA", "").strip() or None)


def _normalizar(bruto: str) -> str:
    """Telefone normalizado, ou "" — NUNCA levanta para fora.

    Levantar aqui seria a primeira diferença de resposta entre um número
    malformado e um número que não existe, e é justamente a diferença que este
    arquivo inteiro existe para não ter.
    """
    try:
        n = numeros.normalizar(bruto or "")
        return n if numeros.valido(n) else ""
    except Exception:  # noqa: BLE001 — o contrato é não vazar o motivo
        return ""


def _vinculos(telefone: str, esquema: str | None = None) -> list[dict]:
    return pglocal.query(
        """SELECT motorista_codigo, nome FROM mot_vinculos
            WHERE telefone = %(f)s AND ativo
            ORDER BY nome, motorista_codigo""",
        {"f": telefone}, _esq(esquema))


def pedir(telefone_bruto: str, *, ip: str = "", esquema: str | None = None,
          http=None) -> dict:
    """Manda um código, ou não manda. A resposta é a MESMA nos dois casos."""
    esq = _esq(esquema)
    fone = _normalizar(telefone_bruto)
    if not fone:
        return {"ok": True, "mensagem": RESPOSTA_PEDIDO}

    # OS DOIS TETOS NA MESMA IDA AO BANCO. Separá-los em duas consultas só
    # daria duas viagens para responder a mesma pergunta.
    recentes = pglocal.um(
        """SELECT sum(CASE WHEN telefone = %(f)s THEN 1 ELSE 0 END) AS por_fone,
                  sum(CASE WHEN ip = %(ip)s AND %(ip)s <> '' THEN 1 ELSE 0 END) AS por_ip
             FROM mot_codigos
            WHERE criado_em > now() - interval '1 hour'""",
        {"f": fone, "ip": (ip or "")[:64]}, esq)
    r = recentes or {}
    if (int(r.get("por_fone") or 0) >= MAX_PEDIDOS_HORA
            or int(r.get("por_ip") or 0) >= MAX_PEDIDOS_HORA_IP):
        # O log distingue os dois (um é pessoa insistindo, o outro é script);
        # a RESPOSTA não distingue nada, que é o ponto.
        log.info("pedido de código freado (fone=%s ip=%s)",
                 r.get("por_fone"), r.get("por_ip"))
        return {"ok": True, "mensagem": RESPOSTA_PEDIDO}

    if not _vinculos(fone, esq):
        # Nada é enviado e nada é gravado: gravar aqui faria a tabela de
        # códigos virar a lista de quem TENTOU, que é justamente o dado que
        # não se quer ter.
        return {"ok": True, "mensagem": RESPOSTA_PEDIDO}

    codigo = f"{secrets.randbelow(900000) + 100000}"
    pglocal.executar(
        """INSERT INTO mot_codigos(telefone, codigo_hash, expira_em, ip)
           VALUES (%(f)s, %(h)s, now() + (%(m)s * interval '1 minute'), %(ip)s)""",
        {"f": fone, "h": _hash(codigo), "ip": (ip or "")[:64],
         "m": VALIDADE_MIN}, esq)

    # O ENVIO INTEIRO VAI DENTRO DO `try`, E A RESPOSTA NÃO MUDA POR NADA QUE
    # ACONTEÇA AQUI. `wa.enviar` tem contrato de nunca levantar, mas o que vem
    # ANTES dele — ler a configuração da Z-API do banco local — pode: basta a
    # tabela de config não existir ainda. Uma exceção escapando daqui viraria
    # 500 para o número CADASTRADO e 200 para o desconhecido, e a resposta
    # uniforme deixaria de ser uniforme exatamente no caso que ela protege.
    try:
        geral = zcfg.ler()
        r = wa.enviar(
            fone, TEXTO.format(codigo=codigo),
            usuario="app-motorista", origem="motorista_entrada",
            instancia=_instancia(), http=http, esquema=esq,
            # A janela vai aberta AQUI e só aqui — ver o docstring do módulo. O
            # resto das regras é o da casa, de propósito: o teto do dia continua
            # protegendo o número.
            regras={**geral, "janela_inicio": "00:00", "janela_fim": "23:59",
                    "limite_numero": geral["limite_dia"], "limite_modelo": None})
        if not r.get("ok"):
            # O motivo vai para o log (é operação: WhatsApp desligado, teto do
            # dia, aparelho desconectado) e NÃO vai para a resposta. Sem o
            # telefone junto: a trilha de quem recebeu o quê é a `zap_envios`,
            # que `enviar` já escreveu.
            log.warning("código de entrada não saiu: %s",
                        r.get("erro") or "sem motivo")
    except Exception as exc:  # noqa: BLE001 — o contrato é a resposta uniforme
        log.warning("código de entrada falhou antes do envio: %s",
                    type(exc).__name__)
    return {"ok": True, "mensagem": RESPOSTA_PEDIDO}


def confirmar(telefone_bruto: str, codigo: str, *, aparelho: str = "",
              motorista: str = "", ip: str = "", agente: str = "",
              esquema: str | None = None) -> dict:
    """Confere o código e abre a sessão.

    Devolve `{"escolher": [...]}` quando o telefone serve a MAIS DE UM
    motorista (medido: 5 casos em 585). Nesse caminho o código NÃO é
    consumido — a pessoa acabou de prová-lo, e queimá-lo para perguntar quem
    ela é obrigaria a pedir outro só por dividir o aparelho com um colega.
    """
    from . import sessao as ses

    esq = _esq(esquema)
    fone = _normalizar(telefone_bruto)
    digitado = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if not fone or not digitado:
        raise Recusa(RECUSA_CODIGO)

    linha = pglocal.um(
        """SELECT id, codigo_hash, tentativas FROM mot_codigos
            WHERE telefone = %(f)s AND usado_em IS NULL AND expira_em > now()
            ORDER BY criado_em DESC LIMIT 1""",
        {"f": fone}, esq)
    if not linha:
        raise Recusa(RECUSA_CODIGO)

    # A tentativa é contada ANTES da comparação. Contar depois deixaria de fora
    # exatamente as que interessam — as que erram —, e o teto nunca chegaria.
    tentativas = int(linha["tentativas"]) + 1
    pglocal.executar(
        "UPDATE mot_codigos SET tentativas = %(t)s WHERE id = %(id)s",
        {"t": tentativas, "id": linha["id"]}, esq)
    if tentativas > MAX_TENTATIVAS:
        pglocal.executar(
            "UPDATE mot_codigos SET usado_em = now() WHERE id = %(id)s",
            {"id": linha["id"]}, esq)
        raise Recusa(RECUSA_CODIGO)

    if not hmac.compare_digest(str(linha["codigo_hash"]), _hash(digitado)):
        raise Recusa(RECUSA_CODIGO)

    vinculos = _vinculos(fone, esq)
    if not vinculos:
        # O vínculo caiu entre o pedido e a confirmação (desligamento). Recusa
        # legível e diferente: aqui a pessoa PROVOU quem é, então esconder o
        # motivo só a faria tentar de novo para sempre.
        pglocal.executar(
            "UPDATE mot_codigos SET usado_em = now() WHERE id = %(id)s",
            {"id": linha["id"]}, esq)
        raise Recusa("Este número não tem acesso ao app. Fale com a torre.")

    escolhido = str(motorista or "").strip()
    if len(vinculos) > 1 and not escolhido:
        return {"escolher": [{"codigo": v["motorista_codigo"],
                              "nome": v["nome"] or ""} for v in vinculos]}
    if escolhido and escolhido not in {v["motorista_codigo"] for v in vinculos}:
        raise Recusa(RECUSA_CODIGO)
    alvo = escolhido or vinculos[0]["motorista_codigo"]

    # Consumir o código invalida TODOS os outros em aberto do mesmo telefone:
    # se alguém pediu três seguidos, os dois não usados não podem continuar
    # valendo depois que um deles já abriu uma sessão.
    pglocal.executar(
        """UPDATE mot_codigos SET usado_em = now()
            WHERE telefone = %(f)s AND usado_em IS NULL""",
        {"f": fone}, esq)

    sessao_id = ses.abrir(alvo, aparelho=aparelho, ip=ip, agente=agente,
                          esquema=esq)
    return {"ok": True, "motorista_codigo": alvo,
            "nome": next(v["nome"] for v in vinculos
                         if v["motorista_codigo"] == alvo),
            "token": ses.emitir(alvo, sessao_id), "sessao_id": sessao_id}
