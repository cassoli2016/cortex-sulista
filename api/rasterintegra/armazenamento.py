# -*- coding: utf-8 -*-
"""Gravação do RasterIntegra no banco local do CÓRTEX (Fase 2).

As mesmas três decisões da Smartec valem aqui:

1. **Converter no limite do módulo** — a data DH da Raster
   (``2026-08-29T12:33:02.000-03:00``) vira ``datetime`` aqui; ``S``/``N``
   vira booleano aqui. Nada de tipo do fornecedor atravessa para a leitura.
2. **``ON CONFLICT DO UPDATE``, sempre** — recoletar é o caso normal: a
   janela de coleta cobre 8 dias e a mesma viagem chega várias vezes.
3. **Contador OMITIDO é zero do fornecedor, mas fica NULL no banco** —
   medido: viagem finalizada com ``ParadasAreaRisco=3`` veio SEM o campo
   ``BotaoPanico``. Guardar o que veio preserva a procedência; quem trata
   NULL como 0 é a leitura, dizendo isso no ⓘ.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from .. import pglocal

log = logging.getLogger(__name__)

# O teste redireciona isto para um schema próprio (fixture `esquema_pg`).
ESQUEMA: str | None = None


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


# ───────────────────────────────────────────────────────── conversores
def dh(valor) -> datetime | None:
    """DH da Raster: ISO com milissegundos e fuso. fromisoformat resolve."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor).strip())
    except ValueError:
        return None


def sn(valor) -> bool | None:
    """S/N/I do fornecedor. 'I' (ignorado pela apólice) é None, não False."""
    if valor in (None, "", "I"):
        return None
    return str(valor).strip().upper() == "S"


def num(valor) -> float | None:
    if valor in (None, ""):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def inteiro(valor) -> int | None:
    n = num(valor)
    return int(n) if n is not None else None


def placa_norm(valor) -> str:
    """A Raster escreve 'AAA-1111'; o ERP, 'AAA1111'. Uma grafia só."""
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def rota_txt(valor) -> str | None:
    """Rota chega como OBJETO {CodRota, Descricao} (medido ao vivo — o manual
    não avisa). A descrição é o que a tela mostra."""
    if isinstance(valor, dict):
        valor = valor.get("Descricao") or valor.get("descricao") or ""
    s = str(valor or "").strip()
    return s or None


def viagem_linha(v: dict) -> dict:
    """Uma viagem do getEventoFimViagem → linha de gr_viagem_fim."""
    ce = v.get("ColetasEntregas") or []
    return {
        "cod_solicitacao": inteiro(v.get("CodSolicitacao")),
        "cod_filial": inteiro(v.get("CodFilial")),
        "placa": placa_norm(v.get("PlacaVeiculo")),
        "vinc_veiculo": (v.get("VincVeiculo") or None),
        "placa_carreta1": placa_norm(v.get("PlacaCarreta1")) or None,
        "cpf_motorista": (str(v.get("CPFMotorista1") or "").strip() or None),
        "vinc_motorista": (v.get("VincMotorista1") or None),
        "cnpj_cliente_orig": (str(v.get("CNPJClienteOrig") or "").strip() or None),
        "cnpj_cliente_dest": (str(v.get("CNPJClienteDest") or "").strip() or None),
        "cnpj_proprietario": (str(v.get("CNPJProprietario") or "").strip() or None),
        "rota": rota_txt(v.get("Rota")),
        "prev_ini": dh(v.get("DataHoraPrevIni")),
        "prev_fim": dh(v.get("DataHoraPrevFim")),
        "real_ini": dh(v.get("DataHoraRealIni")),
        "real_fim": dh(v.get("DataHoraRealFim")),
        "status": (v.get("StatusViagem") or "?"),
        "dentro_prazo": sn(v.get("DentroPrazo")),
        "perc_atraso": num(v.get("PercentualAtraso")),
        "vel_media": num(v.get("VelocidadeMedia")),
        "maior_vel": num(v.get("MaiorVelocidade")),
        "local_maior_vel": (str(v.get("LocalMaiorVelocidade") or "").strip() or None),
        "lat_maior_vel": num(v.get("LatitudeMaiorVelocidade")),
        "lon_maior_vel": num(v.get("LongitudeMaiorVelocidade")),
        "tempo_total_min": inteiro(v.get("TempoTotalViagem")),
        "tempo_parado_min": inteiro(v.get("TempoParado")),
        "tempo_mov_min": inteiro(v.get("TempoMovimentando")),
        "perc_mov": num(v.get("PercentualMovimentando")),
        "parado_area_risco_min": inteiro(v.get("TempoParadoAreaRisco")),
        "parado_alvos_min": inteiro(v.get("TempoParadoAlvos")),
        "perc_pernoite": num(v.get("PercentualPernoite")),
        "menor_pernoite_min": inteiro(v.get("MenorPernoite")),
        "botao_panico": inteiro(v.get("BotaoPanico")),
        "eventos_velocidade": inteiro(v.get("EventosVelocidade")),
        "paradas_area_risco": inteiro(v.get("ParadasAreaRisco")),
        "desvios_rota": inteiro(v.get("DesviosDeRota")),
        "sem_posicao": inteiro(v.get("SemPosicao")),
        "rodou_fora_horario": sn(v.get("RodouForaHorario")),
        "violacao_painel": inteiro(v.get("ViolacaoPainel")),
        "violacao_antena": inteiro(v.get("ViolacaoAntena")),
        "desengate": inteiro(v.get("Desengate")),
        "coletas_entregas": len(ce),
        "coletas_no_prazo": sum(1 for c in ce if (c or {}).get("DentroPrazo") == "S"),
        "link_timeline": (str(v.get("LinkTimeLine") or "").strip() or None),
    }


_COLS = tuple(viagem_linha({"CodSolicitacao": 0, "StatusViagem": "?"}).keys())

_UPSERT_VIAGEM = (
    "INSERT INTO gr_viagem_fim (" + ", ".join(_COLS) + ") VALUES ("
    + ", ".join(f"%({c})s" for c in _COLS) + ") "
    "ON CONFLICT (cod_solicitacao) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS if c != "cod_solicitacao")
    + ", atualizado_em = now()"
)


def upsert_viagens(viagens: list[dict], esquema: str | None = None) -> int:
    """Grava viagens FINALIZADAS. Devolve quantas linhas entraram/atualizaram."""
    linhas = [viagem_linha(v) for v in viagens]
    linhas = [ln for ln in linhas
              if ln["cod_solicitacao"] and ln["placa"] and ln["status"] == "F"]
    if not linhas:
        return 0
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        for ln in linhas:
            cur.execute(_UPSERT_VIAGEM, ln)
        conn.commit()
    return len(linhas)


def upsert_km(dia: date, itens: list[dict], esquema: str | None = None) -> int:
    linhas = []
    for it in itens:
        placa = placa_norm(it.get("Placa"))
        if not placa:
            continue
        linhas.append({
            "dia": dia, "placa": placa,
            "motorista": (str(it.get("Motorista") or "").strip() or None),
            "cpf": (str(it.get("CPF") or "").strip() or None),
            "vinculo": (str(it.get("VinculoVeiculo") or "").strip() or None),
            "km_com_viagem": num(it.get("KMComViagem")),
            "km_sem_viagem": num(it.get("KMSemViagem")),
        })
    if not linhas:
        return 0
    sql = """INSERT INTO gr_km_dia (dia, placa, motorista, cpf, vinculo,
                                    km_com_viagem, km_sem_viagem)
             VALUES (%(dia)s, %(placa)s, %(motorista)s, %(cpf)s, %(vinculo)s,
                     %(km_com_viagem)s, %(km_sem_viagem)s)
             ON CONFLICT (dia, placa) DO UPDATE SET
               motorista = EXCLUDED.motorista, cpf = EXCLUDED.cpf,
               vinculo = EXCLUDED.vinculo,
               km_com_viagem = EXCLUDED.km_com_viagem,
               km_sem_viagem = EXCLUDED.km_sem_viagem,
               coletado_em = now()"""
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        for ln in linhas:
            cur.execute(sql, ln)
        conn.commit()
    return len(linhas)


def registrar_carga(tipo: str, iniciado_em: datetime, janela: str,
                    consultas: int, gravadas: int, erro: str | None = None,
                    esquema: str | None = None) -> None:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO gr_carga (tipo, iniciado_em, terminado_em, janela,
                                     consultas, gravadas, erro)
               VALUES (%s, %s, now(), %s, %s, %s, %s)""",
            (tipo, iniciado_em, janela, consultas, gravadas, erro))
        conn.commit()
