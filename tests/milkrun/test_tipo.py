"""Milk run x coleta simples: a regra e o que ela NAO pode fazer.

A mesma tabela do ERP guarda as duas coisas. O criterio combinado com a
operacao e o numero de paradas da solicitacao (> 1 = milk run). O risco nao e
errar a conta — e classificar DEPOIS dos filtros da tela, que faria a natureza
da operacao mudar conforme quem esta olhando.
"""
import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SERVICO = RAIZ / "api" / "milkrun" / "servico.py"
HTML = RAIZ / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def fonte() -> str:
    return SERVICO.read_text(encoding="utf-8")


def test_a_natureza_e_medida_antes_dos_filtros(fonte):
    """`paradas_total` sai de `c["pontos"]` (as paradas ORIGINAIS) e nao de
    `pts` (as que sobraram do filtro). Um milk run de quatro paradas filtrado
    por um fornecedor mostra uma parada so; medido depois do filtro ele viraria
    'coleta simples' e a tela mentiria sobre o que a operacao e."""
    m = re.search(r"paradas_total = len\((.*?)\)", fonte)
    assert m, "paradas_total nao encontrado"
    assert m.group(1) == 'c["pontos"]', (
        f"paradas_total medido sobre {m.group(1)} — tem de ser as paradas "
        "originais, antes de _passa()")

    # e a atribuicao vem ANTES da linha que aplica o filtro
    i_total = fonte.index("paradas_total = len(")
    i_filtro = fonte.index('pts = [x for x in c["pontos"] if _passa(x)]')
    assert i_total < i_filtro


def test_o_corte_e_mais_de_uma_parada(fonte):
    assert "e_milk = paradas_total > 1" in fonte


def test_a_rota_recusa_tipo_desconhecido():
    """Tipo invalido devolve 422 em vez de cair no `else` e mostrar tudo — um
    erro de digitacao no link nao pode virar recorte silencioso."""
    main = (RAIZ / "api" / "main.py").read_text(encoding="utf-8")
    assert 'if (tipo or "") not in ("milk", "simples", ""):' in main


def test_a_tela_diz_quantas_ficaram_de_fora():
    """Trocar o recorte derruba o total de 234 para 147; sem dizer o que saiu,
    parece dado faltando."""
    html = HTML.read_text(encoding="utf-8")
    assert "fora_simples" in html and "fora_milk" in html
    assert "coleta(s) simples fora" in html


def test_o_padrao_da_tela_e_milk_run():
    """A tela se chama Milk Run: abrir mostrando 87 fretes ponto a ponto no
    meio contraria o proprio nome."""
    html = HTML.read_text(encoding="utf-8")
    assert '<option value="milk" selected>' in html
    fonte_ = SERVICO.read_text(encoding="utf-8")
    arvore = ast.parse(fonte_)
    fn = next(n for n in ast.walk(arvore)
              if isinstance(n, ast.FunctionDef) and n.name == "get_milkrun")
    nomes = [a.arg for a in fn.args.args]
    padroes = dict(zip(nomes[-len(fn.args.defaults):],
                       [ast.literal_eval(d) for d in fn.args.defaults]))
    assert padroes["tipo"] == "milk"


def test_nenhum_parametro_de_get_milkrun_e_reatribuido():
    """Guarda contra o sombreamento que ja aconteceu: `placa` (filtro) foi
    sobrescrito pelo veiculo da linha e a tela passou a se filtrar sozinha,
    de 17 solicitacoes para 2, sem erro nenhum."""
    arvore = ast.parse(SERVICO.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arvore)
              if isinstance(n, ast.FunctionDef) and n.name == "get_milkrun")
    params = {a.arg for a in fn.args.args}
    for no in ast.walk(fn):
        if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Store):
            assert no.id not in params, (
                f"'{no.id}' e parametro de get_milkrun e foi reatribuido na "
                f"linha {no.lineno} — use outro nome")


def test_a_posicao_do_veiculo_e_a_de_agora_e_nao_a_do_periodo(fonte):
    """Com um periodo passado no filtro, mostrar a ultima posicao DO PERIODO
    poria o caminhao onde ele esteve — pior do que nao mostrar."""
    assert "POS_ATUAL_SQL" in fonte
    assert "veiculo_ultimaposicaomacro" in fonte
    # a consulta do rastro do periodo tem janela; a da posicao atual, nao
    i = fonte.index("POS_ATUAL_SQL")
    bloco = fonte[i:fonte.index('"""', fonte.index('"""', i) + 3)]
    assert "%(de)s" not in bloco and "%(ate)s" not in bloco


def test_a_legenda_nao_conta_o_mesmo_veiculo_duas_vezes():
    """'veiculo agora 26' + 'sem posicao recente 1' somava 27 sobre 26 placas:
    o desatualizado estava dentro do total."""
    html = HTML.read_text(encoding="utf-8")
    assert "veículo agora <b>${nVeic-nVelho}</b>" in html


# ---------------------------------------------------------------- % realizado
def test_coleta_vencida_e_nao_feita_PESA_no_indice(fonte):
    """O denominador era `coletadas + frustradas`. A pendente que ja passou da
    hora ficava de fora e sumia da conta em vez de pesar: em 21/08/2026 havia
    14 coletas, 8 feitas e 6 vencidas sem coleta, e a tela dizia 100%."""
    assert "def _pct(concluidos: int, frustrados: int, vencidas: int)" in fonte
    assert "den = concluidos + frustrados + vencidas" in fonte


def test_parada_que_ainda_nao_venceu_fica_fora_do_denominador(fonte):
    """A outra ponta, que a regra original ja acertava: parada das 15h nao
    conta contra a operacao as 11h da manha."""
    assert "def _venceu(" in fonte
    i = fonte.index("def _venceu(")
    corpo = fonte[i:fonte.index("\ndef ", i + 5)]
    assert "prev < agora.isoformat()" in corpo
    assert 'return bool(prev)' in corpo, "sem horario agendado nao ha vencimento"


def test_dia_em_andamento_e_marcado(fonte):
    """100% num dia que ainda esta correndo significa '100% do que venceu', e
    sem dizer isso um dia 27% cumprido sai verde e completo."""
    assert '"em_andamento"' in fonte and '"a_vencer"' in fonte


def test_a_tela_nao_pinta_de_verde_o_dia_em_andamento():
    html = HTML.read_text(encoding="utf-8")
    assert "(x.pct_realizado==null || x.em_andamento) ? 'var(--n700)'" in html
    assert "em andamento · faltam" in html
