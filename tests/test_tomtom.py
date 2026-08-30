"""TomTom: a chave vai na URL, e é isso que dita as regras deste módulo.

Gobrax, Monkey e Prolog mandam token em CABEÇALHO — registrar a URL era
inofensivo. Aqui é `?key=...`: a URL É a credencial, exatamente como na Z-API,
onde essa distinção custou uma manhã. `str(exc)` de `urllib` traz a URL, e a
mensagem de erro vai para a tela, para o log e para a trilha.

E há uma segunda armadilha, específica desta integração: o overlay dos painéis
carrega os tiles DIRETO do navegador, então a chave dele é pública por
construção e a defesa recomendada é restringi-la por domínio. Chave restrita
por domínio **não funciona chamada pelo servidor** — volta 403, que se lê como
"chave errada" e manda conferir o que está certo.
"""
from __future__ import annotations

import urllib.error

import pytest

from api import credenciais
from api.tomtom import cliente, transito


@pytest.fixture
def cofre(tmp_path, monkeypatch):
    monkeypatch.setattr(credenciais, "CAMINHO", tmp_path / "cred.json")
    for n in ("TOMTOM_API_KEY", "TOMTOM_API_KEY_SERVIDOR"):
        monkeypatch.delenv(n, raising=False)
    return tmp_path


# ── o segredo na URL ────────────────────────────────────────────────────────


def test_a_chave_NAO_sobrevive_a_mensagem_de_erro(cofre):
    """O teste que a Z-API ensinou: reproduzir o erro com a URL dentro."""
    credenciais.gravar("TOMTOM_API_KEY", "chave-secreta-de-teste-1234")
    texto = cliente._sanitizar(
        "<urlopen error> https://api.tomtom.com/x?point=1,2&"
        "key=chave-secreta-de-teste-1234")
    assert "chave-secreta-de-teste-1234" not in texto
    assert "***" in texto


def test_as_DUAS_chaves_sao_varridas_sempre(cofre):
    """Limpar só a da vez é a brecha que ninguém revisaria: com dois valores
    possíveis o mesmo texto passa por caminhos diferentes."""
    credenciais.gravar("TOMTOM_API_KEY", "chave-do-mapa-aaaaaaaa")
    credenciais.gravar("TOMTOM_API_KEY_SERVIDOR", "chave-do-servidor-bbbbbb")
    t = cliente._sanitizar("mapa=chave-do-mapa-aaaaaaaa srv=chave-do-servidor-bbbbbb")
    assert "chave-do-mapa" not in t and "chave-do-servidor" not in t


def test_key_DESCONHECIDA_na_url_tambem_e_mascarada(cofre):
    """A rede embaixo. `_sanitizar` só conhece as chaves DESTE processo; uma
    URL montada com outra (teste, ambiente errado, conta de terceiro) passaria
    inteira — e o vazamento que importa é o que ninguém previu."""
    t = cliente._sanitizar("https://api.tomtom.com/x?a=1&key=UMA-CHAVE-QUALQUER&b=2")
    assert "UMA-CHAVE-QUALQUER" not in t
    assert "b=2" in t, "mascarou demais: comeu o resto da querystring"


def test_mascara_no_FIM_da_url_sem_e_comercial(cofre):
    t = cliente._sanitizar("https://api.tomtom.com/x?point=1,2&key=ULTIMA-COISA")
    assert "ULTIMA-COISA" not in t and t.endswith("***")


# ── sem chave é instalação incompleta, não falha ────────────────────────────


def test_sem_chave_RECUSA_dizendo_onde_configurar(cofre):
    assert cliente.configurado() is False
    with pytest.raises(cliente.TomTomNaoConfigurado, match="Gestão"):
        cliente.fluxo(-26.3, -48.8)


def test_a_chave_do_SERVIDOR_vence_a_do_mapa(cofre):
    credenciais.gravar("TOMTOM_API_KEY", "chave-do-mapa-aaaaaaaa")
    assert cliente.chave_servidor() == "chave-do-mapa-aaaaaaaa"
    assert cliente.usando_a_chave_do_mapa() is True
    credenciais.gravar("TOMTOM_API_KEY_SERVIDOR", "chave-do-servidor-bbbbbb")
    assert cliente.chave_servidor() == "chave-do-servidor-bbbbbb"
    assert cliente.usando_a_chave_do_mapa() is False


def test_403_com_a_chave_do_mapa_EXPLICA_o_motivo(cofre, monkeypatch):
    """403 sem explicação manda conferir uma chave que está correta. O caso é
    previsível — chave pública restrita por domínio — e a mensagem tem de
    dizê-lo ANTES de alguém passar a tarde nisso."""
    credenciais.gravar("TOMTOM_API_KEY", "chave-do-mapa-aaaaaaaa")

    def explode(*a, **k):
        raise urllib.error.HTTPError("https://api.tomtom.com/x?key=chave-do-mapa-aaaaaaaa",
                                     403, "Forbidden", {}, None)
    monkeypatch.setattr(cliente.urllib.request, "urlopen", explode)
    with pytest.raises(cliente.TomTomIndisponivel) as e:
        cliente.fluxo(-26.3, -48.8)
    msg = str(e.value)
    assert "403" in msg and "restrita por domínio" in msg
    assert "chave-do-mapa-aaaaaaaa" not in msg


# ── a leitura do trânsito ───────────────────────────────────────────────────


def test_o_que_separa_e_a_RAZAO_e_nao_a_velocidade():
    """40 km/h é bom numa serra e péssimo numa reta."""
    serra = transito.classificar(40, 45, 0.9)
    reta = transito.classificar(40, 110, 0.9)
    assert serra["estado"] == "livre"
    assert reta["estado"] == "congestionado"


def test_CONFIANCA_BAIXA_nao_vira_estado():
    """A própria TomTom diz que a medida é fraca. Pintar de verde ou de
    vermelho seria inventar — é o "0% de retorno vazio" do terceiro, que
    aparecia como melhor da tabela e era ausência de lançamento."""
    r = transito.classificar(20, 100, 0.2)
    assert r["estado"] == "nd" and r["razao"] is None
    assert "confiança" in r.get("motivo", "")


def test_PARADO_e_diferente_de_congestionado():
    """Fila parada e trânsito arrastando pedem decisões diferentes de quem
    pode mandar desviar."""
    assert transito.classificar(3, 100, 0.9)["estado"] == "parado"
    assert transito.classificar(30, 100, 0.9)["estado"] == "congestionado"


def test_via_FECHADA_vence_qualquer_velocidade():
    r = transito.classificar(80, 100, 0.9, fechada=True)
    assert r["estado"] == "bloqueado"


def test_sem_velocidade_de_referencia_e_ND_e_nao_zero():
    assert transito.classificar(50, 0, 0.9)["estado"] == "nd"
    assert transito.classificar(None, 100, 0.9)["estado"] == "nd"


def test_o_payload_traz_o_ATRASO_que_e_o_que_soma():
    """Velocidade não soma ao longo da rota; segundo perdido soma."""
    d = transito.do_payload({"flowSegmentData": {
        "currentSpeed": 30, "freeFlowSpeed": 100, "confidence": 0.9,
        "currentTravelTime": 300, "freeFlowTravelTime": 90, "frc": "FRC1"}})
    assert d["estado"] == "congestionado"
    assert d["atraso_s"] == 210


def test_o_DENOMINADOR_do_resumo_sao_os_MEDIDOS():
    """Contar quem não tem medida como "livre" diria que está tudo bem por
    falta de dado — o erro dos 664 rastreadores "sem sinal"."""
    r = transito.resumo([
        {"estado": "livre", "atraso_s": 0},
        {"estado": "congestionado", "atraso_s": 600},
        {"estado": "nd"}, {"estado": "nd"}, {"estado": "nd"},
    ])
    assert r["medidos"] == 2 and r["sem_medida"] == 3
    assert r["pct_problema"] == 50.0, "o pct tem de ser sobre os medidos"
    assert r["atraso_total_min"] == 10.0


def test_resumo_SEM_NENHUMA_medida_nao_inventa_percentual():
    r = transito.resumo([{"estado": "nd"}, {"estado": "nd"}])
    assert r["pct_problema"] is None


# ── o que NÃO se afirma ─────────────────────────────────────────────────────


def test_o_modulo_NAO_afirma_condicao_de_PAVIMENTO():
    """A TomTom mede FLUXO. Derivar buraco de estrada a partir de velocidade
    seria afirmar o que a fonte não disse — o mesmo erro de dizer há quantas
    horas sumiu um veículo que a API nunca reportou."""
    import inspect
    fonte = inspect.getsource(transito)
    for palavra in ("pavimento", "asfalto", "buraco"):
        # só pode aparecer no texto que EXPLICA que não se mede isso
        for linha in fonte.splitlines():
            if palavra in linha.lower():
                assert "não" in linha.lower() or "NÃO" in linha, linha


# ── incidentes: o número grande e a quebra que o desarma ────────────────────


AMOSTRA = {"incidents": [
    {"properties": {"iconCategory": 8, "magnitudeOfDelay": 4, "delay": None,
                    "from": "PR-423", "to": "Rua São Luiz", "roadNumbers": [],
                    "events": [{"description": "Encerrado/a"}]}},
    {"properties": {"iconCategory": 8, "magnitudeOfDelay": 4, "delay": None,
                    "from": "BR-101", "to": "BR-101", "roadNumbers": ["BR-101"],
                    "events": [{"description": "Encerrado/a"}]}},
    {"properties": {"iconCategory": 6, "magnitudeOfDelay": 2, "delay": 300,
                    "from": "BR-116", "to": "BR-116", "roadNumbers": ["BR-116"],
                    "events": [{"description": "Trânsito lento"}]}},
    {"properties": {"iconCategory": 9, "magnitudeOfDelay": 1, "delay": 60,
                    "from": "Rua X", "to": "Rua Y", "roadNumbers": [],
                    "events": [{"description": "Obras"}]}},
]}


def test_o_total_vem_SEMPRE_com_a_quebra_por_categoria():
    """Medido numa caixa real: 194 incidentes, 173 de UMA categoria. "194
    ocorrências na malha" é verdadeiro e inútil; "173 estradas fechadas" é
    alarmante e enganoso. O número grande vem com a quebra que o desarma."""
    r = transito.ler_incidentes(AMOSTRA)
    assert r["total"] == 4
    assert r["por_categoria"]["Via fechada"] == 2
    assert list(r["por_categoria"])[0] == "Via fechada", "o maior vem primeiro"


def test_o_recorte_que_decide_e_EM_RODOVIA():
    """Fechamento de rua não muda a viagem de um caminhão — e é ele que domina
    a contagem bruta."""
    r = transito.ler_incidentes(AMOSTRA)
    assert r["bloqueios"] == 2
    assert r["bloqueios_em_rodovia"] == 1


def test_CHUVA_E_VENTO_nao_contam_como_bloqueio():
    """Estão na lista da TomTom e são condição de TEMPO, não interdição.
    Misturá-los faria um dia chuvoso parecer um dia de malha travada."""
    r = transito.ler_incidentes({"incidents": [
        {"properties": {"iconCategory": 4, "events": []}},
        {"properties": {"iconCategory": 10, "events": []}}]})
    assert r["bloqueios"] == 0
    assert r["total"] == 2, "continuam aparecendo, só não contam como bloqueio"


def test_atraso_NULO_continua_nulo_e_nao_vira_zero():
    """A API não estima atraso para fechamento sem previsão de reabertura.
    Zero ali diria "não atrasa nada", que é o oposto."""
    r = transito.ler_incidentes(AMOSTRA)
    assert r["itens"][0]["atraso_s"] is None


def test_o_idioma_e_pt_PT_porque_pt_BR_e_RECUSADO():
    """MEDIDO: a API devolve HTTP 400 "Unsupported language parameter value"
    para `pt-BR` e para `pt`. O valor óbvio é o errado, e quem for ajustar vai
    tentar `pt-BR` primeiro."""
    assert cliente.IDIOMA == "pt-PT"
