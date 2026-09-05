# -*- coding: utf-8 -*-
"""O detalhe de uma carga, para a página pública.

DUAS DECISÕES QUE VALEM MAIS QUE O RESTO DO ARQUIVO

1. **Cada abertura reprova o segundo fator.** O detalhe não recebe um
   identificador que fala por si: ele recebe o documento e os quatro dígitos do
   CNPJ de novo, refaz a busca e só então enriquece a carga que casar. O
   identificador opaco serve para escolher QUAL das cargas da lista, nunca para
   provar direito a ela. Assim um link encaminhado num grupo de WhatsApp —
   que é para onde esses links vão — não abre nada sozinho.

2. **A posição é DISTÂNCIA e PROGRESSO, nunca coordenada.** Publicar a
   coordenada de um caminhão numa página aberta é ferramenta de roubo de carga.
   "Faltam 180 km, 68% da viagem" responde o que quem espera a carga quer
   saber — e não serve para interceptar ninguém.

   A conta é toda nossa, sem fornecedor externo: o CT-e traz
   `latitudeentrega`/`longitudeentrega` (preenchidas em 16.924 de 16.928 CT-e
   dos últimos 90 dias) e a posição do veículo vem do rastreamento que o ERP já
   recebe. A distância é em LINHA RETA e o texto diz isso — chamar de "faltam
   180 km de estrada" seria inventar precisão que a reta não tem.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from .. import db
from . import consulta

log = logging.getLogger("cortex.rastreio.detalhe")

#: Abaixo disto o veículo é tratado como CHEGADO. Não é chute: é a ordem de
#: grandeza de um pátio grande mais o erro do GPS. Menos que isso faria a carga
#: alternar entre "chegando" e "chegou" a cada posição nova.
RAIO_CHEGADA_KM = 2.0

#: Acima desta razao entre "o que falta" e "a rota inteira", a posicao nao e
#: deste trecho — o veiculo ja esta noutra viagem. 1,2 da folga para o desvio
#: normal de estrada sem deixar passar o caso em que o caminhao esta a 700 km
#: de uma rota de 340.
FORA_DA_ROTA = 1.2

#: Posição mais velha que isto não se apresenta como "agora". O rastreamento
#: falha, o veículo entra em área sem sinal, e um ponto de ontem exibido como
#: atual é pior que nenhum ponto — quem lê decide em cima dele.
IDADE_MAX_MIN = 180

#: A carga em si, com o que o detalhe precisa e a busca não devolve.
DETALHE_SQL = """
SELECT c.grupo, c.empresa, c.filial, c.numero, c.serie,
       c.dtemissao, c.dtprevisaoentrega, c.dtentrega,
       c.dtagendamentoentrega, c.dtiniciodescarga,
       trim(c.veiculo)                       AS placa,
       c.cidadecoleta, c.ufcoleta,
       c.latitudecoleta::float8              AS lat_coleta,
       c.longitudecoleta::float8             AS lng_coleta,
       c.latitudeentrega::float8             AS lat_entrega,
       c.longitudeentrega::float8            AS lng_entrega,
       cd.nomefantasia                       AS destinatario_nome,
       cd.cidade                             AS destinatario_cidade,
       cd.uf                                 AS destinatario_uf
FROM conhecimento c
LEFT JOIN cadastro cd ON cd.codigo = c.destinatario
WHERE c.grupo = %(g)s AND c.empresa = %(e)s AND c.filial = %(f)s
  AND c.numero = %(n)s AND c.serie = %(s)s
  AND c.dtcancelamento IS NULL
"""

#: A posição do veículo. Ela NÃO sai da API pública — entra só na conta da
#: distância. O `MAX` pela data evita o registro velho de um sequencial antigo.
POSICAO_SQL = """
SELECT vp.latituderastreadora::float8  AS lat,
       vp.longituderastreadora::float8 AS lng,
       vp.dt                           AS quando
FROM rastreamento.veiculo_ultimaposicaomacro um
JOIN veiculo_posicao vp ON vp.veiculo = um.veiculo
  AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
WHERE um.veiculo = %(placa)s
  AND vp.latituderastreadora IS NOT NULL
  AND vp.longituderastreadora IS NOT NULL
"""

#: O km da rota, do embarque. Vem da viagem e não de conta nossa: é o número
#: que a operação usa, e inventar outro faria a página discordar do painel.
KM_SQL = """
SELECT max(coalesce(p.kmfretecompra, 0))::float8 AS km
FROM programacaoembarque p
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND (trim(p.veiculo) = %(placa)s OR trim(p.carreta1) = %(placa)s)
  AND p.dtsaida IS NOT NULL AND p.dtchegada IS NULL
"""


def _reta_km(a_lat, a_lng, b_lat, b_lng) -> float | None:
    """Distância em linha reta (haversine), em km.

    RETA, e o texto da tela diz isso. A distância de estrada é sempre maior, e
    apresentar a reta como se fosse rodovia daria uma previsão otimista todo
    dia — o tipo de erro que ninguém confere porque parece preciso.
    """
    try:
        vals = [float(x) for x in (a_lat, a_lng, b_lat, b_lng)]
    except (TypeError, ValueError):
        return None
    if any(v == 0 for v in vals[:2]) or any(v == 0 for v in vals[2:]):
        return None
    la1, lo1, la2, lo2 = (math.radians(v) for v in vals)
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _idade_min(quando) -> int | None:
    """Idade da posição, em minutos.

    O CARIMBO DO ERP VEM INGENUO E EM HORARIO LOCAL. Tratá-lo como UTC soma
    três horas em UTC-3 — e o efeito não é um erro pequeno: com o teto de 180
    minutos, TODA posição nascia com 181 minutos de idade e a página nunca
    mostrava veículo ao vivo. Medido em três cargas seguidas, todas com
    posição de menos de dois minutos, todas lidas como 181.

    Ingênuo compara-se com relógio ingênuo; com fuso, com relógio com fuso.
    """
    if not quando:
        return None
    try:
        if quando.tzinfo:
            delta = datetime.now(timezone.utc) - quando
        else:
            delta = datetime.now() - quando
        return max(0, int(delta.total_seconds() / 60))
    except Exception:  # noqa: BLE001
        return None


def _posicao(placa: str) -> dict | None:
    if not placa:
        return None
    try:
        r = db.query(POSICAO_SQL, {"placa": placa})
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: posição falhou: %s", type(exc).__name__)
        return None
    return dict(r[0]) if r else None


def _km_rota(placa: str) -> float | None:
    if not placa:
        return None
    try:
        r = db.query(KM_SQL, {"placa": placa})
    except Exception:  # noqa: BLE001
        return None
    km = (r[0] or {}).get("km") if r else None
    return float(km) if km else None


def _andamento(linha: dict) -> dict:
    """Onde a carga está, em distância e progresso — nunca em coordenada."""
    fora: dict = {"tem_posicao": False}
    pos = _posicao(linha.get("placa") or "")
    total = _reta_km(linha.get("lat_coleta"), linha.get("lng_coleta"),
                     linha.get("lat_entrega"), linha.get("lng_entrega"))
    if total:
        fora["distancia_total_km"] = round(total, 1)
    km_rota = _km_rota(linha.get("placa") or "")
    if km_rota:
        fora["km_rota"] = round(km_rota, 0)

    if not pos:
        return fora
    idade = _idade_min(pos.get("quando"))
    if idade is None or idade > IDADE_MAX_MIN:
        # POSIÇÃO VELHA NÃO SE APRESENTA COMO AGORA. Ela vira a ressalva.
        fora["posicao_velha_min"] = idade
        return fora

    falta = _reta_km(pos.get("lat"), pos.get("lng"),
                     linha.get("lat_entrega"), linha.get("lng_entrega"))
    if falta is None:
        return fora

    # O VEICULO PODE NAO ESTAR MAIS NESTA CARGA. O CT-e guarda a placa que
    # levou a mercadoria, e o caminhao segue viagem: entrega, engata outra
    # carreta, pega outro frete. Quando a distancia que "falta" e maior que a
    # rota inteira, a posicao lida nao pertence a este trecho.
    #
    # Medido em producao: CT-e 94446, Joinville -> Sorocaba, "faltam 711 km de
    # 342". Prender o progresso entre 0 e 100 transformava isso num 0%
    # plausivel — e 0% e um numero que quem espera a carga LE E ACREDITA. Zero
    # que e ausencia nao e desempenho: aqui ele vira lacuna declarada.
    if total and falta > total * FORA_DA_ROTA:
        fora["fora_da_rota"] = True
        return fora

    fora["tem_posicao"] = True
    fora["atualizado_ha_min"] = idade
    fora["falta_km"] = round(falta, 1)
    fora["chegou"] = falta <= RAIO_CHEGADA_KM
    if total and total > 0:
        pct = 100.0 * (1 - min(1.0, max(0.0, falta / total)))
        fora["progresso_pct"] = int(round(pct))
    return fora


def _linha_do_tempo(linha: dict, andamento: dict) -> list[dict]:
    """A viagem em etapas, para a tela não precisar interpretar datas."""
    etapas = [{"chave": "emitido", "rotulo": "Documento emitido",
               "em": consulta._iso(linha.get("dtemissao")),
               "feito": bool(linha.get("dtemissao"))}]
    etapas.append({"chave": "transito", "rotulo": "Em viagem",
                   "em": None,
                   "feito": bool(linha.get("placa"))})
    if linha.get("dtagendamentoentrega"):
        etapas.append({"chave": "agendado", "rotulo": "Entrega agendada",
                       "em": consulta._iso(linha["dtagendamentoentrega"]),
                       "feito": True})
    etapas.append({"chave": "descarga", "rotulo": "Chegou para descarga",
                   "em": consulta._iso(linha.get("dtiniciodescarga")),
                   "feito": bool(linha.get("dtiniciodescarga"))})
    etapas.append({"chave": "entregue", "rotulo": "Entregue",
                   "em": consulta._iso(linha.get("dtentrega")),
                   "feito": bool(linha.get("dtentrega"))})
    return etapas


def obter(termo: str, cnpj4: str, carga_id: str) -> dict:
    """O detalhe de UMA carga da busca. Nunca levanta.

    Refaz a busca de propósito: é ela que prova o direito à carga. `carga_id`
    só escolhe qual das encontradas — ele nunca prova nada sozinho.
    """
    if len(consulta._so_digitos(termo)) < 3 or             len(consulta._so_digitos(cnpj4)) != 4:
        return {"ok": False, "motivo": "informe o documento e o CNPJ"}

    linhas, motivo = consulta.buscar_cru(termo, cnpj4)
    if motivo:
        return {"ok": False, "motivo": motivo}

    alvo = next((r for r in linhas
                 if consulta.token(r["grupo"], r["empresa"], r["filial"],
                                   r["numero"], r["serie"]) == carga_id), None)
    if not alvo:
        # MESMA RESPOSTA de "não achei": dizer "essa carga existe mas não é
        # deste CNPJ" confirmaria a existência dela para quem chutou.
        return {"ok": True, "carga": None}

    try:
        linhas2 = db.query(DETALHE_SQL, {
            "g": alvo["grupo"], "e": alvo["empresa"], "f": alvo["filial"],
            "n": alvo["numero"], "s": alvo["serie"]})
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: detalhe falhou: %s", type(exc).__name__)
        return {"ok": False, "motivo": "não foi possível consultar agora"}
    if not linhas2:
        return {"ok": True, "carga": None}

    linha = dict(linhas2[0])
    andamento = _andamento(linha)
    return {"ok": True, "carga": {
        # A base é a carga JÁ LIMPA, montada pela mesma lista explícita da
        # busca — o detalhe acrescenta, nunca abre o registro cru.
        **consulta._limpo(alvo),
        "andamento": andamento,
        "etapas": _linha_do_tempo(linha, andamento),
        "consultado_em": datetime.now(timezone.utc).isoformat(),
    }}
