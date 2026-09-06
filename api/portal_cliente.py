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
caminho óbvio: em 05/09/2026 o agrupamento de um cliente de quatro plantas
tinha TRÊS dos QUATRO CNPJs — faltava justamente uma delas. Escopar por ele
entregaria um portal que esconde uma planta inteira do cliente sem erro
nenhum, e o sintoma seria "faltam cargas" meses depois. O agrupamento é
cadastro mantido à mão; a raiz do CNPJ é o próprio documento. Para DECIDIR
QUEM VÊ O QUÊ vale o documento. (O agrupamento continua valendo para o
freetime contratado, que é um contrato comercial e mora nele mesmo.)

DOIS LEITORES, UM DELES TRANCADO
================================
A tela serve o CLIENTE e serve a CASA, e a diferença entre eles não é o
perfil — é o VÍNCULO:

- **usuário com vínculo** (gente do cliente) enxerga a operação dele e só ela.
  Ele não escolhe: se mandar um cliente na requisição, o servidor IGNORA.
  Sem isso a tela deixaria de ser um portal e viraria um buscador da operação
  alheia, com o RBAC achando tudo normal — a tela é a mesma, ele tem acesso.
- **usuário sem vínculo** (gente da casa) ESCOLHE de quem quer ver. Quem lhe
  deu a tela no perfil deu isso de propósito: é a mesma decisão que dá a tela
  `com` ou `clif`, que já listam a carteira inteira para quem as tem.

A ordem importa e está em `alvo()`: o vínculo é consultado PRIMEIRO, e só a
sua ausência abre a escolha. Inverter isso — aceitar o parâmetro e cair no
vínculo quando ele falta — seria a mesma função com a trava do lado errado.

POSIÇÃO NO MAPA: por que aqui pode e no rastreio público não
============================================================
`api/rastreio/` recusa placa e coordenada exata, e a razão está escrita lá:
uma página ABERTA que aceita placa e devolve onde o caminhão está agora é
ferramenta de roubo de carga — quem quiser interceptar não precisa de mais
nada além da placa, que está pintada na porta.

Aqui a diferença não é de grau, é de natureza: há login, o vínculo diz de quem
é a carga, e o mapa só recebe as placas das cargas EM CURSO daquele cliente —
nunca a frota, nunca outro cliente. É o mesmo raciocínio que já libera a placa
nesta tela. Quem vê é a operação (ou o dono da carga), não um desconhecido que
digitou um número.

O que o mapa NÃO faz, e não deve passar a fazer: aceitar placa como ENTRADA.
Escolher um caminhão e perguntar onde ele está é a função que o rastreio
recusou; mostrar onde estão as cargas que já são suas é outra coisa.

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
**Entrega no prazo.** Medido em 05/09/2026 sobre 12 meses de CT-es de um
cliente de linha: `dtprevisaoentrega` é IGUAL à data de emissão em 80,3% deles — é
default do ERP, não prazo, exatamente como as OCs de suprimentos. Sobre a
previsão crua sai "91,2% no prazo", número que parece ótimo e não significa
nada. Restringindo aos CT-es com prazo de verdade (previsão > emissão) E com
entrega registrada, a régua cobre **8,7% da operação**.
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
from datetime import datetime, timedelta

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

    Admin não é exceção: ser admin responde "que telas", não "de quem é a
    operação". Isto aqui responde uma coisa só — "esta sessão está TRANCADA em
    algum cliente?" — e para gente da casa a resposta é não, o que abre a
    escolha em `alvo()` em vez de recusar. Quem decide se alguém da casa entra
    é o RBAC da tela, como em qualquer outra.
    """
    raiz = ((sess or {}).get("cliente_cnpj_raiz") or "").strip()
    if not RE_RAIZ.match(raiz):
        raise SemEscopo("sessão sem vínculo de cliente")
    return raiz


class PrecisaEscolher(Exception):
    """Gente da casa abriu a tela sem dizer de quem. Não é erro: é a tela
    esperando a escolha, e a rota responde 200 com a lista de clientes."""


def alvo(sess: dict | None, pedida: str | None) -> tuple[str, bool]:
    """De quem é a operação que ESTA requisição vai ler. Devolve (raiz, travado).

    A ORDEM É A SEGURANÇA. O vínculo vem primeiro e vence sempre; `pedida` só
    é olhado quando não há vínculo nenhum. Escrito ao contrário — usar
    `pedida` e cair no vínculo quando ela falta — a mesma função deixaria um
    usuário de cliente ler outro cliente só mandando o parâmetro, e nada no
    RBAC acharia estranho.

    `travado=True` diz à tela que não há o que escolher; ela esconde o seletor
    em vez de oferecer uma escolha que o servidor vai ignorar.
    """
    try:
        return escopo(sess), True
    except SemEscopo:
        pass
    escolha = (pedida or "").strip()
    if RE_RAIZ.match(escolha):
        return escolha, False
    raise PrecisaEscolher("nenhum cliente escolhido")


# O NOME de UMA raiz. Consulta escopada: recebe a raiz e devolve o nome dela,
# nunca uma lista. Existe porque um painel de cliente que nao diz QUAL cliente
# e o jeito de alguem na sala de operacao ler a conta errada e agir em cima --
# e numa TV, onde ninguem vai conferir o filtro, isso e pior.
NOME_SQL = """
SELECT coalesce(nullif(trim(cd.razaosocial),''),
                nullif(trim(cd.nomefantasia),''), '') AS nome
FROM cadastro cd
WHERE strpos(cast(cd.codigo AS text), %(raiz)s) = 1
ORDER BY length(cast(cd.codigo AS text)), cd.codigo
LIMIT 1
"""


@cached(ttl=3600, velha_ate=86400)
def nome_do_cliente(raiz: str) -> str:
    """Razao social da raiz, ou vazio. Nunca levanta: e rotulo, nao dado.

    TTL longo e `velha_ate` de um dia porque razao social nao muda de manha
    para tarde -- e porque a alternativa, o painel perder o nome do cliente
    num tropeco do ERP, deixaria a parede mostrando numeros sem dono.
    """
    try:
        linhas = db.query(NOME_SQL, {"raiz": raiz})
        return (linhas[0]["nome"] if linhas else "") or ""
    except Exception:  # noqa: BLE001
        log.warning("nome do cliente falhou para a raiz pedida")
        return ""


# QUEM APARECE NA LISTA de quem escolhe: cliente com carga no período, do mais
# volumoso para o menos. Não é a carteira comercial (isso é a tela `com`) — é
# quem a operação de fato moveu, que é a pergunta desta tela. A raiz sai
# agregada: as quatro filiais da Iochpe-Maxion viram UMA linha, senão quem
# escolhe teria de adivinhar qual planta traz a operação inteira.
CLIENTES_SQL = """
SELECT substr(cast(c.cnpjcpfcodigopagadorfrete AS text), 1, 8) AS raiz,
       -- RAZAO SOCIAL antes do fantasia: a raiz e a EMPRESA, e o fantasia do
       -- ERP traz a filial no nome ("IOCHPE MAXION - RESENDE/RJ"). Agregado
       -- por raiz, o `max()` escolheria uma planta ao acaso para rotular as
       -- e quem escolhe leria o nome de UMA planta achando que perdeu as outras.
       max(coalesce(nullif(trim(cd.razaosocial),''),
                    nullif(trim(cd.nomefantasia),''), '(sem nome)')) AS nome,
       count(*) AS cargas
FROM coleta c
LEFT JOIN cadastro cd ON cd.codigo = c.cnpjcpfcodigopagadorfrete
WHERE c.dtcancelamento IS NULL
  AND c.dtemissao >= current_date - %(dias)s
  AND length(cast(c.cnpjcpfcodigopagadorfrete AS text)) >= 8
GROUP BY 1
HAVING count(*) > 0
ORDER BY 3 DESC
"""


@cached(ttl=600, velha_ate=7200)
def get_clientes(dias: int = 365) -> dict:
    """Os clientes que a operação moveu, para quem escolhe.

    NÃO leva raiz nenhuma na assinatura de propósito: é a única função deste
    módulo que não é escopada, e ela só é chamada por quem NÃO tem vínculo.
    Deixá-la sem o parâmetro é o que impede alguém de, mais adiante, "reusar"
    ela num caminho de cliente sem perceber.
    """
    linhas = db.query(CLIENTES_SQL, {"dias": int(dias)})
    return {
        "clientes": [{"raiz": r["raiz"], "nome": r["nome"], "cargas": r["cargas"]}
                     for r in linhas],
        "janela_dias": int(dias),
        "fonte": f"Sistema de gestão · pagador do frete · {int(dias)} dias · leitura",
    }


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
# A ESPINHA É A COLETA, e os apontamentos são DETALHE dela.
#
# A primeira versão partia de `coleta_ocorrencia` e dava JOIN na coleta: carga
# sem apontamento simplesmente não existia para o painel. Medido em 05/09/2026,
# e é grave: naquele dia a Maxion tinha 5 coletas e ZERO eventos SAC — uma
# delas com manifesto ABERTO, isto é, viajando naquele instante. A operação do
# DIA inteira estava invisível, e o painel não tinha como acusar, porque para
# ele aquelas cargas não existiam.
#
# O apontamento SAC chega com atraso (~1 dia) e cobre 86,7%; a coleta existe no
# instante em que é emitida. Partir do que existe e pendurar o que foi apontado
# é a ordem certa — e a carga sem apontamento aparece dizendo "sem registro",
# que é honesto e visível, em vez de sumir.
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
  GROUP BY 1,2,3,4,5,6,7),
-- O MANIFESTO, agregado de UMA vez em vez de consultado por carga.
--
-- A primeira versao fazia isto num LATERAL correlacionado: 9,45 s numa janela
-- de 45 dias, porque a cadeia de tres tabelas rodava UMA VEZ POR COLETA. Num
-- painel de parede que recarrega a cada 60 s isso nao serve. Agregado assim e
-- uma passada so sobre os MDF-es da janela, e a coleta faz um LEFT JOIN.
--
-- A JANELA DO MDF-e e MAIOR que a das coletas (+30 dias) de proposito: o
-- manifesto que fecha uma carga do comeco da janela pode ter sido emitido
-- antes dela. Cortar os dois no mesmo dia deixaria carga velha eternamente
-- "em curso" na BORDA do periodo -- defeito que so aparece nas cargas mais
-- antigas da janela, e que ninguem procuraria ali.
mdf AS (
  SELECT cc.grupo, cc.empresa,
         cc.filialdocumento              AS filial,
         cc.unidadedocumento             AS unidade,
         cc.diferenciadornumerodocumento AS dif,
         cc.seriedocumento               AS serie,
         cc.numerodocumento              AS numero,
         max(CASE WHEN me.situacaomdfe = 7 THEN 1 ELSE 0 END) AS encerrado,
         max(me.dtencerramento)                               AS encerrado_em
  FROM manifestoeletronico me
  JOIN manifestoeletronico_composicao mec
    ON mec.grupo=me.grupo AND mec.empresa=me.empresa AND mec.filial=me.filial
   AND mec.unidade=me.unidade AND mec.diferenciadornumero=me.diferenciadornumero
   AND mec.serie=me.serie AND mec.numero=me.numero
  JOIN conhecimento_composicao cc
    ON cc.grupo=mec.grupo AND cc.empresa=mec.empresa
   AND cc.filial=mec.filialdocumento AND cc.unidade=mec.unidadedocumento
   AND cc.diferenciadornumero=mec.diferenciadornumerodocumento
   AND cc.serie=mec.seriedocumento AND cc.numero=mec.numerodocumento
  WHERE me.dtemissao >= current_date - (%(dias)s + 30)
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
       to_char(ev.vf,'YYYY-MM-DD HH24:MI') AS t_finalizada,
       coalesce(mdf.encerrado, 0)                     AS mdfe_encerrado,
       to_char(mdf.encerrado_em,'YYYY-MM-DD HH24:MI') AS mdfe_em
FROM coleta c
LEFT JOIN ev ON ev.grupo=c.grupo AND ev.empresa=c.empresa AND ev.filial=c.filial
  AND ev.unidade=c.unidade AND ev.diferenciadornumero=c.diferenciadornumero
  AND ev.serie=c.serie AND ev.numero=c.numero
-- O CT-e do cliente liga a coleta ao manifesto. A CADEIA e
-- coleta -> conhecimento_composicao -> manifestoeletronico_composicao.
-- A tabela `manifesto` (a nao-eletronica) NAO entra: o `manifestoeletronico`
-- nao se liga a ela por chave nenhuma que exista -- medido em 05/09/2026,
-- `filialdocumentoorigem` e NULL nos 3.184 MDF-es de 30 dias, e o
-- `numerodocumentoorigem` nao casa com `manifesto.numero` (0 de 3.184). Ja o
-- `manifestoeletronico_composicao` casa com `conhecimento` em 5.962 de 5.962.
-- Quem tentar "melhorar" isto passando pelo manifesto vai achar zero linhas
-- e concluir que o cliente nao tem viagem.
LEFT JOIN mdf ON mdf.grupo=c.grupo AND mdf.empresa=c.empresa
  AND mdf.filial=c.filial AND mdf.unidade=c.unidade
  AND mdf.dif=c.diferenciadornumero AND mdf.serie=c.serie
  AND mdf.numero=c.numero
WHERE c.dtcancelamento IS NULL
  AND c.dtemissao >= current_date - %(dias)s
  AND """ + FILTRO_CLIENTE + """
ORDER BY coalesce(mdf.encerrado_em, ev.vf, ev.fd, ev.cd, ev.ev, ev.sc, ev.cc,
                  c.dtemissao) DESC
"""


#: Quanto tempo a rota leva, pelo NOSSO historico. Chave: "ORIGEM/UF|DESTINO/UF".
#:
#: TRES FONTES DE TEMPO convivem nesta casa e NUNCA se fundem num numero so: o
#: ETA que o programador digitou no ERP (erra mais de 2h em metade dos casos,
#: medido), o da TomTom (transito de agora, so viagem ativa, tela Torre) e o
#: historico proprio. Aqui e o TERCEIRO, e o rotulo diz isso -- "estimativa
#: pelo historico", nunca "previsao" seca, que numa parede vira promessa.
#:
#: A mediana de deslocamento e PORTA A PORTA e ja inclui fila e pernoite: nao
#: e o tempo de rodar, e o tempo que o veiculo fica preso, que e o que quem
#: espera a carga quer saber.
def _eta_por_rota() -> dict:
    """Mediana de deslocamento por rota, do modulo de ciclos. Cache de 1 h la.

    Rota com menos de `N_MIN` viagens NAO entra: e a regra do proprio modulo
    ("rota com menos de 10 amostras mostra n/d, nunca numero"), e reimplementa-la
    com outro piso aqui criaria duas reguas para a mesma pergunta.
    """
    try:
        from . import programacao_ciclos as _cic
        return {
            (r["ori"] or "") + "|" + (r["dst"] or ""): (r["desloc_med_h"], r["n"])
            for r in _cic.get_ciclos().get("rotas", [])
            if r.get("desloc_med_h") and (r.get("n") or 0) >= _cic.N_MIN
        }
    except Exception:  # noqa: BLE001
        # A previsao e ACRESCIMO: sem ela a carga continua na tela dizendo onde
        # esta. Derrubar o painel por causa do enfeite seria trocar o dado pelo
        # adorno.
        log.warning("ciclos indisponivel: painel sai sem previsao de chegada")
        return {}


def _eta(r: dict, cod: int, rotas: dict) -> dict:
    """Previsão de chegada da carga, ou vazio. Calculada da LINHA CRUA.

    Mora aqui, e não no laço que monta o payload, porque precisa dos horários
    que o payload NÃO leva: a lista de campos da carga é explícita de propósito
    e `t_saiu_carga` não está nela. A primeira versão tentou ler o horário do
    payload, achou `None` em tudo e devolveu previsão nenhuma — sem erro. Foi
    o próprio guard da lista explícita que obrigou a notar.

    A CONTAGEM COMEÇA NA SAÍDA DO CARREGAMENTO, que é onde o histórico também
    começa (`programacaoembarque` conta de `dtsaida` a `dtchegada`). Contar do
    "em viagem" daria uma previsão mais curta para a mesma estrada, e duas
    cargas lado a lado chegariam em horas diferentes conforme qual evento a
    operação apontou.
    """
    vazio = {"eta": None, "eta_amostras": None}
    if cod not in (395, 400):
        return vazio
    chave = ((r.get("origem") or "") + "/" + (r.get("uf_origem") or "") + "|"
             + (r.get("destino") or "") + "/" + (r.get("uf_destino") or ""))
    med = rotas.get(chave)
    base = r.get("t_saiu_carga") or r.get("t_viagem")
    if not med or not base:
        return vazio
    try:
        q = datetime.strptime(base, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return vazio
    return {"eta": (q + timedelta(hours=float(med[0]))).strftime("%Y-%m-%d %H:%M"),
            "eta_amostras": med[1]}


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
    return 0, "Sem apontamento", ""


#: QUEM FECHA A VIAGEM É O MANIFESTO; o evento operacional é a reserva.
#:
#: A primeira versão fechava pelo evento SAC 397 (fim de descarga), depois de
#: descartar o 401 (viagem finalizada), que aparecia UMA vez em 738 cargas.
#: Quem opera apontou que o manifesto seria mais preciso, e a medição deu razão
#: a ele — 45 dias de uma operação de linha:
#:
#:     com fim de descarga (397) ....  671   86,7%
#:     com viagem finalizada (401) ..    1    0,1%
#:     com MDF-e ENCERRADO .......... 764   98,7%
#:
#: E as discordâncias são de MÃO ÚNICA: 93 cargas sem 397 já tinham o manifesto
#: encerrado — o portal dizia "a caminho" para carga que já chegou — e NENHUMA
#: com 397 tinha manifesto aberto. O MDF-e encerrado é superconjunto estrito do
#: apontamento: fecha tudo que o 397 fecha, e mais 93.
#:
#: Faz sentido que seja assim, e é o que sustenta a regra: encerrar o MDF-e é
#: obrigação FISCAL com prazo, que a SEFAZ cobra; apontar fim de descarga é
#: rotina operacional que ninguém multa. Entre um registro que alguém é
#: OBRIGADO a fazer e outro que seria bom fazer, o estado vem do primeiro.
#:
#: O 397 fica como RESERVA para o 1,2% sem manifesto — descartá-lo deixaria
#: essas cargas em curso para sempre, que é o defeito que esta regra existe
#: para não ter.
TERMINAL = 397


def em_curso(r: dict) -> bool:
    """A carga ainda está no ar?

    O MANIFESTO MANDA. Encerrado, a viagem acabou — não importa o que a
    operação apontou ou deixou de apontar. Só na ausência de manifesto é que o
    evento de fim de descarga decide.

    CARGA SEM APONTAMENTO NENHUM CONTA COMO EM CURSO, e essa é a inversão que
    mais muda o painel: antes ela nem aparecia. A coleta existe e o manifesto
    não fechou — isso é uma carga no ar cujo trajeto ninguém apontou ainda, não
    uma carga que não existe. Some da tela quando o manifesto encerrar, que é
    o registro que alguém é obrigado a fazer.
    """
    if r.get("mdfe_encerrado"):
        return False
    cod, _, _ = _marco(r)
    if cod == 0:
        return True
    return ORDEM.index(cod) < ORDEM.index(TERMINAL)


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
# `DISTINCT ON` porque a tabela tem histórico: um cliente pode ter VÁRIAS
# linhas ativas para a mesma filial ao mesmo tempo (uma por tipo de
# mercadoria). Join direto multiplicaria cada coleta por todas elas e o total
# sairia N× maior — plausível, e errado. É a regra de vigência da casa.
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
    mercadoria era. Um cliente pode ter várias linhas ativas ao mesmo tempo,
    TODAS com o mesmo `dtinicio` — uma genérica e outras com tolerância maior,
    por tipo de carga. `DISTINCT ON` ordenado por `dtinicio` desempata ao ACASO
    entre elas: rodada a rodada, o mesmo mês daria perto de 39% ou perto de
    70% de aderência, sem nada no código mudar.

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


@cached(ttl=120)
def get_agora(raiz: str, dias: int = 45) -> dict:
    """As cargas no ar agora. Fonte: coleta + SAC + MDF-e + posição.

    SEM REDE DE LEITURA VELHA, de propósito, e é a única das quatro funções
    deste módulo que não tem. O critério é a RESOLUÇÃO DA PRÓPRIA TELA: as
    outras publicam mês ou dia, e uma leitura de duas horas atrás não muda
    nada do que está ali. Esta publica ONDE A CARGA ESTÁ AGORA, com posição
    de veículo ao lado — e serve um painel de PAREDE, onde ninguém clica para
    conferir a procedência.

    Servir posição de duas horas atrás aqui não é ser resiliente, é mentir com
    tarja: a decisão que alguém tomar olhando o mural já foi tomada quando ele
    lê o aviso. Tela vazia com erro é a resposta honesta para esta.
    """
    linhas = db.query(AGORA_SQL, {"raiz": raiz, "dias": int(dias)})
    rotas = _eta_por_rota() if linhas else {}
    cargas, concluidas = [], 0
    for r in linhas:
        cod, rotulo, quando = _marco(r)
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
            **_eta(r, cod, rotas),
        })
    # CARGA SEM NENHUM APONTAMENTO NÃO VAI PARA O PAINEL DO CLIENTE, por
    # decisão de quem opera (06/09/2026). Ela EXISTE — a coleta foi emitida e o
    # manifesto não fechou — mas o que o portal teria a dizer sobre ela é
    # "não sabemos por onde anda", e isso é processo nosso, não informação do
    # cliente. Ela volta à tela no instante em que a operação apontar o
    # primeiro marco.
    #
    # O QUE ISSO CUSTA, e fica dito: a carga emitida hoje some do painel até o
    # primeiro apontamento, que chega com cerca de um dia de atraso. O número
    # `sem_apontamento` continua saindo na resposta para quem precise medir
    # esse buraco por dentro — some da TELA, não da conta.
    sem_apontamento = [c for c in cargas if not c["marco_cod"]]
    cargas = [c for c in cargas if c["marco_cod"]]
    # POSIÇÃO das cargas que ainda estão no ar. Só as placas DESTAS cargas —
    # `atuais()` devolve a frota inteira (278 placas em 05/09/2026) e o que
    # sai daqui é o recorte do cliente. Fatiar depois de ler é de propósito:
    # a fonte é uma leitura só, barata (0,4 s) e já compartilhada com a Torre.
    pos, resumo_pos = {}, {"com_posicao": 0, "frescas": 0, "fontes": {}}
    _POS_FRESCA_MIN = 120        # o teto de `api/posicoes`, relido no try
    placas = {c["placa"] for c in cargas if c["placa"]}
    if placas:
        try:
            from . import posicoes as _pos
            _POS_FRESCA_MIN = _pos.FRESCA_MIN
            todas = _pos.atuais()["posicoes"]
            for pl in placas:
                r = todas.get(pl)
                if not r or r.get("lat") is None or r.get("lon") is None:
                    continue
                pos[pl] = {
                    "lat": float(r["lat"]), "lon": float(r["lon"]),
                    "velocidade": r.get("velocidade"),
                    # TODA POSIÇÃO DIZ DE ONDE VEIO E QUE IDADE TEM. Mapa que
                    # mistura fontes sem dizer qual é qual transforma "a Gobrax
                    # está fora" em "a frota sumiu".
                    "fonte": r.get("fonte"),
                    "idade_min": r.get("idade_min"),
                    "velha": (r.get("idade_min") is None
                              or r["idade_min"] > _POS_FRESCA_MIN),
                }
                resumo_pos["com_posicao"] += 1
                if not pos[pl]["velha"]:
                    resumo_pos["frescas"] += 1
                f = r.get("fonte") or "?"
                resumo_pos["fontes"][f] = resumo_pos["fontes"].get(f, 0) + 1
        except Exception:  # noqa: BLE001
            # Mapa é acréscimo, não o dado: se a posição falhar, a tela e a TV
            # continuam com as cargas e o mapa DIZ que está sem posição.
            log.warning("posições do portal falharam: mapa sai vazio")

    # PREVISAO DE CHEGADA, so para quem ja saiu e ainda nao chegou. Antes de
    # sair nao ha de onde contar; depois de chegar o numero nao serve mais.
    for c in cargas:
        c["pos"] = pos.get(c["placa"]) if c["placa"] else None

    return {
        "cargas": cargas,
        "em_curso": len(cargas),
        "sem_apontamento": len(sem_apontamento),
        "concluidas_na_janela": concluidas,
        "janela_dias": int(dias),
        # A COBERTURA do mapa vai junto: "12 de 66 com posição" é o que impede
        # alguém de olhar seis pontos na tela e concluir que só há seis cargas.
        # `veiculos`, e nao "cargas com placa": sao placas DISTINTAS. As 66
        # cargas em curso de 05/09/2026 viajavam em 33 veiculos (um caminhao
        # leva varios CT-es), e chamar isso de carga faria a cobertura do mapa
        # parecer metade do que e.
        "posicao": {**resumo_pos, "veiculos": len(placas),
                    "fresca_ate_min": _POS_FRESCA_MIN},
        # A FONTE NÃO NOMEIA FORNECEDOR. Este payload alimenta uma tela e uma
        # parede que o CLIENTE lê, e o nome de quem nos vende rastreamento é
        # assunto nosso — para o cliente o que importa é a idade da leitura,
        # que continua saindo. A procedência por fornecedor segue no campo
        # `fonte` de cada posição, para a Saúde e o diagnóstico interno.
        "fonte": ("Sistema de gestão · coleta, apontamentos de operação e "
                  "encerramento do manifesto · "
                  f"janela de {int(dias)} dias · posição do rastreamento · leitura"),
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
        "fonte": ("Sistema de gestão · apontamentos de chegada e saída no "
                  "carregamento e na descarga + freetime do contrato · "
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
        "fonte": f"Sistema de gestão · {int(meses)} meses até hoje · leitura",
    }
