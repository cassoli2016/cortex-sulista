"""Auditoria de USO — as regras que separam um indicador de um número bonito.

O `audit_log` sempre soube quem MEXEU no sistema. O que não havia era quem
USA: quantos acessos, de quanta gente, por quanto tempo, em que telas. Cada
teste daqui guarda uma decisão que, errada, produziria um número que ninguém
conferiria — e é justamente o número que se olha para decidir treinamento,
licença e o que tirar do menu.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api import auditoria


@pytest.fixture
def cena(esquema_pg, monkeypatch):
    from api import auth
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(auditoria, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute("SELECT id FROM perfis LIMIT 1").fetchone()["id"]
        uid = c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES(%s,%s,%s,%s,1,0,%s) RETURNING id""",
            ("Fulano", "fulano@sulista.com.br", "x", perfil, auditoria._agora()),
        ).fetchone()["id"]
    return {"uid": uid, "email": "fulano@sulista.com.br"}


def _mexer(sid: int, **campos):
    """Reescreve carimbos da sessão — o relógio é o que estes testes controlam."""
    sets = ", ".join(f"{k}=%s" for k in campos)
    with auditoria._conn() as c:
        c.execute(f"UPDATE aud_sessoes SET {sets} WHERE id=%s",
                  (*campos.values(), sid))


def _ts(**kw) -> str:
    return (datetime.now() - timedelta(**kw)).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# A duração — o número que só existe porque não se confia no logout
# ---------------------------------------------------------------------------

def test_duracao_vai_ate_o_ULTIMO_SINAL_e_nao_ate_agora(cena):
    """391 logins para 11 logouts: ninguém sai pelo botão. Se a duração fosse
    `agora − início`, a aba esquecida aberta a noite toda viraria uma sessão de
    catorze horas e levaria a média junto."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    _mexer(sid, inicio=_ts(hours=9), visto_em=_ts(hours=8, minutes=30))
    k = auditoria.resumo(30)["kpis"]
    assert 1750 <= k["dur_mediana"] <= 1850, k["dur_mediana"]   # ~30 min


def test_saida_explicita_fecha_a_sessao_no_horario_da_saida(cena):
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    _mexer(sid, inicio=_ts(hours=3))
    auditoria.fechar_sessao(sid, "logout")
    with auditoria._conn() as c:
        r = c.execute("SELECT fim, fim_motivo FROM aud_sessoes WHERE id=%s",
                      (sid,)).fetchone()
    assert r["fim"] and r["fim_motivo"] == "logout"


def test_fechar_duas_vezes_nao_reescreve_o_fim(cena):
    """Sessão já encerrada não muda de horário: a trilha registra quando
    ACONTECEU, não a última vez que alguém chamou a função."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    auditoria.fechar_sessao(sid, "logout")
    with auditoria._conn() as c:
        primeiro = c.execute("SELECT fim FROM aud_sessoes WHERE id=%s", (sid,)).fetchone()["fim"]
    _mexer(sid, visto_em=_ts(minutes=1))
    auditoria.fechar_sessao(sid, "derrubada")
    with auditoria._conn() as c:
        r = c.execute("SELECT fim, fim_motivo FROM aud_sessoes WHERE id=%s", (sid,)).fetchone()
    assert r["fim"] == primeiro and r["fim_motivo"] == "logout"


# ---------------------------------------------------------------------------
# "Aberta agora" é CALCULADO
# ---------------------------------------------------------------------------

def test_sessao_sem_sinal_recente_nao_conta_como_aberta(cena):
    """Não há coluna de status: quem fecha a aba some sozinho da contagem.
    Status gravado precisaria de rotina para virar, e no dia em que ela não
    roda a tela mente."""
    viva = auditoria.abrir_sessao(cena["uid"], cena["email"])
    velha = auditoria.abrir_sessao(cena["uid"], cena["email"])
    _mexer(velha, visto_em=_ts(minutes=auditoria.JANELA_VIVA_MIN + 5))
    k = auditoria.resumo(30)["kpis"]
    assert k["abertas"] == 1, "a sessão sem sinal recente continuou 'aberta'"
    assert k["acessos"] == 2, "as duas continuam contando como ACESSO"
    auditoria.fechar_sessao(viva)


def test_sessao_encerrada_nao_conta_como_aberta(cena):
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    assert auditoria.resumo(30)["kpis"]["abertas"] == 1
    auditoria.fechar_sessao(sid)
    assert auditoria.resumo(30)["kpis"]["abertas"] == 0


# ---------------------------------------------------------------------------
# Telas: agregação, validação e o freio de escrita
# ---------------------------------------------------------------------------

def test_telas_sao_AGREGADAS_por_sessao(cena):
    """Quem vai e volta entre duas telas trinta vezes gera duas linhas, não
    trinta. As perguntas são as mesmas com um centésimo do volume."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    for _ in range(5):
        auditoria.registrar(sid, "home")
    auditoria.registrar(sid, "dre")
    with auditoria._conn() as c:
        linhas = c.execute("SELECT tela, aberturas FROM aud_telas "
                           "WHERE sessao_id=%s ORDER BY tela", (sid,)).fetchall()
    assert [(r["tela"], r["aberturas"]) for r in linhas] == [("dre", 1), ("home", 5)]


@pytest.mark.parametrize("lixo", [
    "<script>", "../../etc", "TELA", "a" * 40, "com espaco", "1home", "",
])
def test_tela_que_nao_e_chave_de_tela_nao_entra(cena, lixo):
    """O valor chega do navegador, e o que chega do navegador não é dado, é
    entrada: sem validar, a tabela vira depósito de qualquer string."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    auditoria.registrar(sid, lixo)
    with auditoria._conn() as c:
        n = c.execute("SELECT count(*) AS n FROM aud_telas WHERE sessao_id=%s",
                      (sid,)).fetchone()["n"]
    assert n == 0, f"{lixo!r} foi gravado como tela"


def test_visto_em_avanca_de_passo_em_passo(cena):
    """Duas telas abertas no mesmo minuto não são dois sinais de vida
    diferentes — escrever por clique faria a auditoria virar gargalo do
    próprio painel."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    with auditoria._conn() as c:
        antes = c.execute("SELECT visto_em FROM aud_sessoes WHERE id=%s", (sid,)).fetchone()["visto_em"]
    auditoria.registrar(sid, "home")          # logo depois do login
    with auditoria._conn() as c:
        depois = c.execute("SELECT visto_em FROM aud_sessoes WHERE id=%s", (sid,)).fetchone()["visto_em"]
    assert depois == antes, "o visto_em avançou dentro do passo"
    _mexer(sid, visto_em=_ts(minutes=10))     # agora está velho
    auditoria.registrar(sid, "dre")
    with auditoria._conn() as c:
        r = c.execute("SELECT visto_em FROM aud_sessoes WHERE id=%s", (sid,)).fetchone()["visto_em"]
    assert r > _ts(minutes=1), "o visto_em não avançou quando devia"


def test_sessao_encerrada_nao_recebe_mais_sinal(cena):
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    auditoria.fechar_sessao(sid)
    _mexer(sid, visto_em=_ts(minutes=30))
    auditoria.registrar(sid, "home")
    with auditoria._conn() as c:
        v = c.execute("SELECT visto_em FROM aud_sessoes WHERE id=%s", (sid,)).fetchone()["visto_em"]
    assert v < _ts(minutes=20), "sessão fechada voltou a receber sinal de vida"


# ---------------------------------------------------------------------------
# A série e as listas
# ---------------------------------------------------------------------------

def test_dia_sem_acesso_aparece_como_zero(cena):
    """O intervalo de dias é GERADO, não colhido: `GROUP BY` não devolve o dia
    sem linha, e a linha do gráfico emendaria por cima do buraco."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    _mexer(sid, inicio=_ts(days=3), visto_em=_ts(days=3))
    r = auditoria.resumo(7)
    assert len(r["serie"]) == 7, [x["dia"] for x in r["serie"]]
    assert sum(1 for x in r["serie"] if x["acessos"] == 0) == 6


def test_telas_sem_uso_lista_o_que_ninguem_abriu(cena):
    """Vale mais que o Top-N: as mais usadas confirmam o que já se imagina; as
    nunca abertas é que mudam decisão."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"])
    auditoria.registrar(sid, "home")
    sem = auditoria.telas_sem_uso({"home": ("Visão Geral", "Início"),
                                   "dre": ("DRE", "Controladoria")}, 30)
    assert [x["tela"] for x in sem] == ["dre"]


def test_falhas_de_login_vem_do_audit_log(cena):
    """A trilha de ações continua sendo a fonte — a auditoria de uso não
    duplica o que já é registrado."""
    from api import auth
    auth.audit("invasor@x.com", "login_falha", detalhe="senha_incorreta", ip="1.2.3.4")
    auth.audit("invasor@x.com", "login_falha", detalhe="senha_incorreta", ip="5.6.7.8")
    r = auditoria.resumo(30)
    assert r["kpis"]["falhas"] == 2
    assert r["falhas"][0]["email"] == "invasor@x.com" and r["falhas"][0]["ips"] == 2


def test_acoes_de_escrita_excluem_o_que_ja_e_acesso(cena):
    """Login, logout e falha já são medidos como ACESSO nas outras abas —
    contá-los de novo como 'ação' inflaria o indicador de uso do sistema."""
    from api import auth
    auth.audit("a@x.com", "login_ok")
    auth.audit("a@x.com", "logout")
    auth.audit("a@x.com", "usuario_editar", alvo="b@x.com")
    r = auditoria.resumo(30)
    assert [x["acao"] for x in r["acoes"]] == ["usuario_editar"]
    assert r["kpis"]["escritas"] == 1


# ---------------------------------------------------------------------------
# O que NÃO se guarda
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ua,esperado", [
    ("Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit/537 Chrome/120 Safari/537", "Chrome · Windows"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605 Version/17 Safari/604", "Safari · iPhone"),
    ("", ""),
])
def test_user_agent_entra_reduzido(ua, esperado):
    """A string inteira é longa, muda a cada atualização do navegador e não
    responde nada melhor que duas palavras. Guardar menos é a escolha certa
    quando o dado é sobre pessoas."""
    assert auditoria.resumir_agente(ua) == esperado


def test_snapshot_do_copiloto_nao_leva_email_nem_ip(cena):
    """O snapshot é o que pode sair para um modelo externo: só KPI escalar."""
    sid = auditoria.abrir_sessao(cena["uid"], cena["email"], ip="10.0.0.9")
    auditoria.registrar(sid, "home")
    sn = auditoria.snapshot_copiloto()
    texto = repr(sn)
    assert "@" not in texto and "10.0.0" not in texto, texto
    assert set(sn) == {"acessos_30d", "pessoas_30d", "sessao_mediana_min",
                       "sessoes_abertas", "escritas_30d", "falhas_login_30d",
                       "telas_usadas_30d"}


# ---------------------------------------------------------------------------
# A coleta nunca pode atrapalhar
# ---------------------------------------------------------------------------

def test_falha_ao_gravar_nao_derruba_o_login(cena, monkeypatch):
    """Trilha que impede de entrar vira trilha desligada."""
    def explode(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(auditoria, "_conn", explode)
    assert auditoria.abrir_sessao(1, "x@y.com") is None
    auditoria.fechar_sessao(1)          # não levanta
    auditoria.registrar(1, "home")      # não levanta


def test_sem_sessao_nao_grava_nada(cena):
    """Token antigo (emitido antes desta versão) não tem `sid`. Ele continua
    valendo — só não alimenta a auditoria de uso até o próximo login."""
    auditoria.registrar(None, "home")
    auditoria.fechar_sessao(None)
    with auditoria._conn() as c:
        assert c.execute("SELECT count(*) AS n FROM aud_telas").fetchone()["n"] == 0
