"""Orquestração do módulo orçamentário: deriva, grava e compara.

A parte pura (montar_comparativo) fica separada do acesso a dados para poder ser
testada sem banco.
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime

from api import db
from api.orcamento import armazenamento as arm
from api.orcamento.derivacao import derivar, derivar_semestre, indices_sazonais
from api.orcamento.rollup import contas_sem_linha, mapa_conta_linha
from api.orcamento.sql import (AGRUP_CONTA_SQL, HIST_CONTA_SQL, NOME_CONTA_SQL,
                               REAL_CONTA_SQL, meses_fechados)
from api.queries import DRE_MODELO, ler_ajustes

METODOS_VALIDOS = ("espelho", "semestre")


def montar_comparativo(linhas_orc: list[dict], realizado: dict,
                       mapa_linha: dict, ate_mes: int,
                       meses_excluidos: frozenset[int] | set[int] = frozenset(),
                       nomes: dict[str, str] | None = None) -> dict:
    """Agrega orçado e realizado por linha da DRE até `ate_mes` (inclusive).

    linhas_orc: saída de armazenamento.ler_linhas()
    realizado:  {(conta, mes): valor}
    mapa_linha: {conta: rótulo da linha DRE | None}
    meses_excluidos: meses CIRCULARES (dentro da base de derivação) — ficam fora
        do acumulado de linhas, contas e KPIs, porque neles o desvio seria só o
        fator lido de volta. Continuam no `mensal` (gráfico), marcados.
    nomes: {conta: nome do plano de contas} — a chave grupo|reduzido sozinha só
        diz algo para quem decorou o plano; o nome acompanha grade, maiores
        desvios e pendências.
    """
    nomes = nomes or {}
    por_linha: dict[str, dict] = {}
    por_conta: dict[str, dict] = {}
    mensal: dict[int, dict] = {m: {"mes": m, "orcado": 0.0, "realizado": None,
                                   "fechado": m <= ate_mes,
                                   "circular": m in meses_excluidos}
                               for m in range(1, 13)}
    sem_linha: set[str] = set()
    contas_orc: set[str] = set()

    def _acumula(conta: str, mes: int, rot: str, orc: float,
                 origem: str | None) -> None:
        alvo = por_linha.setdefault(rot, {"linha": rot, "orcado": 0.0, "realizado": 0.0})
        alvo["orcado"] += orc
        alvo["realizado"] += realizado.get((conta, mes), 0.0)
        c = por_conta.setdefault(conta, {"conta": conta, "nome": nomes.get(conta),
                                         "linha": rot,
                                         "orcado": 0.0, "realizado": 0.0,
                                         "origem": origem or "sem_base"})
        c["orcado"] += orc
        c["realizado"] += realizado.get((conta, mes), 0.0)

    for l in linhas_orc:
        conta, mes = l["conta"], l["mes"]
        contas_orc.add(conta)
        orc = l["valor_efetivo"] or 0.0
        mensal[mes]["orcado"] += orc
        if mes <= ate_mes:
            real = realizado.get((conta, mes))
            if real is not None:
                if mensal[mes]["realizado"] is None:
                    mensal[mes]["realizado"] = 0.0
                mensal[mes]["realizado"] += real

        rot = mapa_linha.get(conta)
        if rot is None:
            sem_linha.add(conta)
            continue
        if mes > ate_mes or mes in meses_excluidos:
            continue
        _acumula(conta, mes, rot, orc, l["origem"])

    # conta com realizado no ano mas SEM linha de orçamento (apareceu depois da
    # geração): entra na cascata com orçado 0 — descartá-la abriria divergência
    # entre o realizado daqui e o da DRE Gerencial. Sem agrupador, vira pendência.
    for (conta, mes), _v in realizado.items():
        if conta in contas_orc or mes > ate_mes or mes in meses_excluidos:
            continue
        rot = mapa_linha.get(conta)
        if rot is None:   # reportada pelo laço de pendências, logo abaixo
            continue
        _acumula(conta, mes, rot, 0.0, None)

    # pendência também nasce do realizado: a lista da tela lia só as linhas
    # persistidas, de onde gerar() já removeu as contas sem linha — vinha sempre
    # vazia (revisão final, I2; critério de aceite 6)
    for (conta, _mes) in realizado:
        if mapa_linha.get(conta) is None:
            sem_linha.add(conta)

    def _fecha(d: dict) -> dict:
        d["desvio"] = d["realizado"] - d["orcado"]
        base = abs(d["orcado"])
        d["desvio_pct"] = (100.0 * d["desvio"] / base) if base else None
        # o sinal de desvio já captura o efeito no resultado: custo é lançado
        # negativo, então gastar menos deixa o valor menos negativo (desvio>=0);
        # receita é lançada positiva, então faturar menos dá desvio negativo.
        # Não é preciso olhar QUAL linha é custo ou receita — o sinal do valor
        # já resolve os dois casos.
        d["favoravel"] = d["desvio"] >= 0
        return d

    linhas = [_fecha(v) for v in por_linha.values()]
    contas = [_fecha(v) for v in por_conta.values()]
    ordem = {rot: i for i, (rot, _n, _t, _s) in enumerate(DRE_MODELO)}
    linhas.sort(key=lambda x: ordem.get(x["linha"], 999))
    contas.sort(key=lambda x: abs(x["desvio"]), reverse=True)

    # ORÇAMENTO DO ANO por linha — os 12 meses orçados, independente de ate_mes
    # e dos meses circulares. Sem isto, enquanto não há mês comparável (todo o
    # início do ciclo) a cascata orçado×realizado fica vazia e o usuário não
    # consegue VER o orçamento que acabou de montar em lugar nenhum do
    # Acompanhamento (aconteceu em produção no primeiro uso real).
    ano_por_linha: dict[str, dict] = {}
    for l in linhas_orc:
        rot = mapa_linha.get(l["conta"])
        if rot is None:
            continue
        alvo = ano_por_linha.setdefault(rot, {"linha": rot,
                                              "meses": {m: 0.0 for m in range(1, 13)},
                                              "total": 0.0})
        v = l["valor_efetivo"] or 0.0
        alvo["meses"][l["mes"]] += v
        alvo["total"] += v
    orcado_ano = sorted(ano_por_linha.values(),
                        key=lambda x: ordem.get(x["linha"], 999))

    # A grade da aba Montagem precisa das 12 células de TODA conta da versão,
    # independentemente de ate_mes: com o ano ainda não iniciado (ate_mes=0) uma
    # grade derivada de `contas` viria vazia e não haveria o que ajustar.
    grade: dict[str, dict] = {}
    # origem da CONTA (não da primeira célula): com a mediana só nos meses com
    # movimento, o mês 1 de uma esporádica costuma ser sem_base — ler a célula
    # marcaria "base fraca" errado nos dois sentidos.
    # "semestre" entra entre espelho e mediana (I2 da revisão final): hoje é
    # inofensivo porque derivar_semestre nunca mistura origens dentro de uma
    # mesma conta, mas sem entrada no dict cairia em 0 (força de "sem_base")
    # no dia em que isso deixar de ser verdade.
    _forca = {"mediana": 3, "semestre": 2, "espelho": 1, "sem_base": 0}
    for l in linhas_orc:
        g = grade.setdefault(l["conta"], {
            "conta": l["conta"], "nome": nomes.get(l["conta"]),
            "linha": mapa_linha.get(l["conta"]),
            "origem": l["origem"], "meses_com_dado": l["meses_com_dado"],
            "valores": {}, "ajustados": {}})
        if _forca.get(l["origem"], 0) > _forca.get(g["origem"], 0):
            g["origem"] = l["origem"]
        g["valores"][l["mes"]] = l["valor_efetivo"]
        g["ajustados"][l["mes"]] = l["valor_ajustado"] is not None

    return {
        "linhas": linhas,
        "orcado_ano": orcado_ano,
        "contas": contas,
        "grade": sorted(grade.values(), key=lambda g: (g["linha"] or "~", g["conta"])),
        "mensal": [mensal[m] for m in range(1, 13)],
        "sem_linha": [{"conta": c, "nome": nomes.get(c)} for c in sorted(sem_linha)],
        "ate_mes": ate_mes,
        "meses_circulares": sorted(meses_excluidos),
    }


def meses_faltando(historico: dict[str, dict[str, float]],
                   meses: list[str]) -> list[str]:
    """Meses da base sem nenhum lançamento em conta alguma. Função pura."""
    presentes = {m for serie in historico.values() for m in serie}
    return [m for m in meses if m not in presentes]


def _historico(meses: list[str]) -> dict[str, dict[str, float]]:
    de = f"{meses[0]}-01"
    ate_ano, ate_mes = int(meses[-1][:4]), int(meses[-1][5:7])
    ate_mes += 1
    if ate_mes == 13:
        ate_mes, ate_ano = 1, ate_ano + 1
    ate = f"{ate_ano:04d}-{ate_mes:02d}-01"
    rows = db.query(HIST_CONTA_SQL, {"de": de, "ate": ate})
    hist: dict[str, dict[str, float]] = {}
    for r in rows:
        hist.setdefault(r["conta"], {})[r["mes"]] = r["valor"]
    return hist


def _nomes() -> dict[str, str]:
    """Conta -> nome do plano de contas (planoconta.descricao)."""
    return {r["conta"]: r["nome"] for r in db.query(NOME_CONTA_SQL)}


def _mapa() -> tuple[dict, dict]:
    rows = db.query(AGRUP_CONTA_SQL)
    agrup = {r["conta"]: r["agrupador"] for r in rows}
    return agrup, ler_ajustes()


def _serie_por_linha(hist24: dict[str, dict[str, float]],
                     mapa: dict[str, str | None]) -> dict[str, dict[str, float]]:
    """Agrega o histórico de 24 meses POR LINHA da DRE, somando as contas de
    cada linha mês a mês. Conta sem linha (`mapa.get(conta)` é None ou ausente)
    fica fora — não tem como formar o índice sazonal de uma linha que ela não
    integra."""
    por_linha: dict[str, dict[str, float]] = {}
    for conta, serie in hist24.items():
        rot = mapa.get(conta)
        if rot is None:
            continue
        alvo = por_linha.setdefault(rot, {})
        for mes, valor in serie.items():
            alvo[mes] = alvo.get(mes, 0.0) + valor
    return por_linha


def gerar(ano: int, rotulo: str, fator: float, quem: str,
          path=None, hoje: date | None = None,
          versao_id: int | None = None, metodo: str = "espelho",
          agora: datetime | None = None) -> dict:
    """Deriva o baseline do ano.

    Sem `versao_id`, grava numa versão nova. Com `versao_id`, REGERA aquela
    versão no lugar: só o `valor_baseline` é recalculado, e o `valor_ajustado`
    da controladoria sobrevive (spec §2). Sem esse caminho o `ON CONFLICT` do
    `gravar_baseline` nunca dispararia em produção.

    `metodo`:
    - "espelho" (padrão): mês-calendário da base × fator — caminho original.
    - "semestre": nível dos últimos 6 meses × índice sazonal da LINHA (de 24
      meses de histórico) × fator — para quem confia mais no nível recente do
      que no mês espelho de 12 meses atrás.

    REGERAR ignora o `metodo` recebido: a versão já gravou o método com que
    nasceu, e regerar tem de re-derivar POR ESSE método (rolante, na base
    atual) — senão uma versão trocaria de método sem o usuário pedir.

    Versão aprovada ou arquivada é imutável: regerar exige reabrir antes.
    Regerar uma rascunho arquiva uma CÓPIA fiel do estado atual (baseline +
    ajustes) ANTES de re-derivar — é o snapshot histórico do "antes de
    regerar"; a resposta traz o id dessa cópia em `arquivada_id` (None
    quando é geração de versão nova, sem nada para arquivar).
    """
    path = path or arm.DB_PATH
    hoje = hoje or date.today()
    agora = agora or datetime.now()
    arm.init_db(path)

    arquivada_id: int | None = None
    if versao_id is not None:
        versoes = {v["id"]: v for v in arm.listar_versoes(path)}
        if versao_id not in versoes:
            raise KeyError(f"versão inexistente: {versao_id}")
        versao_atual = versoes[versao_id]
        if versao_atual["status"] != "rascunho":
            raise ValueError(
                "Versão aprovada/arquivada é imutável — reabra antes de regerar.")
        metodo = versao_atual.get("metodo") or "espelho"
        arquivada_id = arm.arquivar_copia(
            path, versao_id,
            f"{versao_atual['rotulo']} (antes de regerar {agora.strftime('%d/%m %H:%M')})")

    agrup, ajustes = _mapa()
    mapa = mapa_conta_linha(agrup, ajustes)

    linhas_flat: list[str] = []
    if metodo == "semestre":
        meses = meses_fechados(hoje, 6)
        hist = _historico(meses)
        if not hist:
            raise ValueError("Sem histórico fechado para derivar o baseline.")
        # mesmo bloqueio do espelho: base semestral incompleta produziria
        # nível errado disfarçado de orçamento
        faltam = meses_faltando(hist, meses)
        if faltam:
            raise ValueError(
                f"A base precisa de {len(meses)} meses fechados e faltam {len(faltam)}: "
                + ", ".join(faltam))
        meses24 = meses_fechados(hoje, 24)
        hist24 = _historico(meses24)
        serie_linha = _serie_por_linha(hist24, mapa)
        indices, linhas_flat = indices_sazonais(serie_linha, meses24)
        linhas = derivar_semestre(hist, meses, indices, mapa, fator)
    else:
        meses = meses_fechados(hoje, 12)
        hist = _historico(meses)
        if not hist:
            raise ValueError("Sem histórico fechado para derivar o baseline.")
        # a spec exige bloquear quando a base não tem os 12 meses fechados: derivar mês
        # espelho sobre uma base incompleta produziria zeros disfarçados de orçamento
        faltam = meses_faltando(hist, meses)
        if faltam:
            raise ValueError(
                f"A base precisa de {len(meses)} meses fechados e faltam {len(faltam)}: "
                + ", ".join(faltam))
        linhas = derivar(hist, meses, fator)

    pendentes = contas_sem_linha(sorted(hist), agrup, ajustes)
    # conta sem agrupador (ou com agrupador que o DRE_MODELO não reconhece) não
    # soma em linha nenhuma: fica fora do baseline e é reportada
    linhas = [l for l in linhas if l["conta"] not in set(pendentes)]

    if versao_id is None:
        vid = arm.criar_versao(path, ano, rotulo, fator, quem,
                               meses_base=meses, metodo=metodo)
        regerada, zeradas = False, 0
    else:
        vid, regerada = versao_id, True
        # metodo regravado (coerência) mesmo sendo o mesmo já lido acima —
        # a atualização também troca a base para a janela ATUAL do método
        arm.atualizar_versao(path, vid, fator, meses_base=meses, metodo=metodo)
    arm.gravar_baseline(path, vid, linhas)
    if regerada:
        zeradas = arm.zerar_fora_do_conjunto(
            path, vid, {(l["conta"], l["mes"]) for l in linhas})
    return {"versao_id": vid, "linhas": len(linhas), "meses_base": meses,
            "contas_sem_linha": pendentes, "regerada": regerada,
            "celulas_zeradas": zeradas,
            "meses_circulares": meses_circulares(ano, meses),
            "metodo": metodo, "linhas_flat": linhas_flat,
            "arquivada_id": arquivada_id}


def meses_circulares(ano: int, meses_base: list[str]) -> list[int]:
    """Meses do ano orçado que estão DENTRO da própria base de derivação.

    Orçar 2026 em julho de 2026 põe jan-jun/26 na base: o espelho desses meses é
    o próprio mês, então o 'orçado' deles é o realizado lido de volta x (1+fator)
    e o desvio no acompanhamento seria só o fator (ex.: -5% vira -5,26% em toda
    linha) — comparação circular, não controle orçamentário. Função pura.
    """
    return [m for m in range(1, 13) if f"{ano:04d}-{m:02d}" in set(meses_base)]


def comparativo(versao_id: int, ate_mes: int | None = None,
                path=None, hoje: date | None = None) -> dict:
    """Orçado x realizado da versão, acumulado até o último mês fechado."""
    path = path or arm.DB_PATH
    hoje = hoje or date.today()
    versoes = {v["id"]: v for v in arm.listar_versoes(path)}
    if versao_id not in versoes:
        raise KeyError(f"versão inexistente: {versao_id}")
    v = versoes[versao_id]
    ano = v["ano"]

    if ate_mes is None:
        ate_mes = (hoje.month - 1) if hoje.year == ano else (12 if hoje.year > ano else 0)
    ate_mes = max(0, min(12, ate_mes))

    linhas_orc = arm.ler_linhas(path, versao_id)
    realizado: dict = {}
    if ate_mes > 0:
        fim_ano, fim_mes = (ano, ate_mes + 1) if ate_mes < 12 else (ano + 1, 1)
        rows = db.query(REAL_CONTA_SQL, {"de": f"{ano}-01-01",
                                         "ate": f"{fim_ano:04d}-{fim_mes:02d}-01"})
        for r in rows:
            realizado[(r["conta"], int(r["mes"][5:7]))] = r["valor"]

    agrup, ajustes = _mapa()
    mapa = mapa_conta_linha(agrup, ajustes)
    # meses do ano orçado que estavam dentro da base de derivação: espelho de si
    # mesmos, ficam fora do acumulado (versões antigas, sem meses_base gravado,
    # não têm como saber — seguem sem exclusão até serem regeradas)
    base_reg = json.loads(v["meses_base"]) if v.get("meses_base") else []
    circulares = frozenset(meses_circulares(ano, base_reg))
    out = montar_comparativo(linhas_orc, realizado, mapa, ate_mes,
                             meses_excluidos=circulares, nomes=_nomes())
    out["versao"] = dict(v)
    out["fonte"] = ("Orçado: data/orcamento.db (baseline derivado + ajustes). "
                    "Realizado: ERP AVA, lancamento x planoconta, mesma base da DRE.")
    return out


def exportar_csv(versao_id: int, path=None, agora: datetime | None = None) -> tuple[str, str]:
    """Exporta a versão inteira como CSV pt-BR: BOM, `;`, decimal vírgula.

    Qualquer status exporta (rascunho/aprovado/arquivada) — não há guarda de
    imutabilidade aqui, só leitura. Nome de conta e linha da DRE dependem do
    ERP AVA (réplica só-leitura, pode estar fora do ar pelo túnel): melhor
    esforço com try/except — o export não pode quebrar por isso, as duas
    colunas só saem vazias.
    """
    path = path or arm.DB_PATH
    agora = agora or datetime.now()
    arm.init_db(path)
    versoes = {v["id"]: v for v in arm.listar_versoes(path)}
    if versao_id not in versoes:
        raise KeyError(f"versão inexistente: {versao_id}")
    v = versoes[versao_id]
    linhas = arm.ler_linhas(path, versao_id)

    try:
        nomes = _nomes()
    except Exception:  # noqa: BLE001 — ERP fora não pode quebrar o export
        nomes = {}
    try:
        agrup, ajustes = _mapa()
        mapa = mapa_conta_linha(agrup, ajustes)
    except Exception:  # noqa: BLE001
        mapa = {}

    def _dec(x: float) -> str:
        return f"{x:.2f}".replace(".", ",")

    def _campo(s) -> str:
        s = "" if s is None else str(s)
        if any(ch in s for ch in (";", '"', "\n", "\r")):
            return '"' + s.replace('"', '""') + '"'
        return s

    def _campo_txt(s) -> str:
        # Excel/LibreOffice leem célula que começa com = + - @ (ou TAB/CR)
        # como fórmula; apóstrofo força leitura como texto. Só se aplica às
        # colunas de TEXTO LIVRE (rótulo, conta, nome, linha_dre, origem,
        # ajustadas) — NUNCA a valores de _dec(): custo é lançado negativo
        # neste ERP e "-1234,50" com apóstrofo viraria texto no Excel (A3 da
        # revisão final).
        s = "" if s is None else str(s)
        if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
            s = "'" + s
        return _campo(s)

    base = json.loads(v["meses_base"]) if v.get("meses_base") else []
    faixa = f"{base[0]} a {base[-1]}" if base else ""
    status_txt = v["status"]
    if v.get("aprovado_por"):
        status_txt = f"{status_txt} (aprovado por {v['aprovado_por']} em {v['aprovado_em']})"

    # 3º item do trio = neutralizar contra fórmula (só campos de texto livre).
    cabecalho = [
        ("rotulo", v["rotulo"], True),
        ("ano", v["ano"], False),
        ("metodo", v.get("metodo") or "espelho", False),
        ("base", faixa, False),
        ("fator", _dec(v["fator_tendencia"]), False),
        ("status", status_txt, False),
        ("criado em", v["criado_em"], False),
        ("criado por", v.get("criado_por") or "", False),
        ("exportado em", agora.strftime("%Y-%m-%d %H:%M"), False),
    ]

    buf = io.StringIO()
    buf.write("﻿")               # BOM UTF-8: Excel pt-BR abre acentuado
    for chave, valor, txt in cabecalho:
        campo_valor = _campo_txt(valor) if txt else _campo(valor)
        buf.write(f"{_campo(chave)};{campo_valor}\n")
    buf.write("\n")
    buf.write("conta;nome;linha_dre;origem;meses_com_dado;"
              "jan;fev;mar;abr;mai;jun;jul;ago;set;out;nov;dez;total;ajustadas\n")

    por_conta: dict[str, dict] = {}
    for l in linhas:
        c = por_conta.setdefault(l["conta"], {
            "origem": l["origem"], "meses_com_dado": l["meses_com_dado"],
            "valores": {}, "ajustadas": []})
        c["valores"][l["mes"]] = l["valor_efetivo"]
        if l["valor_ajustado"] is not None:
            c["ajustadas"].append(l["mes"])

    def _linha_dre(conta: str) -> str:
        return mapa.get(conta) or ""

    for conta in sorted(por_conta, key=lambda cta: (_linha_dre(cta), cta)):
        c = por_conta[conta]
        # linhas sempre têm as 12 células (gravar_baseline grava conta x mes
        # completo); None só apareceria de dado incoerente — vira 0,00 e não
        # quebra a exportação.
        valores = [c["valores"].get(m) or 0.0 for m in range(1, 13)]
        ajustadas_str = ",".join(str(m) for m in sorted(c["ajustadas"]))
        # conta/nome/linha_dre/origem/ajustadas são texto livre (AVA ou
        # derivado) -> _campo_txt; meses_com_dado e os valores de _dec() nunca
        # levam apóstrofo de neutralização (A3 da revisão final).
        linha = [_campo_txt(conta), _campo_txt(nomes.get(conta) or ""),
                 _campo_txt(_linha_dre(conta)), _campo_txt(c["origem"]),
                 _campo(c["meses_com_dado"])]
        linha += [_campo(_dec(x)) for x in valores]
        linha.append(_campo(_dec(sum(valores))))
        linha.append(_campo_txt(ajustadas_str))
        buf.write(";".join(linha) + "\n")

    filename = f"orcamento-{v['ano']}-v{versao_id}.csv"
    return buf.getvalue(), filename
