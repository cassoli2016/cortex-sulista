"""Monta o controle de um cliente num período: ERP + ajustes + regra dele."""
from __future__ import annotations

import re
from datetime import date, datetime

from .. import freetime as _ft
from . import cadastro, fonte, planilha, regras


class PerfilNaoExiste(LookupError):
    pass


def _dt(v) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace(" ", "T"))


def _fmt(v) -> str | None:
    return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else None


def contrato_da_carga(contrato: list[dict], carga: dict, dia: date) -> list[dict]:
    """As cláusulas VIGENTES NA DATA DA CARGA, as da filial dela primeiro.

    Vigência na data da carga, e não hoje: a semana passada se cobra com o
    contrato da semana passada. Filial: o contrato é cadastrado por filial, e
    quando a da coleta tem cláusula, é ela que vale; quando não tem, vale o
    resto do contrato do cliente (o relatório do ERP nem olha a filial).
    """
    vig = [ln for ln in contrato if _ft.vigente(ln, dia)]
    mesma = [ln for ln in vig if ln.get("filial") == carga.get("filial")]
    return mesma or vig


def pedido_partes(pedido: str) -> tuple[str, str]:
    """O pedido do cliente e o complemento que vem colado nele.

    O ERP guarda no MESMO campo a ordem de frete do cliente e, em parte das
    cargas, um segundo código grudado ("6100000123ABC0000456"). O primeiro é
    o número; o segundo é o primeiro código letra-e-dígito que vier depois.
    Palavra solta (um nome de operação) não é código e fica de fora.
    """
    p = (pedido or "").strip()
    m = re.match(r"^(\d+)\s*(.*)$", p)
    if not m:
        return p, ""
    comp = re.search(r"[A-Z]{2,}\d+", m.group(2).upper())
    return m.group(1), (comp.group(0) if comp else "")


def _perna_payload(p: dict, erp: dict, nome: str, ajs: dict) -> dict:
    out = {k: p[k] for k in ("inicio_de", "modo", "freetime_h", "valor_h",
                             "clausula", "clausula_mercadoria", "regra",
                             "tempo_s", "excedente_s", "cobrado_s", "valor", "estado")}
    for k in ("janela", "chegada", "saida", "inicio"):
        out[k] = _fmt(p[k])
    # O LADO DO ERP de cada horário que foi ajustado: a tela mostra os dois.
    out["erp"] = {k: _fmt(erp.get(nome + "_" + k))
                  for k in ("janela", "chegada", "saida") if (nome + "_" + k) in ajs}
    return out


def montar(perfil_id: int, de: str, ate: str, esquema: str | None = None) -> dict:
    p = cadastro.perfil(perfil_id, esquema=esquema)
    if not p:
        raise PerfilNaoExiste(perfil_id)
    cfg = p["config"]
    d_de, d_ate = date.fromisoformat(de), date.fromisoformat(ate)
    if d_ate < d_de:
        raise cadastro.Recusa("O fim do período vem antes do começo.")
    if (d_ate - d_de).days > 92:
        raise cadastro.Recusa("Período de até 92 dias — a planilha é por semana ou mês.")

    base = fonte.cargas(p["cliente_codigo"], de, ate)
    ajs_todos = cadastro.ajustes_de([fonte.chave(c) for c in base["cargas"]],
                                    esquema=esquema)
    marco_campo = cadastro.RECORTES[cfg["recorte"]]

    linhas, abertas = [], []
    for c in base["cargas"]:
        ch = fonte.chave(c)
        ajs = ajs_todos.get(ch, {})
        efet = dict(c)
        for campo in cadastro.CAMPOS_HORA:
            if campo in ajs:
                efet[campo] = _dt(ajs[campo]["valor"])
        marco = efet.get(marco_campo)
        if marco is None:
            # AINDA NÃO CHEGOU AO MARCO: a carga é do período, mas a conta não
            # fechou. Aparece à parte, e não soma — somar pela metade seria
            # cobrar duas vezes quando ela fechar.
            ref = efet.get("carga_chegada") or efet.get("carga_janela")
            if ref and d_de <= ref.date() <= d_ate:
                # Os SEIS horários vão junto: é daqui que o ajuste manual
                # fecha a carga que o ERP deixou sem fim de descarga.
                abertas.append({"chave": ch, "coleta": c["numero"], "filial": c["filial"],
                                "mercadoria": c["mercadoria"], "destino": c["destino"],
                                "placa_cavalo": c["placa_cavalo"],
                                "frota_cavalo": c["frota_cavalo"],
                                **{k: _fmt(efet.get(k)) for k in cadastro.CAMPOS_HORA},
                                "erp": {k: _fmt(c.get(k)) for k in cadastro.CAMPOS_HORA
                                        if k in ajs},
                                "ajustes": sorted(ajs.values(), key=lambda a: a["campo"])})
            continue
        if not d_de <= marco.date() <= d_ate:
            continue
        dia = (efet.get("carga_janela") or efet.get("carga_chegada") or c["emissao"]).date()
        contrato = contrato_da_carga(base["contrato"], c, dia)
        conta = regras.calcular(efet, contrato, cfg)
        conta_erp = regras.calcular(c, contrato, cfg) if ajs else conta
        num, comp = pedido_partes(c["pedido"])
        avisos = []
        if c["repeticoes"] > 1:
            avisos.append("mais de um apontamento do mesmo evento — vale o primeiro")
        if c["paradas"] > 1:
            avisos.append("coleta com %d paradas — a conta usa a primeira" % c["paradas"])
        linhas.append({
            "chave": ch, "coleta": c["numero"], "filial": c["filial"],
            "pedido": c["pedido"], "pedido_num": num, "pedido_comp": comp,
            "referencia": (ajs.get("referencia") or {}).get("valor") or comp,
            "mercadoria": c["mercadoria"], "origem": c["origem"], "destino": c["destino"],
            "destinatario_codigo": c["destinatario_codigo"],
            "cidade_origem": c["cidade_origem"], "cidade_destino": c["cidade_destino"],
            "frota_cavalo": c["frota_cavalo"], "placa_cavalo": c["placa_cavalo"],
            "frota_carreta": c["frota_carreta"], "placa_carreta": c["placa_carreta"],
            "ctes": c["ctes"] or "",
            "marco": _fmt(marco),
            "carga": _perna_payload(conta["carga"], c, "carga", ajs),
            "descarga": _perna_payload(conta["descarga"], c, "descarga", ajs),
            "valor": conta["valor"], "valor_erp": conta_erp["valor"],
            "incluida": (ajs.get("incluir") or {}).get("valor") != "nao",
            "ajustes": sorted(ajs.values(), key=lambda a: a["campo"]),
            "avisos": avisos,
        })
    linhas.sort(key=lambda x: (x["carga"]["janela"] or x["carga"]["chegada"] or "",
                               x["filial"], x["coleta"]))
    return {
        "perfil": {"id": p["id"], "cliente_codigo": p["cliente_codigo"],
                   "cliente_nome": p["cliente_nome"], "config": cfg},
        "periodo": {"de": de, "ate": ate, "semana": d_de.isocalendar()[1],
                    "recorte": cfg["recorte"]},
        "resumo": resumo(linhas, abertas),
        "linhas": linhas,
        "abertas": abertas,
        "contrato": [{**ln, "dtinicio": _fmt_d(ln.get("dtinicio")),
                      "dtfim": _fmt_d(ln.get("dtfim")),
                      "vigente": _ft.vigente(ln)} for ln in base["contrato"]],
        "lido_em": base["lido_em"],
        "fonte": ("ERP AVA · Monitoramento SAC (coleta_ocorrencia 394–397, janelas "
                  "da coleta) + sulista.sac_freetimecliente (vigente na data da carga) "
                  "· regra do perfil e ajustes manuais no banco do CÓRTEX"),
    }


def _fmt_d(v):
    if v is None:
        return None
    return (v.date() if hasattr(v, "date") else v).isoformat()


def resumo(linhas: list[dict], abertas: list[dict]) -> dict:
    """Os números do topo. Total nunca gravado: sai das linhas, sempre."""
    inc = [ln for ln in linhas if ln["incluida"]]

    def soma(chave, perna=None):
        return sum(((ln[perna] if perna else ln)[chave] or 0) for ln in inc)
    horarios = [ln for ln in linhas
                if any(a["campo"] in cadastro.CAMPOS_HORA for a in ln["ajustes"])]
    return {
        "cargas": len(inc),
        "com_excedente": sum(1 for ln in inc if ln["valor"] > 0),
        "valor_carga": round(soma("valor", "carga"), 2),
        "valor_descarga": round(soma("valor", "descarga"), 2),
        "valor_total": round(soma("valor"), 2),
        "horas_carga": round(soma("cobrado_s", "carga") / 3600, 2),
        "horas_descarga": round(soma("cobrado_s", "descarga") / 3600, 2),
        # O QUE FOI MEXIDO À MÃO APARECE, com o efeito em reais: número que
        # pode ser mudado sem aparecer não é número, é opinião.
        "ajustadas": len(horarios),
        "efeito_ajustes": round(sum(ln["valor"] - ln["valor_erp"] for ln in inc), 2),
        "excluidas": len(linhas) - len(inc),
        "sem_contrato": sum(1 for ln in inc for p in ("carga", "descarga")
                            if ln[p]["estado"] == regras.SEM_CONTRATO),
        "sem_apontamento": sum(1 for ln in inc
                               if regras.SEM_APONTAMENTO in (ln["carga"]["estado"],
                                                             ln["descarga"]["estado"])),
        "em_aberto": len(abertas),
    }


def exportar(perfil_id: int, de: str, ate: str, esquema: str | None = None) -> tuple[str, bytes]:
    """(nome do arquivo, bytes do .xlsx) — das MESMAS linhas que a tela mostra."""
    d = montar(perfil_id, de, ate, esquema=esquema)
    cfg = d["perfil"]["config"]
    ctx = {"cliente": d["perfil"]["cliente_nome"],
           "semana": d["periodo"]["semana"],
           "de": date.fromisoformat(de).strftime("%d-%m-%Y"),
           "ate": date.fromisoformat(ate).strftime("%d-%m-%Y")}
    nome = planilha.nome_do_arquivo(cfg.get("arquivo"), ctx)
    return nome, planilha.gerar(d["linhas"], cfg["colunas"], cfg.get("aba"))
