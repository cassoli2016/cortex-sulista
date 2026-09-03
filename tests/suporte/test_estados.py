"""A máquina de estados do chamado é uma tabela pura — cada transição
permitida e cada proibida, com a frase que a tela mostra."""
from __future__ import annotations

import pytest

from api.suporte import comum
from api.validacao import DadoInvalido


@pytest.mark.parametrize("de, para, papel, kw", [
    ("aberto", "em_atendimento", "suporte", {}),
    ("em_atendimento", "aguardando_usuario", "suporte", {"texto": "qual a placa?"}),
    ("aguardando_usuario", "em_atendimento", "usuario", {}),          # resposta do dono
    ("em_atendimento", "resolvido", "suporte", {"texto": "corrigido"}),
    ("resolvido", "fechado", "usuario", {}),                          # confirmar
    ("aberto", "fechado", "usuario", {}),                             # desistiu
    ("em_atendimento", "fechado", "suporte", {"motivo": "duplicado"}),
    ("resolvido", "aberto", "usuario", {"texto": "ainda não funciona"}),
    ("fechado", "aberto", "suporte", {"texto": "reabrindo"}),
])
def test_transicoes_permitidas(de, para, papel, kw):
    assert comum.transicao(de, para, papel, **kw) is None


@pytest.mark.parametrize("de, para, papel, kw, trecho", [
    ("aberto", "resolvido", "usuario", {}, "por quem abriu"),
    ("fechado", "resolvido", "suporte", {}, "encerrado"),
    ("aberto", "aberto", "suporte", {}, "já está"),
    ("em_atendimento", "aguardando_usuario", "suporte", {}, "obrigatório"),
    ("em_atendimento", "fechado", "suporte", {}, "motivo"),
    ("em_atendimento", "fechado", "suporte", {"motivo": "inventado"}, "motivo"),
    ("resolvido", "aberto", "usuario", {}, "obrigatório"),
])
def test_transicoes_recusadas_com_frase(de, para, papel, kw, trecho):
    with pytest.raises(DadoInvalido) as e:
        comum.transicao(de, para, papel, **kw)
    assert trecho in str(e.value).lower()


def test_mascaras_nunca_entregam_o_dado_inteiro():
    assert comum.mascarar_email("marcos.silva@sulista.com.br") == "m•••a@sulista.com.br"
    assert comum.mascarar_email("") == "" and comum.mascarar_email("x") == "•••"
    t = comum.mascarar_telefone("5547999998888")
    assert t.startswith("5547") and t.endswith("88") and "9999" not in t
    assert comum.mascarar_telefone(None) == ""


def test_anexos_tetos_e_nome_gerado():
    ok = comum.validar_anexos([{"nome": "../../print.PNG", "b64": "aGVsbG8="}])
    assert ok[0]["nome"] == "anexo-1.png" and ok[0]["mime"] == "image/png" and ok[0]["tamanho"] == 5
    with pytest.raises(DadoInvalido):
        comum.validar_anexos([{"nome": "virus.exe", "b64": "aGVsbG8="}])
    with pytest.raises(DadoInvalido):
        comum.validar_anexos([{"nome": f"a{i}.png", "b64": "aGVsbG8="} for i in range(6)])
    grande = "A" * (comum.ANEXO_MAX_BYTES * 4 // 3 + 100)
    with pytest.raises(DadoInvalido):
        comum.validar_anexos([{"nome": "a.png", "b64": grande}])
    assert comum.validar_anexos(None) == []


def test_texto_do_usuario_nao_vira_chave_de_modelo():
    assert "{{" not in comum.sem_chaves("Prezado {{nome}} {{ x }}")


def test_config_padrao_e_sla(esquema_pg, monkeypatch):
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    c = comum.config()
    assert c["sla_horas_alta"] == "8" and comum.sla_horas(c, "media") == 48
    c2 = comum.gravar_config({"sla_horas_alta": "4", "email_equipe": "ti@x.com; suporte@x.com"}, "teste")
    assert comum.sla_horas(c2, "alta") == 4 and c2["email_equipe"] == "ti@x.com; suporte@x.com"
    # chave ausente não mexe; vazia volta ao padrão
    c3 = comum.gravar_config({"sla_horas_alta": ""}, "teste")
    assert comum.sla_horas(c3, "alta") == 8 and c3["email_equipe"] == "ti@x.com; suporte@x.com"
    with pytest.raises(DadoInvalido):
        comum.gravar_config({"sla_horas_alta": "9999"}, "teste")
    with pytest.raises(DadoInvalido):
        comum.gravar_config({"email_equipe": "nao-e-email"}, "teste")
    with pytest.raises(DadoInvalido):
        comum.gravar_config({"chave_inventada": "1"}, "teste")
