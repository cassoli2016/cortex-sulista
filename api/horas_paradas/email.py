"""O E-MAIL DAS HORAS PARADAS — o resumo do período e a planilha anexada.

Pedido de quem opera (13/09/2026): montar o e-mail com as horas paradas e a
planilha, para os destinatários que quem está na tela decidir, com um lugar
para dizer a quem a resposta deve voltar — o e-mail sai do endereço do
sistema, que ninguém lê.

O QUE O CLIENTE RECEBE é o que a tela mostra, e não uma segunda conta: o
resumo e a tabela saem de `servico.montar`, e o anexo é `servico.planilha_do`
das MESMAS linhas — o mesmo arquivo que o botão "Baixar planilha" entrega.
O que é interno não sai: nem os ajustes manuais com motivo, nem a regra que
respondeu, nem o valor que o ERP daria.

O ENVIO é o do módulo de correio da casa (`api/correio/envio.py`), que nunca
levanta, grava toda tentativa na trilha de e-mails e transforma
`responder_para` em `Reply-To`. E o `responder_para` é o e-mail de QUEM
ENVIA (decisão de quem opera, 13/09/2026): a rota o tira da sessão e ignora o
que vier no pedido — a dúvida do cliente volta para quem mandou a planilha. Aqui fica a outra pergunta — "a planilha
desta semana deste cliente já foi mandada, para quem, e por quem?" —, em
`hp_envio`, com a linha aberta ANTES do envio e fechada depois.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from .. import pglocal
from . import cadastro, planilha, servico

log = logging.getLogger("cortex.horas_paradas")

ORIGEM = "horas_paradas"
MAX_MENSAGEM = 2000

_FRASE_INICIO = {
    "maior": "a partir do horário marcado — ou da chegada do veículo, quando ele chegou depois dele —",
    "janela": "a partir do horário marcado",
    "chegada": "a partir da chegada do veículo",
}


def _hm(segundos) -> str:
    if not segundos:
        return "—"
    m = int(round(segundos / 60))
    return "%dh%02d" % (m // 60, m % 60)


def _br(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _paragrafos(mensagem: str) -> list[str]:
    """A mensagem de quem envia, em parágrafos (linha em branco separa)."""
    mensagem = (mensagem or "").strip()
    if len(mensagem) > MAX_MENSAGEM:
        raise cadastro.Recusa("Mensagem de até %d caracteres." % MAX_MENSAGEM)
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", mensagem) if p.strip()]


def _como_conta(cfg: dict) -> str:
    c, d = cfg["inicio_carga"], cfg["inicio_descarga"]
    if c == d:
        base = ("No carregamento e na descarga, o tempo conta %s até a saída do veículo"
                % _FRASE_INICIO[d])
    else:
        base = ("No carregamento, o tempo conta %s até a saída; na descarga, %s até o "
                "fim da descarga" % (_FRASE_INICIO[c], _FRASE_INICIO[d]))
    if any(r.get("inicio") for r in cfg.get("regras") or []):
        base += " (com as exceções combinadas por mercadoria)"
    arred = int(cfg.get("arredondamento_min") or 0)
    cobra = ("por minuto" if not arred
             else "arredondado para cima a cada %d minutos" % arred)
    return (base + ". O que passa do tempo combinado em contrato é cobrado pelo "
            "valor da hora do contrato, " + cobra + ".")


def montar(perfil_id: int, de: str, ate: str, mensagem: str = "",
           esquema: str | None = None) -> dict:
    """Assunto, HTML, texto e o anexo — sem enviar nada."""
    from ..correio import painel as p

    paragrafos = _paragrafos(mensagem)
    d = servico.montar(perfil_id, de, ate, esquema=esquema)
    cfg = d["perfil"]["config"]
    r = d["resumo"]
    cliente = d["perfil"]["cliente_nome"]
    ctx = servico.contexto(d)
    nome, conteudo = servico.planilha_do(d)
    assunto = planilha.substituir(cfg["email"]["assunto"], ctx)

    inc = [ln for ln in d["linhas"] if ln["incluida"]]
    exced = [ln for ln in inc if ln["valor"] > 0]
    hc, hd = r["horas_carga"] * 3600, r["horas_descarga"] * 3600

    blocos = [p.kpis([
        {"rotulo": "Horas paradas no período", "valor": p.brl(r["valor_total"], 2),
         "estado": "neutro",
         "sub": "carregamento %s · descarga %s" % (p.brl(r["valor_carga"], 2),
                                                   p.brl(r["valor_descarga"], 2))},
        {"rotulo": "Cargas no período", "valor": p.inteiro(r["cargas"]),
         "estado": "neutro", "sub": "%d com tempo excedido" % r["com_excedente"]},
        {"rotulo": "Tempo excedido", "valor": _hm(hc + hd), "estado": "neutro",
         "sub": "carregamento %s · descarga %s" % (_hm(hc), _hm(hd))},
        {"rotulo": "Período", "valor": "%s a %s" % (_br(de)[:5], _br(ate)[:5]),
         "estado": "neutro", "sub": "semana %d" % d["periodo"]["semana"]},
    ])]
    for i, par in enumerate(paragrafos):
        blocos.append(p.paragrafo(par, destaque=(i == 0)))

    linhas = [[str(ln["coleta"]), ln["referencia"] or "—",
               ln["frota_cavalo"] or ln["placa_cavalo"] or "—",
               "%s → %s" % (ln["mercadoria"] or "—", ln["destino"] or "—"),
               _hm(ln["carga"]["cobrado_s"]), _hm(ln["descarga"]["cobrado_s"]),
               p.brl(ln["valor"], 2)] for ln in exced]
    blocos.append(p.secao("Cargas com tempo excedido",
                          "%d de %d cargas do período" % (len(exced), r["cargas"])))
    blocos.append(p.tabela(
        ["Coleta", "Referência", "Veículo", "Carga → destino", "Carreg.", "Descarga", "Valor"],
        linhas, alinha_dir=(4, 5, 6),
        vazio="Nenhuma carga passou do tempo combinado neste período."))
    blocos.append(p.secao("Como ler"))
    blocos.append(p.paragrafo(
        _como_conta(cfg) + " A planilha anexa (%s) traz as %d cargas do período, "
        "com todos os horários." % (nome, r["cargas"])))

    texto = ["Horas paradas — %s — %s a %s" % (cliente, _br(de), _br(ate)), ""]
    texto += paragrafos + ([""] if paragrafos else [])
    texto += ["Total: %s (carregamento %s · descarga %s)"
              % (p.brl(r["valor_total"], 2), p.brl(r["valor_carga"], 2),
                 p.brl(r["valor_descarga"], 2)),
              "Cargas no período: %d · com tempo excedido: %d" % (r["cargas"], len(exced)),
              ""]
    for ln in exced:
        texto.append("Coleta %s · %s · %s → %s · carreg. %s · descarga %s · %s"
                     % (ln["coleta"], ln["frota_cavalo"] or ln["placa_cavalo"] or "—",
                        ln["mercadoria"], ln["destino"], _hm(ln["carga"]["cobrado_s"]),
                        _hm(ln["descarga"]["cobrado_s"]), p.brl(ln["valor"], 2)))
    texto += ["", "A planilha anexa (%s) traz todas as cargas do período." % nome]

    html = p.documento("Horas paradas", blocos,
                       subtitulo="%s · %s a %s" % (cliente, _br(de), _br(ate)),
                       origem="Transportadora Sulista · controle de horas paradas")
    return {"assunto": assunto, "html": html, "texto": "\n".join(texto),
            "anexos": [{"nome": nome, "conteudo": conteudo}], "arquivo": nome,
            "resumo": r, "config_email": cfg["email"], "config": cfg}


def enviar(perfil_id: int, de: str, ate: str, destinatarios, responder_para,
           assunto: str, mensagem: str, autor: str, *, lembrar: bool = False,
           esquema: str | None = None, enviar_=None) -> dict:
    """Monta e envia. Recusa (`cadastro.Recusa`) ANTES de tocar no servidor
    de e-mail; falha do servidor volta em `{"ok": False, "erro": ...}` e fica
    registrada nas duas trilhas."""
    from ..correio import envio

    if not autor:
        raise cadastro.Recusa("Envio sem autor não sai.")
    dests = cadastro.emails_validos(destinatarios, "Destinatário",
                                    cadastro.LIMITE_DESTINATARIOS)
    if not dests:
        raise cadastro.Recusa("Informe ao menos um destinatário.")
    resp = cadastro.emails_validos(responder_para, "Endereço de resposta",
                                   cadastro.LIMITE_RESPOSTA)
    e = montar(perfil_id, de, ate, mensagem, esquema=esquema)
    if not e["resumo"]["cargas"]:
        raise cadastro.Recusa("Nenhuma carga do cliente fechou neste período — "
                              "não há horas paradas para enviar.")
    assunto = " ".join((assunto or "").split())[:200] or e["assunto"]

    # A LINHA NASCE ANTES DO ENVIO. Um processo que cai no meio deixa "sem
    # resposta" à vista, em vez de um envio que ninguém sabe se saiu.
    with pglocal.get_conn(cadastro._esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hp_envio (perfil_id, de, ate, destinatarios, responder_para,
                                     assunto, arquivo, cargas, valor_total, autor)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (int(perfil_id), de, ate, ", ".join(dests), ", ".join(resp), assunto,
             e["arquivo"], e["resumo"]["cargas"], e["resumo"]["valor_total"], autor))
        rid = cur.fetchone()["id"]
        conn.commit()

    res = (enviar_ or envio.enviar)(
        dests, assunto, e["texto"], corpo_html=e["html"], usuario=autor,
        origem="%s:%s:%s:%s" % (ORIGEM, perfil_id, de, ate),
        anexos=e["anexos"], responder_para=resp or None)
    ok = bool(res.get("ok"))
    with pglocal.get_conn(cadastro._esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("UPDATE hp_envio SET ok = %s, erro = %s WHERE id = %s",
                    (ok, (res.get("erro") or "")[:500], rid))
        conn.commit()

    # LEMBRAR só depois de o e-mail ter SAÍDO: lista que falhou não vira padrão.
    if ok and lembrar:
        cfg = dict(e["config"])
        cfg["email"] = dict(cfg["email"], destinatarios=dests)
        cadastro.salvar_config(perfil_id, cfg, autor, esquema=esquema)
    return {"ok": ok, "erro": res.get("erro") or "", "id": rid, "destinatarios": dests,
            "responder_para": resp, "assunto": assunto, "arquivo": e["arquivo"]}


def _linha_envio(r: dict) -> dict:
    r = dict(r)
    r["em"] = r["em"].isoformat()
    r["de"], r["ate"] = r["de"].isoformat(), r["ate"].isoformat()
    r["valor_total"] = float(r["valor_total"])
    return r


def envios(perfil_id: int, limite: int = 10, esquema: str | None = None) -> list[dict]:
    with pglocal.get_conn(cadastro._esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hp_envio WHERE perfil_id = %s ORDER BY em DESC, id DESC"
                    " LIMIT %s", (int(perfil_id), int(limite)))
        return [_linha_envio(r) for r in cur.fetchall()]


def ultimo_envio(esquema: str | None = None) -> dict | None:
    """O envio mais recente de qualquer cliente — para a Saúde."""
    with pglocal.get_conn(cadastro._esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hp_envio ORDER BY em DESC, id DESC LIMIT 1")
        r = cur.fetchone()
    return _linha_envio(r) if r else None
