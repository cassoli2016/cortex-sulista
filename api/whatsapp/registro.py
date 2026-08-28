"""Trilha das mensagens de WhatsApp — PostgreSQL local, schema `cortex`.

Irmã da `correio_envios`, com a mesma regra: **toda tentativa é gravada,
inclusive a que falhou.** Registro só de sucesso esconde justamente o caso que
se precisa investigar ("o cliente diz que não recebeu").

O QUE ESTA TRILHA TEM A MAIS QUE A DO E-MAIL: ela é lida ANTES de cada envio.
`contar_destinatarios_hoje()` é o que alimenta o freio do `envio.py`. Isso muda
duas coisas no desenho:

- o telefone é gravado SEMPRE normalizado (só dígitos, com DDI), senão o mesmo
  cliente contaria como vários destinatários distintos;
- a consulta do contador tem índice próprio (`ix_zap_envios_tel`), porque roda
  a cada mensagem e não uma vez por tela.

Só o envio que DEU CERTO conta para o limite. Uma tentativa recusada pela
Z-API não chegou a WhatsApp nenhum — contá-la faria uma sequência de erros de
configuração consumir a cota do dia e travar o envio de verdade depois.

E O CONTADOR É POR INSTÂNCIA. São dois aparelhos, com dois números e duas
reputações independentes: o WhatsApp não bane o reserva por causa do que o
principal fez. Um contador compartilhado erraria nas duas direções — mandar 60
pelo principal bloquearia o reserva, que não fez nada; e ignorar a separação
deixaria passar duas vezes o limite achando que é um número só.
"""
from __future__ import annotations

from datetime import datetime

from .. import migracoes, pglocal

# A trilha serve para conferir O QUE foi dito, não para virar arquivo.
MAX_MENSAGEM = 4000

# Manopla de redirecionamento (mesmo padrão dos outros stores): o teste faz
# `monkeypatch.setattr(registro, "ESQUEMA", <schema do teste>)`.
ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def gravar(telefone: str, mensagem: str, *, usuario: str = "",
           origem: str = "", ok: bool = False, erro: str = "",
           message_id: str = "", modelo: str = "", instancia: str = "principal",
           esquema: str | None = None) -> int:
    init_db(esquema)
    r = pglocal.um(
        "INSERT INTO zap_envios"
        " (ts, usuario, telefone, mensagem, origem, ok, erro, message_id,"
        "  modelo, instancia)"
        " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), usuario or "",
         telefone or "", (mensagem or "")[:MAX_MENSAGEM], origem or "",
         1 if ok else 0, erro or "", message_id or "", modelo or "",
         instancia or "principal"),
        esquema=_esq(esquema))
    return int(r["id"])


def listar(limite: int = 100, esquema: str | None = None) -> list[dict]:
    init_db(esquema)
    return pglocal.query(
        "SELECT id, ts, usuario, telefone, mensagem, origem, ok, erro,"
        " message_id, modelo, instancia"
        " FROM zap_envios ORDER BY id DESC LIMIT %s",
        (int(limite),), esquema=_esq(esquema))


def contar_destinatarios_hoje(esquema: str | None = None, *,
                              instancia: str = "principal") -> int:
    """Números DISTINTOS que ESTA instância alcançou hoje, com sucesso.

    É este número — e não o total de mensagens — que o WhatsApp usa como sinal
    de spam, segundo a própria documentação da Z-API. Dia de calendário e não
    janela de 24 h porque o operador precisa saber quando a cota volta, e
    "meia-noite" é uma resposta que ele entende.

    Por instância porque a reputação é do NÚMERO: o que o principal fez não
    aproxima o reserva de um banimento, e vice-versa.
    """
    init_db(esquema)
    hoje = datetime.now().strftime("%Y-%m-%d")
    r = pglocal.um(
        "SELECT count(DISTINCT telefone) AS n FROM zap_envios"
        " WHERE ok=1 AND instancia=%s AND ts >= %s",
        (instancia or "principal", hoje + " 00:00:00"), esquema=_esq(esquema))
    return int(r["n"] or 0)


def ja_falou_hoje(telefone: str, esquema: str | None = None, *,
                  instancia: str = "principal") -> bool:
    """Se ESTA instância já falou com ESTE número hoje, mandar outra não gasta
    destinatário distinto — a conversa já existe, e é o caso menos arriscado
    de todos. O freio deixa passar.

    A conversa é do PAR (aparelho, cliente): o cliente ter falado hoje com o
    número principal não abre conversa nenhuma no reserva, que para ele é um
    desconhecido — exatamente o caso que o freio existe para conter.
    """
    init_db(esquema)
    hoje = datetime.now().strftime("%Y-%m-%d")
    r = pglocal.um(
        "SELECT count(*) AS n FROM zap_envios"
        " WHERE ok=1 AND telefone=%s AND instancia=%s AND ts >= %s",
        (telefone, instancia or "principal", hoje + " 00:00:00"),
        esquema=_esq(esquema))
    return bool(r["n"])


def resumo(esquema: str | None = None) -> dict:
    """Panorama da trilha inteira + o gasto do dia DE CADA instância.

    `hoje` continua sendo o da principal, para não quebrar quem já lê essa
    chave; `hoje_por_instancia` é o que a tela usa para mostrar a cota de cada
    número ao lado do seletor de envio.
    """
    init_db(esquema)
    r = pglocal.um(
        "SELECT count(*) AS total,"
        " count(*) FILTER (WHERE ok=1) AS ok,"
        " count(*) FILTER (WHERE ok=0) AS falha,"
        " count(DISTINCT telefone) FILTER (WHERE ok=1) AS numeros,"
        " max(ts) AS ultimo FROM zap_envios", esquema=_esq(esquema))
    por_inst = {q: contar_destinatarios_hoje(esquema, instancia=q)
                for q in ("principal", "backup")}
    return {"total": r["total"] or 0, "ok": r["ok"] or 0,
            "falha": r["falha"] or 0, "numeros": r["numeros"] or 0,
            "ultimo": r["ultimo"],
            "hoje": por_inst["principal"],
            "hoje_por_instancia": por_inst}
