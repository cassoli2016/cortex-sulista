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
    "SMTP_SENHA": "Senha do servidor de e-mail (envio pelo CÓRTEX)",
    # Monkey Exchange — portal de antecipação da Tupy. A autenticação é
    # PLUGÁVEL porque a documentação pública não diz qual é: configure
    # MONKEY_TOKEN (token estático) OU o par CLIENT_ID/CLIENT_SECRET
    # (OAuth2 client_credentials). O que estiver preenchido é o que vale.
    "MONKEY_TOKEN": "Token estático da API Monkey (antecipação Tupy)",
    "MONKEY_CLIENT_ID": "client_id da Monkey (se for OAuth2)",
    "MONKEY_CLIENT_SECRET": "client_secret da Monkey (se for OAuth2)",
    "MONKEY_TOKEN_URL": "URL do endpoint de token da Monkey (se for OAuth2)",
    "MONKEY_SELLER_ID": "ID da Sulista como seller na Monkey (o {id} da URL)",
    "MONKEY_AMBIENTE": "Ambiente da Monkey: hmg (padrão) ou prod",
    # Prolog — gestão de pneus. Autenticação também plugável: o OpenAPI da
    # Prolog não declara securityScheme nenhum, então aceita token, Basic ou
    # OAuth2, e vale o que estiver preenchido.
    "PROLOG_TOKEN": "Token da API Prolog (pneus)",
    "PROLOG_AUTH_HEADER": "Cabeçalho do token na Prolog (padrão X-Prolog-Api-Token)",
    "PROLOG_COMPANY_ID": "Código da empresa da Sulista na Prolog",
    "PROLOG_AUTH_PREFIXO": "Prefixo do token na Prolog (padrão Bearer)",
    "PROLOG_USUARIO": "Usuário da Prolog (se for autenticação Basic)",
    "PROLOG_SENHA": "Senha da Prolog (se for autenticação Basic)",
    "PROLOG_CLIENT_ID": "client_id da Prolog (se for OAuth2)",
    "PROLOG_CLIENT_SECRET": "client_secret da Prolog (se for OAuth2)",
    "PROLOG_TOKEN_URL": "URL do endpoint de token da Prolog (se for OAuth2)",
    "PROLOG_FILIAIS": "IDs das filiais da Sulista na Prolog, separados por vírgula",
    "PROLOG_API_BASE_URL": "URL base da Prolog (padrão https://prologapp.com/prolog)",
}

# senha de SMTP costuma ser curta (e "senha de aplicativo" do Google tem 16
# caracteres); o mínimo de 8 do token continua valendo para as demais
TAMANHO_MINIMO = 8
MINIMO_POR_CREDENCIAL = {"SMTP_SENHA": 4, "MONKEY_SELLER_ID": 1,
                         "MONKEY_AMBIENTE": 3, "PROLOG_FILIAIS": 1,
                         "PROLOG_USUARIO": 3}


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
        minimo = MINIMO_POR_CREDENCIAL.get(nome, TAMANHO_MINIMO)
        if len(valor) < minimo:
            raise ValueError(
                "O valor informado é curto demais para ser uma credencial.")
        dados[nome] = {"valor": valor,
                       "atualizado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    CAMINHO.chmod(0o600)   # o segredo não é legível por outros usuários da máquina
    return status(nome)
