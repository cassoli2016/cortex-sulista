# -*- coding: utf-8 -*-
"""O FECHAMENTO do ciclo: a fotografia que vira folha.

MÊS PAGO NÃO SE RECALCULA. É a regra que a premiação antiga já segue, e o
motivo é que as quatro fontes continuam se mexendo depois do pagamento: a
Gobrax reprocessa um mês, o ERP registra uma ocorrência com três semanas de
atraso, alguém arruma o de-para de um código novo, a régua muda. Qualquer um
desses movimentos mudaria, EM SILÊNCIO, um valor que já saiu na folha — e a
pessoa que conferisse o ciclo um mês depois veria outro número sem que nada
tivesse acontecido.

Por isso, depois de fechado, a tela mostra a FOTO (`prm_fechamento_linha`) e
não o cálculo. A foto guarda as notas dos três pilares, o valor base, de onde o
base veio e o percentual — porque a pergunta que aparece seis meses depois não
é "quanto ele recebeu", é "por que ele recebeu isto".

REABRIR É POSSÍVEL E FICA REGISTRADO. Regra sem escape vira regra contornada
por fora: alguém pagaria por planilha, e o sistema deixaria de ser a fonte.
Reabrir exige motivo, o motivo fica em `prm_fechamento_evento`, e fechar de
novo escreve uma foto nova por cima — com um terceiro evento.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from api import pglocal

from . import ciclo as ciclo_mod, identidade, premio

log = logging.getLogger("cortex.premiacao.fechamento")

ESQUEMA: str | None = None


def _esq():
    return ESQUEMA


class CicloFechado(ValueError):
    """Tentativa de fechar o que já está fechado — recusa legível, não 5xx."""


class CicloEmCurso(ValueError):
    """Tentativa de fechar um ciclo que ainda não terminou."""


def situacao(ciclo: str) -> dict | None:
    """A linha de fechamento deste ciclo, ou None se nunca foi fechado."""
    try:
        r = pglocal.um(
            "SELECT ciclo, situacao, total, motoristas, sem_nota, nota,"
            " fechado_em, fechado_por FROM prm_fechamento WHERE ciclo = %s",
            (ciclo,), esquema=_esq())
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: fechamento indisponivel (%s)", type(exc).__name__)
        return None
    if not r:
        return None
    d = dict(r)
    d["total"] = float(d["total"])
    d["fechado"] = d["situacao"] == "fechado"
    return d


def eventos(ciclo: str) -> list[dict]:
    """O histórico: quem fechou, quem reabriu e por quê."""
    try:
        return [{"acao": r["acao"], "motivo": r["motivo"], "autor": r["autor"],
                 "criado_em": r["criado_em"],
                 "total": float(r["total"]) if r["total"] is not None else None}
                for r in pglocal.query(
                    "SELECT acao, motivo, autor, criado_em, total"
                    " FROM prm_fechamento_evento WHERE ciclo = %s ORDER BY id",
                    (ciclo,), esquema=_esq())]
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: eventos indisponiveis (%s)", type(exc).__name__)
        return []


def ler(ciclo: str) -> dict:
    """A fotografia guardada — sem tocar em nenhuma fonte externa."""
    est = situacao(ciclo)
    linhas = [dict(r) for r in pglocal.query(
        "SELECT motorista, nome, grupo AS tipo, filial, gobrax, conduta, gr,"
        " nota, status, categoria, base, base_origem, pct, valor, motivo"
        " FROM prm_fechamento_linha WHERE ciclo = %s", (ciclo,), esquema=_esq())]
    for x in linhas:
        for k in ("gobrax", "conduta", "gr", "nota", "base", "pct", "valor"):
            if x[k] is not None:
                x[k] = float(x[k])
        x["base_rotulo"] = premio.ORIGENS.get(x["base_origem"] or "", "")
    linhas.sort(key=lambda x: (x["valor"] is None, -(x["valor"] or 0), x["nome"]))
    return {
        "ciclo": ciclo, "rotulo": ciclo_mod.rotulo(ciclo),
        "fechado": bool(est and est["fechado"]),
        "fechamento": est, "eventos": eventos(ciclo),
        "linhas": linhas, "kpis": premio._kpis(linhas),
        # A FOTO NÃO TEM TARJA DE FONTE, e isso é de propósito: ela não
        # consultou fonte nenhuma. Dizer "Gobrax indisponível" numa foto de
        # três meses atrás seria falar do hoje sobre um número do passado.
        "fonte": "fotografia do fechamento",
    }


def pagamento(ciclo: str | None = None, dir_snapshots=None,
              ranking_pronto: dict | None = None) -> dict:
    """O que a tela mostra: a FOTO se o ciclo está fechado, o cálculo se não.

    Esta função existe para que a escolha não fique espalhada por cada rota.
    Ciclo fechado que voltasse a calcular é o defeito inteiro que o fechamento
    evita — e é um defeito de UMA LINHA esquecida.

    `ranking_pronto` serve a quem já montou o ciclo (o app do motorista lê a
    linha dele de um ciclo que acabou de montar): sem ele, mostrar nota e
    prêmio na mesma tela custaria DUAS leituras das quatro fontes.
    """
    alvo = ciclo or ciclo_mod.atual()
    if not ciclo_mod.valido(alvo):
        raise ValueError(f"Ciclo inválido: {alvo!r}. Use 'AAAA-MM'.")
    est = situacao(alvo)
    if est and est["fechado"]:
        return ler(alvo)
    saida = premio.montar(alvo, dir_snapshots=dir_snapshots,
                          ranking_pronto=ranking_pronto)
    saida["fechado"] = False
    saida["fechamento"] = est
    saida["eventos"] = eventos(alvo)
    saida["fonte"] = "cálculo"
    return saida


def fechar(ciclo: str, autor: str, nota: str = "", forcar: bool = False,
           hoje: date | None = None, dir_snapshots=None) -> dict:
    """Congela o ciclo: grava a foto de cada motorista e marca como fechado.

    RECUSA CICLO EM CURSO. Fechar no dia 10 congelaria cinco dias de
    ocorrências que ainda vão chegar, e o valor sairia menor do que o devido
    sem que ninguém percebesse — o erro caro aqui é o que produz um número
    plausível. `forcar=True` existe porque regra sem escape vira regra
    contornada por fora (o adiantamento de um fechamento antes de feriado é
    caso real), e o motivo fica gravado no evento.
    """
    if not ciclo_mod.valido(ciclo):
        raise ValueError(f"Ciclo inválido: {ciclo!r}. Use 'AAAA-MM'.")
    if not autor:
        raise ValueError("Informe quem está fechando (trilha de auditoria).")
    est = situacao(ciclo)
    if est and est["fechado"]:
        raise CicloFechado(
            f"O ciclo {ciclo_mod.rotulo(ciclo)} já foi fechado por"
            f" {est['fechado_por']} em {est['fechado_em'][:10]}."
            " Reabra antes de fechar de novo.")
    _, fim = ciclo_mod.limites(ciclo)          # `fim` é EXCLUSIVO: o dia 16
    dia = hoje or date.today()
    if dia < date.fromisoformat(fim):
        if not forcar:
            # O último dia do ciclo é o 15, e é ele que a mensagem diz: falar do
            # limite exclusivo mandaria quem lê conferir um dia que não é dele.
            ultimo = date.fromordinal(date.fromisoformat(fim).toordinal() - 1)
            raise CicloEmCurso(
                f"O ciclo {ciclo_mod.rotulo(ciclo)} só termina em"
                f" {ultimo.strftime('%d/%m')} — ainda há"
                " ocorrência e viagem por chegar. Para fechar assim mesmo,"
                " confirme dizendo o motivo.")
        if not str(nota or "").strip():
            raise ValueError(
                "Fechar um ciclo em curso exige o motivo, que fica registrado.")

    dados = premio.montar(ciclo, dir_snapshots=dir_snapshots)
    cpf_de = {m["cadastro_codigo"]: m["cpf"] for m in identidade.listar()}
    agora = datetime.now().isoformat(timespec="seconds")
    pglocal.executar("DELETE FROM prm_fechamento_linha WHERE ciclo = %s",
                     (ciclo,), esquema=_esq())
    total = 0.0
    for x in dados["linhas"]:
        cpf = cpf_de.get(x["motorista"])
        if not cpf:
            # Sem CPF não há chave — e a linha não pode sumir em silêncio.
            log.warning("premiacao: fechamento sem cpf para o cadastro %s",
                        x["motorista"])
            continue
        total += x["valor"] or 0
        pglocal.executar(
            "INSERT INTO prm_fechamento_linha(ciclo, cpf, motorista, nome,"
            " grupo, filial, gobrax, conduta, gr, nota, status, categoria,"
            " base, base_origem, pct, valor, motivo)"
            " VALUES(%(ciclo)s,%(cpf)s,%(motorista)s,%(nome)s,%(grupo)s,"
            "%(filial)s,%(gobrax)s,%(conduta)s,%(gr)s,%(nota)s,%(status)s,"
            "%(categoria)s,%(base)s,%(base_origem)s,%(pct)s,%(valor)s,%(motivo)s)",
            {"ciclo": ciclo, "cpf": cpf, "motorista": x["motorista"],
             "nome": x["nome"], "grupo": x["tipo"], "filial": x["filial"],
             "gobrax": x.get("gobrax"), "conduta": x.get("conduta"),
             "gr": x.get("gr"), "nota": x["nota"], "status": x["status"],
             "categoria": x["categoria"], "base": x["base"],
             "base_origem": x["base_origem"], "pct": x["pct"],
             "valor": x["valor"], "motivo": x["motivo"]},
            esquema=_esq())
    kpis = dados["kpis"]
    pglocal.executar(
        "INSERT INTO prm_fechamento(ciclo, situacao, total, motoristas,"
        " sem_nota, nota, fechado_em, fechado_por)"
        " VALUES(%s,'fechado',%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (ciclo) DO UPDATE SET situacao = 'fechado',"
        " total = EXCLUDED.total, motoristas = EXCLUDED.motoristas,"
        " sem_nota = EXCLUDED.sem_nota, nota = EXCLUDED.nota,"
        " fechado_em = EXCLUDED.fechado_em, fechado_por = EXCLUDED.fechado_por",
        (ciclo, round(total, 2), kpis["motoristas"], kpis["sem_nota"],
         str(nota or ""), agora, autor), esquema=_esq())
    pglocal.executar(
        "INSERT INTO prm_fechamento_evento(ciclo, acao, motivo, total, autor,"
        " criado_em) VALUES(%s,'fechou',%s,%s,%s,%s)",
        (ciclo, str(nota or ""), round(total, 2), autor, agora), esquema=_esq())
    return {"ciclo": ciclo, "fechado": True, "total": round(total, 2),
            "motoristas": kpis["motoristas"], "sem_nota": kpis["sem_nota"],
            "autor": autor, "em": agora}


def reabrir(ciclo: str, autor: str, motivo: str) -> dict:
    """Destrava o ciclo para recálculo. Exige motivo, e o motivo fica.

    A FOTO NÃO É APAGADA: ela continua sendo o que foi pago até alguém fechar
    de novo. Apagar na reabertura deixaria uma janela em que ninguém consegue
    dizer quanto a folha levou.
    """
    if not str(motivo or "").strip():
        raise ValueError("Informe o motivo da reabertura, que fica registrado.")
    if not autor:
        raise ValueError("Informe quem está reabrindo (trilha de auditoria).")
    est = situacao(ciclo)
    if not est:
        raise ValueError(f"O ciclo {ciclo} nunca foi fechado.")
    agora = datetime.now().isoformat(timespec="seconds")
    pglocal.executar("UPDATE prm_fechamento SET situacao = 'reaberto'"
                     " WHERE ciclo = %s", (ciclo,), esquema=_esq())
    pglocal.executar(
        "INSERT INTO prm_fechamento_evento(ciclo, acao, motivo, total, autor,"
        " criado_em) VALUES(%s,'reabriu',%s,%s,%s,%s)",
        (ciclo, motivo.strip(), est["total"], autor, agora), esquema=_esq())
    return {"ciclo": ciclo, "fechado": False, "autor": autor, "em": agora}
