"""Proteção real dos arquivos de segredo — e por que a antiga era ficção.

O DEFEITO
=========
Cinco lugares do CÓRTEX gravavam segredo e chamavam `Path.chmod(0o600)`, com o
comentário "não legível por outros usuários da máquina". O servidor é Windows,
e ali `os.chmod` só liga o atributo SOMENTE-LEITURA — quem decide acesso é a
ACL. A frase era falsa há quanto tempo ninguém sabe, e o `CLAUDE.md` a repetia.

O teste que deveria ter pegado isso estava VERMELHO (`0o666`) e ninguém
reparava, porque media `st_mode` numa plataforma onde `st_mode` não quer dizer
nada. Teste que mede a coisa errada é pior que teste ausente: ele ocupa o lugar
do que faria falta.

O ACHADO, ao conferir de verdade, foi melhor do que o temido e pior do que
parecia: os arquivos ESTÃO restritos, mas por HERANÇA da pasta do usuário — não
porque o código pediu. Proteção por acidente sobrevive até o projeto mudar de
lugar.

DUAS DECISÕES QUE ESTES TESTES GUARDAM
======================================
1. **O que conta como exposição é GRUPO AMPLO**, não "qualquer um além do
   dono". A primeira régua acendeu vermelho em 24 certificados, e o "intruso"
   era a conta que opera o painel: os `.pfx` são gravados pela API, que roda
   como SISTEMA, então o dono é o SYSTEM e a pessoa aparecia como "mais
   alguém". Alarme que acende sem haver problema ensina a ignorar o alarme — e
   esse ia nascer com 24 falsos positivos, ou seja ia nascer ignorado.
2. **`proteger` é cirúrgica.** A primeira versão reconstruía a ACL e teria
   trancado a conta do painel — que não é administradora — para fora dos
   certificados, em silêncio, no próximo upload. Proteção que quebra o uso
   legítimo é desligada na semana seguinte.
"""
from __future__ import annotations

import subprocess

import pytest

from api import segredo_arquivo as sa

SID_USUARIOS = "S-1-5-32-545"   # o grupo local "Usuários"


@pytest.fixture
def arquivo(tmp_path):
    f = tmp_path / "segredo.json"
    f.write_text('{"token": "abc"}', encoding="utf-8")
    if not sa.WINDOWS:
        # No Windows da bancada o tmp herda a ACL restrita do perfil do
        # usuário — o "arquivo normal" já nasce protegido. No POSIX do CI o
        # umask 022 entrega 644, que o módulo acusa (corretamente) como
        # exposto: o equivalente do arquivo normal da bancada é 600. Sem
        # isto, seis testes quebravam no Ubuntu do CI — e ficaram dois dias
        # vermelhos sem ninguém abrir o log.
        f.chmod(0o600)
    return f


def _pula_sem_acl(estado):
    if estado["protegido"] is None:
        pytest.skip("ACL não legível nesta máquina")


# -- a régua ----------------------------------------------------------------


def test_conta_nomeada_com_acesso_NAO_e_exposicao():
    """A lição dos 24 falsos positivos. Numa máquina administrada por uma
    pessoa, a conta dela na lista de acesso é o caso normal."""
    assert not sa._e_grupo_amplo("S-1-5-21-1-2-3-1411")
    assert not sa._e_grupo_amplo(sa.SID_SYSTEM)
    assert not sa._e_grupo_amplo(sa.SID_ADMINS)


def test_grupo_amplo_E_exposicao():
    for sid in ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-4"):
        assert sa._e_grupo_amplo(sid), sid


def test_grupo_de_DOMINIO_e_pego_pelo_RID():
    """O SID inteiro de "Usuários do Domínio" muda a cada domínio, então lista
    fixa não o pegaria — e é justamente num domínio que ele significa a
    empresa toda."""
    assert sa._e_grupo_amplo("S-1-5-21-3169727703-4028349470-2347461087-513")


# -- o verificador ----------------------------------------------------------


def test_arquivo_normal_do_projeto_nao_acusa_nada(arquivo):
    _pula_sem_acl(sa.estado(arquivo))
    assert sa.estado(arquivo)["protegido"] is True


def test_ENXERGA_o_arquivo_exposto(arquivo):
    """Sem este, todo o resto passaria por vacuidade: um verificador que
    sempre diz "ok" dá a sensação de que está tudo conferido. Aqui o alvo é
    sabotado de propósito — em cada plataforma pela via dela."""
    _pula_sem_acl(sa.estado(arquivo))
    if not sa.WINDOWS:
        arquivo.chmod(0o644)          # a sabotagem POSIX: grupo+outros leem
        est = sa.estado(arquivo)
        assert est["protegido"] is False
        assert "644" in est["motivo"]
        return
    r = subprocess.run(["icacls", str(arquivo), "/grant", "*%s:(R)" % SID_USUARIOS],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("icacls indisponível")
    est = sa.estado(arquivo)
    assert est["protegido"] is False
    assert SID_USUARIOS in est["intrusos"]
    assert SID_USUARIOS in est["motivo"]


def test_nao_verificado_NAO_e_o_mesmo_que_protegido(arquivo, monkeypatch):
    """A resposta do meio é a que costuma sumir. Dizer "ok" sem medir é
    exatamente o erro que este módulo veio consertar, então `None` tem de
    chegar inteiro até a tela."""
    if not sa.WINDOWS:
        pytest.skip("só no Windows a ACL pode ficar ilegível")
    monkeypatch.setattr(sa, "_sids_com_acesso", lambda c: None)
    est = sa.estado(arquivo)
    assert est["protegido"] is None
    assert est["protegido"] is not False


def test_arquivo_que_nao_existe_nao_e_alarme(tmp_path):
    est = sa.estado(tmp_path / "nao-existe.json")
    assert est["existe"] is False and est["protegido"] is None


# -- a correção -------------------------------------------------------------


def test_proteger_REMOVE_o_grupo_amplo_e_preserva_o_conteudo(arquivo):
    _pula_sem_acl(sa.estado(arquivo))
    if not sa.WINDOWS:
        arquivo.chmod(0o644)
    else:
        r = subprocess.run(["icacls", str(arquivo), "/grant", "*%s:(R)" % SID_USUARIOS],
                           capture_output=True)
        if r.returncode != 0:
            pytest.skip("icacls indisponível")
    assert sa.estado(arquivo)["protegido"] is False
    assert sa.proteger(arquivo)["aplicado"] is True
    assert sa.estado(arquivo)["protegido"] is True
    assert arquivo.read_text(encoding="utf-8") == '{"token": "abc"}'


def test_proteger_NAO_TIRA_o_SYSTEM_nem_a_conta_que_usa(arquivo):
    """O ponto que a primeira versão errava: a API roda como SISTEMA e a conta
    do painel não é administradora. Tirar qualquer um dos dois derruba o
    sistema ou tranca a pessoa fora dos próprios segredos."""
    if not sa.WINDOWS:
        pytest.skip("SID e ACL nomeada são conceitos do Windows")
    _pula_sem_acl(sa.estado(arquivo))
    antes = set(sa.estado(arquivo)["quem"])
    sa.proteger(arquivo)
    depois = set(sa.estado(arquivo)["quem"])
    perdidos = {s for s in antes - depois if not sa._e_grupo_amplo(s)}
    assert not perdidos, perdidos


def test_proteger_e_IDEMPOTENTE(arquivo):
    """Gravar credencial é ação frequente. Reescrever ACL a cada gravação é
    risco sem contrapartida — sem grupo amplo, não roda `icacls` nenhum.
    No POSIX o chmod É a proteção inteira e repetir é inofensivo por
    natureza — lá o motivo estável é "modo 0600"."""
    _pula_sem_acl(sa.estado(arquivo))
    assert sa.proteger(arquivo) == sa.proteger(arquivo)
    esperado = "nada a remover" if sa.WINDOWS else "modo 0600"
    assert esperado in sa.proteger(arquivo)["motivo"]


def test_ACL_ilegivel_NAO_MEXE_em_nada(arquivo, monkeypatch):
    """Na dúvida, não mexer: escrever ACL às cegas dá para trancar o SYSTEM e
    derrubar a API inteira."""
    if not sa.WINDOWS:
        pytest.skip("só no Windows")
    monkeypatch.setattr(sa, "_sids_com_acesso", lambda c: None)
    chamou = []
    monkeypatch.setattr(sa.subprocess, "run",
                        lambda *a, **k: chamou.append(a) or (_ for _ in ()).throw(
                            AssertionError("não podia ter rodado icacls")))
    r = sa.proteger(arquivo)
    assert r["aplicado"] is False and "mantida como estava" in r["motivo"]


# -- o painel da Saúde ------------------------------------------------------


def test_panorama_lista_os_segredos_do_projeto():
    p = sa.panorama()
    if p["total"] == 0:
        # num clone limpo (o CI) não existe credenciais.json nem .pfx — zero
        # aqui é o estado correto de quem não tem segredo, não um defeito.
        # Na bancada de produção os arquivos existem e o assert roda inteiro.
        pytest.skip("clone limpo: nenhum arquivo de segredo no disco")
    rotulos = {i["rotulo"] for i in p["itens"]}
    assert "Cofre de credenciais" in rotulos


def test_os_certificados_sao_UMA_LINHA_e_nao_vinte_e_quatro():
    """Cartão com 24 linhas dizendo a mesma coisa é cartão que se aprende a
    pular — a lição dos nove SQLite migrados. O grupo leva o PIOR estado."""
    if not sa.certificados():
        pytest.skip("sem certificados nesta máquina")
    linhas = [i for i in sa.panorama()["itens"] if ".pfx" in i["rotulo"]]
    assert len(linhas) == 1, linhas
    assert "arquivo" in linhas[0]["arquivo"]


# -- o lote -----------------------------------------------------------------


def test_o_LOTE_e_o_avulso_dao_a_mesma_resposta(tmp_path):
    """`panorama` lê a ACL de todos os arquivos numa chamada só — por arquivo
    eram 3,4 s dentro do `coletar()` da Saúde, e essa tela já foi de 5,6 s
    para 0,95 s justamente tirando dela um diagnóstico caro repetido.

    Duas leituras diferentes da mesma coisa divergem no dia em que uma delas
    ganhar um ajuste; por isso as duas passam pelo MESMO julgamento, e este
    teste é o que amarra isso.
    """
    if not sa.WINDOWS:
        pytest.skip("o lote só existe no Windows")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    for f in (a, b):
        f.write_text("{}", encoding="utf-8")
    subprocess.run(["icacls", str(b), "/grant", "*%s:(R)" % SID_USUARIOS],
                   capture_output=True)
    lote = sa._acessos_em_lote([a, b])
    if lote.get(str(a)) is None:
        pytest.skip("ACL não legível nesta máquina")
    for f in (a, b):
        assert (sa._julgar(lote[str(f)])["protegido"]
                == sa.estado(f)["protegido"]), f


def test_arquivo_que_o_lote_NAO_devolveu_vira_nao_verificado(tmp_path):
    """O caso silencioso: se o PowerShell falhar em um dos caminhos, o que
    NÃO pode acontecer é ele sair da lista e o cartão dizer que está tudo
    conferido."""
    faltante = tmp_path / "sumido.json"
    assert sa._julgar(None)["protegido"] is None
    assert sa._julgar(None)["motivo"]
    lote = sa._acessos_em_lote([faltante])   # nem existe
    assert lote[str(faltante)] is None
