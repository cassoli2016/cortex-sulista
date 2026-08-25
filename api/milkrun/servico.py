"""Monta a visão da operação de milk run a partir do ERP + rastro.

MODELO DE DADOS (decifrado no ERP, não documentado em lugar nenhum):

- `coleta` é a solicitação de carga. `coleta.dtcoletar` é a JANELA COMBINADA
  com o fornecedor — preenchida em 99,8% das 8.817 coletas dos últimos 90
  dias, e com hora útil em 98,7% delas.
- `coleta_endereco.tipo = 1` é o REMETENTE, isto é, o ponto onde o caminhão
  vai carregar (2.569 de 2.569 conferem com `coleta.remetente`). Os tipos 2,
  3 e 7 são destinatário; 5 e 6 repetem o remetente.
- `coleta.veiculo` traz a placa alocada — 609 de 640 coletas da MWM nos
  últimos 30 dias.

`dtrealizado` NÃO serve como hora de chegada: na coleta 55643 ele marca
21/08 21:32 para uma coleta prevista em 25/08 16:00, quatro dias ANTES. É
carimbo de processamento da solicitação, não de chegada no fornecedor. Essa é
justamente a lacuna que a detecção por rastro preenche.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from api import db
from api.queries import cached
from api.milkrun import deteccao as det

# Janela de rastro em volta do dia. Coleta marcada para 23:00 costuma ser
# atendida na madrugada seguinte, e o caminhão sai da base horas antes: cortar
# no dia civil perderia a chegada nos dois extremos.
FOLGA_ANTES_H = 8
FOLGA_DEPOIS_H = 14

COLETAS_SQL = """
SELECT co.numero, co.dtcoletar, co.dtrealizado, co.dtemissao,
       co.veiculo, co.motorista,
       coalesce(nullif(trim(mo.nomefantasia),''), nullif(trim(mo.razaosocial),''),
                '') AS motorista_nome,
       ce.cnpjcpfcodigo AS ponto_cnpj,
       coalesce(nullif(trim(ce.razaosocial),''), '(sem nome)') AS ponto_nome,
       ce.cidade AS ponto_cidade, ce.uf AS ponto_uf,
       ce.latitude::float8  AS ponto_lat,
       ce.longitude::float8 AS ponto_lng,
       coalesce(nullif(trim(cd.nomefantasia),''), nullif(trim(cd.razaosocial),''),
                '(sem cadastro)') AS destino_nome,
       co.cnpjcpfcodigotomadorservico AS tomador
FROM coleta co
JOIN coleta_endereco ce
  ON ce.grupo=co.grupo AND ce.empresa=co.empresa AND ce.filial=co.filial
 AND ce.numero=co.numero AND ce.tipo = 1
LEFT JOIN cadastro cd ON cd.codigo = co.destinatario
LEFT JOIN cadastro mo ON mo.codigo = co.motorista
WHERE co.dtcancelamento IS NULL
  AND co.dtcoletar >= %(de)s::timestamp
  AND co.dtcoletar <  %(ate)s::timestamp
  AND co.cnpjcpfcodigotomadorservico LIKE %(tomador)s
ORDER BY co.dtcoletar, co.numero
"""

# Rastro dos veiculos do dia. `latituderastreadora` e nao `latitude`: e a
# posicao que a rastreadora reporta, que e a que a Torre ja usa.
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


def _janela(dia: date) -> tuple[datetime, datetime]:
    ini = datetime.combine(dia, time.min) - timedelta(hours=FOLGA_ANTES_H)
    fim = datetime.combine(dia, time.max) + timedelta(hours=FOLGA_DEPOIS_H)
    return ini, fim


@cached(ttl=60)
def get_milkrun(dia: str | None = None, tomador: str = "02162259") -> dict:
    """Operação do dia: cada ponto com combinado × detectado.

    `tomador` é o prefixo do CNPJ (raiz), não o CNPJ inteiro: a MWM tem quatro
    filiais cadastradas e a coleta pode ser tomada por qualquer uma delas.
    """
    d = date.fromisoformat(dia) if dia else date.today()
    ini, fim = _janela(d)

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(COLETAS_SQL, {
            "de": datetime.combine(d, time.min).isoformat(),
            "ate": (datetime.combine(d, time.min) + timedelta(days=1)).isoformat(),
            "tomador": tomador + "%"})
        coletas = cur.fetchall()

        placas = sorted({c["veiculo"] for c in coletas
                         if (c["veiculo"] or "").strip()})
        rastro: dict[str, list] = {}
        if placas:
            cur.execute(RASTRO_SQL, {"placas": placas,
                                     "de": ini.isoformat(), "ate": fim.isoformat()})
            for p in cur.fetchall():
                rastro.setdefault(p["veiculo"], []).append(dict(p))

        cur.execute("SELECT current_timestamp AS ts")
        agora = cur.fetchone()["ts"]

    pontos = []
    for c in coletas:
        placa = (c["veiculo"] or "").strip()
        lat, lng = c["ponto_lat"], c["ponto_lng"]
        visita = None
        visitas = []
        # Raio por ponto ainda nao e cadastravel: fica o padrao. Medido no
        # rastro real, 300 m erra em patio grande (em Resende o caminhao para
        # a 861 m do ponto cadastrado), por isso a tela mostra a distancia
        # minima que o veiculo chegou — e o que permite calibrar.
        if placa and lat and lng and rastro.get(placa):
            visitas = det.detectar(rastro[placa], lat, lng)
            visita = det.visita_da_janela(visitas, c["dtcoletar"])
        estado = det.classificar(visita, c["dtcoletar"])

        pontos.append({
            "coleta": c["numero"],
            "previsto": c["dtcoletar"].isoformat() if c["dtcoletar"] else None,
            "placa": placa or None,
            "motorista": (c["motorista_nome"] or "").strip() or None,
            "ponto": c["ponto_nome"],
            "cidade": c["ponto_cidade"], "uf": c["ponto_uf"],
            "lat": lat, "lng": lng,
            "destino": c["destino_nome"],
            "chegada": visita.chegada.isoformat() if visita else None,
            "saida": (visita.saida.isoformat()
                      if visita and visita.saida else None),
            "permanencia_min": visita.minutos if visita else None,
            "distancia_m": visita.distancia_min_m if visita else None,
            "parou": visita.parou if visita else None,
            "visitas_no_dia": len(visitas),
            # o que o ERP registra hoje, para a tela poder mostrar o tamanho
            # do erro do apontamento manual
            "registrado_erp": (c["dtrealizado"].isoformat()
                               if c["dtrealizado"] else None),
            **estado,
        })

    total = len(pontos)
    concl = sum(1 for p in pontos if p["estado"] == "concluido")
    no_local = sum(1 for p in pontos if p["estado"] == "no_local")
    atrasados = sum(1 for p in pontos if p.get("pontualidade") == "atrasado")
    sem_placa = sum(1 for p in pontos if not p["placa"])
    sem_coord = sum(1 for p in pontos if not (p["lat"] and p["lng"]))

    return {
        "dia": d.isoformat(),
        "tomador": tomador,
        "pontos": pontos,
        "kpis": {
            "pontos": total,
            "concluidos": concl,
            "no_local": no_local,
            "aguardando": total - concl - no_local,
            "atrasados": atrasados,
            # lacunas de CADASTRO, nao de operacao: sem placa ou sem
            # coordenada a deteccao nao tem como funcionar, e some-las ao
            # "aguardando" faria parecer atraso do motorista
            "sem_placa": sem_placa,
            "sem_coordenada": sem_coord,
            "veiculos": len({p["placa"] for p in pontos if p["placa"]}),
        },
        "atualizado_em": agora.isoformat(),
        "fonte": ("ERP AVA · coleta + coleta_endereco (tipo 1 = remetente) "
                  "cruzado com veiculo_posicao · chegada e saida DETECTADAS "
                  "pelo rastro, nao digitadas"),
    }
