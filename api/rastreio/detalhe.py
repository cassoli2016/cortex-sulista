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
import time
from datetime import datetime, timezone

from .. import db
from . import consulta, rota

log = logging.getLogger("cortex.rastreio.detalhe")

#: Quanto o veiculo pode se afastar da rota cadastrada e ainda estar nela.
#: A poligonal tem, em metade das rotas, dois pontos para trezentos km — entao
#: a folga precisa ser generosa, ou toda viagem viraria "fora da rota".
FORA_DA_ROTA_KM = 60

#: O raio do circulo que o mapa desenha, em km, e o passo do arredondamento
#: da coordenada. Os dois andam JUNTOS de proposito: o circulo tem de ser do
#: tamanho da incerteza real, senao ele mente — desenhar 2 km em cima de uma
#: coordenada arredondada a 11 km promete uma precisao que o numero nao tem.
#:
#: Comecou em 12 km e caiu para 5 depois de ver no mapa: 12 km cobria metade
#: do ABC e o circulo virava o assunto da tela, escondendo a rota.
#:
#: O QUE MUDA NA SEGURANCA, dito com honestidade: pouco, e por um motivo que
#: so ficou claro com a tela pronta — a ROTA e desenhada. Um circulo sobre uma
#: rota visivel ja indica o trecho, seja ele de 5 ou de 12 km. O que protege
#: de verdade continua sendo nao publicar a coordenada, e e isso que o
#: arredondamento faz.
AREA_RAIO_KM = 5
AREA_PASSO_GRAU = 0.05          # ~5,5 km, do tamanho do circulo


def _arredondar(v: float) -> float:
    """Coordenada na grade do circulo. `round(v, 1)` dava 11 km; o passo agora
    acompanha o raio desenhado."""
    return round(round(float(v) / AREA_PASSO_GRAU) * AREA_PASSO_GRAU, 4)

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
#:
#: OS TRES JOINS DE `cadastro` NAO MULTIPLICAM A LINHA, e isso foi conferido no
#: banco vivo antes de entrar (regra da casa: join novo se confere dos dois
#: lados). `cadastro` tem 8.343 linhas para 8.343 `codigo` distintos, e a
#: consulta com os quatro joins nao dobra nenhum dos CT-e dos ultimos 30 dias.
#: `cadastro.codigo` E o CNPJ/CPF — nao ha id sequencial nesta base.
DETALHE_SQL = """
SELECT c.grupo, c.empresa, c.filial, c.numero, c.serie,
       c.dtemissao, c.dtprevisaoentrega, c.dtentrega,
       c.dtagendamentoentrega, c.dtiniciodescarga,
       trim(c.veiculo)                       AS placa,
       trim(c.carreta1)                      AS carreta,
       c.cidadecoleta, c.ufcoleta,
       c.latitudecoleta::float8              AS lat_coleta,
       c.longitudecoleta::float8             AS lng_coleta,
       c.latitudeentrega::float8             AS lat_entrega,
       c.longitudeentrega::float8            AS lng_entrega,
       cd.nomefantasia                       AS destinatario_nome,
       cd.cidade                             AS destinatario_cidade,
       cd.uf                                 AS destinatario_uf,
       coalesce(nullif(trim(mt.nomefantasia),''),
                nullif(trim(mt.razaosocial),''))  AS motorista_nome,
       coalesce(nullif(trim(tm.nomefantasia),''),
                nullif(trim(tm.razaosocial),''))  AS cliente_nome,
       coalesce(nullif(trim(pg.nomefantasia),''),
                nullif(trim(pg.razaosocial),''))  AS pagador_nome
FROM conhecimento c
LEFT JOIN cadastro cd ON cd.codigo = c.destinatario
LEFT JOIN cadastro mt ON mt.codigo = c.motorista
LEFT JOIN cadastro tm ON tm.codigo = c.cnpjcpfcodigotomadorservico
LEFT JOIN cadastro pg ON pg.codigo = c.cnpjcpfcodigopagadorfrete
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

#: AS NOTAS DO CT-e. E o documento que quem RECEBE conhece — ele guarda a nota
#: do fornecedor, quase nunca o numero do conhecimento —, entao ver a propria
#: nota na tela e o que confirma "e a minha carga mesmo".
#:
#: Sai so o NUMERO. A chave de acesso de 44 digitos identifica a nota inteira
#: na SEFAZ e nao acrescenta nada a quem ja esta olhando a carga.
NOTAS_SQL = """
SELECT DISTINCT cn.numeronotafiscal AS numero
FROM conhecimento_composicao cc
JOIN coleta_notafiscal cn
  ON cn.grupo = cc.grupo AND cn.empresa = cc.empresa
 AND cn.filial = cc.filialdocumento AND cn.unidade = cc.unidadedocumento
 AND cn.diferenciadornumero = cc.diferenciadornumerodocumento
 AND cn.serie = cc.seriedocumento AND cn.numero = cc.numerodocumento
WHERE cc.grupo = %(g)s AND cc.empresa = %(e)s AND cc.filial = %(f)s
  AND cc.numero = %(n)s AND cc.serie = %(s)s
  AND cn.numeronotafiscal IS NOT NULL
ORDER BY 1
LIMIT 40
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


def _notas(chaves: dict) -> list[str]:
    try:
        return [str(r["numero"]) for r in db.query(NOTAS_SQL, chaves)]
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: notas falharam: %s", type(exc).__name__)
        return []


#: Cache do transito, por coordenada ARREDONDADA. Duas razoes, e as duas
#: importam: o limite da TomTom e de RITMO (nao de cota diaria), e numa pagina
#: publica dez pessoas podem estar olhando o mesmo caminhao ao mesmo tempo.
#: Arredondar para duas casas (~1,1 km) faz todas compartilharem uma chamada.
_TRANSITO: dict[tuple, tuple[float, dict]] = {}
TRANSITO_TTL_S = 600


def _transito(lat: float, lng: float) -> dict | None:
    """Como esta a estrada onde o veiculo esta. `None` quando nao da para saber.

    NAO E ALARME QUANDO FALTA: transito e informacao a mais. Sem chave da
    TomTom, com ela fora do ar ou no 429 de ritmo, a secao simplesmente nao
    aparece — inventar "fluxo normal" seria pior que o silencio.
    """
    from ..tomtom import cliente as tt_cli
    from ..tomtom import transito as tt

    if not tt_cli.configurado():
        return None
    chave = (round(float(lat), 2), round(float(lng), 2))
    agora = time.time()
    guardado = _TRANSITO.get(chave)
    if guardado and agora - guardado[0] < TRANSITO_TTL_S:
        return guardado[1]
    try:
        bruto = tt_cli.fluxo(chave[0], chave[1])
        lido = tt.do_payload(bruto)
    except Exception as exc:  # noqa: BLE001
        log.info("rastreio: transito indisponivel: %s", type(exc).__name__)
        return None
    if len(_TRANSITO) > 800:
        _TRANSITO.clear()
    _TRANSITO[chave] = (agora, lido)
    return lido


#: As chaves do conhecimento em curso. Um dicionario de modulo em vez de mais
#: um parametro em `_andamento`: a funcao ja e chamada de dois lugares e a
#: assinatura dela e testada.
_CHAVES_ATUAIS: dict = {}


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

    # A ROTA REAL MANDA. A reta so existe como plano B, para a viagem sem
    # trajeto cadastrado — e ela subestima sempre: "faltam 56 km" quando faltam
    # 80 de asfalto e uma promessa que a operacao nao cumpre, e quem espera na
    # doca organiza a equipe em cima dela.
    r = rota.obter(_CHAVES_ATUAIS.get("chaves") or {},
                   linha.get("destinatario_cidade") or "")
    if r:
        pr = rota.progresso(r, pos["lat"], pos["lng"])
        if pr and pr.get("falta_km") is not None:
            # AFASTAMENTO DA ROTA no lugar da comparacao de distancias: ele
            # nao depende de o destino estar a frente, e responde direto a
            # pergunta "este veiculo esta nesta viagem?".
            if pr["afastado_km"] > FORA_DA_ROTA_KM:
                fora["fora_da_rota"] = True
                return fora
            fora["tem_posicao"] = True
            fora["atualizado_ha_min"] = idade
            fora["progresso_pct"] = pr["progresso_pct"]
            fora["falta_km"] = pr["falta_km"]
            fora["km_rota"] = pr["rota_km"]
            fora["percorrido_km"] = pr["percorrido_km"]
            fora["rodovia"] = pr.get("rodovia")
            fora["por_rota"] = True
            fora["chegou"] = pr["falta_km"] <= RAIO_CHEGADA_KM
            fora["area"] = {"lat": _arredondar(pos["lat"]),
                            "lng": _arredondar(pos["lng"]),
                            "raio_km": AREA_RAIO_KM}
            # AS PARADAS VAO JUNTO. Sem elas, uma rota de coleta que vai ate
            # o ponto mais distante e VOLTA recolhendo parece uma linha
            # cruzada, e quem olha conclui que o mapa esta quebrado. Com os
            # pontos marcados, a mesma linha se le como o que e: um circuito
            # com paradas.
            fora["rota_pontos"] = [{"lat": x["lat"], "lng": x["lng"],
                                    "nome": (x.get("cidadepassa") or "").strip().title()}
                                   for x in r["pontos"]]
            t = _transito(pos["lat"], pos["lng"])
            if t:
                atraso = t.get("atraso_s")
                fora["transito"] = {
                    "estado": t.get("estado"), "rotulo": t.get("rotulo"),
                    "atraso_min": (int(round(atraso / 60.0))
                                   if isinstance(atraso, (int, float)) and atraso
                                   else None)}
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

    # A POSICAO PARA O MAPA, ARREDONDADA DE PROPOSITO. Uma casa decimal e
    # ~11 km: diz a REGIAO onde o veiculo esta e nao serve para intercepta-lo
    # numa rodovia. E o que foi decidido para esta pagina, e o mapa desenha um
    # CIRCULO com esse raio em vez de um alfinete — alfinete promete precisao
    # que este numero nao tem, e quem olha acredita no alfinete.
    fora["area"] = {"lat": _arredondar(pos["lat"]),
                    "lng": _arredondar(pos["lng"]),
                    "raio_km": AREA_RAIO_KM}
    # O TRANSITO le a coordenada CHEIA (ela nao sai daqui) porque a leitura da
    # TomTom e do trecho de estrada, e arredondar antes cairia noutro trecho.
    t = _transito(pos["lat"], pos["lng"])
    if t:
        # `atraso_s` e o nome do campo na leitura da TomTom; a tela fala em
        # minutos, e converter no LIMITE do modulo evita cada tela dividir por
        # 60 do seu jeito.
        atraso = t.get("atraso_s")
        fora["transito"] = {
            "estado": t.get("estado"), "rotulo": t.get("rotulo"),
            "atraso_min": (int(round(atraso / 60.0))
                           if isinstance(atraso, (int, float)) and atraso else None)}
    if total and total > 0:
        pct = 100.0 * (1 - min(1.0, max(0.0, falta / total)))
        fora["progresso_pct"] = int(round(pct))
    return fora


#: Conectivos que ficam em minuscula quando o CAIXA ALTA do ERP vira nome de
#: gente. Nome de pessoa gritado numa pagina que o cliente le e so descuido de
#: cadastro vazando para fora.
_CONECTIVOS = {"de", "da", "do", "das", "dos", "e"}


def _nome_pessoa(v) -> str | None:
    """O nome do motorista como se escreve, a partir do caixa alta do ERP."""
    partes = (v or "").split()
    if not partes:
        return None
    return " ".join(p.lower() if p.lower() in _CONECTIVOS else p.capitalize()
                    for p in partes)


def _transporte(linha: dict) -> dict:
    """Quem contratou, quem paga e quem esta levando a carga.

    ESTE BLOCO TEM NOME PROPRIO DE PROPOSITO. Ele e o unico lugar da pagina
    publica com placa e nome de pessoa, e o `mensagem`/`aviso` monta o texto do
    WhatsApp por lista explicita de campos — separado assim, ninguem o alcanca
    por descuido ao escrever uma mensagem nova.

    O PAGADOR QUASE NUNCA E OUTRO. Medido em 05/09/2026: tomador e pagador do
    frete sao a MESMA empresa em 16.960 dos 16.964 CT-e dos ultimos 90 dias (os
    quatro restantes nao tem nem um nem outro). Repetir a mesma razao social em
    duas linhas e coluna constante — a tela junta as duas quando coincidem, e
    so separa quando ha o que separar. O campo continua saindo porque o dia em
    que a operacao vender frete com pagador de terceiro, a tela ja o mostra.
    """
    cliente = (linha.get("cliente_nome") or "").strip() or None
    pagador = (linha.get("pagador_nome") or "").strip() or None
    return {
        "cliente": cliente,
        "pagador": pagador,
        "pagador_igual_cliente": bool(cliente and pagador
                                      and cliente == pagador),
        "motorista": _nome_pessoa(linha.get("motorista_nome")),
        # A placa vai como esta pintada na porta: sem hifen inventado e sem
        # formatacao nossa, porque quem confere na portaria compara caractere
        # a caractere com o veiculo parado na frente dele.
        "cavalo": (linha.get("placa") or "").strip().upper() or None,
        # CARRETA1 SO. Cobertura medida: 82,0% em 90 dias; a segunda aparece em
        # 1,6% (bitrem) e a terceira em nenhum CT-e. Sem carreta a linha
        # simplesmente nao aparece — carga de truck nao tem implemento, e um
        # "n/d" ali seria falha inventada.
        "carreta": (linha.get("carreta") or "").strip().upper() or None,
    }


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

    return {"ok": True, "carga": _montar(dict(linhas2[0]), {
        "g": alvo["grupo"], "e": alvo["empresa"], "f": alvo["filial"],
        "n": alvo["numero"], "s": alvo["serie"]})}


def _montar(linha: dict, chaves: dict) -> dict:
    """A carga pública, a partir de UMA linha do detalhe.

    Existe separada porque há DOIS caminhos até aqui — a busca (documento +
    CNPJ) e o link assinado do WhatsApp — e um segundo lugar montando o mesmo
    payload é um segundo lugar por onde um campo novo do ERP entra na página
    pública sem ninguém decidir.
    """
    _CHAVES_ATUAIS["chaves"] = chaves
    andamento = _andamento(linha)
    # ORIGEM E DESTINO VAO INTEIROS. Nao e incoerencia com a posicao
    # arredondada: o endereco de coleta e o de entrega sao de quem despachou e
    # de quem recebe — as duas pontas ja os conhecem. O que se protege e onde
    # o CAMINHAO esta agora.
    pontos = {}
    if linha.get("lat_coleta") and linha.get("lng_coleta"):
        pontos["origem"] = {"lat": float(linha["lat_coleta"]),
                            "lng": float(linha["lng_coleta"])}
    if linha.get("lat_entrega") and linha.get("lng_entrega"):
        pontos["destino"] = {"lat": float(linha["lat_entrega"]),
                             "lng": float(linha["lng_entrega"])}
    return {
        # A base é a carga JÁ LIMPA, montada pela mesma lista explícita da
        # busca — o detalhe acrescenta, nunca abre o registro cru.
        **consulta._limpo(linha),
        "andamento": andamento,
        "transporte": _transporte(linha),
        "etapas": _linha_do_tempo(linha, andamento),
        "notas": _notas(chaves),
        "mapa": pontos,
        "consultado_em": datetime.now(timezone.utc).isoformat(),
    }


def por_link(token: str) -> dict:
    """A carga de um link assinado do WhatsApp. Nunca levanta.

    O TOKEN É A PROVA, e é a única aqui. Quem o recebeu já provou o CNPJ no
    cadastro da assinatura; exigir de novo o documento e os quatro dígitos a
    cada aviso de hora em hora transformaria o link em um formulário, e ninguém
    o usaria. O que sustenta isso é o que o token é: assinado com HMAC (não se
    forja nem se incrementa para a carga do vizinho) e com prazo curto
    (`consulta.LINK_DIAS`), então um encaminhamento no grupo da família não
    vira acesso permanente.
    """
    chaves = consulta.link_abrir(token or "")
    if not chaves:
        # MESMA RESPOSTA para token adulterado, expirado e malformado: separar
        # os motivos diria a quem tenta se o palpite chegou perto.
        return {"ok": True, "carga": None}
    try:
        linhas = db.query(DETALHE_SQL, chaves)
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: detalhe por link falhou: %s", type(exc).__name__)
        return {"ok": False, "motivo": "não foi possível consultar agora"}
    if not linhas:
        return {"ok": True, "carga": None}
    return {"ok": True, "carga": _montar(dict(linhas[0]), chaves)}
