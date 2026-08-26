"""Monta a visão da operação de milk run a partir do ERP + rastro.

MODELO DE DADOS (decifrado no ERP, não documentado em lugar nenhum):

- `coleta` é a SOLICITAÇÃO. `coleta.situacao`: 2 = pendente, 6 = em
  andamento, 7 = finalizada, 8 = cancelada.
- **`coleta_cliente` é o PONTO** — a parada do roteiro. Uma solicitação tem de
  1 a 4 pontos: a coleta 55621 tem quatro, agendados para 10:00, 13:00, 15:00
  e 17:00. É por isso que a tela agrupa por coleta — a solicitação é o
  roteiro, e cada linha dela é uma parada.
- `coleta_cliente.dtagendamentocoleta` é a JANELA DAQUELE PONTO, preenchida
  em 1.267 de 1.269 linhas da MWM nos últimos 60 dias. É mais precisa que
  `coleta.dtcoletar`, que vale para a solicitação inteira.
- `hra_chegada` e `hra_saida` são os horários DIGITADOS. NÃO são lidos: a tela
  mostra só o que o rastreamento produz. Coleta sem detecção fica com
  travessão — é assim que a falta de calibragem aparece, em vez de ficar
  escondida atrás de uma hora que alguém digitou.
- `coletada = 1` e `frustrada = 1` são os desfechos que a operação registra.

MILK RUN × COLETA SIMPLES. A mesma tabela guarda as duas coisas: 87 das 234
solicitações da MWM em agosto têm UMA parada só — é frete ponto a ponto, não
roteiro de coleta. O critério é o número de paradas da solicitação (> 1 = milk
run), e ele é medido ANTES dos filtros da tela: um milk run de quatro paradas
filtrado por um fornecedor mostra uma parada só, e classificar depois do filtro
o rebaixaria a "coleta simples" — a tela mudaria a natureza da operação
conforme quem está olhando.

`coleta.dtrealizado` NÃO serve como hora de chegada: na coleta 55643 marca
21/08 21:32 para uma coleta prevista em 25/08 16:00 — quatro dias ANTES. É
carimbo de processamento da solicitação.

A coordenada do ponto vem de `cadastro` pelo CNPJ do remetente: é o cadastro
do fornecedor (87% preenchido), não o endereço copiado na solicitação.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from api import db
from api.milkrun import deteccao as det
from api.queries import cached

# Janela de rastro em volta do dia. Coleta agendada para 23:00 é atendida na
# madrugada seguinte, e o caminhão sai da base horas antes: cortar no dia civil
# perderia a chegada nos dois extremos.
FOLGA_ANTES_H = 8
FOLGA_DEPOIS_H = 14

PONTOS_SQL = """
SELECT co.numero AS coleta, cc.sequencia,
       co.situacao, co.dtcoletar, co.veiculo, co.dtcancelamento,
       cc.dtagendamentocoleta,
       -- hra_chegada/hra_saida (o apontamento DIGITADO) sairam de proposito:
       -- a tela mostra so o que o rastreamento produz. Coleta sem deteccao
       -- fica com travessao, e e assim que a falta de calibragem aparece em
       -- vez de ficar escondida atras de uma hora digitada.
       cc.coletada, cc.frustrada, cc.remetente,
       coalesce(nullif(trim(cr.nomefantasia),''), nullif(trim(cr.razaosocial),''),
                '(sem cadastro)') AS ponto_nome,
       cr.cidade AS ponto_cidade, cr.uf AS ponto_uf,
       cr.latitude::float8  AS ponto_lat,
       cr.longitude::float8 AS ponto_lng,
       coalesce(nullif(trim(cd.nomefantasia),''), nullif(trim(cd.razaosocial),''),
                '') AS destino_nome,
       coalesce(nullif(trim(mo.nomefantasia),''), nullif(trim(mo.razaosocial),''),
                '') AS motorista_nome
FROM coleta co
JOIN coleta_cliente cc
  ON cc.grupo=co.grupo AND cc.empresa=co.empresa AND cc.filial=co.filial
 AND cc.numero=co.numero
LEFT JOIN cadastro cr ON cr.codigo = cc.remetente
LEFT JOIN cadastro cd ON cd.codigo = cc.destinatario
LEFT JOIN cadastro mo ON mo.codigo = co.motorista
WHERE co.cnpjcpfcodigotomadorservico LIKE %(tomador)s
  AND coalesce(cc.dtagendamentocoleta, co.dtcoletar) >= %(de)s::timestamp
  AND coalesce(cc.dtagendamentocoleta, co.dtcoletar) <  %(ate)s::timestamp
ORDER BY co.numero, cc.sequencia
"""

RASTRO_SQL = """
SELECT veiculo, dt,
       latituderastreadora::float8  AS lat,
       longituderastreadora::float8 AS lng,
       velocidade::float8 AS velocidade
FROM veiculo_posicao
WHERE veiculo = ANY(%(placas)s)
  AND dt >= %(de)s::timestamp AND dt <= %(ate)s::timestamp
ORDER BY veiculo, dt
"""

# Onde cada veiculo esta AGORA. `veiculo_ultimaposicaomacro` guarda o
# ponteiro para a ultima posicao de cada placa, entao isto nao varre o
# historico — e a mesma fonte que a Torre usa, para as duas telas nunca
# discordarem sobre onde o caminhao esta.
POS_ATUAL_SQL = """
SELECT um.veiculo AS placa,
       vp.latituderastreadora::float8  AS lat,
       vp.longituderastreadora::float8 AS lng,
       to_char(vp.dt,'YYYY-MM-DD HH24:MI') AS posicao_em,
       greatest(vp.velocidade,0)::int AS velocidade,
       (vp.dt >= current_timestamp - interval '2 hours') AS recente
FROM rastreamento.veiculo_ultimaposicaomacro um
JOIN veiculo_posicao vp ON vp.veiculo = um.veiculo
 AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
WHERE um.veiculo = ANY(%(placas)s)
  AND vp.latituderastreadora IS NOT NULL
  AND vp.longituderastreadora IS NOT NULL
"""

SIT = {2: "pendente", 3: "pendente", 4: "pendente", 6: "em andamento",
       7: "finalizada", 8: "cancelada"}


def _iso(v) -> str | None:
    return v.isoformat() if v else None


def _venceu(ponto: dict, agora: datetime) -> bool:
    """A parada JA DEVERIA ter acontecido. Sem horario agendado nao da para
    dizer que venceu — e a mesma razao pela qual `classificar` devolve "sem
    janela" em vez de inventar atraso."""
    prev = ponto.get("previsto")
    return bool(prev) and prev < agora.isoformat()


def _pct(concluidos: int, frustrados: int, vencidas: int) -> float | None:
    """Realizadas sobre o que JA TINHA DE ESTAR RESOLVIDO.

    Denominador = coletadas + frustradas + pendentes cujo horario ja passou.
    As duas pontas importam: parada das 15h fora do denominador as 11h (senao
    a manha parece um desastre), e parada das 9h que ninguem fez DENTRO dele
    (senao ela some do indice em vez de pesar). Sem a segunda metade, 21/08
    marcava 100% com 6 coletas perdidas.
    """
    den = concluidos + frustrados + vencidas
    return round(100 * concluidos / den, 1) if den else None


def _mediana(vals: list) -> float | None:
    """Mediana e nao media: uma parada de 8 horas num ponto com fila puxaria a
    media e diria que a operacao inteira e lenta."""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    return round(v[len(v) // 2], 1)


@cached(ttl=60)
def get_milkrun(de: str | None = None, ate: str | None = None,
                tomador: str = "02162259", situacao: str = "",
                fornecedor: str = "", placa: str = "",
                tipo: str = "milk") -> dict:
    """Operação do período, agrupada por DATA e, dentro dela, por solicitação.

    `tomador` é a RAIZ do CNPJ: a MWM tem quatro filiais cadastradas e a
    solicitação pode ser tomada por qualquer uma delas.

    `tipo`: 'milk' (só solicitações com mais de uma parada, o padrão da tela),
    'simples' (só as de parada única) ou '' para as duas.

    Os filtros de situação, fornecedor e placa são aplicados ANTES de somar
    os indicadores — KPI que não segue o filtro da tela mente sobre o recorte
    que a pessoa está olhando.
    """
    hoje = date.today()
    d_de = date.fromisoformat(de) if de else hoje
    d_ate = date.fromisoformat(ate) if ate else d_de
    if d_ate < d_de:
        d_de, d_ate = d_ate, d_de
    ini_dia = datetime.combine(d_de, time.min)
    fim_dia = datetime.combine(d_ate, time.min) + timedelta(days=1)

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(PONTOS_SQL, {
            "tomador": tomador + "%",
            "de": ini_dia.isoformat(),
            "ate": fim_dia.isoformat()})
        linhas = cur.fetchall()

        placas = sorted({(l["veiculo"] or "").strip() for l in linhas
                         if (l["veiculo"] or "").strip()})
        rastro: dict[str, list] = {}
        if placas:
            cur.execute(RASTRO_SQL, {
                "placas": placas,
                "de": (ini_dia - timedelta(hours=FOLGA_ANTES_H)).isoformat(),
                "ate": (fim_dia + timedelta(hours=FOLGA_DEPOIS_H)).isoformat()})
            for p in cur.fetchall():
                rastro.setdefault(p["veiculo"], []).append(dict(p))
            # filtra e ordena UMA vez por placa: `detectar` roda uma vez por
            # PONTO e antes refazia isso a cada chamada (40 s numa semana)
            for _pl, _ps in rastro.items():
                rastro[_pl] = det.preparar(_ps)

        # POSICAO ATUAL de cada placa do periodo, para o mapa mostrar onde o
        # caminhao esta agora e nao so onde as paradas ficam. Consulta separada
        # de proposito: o rastro do periodo pode ter dias, e a ultima posicao
        # tem de ser a de AGORA, inclusive quando o periodo filtrado ja passou.
        posicoes: dict[str, dict] = {}
        if placas:
            cur.execute(POS_ATUAL_SQL, {"placas": placas})
            for p in cur.fetchall():
                posicoes[p["placa"]] = dict(p)

        cur.execute("SELECT current_timestamp AS ts")
        agora = cur.fetchone()["ts"]

    coletas: dict[int, dict] = {}
    for l in linhas:
        # `placa_l` e nao `placa`: o parametro de filtro se chama `placa`, e
        # reaproveitar o nome aqui o sobrescrevia com o veiculo da ultima
        # linha — a tela passava a filtrar sozinha por uma placa que ninguem
        # pediu, e 17 solicitacoes viravam 2 sem erro nenhum.
        placa_l = (l["veiculo"] or "").strip()
        lat, lng = l["ponto_lat"], l["ponto_lng"]
        previsto = l["dtagendamentocoleta"] or l["dtcoletar"]

        visita, visitas = None, []
        if placa_l and lat and lng and rastro.get(placa_l):
            visitas = det.detectar(rastro[placa_l], lat, lng, preparadas=True)
            visita = det.visita_da_janela(visitas, previsto)
        estado = det.classificar(visita, previsto)

        # O DESFECHO registrado pela operação manda sobre o detectado.
        # "Frustrada" é informação que o rastro não tem: o caminhão esteve lá e
        # voltou vazio, e o rastreamento veria isso como visita normal.
        frustrada = l["frustrada"] == 1
        coletada = l["coletada"] == 1
        if frustrada:
            estado = {**estado, "estado": "frustrada", "rotulo": "frustrada"}
        elif coletada and estado["estado"] == "aguardando":
            # a operação apontou coleta e o rastro não viu: quase sempre é
            # coordenada errada ou raio pequeno. Deixar como "aguardando"
            # esconderia uma coleta que aconteceu.
            estado = {**estado, "estado": "concluido",
                      "rotulo": "coletado (sem rastro)"}


        ponto = {
            "coleta": l["coleta"], "sequencia": l["sequencia"],
            "previsto": _iso(previsto),
            "placa": placa_l or None,
            "ponto": l["ponto_nome"], "cidade": l["ponto_cidade"],
            "uf": l["ponto_uf"], "lat": lat, "lng": lng,
            "destino": l["destino_nome"] or None,
            "chegada": _iso(visita.chegada) if visita else None,
            "saida": _iso(visita.saida) if visita and visita.saida else None,
            "permanencia_min": visita.minutos if visita else None,
            "distancia_m": visita.distancia_min_m if visita else None,
            "visitas_no_dia": len(visitas),
            "coletada": coletada, "frustrada": frustrada,
            **estado,
        }

        c = coletas.setdefault(l["coleta"], {
            "coleta": l["coleta"],
            "situacao": SIT.get(l["situacao"], f"situação {l['situacao']}"),
            "cancelada": l["dtcancelamento"] is not None,
            "placa": placa_l or None,
            "motorista": (l["motorista_nome"] or "").strip() or None,
            "pontos": [],
        })
        c["pontos"].append(ponto)

    # ---- FILTROS. Aplicados aqui, antes de qualquer soma: indicador que
    # ignora o filtro da tela diz respeito a outro recorte que o da tabela.
    alvo_sit = (situacao or "").strip()
    alvo_forn = (fornecedor or "").strip().lower()
    alvo_placa = (placa or "").strip().upper()

    def _passa(x) -> bool:
        if alvo_sit and x["estado"] != alvo_sit:
            return False
        if alvo_forn and alvo_forn not in (x["ponto"] or "").lower():
            return False
        if alvo_placa and alvo_placa not in (x["placa"] or ""):
            return False
        return True

    alvo_tipo = (tipo or "").strip().lower()

    grupos, fora_tipo = [], {"milk": 0, "simples": 0}
    for c in coletas.values():
        # NATUREZA DA SOLICITACAO — medida sobre as paradas ORIGINAIS. Depois
        # do filtro de fornecedor um roteiro de quatro paradas aparece com uma
        # so, e classificar aqui embaixo o chamaria de coleta simples: a tela
        # mudaria o que a operacao E conforme o filtro de quem olha.
        paradas_total = len(c["pontos"])
        e_milk = paradas_total > 1
        if alvo_tipo == "milk" and not e_milk:
            fora_tipo["simples"] += 1
            continue
        if alvo_tipo == "simples" and e_milk:
            fora_tipo["milk"] += 1
            continue

        pts = [x for x in c["pontos"] if _passa(x)]
        if not pts:
            continue
        c = {**c, "pontos": pts}
        c["paradas_total"] = paradas_total
        c["milkrun"] = e_milk
        # Roteiro cujas paradas sao TODAS o mesmo endereco: pela contagem e
        # milk run, na pratica sao varias cargas no mesmo lugar. Sao 4 em 147
        # e tres delas na propria planta da MWM. Fica marcado em vez de
        # reclassificado — a regra e do usuario, o aviso e meu.
        c["mesmo_local"] = e_milk and len({x["ponto"] for x in c["pontos"]}) == 1
        c["total"] = len(pts)
        c["concluidos"] = sum(1 for x in pts if x["estado"] == "concluido")
        c["frustrados"] = sum(1 for x in pts if x["estado"] == "frustrada")
        c["pendentes"] = sum(1 for x in pts if x["estado"] == "aguardando")
        c["no_local"] = sum(1 for x in pts if x["estado"] == "no_local")
        c["primeiro"] = pts[0]["previsto"]
        c["ultimo"] = pts[-1]["previsto"]
        c["data"] = (pts[0]["previsto"] or "")[:10]
        grupos.append(c)
    grupos.sort(key=lambda c: (c["primeiro"] or "", c["coleta"]))

    todos = [x for g in grupos for x in g["pontos"]]

    # ---- POR DATA. O usuario le a operacao por dia, entao o dia e o nivel de
    # cima: quantas solicitacoes, quantas paradas e quanto ja foi realizado.
    dias: dict[str, dict] = {}
    for g in grupos:
        dia_g = dias.setdefault(g["data"], {
            "data": g["data"], "solicitacoes": 0, "pontos": 0,
            "concluidos": 0, "frustrados": 0, "pendentes": 0, "no_local": 0,
            "vencidas": 0, "coletas": []})
        dia_g["solicitacoes"] += 1
        dia_g["pontos"] += g["total"]
        dia_g["concluidos"] += g["concluidos"]
        dia_g["frustrados"] += g["frustrados"]
        dia_g["pendentes"] += g["pendentes"]
        dia_g["no_local"] += g["no_local"]
        # pendentes que ja passaram da hora — entram no denominador
        dia_g["vencidas"] += sum(1 for x in g["pontos"]
                                 if x["estado"] == "aguardando"
                                 and _venceu(x, agora))
        dia_g["coletas"].append(g)
    for x in dias.values():
        x["pct_realizado"] = _pct(x["concluidos"], x["frustrados"],
                                  x["vencidas"])
        x["pct_do_total"] = (round(100 * x["concluidos"] / x["pontos"], 1)
                             if x["pontos"] else None)
        # AINDA POR VIR: pendente cujo horario nao chegou. Enquanto houver
        # uma, o dia esta EM ANDAMENTO e um 100% ali significa "100% do que
        # venceu ate agora", nao "dia concluido" — a tela tem de dizer isso,
        # senao um dia 27% cumprido aparece verde e completo.
        x["a_vencer"] = x["pendentes"] - x["vencidas"]
        x["em_andamento"] = x["a_vencer"] > 0
    por_data = sorted(dias.values(), key=lambda x: x["data"])

    concl_tot = sum(1 for x in todos if x["estado"] == "concluido")
    frustr_tot = sum(1 for x in todos if x["estado"] == "frustrada")
    venc_tot = sum(1 for x in todos if x["estado"] == "aguardando"
                   and _venceu(x, agora))
    aventar_tot = sum(1 for x in todos if x["estado"] == "aguardando") - venc_tot

    return {
        "de": d_de.isoformat(), "ate": d_ate.isoformat(),
        "dia": d_de.isoformat(),           # compatibilidade
        "tomador": tomador,
        "filtros": {"situacao": alvo_sit, "fornecedor": fornecedor,
                    "placa": placa, "tipo": alvo_tipo},
        # onde cada veiculo do recorte esta agora
        "veiculos_pos": posicoes,
        "por_data": por_data,
        "coletas": grupos,
        "kpis": {
            "solicitacoes": len(grupos),
            "pontos": len(todos),
            "concluidos": sum(1 for x in todos if x["estado"] == "concluido"),
            "no_local": sum(1 for x in todos if x["estado"] == "no_local"),
            "pendentes": sum(1 for x in todos if x["estado"] == "aguardando"),
            "frustrados": sum(1 for x in todos if x["estado"] == "frustrada"),
            "atrasados": sum(1 for x in todos
                             if x.get("pontualidade") == "atrasado"),
            # lacunas de CADASTRO, não de operação: sem placa ou sem coordenada
            # a detecção não tem o que rastrear, e somar isso a "pendente"
            # faria parecer atraso do motorista
            "sem_placa": sum(1 for x in todos if not x["placa"]),
            "sem_coordenada": sum(1 for x in todos
                                  if not (x["lat"] and x["lng"])),
            "veiculos": len({x["placa"] for x in todos if x["placa"]}),
            # coletas em que o rastreamento nao achou a chegada: e a lista
            # de calibragem de raio/coordenada, e o unico numero que substitui
            # o antigo "manual x rastro" com utilidade
            "sem_rastro": sum(1 for x in todos if not x["chegada"]),
            "dias": len(por_data),
            # realizado sobre o que JA TINHA DE ESTAR RESOLVIDO: feitas,
            # frustradas e as pendentes que passaram da hora. Parada que ainda
            # nao venceu fica fora; parada vencida e nao feita PESA.
            "pct_realizado": _pct(concl_tot, frustr_tot, venc_tot),
            "vencidas": venc_tot,
            "a_vencer": aventar_tot,
            "permanencia_mediana": _mediana(
                [x["permanencia_min"] for x in todos
                 if x["permanencia_min"] is not None]),
            "fornecedores": len({x["ponto"] for x in todos if x["ponto"]}),
            # o que o filtro de tipo deixou de fora — sem isto o total da tela
            # some sem explicacao quando alguem troca o recorte
            "fora_simples": fora_tipo["simples"],
            "fora_milk": fora_tipo["milk"],
            "paradas_por_solicitacao": (round(len(todos) / len(grupos), 1)
                                        if grupos else None),
            "mesmo_local": sum(1 for g in grupos if g.get("mesmo_local")),
            "veiculos_ao_vivo": sum(1 for v in posicoes.values()
                                    if v.get("recente")),
        },
        "atualizado_em": agora.isoformat(),
        "fonte": ("ERP AVA · coleta + coleta_cliente (cada linha é um PONTO do "
                  "roteiro) cruzado com veiculo_posicao · chegada e saída "
                  "DETECTADAS pelo rastro; hra_chegada/hra_saida são o "
                  "apontamento manual, mostrado ao lado para comparação"),
    }
