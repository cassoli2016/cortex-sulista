"""Rotinas agendadas de WhatsApp — o QUE mandar, para QUEM, e o que impede.

O QUANDO vem de `api/agendamento.py`, o mesmo módulo que o correio usa. Aqui
fica só o que é do canal.

AS GUARDAS PRÓPRIAS DESTE CANAL, e a primeira é a que mais importa:

1. **DADO RUIM NÃO VIRA MENSAGEM.** Se o provedor não conseguir preencher todas
   as variáveis — o AVA fora do ar, o mês sem movimento —, a rotina REGISTRA e
   NÃO ENVIA. Uma automação que manda "Faturamento de hoje: R$ 0,00" às 8h da
   manhã para a diretoria não é um bug pequeno: é um susto, e depois é um
   remetente que ninguém mais lê.
2. **Nasce desligada**, como todo o resto do módulo. Cadastrar não é autorizar
   a disparar.
3. **Passa pelo MESMO `enviar_modelo` da tela.** Não existe caminho paralelo:
   a rotina obedece ao interruptor geral, à janela, ao limite do número, ao
   sub-limite do modelo e à checagem de conexão. Um atalho "porque é
   automático" seria justamente o jeito de perder o número dormindo.
4. **A passagem é marcada mesmo sem enviar** — ver `api/agendamento.py`.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .. import migracoes, pglocal
from ..agendamento import FREQUENCIAS, descrever, deve_rodar, hhmm, proxima

log = logging.getLogger("cortex.whatsapp.agenda")

ESQUEMA: str | None = None

_COLUNAS = ("id, modelo, destinatarios, instancia, frequencia, hora,"
            " dia_semana, dia_mes, dias_uteis, ativo, ultima_execucao,"
            " ultimo_resultado, criado_por, criado_em, alterado_por, alterado_em")


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def validar(dados: dict) -> dict:
    """Normaliza e recusa o que não dá para agendar.

    Recusar na GRAVAÇÃO, e não no disparo: erro que só aparece numa rotina
    desassistida às 8h da manhã é erro que ninguém vê — e que fica quebrado
    até alguém notar a ausência da mensagem, o que pode levar semanas.
    """
    from . import cliente, modelos, numeros

    chave = str(dados.get("modelo") or "").strip()
    if not chave:
        raise ValueError("Escolha o modelo de mensagem.")
    modelo = modelos.obter(chave)
    if not modelo:
        raise ValueError(f"O modelo “{chave}” não existe.")

    brutos = numeros.separar(dados.get("destinatarios") or "")
    if not brutos:
        raise ValueError("Informe ao menos um destinatário.")
    # GRUPO TAMBÉM É DESTINATÁRIO. A agenda nasceu só com telefone e usava
    # `valido`/`normalizar`, que recusam id de grupo — enquanto o ENVIO já
    # aceitava grupo desde sempre, por `destino`. O efeito era uma rotina que
    # não dava para cadastrar para um grupo, com a mensagem de erro errada
    # ("Telefone inválido") apontando para o lugar errado.
    ruins = [b for b in brutos if not numeros.destino_valido(b)]
    if ruins:
        raise ValueError("Destinatário inválido: " + ", ".join(ruins[:3]))
    # guardado NORMALIZADO, como a trilha: o mesmo número digitado de dois
    # jeitos viraria dois destinatários e gastaria duas fatias do limite
    dest = ", ".join(numeros.destino(b)[1] for b in brutos)

    freq = str(dados.get("frequencia") or "diario").strip().lower()
    if freq not in FREQUENCIAS:
        raise ValueError(f"Frequência deve ser uma de: {', '.join(FREQUENCIAS)}.")

    h, m = hhmm(dados.get("hora") or "08:00")

    dia_semana, dia_mes = dados.get("dia_semana"), dados.get("dia_mes")
    if freq == "semanal":
        try:
            dia_semana = int(dia_semana)
        except (TypeError, ValueError):
            raise ValueError("Escolha o dia da semana.") from None
        if not (1 <= dia_semana <= 7):
            raise ValueError("Dia da semana deve ser de 1 (segunda) a 7.")
        dia_mes = None
    elif freq == "mensal":
        try:
            dia_mes = int(dia_mes)
        except (TypeError, ValueError):
            raise ValueError("Escolha o dia do mês.") from None
        # 28 é o teto porque 29, 30 e 31 não existem em todo mês: um mensal
        # marcado no dia 31 não sairia em fevereiro nenhum, e ninguém saberia
        if not (1 <= dia_mes <= 28):
            raise ValueError("Dia do mês deve ser de 1 a 28 — 29, 30 e 31 não "
                             "existem em todos os meses.")
        dia_semana = None
    else:
        dia_semana = dia_mes = None

    inst = str(dados.get("instancia") or "").strip().lower()
    if inst and inst not in cliente.INSTANCIAS:
        raise ValueError(f"Número “{inst}” não existe.")

    return {"modelo": chave, "destinatarios": dest, "instancia": inst or None,
            "frequencia": freq, "hora": f"{h:02d}:{m:02d}",
            "dia_semana": dia_semana, "dia_mes": dia_mes,
            "dias_uteis": 1 if dados.get("dias_uteis", True) else 0,
            "ativo": 1 if dados.get("ativo") else 0}


def listar(esquema: str | None = None) -> list[dict]:
    init_db(esquema)
    return pglocal.query(f"SELECT {_COLUNAS} FROM zap_agenda ORDER BY id",
                         (), esquema=_esq(esquema))


def gravar(dados: dict, quem: str, esquema: str | None = None) -> dict:
    if not quem:
        raise ValueError("Informe quem está criando a rotina.")
    v = validar(dados)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    init_db(esquema)
    ident = dados.get("id")
    if ident:
        r = pglocal.um(
            "UPDATE zap_agenda SET modelo=%s, destinatarios=%s, instancia=%s,"
            " frequencia=%s, hora=%s, dia_semana=%s, dia_mes=%s, dias_uteis=%s,"
            " ativo=%s, alterado_por=%s, alterado_em=%s WHERE id=%s"
            " RETURNING id",
            (v["modelo"], v["destinatarios"], v["instancia"], v["frequencia"],
             v["hora"], v["dia_semana"], v["dia_mes"], v["dias_uteis"],
             v["ativo"], quem, agora, int(ident)), esquema=_esq(esquema))
        if not r:
            raise ValueError(f"Rotina {ident} não existe.")
        novo = int(r["id"])
    else:
        r = pglocal.um(
            "INSERT INTO zap_agenda(modelo, destinatarios, instancia,"
            " frequencia, hora, dia_semana, dia_mes, dias_uteis, ativo,"
            " criado_por, criado_em) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " RETURNING id",
            (v["modelo"], v["destinatarios"], v["instancia"], v["frequencia"],
             v["hora"], v["dia_semana"], v["dia_mes"], v["dias_uteis"],
             v["ativo"], quem, agora), esquema=_esq(esquema))
        novo = int(r["id"])
    return {**v, "id": novo}


def remover(ident: int, esquema: str | None = None) -> None:
    init_db(esquema)
    pglocal.executar("DELETE FROM zap_agenda WHERE id=%s", (int(ident),),
                     esquema=_esq(esquema))


def registrar_execucao(ident: int, resultado: str,
                       esquema: str | None = None) -> None:
    """Marca a passagem da rotina — INCLUSIVE quando não houve envio.

    É esta marca, e não o envio, que impede o disparo a cada passagem do
    agendador do Windows.
    """
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pglocal.executar("UPDATE zap_agenda SET ultima_execucao=%s,"
                     " ultimo_resultado=%s WHERE id=%s",
                     (agora, str(resultado)[:200], int(ident)),
                     esquema=_esq(esquema))


def montar_texto(chave: str, esquema: str | None = None) -> tuple[dict, str]:
    """Os valores do modelo, prontos para o envio — ou o motivo de não dar.

    Devolve `(valores, erro)`. **Erro não vazio significa NÃO ENVIAR**: uma
    rotina que manda "Faturamento de hoje: R$ 0,00" porque o ERP não respondeu
    assusta a diretoria de manhã e, depois de duas vezes, vira um remetente que
    ninguém lê.
    """
    from . import modelos, valores

    modelo = modelos.obter(chave, esquema=esquema)
    if not modelo:
        return {}, f"o modelo “{chave}” não existe mais"
    if not modelo["ativo"]:
        return {}, f"o modelo “{modelo['nome']}” está desligado"

    precisa = modelo.get("variaveis") or []
    if not precisa:
        return {}, ""                      # texto fixo, nada a preencher

    provedor = modelos.provedor_do_contexto(modelo["contexto"])
    if not provedor:
        return {}, (f"o modelo usa variáveis e o contexto "
                    f"“{modelo['contexto']}” não sabe preenchê-las sozinho — "
                    "só dá para mandar à mão")
    try:
        vals = valores.obter(provedor)
    except Exception as exc:   # noqa: BLE001 - rotina não pode levantar
        # A mensagem do provedor entra quando ele SABE dizer o motivo. "não foi
        # possível ler os números" é verdadeiro e inútil quando o motivo real é
        # "a coleta está parada há 40 h" — e é esse texto que vai para a tela.
        motivo = str(exc).strip()
        return {}, (motivo if isinstance(exc, ValueError) and motivo
                    else f"não foi possível ler os números ({type(exc).__name__})")

    # SILÊNCIO NÃO É FALHA. Um provedor pode legitimamente não ter o que dizer
    # hoje — nenhuma notificação vencendo, nenhum título a cobrar. Antes desta
    # linha isso caía na checagem de `faltando` abaixo e virava "faltou lista",
    # que é uma acusação de dado incompleto para um dia em que está tudo certo.
    # Quem separa os dois é `executar`.
    if vals.get("_silencio"):
        return vals, ""

    faltando = [v for v in precisa if not str(vals.get(v) or "").strip()]
    if faltando:
        return {}, ("faltou " + ", ".join(faltando)
                    + " — os números não vieram completos, nada foi enviado")
    return vals, ""


def executar(ag: dict, *, ensaio: bool = False, forcado: bool = False,
             http=None, esquema: str | None = None) -> str:
    """Roda UMA rotina e devolve o resultado em uma linha. Nunca levanta."""
    from .envio import enviar_modelo

    ident, chave = ag.get("id"), ag.get("modelo")
    vals, erro = montar_texto(chave, esquema=esquema)
    if erro:
        if not ensaio:
            registrar_execucao(ident, f"não enviado: {erro}", esquema)
        return f" --   #{ident} {chave}: {erro}"

    # NÃO HAVIA O QUE MANDAR — e isso é um terceiro estado, nem envio nem
    # falha. Registrar como falha faria a tela mostrar vermelho todo dia em que
    # a operação está em dia, e aí o vermelho para de querer dizer alguma
    # coisa. O motivo fica no histórico, que é onde serve.
    silencio = str(vals.get("_silencio") or "").strip()
    if silencio:
        if not ensaio:
            registrar_execucao(ident, f"nada a enviar: {silencio}", esquema)
        return f" ..   #{ident} {chave}: nada a enviar ({silencio})"

    if ensaio:
        anexo = vals.get("_anexo")
        extra = (" com anexo %s (%d KB)" % (anexo[1], len(anexo[0]) // 1024)
                 if anexo else "")
        return (f" .    #{ident} {chave}: enviaria para "
                f"{ag.get('destinatarios')}{extra}")

    # O ANEXO VEM DO PROVEDOR, com underscore como o `_silencio`: ele não é
    # variável do texto (não aparece em lugar nenhum do corpo) e por isso sai
    # de `vals` antes de ir para o `renderizar`, que só sabe substituir texto.
    # Quem decide se há anexo é quem tem o dado — o provedor —, nunca a agenda.
    anexo = vals.pop("_anexo", None)
    r = enviar_modelo(ag.get("destinatarios"), chave, vals,
                      usuario="agenda", origem="agenda" + (":forcado" if forcado else ""),
                      instancia=ag.get("instancia"), anexo=anexo,
                      http=http, esquema=esquema)
    registrar_execucao(
        ident,
        f"{r['enviados']} enviada(s), {r['falhas']} falha(s)"
        + (f": {r['erro']}" if r["erro"] else ""), esquema)
    if r["ok"]:
        return f"OK   #{ident} {chave} → {r['enviados']} destinatário(s)"
    return f"FALHA #{ident} {chave}: {r['erro'][:140]}"


def estado(esquema: str | None = None) -> dict:
    """Tudo que a tela precisa, com o motivo de cada rotina não estar pronta."""
    from . import modelos

    nomes = {m["chave"]: m["nome"] for m in modelos.listar(esquema)}
    itens = []
    for ag in listar(esquema):
        pode, porque = deve_rodar(ag)
        itens.append({**ag, "quando": descrever(ag), "proxima": proxima(ag),
                      "pronto": pode, "motivo": porque,
                      # modelo excluído aparece com o nome cru e a rotina
                      # recusa na hora — some da tela seria pior
                      "modelo_nome": nomes.get(ag["modelo"], ag["modelo"])})
    return {"rotinas": itens,
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
