"""Inscrições de Web Push, agora no PostgreSQL local.

Segundo store migrado (ver `docs/MIGRACAO_POSTGRES.md`). Não havia teste
nenhum aqui antes; a migração é a hora de escrever, porque é quando se sabe o
que pode quebrar.

O que se protege:

1. **Zero por banco vazio e zero por banco caído não são a mesma coisa.** Um é
   "ninguém se inscreveu" e a tela está certa; o outro é falha e tem de subir.
2. **A mesma inscrição não vira duas.** O navegador reenvia a subscription a
   cada visita; sem `ON CONFLICT` o mesmo aparelho receberia o push repetido.
3. **Nada de DDL no import.** Com o banco fora do ar, um `init_db()` no import
   derrubaria a API inteira na subida.
"""
from __future__ import annotations

import pytest

from api import pglocal, push


def _sub(ep="https://fcm.googleapis.com/fcm/send/abc123"):
    return {"endpoint": ep, "keys": {"p256dh": "chave-publica", "auth": "auth-x"}}


# ------------------------------------------------------- sem tocar no banco

def test_importar_o_modulo_nao_cria_tabela_nenhuma():
    """Enquanto era SQLite, `init_db()` rodava no import e custava nada. Com o
    Postgres isso faria a API não subir com o banco fora do ar."""
    fonte = (push.__file__)
    with open(fonte, encoding="utf-8") as f:
        corpo = f.read()
    # a chamada existe dentro de funções; o que não pode é no nível do módulo
    for linha in corpo.splitlines():
        assert not linha.startswith("init_db("), linha


def test_subscription_incompleta_e_recusada_antes_de_qualquer_conexao():
    """Validação antes do banco: navegador que manda meia subscription não
    pode nem abrir conexão."""
    with pytest.raises(ValueError):
        push.salvar_sub({"endpoint": "https://x"}, "alguem")
    with pytest.raises(ValueError):
        push.salvar_sub({}, None)


# ------------------------------------------------------------- com banco

def test_leitura_sem_tabela_e_vazio_nao_erro(pg_disponivel):
    """Schema recém-criado, ninguém inscrito: a tela mostra zero e está certa."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    nome = "teste_push_sem_tabela"
    pglocal.criar_esquema(nome)   # schema vazio DE PROPÓSITO: sem migrations
    try:
        assert push.contar_subs(esquema=nome) == 0
        assert push._all_subs(esquema=nome) == []
        assert push.subs_do_usuario("x", esquema=nome) == []
        assert push._ja_enviou_hoje(esquema=nome) is False
    finally:
        pglocal.apagar_esquema(nome)


def test_salva_e_conta(esquema_pg):
    push.salvar_sub(_sub(), "ana@sulista.local", esquema=esquema_pg)
    assert push.contar_subs(esquema=esquema_pg) == 1
    assert push.contar_subs("ana@sulista.local", esquema=esquema_pg) == 1
    assert push.contar_subs("outro@sulista.local", esquema=esquema_pg) == 0


def test_a_mesma_inscricao_nao_vira_duas(esquema_pg):
    """O navegador reenvia a subscription a cada visita. Sem ON CONFLICT o
    mesmo aparelho receberia o push repetido."""
    push.salvar_sub(_sub(), "ana@sulista.local", esquema=esquema_pg)
    push.salvar_sub(_sub(), "ana@sulista.local", esquema=esquema_pg)
    assert push.contar_subs(esquema=esquema_pg) == 1


def test_reinscrever_com_outro_usuario_troca_o_dono(esquema_pg):
    """Mesmo aparelho, outra pessoa logada: o push tem de seguir quem está
    logado agora, senão o alerta vai para o dono anterior."""
    push.salvar_sub(_sub(), "ana@sulista.local", esquema=esquema_pg)
    push.salvar_sub(_sub(), "bruno@sulista.local", esquema=esquema_pg)
    assert push.contar_subs("ana@sulista.local", esquema=esquema_pg) == 0
    assert push.contar_subs("bruno@sulista.local", esquema=esquema_pg) == 1


def test_remover_inscricao_morta(esquema_pg):
    """404/410 do serviço de push = aparelho que desinstalou. A limpeza roda
    dentro do envio e não pode falhar."""
    push.salvar_sub(_sub(), "ana@sulista.local", esquema=esquema_pg)
    push.remover_sub(_sub()["endpoint"], esquema=esquema_pg)
    assert push.contar_subs(esquema=esquema_pg) == 0


def test_marcador_do_digest_nao_repete_no_mesmo_dia(esquema_pg):
    assert push._ja_enviou_hoje(esquema=esquema_pg) is False
    push._marca_hoje(esquema=esquema_pg)
    assert push._ja_enviou_hoje(esquema=esquema_pg) is True
    push._marca_hoje(esquema=esquema_pg)   # idempotente
    assert push._ja_enviou_hoje(esquema=esquema_pg) is True


def test_marcador_funciona_em_instalacao_que_nunca_teve_inscricao(pg_disponivel):
    """O marcador é gravado MESMO com zero envios, e numa instalação sem
    inscrição as tabelas ainda não existem. Sem o init, o laço do digest
    falharia de 5 em 5 minutos durante a hora inteira."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    nome = "teste_push_digest_virgem"
    pglocal.criar_esquema(nome)
    try:
        push._marca_hoje(esquema=nome)
        assert push._ja_enviou_hoje(esquema=nome) is True
    finally:
        pglocal.apagar_esquema(nome)
