"""Cofre local de credenciais de integração — data/credenciais.json.

Existe para que o token de um fornecedor possa ser trocado pela tela de Gestão,
sem editar arquivo no servidor nem reiniciar a API.

Duas regras que o resto do sistema depende:

1. **O valor entra e não volta.** `status()` devolve só o mascarado; quem
   precisa do valor de verdade chama `ler()`, e nenhum endpoint expõe isso.
2. **O cofre vence a variável de ambiente.** É o que o usuário acabou de
   configurar conscientemente na tela; a ordem inversa criaria o caso de salvar
   e nada acontecer.

O arquivo nasce com permissão 0600 e fica fora do git, como o .env.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAMINHO = ROOT / "data" / "credenciais.json"

# credenciais que a tela de Gestão sabe editar
CONHECIDAS = {
    "GOBRAX_TOKEN": "Token da API Gobrax (telemetria e premiação)",
}

TAMANHO_MINIMO = 8


def _carregar() -> dict:
    try:
        return json.loads(CAMINHO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # arquivo ausente ou corrompido não pode derrubar a aplicação:
        # a integração simplesmente fica desconfigurada
        return {}


def mascarar(valor: str) -> str:
    """'abcdefghij…wxyz' — só as pontas, o suficiente para conferir de qual
    credencial se trata sem revelar nada utilizável."""
    if not valor:
        return ""
    if len(valor) <= 10:
        return "•" * len(valor)
    return f"{valor[:4]}…{valor[-4:]}"


def ler(nome: str) -> str | None:
    """Valor efetivo: cofre primeiro, ambiente depois."""
    guardado = (_carregar().get(nome) or {}).get("valor")
    if guardado:
        return guardado
    return os.environ.get(nome, "").strip() or None


def status(nome: str) -> dict:
    """O que a tela recebe. NUNCA inclui o valor."""
    entrada = _carregar().get(nome) or {}
    valor = entrada.get("valor")
    origem = "cofre" if valor else ("ambiente"
                                    if os.environ.get(nome, "").strip() else None)
    efetivo = valor or os.environ.get(nome, "").strip()
    return {
        "nome": nome,
        "descricao": CONHECIDAS.get(nome, ""),
        "configurado": bool(efetivo),
        "mascarado": mascarar(efetivo) if efetivo else None,
        "origem": origem,
        "atualizado_em": entrada.get("atualizado_em"),
    }


def listar() -> list[dict]:
    return [status(nome) for nome in CONHECIDAS]


def gravar(nome: str, valor: str) -> dict:
    """Grava (ou apaga, com valor vazio). Devolve o status, nunca o valor."""
    if nome not in CONHECIDAS:
        raise ValueError(f"credencial desconhecida: {nome}")
    valor = (valor or "").strip()
    dados = _carregar()
    if not valor:
        dados.pop(nome, None)
    else:
        if len(valor) < TAMANHO_MINIMO:
            raise ValueError(
                "O valor informado é curto demais para ser uma credencial.")
        dados[nome] = {"valor": valor,
                       "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    CAMINHO.chmod(0o600)   # o segredo não é legível por outros usuários da máquina
    return status(nome)
