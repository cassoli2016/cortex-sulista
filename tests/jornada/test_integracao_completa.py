"""A integração RasterJOR inteira — os nove recursos e o que cada um custa.

O QUE MUDOU EM 08/09/2026
=========================
O CÓRTEX coletava 4 dos 11 endpoints que a RasterJOR publica. Os outros viviam
numa ETL do ERP que morreu sem alarme nenhum — a diária por dia em 12/02/2026,
as anomalias do fornecedor em 27/05/2025 — e o sintoma de todas foi o mesmo:
uma tela vazia, que se lê como "ninguém rodou".

Entraram cinco: `diarias`, `eventos` (as macros), `excecoes`, `anomalias` e
`veiculos`. Este arquivo guarda as decisões que não se explicam sozinhas.

AS TRÊS QUE MAIS CUSTAM SE ERRADAS
==================================
1. **A diária é pedida UM DIA POR VEZ.** O endpoint AGREGA o período: pedindo o
   mês, ele responde "12 meias e 4 inteiras", sem dizer em que dias. Quem
   "otimizar" para pedir a semana e distribuir estará inventando datas — e data
   inventada vira gráfico.
2. **`/vehicles/` é o único recurso que responde AGORA**, e por isso tem
   cadência própria (5 min, que é o teto do próprio endpoint). Pela cadência
   normal de 12 horas o painel de TV não ficaria desatualizado: ficaria VAZIO,
   porque a régua de frescor dele é de 30 minutos.
3. **Nenhuma tabela guarda `cid`.** O contrato de ausência tem o campo, ele é
   dado de saúde, e o repositório do código é PÚBLICO.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest

from api.jornada import cliente, coleta, tempo_real

RAIZ = Path(__file__).resolve().parent.parent.parent
MIGRATION = RAIZ / "sql" / "cortex" / "0075_jornada_completa.sql"


# ── o catálogo e os gravadores andam juntos ─────────────────────────────────


def test_todo_recurso_tem_entrada_no_CATALOGO():
    """Recurso em `RECURSOS` sem entrada no catálogo levanta na coleta, mas só
    quando alguém rodar aquele recurso — e a coleta engole exceção de propósito,
    então a falha vira uma linha `ok=0` que ninguém lê no mesmo dia."""
    faltam = [r for r in cliente.RECURSOS if r not in cliente.CATALOGO]
    assert not faltam, "sem entrada no CATALOGO: %s" % faltam


def test_todo_recurso_tem_GRAVADOR_menos_a_diaria():
    """A diária fica fora do mapa DE PROPÓSITO: o gravador dela precisa saber
    que dia está gravando, e o dia não vem no payload. Deixá-la fora é o que
    impede alguém de chamá-la pelo caminho genérico e gravar o dia errado."""
    esperado = set(cliente.RECURSOS) - {"diarias"}
    assert set(coleta._GRAVA) == esperado
    assert "diarias" not in coleta._GRAVA


def test_a_lista_do_D_MENOS_1_e_DERIVADA_e_nao_escrita_a_mao():
    """Lista paralela envelhece em silêncio: no dia em que alguém acrescentar um
    recurso, ela continuaria dizendo que ele é de tempo real (ou não é)."""
    assert cliente.RECURSO_TEMPO_REAL in cliente.RECURSOS
    assert cliente.RECURSO_TEMPO_REAL not in cliente.RECURSOS_D_MENOS_1
    assert set(cliente.RECURSOS_D_MENOS_1) == set(cliente.RECURSOS) - {
        cliente.RECURSO_TEMPO_REAL}


def test_cada_recurso_declara_os_NOMES_DE_DATA_que_a_API_usa():
    """A API não padroniza os parâmetros de data nem dentro dela mesma: há TRÊS
    pares em uso. Um recurso que declare o par errado devolve o período inteiro
    (a API ignora o desconhecido) sem erro nenhum — a coleta traz tudo e a
    trilha registra sucesso."""
    esperado = {
        "jornadas": ("from_date", "to_date"),
        "inconformidades": ("start", "end"),
        "ausencias": ("start", "end"),
        "diarias": ("data_inicial", "data_final"),
        "eventos": ("from_date", "to_date"),
        "excecoes": ("data_inicial", "data_final"),
        "anomalias": ("from_date", "to_date"),
    }
    for recurso, (de, ate) in esperado.items():
        cfg = cliente.CATALOGO[recurso]
        assert (cfg["de"], cfg["ate"]) == (de, ate), recurso
    # os dois de CADASTRO não aceitam janela
    for recurso in ("motoristas", "veiculos"):
        cfg = cliente.CATALOGO[recurso]
        assert cfg["de"] is None and cfg["ate"] is None, recurso


def test_quem_e_cadastro_sai_do_CATALOGO_e_nao_de_um_if():
    """O laço da coleta decidia a janela por `recurso == "motoristas"`. Foi isso
    que fez `veiculos` — o segundo cadastro — nascer pedindo data."""
    fonte = Path(coleta.__file__).read_text(encoding="utf-8")
    assert 'recurso == "motoristas"' not in fonte, (
        "a janela voltou a sair de um nome escrito à mão no laço")
    assert 'cfg.get("de") and cfg.get("ate")' in fonte


# ── a diária: um dia por chamada ────────────────────────────────────────────


def test_a_diaria_e_pedida_UM_DIA_POR_VEZ():
    """A regressão mais provável do módulo, e a que não tem sintoma: pedir a
    semana devolve o agregado dela, e distribuí-lo pelos dias inventa datas que
    depois viram gráfico e acusação."""
    pedidos = []

    def _falso(recurso, *, de=None, ate=None):
        pedidos.append((recurso, de, ate))
        return [{"periodo": {}, "motoristas": []}], 5

    orig = coleta.cliente.chamar
    coleta.cliente.chamar = _falso
    try:
        coleta._passagem_diarias(None, "2026-03-01", "2026-03-05", "ts")
    finally:
        coleta.cliente.chamar = orig

    assert len(pedidos) == 5, "a janela de 5 dias não virou 5 chamadas"
    for _, de, ate in pedidos:
        assert de == ate, "pediu um intervalo, e o retorno seria um agregado"
    assert [p[1] for p in pedidos] == [
        "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]


def test_a_diaria_grava_o_dia_QUE_LHE_FOI_DADO():
    """O payload não tem data. Se o gravador procurasse uma ali, acharia `None`
    e a coluna ficaria nula sem erro nenhum."""
    gravados = []

    class _Cur:
        def execute(self, sql, args):
            gravados.append(args)

    env = [{"periodo": {"data_inicial": "2026-03-10T00:00:00"},
            "motoristas": [{"cpf": "123", "nome": "FULANO",
                            "diarias": [{"tipo": "Meia", "pais": "BR",
                                         "quantidade": 1,
                                         "valor_unitario": 53.72,
                                         "valor_total": 53.72}]}]}]
    n = coleta._grava_diarias(_Cur(), env, "ts", "api", date(2026, 3, 1))
    assert n == 1
    # (documento, data, tipo, pais, …) — a data é a do parâmetro, não a do
    # `periodo` do payload, que aqui aponta para outro dia de propósito
    assert gravados[0][1] == date(2026, 3, 1)


# ── o dado de saúde que não entra ───────────────────────────────────────────


def test_NENHUMA_tabela_nova_guarda_o_CID():
    """O contrato de ausência tem `cid` — diagnóstico médico. O coletor já o
    ignorava; a migration não pode reintroduzi-lo por descuido. O repo é
    público."""
    sql = MIGRATION.read_text(encoding="utf-8")
    assert not re.search(r"^\s*cid\s+\w", sql, re.M), (
        "uma tabela nova ganhou coluna `cid`: é dado de saúde")
    fonte = Path(coleta.__file__).read_text(encoding="utf-8")
    assert '"cid"' not in fonte and "'cid'" not in fonte


# ── a escrita ───────────────────────────────────────────────────────────────


def test_a_escrita_e_uma_porta_SEPARADA_da_leitura():
    """`chamar()` é lido como seguro em todo o módulo. Se ele aceitasse método,
    uma chamada de leitura com argumento errado viraria escrita no sistema do
    fornecedor — e o erro só apareceria depois, no dado dele."""
    import inspect
    assinatura = inspect.signature(cliente.chamar)
    assert "metodo" not in assinatura.parameters
    assert set(cliente.ESCRITAS) == {"criar_ausencia", "apagar_ausencia"}


def test_a_tela_NUNCA_manda_o_caminho():
    """A regra do playground de fornecedor: a tela manda a AÇÃO, o servidor
    monta a URL. Caminho vindo de fora é o que transforma um endpoint de leitura
    em qualquer endpoint."""
    import inspect
    p = inspect.signature(cliente.enviar).parameters
    assert set(p) == {"acao", "corpo", "external_pk"}
    with pytest.raises(cliente.RasterIndisponivel):
        cliente.enviar("/external-api/absences/")


def test_criar_ausencia_RECUSA_enquanto_o_codigo_do_tipo_for_desconhecido():
    """O bloqueio que impede escrever hoje, e por que ele é uma recusa e não um
    palpite: `POST /absences/` exige `type_id` (inteiro) e a OpenAPI não publica
    a tabela que liga o código ao nome. Criar com o tipo errado altera a
    apuração do motorista no sistema do fornecedor e só se desfaz apagando."""
    assert cliente.TIPOS_AUSENCIA == {}, (
        "quando a tabela chegar, ela entra aqui e a recusa some sozinha")
    with pytest.raises(cliente.TipoDeAusenciaDesconhecido) as e:
        cliente.tipo_de_ausencia("ATESTADO MEDICO")
    assert "type_id" in str(e.value), "a recusa precisa dizer o que falta"


def test_apagar_valida_o_id_ANTES_de_virar_segmento_de_URL():
    with pytest.raises(cliente.RasterIndisponivel):
        cliente.enviar("apagar_ausencia", external_pk="../../outra-coisa")


# ── ler o CORPO, não o status ───────────────────────────────────────────────


def test_HTTP_400_com_mensagem_e_RECUSA_e_nao_queda_do_fornecedor():
    """Medido em 08/09/2026: `/vehicles/` recusa consulta frequente com HTTP
    **400** e `{"mensagem": "Faltam 5 minutos…"}`. Tratar isso como
    indisponibilidade acende, na Saúde, alarme de integração parada por causa de
    um freio de cinco minutos — o fornecedor estava são e só pediu para
    esperar."""
    fonte = Path(cliente.__file__).read_text(encoding="utf-8")
    i = fonte.index("except urllib.error.HTTPError")
    trecho = fonte[i:i + 1400]
    assert "_CHAVES_RECUSA" in trecho, (
        "o corpo do 4xx voltou a ser ignorado: status decidindo sozinho")
    assert "RasterRecusou" in trecho


# ── o tempo real ────────────────────────────────────────────────────────────


def test_a_duracao_do_evento_passa_de_24_HORAS():
    """Medido: um motorista EM REPOUSO aparecia como "101:32". Tratar isso como
    hora de relógio devolveria lixo."""
    assert tempo_real._minutos("101:32") == 101 * 60 + 32
    assert tempo_real._minutos("00:44") == 44
    assert tempo_real._minutos("") is None
    assert tempo_real._minutos("nao é hora") is None


def test_SO_a_direcao_continua_tem_cor():
    """Num painel ligado o dia inteiro, toda cor que não significa nada ensina a
    ignorar as que significam. Repouso longo é folga, não infração."""
    assert tempo_real._semaforo("EM DIREÇÃO", 400) == "ruim"      # > 5h30
    assert tempo_real._semaforo("EM DIREÇÃO", 300) == "atencao"   # > 4h30
    assert tempo_real._semaforo("EM DIREÇÃO", 60) == "bom"
    assert tempo_real._semaforo("EM REPOUSO", 9077) == ""
    assert tempo_real._semaforo("PARADO EM JORNADA", 5000) == ""


def test_o_limite_e_o_da_LEI_13103_e_o_aviso_abre_ANTES():
    """5h30 é o teto legal de direção contínua. O amarelo abre uma hora antes
    porque é o tempo de alguém falar com o motorista — alerta que acende junto
    com a infração não serve para evitá-la."""
    assert tempo_real.DIRECAO_CONTINUA_MAX_MIN == 330
    assert tempo_real.DIRECAO_CONTINUA_AVISO_MIN == 270
    assert tempo_real.DIRECAO_CONTINUA_AVISO_MIN < tempo_real.DIRECAO_CONTINUA_MAX_MIN


def test_o_denominador_e_QUEM_REPORTA_e_o_resto_e_dito():
    """São 175 veículos no cadastro e ~20 reportando, com idade de posição
    bimodal (mediana 4 min, p90 169 DIAS). "12% da frota em direção" seria um
    número falso sobre uma frota que não está toda em operação."""
    agora = datetime.now()
    recente = agora.strftime("%d/%m/%Y %H:%M:%S") + " - 0.02 km de PATIO"
    velho = "01/01/2026 03:00:00 - 5 km de OUTRO LUGAR"

    class _PG:
        @staticmethod
        def query(sql, params, esquema=None):
            if "jor_veiculos" in sql:
                return [
                    {"placa": "AAA1A11", "motorista": "FULANO",
                     "ultima_posicao": recente, "latitude": None,
                     "longitude": None, "evento_atual": "EM DIREÇÃO",
                     "evento_duracao": "01:00", "coletado_em": "t"},
                    {"placa": "BBB2B22", "motorista": "CICRANO",
                     "ultima_posicao": velho, "latitude": None,
                     "longitude": None, "evento_atual": "EM DIREÇÃO",
                     "evento_duracao": "01:00", "coletado_em": "t"},
                    {"placa": "CCC3C33", "motorista": "", "ultima_posicao": "",
                     "latitude": None, "longitude": None, "evento_atual": "",
                     "evento_duracao": "", "coletado_em": "t"},
                ]
            return []

    orig = tempo_real.pglocal
    tempo_real.pglocal = _PG
    try:
        d = tempo_real.agora()
    finally:
        tempo_real.pglocal = orig

    k = d["kpis"]
    assert k["frota"] == 3, "a frota inteira continua sendo dita"
    assert k["reportando"] == 1, "o veículo de janeiro entrou como se fosse agora"
    assert k["em_direcao"] == 1, "posição de meses atrás virou 'em direção'"
    assert k["mudos"] == 1, "quem parou de reportar precisa ser contado à parte"


def test_o_painel_de_TV_NAO_pode_servir_leitura_velha():
    """A tela publica MINUTOS. A regra da casa para essa resolução é a da torre
    e da portaria: número velho servido com tarja continua sendo número velho, e
    a decisão tomada sobre ele já foi tomada."""
    fonte = Path(tempo_real.__file__).read_text(encoding="utf-8")
    assert "velha_ate" not in fonte.split('"""', 2)[2], (
        "o módulo de tempo real ganhou rede de leitura velha")
    from api import main
    rota = Path(main.__file__).read_text(encoding="utf-8")
    i = rota.index('def jornada_tv(')
    corpo = rota[i:i + 1600]
    assert "@cached" not in corpo and "velha_ate" not in corpo


# ── a tela nova, e as listas que ela cobrou ─────────────────────────────────


def test_todo_painel_de_TV_esta_nas_DUAS_reguas():
    """Varredura, e não conferência de uma tela nomeada à mão.

    Havia um guard que checava `tvcli` nas duas listas `E_TV`. Ele passa com
    `tvjor` fora — lista escrita à mão que confere UM item não é varredura, e o
    painel que ficar de fora é medido pela régua errada: penalidade de tabela
    solta que não se aplica a mural, e limite de 900px em vez de 1050.
    """
    import importlib.util

    def _carrega(nome):
        cam = RAIZ / "scripts" / (nome + ".py")
        spec = importlib.util.spec_from_file_location(nome, cam)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    from api import auth
    tvs = {t for t in auth.TELAS if t.startswith("tv")}
    assert tvs, "nenhuma tela de TV encontrada em auth.TELAS"
    for mod in ("medir_paineis", "auditar_espacos"):
        fora = sorted(tvs - set(_carrega(mod).E_TV))
        assert not fora, "%s: painel de TV fora do E_TV: %s" % (mod, fora)


def test_a_lista_de_telas_de_TV_do_front_bate_com_o_RBAC():
    """`TELAS_TV` no `index.html` decide se a tela entra em modo mural e se ela
    se recarrega sozinha. Esquecer um painel ali não dá erro nenhum: ele abre
    com a barra lateral por cima, ou fica parado na tela para sempre."""
    html = (RAIZ / "api" / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const TELAS_TV = new Set\(\[([^\]]*)\]\)", html)
    assert m, "TELAS_TV sumiu do index.html"
    no_front = set(re.findall(r"'([a-z]+)'", m.group(1)))
    from api import auth
    no_rbac = {t for t in auth.TELAS if t.startswith("tv")}
    assert no_front == no_rbac, (
        "front %s × RBAC %s" % (sorted(no_front), sorted(no_rbac)))

    # E O MAPA DE RECARGA, que é a OUTRA metade e ficaria de fora.
    # `TELAS_TV` só responde "isto é um mural?". Quem responde "e quem o
    # redesenha a cada ciclo?" é `tvRecarregar`, e são duas listas: um painel
    # na primeira e fora da segunda entra em modo TV, esconde a barra lateral e
    # congela no primeiro quadro — a falha que ninguém vê, porque a tela está
    # bonita e parada na parede.
    i = html.index("function tvRecarregar(v){")
    mapa = html[i:html.index(chr(10) + "}", i)]   # até o limite real da função
    fora = sorted(t for t in no_rbac if (t + ":") not in mapa)
    assert not fora, "painel de TV sem carregador em tvRecarregar: %s" % fora
