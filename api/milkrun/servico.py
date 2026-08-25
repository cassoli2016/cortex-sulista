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
- **`hra_chegada` e `hra_saida` são os horários DIGITADOS**, e são campos
  TEXTO. É exatamente o apontamento manual que a detecção veio substituir;
  ficam lado a lado na tela para o tamanho do erro aparecer.
- `coletada = 1` e `frustrada = 1` são os desfechos que a operação registra.

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
       cc.dtagendamentocoleta, cc.hra_chegada, cc.hra_saida,
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

SIT = {2: "pendente", 3: "pendente", 4: "pendente", 6: "em andamento",
       7: "finalizada", 8: "cancelada"}


def _hora(txt) -> datetime | None:
    """`hra_chegada`/`hra_saida` são campos TEXTO no ERP. Na prática vêm como
    'AAAA-MM-DD HH:MM:SS', mas texto aceita qualquer coisa — o que não
    converte vira None em vez de derrubar a tela inteira."""
    if not txt:
        return None
    s = str(txt).strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
              "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _iso(v) -> str | None:
    return v.isoformat() if v else None


@cached(ttl=60)
def get_milkrun(dia: str | None = None, tomador: str = "02162259") -> dict:
    """Operação do dia, agrupada por solicitação de coleta.

    `tomador` é a RAIZ do CNPJ: a MWM tem quatro filiais cadastradas e a
    solicitação pode ser tomada por qualquer uma delas.
    """
    d = date.fromisoformat(dia) if dia else date.today()
    ini_dia = datetime.combine(d, time.min)

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(PONTOS_SQL, {
            "tomador": tomador + "%",
            "de": ini_dia.isoformat(),
            "ate": (ini_dia + timedelta(days=1)).isoformat()})
        linhas = cur.fetchall()

        placas = sorted({(l["veiculo"] or "").strip() for l in linhas
                         if (l["veiculo"] or "").strip()})
        rastro: dict[str, list] = {}
        if placas:
            cur.execute(RASTRO_SQL, {
                "placas": placas,
                "de": (ini_dia - timedelta(hours=FOLGA_ANTES_H)).isoformat(),
                "ate": (ini_dia + timedelta(days=1,
                                            hours=FOLGA_DEPOIS_H)).isoformat()})
            for p in cur.fetchall():
                rastro.setdefault(p["veiculo"], []).append(dict(p))

        cur.execute("SELECT current_timestamp AS ts")
        agora = cur.fetchone()["ts"]

    coletas: dict[int, dict] = {}
    for l in linhas:
        placa = (l["veiculo"] or "").strip()
        lat, lng = l["ponto_lat"], l["ponto_lng"]
        previsto = l["dtagendamentocoleta"] or l["dtcoletar"]

        visita, visitas = None, []
        if placa and lat and lng and rastro.get(placa):
            visitas = det.detectar(rastro[placa], lat, lng)
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

        man_cheg = _hora(l["hra_chegada"])
        man_said = _hora(l["hra_saida"])
        dif_manual = None
        if visita and man_cheg:
            dif_manual = round((man_cheg - visita.chegada).total_seconds() / 60)

        ponto = {
            "coleta": l["coleta"], "sequencia": l["sequencia"],
            "previsto": _iso(previsto),
            "placa": placa or None,
            "ponto": l["ponto_nome"], "cidade": l["ponto_cidade"],
            "uf": l["ponto_uf"], "lat": lat, "lng": lng,
            "destino": l["destino_nome"] or None,
            "chegada": _iso(visita.chegada) if visita else None,
            "saida": _iso(visita.saida) if visita and visita.saida else None,
            "permanencia_min": visita.minutos if visita else None,
            "distancia_m": visita.distancia_min_m if visita else None,
            "visitas_no_dia": len(visitas),
            "manual_chegada": _iso(man_cheg),
            "manual_saida": _iso(man_said),
            "dif_manual_min": dif_manual,
            "coletada": coletada, "frustrada": frustrada,
            **estado,
        }

        c = coletas.setdefault(l["coleta"], {
            "coleta": l["coleta"],
            "situacao": SIT.get(l["situacao"], f"situação {l['situacao']}"),
            "cancelada": l["dtcancelamento"] is not None,
            "placa": placa or None,
            "motorista": (l["motorista_nome"] or "").strip() or None,
            "pontos": [],
        })
        c["pontos"].append(ponto)

    grupos = sorted(coletas.values(),
                    key=lambda c: (c["pontos"][0]["previsto"] or "", c["coleta"]))
    for g in grupos:
        p = g["pontos"]
        g["total"] = len(p)
        g["concluidos"] = sum(1 for x in p if x["estado"] == "concluido")
        g["frustrados"] = sum(1 for x in p if x["estado"] == "frustrada")
        g["pendentes"] = sum(1 for x in p if x["estado"] == "aguardando")
        g["no_local"] = sum(1 for x in p if x["estado"] == "no_local")
        g["primeiro"] = p[0]["previsto"]
        g["ultimo"] = p[-1]["previsto"]

    todos = [x for g in grupos for x in g["pontos"]]
    difs = sorted(abs(x["dif_manual_min"]) for x in todos
                  if x["dif_manual_min"] is not None)

    return {
        "dia": d.isoformat(),
        "tomador": tomador,
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
            "dif_manual_mediana": difs[len(difs) // 2] if difs else None,
            "dif_manual_n": len(difs),
        },
        "atualizado_em": agora.isoformat(),
        "fonte": ("ERP AVA · coleta + coleta_cliente (cada linha é um PONTO do "
                  "roteiro) cruzado com veiculo_posicao · chegada e saída "
                  "DETECTADAS pelo rastro; hra_chegada/hra_saida são o "
                  "apontamento manual, mostrado ao lado para comparação"),
    }
