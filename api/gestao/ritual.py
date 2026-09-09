# -*- coding: utf-8 -*-
"""O Ritual Semanal de Gestão — "Execução & Resultados".

Trinta minutos por semana para enxergar o número, atacar o desvio e sair com
compromisso claro. Quatro gerências: Comercial, Operação, Manutenção e RH.

POR QUE ESTE MÓDULO EXISTE
==========================

A reunião de resultados produz um plano de ação. O que faltava era a semana
seguinte: alguém abrir o plano, perguntar o que andou, e registrar o que fica
combinado até a próxima. Sem isso o plano vira documento, e o acompanhamento
vira cada gerente trazendo o próprio PowerPoint com os próprios números — que é
onde a discussão deixa de ser sobre o desvio e passa a ser sobre de onde veio o
número.

AS TRÊS DECISÕES QUE MOLDAM TUDO
================================

**1. O realizado vem da fonte, não do gerente, sempre que a casa já mede.**
`FONTES` é o registro de números que o CÓRTEX já calcula. Indicador que aponta
para uma fonte NÃO tem campo de digitação: o valor chega do mesmo lugar que a
tela do assunto mostra, e o gerente gasta o tempo dele explicando o desvio.
Indicador sem fonte (`manual`) continua existindo — a empresa mede coisas que o
sistema ainda não mede, e recusá-las deixaria uma gerência inteira de fora da
primeira semana. A tela DIZ qual é qual: número automático e número digitado
não têm a mesma qualidade, e apresentá-los iguais é que faz um herdar a
confiança do outro.

**2. O painel se preenche ANTES, e a reunião decide.**
Por isso o módulo publica `pendencias()`: quem ainda não preencheu é informação
de gestão por si só, e aparece na tela antes de a reunião começar. O prazo NÃO
é trava — preencher depois é aceito e fica marcado como atrasado. Travar
transformaria "esqueci" em "não tenho o número na sala", que é pior para todos.

**3. Compromisso não é conceito novo: é uma `ges_acoes`.**
Com prazo na próxima reunião. Uma tabela paralela de compromissos faria o plano
de ação da reunião de resultados e o da semanal viverem em dois lugares — o
mesmo PowerPoint paralelo que este ritual mata, só que dentro do banco, onde
ninguém enxerga a duplicidade.

QUEM PODE PREENCHER, E POR QUE NÃO É POR DONO
---------------------------------------------

Quem tem a tela preenche qualquer gerência, e todo apontamento grava
`preenchido_por`. A alternativa — só o gestor da gerência escreve na linha dela
— exigiria autorização POR LINHA, que não existe nesta casa (a unidade de RBAC
é a tela), e quebraria o caso real de alguém preencher pelo colega que está na
estrada. A escolha é atribuição visível em vez de bloqueio: a tela mostra quem
preencheu cada linha, e isso resolve a pergunta de responsabilidade sem inventar
um segundo modelo de permissão.

A ROTA NÃO FICA SOB /api/gestao, E ISSO É DELIBERADO
----------------------------------------------------
`/api/gestao/*` é ADMIN, checado no middleware antes do mapeamento de telas
(`api/auth.py`). O ritual é preenchido por GERENTE, que não é administrador —
sob aquele prefixo a tela nasceria inútil para exatamente o público dela. As
rotas vivem em `/api/ritual/*`, com RBAC normal pela tela `gesrit`.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from api import pglocal
from api.gestao import comum

log = logging.getLogger("cortex.ritual")

STATUS = ("verde", "amarelo", "vermelho")

#: Status que OBRIGAM ação. É a regra do jogo do quadro: "problema sem ação não
#: fecha pauta". Verde não obriga — exigir ação de quem está na meta é o que
#: ensina a inventar ação para poder fechar a reunião.
EXIGEM_ACAO = ("amarelo", "vermelho")

MAX_PRIORIDADES = 3


class DadoInvalido(comum.DadoInvalido):
    """Recusa legível — vira 409, nunca 5xx (o Cloudflare troca o corpo)."""


# ============================================================ as fontes
#
# CADA FONTE É UM ESCALAR COM PROCEDÊNCIA. `ler` devolve `float` ou `None`, e
# `None` significa "a fonte não respondeu AGORA" -- nunca zero. Zero e ausência
# são a mesma coisa na tela e coisas opostas na reunião: zero acidente é um
# resultado, nenhum dado sobre acidentes é uma pergunta em aberto.
#
# REGRA PARA ACRESCENTAR: leitura BARATA e já cacheada. O painel é lido várias
# vezes por semana por várias pessoas, e uma fonte que sai para a rede aqui
# transforma a abertura da tela em coleta -- a casa já tem a regra (fonte de
# painel jamais dispara coleta externa).

class Fonte:
    """Um número que a casa já calcula, pronto para virar indicador.

    `unidade`, `casas` e `direcao` são SUGESTÕES para o cadastro: quem cadastra
    o indicador recebe os valores certos já preenchidos, e pode mudá-los. Eles
    ficam gravados no indicador porque é o indicador que registra o que foi
    combinado -- se a fonte mudar de unidade um dia, o histórico não pode mudar
    de significado retroativamente.
    """

    __slots__ = ("chave", "rotulo", "gerencia", "unidade", "casas",
                 "direcao", "ler", "onde")

    def __init__(self, chave, rotulo, gerencia, unidade, casas, direcao,
                 ler, onde):
        self.chave, self.rotulo, self.gerencia = chave, rotulo, gerencia
        self.unidade, self.casas, self.direcao = unidade, casas, direcao
        self.ler, self.onde = ler, onde

    def como_dict(self) -> dict:
        return {"chave": self.chave, "rotulo": self.rotulo,
                "gerencia": self.gerencia, "unidade": self.unidade,
                "casas": self.casas, "direcao": self.direcao,
                "onde": self.onde}


def _vg(campo: str, fator: float = 1.0):
    """Um campo escalar da Visão Geral, que é leitura cacheada.

    A Visão Geral é o resumo de todas as áreas e já está quente quase sempre --
    é a tela inicial da casa. Puxar daqui é o que garante que o número do ritual
    seja LITERALMENTE o mesmo que a diretoria vê na abertura do painel, e não um
    recálculo parecido. Dois caminhos para o mesmo número é como se descobre,
    numa reunião, que dois relatórios discordam.
    """
    def ler():
        from api import queries
        v = queries.get_visao_geral().get(campo)
        return None if v is None else float(v) * fator
    return ler


#: Registro das fontes automáticas. A chave é o que fica gravado no indicador.
#:
#: Fonte que some daqui deixa indicadores órfãos apontando para o nada -- e o
#: sintoma seria um indicador eternamente vazio, não um erro. Por isso
#: `tests/test_ritual_gestao.py` varre o CADASTRO contra este registro e o
#: registro contra a EXECUÇÃO: toda fonte tem de responder número ou `None`
#: sem levantar.
FONTES: dict[str, Fonte] = {}


def _registrar(chave, rotulo, gerencia, unidade, casas, direcao, ler, onde):
    FONTES[chave] = Fonte(chave, rotulo, gerencia, unidade, casas, direcao,
                          ler, onde)


_registrar("receita_faturada_mes", "Receita faturada no mês", "comercial",
           "R$", 0, "maior_melhor", _vg("faturamento_mes"),
           "Visão Geral · faturamento do mês (notas emitidas)")
_registrar("receita_cte_mes", "Receita de frete no mês (CT-e)", "comercial",
           "R$", 0, "maior_melhor", _vg("receita_mes_cte"),
           "Visão Geral · frete das viagens do mês")
_registrar("atingimento_meta", "Atingimento da meta", "comercial",
           "%", 1, "maior_melhor", _vg("atingimento_mes", 100.0),
           "Visão Geral · realizado ÷ meta acumulados, a régua da meta")
_registrar("receber_vencido", "Contas a receber vencidas", "comercial",
           "R$", 0, "menor_melhor", _vg("receber_vencido"),
           "Visão Geral · títulos a receber já vencidos")
_registrar("os_abertas", "Ordens de serviço abertas", "manutencao",
           "OS", 0, "menor_melhor", _vg("os_abertas"),
           "Visão Geral · OS de manutenção em aberto")
_registrar("manutencao_mes", "Custo de manutenção no mês", "manutencao",
           "R$", 0, "menor_melhor", _vg("manutencao_mes"),
           "Visão Geral · manutenção lançada no mês")
_registrar("combustivel_mes", "Custo de combustível no mês", "operacao",
           "R$", 0, "menor_melhor", _vg("combustivel_proprio_mes"),
           "Visão Geral · combustível da frota própria no mês")
_registrar("oc_atrasadas", "Ordens de compra atrasadas", "manutencao",
           "OC", 0, "menor_melhor", _vg("oc_atrasadas"),
           "Visão Geral · OC aprovadas e vencidas sem nota")




def _mes_corrente() -> tuple[str, str]:
    """Do dia 1 até hoje.

    A JANELA É DECISÃO, e a alternativa óbvia (ano corrente, que é o que o
    Copiloto usa) tornaria estes indicadores inúteis AQUI: retorno vazio e RKM
    acumulados de doze meses praticamente não se movem de uma semana para a
    outra, e indicador que não pode mudar dentro do ciclo não é indicador de
    ritual semanal -- é papel de parede. Mês corrente move, e são razões (não
    somas), então já dizem alguma coisa com poucos dias.
    """
    hoje = date.today()
    return hoje.replace(day=1).isoformat(), hoje.isoformat()


def _aninhado(importar: str, funcao: str, caminho: str, fator: float = 1.0,
              args: tuple = (), janela_mes: bool = False):
    """Um escalar de dentro do retorno de uma função de tela.

    `caminho` é pontilhado ("kpis.retorno_vazio"). As chaves foram SONDADAS
    contra o sistema vivo, não deduzidas do código: chave errada aqui não
    levanta erro nenhum -- produz um indicador eternamente vazio, que é a
    classe de defeito que só se descobre na reunião, quando alguém pergunta
    por que aquela linha nunca tem número. E ASSINATURA ERRADA dá no mesmo: as
    três fontes da Operação nasceram mudas porque `get_analise_km` pede janela
    de data e eu chamei sem argumento -- o `except` de `ler_fonte` engoliu o
    `TypeError` e devolveu célula vazia, calada. Por isso o guard EXECUTA todas.
    """
    def ler():
        import importlib
        fn = getattr(importlib.import_module(importar), funcao)
        a = (None, *_mes_corrente()) if janela_mes else args
        d = fn(*a)
        for parte in caminho.split("."):
            if not isinstance(d, dict):
                return None
            d = d.get(parte)
        return None if d is None else float(d) * fator
    return ler


# ---- Operação. Vêm da Análise de KM, que é a mesma fonte da tela `km`.
_registrar("retorno_vazio", "Retorno vazio", "operacao",
           "%", 1, "menor_melhor",
           _aninhado("api.queries", "get_analise_km", "kpis.retorno_vazio", 100.0, janela_mes=True),
           "Análise de KM, mês corrente · (km total − km carregado) ÷ km "
           "total. Acima de 20% é o alerta da casa para lotação")
_registrar("rkm", "RKM — receita por km carregado", "operacao",
           "R$/km", 2, "maior_melhor",
           _aninhado("api.queries", "get_analise_km", "kpis.rkm", janela_mes=True),
           "Análise de KM, mês corrente · receita de frete ÷ km carregado")
_registrar("diesel_km", "Consumo — km por litro", "operacao",
           "km/l", 2, "maior_melhor",
           _aninhado("api.queries", "get_analise_km", "diesel_km", janela_mes=True),
           "Análise de KM, mês corrente · km rodado ÷ litros abastecidos")

# ---- RH. Três telas diferentes, e de propósito: são perguntas diferentes.
_registrar("cnh_vencidas", "CNH vencidas", "rh",
           "motoristas", 0, "menor_melhor",
           _aninhado("api.queries_folha", "get_cnh", "kpis.vencidas"),
           "CNH dos Motoristas · habilitação vencida entre quem está dirigindo")
_registrar("cnh_vence_prazo", "CNH vencendo no prazo", "rh",
           "motoristas", 0, "menor_melhor",
           _aninhado("api.queries_folha", "get_cnh", "kpis.vence_prazo"),
           "CNH dos Motoristas · vence dentro da janela de aviso")
_registrar("ferias_sem_agenda", "Férias vencidas sem agendamento", "rh",
           "pessoas", 0, "menor_melhor",
           _aninhado("api.queries_folha", "get_ferias", "kpis.sem_agenda"),
           "Férias · quem já tem direito e não tem período marcado")
_registrar("hc_ativos", "Quadro ativo", "rh",
           "pessoas", 0, "maior_melhor",
           _aninhado("api.people", "get_people", "kpis.ativos"),
           "People Analytics · pessoas ativas na folha")
_registrar("afastados", "Afastados", "rh",
           "pessoas", 0, "menor_melhor",
           _aninhado("api.people", "get_people", "kpis.afastados"),
           "People Analytics · afastamentos vigentes")




# ============================================================ o ciclo

def _q(sql, params=None, esquema=None):
    return pglocal.query(sql, params, esquema=comum._esq(esquema))


def _um(sql, params=None, esquema=None):
    return pglocal.um(sql, params, esquema=comum._esq(esquema))


def _exec(sql, params=None, esquema=None):
    return pglocal.executar(sql, params, esquema=comum._esq(esquema))


def semana_de(d: date) -> tuple[int, int]:
    """Ano e semana ISO. `isocalendar` e nao `strftime('%W')`: a semana ISO e a
    que a empresa usa ao dizer "semana 37", e a virada de ano nao inventa uma
    semana 0 de dois dias."""
    iso = d.isocalendar()
    return iso[0], iso[1]


def abrir_ciclo(data_reuniao: str, prazo: str = "", usuario: str = "",
                esquema: str | None = None) -> dict:
    """Abre a semana. Idempotente por (ano, semana) -- reabrir devolve o que ja
    existe em vez de criar um segundo painel concorrente para a mesma semana,
    que e o erro que ninguem percebe ate dois grupos preencherem painel
    diferente."""
    d = comum.data_br(data_reuniao, "a data da reunião", obrigatorio=True)
    ano, sem = semana_de(d)
    ja = _um("SELECT * FROM ges_ciclos WHERE ano=%s AND semana=%s",
             (ano, sem), esquema=esquema)
    if ja:
        return dict(ja)
    _exec("""INSERT INTO ges_ciclos(ano, semana, data_reuniao,
                                    prazo_preenchimento, criado_por, criado_em)
             VALUES (%s,%s,%s,%s,%s,%s)""",
          (ano, sem, d, prazo or "", usuario, comum.agora()), esquema=esquema)
    return dict(_um("SELECT * FROM ges_ciclos WHERE ano=%s AND semana=%s",
                    (ano, sem), esquema=esquema))


def ciclo_corrente(esquema: str | None = None) -> dict | None:
    """O ciclo ABERTO mais recente, ou o ultimo fechado se nao ha aberto.

    Nunca cria sozinho: abrir a semana e um ato de quem conduz, e um ciclo que
    nasce por alguem ter aberto a tela encheria o historico de semanas vazias
    que ninguem reuniu.
    """
    r = _um("""SELECT * FROM ges_ciclos
                ORDER BY (status='aberto') DESC, data_reuniao DESC LIMIT 1""",
            esquema=esquema)
    return dict(r) if r else None


# ============================================================ o painel

def farol(desvio_pct, tol_verde, tol_vermelho) -> str | None:
    """A COR, calculada a partir do desvio contra a meta.

    POR QUE ELA E CALCULADA, E NAO ESCOLHIDA
    ========================================
    A decisao fundadora do modulo diz que "o realizado vem da FONTE, nao do
    gerente". Ate 08/09/2026 isso valia so para o VALOR: a cor continuava
    sendo digitada, e como nenhum dos 12 indicadores tinha meta, ela era
    escolha inteiramente livre.

    O numero objetivo com veredito subjetivo e o pior dos dois mundos: a
    reuniao discute a cor, que e o que a regra de fechamento usa, e o rigor do
    numero nao serve para nada. Calcular o farol e o que faz a pergunta da
    sala ser "por que desviou" em vez de "por que voce pintou de amarelo".

    `None` quando falta meta ou realizado -- e `None` NAO e verde. Linha sem
    regua nao e linha sem problema, e pinta-la de verde faria o painel ficar
    mais bonito exatamente onde ninguem mediu nada.
    """
    if desvio_pct is None:
        return None
    d = float(desvio_pct)
    if d >= float(tol_verde if tol_verde is not None else 0):
        return "verde"
    if d >= float(tol_vermelho if tol_vermelho is not None else -10):
        return "amarelo"
    return "vermelho"


def _desvio(meta, realizado, direcao):
    """Desvio percentual COM SINAL, orientado pelo que e bom.

    Positivo = melhor que a meta, sempre -- independentemente de o indicador ser
    "quanto mais melhor" ou o contrario. Sem essa orientacao, o painel poe lado
    a lado um -8% que e otimo (multa abaixo da meta) e um -8% que e pessimo
    (receita abaixo da meta), e a coluna deixa de poder ser lida de relance,
    que e a unica coisa que ela precisa fazer.
    """
    if meta in (None, 0) or realizado is None:
        return None
    d = (float(realizado) - float(meta)) / abs(float(meta)) * 100.0
    return d if direcao == "maior_melhor" else -d


def painel(ciclo_id: int, esquema: str | None = None) -> dict:
    """O painel unico da semana: uma linha por indicador, agrupado por gerencia.

    O REALIZADO AUTOMATICO E LIDO AQUI, a cada pintura, e nao so no
    apontamento: o painel e aberto varias vezes entre a vespera e a reuniao, e
    congelar o numero no primeiro acesso mostraria dado velho justamente na
    sala. O que ficou gravado (`realizado_auto` do apontamento) continua a
    disposicao para responder "o que estava na tela quando decidimos".
    """
    ciclo = _um("SELECT * FROM ges_ciclos WHERE id=%s", (ciclo_id,), esquema=esquema)
    if not ciclo:
        raise DadoInvalido("Este ciclo não existe mais.")

    linhas = _q("""
        SELECT i.id AS indicador_id, i.nome, i.unidade, i.direcao, i.fonte,
               i.casas, i.meta_padrao, i.ordem,
               i.tol_verde, i.tol_vermelho,
               g.id AS gerencia_id, g.chave AS gerencia, g.nome AS gerencia_nome,
               g.ordem AS gerencia_ordem, g.gestor_id,
               u.nome AS gestor_nome,
               a.id AS apont_id, a.meta, a.realizado, a.realizado_auto,
               a.status, a.desvio, a.acao_id, a.prioridade,
               a.status_calculado, a.status_motivo,
               a.preenchido_por, a.preenchido_em,
               ac.o_que AS acao_o_que, ac.prazo AS acao_prazo,
               ac.status AS acao_status, ac.percentual AS acao_percentual,
               ac.responsavel_nome AS acao_resp_nome,
               ru.nome AS acao_resp_usuario
          FROM ges_indicadores i
          JOIN ges_gerencias g ON g.id = i.gerencia_id
     LEFT JOIN usuarios u ON u.id = g.gestor_id
     LEFT JOIN ges_apontamentos a ON a.indicador_id = i.id AND a.ciclo_id = %s
     LEFT JOIN ges_acoes ac ON ac.id = a.acao_id
     LEFT JOIN usuarios ru ON ru.id = ac.responsavel_id
         WHERE i.ativo = 1 AND g.ativa = 1
      ORDER BY g.ordem, g.nome, i.ordem, i.nome""",
        (ciclo_id,), esquema=esquema)

    hoje = comum.hoje()
    fora = []
    for r in linhas:
        d = dict(r)
        auto = ler_fonte(d["fonte"]) if d["fonte"] != "manual" else None
        d["automatico"] = d["fonte"] != "manual"
        d["fonte_onde"] = FONTES[d["fonte"]].onde if d["fonte"] in FONTES else ""
        # A FONTE DESCONHECIDA SE DENUNCIA. Indicador apontando para uma chave
        # que nao existe mais no registro apareceria como "automatico e vazio"
        # para sempre -- indistinguivel de fonte com dia ruim.
        d["fonte_orfa"] = d["automatico"] and d["fonte"] not in FONTES
        d["realizado_agora"] = auto
        # O valor que a linha MOSTRA: o automatico manda quando ha fonte.
        val = auto if d["automatico"] else (
            float(d["realizado"]) if d["realizado"] is not None else None)
        d["valor"] = val
        meta = d["meta"] if d["meta"] is not None else d["meta_padrao"]
        d["meta_valor"] = float(meta) if meta is not None else None
        d["desvio_pct"] = _desvio(d["meta_valor"], val, d["direcao"])

        # O FAROL E CALCULADO A CADA PINTURA, pelo mesmo motivo que o realizado
        # automatico: o painel abre varias vezes entre a vespera e a reuniao, e
        # a fonte pode ter mudado. O que ficou gravado no apontamento responde
        # "o que estava na tela quando decidimos".
        d["status_agora"] = farol(d["desvio_pct"], d["tol_verde"],
                                  d["tol_vermelho"])
        # O QUE A LINHA VALE, em TRES casos e nao dois:
        #
        #   1. discordou com motivo  -> vale a escolha da pessoa;
        #   2. ha calculo            -> vale o calculo (e uma meta nova
        #                               reflete na hora, sem depender de
        #                               alguem reapontar);
        #   3. NAO ha calculo        -> vale a escolha, que e a unica fonte
        #                               de cor que a linha tem.
        #
        # O caso 3 nasceu de um defeito: sem ele, `status_agora` nulo APAGAVA
        # a cor escolhida, e como os 12 indicadores da casa estao sem meta, o
        # painel inteiro ficava sem cor por mais que alguem preenchesse.
        d["status"] = (d["status"] if d["status_motivo"]
                       else (d["status_agora"] or d["status"]))
        d["divergente"] = bool(d["status_motivo"]
                               and d["status"] != d["status_agora"])
        # SEM META E SEM REALIZADO SAO COISAS DIFERENTES, e a tela precisa
        # dizer qual -- uma se conserta no cadastro, a outra na fonte.
        d["sem_meta"] = d["meta_valor"] is None
        for k in ("tol_verde", "tol_vermelho"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        # PREENCHIDO deixa de significar "alguem escolheu a cor": com o farol
        # calculado, a linha ja nasce com cor. O que a reuniao ainda precisa e
        # que alguem TENHA OLHADO -- e isso e o apontamento existir.
        d["preenchido"] = bool(d["apont_id"])
        # Atraso da acao: DERIVADO, nunca gravado (mesma regra de ges_acoes).
        d["acao_atrasada"] = bool(
            d["acao_prazo"] and d["acao_status"] in ("aberta", "em_andamento")
            and d["acao_prazo"] < hoje)
        d["exige_acao"] = d["status"] in EXIGEM_ACAO and not d["acao_id"]
        for k in ("meta", "realizado", "realizado_auto"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        if d.get("acao_prazo"):
            d["acao_prazo"] = d["acao_prazo"].isoformat()
        fora.append(d)

    ger: dict = {}
    for d in fora:
        ger.setdefault(d["gerencia"], {
            "chave": d["gerencia"], "nome": d["gerencia_nome"],
            "gestor": d["gestor_nome"] or "", "linhas": []})["linhas"].append(d)

    c = dict(ciclo)
    c["data_reuniao"] = c["data_reuniao"].isoformat()
    return {
        "ciclo": c,
        "gerencias": list(ger.values()),
        "resumo": _resumo(fora),
        "pendencias": _pendencias(ger.values()),
        "pendencias_de_cadastro": pendencias_de_cadastro(fora, ger.values()),
        "bloqueios": bloqueios(fora),
        "prioridades": [d for d in fora if d["prioridade"]],
        "fonte": "banco do CÓRTEX (ges_*) + as telas de cada indicador",
    }


def pendencias_de_cadastro(linhas: list[dict], gerencias) -> list[dict]:
    """O que falta CONFIGURAR para o ritual funcionar de verdade.

    E uma lista diferente de `_pendencias`, e a diferenca decide a quem a tela
    cobra. `_pendencias` diz quem nao PREENCHEU esta semana -- e trabalho do
    gerente, toda semana. Esta diz o que nunca foi CONFIGURADO -- e trabalho de
    quem cuida do cadastro, uma vez.

    Sem ela, o modo de falha e mudo e foi exatamente o encontrado em
    08/09/2026: os 12 indicadores sem meta e as 4 gerencias sem gestor. O
    painel abria inteiro, com numero em toda linha, e nada dizia que o farol
    nao podia funcionar. Um painel que parece completo e nao tem regua e pior
    que um painel vazio, porque ninguem desconfia dele.
    """
    fora: list[dict] = []

    sem_meta = [d["nome"] for d in linhas if d["sem_meta"]]
    if sem_meta:
        fora.append({
            "tipo": "sem_meta", "quantos": len(sem_meta), "de": len(linhas),
            "itens": sem_meta[:8],
            "mensagem": "%d de %d indicadores estao SEM META. Sem meta nao ha "
                        "desvio, e sem desvio o farol nao acende -- a linha "
                        "aparece com numero e sem cor."
                        % (len(sem_meta), len(linhas))})

    sem_gestor = [g["nome"] for g in gerencias if not g["gestor"]]
    if sem_gestor:
        fora.append({
            "tipo": "sem_gestor", "quantos": len(sem_gestor),
            "de": len(list(gerencias)), "itens": sem_gestor,
            "mensagem": "%d gerencia(s) sem gestor: %s. A lista de quem nao "
                        "preencheu existe para dizer A QUEM cobrar, e sem "
                        "gestor ela nao sabe."
                        % (len(sem_gestor), ", ".join(sem_gestor))})

    orfas = [d["nome"] for d in linhas if d.get("fonte_orfa")]
    if orfas:
        fora.append({
            "tipo": "fonte_orfa", "quantos": len(orfas), "de": len(linhas),
            "itens": orfas[:8],
            "mensagem": "%d indicador(es) apontam para uma fonte que nao "
                        "existe mais no catalogo: %s. Eles ficariam vazios "
                        "para sempre sem dar erro."
                        % (len(orfas), ", ".join(orfas[:4]))})
    return fora


def _resumo(linhas: list[dict]) -> dict:
    """Os KPIs do topo. `sem_status` é contado à parte de propósito: linha em
    branco não é linha verde, e somá-las como "sem problema" faria o painel
    ficar mais bonito exatamente quando ninguém preencheu."""
    return {
        "indicadores": len(linhas),
        "verde": sum(1 for d in linhas if d["status"] == "verde"),
        "amarelo": sum(1 for d in linhas if d["status"] == "amarelo"),
        "vermelho": sum(1 for d in linhas if d["status"] == "vermelho"),
        "sem_status": sum(1 for d in linhas if not d["status"]),
        "sem_acao": sum(1 for d in linhas if d["exige_acao"]),
        "automaticos": sum(1 for d in linhas if d["automatico"]),
        # SEM META e contado a parte de "sem_status" de proposito: os dois
        # aparecem como linha sem cor, e o conserto de cada um e em lugar
        # diferente -- um no cadastro, outro na fonte.
        "sem_meta": sum(1 for d in linhas if d.get("sem_meta")),
        "divergentes": sum(1 for d in linhas if d.get("divergente")),
    }


def _pendencias(gerencias) -> list[dict]:
    """Quem ainda não preencheu, por gerência — a informação que existe ANTES
    da reunião e que é a razão de o preenchimento ser antes dela."""
    fora = []
    for g in gerencias:
        falta = [d["nome"] for d in g["linhas"] if not d["preenchido"]]
        if falta:
            fora.append({"gerencia": g["nome"], "gestor": g["gestor"],
                         "faltam": len(falta), "de": len(g["linhas"]),
                         "indicadores": falta[:8]})
    return fora


def bloqueios(linhas: list[dict]) -> list[dict]:
    """As REGRAS DO JOGO, como lista de pendências nomeadas.

    Elas existem no quadro da parede ("problema sem ação não fecha pauta") e
    aqui viram condição de fechamento. Devolver a LISTA em vez de um booleano é
    o que permite a tela dizer o que falta em vez de só recusar — recusa sem
    motivo é a forma mais rápida de ensinar alguém a contornar a regra.
    """
    fora = []
    for d in linhas:
        if d["exige_acao"]:
            fora.append({"tipo": "desvio_sem_acao", "indicador": d["nome"],
                         "gerencia": d["gerencia_nome"],
                         "mensagem": "%s (%s) está %s e não tem ação."
                                     % (d["nome"], d["gerencia_nome"], d["status"])})
    return fora




# ============================================================ apontar

def apontar(ciclo_id: int, indicador_id: int, dados: dict, usuario: str = "",
            esquema: str | None = None) -> dict:
    """O bloco de 2 minutos do gerente, gravado.

    EDIÇÃO PARCIAL COM A REGRA DA CASA: chave ausente não mexe, chave vazia
    limpa. É o que permite a tela salvar só o campo que a pessoa tocou sem
    apagar o resto do que já estava ali — e o que permite o condutor ajustar a
    prioridade na reunião sem reenviar o desvio inteiro.
    """
    ciclo = _um("SELECT * FROM ges_ciclos WHERE id=%s", (ciclo_id,), esquema=esquema)
    if not ciclo:
        raise DadoInvalido("Este ciclo não existe mais.")
    if ciclo["status"] == "fechado":
        raise DadoInvalido(
            "Esta semana já foi fechada. Reabra o ciclo para alterar o painel.")
    ind = _um("SELECT * FROM ges_indicadores WHERE id=%s", (indicador_id,),
              esquema=esquema)
    if not ind:
        raise DadoInvalido("Este indicador não existe mais.")

    atual = _um("""SELECT * FROM ges_apontamentos
                    WHERE ciclo_id=%s AND indicador_id=%s""",
                (ciclo_id, indicador_id), esquema=esquema) or {}

    campos: dict = {}

    # O FAROL CALCULADO E GRAVADO SEMPRE, junto do apontamento: e ele que
    # responde "o que o sistema dizia quando decidimos", e sem isso a
    # divergencia entre o calculado e o escolhido some no dia em que a meta
    # mudar.
    val_auto = ler_fonte(ind["fonte"]) if ind["fonte"] != "manual" else None
    meta_ef = dados.get("meta") if "meta" in dados else atual.get("meta")
    if meta_ef in (None, ""):
        meta_ef = ind["meta_padrao"]
    val_ef = val_auto if ind["fonte"] != "manual" else (
        dados.get("realizado") if "realizado" in dados else atual.get("realizado"))
    campos["status_calculado"] = farol(
        _desvio(_numero(meta_ef, "meta"), _numero(val_ef, "realizado"),
                ind["direcao"]),
        ind.get("tol_verde"), ind.get("tol_vermelho"))

    if "status" in dados:
        st = (dados["status"] or "").strip()
        if st and st not in STATUS:
            raise DadoInvalido("Semáforo inválido: use verde, amarelo ou vermelho.")
        # DISCORDAR DO FAROL E UM ATO, e ato tem motivo.
        #
        # A saida existe porque as vezes o calculo esta errado mesmo: o mes teve
        # um evento que a meta nao previa, a fonte contou o que nao devia.
        # Tirar a saida faria alguem contornar por fora -- mexer na meta ate a
        # cor sair certa --, e ai o painel mente sem deixar rastro.
        #
        # Mas exigir o motivo e o que impede a discordancia de virar o estado
        # NORMAL. Sem ele, em duas semanas todo mundo pinta a mao de novo e o
        # farol calculado vira enfeite.
        motivo = (dados.get("status_motivo") or "").strip()
        # SO SE HA COR CALCULADA E QUE ESCOLHER OUTRA E DISCORDAR.
        #
        # Sem meta nao ha desvio, sem desvio nao ha farol, e a escolha da
        # pessoa e a UNICA fonte de cor da linha -- exigir que ela justifique
        # discordar de coisa nenhuma tornaria o indicador impossivel de
        # preencher. Com os 12 indicadores da casa hoje sem meta, isso
        # travaria o ritual inteiro.
        #
        # A regra existe para impedir que a discordancia vire o estado normal
        # ONDE HA CALCULO -- e nao para punir quem ainda nao tem regua.
        if st and campos["status_calculado"] and st != campos["status_calculado"]:
            if len(motivo) < 10:
                raise DadoInvalido(
                    "Para apresentar %s onde o cálculo diz %s, explique por quê "
                    "(pelo menos 10 caracteres). O motivo fica registrado com o "
                    "seu nome." % (st, campos["status_calculado"] or "sem cor"))
            campos["status"] = st
            campos["status_motivo"] = motivo
        else:
            # Concordou (ou limpou): a linha volta a seguir o calculo.
            # `or ""` porque a coluna e NOT NULL: sem meta o calculo e None, e
            # gravar None estoura a transacao inteira -- o apontamento que a
            # pessoa acabou de fazer se perde por causa de um cadastro
            # incompleto que nao e culpa dela.
            campos["status"] = st or campos["status_calculado"] or ""
            campos["status_motivo"] = None
    elif not atual.get("status_motivo"):
        campos["status"] = campos["status_calculado"] or atual.get("status") or ""
    if "desvio" in dados:
        campos["desvio"] = comum.texto(dados["desvio"], "desvio", obrigatorio=False)
    if "meta" in dados:
        campos["meta"] = _numero(dados["meta"], "meta")
    if "realizado" in dados:
        # INDICADOR AUTOMÁTICO NÃO ACEITA DIGITAÇÃO, e a recusa é explícita em
        # vez de silenciosa: gravar calado deixaria a pessoa achando que mandou
        # no número, e a próxima pintura (que relê a fonte) desfaria na cara
        # dela sem explicação.
        if ind["fonte"] != "manual":
            raise DadoInvalido(
                "O realizado deste indicador vem de %s e não se digita. "
                "Se o número está errado, o conserto é na origem."
                % (FONTES[ind["fonte"]].onde if ind["fonte"] in FONTES
                   else "uma fonte automática"))
        campos["realizado"] = _numero(dados["realizado"], "realizado")
    if "acao_nova" in dados and dados["acao_nova"]:
        campos["acao_id"] = _criar_acao(dados["acao_nova"], usuario, esquema)
    elif "acao_id" in dados:
        campos["acao_id"] = _acao_valida(dados["acao_id"], esquema)

    # O realizado automático fica CARIMBADO no apontamento: é ele que responde
    # "o que estava na tela quando decidimos" depois de o ERP reprocessar.
    if ind["fonte"] != "manual":
        campos["realizado_auto"] = ler_fonte(ind["fonte"])

    campos["preenchido_por"] = usuario
    campos["preenchido_em"] = comum.agora()

    if atual:
        sets = ", ".join("%s=%%s" % k for k in campos)
        _exec("UPDATE ges_apontamentos SET %s WHERE id=%%s" % sets,
              (*campos.values(), atual["id"]), esquema=esquema)
    else:
        cols = ["ciclo_id", "indicador_id", *campos]
        _exec("INSERT INTO ges_apontamentos(%s) VALUES (%s)"
              % (", ".join(cols), ", ".join(["%s"] * len(cols))),
              (ciclo_id, indicador_id, *campos.values()), esquema=esquema)
    return dict(_um("""SELECT * FROM ges_apontamentos
                        WHERE ciclo_id=%s AND indicador_id=%s""",
                    (ciclo_id, indicador_id), esquema=esquema))


def _numero(v, rotulo):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(".", "").replace(",", ".")
                     if isinstance(v, str) and "," in str(v) else v)
    except (TypeError, ValueError):
        raise DadoInvalido("O campo %s precisa ser um número." % rotulo) from None


def _criar_acao(dados: dict, usuario: str, esquema) -> int:
    """A ação nasce AQUI, na reunião, e vai para `ges_acoes` — a mesma tabela
    do Plano de Ação, não uma cópia.

    Sem isto a regra do jogo não teria como ser cumprida por quem ela cobra:
    criar ação é rota `/api/gestao`, que é ADMIN, e quem tem o desvio é o
    gerente. A alternativa seria o gerente pedir para um administrador criar a
    ação — e uma regra que depende de terceiro para ser cumprida é uma regra
    que não se cumpre.

    O 5W2H completo continua sendo editado na tela de Planos de Ação. Aqui
    entram os três campos sem os quais o compromisso não existe: o quê, quem e
    quando. É a mesma lista que o quadro chama de saída obrigatória.
    """
    o_que = comum.texto(dados.get("o_que"), "o que será feito",
                        maximo=comum.TITULO_MAX, obrigatorio=True)
    prazo = comum.data_br(dados.get("prazo"), "o prazo", obrigatorio=True)
    resp_id, resp_nome = comum.pessoa(
        dados.get("responsavel_id"), dados.get("responsavel_nome"),
        "o responsável", esquema=esquema)
    r = _um("""INSERT INTO ges_acoes(o_que, por_que, responsavel_id,
                                     responsavel_nome, prazo, area, prioridade,
                                     status, criado_por, criado_em)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'aberta',%s,%s) RETURNING id""",
            (o_que, comum.texto(dados.get("por_que"), "por quê"),
             resp_id, resp_nome, prazo,
             comum.texto(dados.get("area"), "área"),
             (dados.get("prioridade") or "alta"),
             usuario, comum.agora()), esquema=esquema)
    return r["id"]


def _acao_valida(acao_id, esquema):
    if acao_id in (None, "", 0):
        return None
    r = _um("SELECT id FROM ges_acoes WHERE id=%s", (int(acao_id),), esquema=esquema)
    if not r:
        raise DadoInvalido("Esta ação não existe mais.")
    return int(acao_id)


def priorizar(ciclo_id: int, indicador_id: int, posicao, usuario: str = "",
              esquema: str | None = None) -> None:
    """As três entregas críticas da semana — a saída obrigatória da reunião.

    `posicao` vazio TIRA da lista. O teto de três é do BANCO (índice único
    parcial), não desta função: regra de negócio que só existe no Python é
    regra que a próxima rota esquece.
    """
    if posicao in (None, "", 0):
        _exec("""UPDATE ges_apontamentos SET prioridade=NULL
                  WHERE ciclo_id=%s AND indicador_id=%s""",
              (ciclo_id, indicador_id), esquema=esquema)
        return
    p = int(posicao)
    if not 1 <= p <= MAX_PRIORIDADES:
        raise DadoInvalido("A prioridade vai de 1 a %d." % MAX_PRIORIDADES)
    # Libera quem estava na posição antes: sem isto o índice único recusaria a
    # troca, e trocar a ordem das prioridades é coisa que acontece na reunião.
    _exec("""UPDATE ges_apontamentos SET prioridade=NULL
              WHERE ciclo_id=%s AND prioridade=%s""", (ciclo_id, p), esquema=esquema)
    apontar(ciclo_id, indicador_id, {}, usuario, esquema)
    _exec("""UPDATE ges_apontamentos SET prioridade=%s
              WHERE ciclo_id=%s AND indicador_id=%s""",
          (p, ciclo_id, indicador_id), esquema=esquema)


def fechar(ciclo_id: int, usuario: str = "", forcar: bool = False,
           esquema: str | None = None) -> dict:
    """Fecha a semana — e é aqui que as regras do jogo deixam de ser cartaz.

    A recusa é 409 com a LISTA do que falta (ver `bloqueios`). `forcar` existe
    porque uma regra sem escape vira regra contornada por fora: alguém apontaria
    verde no vermelho só para conseguir fechar, e aí o painel passa a mentir.
    Forçar fica REGISTRADO em `observacoes`, que é o que mantém o custo social
    da exceção.
    """
    p = painel(ciclo_id, esquema=esquema)
    if p["bloqueios"] and not forcar:
        raise DadoInvalido(
            "Desvio sem ação não fecha pauta — falta ação em: %s."
            % "; ".join(b["indicador"] for b in p["bloqueios"][:5]))
    obs = ""
    if p["bloqueios"]:
        obs = ("Fechado com %d desvio(s) sem ação, por %s em %s."
               % (len(p["bloqueios"]), usuario or "?", comum.agora()))
    _exec("""UPDATE ges_ciclos
                SET status='fechado', fechado_por=%s, fechado_em=%s,
                    observacoes = CASE WHEN %s = '' THEN observacoes
                                       ELSE trim(observacoes || ' ' || %s) END
              WHERE id=%s""",
          (usuario, comum.agora(), obs, obs, ciclo_id), esquema=esquema)
    return {"fechado": True, "com_bloqueio": len(p["bloqueios"])}


def reabrir(ciclo_id: int, usuario: str = "", esquema: str | None = None) -> dict:
    _exec("""UPDATE ges_ciclos SET status='aberto',
                observacoes = trim(observacoes || ' ' || %s)
              WHERE id=%s""",
          ("Reaberto por %s em %s." % (usuario or "?", comum.agora()), ciclo_id),
          esquema=esquema)
    return {"reaberto": True}


# ============================================== o fechamento da semana passada

def cobranca(ciclo_id: int, esquema: str | None = None) -> dict:
    """O que foi prometido na semana ANTERIOR, e o que saiu.

    DERIVADO das ações, nunca gravado: o "cumpriu" que se grava passa a
    discordar da própria ação no primeiro edit, e a reunião perde a única coisa
    que a torna diferente de uma conversa — a memória do que foi combinado.

    A pergunta é sobre as ações ligadas ao painel do ciclo anterior, com prazo
    até a reunião de agora: promessa com prazo daqui a um mês não é
    descumprimento, é prazo.
    """
    c = _um("SELECT * FROM ges_ciclos WHERE id=%s", (ciclo_id,), esquema=esquema)
    if not c:
        raise DadoInvalido("Este ciclo não existe mais.")
    ant = _um("""SELECT * FROM ges_ciclos
                  WHERE data_reuniao < %s ORDER BY data_reuniao DESC LIMIT 1""",
              (c["data_reuniao"],), esquema=esquema)
    if not ant:
        return {"anterior": None, "itens": [], "resumo": {}}

    itens = _q("""
        SELECT ac.id, ac.o_que, ac.prazo, ac.status, ac.percentual,
               ac.concluida_em, ac.responsavel_nome, u.nome AS responsavel_usuario,
               i.nome AS indicador, g.nome AS gerencia
          FROM ges_apontamentos a
          JOIN ges_acoes ac ON ac.id = a.acao_id
          JOIN ges_indicadores i ON i.id = a.indicador_id
          JOIN ges_gerencias g ON g.id = i.gerencia_id
     LEFT JOIN usuarios u ON u.id = ac.responsavel_id
         WHERE a.ciclo_id = %s AND ac.prazo <= %s
      ORDER BY g.ordem, ac.prazo""",
        (ant["id"], c["data_reuniao"]), esquema=esquema)

    fora = []
    for r in itens:
        d = dict(r)
        d["prazo"] = d["prazo"].isoformat() if d["prazo"] else None
        d["cumpriu"] = d["status"] == "concluida"
        d["responsavel"] = d["responsavel_usuario"] or d["responsavel_nome"]
        fora.append(d)
    cumpridas = sum(1 for d in fora if d["cumpriu"])
    return {
        "anterior": {"id": ant["id"], "ano": ant["ano"], "semana": ant["semana"],
                     "data_reuniao": ant["data_reuniao"].isoformat()},
        "itens": fora,
        "resumo": {"prometidas": len(fora), "cumpridas": cumpridas,
                   "abertas": len(fora) - cumpridas,
                   # `None`, nunca 0: sem promessa não há taxa, e 0% diria
                   # "ninguém cumpriu nada" numa semana em que nada foi pedido.
                   "taxa": (cumpridas / len(fora)) if fora else None},
    }




# ============================================================ cadastro

def acoes_abertas(limite: int = 200, esquema: str | None = None) -> list[dict]:
    """As ações vivas, para o modal ligar numa que já existe.

    É o caso COMUM, e não a exceção: o desvio desta semana costuma ser o mesmo
    da semana passada, e criar uma ação nova a cada reunião produziria seis
    ações para um problema só — cada uma com 20% de andamento, nenhuma
    concluída, e o plano de ação virando lista de intenções repetidas.
    """
    rs = _q("""SELECT a.id, a.o_que, a.prazo, a.status, a.percentual,
                      a.responsavel_nome, u.nome AS responsavel_usuario
                 FROM ges_acoes a
            LEFT JOIN usuarios u ON u.id = a.responsavel_id
                WHERE a.status IN ('aberta','em_andamento')
             ORDER BY a.prazo LIMIT %s""", (limite,), esquema=esquema)
    fora = []
    for r in rs:
        d = dict(r)
        d["prazo"] = d["prazo"].isoformat() if d["prazo"] else None
        d["responsavel"] = d["responsavel_usuario"] or d["responsavel_nome"]
        fora.append(d)
    return fora


def ciclos_recentes(limite: int = 12, esquema: str | None = None) -> list[dict]:
    """As últimas semanas, para o seletor. Serve à pergunta que a reunião faz
    toda vez -- "o que a gente combinou na outra?" -- sem obrigar a decorar
    número de semana."""
    rs = _q("""SELECT id, ano, semana, data_reuniao, status
                 FROM ges_ciclos ORDER BY data_reuniao DESC LIMIT %s""",
            (limite,), esquema=esquema)
    fora = []
    for r in rs:
        d = dict(r)
        d["data_reuniao"] = d["data_reuniao"].isoformat()
        fora.append(d)
    return fora


def gerencias(esquema: str | None = None) -> list[dict]:
    rs = _q("""SELECT g.*, u.nome AS gestor_nome,
                      (SELECT count(*) FROM ges_indicadores i
                        WHERE i.gerencia_id=g.id AND i.ativo=1) AS indicadores
                 FROM ges_gerencias g
            LEFT JOIN usuarios u ON u.id = g.gestor_id
             ORDER BY g.ativa DESC, g.ordem, g.nome""", esquema=esquema)
    return [dict(r) for r in rs]


def salvar_gerencia(dados: dict, esquema: str | None = None) -> dict:
    """Só o gestor e a ordem se editam pela tela. A CHAVE não: ela é o que os
    indicadores e o histórico citam, e renomeá-la em produção reescreveria a
    ligação de ciclos passados sem ninguém pedir."""
    gid = int(dados.get("id") or 0)
    if not gid:
        raise DadoInvalido("Gerência não informada.")
    gestor = dados.get("gestor_id")
    _exec("""UPDATE ges_gerencias
                SET gestor_id=%s, ordem=%s, ativa=%s WHERE id=%s""",
          (int(gestor) if gestor else None,
           int(dados.get("ordem") or 0),
           1 if dados.get("ativa", 1) else 0, gid), esquema=esquema)
    return {"id": gid}


def indicadores(esquema: str | None = None) -> list[dict]:
    rs = _q("""SELECT i.*, g.chave AS gerencia, g.nome AS gerencia_nome
                 FROM ges_indicadores i
                 JOIN ges_gerencias g ON g.id = i.gerencia_id
             ORDER BY g.ordem, i.ordem, i.nome""", esquema=esquema)
    fora = []
    for r in rs:
        d = dict(r)
        d["meta_padrao"] = (float(d["meta_padrao"])
                            if d["meta_padrao"] is not None else None)
        # Decimal nao sobrevive ao JSONResponse: converte no LIMITE do modulo,
        # e nao no render(), onde o estouro cai DEPOIS do try/except da rota.
        for k in ("tol_verde", "tol_vermelho"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        d["automatico"] = d["fonte"] != "manual"
        d["fonte_onde"] = FONTES[d["fonte"]].onde if d["fonte"] in FONTES else ""
        d["fonte_orfa"] = d["automatico"] and d["fonte"] not in FONTES
        fora.append(d)
    return fora


def salvar_indicador(dados: dict, esquema: str | None = None) -> dict:
    """Cria ou edita. A FONTE É VALIDADA CONTRA O REGISTRO na entrada.

    Deixar passar uma chave desconhecida não daria erro nenhum: o indicador
    entraria como automático e ficaria vazio para sempre — o defeito que só
    aparece na reunião, quando alguém pergunta por que aquela linha nunca tem
    número. Validar aqui é dois segundos; descobrir lá custa a reunião.
    """
    ind_id = int(dados.get("id") or 0)
    nome = comum.texto(dados.get("nome"), "o nome do indicador",
                       maximo=comum.TITULO_MAX, obrigatorio=True)
    ger = int(dados.get("gerencia_id") or 0)
    if not _um("SELECT id FROM ges_gerencias WHERE id=%s", (ger,), esquema=esquema):
        raise DadoInvalido("Escolha a gerência do indicador.")
    fonte = (dados.get("fonte") or "manual").strip() or "manual"
    if fonte != "manual" and fonte not in FONTES:
        raise DadoInvalido(
            "Fonte automática desconhecida: %s. As disponíveis são: %s."
            % (fonte, ", ".join(sorted(FONTES))))
    direcao = (dados.get("direcao") or "maior_melhor").strip()
    if direcao not in ("maior_melhor", "menor_melhor"):
        raise DadoInvalido("Direção inválida: use maior_melhor ou menor_melhor.")
    # AS FAIXAS DO FAROL. Vazio cai no padrao (0 e -10) em vez de virar NULO:
    # a coluna e NOT NULL, e um NULO aqui faria `farol()` cair no default de
    # qualquer jeito -- so que sem ninguem conseguir VER qual e a regra da
    # linha. Regra invisivel e regra que a proxima pessoa descobre errando.
    tolv = _numero(dados.get("tol_verde"), "faixa do verde")
    tolr = _numero(dados.get("tol_vermelho"), "faixa do vermelho")
    tolv = 0.0 if tolv is None else float(tolv)
    tolr = -10.0 if tolr is None else float(tolr)
    if tolr > tolv:
        raise DadoInvalido(
            "A faixa do vermelho (%g) tem de ser MENOR que a do verde (%g). "
            "Como está, não sobra faixa para o amarelo — e o painel só teria "
            "duas cores." % (tolr, tolv))

    campos = (nome, ger, (dados.get("unidade") or "").strip()[:20], direcao,
              fonte, _numero(dados.get("meta_padrao"), "meta"),
              tolv, tolr,
              max(0, min(4, int(dados.get("casas") or 0))),
              int(dados.get("ordem") or 0),
              1 if dados.get("ativo", 1) else 0)
    if ind_id:
        _exec("""UPDATE ges_indicadores
                    SET nome=%s, gerencia_id=%s, unidade=%s, direcao=%s,
                        fonte=%s, meta_padrao=%s, tol_verde=%s, tol_vermelho=%s,
                        casas=%s, ordem=%s, ativo=%s
                  WHERE id=%s""", (*campos, ind_id), esquema=esquema)
        return {"id": ind_id}
    r = _um("""INSERT INTO ges_indicadores(nome, gerencia_id, unidade, direcao,
                                           fonte, meta_padrao, tol_verde,
                                           tol_vermelho, casas, ordem,
                                           ativo, criado_em)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (*campos, comum.agora()), esquema=esquema)
    return {"id": r["id"]}


def excluir_indicador(ind_id: int, esquema: str | None = None) -> dict:
    """INATIVA, não apaga. Os apontamentos de semanas passadas citam o
    indicador, e um DELETE levaria junto o painel do que já foi decidido —
    reescrevendo a história das reuniões para arrumar o cadastro de hoje."""
    _exec("UPDATE ges_indicadores SET ativo=0 WHERE id=%s", (ind_id,),
          esquema=esquema)
    return {"inativado": True}




# ---------------------------------------------------------------------------
# SEGUNDA LEVA: o ritual olhando ESTRATEGIA e EXECUCAO, e nao so o mes.
#
# A regra de entrada continua a mesma -- leitura barata e ja cacheada --, e
# todas foram cronometradas contra o sistema vivo antes de entrar: a mais cara
# e a de horas extras, 2,7 s; a maioria fica abaixo de 1,5 s. Fonte de dez
# segundos aqui viraria reuniao esperando tela.
#
# E DUAS TRADUCOES, porque o pedido veio em linguagem de reuniao e uma linha do
# painel e um NUMERO SO:
#
#   "embarques por cliente"    -> quantos embarques, quantos clientes, e o
#   "faturamento por cliente"     PESO dos maiores. A quebra por cliente e
#                                 relatorio (a tela `com` faz isso); o que
#                                 decide numa reuniao de estrategia e a
#                                 CONCENTRACAO -- hoje 94% da receita em dez
#                                 clientes, e 21% num so.


def _prod(caminho, fator=1.0):
    """Produtividade de Veiculos, mes corrente."""
    return _aninhado("api.queries", "get_produtividade_veiculos", caminho,
                     fator, janela_mes=True)


def _com(caminho, fator=1.0):
    """Clientes e RKM, mes corrente."""
    return _aninhado("api.queries", "get_comercial", caminho, fator,
                     janela_mes=True)


def _diarias(campo):
    """Diaria paga (folha) x dias trabalhados (jornada), mes corrente.

    Duas consultas em bancos diferentes -- a folha no AVA, a jornada no
    Postgres local --, cruzadas por nome normalizado. Medido em 0,2 s porque as
    duas ja estao cacheadas; e por isso que entra.
    """
    def ler():
        from api.jornada import diarias as dj
        ini, fim = _mes_corrente()
        d = dj.levantar(date.fromisoformat(ini), date.fromisoformat(fim))
        v = dj.resumo(d, dj.mensal(d)).get(campo)
        return None if v is None else float(v)
    return ler


def _pneus(campo, de_troca=False):
    """O que o parque de pneus CUSTA -- nao o instantaneo da Prolog.

    Sai do banco da casa cruzado com o ERP e nao gasta cota da API da Prolog,
    entao continua respondendo no dia em que ela cair.

    `de_troca` escolhe entre as DUAS funcoes do modulo, e a distincao custou
    duas fontes mudas: copiei os nomes do snapshot do Copiloto, que RENOMEIA
    as chaves na saida dele (`vencidos_n` vira `pneus_abaixo_do_limite`).
    Ler o consumidor em vez da fonte e como se herda um apelido que so existe
    lá.
    """
    def ler():
        from api.pneus import servico as pn
        v = (pn.troca() if de_troca else pn.rendimento()).get(campo)
        return None if v is None else float(v)
    return ler


def _crm(campo):
    def ler():
        from api.crm import painel as cp
        v = (cp.tudo().get("kpis") or {}).get(campo)
        return None if v is None else float(v)
    return ler


# ---- Comercial: quanto se embarca, para quantos, e quao concentrado.
_registrar("embarques_mes", "Embarques no mês (CT-e)", "comercial",
           "CT-e", 0, "maior_melhor", _com("kpis.ctes"),
           "Clientes e RKM, mês corrente · CT-e emitidos")
_registrar("clientes_ativos_mes", "Clientes com carga no mês", "comercial",
           "clientes", 0, "maior_melhor", _com("kpis.clientes"),
           "Clientes e RKM, mês corrente · clientes distintos com embarque")
_registrar("concentracao_top10", "Concentração nos 10 maiores clientes",
           "comercial", "%", 1, "menor_melhor",
           _com("kpis.concentracao_top10", 100.0),
           "Clientes e RKM, mês corrente · quanto da receita está nos dez "
           "maiores. É o número de RISCO da carteira, não de desempenho")
_registrar("peso_maior_cliente", "Peso do maior cliente", "comercial",
           "%", 1, "menor_melhor", _com("abc.top1", 100.0),
           "Clientes e RKM, mês corrente · fatia da receita no cliente nº 1")
_registrar("crm_ganhas", "Negócios ganhos no período", "comercial",
           "negócios", 0, "maior_melhor", _crm("ganhas_janela"),
           "CRM · oportunidades marcadas como ganhas. ATENÇÃO: lê ZERO "
           "enquanto o funil do CRM não for alimentado — e zero por falta de "
           "preenchimento não é desempenho")
_registrar("crm_contas_paradas", "Contas ativas que pararam", "comercial",
           "contas", 0, "menor_melhor", _crm("contas_paradas"),
           "CRM · contas da carteira sem faturamento recente")

# ---- Operação: o que a frota rende, e o que ela deixa de render.
_registrar("receita_por_veiculo", "Receita por veículo no mês", "operacao",
           "R$", 0, "maior_melhor", _prod("kpis.receita_por_veiculo"),
           "Produtividade de Veículos, mês corrente · receita ÷ veículos que "
           "rodaram")
_registrar("km_por_veiculo", "Km por veículo no mês", "operacao",
           "km", 0, "maior_melhor", _prod("kpis.km_por_veiculo"),
           "Produtividade de Veículos, mês corrente")
_registrar("ociosidade_frota", "Ociosidade da frota", "operacao",
           "%", 1, "menor_melhor", _prod("kpis.ociosidade", 100.0),
           "Produtividade de Veículos, mês corrente · veículos da base que não "
           "rodaram no período")
_registrar("veiculos_ociosos", "Veículos parados no mês", "operacao",
           "veículos", 0, "menor_melhor", _prod("kpis.ociosos"),
           "Produtividade de Veículos, mês corrente · quantos, em número")

# ---- Manutenção: o que o pneu custa por km, e o que vai pedir dinheiro.
_registrar("cpk_pneus", "CPK — custo de pneu por km", "manutencao",
           "R$/km", 3, "menor_melhor", _pneus("cpk_mediano"),
           "Pneus · CPK mediano do parque avaliado. MEDIANA e não média: um "
           "pneu fora da curva move a média o bastante para se inocentar")
_registrar("pneus_abaixo_limite", "Pneus abaixo do limite de sulco",
           "manutencao", "pneus", 0, "menor_melhor",
           _pneus("vencidos_n", de_troca=True),
           "Pneus · abaixo do limite interno de troca")
_registrar("trocas_pneus_30d", "Trocas de pneu previstas em 30 dias",
           "manutencao", "pneus", 0, "menor_melhor",
           _pneus("urgentes_30d", de_troca=True),
           "Pneus · previsão pelo desgaste medido. É planejamento de caixa, "
           "não alarme")

# ---- RH: o que a hora extra e a diária custam, e quem está indo embora.
_registrar("horas_extras_mes", "Horas extras no mês", "rh",
           "R$", 0, "menor_melhor",
           _aninhado("api.queries_folha", "get_horas_extras",
                     "kpis.total_mes"),
           "Horas Extras · valor lançado na competência")
_registrar("he_pct_folha", "Horas extras sobre a folha", "rh",
           "%", 1, "menor_melhor",
           _aninhado("api.queries_folha", "get_horas_extras",
                     "kpis.pct_proventos"),
           "Horas Extras · a RÉGUA. O valor absoluto cresce com o quadro; o "
           "percentual diz se a operação está se apoiando em hora extra")
_registrar("diarias_mes", "Diárias de motorista no mês", "rh",
           "R$", 0, "menor_melhor", _diarias("total"),
           "Jornada · diária paga na folha, mês corrente")
_registrar("diaria_por_dia", "Diária por dia trabalhado", "rh",
           "R$", 2, "menor_melhor", _diarias("por_dia"),
           "Jornada · diária paga ÷ dias trabalhados de quem a jornada "
           "enxerga. É razão, então não se move com o tamanho da frota")
_registrar("turnover", "Turnover 12 meses", "rh",
           "%", 1, "menor_melhor",
           _aninhado("api.queries_folha", "get_headcount",
                     "kpis.turnover_pct"),
           "Headcount · desligamentos sobre o quadro, 12 meses. É o indicador "
           "mais estratégico do RH: rotatividade alta reaparece como custo de "
           "treinamento, sinistro e hora extra três meses depois")


def fontes_publicas() -> list[dict]:
    """O catálogo, para a tela de cadastro de indicador."""
    return [f.como_dict() for f in FONTES.values()]


def ler_fonte(chave: str) -> float | None:
    """O valor de uma fonte AGORA, ou `None` se ela não respondeu.

    Falha de fonte NÃO derruba o painel: uma consulta ruim numa terça não pode
    apagar as outras onze linhas da reunião. O que ela produz é uma célula
    vazia, dita como vazia.
    """
    f = FONTES.get(chave)
    if f is None:
        return None
    try:
        return f.ler()
    except Exception as exc:  # noqa: BLE001
        log.warning("fonte %s falhou: %s", chave, type(exc).__name__)
        return None
