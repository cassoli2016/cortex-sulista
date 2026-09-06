# -*- coding: utf-8 -*-
"""O painel de administração dos monitoramentos de carga.

QUEM SE INSCREVE NA PÁGINA PÚBLICA NÃO TEM CONTA, e por isso ninguém aqui
dentro sabia o que estava em voo: quantas pessoas acompanham uma carga agora,
quantas foram avisadas, quem cancelou e por quê. A inscrição nascia, mandava
mensagem de hora em hora e morria sozinha sem nunca aparecer numa tela. Este
módulo é o outro lado daquele balcão.

DUAS COISAS QUE DECIDEM O RESTO DO ARQUIVO

1. **São DOIS BANCOS, e não dá para juntar num `JOIN`.** A inscrição mora no
   CÓRTEX (PostgreSQL 16, `rst_inscricao`); a carga mora no AVA, que é a
   réplica do ERP (PostgreSQL 9.3, `conhecimento`). O caminho é: ler as
   inscrições de um lado e buscar TODAS as cargas do outro numa consulta só,
   por chave de texto. Uma consulta por linha seria N+1 contra uma réplica de
   terceiro — e é assim que se derruba a tela no dia em que houver duzentas
   inscrições.

2. **`ultimo_envio` velho NÃO É FALHA, e a tela não pode pintar de vermelho.**
   O aviso não reenvia mensagem idêntica à anterior (é o que separa "aviso de
   hora em hora" de "24 mensagens iguais por dia", que faz a pessoa bloquear o
   número da empresa). Um caminhão parado a noite inteira produz, corretamente,
   zero envio. O painel diz há quanto tempo foi o último e DIZ POR QUE isso
   pode ser normal, em vez de acender um alarme que ensina a ignorar alarmes.

O QUE ESTA TELA MOSTRA E A PÚBLICA NÃO: o telefone de quem se inscreveu. É
tela autenticada, com RBAC por tela (`mon`), e sem o número não há como
atender quem liga. Ele NUNCA entra em URL — vai no corpo da resposta, e a ação
de encerrar manda o `id` da inscrição.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from .. import db, pglocal
from ..whatsapp import numeros
from . import consulta

log = logging.getLogger("cortex.rastreio.painel")

#: Teto de linhas por lista. Não é paginação — é o limite que impede uma tela
#: de administração de virar um dump da tabela no dia em que ela crescer.
TETO_LISTA = 300

#: Janela padrão do histórico e da série, em dias.
DIAS_PADRAO = 14

#: O que cada `cancelado_por` quer dizer. **CÓDIGO SEM TABELA DE DOMÍNIO NÃO
#: VIRA RÓTULO INVENTADO**: `encerrar()` aceita texto livre, então o que não
#: estiver aqui aparece CRU na tela, dizendo que é cru — melhor um código feio
#: e verdadeiro que um rótulo bonito e errado.
MOTIVOS = {
    "entregue": "Carga entregue",
    "pagina": "Cancelou na página",
    "whatsapp": "Respondeu SAIR no WhatsApp",
}


def _fim(ins: dict) -> tuple[str, str]:
    """Como a inscrição terminou: (chave, rótulo)."""
    if ins.get("ativo") and ins.get("expirada"):
        # EXPIRAR NÃO É CANCELAR. A inscrição morre sozinha aos 15 dias porque
        # ninguém volta para cancelar; contar isso como desistência faria a
        # taxa de cancelamento mentir para cima.
        return "expirada", "Expirou sozinha"
    if ins.get("ativo"):
        return "ativa", "Acompanhando"
    por = (ins.get("cancelado_por") or "").strip()
    if por in MOTIVOS:
        return por, MOTIVOS[por]
    if not por:
        return "encerrada", "Encerrada (motivo não registrado)"
    # QUEM ENCERROU PELA TELA VAI PARA UM BALDE SÓ. `cancelado_por` guarda
    # `admin:<e-mail>`, e agrupar por esse texto cru faria a tabela "como os
    # monitoramentos terminam" ganhar UMA LINHA POR ADMINISTRADOR — um campo
    # de identidade virando dimensão, que é como uma tabela de resumo deixa de
    # caber na tela. O e-mail não se perde: ele continua no `fim_detalhe` da
    # linha do histórico, que é onde a pergunta "quem foi?" se faz.
    if por.startswith("admin:"):
        return "admin", "Encerrada pela administração"
    return "outro", "Encerrada — %s" % por


def _chave(r: dict) -> str:
    return "%s|%s|%s|%s|%s" % (r["grupo"], r["empresa"], r["filial"],
                               r["numero"], r["serie"])


#: As cargas de um lote de inscrições, do AVA, numa consulta só.
#:
#: A chave vai como TEXTO concatenado em vez de cinco listas paralelas: é o
#: mesmo padrão de `queries.py` para chave composta, funciona no 9.3 e não
#: depende de o driver adaptar tupla de tuplas.
CARGAS_SQL = """
SELECT c.grupo, c.empresa, c.filial, c.numero, c.serie,
       c.dtemissao, c.dtentrega, c.dtiniciodescarga, c.dtprevisaoentrega,
       trim(c.veiculo)  AS placa,
       c.cidadecoleta, c.ufcoleta,
       cd.nomefantasia  AS destinatario_nome,
       cd.cidade        AS destinatario_cidade,
       cd.uf            AS destinatario_uf
FROM conhecimento c
LEFT JOIN cadastro cd ON cd.codigo = c.destinatario
WHERE (c.grupo::text || '|' || c.empresa::text || '|' || c.filial::text
       || '|' || c.numero::text || '|' || c.serie::text) = ANY(%(chaves)s)
"""


def _cargas(linhas: list[dict]) -> dict:
    """`{chave: carga}` para o lote inteiro. Nunca levanta.

    A RÉPLICA DO ERP PODE ESTAR COM UM DIA RUIM e esta tela não morre por
    isso: sem as cargas, as inscrições ainda aparecem — com documento, telefone
    e datas, que é o que vive no banco da casa. O que some é o enriquecimento,
    e a tela diz que ele faltou em vez de fingir que a carga não existe.
    """
    chaves = sorted({_chave(r) for r in linhas})
    if not chaves:
        return {}
    try:
        return {_chave(dict(r)): dict(r)
                for r in db.query(CARGAS_SQL, {"chaves": chaves})}
    except Exception as exc:  # noqa: BLE001
        log.warning("painel de monitoramentos: cargas nao vieram: %s",
                    type(exc).__name__)
        return {}


def _idade_min(quando) -> int | None:
    if not quando:
        return None
    try:
        agora = (datetime.now(timezone.utc) if quando.tzinfo
                 else datetime.now())
        return max(0, int((agora - quando).total_seconds() / 60))
    except Exception:  # noqa: BLE001
        return None


def _linha(ins: dict, cargas: dict) -> dict:
    """Uma inscrição, pronta para a tela."""
    carga = cargas.get(_chave(ins)) or {}
    chave_fim, rotulo_fim = _fim(ins)
    estado, estado_rotulo = (consulta._estado(carga) if carga
                             else ("desconhecido", "Carga não encontrada"))
    return {
        "id": ins["id"],
        "documento": "CT-e %s" % ins["numero"],
        "origem": consulta._lugar(carga.get("cidadecoleta"),
                                  carga.get("ufcoleta")),
        "destino": consulta._lugar(carga.get("destinatario_cidade"),
                                   carga.get("destinatario_uf")),
        "destinatario": (carga.get("destinatario_nome") or "").strip() or None,
        "estado": estado,
        "estado_rotulo": estado_rotulo,
        # FORMATADO NA EXIBIÇÃO, guardado normalizado — a casa tem UM validador
        # de telefone e é ele que manda no formato.
        "telefone": numeros.formatar(ins["telefone"]),
        "criado_em": consulta._iso(ins.get("criado_em")),
        "expira_em": consulta._iso(ins.get("expira_em")),
        "envios": int(ins.get("envios") or 0),
        "ultimo_envio": consulta._iso(ins.get("ultimo_envio")),
        "ultimo_envio_min": _idade_min(ins.get("ultimo_envio")),
        "encerrado_em": consulta._iso(ins.get("cancelado_em")),
        "fim": chave_fim,
        "fim_rotulo": rotulo_fim,
        # QUEM, quando houve um quem. Fica FORA do rótulo de propósito: o
        # rótulo é a dimensão que a tabela de resumo agrupa, e identidade
        # dentro de dimensão é o que faz a linha se multiplicar.
        "fim_detalhe": ((ins.get("cancelado_por") or "")[6:].strip() or None
                        if (ins.get("cancelado_por") or "").startswith("admin:")
                        else None),
        "horas": _horas(ins),
    }


def _horas(ins: dict) -> float | None:
    """Quanto tempo a inscrição durou (ou dura), em horas."""
    ini, fim = ins.get("criado_em"), ins.get("cancelado_em")
    if not ini:
        return None
    if not fim:
        fim = datetime.now(timezone.utc) if ini.tzinfo else datetime.now()
    try:
        return round((fim - ini).total_seconds() / 3600.0, 1)
    except Exception:  # noqa: BLE001
        return None


LISTA_SQL = """
SELECT id, grupo, empresa, filial, numero, serie, telefone,
       criado_em, expira_em, ativo, cancelado_em, cancelado_por,
       ultimo_envio, envios,
       (ativo AND expira_em <= now()) AS expirada
FROM rst_inscricao
WHERE (%(ativas)s AND ativo AND expira_em > now())
   OR (NOT %(ativas)s AND (NOT ativo OR expira_em <= now()))
ORDER BY coalesce(cancelado_em, criado_em) DESC
LIMIT %(teto)s
"""


def _listar(ativas: bool) -> list[dict]:
    try:
        return [dict(r) for r in pglocal.query(
            LISTA_SQL, {"ativas": ativas, "teto": TETO_LISTA})]
    except Exception as exc:  # noqa: BLE001
        log.warning("painel de monitoramentos: lista falhou: %s",
                    type(exc).__name__)
        return []


RESUMO_SQL = """
SELECT
  count(*)::int AS total,
  sum(CASE WHEN ativo AND expira_em >  now() THEN 1 ELSE 0 END)::int AS ativas,
  sum(CASE WHEN ativo AND expira_em <= now() THEN 1 ELSE 0 END)::int AS expiradas,
  sum(CASE WHEN NOT ativo THEN 1 ELSE 0 END)::int AS encerradas,
  sum(CASE WHEN NOT ativo AND cancelado_por = 'entregue' THEN 1 ELSE 0 END)::int
    AS por_entrega,
  count(DISTINCT CASE WHEN ativo AND expira_em > now() THEN telefone END)::int
    AS fones_ativos,
  count(DISTINCT CASE WHEN ativo AND expira_em > now()
        THEN (grupo, empresa, filial, numero, serie) END)::int AS cargas_ativas,
  count(DISTINCT telefone)::int AS fones,
  count(DISTINCT (grupo, empresa, filial, numero, serie))::int AS cargas,
  coalesce(sum(envios), 0)::int AS envios,
  max(ultimo_envio) AS ultimo_envio,
  min(criado_em)    AS primeira,
  sum(CASE WHEN criado_em > now() - interval '24 hours' THEN 1 ELSE 0 END)::int
    AS novas_24h
FROM rst_inscricao
"""


def _resumo() -> dict:
    try:
        return dict(pglocal.query(RESUMO_SQL, ())[0])
    except Exception as exc:  # noqa: BLE001
        log.warning("painel de monitoramentos: resumo falhou: %s",
                    type(exc).__name__)
        return {}


#: A série de inscrições por dia.
#:
#: O INTERVALO É GERADO, não colhido: `GROUP BY` não devolve o dia em que
#: ninguém se inscreveu, e a série emendaria segunda em quinta desenhando uma
#: reta que nunca existiu. E ela COMEÇA NA PRIMEIRA INSCRIÇÃO — desenhar dias
#: anteriores ao nascimento do recurso mostraria zeros que não são queda de
#: desempenho, são um recurso que ainda não existia.
SERIE_SQL = """
WITH lim AS (
  SELECT greatest(current_date - (%(dias)s::int - 1),
                  coalesce(min(criado_em)::date, current_date)) AS ini
  FROM rst_inscricao
), dias AS (
  SELECT generate_series((SELECT ini FROM lim), current_date, '1 day')::date AS d
)
SELECT d.d AS dia,
       count(i.id)::int AS novas,
       coalesce(sum(CASE WHEN i.cancelado_em::date = d.d THEN 1 ELSE 0 END), 0)::int
         AS encerradas
FROM dias d
LEFT JOIN rst_inscricao i ON i.criado_em::date = d.d
GROUP BY d.d ORDER BY d.d
"""


def _serie(dias: int) -> list[dict]:
    try:
        return [{"dia": r["dia"].isoformat() if isinstance(r["dia"], date)
                 else str(r["dia"]),
                 "novas": int(r["novas"] or 0)}
                for r in pglocal.query(SERIE_SQL, {"dias": dias})]
    except Exception as exc:  # noqa: BLE001
        log.warning("painel de monitoramentos: serie falhou: %s",
                    type(exc).__name__)
        return []


#: Quem está perto dos tetos do módulo. É a parte ACIONÁVEL da tela: teto
#: batido é gente que tentou acompanhar mais uma carga e não conseguiu, e isso
#: não aparece em lugar nenhum hoje.
FREIOS_SQL = """
SELECT telefone,
       count(*)::int AS ativas,
       max(criado_em) AS ultima
FROM rst_inscricao
WHERE ativo AND expira_em > now()
GROUP BY telefone
HAVING count(*) >= %(piso)s
ORDER BY 2 DESC, 3 DESC
LIMIT 20
"""


def _freios() -> dict:
    """Telefones e cargas encostando nos tetos de `assinatura`."""
    from . import assinatura
    piso = max(1, assinatura.MAX_ATIVAS_POR_FONE - 1)
    try:
        fones = [{"telefone": numeros.formatar(r["telefone"]),
                  "ativas": int(r["ativas"]),
                  "no_teto": int(r["ativas"]) >= assinatura.MAX_ATIVAS_POR_FONE}
                 for r in pglocal.query(FREIOS_SQL, {"piso": piso})]
    except Exception as exc:  # noqa: BLE001
        log.warning("painel de monitoramentos: freios falharam: %s",
                    type(exc).__name__)
        fones = []
    return {"telefones": fones,
            "teto_por_fone": assinatura.MAX_ATIVAS_POR_FONE,
            "teto_por_carga": assinatura.MAX_POR_CARGA,
            "teto_criadas_24h": assinatura.MAX_CRIADAS_24H,
            "dias_validade": assinatura.DIAS_VALIDADE}


def painel(dias: int = DIAS_PADRAO) -> dict:
    """Tudo o que a tela `mon` mostra. Nunca levanta.

    UM PAYLOAD SÓ para a tela inteira: são quatro listas pequenas do mesmo
    assunto, e quatro rotas dariam quatro estados de carregamento para
    reconciliar por nada.
    """
    dias = max(2, min(90, int(dias or DIAS_PADRAO)))
    ativas = _listar(True)
    passadas = _listar(False)
    # UM LOTE SÓ contra o ERP, com as chaves das duas listas juntas.
    cargas = _cargas(ativas + passadas)
    r = _resumo()
    envio = r.get("ultimo_envio")
    return {
        "ok": True,
        "resumo": {
            "ativas": int(r.get("ativas") or 0),
            "cargas_ativas": int(r.get("cargas_ativas") or 0),
            "fones_ativos": int(r.get("fones_ativos") or 0),
            "novas_24h": int(r.get("novas_24h") or 0),
            "total": int(r.get("total") or 0),
            "encerradas": int(r.get("encerradas") or 0),
            "expiradas": int(r.get("expiradas") or 0),
            "por_entrega": int(r.get("por_entrega") or 0),
            "cargas": int(r.get("cargas") or 0),
            "fones": int(r.get("fones") or 0),
            "envios": int(r.get("envios") or 0),
            "ultimo_envio": consulta._iso(envio),
            "ultimo_envio_min": _idade_min(envio),
            "primeira": consulta._iso(r.get("primeira")),
        },
        "ativas": [_linha(i, cargas) for i in ativas],
        "historico": [_linha(i, cargas) for i in passadas],
        "serie": _serie(dias),
        "freios": _freios(),
        "cargas_faltando": bool((ativas or passadas) and not cargas),
        "dias": dias,
        "consultado_em": datetime.now(timezone.utc).isoformat(),
    }


def encerrar(ident: int, usuario: str) -> dict:
    """Encerra uma inscrição pela tela de administração.

    O MOTIVO GRAVADO DIZ QUEM FOI. `cancelado_por` é o campo que a tela lê para
    contar por que as inscrições terminam, e um "cancelado" genérico misturaria
    a desistência de quem espera a carga com a intervenção de quem administra —
    que são coisas opostas para quem lê o número.
    """
    from . import assinatura
    try:
        ident = int(ident)
    except (TypeError, ValueError):
        return {"ok": False, "motivo": "inscrição inválida"}
    linhas = pglocal.query(
        "SELECT id FROM rst_inscricao WHERE id = %s AND ativo", (ident,))
    if not linhas:
        # RECUSA LEGÍVEL É 4xx, e a rota devolve 409: já encerrada não é falha
        # nossa, e um 500 aqui viraria a página do Cloudflare.
        return {"ok": False, "motivo": "inscrição já encerrada ou inexistente"}
    assinatura.encerrar(ident, "admin:%s" % (usuario or "?")[:30])
    return {"ok": True}
