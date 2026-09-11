# -*- coding: utf-8 -*-
"""O que a tela mostra das batidas — agregado, do banco da casa.

NÃO FALA COM O FORNECEDOR. Tudo aqui sai de `pc_marcacao` e `pc_cerca`, que a
coleta enche a cada 10 minutos. Tela que chama fornecedor a cada pintura fica
refém do dia ruim dele, e esta responde "e agora?" — precisa abrir.

O QUE ESTA TELA PODE E NÃO PODE DIZER
=====================================
Pode dizer que uma batida caiu fora, a que distância, e de quem foi. NÃO pode
dizer ONDE a pessoa estava: a coordenada é descartada na coleta, e o que fica é
um escalar até a cerca mais próxima. Isso é decisão de projeto, não limitação
— ver `coleta.py`.

A CALIBRAÇÃO DO RAIO É O NÚMERO QUE ESTA TELA EXISTE PARA DAR
=============================================================
Cerca apertada reprova quem está dentro da unidade — e foi isso, mais a
ausência de GPS, que produziu os 63% de "fora de cerca" que fizeram o ponto por
aplicativo ser desligado em jan/2025.

A tabela mostra, por cerca, quantas batidas o fornecedor REPROVOU que estão a
poucos passos do centro. Reprovada a 60 m de um raio de 40 m é problema de
raio; reprovada a 2 km é outra conversa, e não se resolve com raio. Quem decide
o raio novo é o RH, com o número na frente — ver `calibracao()` para por que
não se mede isso pela dispersão de todas as batidas.
"""
from __future__ import annotations

import logging

from api import pglocal
from api.queries import cached

log = logging.getLogger(__name__)

ESQUEMA: str | None = None

#: Janela padrão da tela. 14 dias cobre duas semanas de escala sem pesar.
DIAS = 14


def _esq() -> str | None:
    return ESQUEMA


def _q(sql: str, params=None) -> list[dict]:
    try:
        return pglocal.query(sql, params, esquema=_esq())
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return []
        raise


@cached(ttl=60, velha_ate=3600)
def resumo(dias: int = DIAS) -> dict:
    """KPIs, série diária e o frescor da coleta.

    TTL de 60 s: a coleta roda de 10 em 10 minutos, então cache maior só
    atrasaria o que já chegou. A tela pergunta "e agora?".
    """
    dias = max(1, min(int(dias or DIAS), 90))
    p = {"d": dias}

    tot = _q("""SELECT COUNT(*) n,
                       COUNT(DISTINCT matricula) pessoas,
                       MAX(marcada_em) ultima,
                       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latencia_s)) latencia,
                       SUM(CASE WHEN situacao='dentro' THEN 1 ELSE 0 END) dentro,
                       SUM(CASE WHEN situacao='fora' THEN 1 ELSE 0 END) fora,
                       SUM(CASE WHEN situacao='sem_coordenada' THEN 1 ELSE 0 END) sem
                  FROM pc_marcacao
                 WHERE marcada_em >= now() - make_interval(days => %(d)s)""", p)
    t = tot[0] if tot else {}
    n = int(t.get("n") or 0)

    # A série é POR DIA e o dia de hoje sai marcado: ele está em curso, e uma
    # coluna baixa às 9h da manhã não é queda de movimento.
    serie = [{
        "dia": r["dia"].isoformat() if hasattr(r["dia"], "isoformat") else str(r["dia"]),
        "dentro": int(r["dentro"]), "fora": int(r["fora"]),
        "sem_coordenada": int(r["sem"]), "total": int(r["total"]),
        "parcial": bool(r["hoje"]),
    } for r in _q("""SELECT date_trunc('day', marcada_em)::date dia,
                            SUM(CASE WHEN situacao='dentro' THEN 1 ELSE 0 END) dentro,
                            SUM(CASE WHEN situacao='fora' THEN 1 ELSE 0 END) fora,
                            SUM(CASE WHEN situacao='sem_coordenada' THEN 1 ELSE 0 END) sem,
                            COUNT(*) total,
                            (date_trunc('day', marcada_em)::date = current_date) hoje
                       FROM pc_marcacao
                      WHERE marcada_em >= now() - make_interval(days => %(d)s)
                      GROUP BY 1, 6 ORDER BY 1""", p)]

    cursor = {}
    c = _q("SELECT * FROM pc_cursor WHERE chave = 'marcacoes'")
    if c:
        cursor = {"ultimo_id": int(c[0]["ultimo_id"]),
                  "marcacoes": int(c[0]["marcacoes"]),
                  "ultima_coleta_em": c[0]["ultima_coleta_em"].isoformat()
                                      if c[0]["ultima_coleta_em"] else None,
                  "ultimo_erro": c[0]["ultimo_erro"]}

    return {
        "dias": dias,
        "kpis": {
            "batidas": n,
            "pessoas": int(t.get("pessoas") or 0),
            "ultima_batida": t["ultima"].isoformat() if t.get("ultima") else None,
            "latencia_s": int(t["latencia"]) if t.get("latencia") is not None else None,
            "dentro": int(t.get("dentro") or 0),
            "fora": int(t.get("fora") or 0),
            "sem_coordenada": int(t.get("sem") or 0),
            # A fração SEM COORDENADA é o número que decide se a cerca pode
            # virar regra: metade das batidas não traz GPS, e uma regra que
            # reprove essa metade é uma regra que ninguém consegue cumprir.
            "pct_sem_coordenada": round(100 * (t.get("sem") or 0) / n, 1) if n else 0.0,
            "pct_fora": round(100 * (t.get("fora") or 0) / n, 1) if n else 0.0,
        },
        "serie": serie,
        "cursor": cursor,
        "fonte": "CÓRTEX · pc_marcacao (coleta do Ponto Certificado, 10 em 10 min)",
    }


@cached(ttl=300, velha_ate=3600)
def calibracao(dias: int = 30) -> list[dict]:
    """Quanto o raio atual REPROVA de quem está logo ali.

    A PRIMEIRA VERSÃO DISTO ESTAVA ERRADA, e a lição fica escrita porque o
    número parecia certo: eu tomava o p95 de TODAS as batidas atribuídas à
    cerca — inclusive as que caíram a 12 km e só tinham aquela como a mais
    próxima — e chamava de "dispersão real". Dava p95 de 12.285 m para
    PIRAQUARA e o veredito "apertado" para tudo, sempre. Média de quem está
    dentro com quem está longe não descreve nenhum dos dois.

    E o outro lado também não serve: as batidas ACEITAS estão, por construção,
    dentro do raio — o p95 delas nunca acusaria raio apertado.

    O que responde a pergunta é a FAIXA LOGO FORA: quantas batidas o fornecedor
    reprovou que estão a poucos passos do centro. Se há gente reprovada a 60 m
    de um raio de 40 m, o raio é o problema — não a pessoa. Acima de ~500 m a
    conversa é outra (trabalho externo, home office), e não se resolve com
    raio.
    """
    dias = max(7, min(int(dias or 30), 180))
    linhas = _q("""
        WITH fora AS (
            SELECT cerca_proxima nome, distancia_m dist
              FROM pc_marcacao
             WHERE situacao = 'fora' AND distancia_m IS NOT NULL
               AND cerca_proxima IS NOT NULL
               AND marcada_em >= now() - make_interval(days => %(d)s)
        ), dentro AS (
            SELECT cerca_proxima nome, COUNT(*) n
              FROM pc_marcacao
             WHERE situacao = 'dentro'
               AND marcada_em >= now() - make_interval(days => %(d)s)
             GROUP BY 1
        ), perto AS (
            SELECT nome,
                   COUNT(*) FILTER (WHERE dist <= 100) ate100,
                   COUNT(*) FILTER (WHERE dist <= 250) ate250,
                   COUNT(*) FILTER (WHERE dist <= 500) ate500,
                   COUNT(*) FILTER (WHERE dist > 500)  longe,
                   ROUND(MIN(dist)) mais_perto
              FROM fora GROUP BY 1
        )
        SELECT c.nome, MIN(c.forma) forma, MAX(c.raio_m) raio_m,
               BOOL_OR(c.ativa) ativa, COUNT(*) pontos,
               COALESCE(MAX(d.n), 0) aceitas,
               COALESCE(MAX(p.ate100), 0) ate100,
               COALESCE(MAX(p.ate250), 0) ate250,
               COALESCE(MAX(p.ate500), 0) ate500,
               COALESCE(MAX(p.longe), 0) longe,
               MAX(p.mais_perto) mais_perto
          FROM pc_cerca c
          LEFT JOIN dentro d ON d.nome = c.nome
          LEFT JOIN perto  p ON p.nome = c.nome
         GROUP BY c.nome ORDER BY 6 DESC, 9 DESC, c.nome""", {"d": dias})

    saida = []
    for r in linhas:
        raio = float(r["raio_m"] or 0)
        poligono = r["forma"] == "poligono"
        ate250 = int(r["ate250"])
        perto = int(r["mais_perto"]) if r["mais_perto"] is not None else None
        if poligono:
            veredito = "n/d"
            motivo = ("área desenhada por vértices, sem raio — a distância aqui "
                      "é medida até o vértice, não até a borda")
        elif ate250:
            veredito = "apertado"
            motivo = (f"{ate250} batida(s) reprovada(s) a menos de 250 m do centro"
                      + (f", a mais próxima a {perto} m" if perto is not None else ""))
        elif int(r["longe"]):
            veredito = "ok"
            motivo = (f"as {int(r['longe'])} reprovadas estão todas acima de 500 m — "
                      "não é raio, é lugar")
        elif int(r["aceitas"]):
            veredito = "ok"
            motivo = "nenhuma batida reprovada perto"
        else:
            veredito, motivo = "n/d", "sem batida atribuída no período"
        saida.append({
            "nome": r["nome"], "forma": r["forma"], "pontos": int(r["pontos"]),
            "raio_m": raio if not poligono else None, "ativa": bool(r["ativa"]),
            "aceitas": int(r["aceitas"]),
            "ate100": int(r["ate100"]), "ate250": ate250, "ate500": int(r["ate500"]),
            "longe": int(r["longe"]), "mais_perto": perto,
            "veredito": veredito, "motivo": motivo,
        })
    return saida


@cached(ttl=900, velha_ate=7200)
def _nomes() -> dict:
    """Matrícula -> (nome, filial), do ERP.

    O NOME NÃO É GRAVADO NA COLETA, de propósito: `pc_marcacao` guarda a
    matrícula e mais nada de identidade. Um espelho de nomes no banco da casa
    envelhece — a pessoa muda de filial, casa, é desligada — e passa a mostrar
    um cadastro que já não existe. Resolver na LEITURA custa uma consulta com
    TTL de 15 min e sempre diz o que o ERP diz hoje.

    A chave é a chapa de 6 dígitos, e é por isso que `cliente._matricula()`
    normaliza com zeros à esquerda: o fornecedor devolve "3878" para 36% das
    pessoas, e sem o `zfill` o nome não aparece — sem erro nenhum.
    """
    try:
        from api import db_folha
        if not db_folha.configured():
            return {}
        linhas = db_folha.query(
            """SELECT chapafunc chapa, nomefunc nome, descsecao filial,
                      descfuncao funcao, situacaofunc situacao
                 FROM vw_funcionarios WHERE codigoempresa = 1""")
    except Exception as exc:  # noqa: BLE001
        # Sem o ERP a tela continua: ela mostra a matrícula, que é o que ela
        # tinha antes. Nome ausente não pode derrubar o resto do painel.
        log.warning("painel: nomes indisponiveis: %s", type(exc).__name__)
        return {}
    return {(r["chapa"] or "").strip(): {
                "nome": r["nome"], "filial": r["filial"],
                "funcao": r["funcao"], "situacao": r["situacao"]}
            for r in linhas if (r["chapa"] or "").strip()}


@cached(ttl=120, velha_ate=3600)
def por_pessoa(dias: int = DIAS, limite: int = 40) -> list[dict]:
    """Quem bate fora, e quanto. PII — a tela é de RBAC de RH.

    A ordem é por batidas FORA, não por total: quem tem 3 de 3 fora importa
    mais que quem tem 5 de 200.
    """
    dias = max(1, min(int(dias or DIAS), 90))
    nomes = _nomes()
    return [{
        "matricula": r["matricula"],
        # O nome vem do ERP na hora. Quando ele não responde, a matrícula
        # continua ali: melhor a chave crua do que uma linha sem identidade.
        "nome": (nomes.get(r["matricula"]) or {}).get("nome"),
        "filial": (nomes.get(r["matricula"]) or {}).get("filial"),
        "funcao": (nomes.get(r["matricula"]) or {}).get("funcao"),
        "batidas": int(r["n"]),
        "fora": int(r["fora"]), "dentro": int(r["dentro"]),
        "sem_coordenada": int(r["sem"]),
        "pct_fora": round(100 * int(r["fora"]) / int(r["n"]), 1) if r["n"] else 0.0,
        "distancia_media": int(r["dist"]) if r["dist"] is not None else None,
        "ultima": r["ultima"].isoformat() if r["ultima"] else None,
    } for r in _q("""
        SELECT matricula, COUNT(*) n,
               SUM(CASE WHEN situacao='fora' THEN 1 ELSE 0 END) fora,
               SUM(CASE WHEN situacao='dentro' THEN 1 ELSE 0 END) dentro,
               SUM(CASE WHEN situacao='sem_coordenada' THEN 1 ELSE 0 END) sem,
               ROUND(AVG(distancia_m) FILTER (WHERE situacao='fora')) dist,
               MAX(marcada_em) ultima
          FROM pc_marcacao
         WHERE marcada_em >= now() - make_interval(days => %(d)s)
         GROUP BY matricula
        HAVING SUM(CASE WHEN situacao='fora' THEN 1 ELSE 0 END) > 0
         ORDER BY 3 DESC, 2 DESC LIMIT %(l)s""", {"d": dias, "l": max(5, min(limite, 200))})]


def _dia_pedido(dia: str | None) -> str:
    """Traduz o que a tela pede para uma data ISO, SEMPRE em horário local.

    `hoje`/`ontem` se resolvem no BANCO (`current_date`), que é onde
    `marcada_em` é comparada — resolver aqui no Python daria a data do processo
    da API, e a casa já se queimou com `toISOString()` devolvendo o dia
    anterior em UTC−3. Data explícita passa validada; qualquer outra coisa é
    hoje.
    """
    import re
    d = (dia or "hoje").strip().lower()
    if d in ("hoje", "ontem"):
        return d
    return d if re.match(r"^\d{4}-\d{2}-\d{2}$", d) else "hoje"


@cached(ttl=60, velha_ate=1800)
def do_dia(dia: str | None = None) -> dict:
    """O DIA: quem bateu, a que horas e onde — uma linha por PESSOA.

    É a pergunta operacional que o AFD do ERP não responde: ele chega por
    importação manual, com mediana de 3 dias de atraso, então "quem bateu hoje"
    simplesmente não existe lá. Aqui existe, com 12 s de latência mediana.

    "ONDE" TEM TRÊS RESPOSTAS, E A MAIS COMUM É UMA AUSÊNCIA
    =======================================================
    Medido em 11/09/2026 (66 batidas do dia até as 8h19):

        dentro de cerca ....  18  -> o lugar TEM nome (PIRAQUARA, AUDI, TUPY)
        fora de cerca ......  16  -> não há nome; o que se sabe é a DISTÂNCIA
                                     até a cerca mais próxima (9 a 12 km)
        sem coordenada .....  32  -> não se sabe, e não é infração

    A terceira é quase metade, e chamá-la de "fora" seria repetir o defeito que
    desligou o ponto por aplicativo em jan/2025. O que se sabe dela é o RELÓGIO
    onde a batida entrou, e por isso ele vai junto na linha: das 59 séries
    vistas, 57 são de UMA pessoa só (aplicativo no aparelho dela) e uma —
    `00000.31900.997904` — é usada por 42 pessoas de TODAS as filiais e nunca
    manda GPS. Não é um relógio de parede de uma unidade (as filiais não
    batem), e este módulo NÃO inventa o que ele é: mostra o número de série e
    quantas pessoas o usam, que é o que dá para provar. Quem sabe é o RH.

    O DIA DE HOJE ESTÁ EM CURSO, e a tela diz isso: às 8h da manhã quem entra
    às 13h ainda não bateu. Contar isso como falta seria transformar o relógio
    em acusação.
    """
    d = _dia_pedido(dia)
    if d == "hoje":
        onde, p = "marcada_em >= current_date AND marcada_em < current_date + 1", {}
    elif d == "ontem":
        onde, p = ("marcada_em >= current_date - 1 AND marcada_em < current_date", {})
    else:
        onde = "marcada_em >= %(d)s::date AND marcada_em < %(d)s::date + 1"
        p = {"d": d}

    linhas = _q(f"""
        SELECT matricula, marcada_em, situacao, local, distancia_m,
               cerca_proxima, relogio, atividade,
               (marcada_em::date) dia
          FROM pc_marcacao
         WHERE {onde}
         ORDER BY matricula, marcada_em""", p)

    # Quantas pessoas usam cada relógio NA JANELA LONGA, não no dia: com um dia
    # só, todo relógio pareceria individual e a distinção sumiria.
    compart = {r["relogio"]: int(r["p"]) for r in _q(
        """SELECT relogio, COUNT(DISTINCT matricula) p FROM pc_marcacao
            WHERE relogio IS NOT NULL AND marcada_em >= now() - interval '90 days'
            GROUP BY 1""")}

    nomes = _nomes()
    pessoas: dict[str, dict] = {}
    for r in linhas:
        m = r["matricula"]
        cad = nomes.get(m) or {}
        alvo = pessoas.setdefault(m, {
            "matricula": m, "nome": cad.get("nome"), "filial": cad.get("filial"),
            "funcao": cad.get("funcao"), "situacao_cad": cad.get("situacao"),
            "batidas": [], "n": 0, "dentro": 0, "fora": 0, "sem_coordenada": 0,
            "locais": [], "primeira": None, "ultima": None,
        })
        hora = r["marcada_em"].strftime("%H:%M")
        # O LUGAR, pelo que se sabe dele — e nunca um nome inventado para a
        # ausência. `local` vem 'FORA DE CERCA' do fornecedor nos dois casos
        # em que não há lugar, então ele não serve de rótulo sozinho.
        if r["situacao"] == "dentro":
            lugar = r["local"] or r["cerca_proxima"] or "dentro de cerca"
        elif r["situacao"] == "fora":
            km = (r["distancia_m"] or 0) / 1000
            perto = r["cerca_proxima"]
            # VÍRGULA, não ponto: o rótulo vai para a tela em português, e
            # "11.3 km" se lê como outra coisa em quem escreve 11,3.
            lugar = (f"{km:.1f}".replace(".", ",") + f" km de {perto}"
                     if perto and km >= 1
                     else f"{r['distancia_m']} m de {perto}" if perto
                     else "fora de cerca")
        else:
            lugar = "sem GPS"
        alvo["batidas"].append({
            "hora": hora, "situacao": r["situacao"], "lugar": lugar,
            "local": r["local"], "cerca": r["cerca_proxima"],
            "distancia_m": int(r["distancia_m"]) if r["distancia_m"] is not None else None,
            "relogio": r["relogio"],
            "relogio_pessoas": compart.get(r["relogio"]),
            "atividade": r["atividade"],
        })
        alvo["n"] += 1
        alvo[r["situacao"]] += 1
        if r["situacao"] == "dentro" and lugar not in alvo["locais"]:
            alvo["locais"].append(lugar)
        alvo["primeira"] = alvo["primeira"] or hora
        alvo["ultima"] = hora

    ordenadas = sorted(pessoas.values(),
                       key=lambda x: (x["ultima"] or ""), reverse=True)

    # O resumo por LUGAR, que responde "onde a casa bateu hoje" sem abrir
    # pessoa por pessoa.
    # O FORA NÃO VIRA UM BALDE SÓ: ele se agrupa pela cerca MAIS PRÓXIMA, e é
    # assim que um local de trabalho SEM CERCA aparece — dez pessoas batendo
    # todo dia a 11 km da mesma unidade não são dez infrações, é uma cerca que
    # ninguém cadastrou. Foi o que os 68 casos acima de 10 km mostraram.
    locais: dict[str, dict] = {}
    for pes in pessoas.values():
        for b in pes["batidas"]:
            if b["situacao"] == "dentro":
                chave = b["local"] or "dentro de cerca"
            elif b["situacao"] == "fora":
                chave = "longe de " + (b["cerca"] or "qualquer cerca")
            else:
                chave = "sem GPS"
            alvo = locais.setdefault(chave, {"local": chave, "batidas": 0,
                                             "pessoas": set(), "situacao": b["situacao"],
                                             "dist": []})
            alvo["batidas"] += 1
            alvo["pessoas"].add(pes["matricula"])
            if b["distancia_m"] is not None:
                alvo["dist"].append(b["distancia_m"])
    def _mediana(v):
        if not v:
            return None
        v = sorted(v)
        return int(v[len(v) // 2])
    resumo_local = sorted(
        ({"local": v["local"], "situacao": v["situacao"], "batidas": v["batidas"],
          "pessoas": len(v["pessoas"]), "distancia_m": _mediana(v["dist"])}
         for v in locais.values()),
        key=lambda x: -x["batidas"])

    return {
        "dia": d,
        "data": linhas[0]["dia"].isoformat() if linhas else None,
        "em_curso": d == "hoje",
        "kpis": {
            "pessoas": len(pessoas),
            "batidas": len(linhas),
            "dentro": sum(1 for r in linhas if r["situacao"] == "dentro"),
            "fora": sum(1 for r in linhas if r["situacao"] == "fora"),
            "sem_coordenada": sum(1 for r in linhas if r["situacao"] == "sem_coordenada"),
            "primeira": ordenadas and min(p["primeira"] for p in pessoas.values()) or None,
            "ultima": ordenadas and max(p["ultima"] for p in pessoas.values()) or None,
        },
        "pessoas": ordenadas,
        "locais": resumo_local,
        "fonte": "CÓRTEX · pc_marcacao (Ponto Certificado, coleta de 10 em 10 min)",
    }



#: Quanto a distância do dia pode se afastar da distância típica e ainda contar
#: como "o mesmo lugar". Dez por cento sobre 1.884 m são 188 m — mais que o
#: suficiente para o GPS de um celular e para a pessoa bater do outro lado do
#: pátio, e pouco o bastante para não confundir 12 km com 51 km.
MESMO_LUGAR_TOLERANCIA = 0.10


@cached(ttl=300, velha_ate=7200)
def fora_por_dia(dias: int = 7, ate: str | None = None) -> dict:
    """A evolução diária das batidas reprovadas, POR CERCA.

    O NÚMERO SOZINHO NÃO DIZ O QUE FAZER, e é por isso que esta função existe
    em vez de um total. "44 batidas fora de cerca ontem" pode ser qualquer uma
    de três coisas, e elas pedem providências opostas. O que as separa não é a
    quantidade: é a DISTÂNCIA, e principalmente se ela se REPETE.

    Medido em 11/09/2026, últimos 7 dias:

        SBC OPERACIONAL .. 37 a 44 por dia · 10-11 pessoas · 1.877 a 1.885 m
        PIRAQUARA ........  4 a 10 por dia ·  1-4  pessoas · 12.279 a 12.310 m
        MAXION CRZ .......  2 a  7 por dia ·  2-3  pessoas · 2.846 a 100.978 m
        TUPY .............  1 a  2 por dia ·  1    pessoa  ·    41 a 7.291 m

    A primeira linha é onze pessoas batendo TODO DIA a mil oitocentos e oitenta
    e poucos metros — a mesma distância, dia após dia, com variação de oito
    metros em cinco dias. Isso não é gente no lugar errado: é um local de
    trabalho que ninguém cadastrou como cerca. A terceira linha é a mesma
    quantidade de gente com a distância pulando de 2,8 km para 100 km: essas
    estão em trânsito, e cerca nenhuma resolve. A quarta, a 41 m, é cerca
    apertada demais.

    Por isso a saída traz, por cerca, a série diária E `dias_no_mesmo_lugar`:
    em quantos dos dias com movimento a distância mediana ficou dentro de
    ±10% da distância típica. É esse número — e não o total — que diz se há um
    endereço a cadastrar.
    """
    import re
    from datetime import date as _d, timedelta as _td

    dias = max(2, min(int(dias or 7), 60))
    # `ate` existe para o e-mail da manhã, que fala do dia ANTERIOR: incluir
    # hoje ali poria uma coluna de meia manhã ao lado de dias inteiros, e a
    # queda seria lida como melhora.
    fim = (_d.fromisoformat(ate)
           if ate and re.match(r"^\d{4}-\d{2}-\d{2}$", ate) else _d.today())
    ini = fim - _td(days=dias - 1)
    linhas = _q("""
        SELECT COALESCE(cerca_proxima, '(sem cerca próxima)') cerca,
               (marcada_em::date) dia,
               COUNT(*) n,
               COUNT(DISTINCT matricula) pessoas,
               ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY distancia_m)) dist
          FROM pc_marcacao
         WHERE situacao = 'fora'
           AND marcada_em >= %(i)s::date
           AND marcada_em <  %(f)s::date + 1
         GROUP BY 1, 2 ORDER BY 1, 2""",
        {"i": ini.isoformat(), "f": fim.isoformat()})

    # O eixo de dias é GERADO, não colhido: dia sem reprovação nenhuma é uma
    # coluna ZERO na série, e não um buraco que emenda terça com sexta.
    eixo = [ini + _td(days=i) for i in range(dias)]

    por_cerca: dict[str, dict] = {}
    for r in linhas:
        c = por_cerca.setdefault(r["cerca"], {"cerca": r["cerca"], "por_dia": {},
                                              "pessoas": 0, "dist": []})
        c["por_dia"][r["dia"]] = int(r["n"])
        c["pessoas"] = max(c["pessoas"], int(r["pessoas"]))
        if r["dist"] is not None:
            c["dist"].append(float(r["dist"]))

    saida = []
    for c in por_cerca.values():
        ds = sorted(c["dist"])
        tipica = ds[len(ds) // 2] if ds else None
        perto = ([x for x in ds
                  if abs(x - tipica) <= tipica * MESMO_LUGAR_TOLERANCIA]
                 if tipica else [])
        saida.append({
            "cerca": c["cerca"],
            "serie": [c["por_dia"].get(d, 0) for d in eixo],
            "total": sum(c["por_dia"].values()),
            "pessoas": c["pessoas"],
            "distancia_m": int(tipica) if tipica is not None else None,
            "dias_com_movimento": len(ds),
            "dias_no_mesmo_lugar": len(perto),
        })
    saida.sort(key=lambda x: -x["total"])
    return {
        "dias": [d.isoformat() for d in eixo],
        "rotulos": [d.strftime("%d/%m") for d in eixo],
        "cercas": saida,
        "total": sum(c["total"] for c in saida),
        "tolerancia": MESMO_LUGAR_TOLERANCIA,
    }



@cached(ttl=300, velha_ate=7200)
def composicao_por_dia(dias: int = 7, ate: str | None = None) -> dict:
    """Dentro, fora e sem GPS, dia a dia — e o percentual que se pode afirmar.

    O DENOMINADOR DO PERCENTUAL NÃO É O TOTAL, e essa é a decisão que faz este
    número valer alguma coisa. Quase metade das batidas chega SEM COORDENADA
    (144 de 284 em 10/09/2026), e batida sem GPS não caiu dentro nem fora: não
    se sabe. Dividir "dentro" pelo total daria 26% e seria lido como "só um
    quarto das pessoas bate no lugar certo", quando o que aconteceu é que
    metade dos aparelhos não mandou posição.

    Então o percentual sai sobre as batidas COM COORDENADA — as únicas que
    podiam ser julgadas —, e o número das outras viaja ao lado, sempre. É a
    mesma regra do rastreador da frota, onde tirar do denominador quem não
    tinha como cumprir levou "79% sem sinal" a 86,7% de cobertura.

    Medido em 10/09/2026: 73 dentro e 67 fora entre as 140 com GPS, ou seja
    52,1% dentro — e 144 sem GPS ao lado, que é o número que decide se a cerca
    pode virar regra.
    """
    import re
    from datetime import date as _d, timedelta as _td

    dias = max(2, min(int(dias or 7), 60))
    fim = (_d.fromisoformat(ate)
           if ate and re.match(r"^\d{4}-\d{2}-\d{2}$", ate) else _d.today())
    ini = fim - _td(days=dias - 1)
    linhas = _q("""
        SELECT (marcada_em::date) dia,
               SUM(CASE WHEN situacao='dentro' THEN 1 ELSE 0 END) dentro,
               SUM(CASE WHEN situacao='fora' THEN 1 ELSE 0 END) fora,
               SUM(CASE WHEN situacao='sem_coordenada' THEN 1 ELSE 0 END) sem
          FROM pc_marcacao
         WHERE marcada_em >= %(i)s::date AND marcada_em < %(f)s::date + 1
         GROUP BY 1""", {"i": ini.isoformat(), "f": fim.isoformat()})
    por_dia = {r["dia"]: r for r in linhas}

    # Eixo GERADO: dia sem batida nenhuma e uma barra vazia, nao um buraco.
    eixo = [ini + _td(days=i) for i in range(dias)]
    serie = []
    for d in eixo:
        r = por_dia.get(d) or {}
        serie.append({
            "dia": d.isoformat(), "rotulo": d.strftime("%d/%m"),
            "dentro": int(r.get("dentro") or 0),
            "fora": int(r.get("fora") or 0),
            "sem_coordenada": int(r.get("sem") or 0),
        })
    dentro = sum(x["dentro"] for x in serie)
    fora = sum(x["fora"] for x in serie)
    sem = sum(x["sem_coordenada"] for x in serie)
    com_gps = dentro + fora
    return {
        "rotulos": [x["rotulo"] for x in serie],
        "serie": serie,
        "dentro": dentro, "fora": fora, "sem_coordenada": sem,
        "com_gps": com_gps, "total": dentro + fora + sem,
        # None, e nao zero, quando nao houve nenhuma batida com coordenada:
        # zero afirmaria "ninguem bateu dentro", que ninguem mediu.
        "pct_dentro": round(100 * dentro / com_gps, 1) if com_gps else None,
        "pct_sem_coordenada": (round(100 * sem / (com_gps + sem), 1)
                               if (com_gps + sem) else None),
    }


def matriculas_do_dia(dia: str) -> set[str]:
    """Quem bateu naquele dia — só as matrículas, para cruzar com o ERP.

    Fica aqui, e não em quem pergunta, porque é `pc_marcacao` que sabe
    responder — e porque a matrícula precisa sair com os mesmos 6 dígitos com
    que a coleta a normaliza: o fornecedor devolve "3878" para 36% das
    pessoas, e comparar isso com a chapa do ERP não casa nada, sem erro nenhum.
    """
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", dia or ""):
        raise ValueError("dia inválido")
    return {r["matricula"] for r in _q(
        """SELECT DISTINCT matricula FROM pc_marcacao
            WHERE marcada_em >= %(d)s::date
              AND marcada_em <  %(d)s::date + 1""", {"d": dia})}


def painel(dias: int = DIAS) -> dict:
    """O payload da aba. Nunca levanta por tabela ausente."""
    d = resumo(dias)
    return {**d, "calibracao": calibracao(), "por_pessoa": por_pessoa(dias)}
