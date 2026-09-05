# -*- coding: utf-8 -*-
"""Portal do cliente — "Minha Operação" (tela `cliop`).

A SEGUNDA PERGUNTA DE ACESSO DESTA CASA. O RBAC do CÓRTEX sempre respondeu
uma só: QUE TELA você abre (perfil × tela). Funcionava porque todo usuário era
gente da casa — quem podia abrir a tela podia ver a tela inteira. Aqui quem
loga é gente do CLIENTE, e a pergunta passa a ser QUAIS LINHAS são suas.

Não há RLS no banco, e não vai haver por causa desta tela: o AVA é réplica
somente-leitura de um ERP de terceiro (PostgreSQL 9.3), onde não se cria
política nenhuma. Então o escopo é aplicado AQUI, no servidor, e a regra é
uma frase: **nenhuma consulta deste módulo se monta sem uma raiz de CNPJ**.
`escopo()` levanta quando não há vínculo; não existe caminho que devolva
"todos" — é por isso que ela levanta em vez de devolver `None`, que alguém
mais adiante trataria como "sem filtro" num `if`.

POR QUE A RAIZ E NÃO O `agrupamentocliente` DO ERP, que existe e seria o
caminho óbvio: em 05/09/2026 o agrupamento 8 ("IOCHPE MAXION") tinha TRÊS dos
QUATRO CNPJs da empresa — faltava o 61156113000680 (Contagem/MG). Escopar por
ele entregaria um portal que esconde uma planta inteira do cliente sem erro
nenhum, e o sintoma seria "faltam cargas" meses depois. O agrupamento é
cadastro mantido à mão; a raiz do CNPJ é o próprio documento. Para DECIDIR
QUEM VÊ O QUÊ vale o documento. (O agrupamento continua valendo para o
freetime contratado, que é um contrato comercial e mora nele mesmo.)

O QUE NÃO SAI DAQUI
===================
Nome e telefone de motorista, CPF, valor de frete, custo, e a operação de
qualquer outro cliente. O que sai é a carga DELE: onde está, que horas
carregou e descarregou, quanto tempo ficou parada e contra qual freetime.

A placa SAI, e a diferença para o rastreio público é a identidade: lá qualquer
desconhecido digita um número, e placa + posição numa página aberta é
ferramenta de roubo de carga (`api/rastreio/__init__.py` explica). Aqui há
login, o vínculo é com a empresa dona da carga e a ação fica no `audit_log`.

O QUE ESTA TELA NÃO MEDE, DE PROPÓSITO
======================================
**Entrega no prazo.** Medido em 05/09/2026 sobre os 7.285 CT-es de 12 meses da
Maxion: `dtprevisaoentrega` é IGUAL à data de emissão em 80,3% deles — é
default do ERP, não prazo, exatamente como as OCs de suprimentos. Sobre a
previsão crua sai "91,2% no prazo", número que parece ótimo e não significa
nada. Restringindo aos CT-es com prazo de verdade (previsão > emissão) E com
entrega registrada, a régua cobre 634 de 7.285 — **8,7% da operação**.
Um KPI de pontualidade medindo 8,7% e chamando de nível de serviço é pior que
não ter KPI, e num painel que o CLIENTE lê é pior ainda: ele cobraria por ele.
Fica como nota de cobertura, não como número.

O que substitui é PERMANÊNCIA, que a operação registra de verdade: as
ocorrências SAC (394 chegada para carregamento → 395 saída → 396 chegada para
descarga → 397 fim de descarga) cobrem ~72% dos CT-es e têm hora. É também o
que dói num cliente industrial — veículo parado no pátio — e já tem contrato
contra o qual comparar (`sulista.sac_freetimecliente`).
"""
from __future__ import annotations

import logging
import re

from . import db
from .queries import cached

log = logging.getLogger("cortex.portal_cliente")

RE_RAIZ = re.compile(r"^[0-9]{8}$")

#: Teto físico de cada janela de permanência, em horas. Mesma régua do
#: SAC/Freetime e de `programacao_ciclos`: acima de 24h é quase sempre artefato
#: de pareamento (min(chegada) → max(saída) atravessando dias), não veículo
#: parado. Fora da faixa vira n/d CONTADO, nunca zero e nunca número inventado.
CAP_H = 24.0

#: Ocorrências SAC que formam a linha do tempo da carga. Os rótulos vêm da
#: tabela de domínio `public.ocorrencia` do ERP — não são invenção nossa, e é
#: por isso que estão aqui com o código ao lado: código sem tabela de domínio
#: não vira rótulo, e este tem tabela.
MARCOS = {
    394: "Chegada para carregamento",
    398: "Aguardando carregamento",
    395: "Saída do carregamento",
    400: "Em viagem",
    396: "Chegada para descarga",
    399: "Aguardando descarga",
    397: "Fim de descarga",
    401: "Viagem finalizada",
}

#: A ordem do fluxo. `max()` sobre ela responde "em que pé está" sem depender
#: de data ausente — estado vem do EVENTO, que é o campo de estado desta
#: operação, nunca de "não tem data de entrega".
ORDEM = [394, 398, 395, 400, 396, 399, 397, 401]


class SemEscopo(Exception):
    """Usuário sem vínculo de cliente pediu dado do portal.

    É exceção, e não um retorno vazio, porque vazio se confunde com "cliente
    sem carga hoje" — e um portal que mostra tela vazia para quem deveria ver
    a operação inteira demora semanas para ser reportado. Vira 403 na rota.
    """


def escopo(sess: dict | None) -> str:
    """A raiz de CNPJ da sessão, ou levanta. NUNCA devolve vazio.

    FAIL-CLOSED, e a diferença importa: se esta função pudesse devolver `None`
    ou `""` para "sem vínculo", a primeira consulta que interpolasse isso num
    `strpos(..., '') = 1` casaria com TODAS as linhas — o filtro de segurança
    viraria um filtro que não filtra, sem erro nenhum. Levantar é o que garante
    que o caminho "sem escopo" não tem para onde seguir.

    Admin NÃO é exceção aqui. Ser admin do CÓRTEX responde "que telas", não
    "de quem é a operação"; um admin sem vínculo não tem operação de cliente
    para ver, e liberar tudo para ele criaria a única sessão do sistema em que
    a tela mostra a carteira inteira — que é justamente o que o portal não pode
    ser capaz de fazer.
    """
    raiz = ((sess or {}).get("cliente_cnpj_raiz") or "").strip()
    if not RE_RAIZ.match(raiz):
        raise SemEscopo("sessão sem vínculo de cliente")
    return raiz


# O filtro de cliente, em SQL. Sai daqui e de nenhum outro lugar: uma segunda
# grafia deste `WHERE` é uma segunda chance de esquecer um dos três papéis.
#
# TRÊS PAPÉIS, e todos contam. Medido em 12 meses da Maxion: tomador+pagador em
# 7.227 CT-es, e 58 em que ela é SÓ destinatária (outro paga o frete e ela
# recebe a mercadoria). Esses 58 são carga dela tanto quanto os outros — quem
# espera a mercadoria é quem mais quer saber onde ela está.
#
# `strpos(cast(... AS text), raiz) = 1` e não `LIKE raiz || '%'`: as colunas de
# CNPJ do ERP são numéricas (é por isso que se chamam `cnpjcpfcodigo...`), o
# cast é obrigatório, e o `%` dentro de string SQL viraria placeholder do
# psycopg. Casar no INÍCIO é o que faz "raiz" significar raiz: `strpos > 1`
# acharia a sequência no meio de outro CNPJ.
FILTRO_CLIENTE = """(   strpos(cast(c.cnpjcpfcodigotomadorservico AS text), %(raiz)s) = 1
                     OR strpos(cast(c.cnpjcpfcodigopagadorfrete   AS text), %(raiz)s) = 1
                     OR strpos(cast(c.destinatario                AS text), %(raiz)s) = 1)"""


# ============================================================================
# 1) AGORA — as cargas em curso, e em que pé cada uma está.
# ============================================================================
# ESTADO VEM DO EVENTO, não da ausência de data. A regra da casa ("estado de
# fluxo vem do CAMPO de estado, nunca da ausência de data") aqui se lê assim:
# a carga está "em viagem" porque existe o evento 400, não porque `dtentrega`
# está NULL — que, medido, é NULL em 35% das cargas JÁ ENTREGUES.
#
# Uma linha por coleta, com o marco de maior ORDEM alcançado. `max(CASE ...)`
# por código em vez de `DISTINCT ON` porque o pareamento por par (chegada,
# saída) já precisa das colunas separadas para a permanência — é a mesma
# varredura servindo às duas perguntas, e é o que cabe no timeout do AVA.
AGORA_SQL = """
WITH ev AS (
  SELECT grupo,empresa,filial,unidade,diferenciadornumero,serie,numero,
    min(CASE WHEN ocorrencia=394 THEN dtocorrencia END) AS cc,
    max(CASE WHEN ocorrencia=395 THEN dtocorrencia END) AS sc,
    max(CASE WHEN ocorrencia=400 THEN dtocorrencia END) AS ev,
    min(CASE WHEN ocorrencia=396 THEN dtocorrencia END) AS cd,
    max(CASE WHEN ocorrencia=397 THEN dtocorrencia END) AS fd,
    max(CASE WHEN ocorrencia=401 THEN dtocorrencia END) AS vf
  FROM coleta_ocorrencia
  WHERE ocorrencia IN (394,395,396,397,400,401)
    AND dtocorrencia >= current_date - %(dias)s
  GROUP BY 1,2,3,4,5,6,7)
SELECT c.numero AS coleta,
       to_char(c.dtemissao,'YYYY-MM-DD')        AS emissao,
       upper(trim(coalesce(c.origem,'')))  AS origem,
       coalesce(c.uforigem,'')                   AS uf_origem,
       upper(trim(coalesce(c.destino,''))) AS destino,
       coalesce(c.ufdestino,'')                  AS uf_destino,
       trim(coalesce(c.veiculo,''))              AS placa,
       to_char(ev.cc,'YYYY-MM-DD HH24:MI') AS t_cheg_carga,
       to_char(ev.sc,'YYYY-MM-DD HH24:MI') AS t_saiu_carga,
       to_char(ev.ev,'YYYY-MM-DD HH24:MI') AS t_viagem,
       to_char(ev.cd,'YYYY-MM-DD HH24:MI') AS t_cheg_desc,
       to_char(ev.fd,'YYYY-MM-DD HH24:MI') AS t_fim_desc,
       to_char(ev.vf,'YYYY-MM-DD HH24:MI') AS t_finalizada
FROM ev
JOIN coleta c ON c.grupo=ev.grupo AND c.empresa=ev.empresa AND c.filial=ev.filial
  AND c.unidade=ev.unidade AND c.diferenciadornumero=ev.diferenciadornumero
  AND c.serie=ev.serie AND c.numero=ev.numero
WHERE c.dtcancelamento IS NULL
  AND """ + FILTRO_CLIENTE + """
ORDER BY coalesce(ev.vf, ev.fd, ev.cd, ev.ev, ev.sc, ev.cc) DESC
"""


def _marco(r: dict) -> tuple[int, str, str]:
    """O marco mais avançado que a carga alcançou: (código, rótulo, horário).

    Percorre ORDEM de trás para frente e para no primeiro evento com horário.
    Sem inferência: se o ERP não registrou 396, a carga não "chegou para
    descarga" — ela está no último marco que ALGUÉM registrou, e é isso que a
    tela diz. Carga sem evento nenhum não chega aqui (o `ev` não teria linha).
    """
    campos = {394: "t_cheg_carga", 395: "t_saiu_carga", 400: "t_viagem",
              396: "t_cheg_desc", 397: "t_fim_desc", 401: "t_finalizada"}
    for cod in reversed(ORDEM):
        col = campos.get(cod)
        if col and r.get(col):
            return cod, MARCOS[cod], r[col]
    return 0, "Sem registro", ""


#: O marco TERMINAL é o 397 (fim de descarga), não o 401 (viagem finalizada).
#: Medido em 05/09/2026: numa janela de 45 dias com 738 cargas da Maxion, 671
#: tinham 397 e UMA tinha 401 — o 401 aparece em ~45% do histórico (2.296 de
#: 5.137 no ano) e some no recente. Fechar a carga pelo 401 deixaria a
#: operação inteira eternamente "em curso" na tela do cliente: a carga chegou,
#: descarregou, e o portal continuaria dizendo que ela está a caminho. É o
#: mesmo erro de sempre — estado tirado da AUSÊNCIA de um registro que a
#: operação não tem obrigação de fazer.
TERMINAL = 397


def em_curso(r: dict) -> bool:
    """A carga ainda está no ar? Terminal = fim de descarga (ver TERMINAL)."""
    cod, _, _ = _marco(r)
    return 0 < cod and ORDEM.index(cod) < ORDEM.index(TERMINAL)


# ============================================================================
# 2) PERMANÊNCIA — quanto tempo o veículo ficou parado, contra o contratado.
# ============================================================================
# É a capa do painel, e não a pontualidade, pelo motivo escrito no topo deste
# arquivo: prazo de entrega é medível em 8,7% da operação e permanência em
# ~72%. Um número que cobre 8,7% num painel que o cliente lê é um número que
# ele vai cobrar sem saber que ele não existe.
#
# O FREETIME VEM DO CONTRATO (`sulista.sac_freetimecliente`), por
# `agrupamentocliente`, e é a ÚNICA coisa aqui que não passa pela raiz do
# CNPJ — porque freetime é cláusula comercial e mora no agrupamento mesmo.
# `DISTINCT ON` porque a tabela tem histórico: a Maxion tinha QUATRO linhas
# ativas para a mesma filial em 05/09/2026 (3h de carga, e descarga entre 3h e
# 6,5h). Join direto multiplicaria cada coleta por quatro e o total ficaria
# 4× maior — plausível, e errado. É a regra de vigência da casa.
PERM_SQL = """
WITH ev AS (
  SELECT grupo,empresa,filial,unidade,diferenciadornumero,serie,numero,
    min(CASE WHEN ocorrencia=394 THEN dtocorrencia END) AS cc,
    max(CASE WHEN ocorrencia=395 THEN dtocorrencia END) AS sc,
    min(CASE WHEN ocorrencia=396 THEN dtocorrencia END) AS cd,
    max(CASE WHEN ocorrencia=397 THEN dtocorrencia END) AS fd
  FROM coleta_ocorrencia
  WHERE ocorrencia IN (394,395,396,397)
    AND dtocorrencia::date BETWEEN %(dt_de)s AND %(dt_ate)s
  GROUP BY 1,2,3,4,5,6,7)
SELECT c.numero AS coleta,
       to_char(coalesce(ev.fd, ev.cd, ev.sc, ev.cc),'YYYY-MM-DD') AS data,
       upper(trim(coalesce(c.origem,'')))  AS origem,
       upper(trim(coalesce(c.destino,''))) AS destino,
       CASE WHEN ev.sc > ev.cc THEN extract(epoch from (ev.sc-ev.cc))/3600 END AS h_carga,
       CASE WHEN ev.fd > ev.cd THEN extract(epoch from (ev.fd-ev.cd))/3600 END AS h_descarga
FROM ev
JOIN coleta c ON c.grupo=ev.grupo AND c.empresa=ev.empresa AND c.filial=ev.filial
  AND c.unidade=ev.unidade AND c.diferenciadornumero=ev.diferenciadornumero
  AND c.serie=ev.serie AND c.numero=ev.numero
WHERE c.dtcancelamento IS NULL
  AND """ + FILTRO_CLIENTE + """
"""

# O freetime vigente do cliente. Uma linha, ou nenhuma — e "nenhuma" é n/d na
# tela, nunca zero: freetime zero significaria que toda hora parada é excedente.
FREETIME_SQL_TODAS = """
-- DISTINCT porque o vínculo tem UMA LINHA POR CNPJ (a Maxion tem três
-- filiais no agrupamento) e o join multiplicaria cada contrato por elas:
-- quatro contratos virariam doze, e "contratos: 12" na tela seria falso.
-- min/max sobreviveriam à duplicata; a CONTAGEM não — e é ela que diz ao
-- leitor se existe faixa ou não.
SELECT DISTINCT
       round((extract(epoch from ft.freetimecarga)/3600)::numeric,1)::float8    AS ft_carga_h,
       round((extract(epoch from ft.freetimedescarga)/3600)::numeric,1)::float8 AS ft_descarga_h,
       coalesce(nullif(trim(ft.observacao),''),'(genérico)')                    AS mercadoria
FROM sulista.sac_freetimecliente ft
JOIN agrupamentocliente_cnpjcpfcodigo acc ON acc.codigo = ft.agrupamentocliente
WHERE ft.ativoinativo = 1
  AND acc.vinculo = 1
  AND strpos(cast(acc.cnpjcpfcodigo AS text), %(raiz)s) = 1
ORDER BY 2, 3
"""


def _freetime(raiz: str) -> dict:
    """O freetime contratado, como FAIXA — nunca como um número só.

    O CONTRATO DISTINGUE POR MERCADORIA e a ocorrência SAC não diz qual
    mercadoria era. Medido em 05/09/2026: a Maxion tem QUATRO linhas ativas,
    todas com o mesmo `dtinicio` (01/08/2024) — 3h de descarga na linha
    genérica e 6,5h nas de ESCADAS, RODAS e CONJUNTOS. `DISTINCT ON` ordenado
    por `dtinicio` desempata ao ACASO entre elas: rodada a rodada, o mesmo mês
    daria 38,6% ou 70% de aderência, sem nada no código mudar.

    Então não se escolhe. Devolve-se o PISO (menor freetime) e o TETO (maior),
    e a tela mostra três faixas: dentro do piso é aderente sob qualquer
    contrato; acima do teto é excedente sob qualquer contrato; no meio a
    resposta depende de um dado que não temos, e a tela DIZ isso em vez de
    chutar para um dos lados. Num painel que o CLIENTE lê, chutar para o lado
    que nos favorece é pior ainda: ele fecha conta em cima.

    (A mesma ambiguidade existe hoje no `SAC_FT_REP` de `api/queries.py`, que
    alimenta a tela `sac` — lá o desempate arbitrário está de pé. Não mexo
    nele daqui: é tela de outra frente e a correção merece a própria entrega.)
    """
    linhas = db.query(FREETIME_SQL_TODAS, {"raiz": raiz})
    cargas = [r["ft_carga_h"] for r in linhas if r["ft_carga_h"]]
    descs = [r["ft_descarga_h"] for r in linhas if r["ft_descarga_h"]]
    return {
        "contratos": len(linhas),
        "carga_piso": min(cargas) if cargas else None,
        "carga_teto": max(cargas) if cargas else None,
        "descarga_piso": min(descs) if descs else None,
        "descarga_teto": max(descs) if descs else None,
        # A tela precisa saber se a faixa é uma faixa ou um ponto: com um
        # contrato só não há zona cinzenta, e mostrar uma faixa de largura
        # zero como se fosse dúvida seria inventar uma incerteza que não há.
        "ambiguo": bool(cargas and descs and (min(descs) != max(descs)
                                              or min(cargas) != max(cargas))),
    }


def _faixas(valores: list[float], piso: float | None, teto: float | None) -> dict:
    """Reparte as permanências nas três faixas do freetime."""
    n = len(valores)
    if not n or piso is None or teto is None:
        return {"n": n, "dentro": None, "zona": None, "fora": None}
    dentro = sum(1 for h in valores if h <= piso)
    fora = sum(1 for h in valores if h > teto)
    return {"n": n, "dentro": dentro, "zona": n - dentro - fora, "fora": fora,
            "dentro_pct": round(100.0 * dentro / n, 1),
            "zona_pct": round(100.0 * (n - dentro - fora) / n, 1),
            "fora_pct": round(100.0 * fora / n, 1)}


def _mediana(v: list[float]) -> float | None:
    if not v:
        return None
    s = sorted(v)
    m = len(s) // 2
    return round(s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2, 2)


# ============================================================================
# 3) HISTÓRICO — volume por mês e as rotas que a operação de fato usa.
# ============================================================================
# O intervalo de meses é GERADO no Python a partir da janela pedida, não
# colhido do `GROUP BY`: mês sem carga não volta do banco e a série emendaria
# junho em agosto como se julho não existisse. Mês sem coleta vai rotulado,
# com barra cinza e linha ABERTA na tela.
HIST_SQL = """
SELECT to_char(c.dtemissao,'YYYY-MM')           AS mes,
       upper(trim(coalesce(c.origem,'')))       AS origem,
       coalesce(c.uforigem,'')                  AS uf_origem,
       upper(trim(coalesce(c.destino,'')))      AS destino,
       coalesce(c.ufdestino,'')                 AS uf_destino,
       count(*)                                 AS cargas
FROM coleta c
WHERE c.dtcancelamento IS NULL
  AND c.dtemissao >= %(desde)s
  AND """ + FILTRO_CLIENTE + """
GROUP BY 1,2,3,4,5
"""


@cached(ttl=120, velha_ate=7200)
def get_agora(raiz: str, dias: int = 45) -> dict:
    """As cargas no ar agora, por marco. Fonte: SAC + coleta.

    `velha_ate` de 2h: o ERP é réplica de produção de terceiro e já degradou
    uma manhã inteira. Uma leitura de 40 minutos atrás, DITA na tela, é
    honesta e serve; portal em branco na cara do cliente não é nenhum dos
    dois. A tarja é obrigatória — número velho servido calado é pior que tela
    vazia, porque ninguém desconfia dele.
    """
    linhas = db.query(AGORA_SQL, {"raiz": raiz, "dias": int(dias)})
    cargas, concluidas = [], 0
    for r in linhas:
        cod, rotulo, quando = _marco(r)
        if not cod:
            continue
        if not em_curso(r):
            concluidas += 1
            continue
        # Lista EXPLÍCITA, campo a campo — nunca `dict(r)`. É o padrão que o
        # rastreio público provou: cópia do registro do ERP faz de uma coluna
        # nova do fornecedor um vazamento no dia em que alguém a criar, sem
        # ninguém rever nada. Aqui há login, mas o mecanismo do erro é o mesmo.
        cargas.append({
            "coleta": r["coleta"], "emissao": r["emissao"],
            "origem": r["origem"], "uf_origem": r["uf_origem"],
            "destino": r["destino"], "uf_destino": r["uf_destino"],
            "placa": r["placa"],
            "marco": rotulo, "marco_cod": cod, "marco_em": quando,
        })
    return {
        "cargas": cargas,
        "em_curso": len(cargas),
        "concluidas_na_janela": concluidas,
        "janela_dias": int(dias),
        "fonte": ("ERP AVA · ocorrências SAC (394-401) + coleta · "
                  f"janela de {int(dias)} dias · leitura"),
    }


@cached(ttl=180, velha_ate=7200)
def get_permanencia(raiz: str, dt_de: str, dt_ate: str) -> dict:
    """Permanência em carregamento e descarga, contra o freetime contratado."""
    linhas = db.query(PERM_SQL, {"raiz": raiz, "dt_de": dt_de, "dt_ate": dt_ate})
    ft = _freetime(raiz)

    def colher(campo: str) -> tuple[list[float], int]:
        bons, fora = [], 0
        for r in linhas:
            h = r[campo]
            if h is None:
                continue
            # Régua física: acima de 24h é pareamento atravessando dias, não
            # veículo parado. Fora dela é n/d CONTADO — nunca zero, que
            # entraria na mediana puxando-a para baixo, e nunca descartado em
            # silêncio, que esconderia um problema de coleta de evento.
            if 0 < h <= CAP_H:
                bons.append(float(h))
            elif h > CAP_H:
                fora += 1
        return bons, fora

    h_carga, fora_carga = colher("h_carga")
    h_desc, fora_desc = colher("h_descarga")
    return {
        "carga": {"mediana_h": _mediana(h_carga),
                  **_faixas(h_carga, ft["carga_piso"], ft["carga_teto"]),
                  "fora_da_regua": fora_carga},
        "descarga": {"mediana_h": _mediana(h_desc),
                     **_faixas(h_desc, ft["descarga_piso"], ft["descarga_teto"]),
                     "fora_da_regua": fora_desc},
        "freetime": ft,
        "cargas_no_periodo": len(linhas),
        "periodo": {"de": dt_de, "ate": dt_ate},
        "fonte": ("ERP AVA · ocorrências SAC 394→395 (carga) e 396→397 "
                  "(descarga) + sulista.sac_freetimecliente · "
                  f"permanências acima de {CAP_H:.0f}h tratadas como n/d · leitura"),
    }


@cached(ttl=600, velha_ate=7200)
def get_historico(raiz: str, meses: int = 12) -> dict:
    """Volume por mês e as rotas usadas, na janela pedida."""
    from datetime import date

    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    # A janela é ancorada no mês corrente e ANDA PARA TRÁS mês a mês, sem
    # aritmética de 30 dias: `hoje - 365` cortaria o mês mais antigo pela
    # metade e a primeira barra da série sairia menor por artefato de janela,
    # não por queda de volume.
    chaves = []
    for _ in range(int(meses)):
        chaves.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    chaves.reverse()
    desde = f"{chaves[0]}-01"

    linhas = db.query(HIST_SQL, {"raiz": raiz, "desde": desde})
    por_mes = {k: 0 for k in chaves}          # o intervalo é GERADO, não colhido
    rotas: dict[str, int] = {}
    for r in linhas:
        if r["mes"] in por_mes:
            por_mes[r["mes"]] += r["cargas"]
        rot = (f'{r["origem"]}/{r["uf_origem"]} → {r["destino"]}/{r["uf_destino"]}')
        rotas[rot] = rotas.get(rot, 0) + r["cargas"]

    top = sorted(rotas.items(), key=lambda kv: kv[1], reverse=True)[:10]
    total = sum(rotas.values())
    return {
        "meses": [{"mes": k, "cargas": por_mes[k],
                   # O mês corrente é PARCIAL e a tela hachura a barra: sem
                   # isso a última coluna despenca todo dia 1º e alguém lê
                   # queda de demanda onde só há mês pela metade.
                   "parcial": k == chaves[-1]} for k in chaves],
        "rotas": [{"rota": r, "cargas": n,
                   "pct": round(100.0 * n / total, 1) if total else None}
                  for r, n in top],
        # Top-N leva CONTADOR, senão vira total falso: "10 de 25 rotas ·
        # 6.812 das 7.352 cargas" é o que impede o leitor de somar a lista e
        # achar que somou a operação.
        "rotas_mostradas": len(top),
        "rotas_total": len(rotas),
        "cargas_nas_rotas_mostradas": sum(n for _, n in top),
        "cargas_total": total,
        "fonte": f"ERP AVA · coleta · {int(meses)} meses até hoje · leitura",
    }
