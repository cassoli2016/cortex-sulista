"""Cofre local de credenciais de integração — data/credenciais.json.

Existe para que o token de um fornecedor possa ser trocado pela tela de Gestão,
sem editar arquivo no servidor nem reiniciar a API.

Duas regras que o resto do sistema depende:

1. **O segredo entra e não volta.** `status()` devolve só o mascarado; quem
   precisa do valor de verdade chama `ler()`, e nenhum endpoint expõe isso.
   A única exceção é o campo marcado `segredo: False` no catálogo — ambiente,
   URL base, id de filial, cabeçalho: configuração, não credencial. O padrão
   é segredo, então campo novo nasce protegido mesmo se a linha esquecer.
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

# ---------------------------------------------------------------- catálogo
#
# Antes isto era uma lista plana de 22 nomes, todos com a mesma cara na tela:
# quem abria a aba via onze campos PROLOG_* dizendo "não configurado — a
# integração fica desligada", quando a Prolog precisa de UM dos três modos de
# autenticação, não dos onze campos. O catálogo abaixo diz a que fornecedor
# cada campo pertence, se é ALTERNATIVA (modo de autenticação) ou AJUSTE
# (sempre válido), e o que de fato falta para o fornecedor ligar.
#
# `segredo=False` é EXCEÇÃO DELIBERADA e o valor desses campos VOLTA para a
# tela: ambiente, URL base, id de filial e cabeçalho não são segredo, e
# mascarar "hmg" como "•••" só impede o operador de conferir o que configurou.
# O padrão é `segredo=True` — campo novo nasce protegido a menos que a linha
# diga o contrário.

CAMPOS: dict[str, dict] = {
    "GOBRAX_TOKEN": {
        "rotulo": "Token de API",
        "descricao": "Token da API Gobrax (telemetria e premiação)"},

    "SMTP_SENHA": {
        "rotulo": "Senha do servidor",
        "descricao": "Senha do servidor de e-mail (envio pelo CÓRTEX)"},

    # Monkey Exchange — portal de antecipação da Tupy. A autenticação é
    # PLUGÁVEL porque a documentação pública não diz qual é: vale token
    # estático OU o par client_id/client_secret (OAuth2 client_credentials).
    "MONKEY_TOKEN": {
        "rotulo": "Token estático",
        "descricao": "Token pronto, sem troca por access_token"},
    "MONKEY_CLIENT_ID": {
        "rotulo": "client_id", "segredo": False,
        "descricao": "Identificador do cliente OAuth2 (não é segredo)"},
    "MONKEY_CLIENT_SECRET": {
        "rotulo": "client_secret",
        "descricao": "Segredo do par OAuth2"},
    "MONKEY_TOKEN_URL": {
        "rotulo": "URL do token", "segredo": False, "obrigatorio": False,
        "descricao": "Só se não for o padrão <base>/oauth/token",
        "placeholder": "https://…/oauth/token"},
    "MONKEY_SELLER_ID": {
        "rotulo": "sellerId da Sulista", "segredo": False,
        "descricao": "O {id} de /v2/sellers/{id}/receivables — um por CNPJ"},
    "MONKEY_AMBIENTE": {
        "rotulo": "Ambiente", "segredo": False, "obrigatorio": False,
        "descricao": "hmg (homologação, padrão) ou prod", "placeholder": "hmg"},

    # Prolog — gestão de pneus. O OpenAPI da Prolog não declara
    # securityScheme nenhum, então aceita token, Basic ou OAuth2.
    "PROLOG_TOKEN": {
        "rotulo": "Token de API",
        "descricao": "Vai no cabeçalho X-Prolog-Api-Token"},
    "PROLOG_USUARIO": {
        "rotulo": "Usuário", "segredo": False,
        "descricao": "Login da Prolog (autenticação Basic)"},
    "PROLOG_SENHA": {
        "rotulo": "Senha", "descricao": "Senha da Prolog (autenticação Basic)"},
    "PROLOG_CLIENT_ID": {
        "rotulo": "client_id", "segredo": False,
        "descricao": "Identificador do cliente OAuth2 (não é segredo)"},
    "PROLOG_CLIENT_SECRET": {
        "rotulo": "client_secret", "descricao": "Segredo do par OAuth2"},
    "PROLOG_TOKEN_URL": {
        "rotulo": "URL do token", "segredo": False, "obrigatorio": False,
        "descricao": "Só se não for o padrão <base>/oauth/token",
        "placeholder": "https://…/oauth/token"},
    "PROLOG_FILIAIS": {
        "rotulo": "Filiais", "segredo": False,
        "descricao": "Ids das filiais da Sulista na Prolog, separados por vírgula",
        "placeholder": "12, 15, 21"},
    "PROLOG_API_BASE_URL": {
        "rotulo": "URL base", "segredo": False, "obrigatorio": False,
        "descricao": "Padrão https://prologapp.com/prolog",
        "placeholder": "https://prologapp.com/prolog"},
    "PROLOG_AUTH_HEADER": {
        "rotulo": "Cabeçalho do token", "segredo": False, "obrigatorio": False,
        "descricao": "Padrão X-Prolog-Api-Token — trocar só se a Prolog mudar",
        "placeholder": "X-Prolog-Api-Token"},
    "PROLOG_AUTH_PREFIXO": {
        "rotulo": "Prefixo do token", "segredo": False, "obrigatorio": False,
        "descricao": "Padrão vazio no cabeçalho próprio; Bearer no Authorization",
        "placeholder": "Bearer"},
}

# A ORDEM DOS MODOS IMPORTA: é a mesma prioridade que `modo_auth()` de cada
# cliente aplica (monkey/cliente.py, pneus/cliente.py). Se divergir, a tela
# diria "autenticando por usuário e senha" enquanto o código usa o token — e o
# teste `test_modo_ativo_bate_com_o_cliente` quebra de propósito.
SERVICOS: list[dict] = [
    {
        "chave": "gobrax",
        "nome": "Gobrax",
        "resumo": "Telemetria da frota (consumo, condução, hodômetro e rastro) "
                  "e a premiação por nota × km.",
        "alimenta": "Telemetria · Premiação",
        "modos": [{"chave": "token", "rotulo": "Token de API",
                   "dica": "o mesmo token usado no portal da Gobrax",
                   "campos": ["GOBRAX_TOKEN"]}],
        "ajustes": [],
    },
    {
        "chave": "prolog",
        "nome": "Prolog",
        "resumo": "Gestão de pneus — parque instalado, sulco, CPK e movimentação. "
                  "A API tem COTA: a coleta é agendada e retomável.",
        "alimenta": "Pneus",
        "modos": [
            {"chave": "token", "rotulo": "Token de API",
             "campos": ["PROLOG_TOKEN"]},
            {"chave": "basic", "rotulo": "Usuário e senha",
             "campos": ["PROLOG_USUARIO", "PROLOG_SENHA"]},
            {"chave": "oauth", "rotulo": "OAuth2",
             "dica": "client_credentials — o par é trocado por access_token",
             "campos": ["PROLOG_CLIENT_ID", "PROLOG_CLIENT_SECRET",
                        "PROLOG_TOKEN_URL"]},
        ],
        "ajustes": ["PROLOG_FILIAIS", "PROLOG_API_BASE_URL",
                    "PROLOG_AUTH_HEADER", "PROLOG_AUTH_PREFIXO"],
    },
    {
        "chave": "monkey",
        "nome": "Monkey Exchange",
        "resumo": "Antecipação de recebíveis da Tupy. Cada CNPJ da Sulista é um "
                  "sellerId diferente no portal.",
        "alimenta": "Antecipações",
        "modos": [
            {"chave": "token", "rotulo": "Token estático",
             "campos": ["MONKEY_TOKEN"]},
            {"chave": "oauth", "rotulo": "OAuth2",
             "dica": "client_credentials — o par é trocado por access_token",
             "campos": ["MONKEY_CLIENT_ID", "MONKEY_CLIENT_SECRET",
                        "MONKEY_TOKEN_URL"]},
        ],
        "ajustes": ["MONKEY_SELLER_ID", "MONKEY_AMBIENTE"],
    },
    {
        # Editado na aba E-mail, que tem servidor, porta, remetente e trilha de
        # envio. Aparece aqui só no panorama: ter dois lugares para digitar a
        # mesma senha é o que fazia o operador salvar num e conferir no outro.
        "chave": "smtp",
        "nome": "Servidor de e-mail (SMTP)",
        "resumo": "Envio de e-mail pelo CÓRTEX — régua de cobrança, relatórios "
                  "e avisos.",
        "alimenta": "Correio · Cobrança",
        "modos": [{"chave": "senha", "rotulo": "Senha",
                   "campos": ["SMTP_SENHA"]}],
        "ajustes": [],
        "aba": "email",
    },
]

# a tela de Gestão só sabe editar o que está no catálogo
CONHECIDAS = {nome: c["descricao"] for nome, c in CAMPOS.items()}

# senha de SMTP costuma ser curta (e "senha de aplicativo" do Google tem 16
# caracteres); o mínimo de 8 do token continua valendo para as demais
TAMANHO_MINIMO = 8
MINIMO_POR_CREDENCIAL = {"SMTP_SENHA": 4, "MONKEY_SELLER_ID": 1,
                         "MONKEY_AMBIENTE": 3, "PROLOG_FILIAIS": 1,
                         "PROLOG_USUARIO": 3, "PROLOG_AUTH_PREFIXO": 3,
                         "PROLOG_AUTH_HEADER": 3}


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


def e_segredo(nome: str) -> bool:
    """Campo desconhecido é segredo. O `get` com padrão True é o que garante
    que uma credencial nova esquecida no catálogo não vaze por omissão."""
    return bool(CAMPOS.get(nome, {}).get("segredo", True))


def status(nome: str) -> dict:
    """O que a tela recebe.

    NUNCA inclui o valor de um SEGREDO — só o mascarado. Campo marcado
    `segredo: False` no catálogo (ambiente, URL base, filiais, cabeçalho) volta
    com o valor: são configuração, e escondê-los impedia conferir o que estava
    valendo sem abrir o arquivo no servidor.
    """
    meta = CAMPOS.get(nome, {})
    entrada = _carregar().get(nome) or {}
    valor = entrada.get("valor")
    origem = "cofre" if valor else ("ambiente"
                                    if os.environ.get(nome, "").strip() else None)
    efetivo = valor or os.environ.get(nome, "").strip()
    st = {
        "nome": nome,
        "rotulo": meta.get("rotulo", nome),
        "descricao": meta.get("descricao", ""),
        "segredo": e_segredo(nome),
        "obrigatorio": bool(meta.get("obrigatorio", True)),
        "placeholder": meta.get("placeholder", ""),
        "configurado": bool(efetivo),
        "mascarado": mascarar(efetivo) if efetivo else None,
        "origem": origem,
        "atualizado_em": entrada.get("atualizado_em"),
    }
    if efetivo and not st["segredo"]:
        st["valor"] = efetivo
    return st


def listar() -> list[dict]:
    return [status(nome) for nome in CONHECIDAS]


# ------------------------------------------------------------------ panorama

def _modo_completo(modo: dict) -> bool:
    """Um modo está completo quando todos os campos OBRIGATÓRIOS dele estão
    preenchidos. `MONKEY_TOKEN_URL` é opcional dentro do OAuth2 (o cliente cai
    no padrão <base>/oauth/token), e exigi-lo faria a tela dizer que falta algo
    que não falta."""
    return all(bool(ler(c)) for c in modo["campos"]
               if CAMPOS.get(c, {}).get("obrigatorio", True))


def _falta_do_servico(svc: dict, modo_ativo: str | None) -> list[str]:
    faltando: list[str] = []
    if not modo_ativo:
        faltando.append("credencial de acesso ("
                        + " ou ".join(m["rotulo"] for m in svc["modos"]) + ")")
    for nome in svc["ajustes"]:
        if CAMPOS.get(nome, {}).get("obrigatorio", True) and not ler(nome):
            faltando.append(CAMPOS[nome]["rotulo"].lower())
    return faltando


def panorama() -> list[dict]:
    """Os fornecedores, cada um com o estado que a tela mostra no cabeçalho.

    `estado` é o semáforo do cartão:
      ativa       — tem autenticação completa E os ajustes obrigatórios;
      incompleta  — começou a ser configurada e falta alguma coisa;
      desligada   — nada preenchido (não é erro: o recurso não existe aqui).
    """
    fora: list[dict] = []
    for svc in SERVICOS:
        modos = []
        modo_ativo = None
        for m in svc["modos"]:
            completo = _modo_completo(m)
            if completo and modo_ativo is None:
                modo_ativo = m["chave"]
            modos.append({**m, "completo": completo,
                          "campos": [status(c) for c in m["campos"]]})
        ajustes = [status(c) for c in svc["ajustes"]]
        falta = _falta_do_servico(svc, modo_ativo)
        algum = any(c["configurado"] for m in modos for c in m["campos"])             or any(c["configurado"] for c in ajustes)
        estado = ("ativa" if modo_ativo and not falta
                  else "incompleta" if algum else "desligada")
        fora.append({
            "chave": svc["chave"], "nome": svc["nome"],
            "resumo": svc["resumo"], "alimenta": svc["alimenta"],
            "aba": svc.get("aba"),
            "estado": estado, "modo_ativo": modo_ativo, "falta": falta,
            "modos": modos, "ajustes": ajustes,
        })
    return fora


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
