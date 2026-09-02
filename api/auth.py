"""CÓRTEX — autenticação, perfis de acesso e auditoria (área de Gestão).

Armazenamento no banco local do CÓRTEX (PostgreSQL, schema `cortex`) — o ERP
AVA é somente leitura, então usuários/perfis/audit vivem aqui. Senhas com Argon2; sessão via JWT
(HS256, APP_SECRET do .env) em cookie HttpOnly com renovação deslizante.

A permissão é POR TELA do painel (as chaves do objeto VIEWS do frontend).
Cada rota /api/* é mapeada às telas que a consomem (ROTA_TELAS); o usuário
precisa ter ao menos uma delas. /api/gestao/* exige perfil administrador.
Toda escrita entra em audit_log (regra CLAUDE.md §8).
"""
from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import psycopg
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from . import db as _db  # noqa: F401  (importa para garantir o .env carregado)
from . import fotos, migracoes, pglocal
from .whatsapp import numeros as telefones

log = logging.getLogger("cortex.auth")

ROOT = Path(__file__).resolve().parent.parent
COOKIE = "cortex_sess"

# Manopla de redirecionamento, no lugar do antigo `DB_PATH`: o teste faz
# `monkeypatch.setattr(auth, "ESQUEMA", <schema do teste>)`.
ESQUEMA: str | None = None
_ph = PasswordHasher()

# Segredo de assinatura: sem APP_SECRET no .env, gera um efêmero (derruba as
# sessões a cada restart, mas nunca roda com segredo previsível).
SECRET = os.environ.get("APP_SECRET", "").strip()
if not SECRET or SECRET.startswith("__"):
    SECRET = os.urandom(32).hex()
    log.warning("APP_SECRET ausente no .env — usando segredo efêmero (sessões caem no restart)")

# ---------------------------------------------------------------- telas/RBAC

# Telas do painel (mesmas chaves/rótulos do objeto VIEWS do index.html).
TELAS: dict[str, tuple[str, str]] = {  # chave -> (rótulo, grupo do menu)
    "home":    ("Visão Geral", "Início"),
    "cop":     ("Copiloto Cortex", "Início"),
    "fluxo":   ("Fluxo de Caixa e Bancos", "Financeiro"),
    "receber": ("Contas a Receber", "Financeiro"),
    "cob":     ("Régua de Cobrança", "Financeiro"),
    "banc":    ("Bancos", "Financeiro"),
    "extb":    ("Extrato Bancário", "Financeiro"),
    "lanc":    ("Lançamentos Bancários", "Financeiro"),
    "antec":   ("Antecipação de Recebíveis", "Financeiro"),
    "antport": ("Portais de Antecipação", "Financeiro"),
    "milkrun": ("Operação MWM", "Operação"),
    "rec":     ("Lançamentos Recorrentes", "Financeiro"),
    "fluxcon": ("Fluxo Consolidado", "Financeiro"),
    "pagar":   ("Contas a Pagar", "Financeiro"),
    "com":     ("Clientes e RKM", "Comercial"),
    "clif":    ("Consulta de Cliente", "Comercial"),
    "crm":     ("CRM — Funil Comercial", "Comercial"),
    "drecli":  ("DRE por Cliente", "Comercial"),
    "dre":     ("DRE Gerencial", "Controladoria"),
    "bal":     ("Balanço Patrimonial", "Controladoria"),
    "cont":    ("Contabilidade", "Controladoria"),
    "qual":    ("Qualidade e Certidões", "Controladoria"),
    "orc":     ("Orçamento", "Controladoria"),
    "fech":    ("Fechamento do Mês", "Controladoria"),
    "agr":     ("Agregados e Terceiros", "Operação"),
    "mvb":     ("Frota Própria × Agregado", "Operação"),
    "km":      ("Análise de KM", "Operação"),
    "prog":    ("Programação Inteligente", "Operação"),
    "torre":   ("Torre de Controle", "Operação"),
    "gr":      ("Gerenciamento de Risco", "Operação"),
    "jorn":    ("Jornada do Motorista", "Operação"),
    "cex":     ("Custos Extras", "Operação"),
    "sac":     ("SAC / Freetime", "Operação"),
    "port":    ("Portaria", "Operação"),
    "oc":      ("Ordens de Compra", "Suprimentos"),
    "custos":  ("Painel de Custos", "Suprimentos"),
    "pecas":   ("Preço de Peças", "Suprimentos"),
    "comb":    ("Combustível", "Frota"),
    "man":     ("Manutenção", "Frota"),
    "veic":    ("Veículos", "Frota"),
    "mprev":   ("Manutenção Preventiva", "Frota"),
    "comrast": ("Comunicação Rastreadora", "Frota"),
    "veicf":   ("Consulta de Veículo", "Frota"),
    "mul":     ("Multas — Smartec", "Frota"),
    "prem":    ("Premiação de Motoristas", "Telemetria"),
    "rh":      ("RH — Vagas", "Recursos Humanos"),
    "hc":      ("Headcount", "Recursos Humanos"),
    "folha":   ("Custo de Folha", "Recursos Humanos"),
    "pedagio": ("Validação de Pedágio", "Operação"),
    "folhaind": ("Indicadores de Folha", "Recursos Humanos"),
    "cnh":     ("CNH dos Motoristas", "Recursos Humanos"),
    "pneus":   ("Pneus", "Frota"),
    "ferias":  ("Férias — Vencimento", "Recursos Humanos"),
    "people":  ("People Analytics", "Recursos Humanos"),
    "he":      ("Horas Extras", "Recursos Humanos"),
    "poli":    ("Permanência na Planta — Tupy", "Operação"),
    "ctecp":   ("CT-e de Contrapartida", "Controladoria"),
    "anpiso":  ("Piso Mínimo de Frete", "ANTT"),
    "anrntrc": ("RNTRC dos Transportadores", "ANTT"),
    "telcon":  ("Consumo e Estatísticas", "Telemetria"),
    "telcond": ("Condução Econômica", "Telemetria"),
    "telhod":  ("Hodômetro e Rastro", "Telemetria"),
    "prodveic": ("Produtividade de Veículos", "Business Intelligence"),
    "fat":     ("Faturamento Detalhado", "Controladoria"),
    "tvfat":   ("Painel TV — Faturamento", "Business Intelligence"),
    "tvope":   ("Painel TV — Operação", "Business Intelligence"),
    "tvdir":   ("Painel TV — Diretoria", "Business Intelligence"),
    "gesacao": ("Planos de Ação", "Gestão"),
    "gesata":  ("Atas de Reunião", "Gestão"),
    "doc":     ("Documentação", "Administração"),
}

# Rota (prefixo) -> telas que a consomem. Prefixos mais específicos primeiro.
ROTA_TELAS: list[tuple[str, frozenset[str]]] = [
    # metadados de filtro (empresa/filiais) usados por todas as telas com filtro:
    # basta ter QUALQUER tela atribuída — nunca fica aberto a usuário sem acesso.
    ("/api/financeiro/filtros",       frozenset(TELAS)),
    # documentação e versão: qualquer usuário logado, com qualquer tela
    ("/api/documentacao",             frozenset(TELAS)),
    ("/api/versao",                   frozenset(TELAS)),
    ("/api/telemetria/consumo/atualizar", frozenset({"telcon"})),
    ("/api/telemetria/consumo/evolucao", frozenset({"telcon"})),
    ("/api/telemetria/consumo",       frozenset({"telcon"})),
    ("/api/telemetria/motoristas",    frozenset({"telcond"})),
    ("/api/telemetria/conducao/frota", frozenset({"telcond"})),
    ("/api/telemetria/conducao",      frozenset({"telcond"})),
    ("/api/telemetria/comunicacao",   frozenset({"telcon"})),
    ("/api/telemetria/hodometro",     frozenset({"telhod"})),
    ("/api/telemetria/rastro",        frozenset({"telhod"})),
    ("/api/operacao/antt/piso",       frozenset({"anpiso"})),
    ("/api/operacao/antt/rntrc/atualizar", frozenset({"anrntrc"})),
    ("/api/operacao/antt/rntrc",      frozenset({"anrntrc"})),
    ("/api/financeiro/contabil",      frozenset({"cont"})),
    ("/api/qualidade",                frozenset({"qual"})),
    ("/api/rh/headcount",             frozenset({"hc"})),
    ("/api/rh/folha-indicadores",     frozenset({"folhaind"})),
    ("/api/rh/cnh",                   frozenset({"cnh"})),
    ("/api/rh/ferias",                frozenset({"ferias"})),
    ("/api/rh/people",                frozenset({"people"})),
    ("/api/frota/pneus",              frozenset({"pneus"})),
    ("/api/operacional/poligonos",    frozenset({"poli"})),
    # sub-rotas ANTES da generica: ROTA_TELAS casa por PREFIXO
    # mais especifica ANTES da generica: ROTA_TELAS casa por PREFIXO
    ("/api/fiscal/contrapartida/transmitidos", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/validacao", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/automacao", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/documento", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/envio", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/cancelar", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/autorizacao", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida/certificado", frozenset({"ctecp"})),
    ("/api/fiscal/contrapartida",     frozenset({"ctecp"})),
    # Gestão: o painel de acompanhamento serve as DUAS telas (é o mesmo
    # dado), e /atas vem antes de /acoes só pela convenção do arquivo.
    ("/api/gestao/painel",            frozenset({"gesacao", "gesata"})),
    ("/api/gestao/atas",              frozenset({"gesata", "gesacao"})),
    ("/api/gestao/acoes",             frozenset({"gesacao", "gesata"})),
    # jornada: /raster ANTES da generica /api/jornada
    ("/api/jornada/motorista",        frozenset({"jorn"})),
    ("/api/jornada/raster",           frozenset({"jorn"})),
    ("/api/jornada/coletar",          frozenset({"jorn"})),
    ("/api/rh/folha-estrutura",       frozenset({"folha"})),
    ("/api/operacao/pedagio",         frozenset({"pedagio"})),
    ("/api/operacao/gr",              frozenset({"gr"})),
    # o Portal Tupy é ABA de Portais de Antecipação desde a v0.209.0 — a rota
    # herda a tela que a contém (sub-aba não é tela, não tem RBAC próprio)
    ("/api/financeiro/tupy",          frozenset({"antport"})),
    ("/api/rh/folha-custo",           frozenset({"folha"})),
    ("/api/rh/horas-extras",          frozenset({"he"})),
    ("/api/rh/vagas",                 frozenset({"rh"})),
    ("/api/financeiro/overview",      frozenset({"fluxo", "receber", "pagar"})),
    ("/api/financeiro/dre-cliente",   frozenset({"drecli"})),
    ("/api/controladoria/previsao",   frozenset({"fech"})),
    ("/api/controladoria/orcamento",  frozenset({"orc"})),
    # ANTES da rota generica de extrato: `ROTA_TELAS` casa por PREFIXO,
    # e "/api/financeiro/bancos" nao colide, mas a ordem aqui e a
    # convencao do arquivo - rota mais especifica primeiro.
    ("/api/financeiro/bancos",        frozenset({"banc"})),
    ("/api/financeiro/extrato",       frozenset({"extb"})),
    ("/api/financeiro/lancamentos",   frozenset({"lanc"})),
    ("/api/financeiro/recorrentes",   frozenset({"rec"})),
    # ANTES da rota generica: ROTA_TELAS casa por PREFIXO, e
    # "/api/operacao/milkrun" tambem casaria "/chat-stream". Aqui as duas
    # dao na mesma tela, mas deixar a ordem certa evita que uma futura
    # sub-rota com outra permissao seja silenciosamente liberada pela mais
    # generica (foi o que aconteceu com /clientes-lista x /clientes).
    ("/api/operacao/milkrun/chat-stream", frozenset({"milkrun"})),
    ("/api/operacao/milkrun", frozenset({"milkrun"})),
    ("/api/financeiro/credito", frozenset({"fluxo", "fluxcon", "antec"})),
    ("/api/orcamento/plano", frozenset({"orc"})),
    ("/api/financeiro/antecipacoes", frozenset({"antport", "antec"})),
    ("/api/financeiro/antecipacao",   frozenset({"antec"})),
    ("/api/financeiro/fluxo-consolidado/detalhe", frozenset({"fluxcon"})),
    ("/api/financeiro/fluxo-consolidado", frozenset({"fluxcon"})),
    ("/api/financeiro/dre",           frozenset({"dre"})),
    ("/api/financeiro/balanco",       frozenset({"bal"})),
    ("/api/financeiro/cobranca",      frozenset({"cob"})),
    ("/api/visao-geral",              frozenset({"home", "tvfat", "tvope", "tvdir"})),
    ("/api/faturamento/detalhado",    frozenset({"fat"})),
    ("/api/alertas",                  frozenset({"home"})),
    ("/api/suprimentos/precos-pecas", frozenset({"pecas"})),
    ("/api/suprimentos/custos",       frozenset({"custos"})),
    ("/api/suprimentos/oc-pendentes", frozenset({"oc"})),
    ("/api/suprimentos/ordens-compra", frozenset({"oc"})),
    ("/api/suprimentos/agregados",    frozenset({"agr"})),
    ("/api/frota/manutencao-preventiva", frozenset({"mprev"})),
    ("/api/frota/comunicacao-rastreadora", frozenset({"comrast"})),
    ("/api/frota/veiculos/identidade", frozenset({"veic"})),
    ("/api/frota/veiculos",           frozenset({"veic"})),
    ("/api/frota/veiculo",            frozenset({"veicf"})),
    ("/api/frota/combustivel",        frozenset({"comb", "tvope"})),
    ("/api/frota/manutencao",         frozenset({"man"})),
    ("/api/frota/multas",             frozenset({"mul"})),
    ("/api/smartec",                  frozenset({"mul"})),
    ("/api/premiacao/recoletar",      frozenset({"prem"})),
    ("/api/premiacao/config",         frozenset({"prem"})),
    ("/api/premiacao/ocorrencias",    frozenset({"prem"})),
    ("/api/frota/premiacao",          frozenset({"prem"})),
    # MAIS ESPECIFICA ANTES DA GENERICA:  casaria o
    # prefixo de  e o barraria por outra tela.
    ("/api/jornada/diarias",          frozenset({"jorn"})),
    ("/api/operacao/torre/chegadas",  frozenset({"torre", "tvope"})),
    ("/api/operacao/torre/estradas",  frozenset({"torre", "tvope"})),
    ("/api/operacao/torre",           frozenset({"torre", "tvope"})),
    ("/api/operacao/programacao",     frozenset({"prog", "tvope"})),
    ("/api/operacao/seguranca",       frozenset({"tvope"})),
    ("/api/bi/produtividade-veiculos", frozenset({"prodveic"})),
    ("/api/operacao/analise-km",      frozenset({"km", "tvope"})),
    ("/api/operacao/make-vs-buy",     frozenset({"mvb"})),
    ("/api/operacao/custos-extras",   frozenset({"cex"})),
    ("/api/operacao/sac-freetime",    frozenset({"sac"})),
    ("/api/operacao/portaria",        frozenset({"port"})),
    ("/api/comercial/crm",            frozenset({"crm"})),
    # mais específica ANTES: /clientes-lista começa com /clientes e cairia na
    # regra do painel comercial, barrando quem só tem a Consulta de Cliente
    ("/api/comercial/clientes-lista", frozenset({"com", "clif"})),
    ("/api/comercial/clientes",       frozenset({"com"})),
    ("/api/comercial/cliente",        frozenset({"clif"})),
    ("/api/copiloto",                 frozenset({"cop"})),
    ("/api/tv",                       frozenset({"tvfat", "tvope"})),
]

# Rotas liberadas sem sessão (a página raiz mostra o overlay de login;
# /static tem o logo usado na tela de login).
_PUBLICAS = ("/api/auth/login", "/api/auth/setup", "/api/auth/setup-status", "/api/health")

# Autoservice de conta: exige sessão válida (checado antes), mas nenhuma tela
# específica — todo usuário autenticado pode ver o próprio perfil/trocar a
# própria senha/sair. /api/gestao/* não entra aqui: já é checado à parte
# (admin) antes de chegar em _telas_da_rota.
_ROTAS_AUTOSERVICO = ("/api/auth/me", "/api/auth/logout", "/api/auth/trocar-senha",
                      "/api/auth/perfil")

# Rotas /api/* que EXIGEM sessão mas não pertencem a tela nenhuma: valem para
# qualquer usuário logado. Push é assinatura do próprio aparelho; report é
# avisar de defeito/pedir melhoria — negar isso a quem não é admin deixaria o
# botão visível para todos e funcionando só para um.
# `/api/auth/foto/` entra aqui, e não em _ROTAS_AUTOSERVICO, porque não é só a
# PRÓPRIA foto: a lista de usuários e a auditoria mostram a foto de outras
# pessoas, então o caminho carrega um id e precisa casar por prefixo.
_ROTAS_SEM_TELA = ("/api/push/", "/api/report", "/api/auth/foto/",
                   "/api/favoritos", "/api/notificacoes")

# Telas que EXISTEM no menu mas nao tem entrada em `TELAS`, porque o acesso a
# elas e decidido de outro jeito:
#   `srv` e `gestao` sao liberadas pelo `sess["admin"]` (a Gestao pelo proprio
#   middleware, que barra `/api/gestao` para nao-administrador);
#   `jornf` e drill-down da Jornada, alcancada a partir dela.
#
# A lista existe para o FAVORITO: sem ela, o administrador nao conseguiria
# favoritar a Saude do Servidor -- a validacao usaria `TELAS` e a recusaria
# como "sem acesso", que e o oposto da verdade. Ha teste comparando isto com o
# `VIEWS` do `index.html`, entao tela nova fora dos dois quebra a suite em vez
# de aparecer como favorito impossivel.
TELAS_FORA_DO_RBAC = {
    "srv":    ("Saúde do Servidor", "Sistema"),
    "gestao": ("Gestão", "Sistema"),
    "jornf":  ("Ficha de Jornada", "Operação"),
}


def telas_favoritaveis(sess: dict | None) -> set[str]:
    """O que esta pessoa pode favoritar.

    ADMIN VE TUDO: `sess["telas"]` do administrador nao enumera as telas (o
    middleware o libera por `sess["admin"]`), entao usar aquele conjunto como
    filtro esconderia todas elas dele.
    """
    if not sess:
        return set()
    if sess.get("admin"):
        return set(TELAS) | set(TELAS_FORA_DO_RBAC)
    return set(sess.get("telas") or ())


def rota_sem_tela(path: str) -> bool:
    return path in _ROTAS_AUTOSERVICO or path.startswith(_ROTAS_SEM_TELA)


def _rota_publica(path: str) -> bool:
    return (path == "/" or path == "/sw.js" or path.startswith("/static/") or path in _PUBLICAS)


def _local_direto(headers: Headers, cliente: str) -> bool:
    """Acesso direto DESTA máquina. O Cloudflare Tunnel roda local (o tráfego
    dele também chega como loopback), mas a borda sempre põe Cf-Connecting-IP —
    a ausência do header distingue o acesso local de verdade."""
    return cliente in ("127.0.0.1", "::1") and not headers.get("cf-connecting-ip")


# ------------------------------------------------- PostgreSQL local (cortex)

def _muitos(c, sql: str, params: list) -> None:
    """`executemany` é do CURSOR, não da conexão — ao contrário de `execute`,
    que o psycopg oferece nos dois. Este atalho mantém as chamadas de seed
    legíveis em vez de aninhar um `with` a cada uma."""
    with c.cursor() as cur:
        cur.executemany(sql, params)


def _conn():
    """Conexão curta no schema em vigor: transação automática, close garantido.

    Devolve a CONEXÃO do psycopg, que tem `.execute()` própria — por isso os
    ~160 `c.execute(...).fetchone()` deste arquivo continuam funcionando sem
    mudar de forma. O que mudou foi o dialeto (`?` -> `%s`, `INSERT OR IGNORE`
    -> `ON CONFLICT DO NOTHING`, `lastrowid` -> `RETURNING id`).
    """
    return pglocal.get_conn(ESQUEMA)


_CONFIG_PADRAO = {
    "sessao_ttl_min": os.environ.get("JWT_TTL_MIN", "480"),
    "max_tentativas": "5",
    "bloqueio_min": "15",
    "senha_min": "8",
}

# Perfis-modelo por área (não-admin), semeados UMA vez (flag em config) para
# agilizar o cadastro de usuários. O admin pode editar/excluir à vontade — a
# exclusão NÃO ressuscita no restart (o flag impede o reseed). Telas cross-área
# (home/cop/TV) vazam dados de outras áreas (ex.: snapshot do copiloto), então
# ficam fora dos perfis de área e só entram no perfil amplo "Diretoria".
# Perfis-modelo alinhados aos grupos do menu (reorg 2026-07-17).
_PERFIS_MODELO = [
    # Cliente externo: uma tela so, somente leitura. Qualquer tela a mais aqui
    # e dado da Sulista saindo para fora.
    ("Cliente — Milk Run",
     "Acompanhamento da operação de milk run em tempo real. Perfil de CLIENTE: "
     "uma única tela, sem acesso a nenhum outro dado da Sulista.",
     ["milkrun"]),
    ("Comercial",   "Clientes/RKM, consulta por cliente, CRM (funil, contas, "
                    "oportunidades, atividades e contratos) e DRE por cliente.",
     ["com", "clif", "crm", "drecli"]),
    ("Financeiro",  "Caixa, recebíveis, pagáveis, cobrança, extrato, lançamentos bancários e antecipação.",
     ["fluxo", "fluxcon", "receber", "pagar", "cob", "banc", "extb", "lanc", "antec", "rec", "antport"]),
    ("Controladoria", "DRE gerencial, balanço patrimonial, contabilidade, DRE/margem por cliente, qualidade/certidões e extrato bancário.",
     ["dre", "bal", "cont", "drecli", "qual", "orc", "banc", "extb", "fech", "anpiso",
      "anrntrc", "ctecp"]),
    ("Operação",    "Torre de controle, programação, jornada, custos extras, SAC/freetime, portaria, análise de KM, agregados e make-vs-buy.",
     ["torre", "prog", "jorn", "cex", "sac", "port", "km", "agr", "mvb",
      "poli"]),
    ("Frota",       "Veículos, consulta por placa, combustível, manutenção, preventiva, rastreadora, multas, infrações e licenças da Smartec, e premiação de motoristas.",
     ["veic", "veicf", "comb", "man", "mprev", "comrast", "mul",
      "pneus", "telcon", "telcond", "telhod", "cnh"]),
    ("Suprimentos", "Ordens de compra, painel de custos e preço de peças.",
     ["oc", "custos", "pecas"]),
    ("Painéis TV",  "Apenas os painéis de TV (faturamento e operação) — para telão/quiosque.",
     ["tvfat", "tvope"]),
    ("Recursos Humanos", "Vagas, headcount, custo de folha, indicadores, horas extras e CNH.",
     ["rh", "hc", "folha", "folhaind", "he", "cnh", "ferias", "people"]),
    ("Diretoria",   "Visão executiva ampla: consolidado, copiloto e principais indicadores.",
     ["home", "cop", "fluxo", "dre", "drecli", "com", "km", "prodveic", "torre", "jorn", "mvb", "veic", "prem", "rh", "hc", "folha", "folhaind", "he", "fech", "anpiso", "anrntrc",
      "telcon", "telcond", "telhod"]),
]


def init_db() -> None:
    """Aplica o schema e semeia o mínimo: as políticas padrão, o perfil de
    administrador (o setup cria o primeiro usuário nele) e os perfis-modelo.

    O DDL saiu para `sql/cortex/0011_auth.sql`; o SEED continua aqui porque é
    dado, não estrutura — e porque ele é versionado por flags em `config`
    (`perfis_modelo_v1..vN`), que é o que impede de recriar perfil que o admin
    excluiu de propósito.
    """
    migracoes.aplicar(ESQUEMA)
    with _conn() as c:
        for k, v in _CONFIG_PADRAO.items():
            c.execute("INSERT INTO config(chave, valor) VALUES(%s,%s) ON CONFLICT(chave) DO NOTHING", (k, v))
        # perfil administrador sempre existe (o setup cria o primeiro usuário nele)
        c.execute(
            "INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES(%s,%s,1,%s) ON CONFLICT(nome) DO NOTHING",
            ("Administrador", "Acesso total, inclusive à área de Gestão.", _agora()),
        )
        _seed_perfis_modelo(c)


def _seed_perfis_modelo(c: psycopg.Connection) -> None:
    """Semeia os perfis-modelo por área UMA única vez (idempotente via flag).

    Não recria perfis que o admin tenha excluído: o flag 'perfis_modelo_v1'
    marca que o seed já rodou, independentemente do que exista depois.
    """
    # v2 (reorg de menu 2026-07-17): adiciona perfis-modelo novos (ex.: Controladoria)
    # sem tocar nos existentes/editados pelo admin (INSERT OR IGNORE por nome).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v2'").fetchone():
        for nome, desc, telas in _PERFIS_MODELO:
            cur = c.execute(
                "INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES(%s,%s,0,%s) ON CONFLICT(nome) DO NOTHING RETURNING id",
                (nome, desc, _agora()))
            novo = cur.fetchone()   # None quando o nome já existia
            if novo:
                _muitos(c, 
                    "INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s)"
                    " ON CONFLICT DO NOTHING",
                    [(novo["id"], t) for t in telas])
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v1', '1') ON CONFLICT(chave) DO NOTHING")
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v2', '1') ON CONFLICT(chave) DO NOTHING")

    # v3 (jornada 2026-07-17): adiciona a tela 'jorn' aos perfis Operação e
    # Diretoria já existentes (sem recriar perfis editados pelo admin).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v3'").fetchone():
        for perfil_nome in ("Operação", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (perfil_nome,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "jorn"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v3', '1') ON CONFLICT(chave) DO NOTHING")

    # v4 (custos extras 2026-07-17): adiciona a tela 'cex' ao perfil Operação.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v4'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Operação'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "cex"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v4', '1') ON CONFLICT(chave) DO NOTHING")

    # v5 (SAC/freetime 2026-07-17): adiciona a tela 'sac' ao perfil Operação.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v5'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Operação'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "sac"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v5', '1') ON CONFLICT(chave) DO NOTHING")

    # v6 (manutenção preventiva 2026-07-17): adiciona a tela 'mprev' ao perfil Frota.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v6'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Frota'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "mprev"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v6', '1') ON CONFLICT(chave) DO NOTHING")

    # v7 (comunicação rastreadora 2026-07-17): adiciona 'comrast' ao perfil Frota.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v7'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Frota'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "comrast"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v7', '1') ON CONFLICT(chave) DO NOTHING")

    # v8 (qualidade 2026-07-17): adiciona a tela 'qual' ao perfil Controladoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v8'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Controladoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "qual"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v8', '1') ON CONFLICT(chave) DO NOTHING")

    # v9 (portaria 2026-07-17): adiciona a tela 'port' ao perfil Operação.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v9'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Operação'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "port"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v9', '1') ON CONFLICT(chave) DO NOTHING")

    # v10 (CRM 2026-07-17): adiciona a tela 'crm' ao perfil Comercial.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v10'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Comercial'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "crm"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v10', '1') ON CONFLICT(chave) DO NOTHING")

    # v11 (RH vagas 2026-07-17): adiciona a tela 'rh' ao perfil Diretoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v11'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "rh"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v11', '1') ON CONFLICT(chave) DO NOTHING")

    # v12 (folha GLOBUS 2026-07-18): telas 'hc' e 'folha' ao perfil Diretoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v12'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            for t in ("hc", "folha"):
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], t))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v12', '1') ON CONFLICT(chave) DO NOTHING")

    # v13 (painel de custos 2026-07-18): tela 'custos' ao perfil Suprimentos.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v13'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Suprimentos'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "custos"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v13', '1') ON CONFLICT(chave) DO NOTHING")

    # v14 (indicadores de folha 2026-07-18): tela 'folhaind' ao perfil Diretoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v14'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "folhaind"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v14', '1') ON CONFLICT(chave) DO NOTHING")

    # v15 (horas extras 2026-07-18): tela 'he' ao perfil Diretoria.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v15'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "he"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v15', '1') ON CONFLICT(chave) DO NOTHING")

    # v16 (2026-07-18): perfil-modelo dedicado de Recursos Humanos — antes as
    # telas de RH só existiam embutidas no perfil amplo Diretoria, obrigando
    # a dar acesso a caixa/DRE/comercial só para liberar folha/headcount.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v16'").fetchone():
        cur = c.execute(
            "INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES(%s,%s,0,%s) ON CONFLICT(nome) DO NOTHING RETURNING id",
            ("Recursos Humanos", "Vagas, headcount, custo de folha, indicadores e horas extras.", _agora()))
        novo = cur.fetchone()
        if novo:
            _muitos(c, 
                "INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s)"
                " ON CONFLICT DO NOTHING",
                [(novo["id"], t) for t in ("rh", "hc", "folha", "folhaind", "he")])
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v16', '1') ON CONFLICT(chave) DO NOTHING")

    # v17 (orçamento 2026-07-26): tela 'orc' ao perfil Controladoria. A tela
    # nasceu depois que o perfil já existia nas bases em uso — editar
    # _PERFIS_MODELO só vale para instalação nova (mesmo caso da v8/'qual').
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v17'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Controladoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "orc"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v17', '1') ON CONFLICT(chave) DO NOTHING")

    # v18 (premiação de motoristas 2026-07-27): tela 'prem' aos perfis Frota e
    # Diretoria. A tela nasceu depois que os perfis já existiam nas bases em
    # uso — editar _PERFIS_MODELO só vale para instalação nova (mesmo caso da
    # v8/'qual' e v17/'orc').
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v18'").fetchone():
        for nome_perfil in ("Frota", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "prem"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v18', '1') ON CONFLICT(chave) DO NOTHING")

    # v19 (extrato bancário 2026-08-01): tela 'extb' aos perfis Financeiro e
    # Controladoria. A tela nasceu depois que os perfis já existiam nas bases em
    # uso — editar _PERFIS_MODELO só vale para instalação nova (mesmo caso da
    # v8/'qual', v17/'orc' e v18/'prem').
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v19'").fetchone():
        for nome_perfil in ("Financeiro", "Controladoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "extb"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v19', '1') ON CONFLICT(chave) DO NOTHING")

    # v20 (previsao de fechamento 2026-08-02): tela 'fech' aos perfis
    # Controladoria e Diretoria. Mesmo caso da v19/'extb': a tela nasceu depois
    # que os perfis ja existiam nas bases em uso.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v20'").fetchone():
        for nome_perfil in ("Controladoria", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "fech"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v20', '1') ON CONFLICT(chave) DO NOTHING")

    # v21 (documentacao 2026-08-08): tela 'doc' a TODOS os perfis existentes.
    # Diferente da v19/v20, aqui nao ha lista de perfis: documentacao nao e dado
    # sensivel e serve a todo mundo que usa o painel.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v21'").fetchone():
        for row in c.execute("SELECT id FROM perfis").fetchall():
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "doc"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v21', '1') ON CONFLICT(chave) DO NOTHING")

    # v22 (piso minimo ANTT 2026-08-18): tela 'anpiso' SO a Controladoria e
    # Diretoria -- deliberadamente restrita, ao contrario da v21.
    #
    # A tela documenta, mes a mes e por transportador, frete pago abaixo do piso
    # minimo legal. Medido em producao: 79% a 87% das viagens, R$ 1,2 a 1,6
    # milhao por mes. E informacao de risco regulatorio, nao operacional: quem
    # contrata o agregado no dia a dia (Operacao, Suprimentos) nao precisa dela
    # para trabalhar, e ampliar o acesso amplia a exposicao sem ganho.
    #
    # Diretoria entra por necessidade, nao por hierarquia: e o unico perfil com
    # usuario real. Conceder so a Controladoria faria a tela nascer invisivel --
    # foi o que aconteceu com 'extb' na v19.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v22'").fetchone():
        for nome_perfil in ("Controladoria", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "anpiso"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v22', '1') ON CONFLICT(chave) DO NOTHING")

    # v23 (RNTRC 2026-08-18): mesma restricao da v22. A tela nomeia
    # transportadores contratados com registro fora de ATIVO e o valor pago a
    # cada um -- informacao de compliance, nao operacional.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v23'").fetchone():
        for nome_perfil in ("Controladoria", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "anrntrc"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v23', '1') ON CONFLICT(chave) DO NOTHING")

    # v24 (Telemetria 2026-08-19): a Premiacao saiu do grupo Frota e passou a
    # viver em Telemetria. O perfil Frota perdeu a tela no modelo, mas quem ja
    # tinha a permissao CONTINUA com ela -- mudar de grupo no menu nao e razao
    # para tirar acesso de ninguem. Diretoria ja tinha 'prem' desde o modelo.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v24'").fetchone():
        for nome_perfil in ("Frota", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "prem"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v24', '1') ON CONFLICT(chave) DO NOTHING")

    # v25 (telas de Telemetria 2026-08-19): consumo, conducao e hodometro para
    # Frota (e a operacao da frota) e Diretoria (unico perfil com usuario real).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v25'").fetchone():
        for nome_perfil in ("Frota", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome_perfil,)).fetchone()
            if row:
                for tela in ("telcon", "telcond", "telhod"):
                    c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                              " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], tela))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v25', '1') ON CONFLICT(chave) DO NOTHING")

    # v26 (2026-08-25): perfil de CLIENTE do milk run. O seed geral e travado
    # pela flag 'perfis_modelo_v2', marcada em julho — sem um bloco novo, um
    # perfil-modelo criado depois disso nunca chega ao banco. Foi o que
    # aconteceu: o perfil existia no codigo e nao aparecia na tela de Gestao.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v26'").fetchone():
        for nome_perfil, desc, telas in _PERFIS_MODELO:
            if not nome_perfil.startswith("Cliente"):
                continue
            cur = c.execute(
                "INSERT INTO perfis(nome, descricao, admin, criado_em)"
                " VALUES(%s,%s,0,%s) ON CONFLICT(nome) DO NOTHING RETURNING id", (nome_perfil, desc, _agora()))
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                _muitos(c, "INSERT INTO perfil_telas(perfil_id, tela)"
                              " VALUES(%s,%s) ON CONFLICT DO NOTHING", [(row["id"], t) for t in telas])
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v26', '1') ON CONFLICT(chave) DO NOTHING")

    # v27 (2026-08-25): tela 'cnh' aos perfis que ja cuidam de gente e de
    # frota. Mesmo motivo dos blocos acima: o seed geral esta travado desde
    # julho, entao tela nova nunca chega sozinha a um perfil existente.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v27'").fetchone():
        for nome_perfil in ("Recursos Humanos", "Diretoria", "Frota"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                          " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], "cnh"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v27', '1') ON CONFLICT(chave) DO NOTHING")

    # v28 (2026-08-25): tela 'ferias'. Mesmo motivo dos blocos anteriores — o
    # seed geral esta travado desde julho e tela nova nao chega sozinha a
    # perfil que ja existe.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v28'").fetchone():
        for nome_perfil in ("Recursos Humanos", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                          " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], "ferias"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v28', '1') ON CONFLICT(chave) DO NOTHING")

    # v29 (2026-08-25): tela 'pneus'.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v29'").fetchone():
        for nome_perfil in ("Frota", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                          " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], "pneus"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v29', '1') ON CONFLICT(chave) DO NOTHING")

    # v30 (2026-08-25): tela 'people'.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v30'").fetchone():
        for nome_perfil in ("Recursos Humanos", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                          " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], "people"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v30', '1') ON CONFLICT(chave) DO NOTHING")

    # v31 (2026-08-26): tela 'poli' (permanencia nos poligonos da Tupy).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v31'").fetchone():
        for nome_perfil in ("Operação", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                          " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], "poli"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v31', '1') ON CONFLICT(chave) DO NOTHING")

    # v32 (2026-08-26): tela 'ctecp' (CT-e de contrapartida do agregado).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v32'").fetchone():
        for nome_perfil in ("Controladoria", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s",
                            (nome_perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                          " VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], "ctecp"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v32', '1') ON CONFLICT(chave) DO NOTHING")

    # v33 (2026-08-28): concedeu a tela 'ctetx' a Controladoria e Diretoria.
    # A tela durou horas: virou ABA dentro da 'ctecp', porque acompanhar a fila
    # e acompanhar o que saiu sao a mesma sessao de trabalho e nao mereciam
    # duas entradas no menu. O bloco fica registrado aqui como historia; quem
    # limpa e a v34.

    # v34 (2026-08-28): recolhe as concessoes da v33. Sem isto, `perfil_telas`
    # guarda para sempre linhas apontando para uma tela que nao existe mais em
    # `TELAS` - invisiveis na interface e confusas para quem for ler a tabela.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v34'").fetchone():
        c.execute("DELETE FROM perfil_telas WHERE tela='ctetx'")
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v34', '1') ON CONFLICT(chave) DO NOTHING")

    # v35 (2026-09-01): painel de TV da diretoria ('tvdir') ao perfil
    # Diretoria — é o mural dela. Sem a concessão, tela nova só aparece para
    # administrador, e ninguém da sala em que a TV fica conseguiria abri-la.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v35'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Diretoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "tvdir"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v35', '1') ON CONFLICT(chave) DO NOTHING")

    # v36 (2026-09-01): Faturamento Detalhado ('fat') para Diretoria,
    # Comercial e Financeiro — a tela é leitura executiva das emissões
    # contra a meta; sem a concessão, id novo só aparece para administrador.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v36'").fetchone():
        for perfil in ("Diretoria", "Comercial", "Financeiro"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "fat"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v36', '1') ON CONFLICT(chave) DO NOTHING")

    # v37 (2026-09-01): a tela 'fat' mudou do grupo BI para Controladoria a
    # pedido do dono — o perfil Controladoria passa a ve-la (os grants da v36
    # continuam valendo; grupo do menu nao e RBAC, mas tela no grupo que o
    # perfil habita sem o perfil poder abri-la seria um menu que mente).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v37'").fetchone():
        row = c.execute("SELECT id FROM perfis WHERE nome='Controladoria'").fetchone()
        if row:
            c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      (row["id"], "fat"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v37', '1') ON CONFLICT(chave) DO NOTHING")

    # v38 (2026-09-01): Gerenciamento de Risco ('gr') para Operação e
    # Diretoria — a tela nasce da Fase 1 do módulo RasterIntegra (eventos do
    # hub, cobertura de GR nas viagens e frescor por fonte, lidos do ERP).
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v38'").fetchone():
        for perfil in ("Operação", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "gr"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v38', '1') ON CONFLICT(chave) DO NOTHING")

    # v39 (2026-09-01): Portal Tupy ('tupy') para Financeiro e Diretoria —
    # a validação do que a API da Monkey entrega (espelho mky_recebiveis):
    # antecipado por mês, taxa, deságio, investidores e a conferência com a
    # posição do painel de Antecipações.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v39'").fetchone():
        for perfil in ("Financeiro", "Diretoria"):
            row = c.execute("SELECT id FROM perfis WHERE nome=%s", (perfil,)).fetchone()
            if row:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (row["id"], "tupy"))
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v39', '1') ON CONFLICT(chave) DO NOTHING")

    # v40 (2026-09-01): o Portal Tupy deixou de ser tela — é a primeira aba de
    # Portais de Antecipação ('antport'), a pedido do dono (um menu a menos).
    # Quem via 'tupy' passa a ver 'antport' (a substituta HERDA o acesso; sem
    # isto a Diretoria perderia o portal) e o grant órfão sai.
    if not c.execute("SELECT 1 FROM config WHERE chave='perfis_modelo_v40'").fetchone():
        c.execute("INSERT INTO perfil_telas(perfil_id, tela)"
                  " SELECT perfil_id, 'antport' FROM perfil_telas WHERE tela='tupy'"
                  " ON CONFLICT DO NOTHING")
        c.execute("DELETE FROM perfil_telas WHERE tela='tupy'")
        c.execute("INSERT INTO config(chave, valor) VALUES('perfis_modelo_v40', '1') ON CONFLICT(chave) DO NOTHING")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cfg(chave: str) -> int:
    with _conn() as c:
        row = c.execute("SELECT valor FROM config WHERE chave=%s", (chave,)).fetchone()
    try:
        return int(row["valor"]) if row else int(_CONFIG_PADRAO[chave])
    except (ValueError, KeyError):
        return int(_CONFIG_PADRAO.get(chave, "0"))


def audit(usuario: str, acao: str, alvo: str = "", detalhe: str = "", ip: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(%s,%s,%s,%s,%s,%s)",
            (_agora(), usuario, acao, alvo, detalhe, ip),
        )


def _telas_do_perfil(c: psycopg.Connection, perfil_id: int, admin: bool) -> list[str]:
    if admin:
        return list(TELAS.keys())
    rows = c.execute("SELECT tela FROM perfil_telas WHERE perfil_id=%s", (perfil_id,)).fetchall()
    return [r["tela"] for r in rows if r["tela"] in TELAS]


# ---------------------------------------------------------------- sessão/JWT

def _emitir_token(usuario_id: int, token_ver: int) -> str:
    agora = datetime.now(timezone.utc)
    ttl = max(5, cfg("sessao_ttl_min"))
    return jwt.encode(
        {"sub": str(usuario_id), "ver": token_ver,
         "iat": agora, "exp": agora + timedelta(minutes=ttl)},
        SECRET, algorithm="HS256",
    )


def _cookie_kwargs(https: bool) -> dict:
    return {"key": COOKIE, "httponly": True, "samesite": "lax", "path": "/", "secure": https}


def _set_cookie(resp: Response, token: str, https: bool) -> None:
    resp.set_cookie(value=token, max_age=cfg("sessao_ttl_min") * 60, **_cookie_kwargs(https))


def _https(request: Request) -> bool:
    return (request.headers.get("x-forwarded-proto", request.url.scheme) == "https")


def sessao_atual(token: str | None) -> dict | None:
    """Valida o JWT e carrega o usuário. None = sem sessão válida."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    with _conn() as c:
        u = c.execute(
            """SELECT u.*, p.nome AS perfil_nome, p.admin AS perfil_admin,
                      f.atualizado_em AS foto_em
               FROM usuarios u
               JOIN perfis p ON p.id = u.perfil_id
               LEFT JOIN usuario_fotos f ON f.usuario_id = u.id
               WHERE u.id = %s""", (int(claims["sub"]),),
        ).fetchone()
        if not u or not u["ativo"] or u["token_ver"] != claims.get("ver"):
            return None
        telas = _telas_do_perfil(c, u["perfil_id"], bool(u["perfil_admin"]))
    return {
        "id": u["id"], "nome": u["nome"], "email": u["email"],
        "perfil_id": u["perfil_id"], "perfil": u["perfil_nome"],
        "admin": bool(u["perfil_admin"]), "telas": telas,
        "deve_trocar_senha": bool(u["deve_trocar_senha"]),
        "telefone": u["telefone"] or "", "cargo": u["cargo"] or "",
        "setor": u["setor"] or "", "ramal": u["ramal"] or "",
        "foto_em": u["foto_em"],
        "token_ver": u["token_ver"], "exp": claims["exp"], "iat": claims["iat"],
    }


def _payload_me(s: dict) -> dict:
    # `telefone_fmt` vai junto do normalizado de propósito: o banco guarda
    # `5547999998888` (é o que faz contagem e comparação baterem) e a tela
    # mostra `(47) 99999-8888`. Formatar no cliente seria reescrever em
    # JavaScript uma regra que já existe em Python, com o risco de as duas
    # discordarem em algum caso de borda.
    dados = {k: s[k] for k in ("id", "nome", "email", "perfil", "perfil_id",
                               "admin", "telas", "deve_trocar_senha",
                               "telefone", "cargo", "setor", "ramal", "foto_em")}
    dados["telefone_fmt"] = telefones.formatar(s["telefone"]) if s["telefone"] else ""
    return dados


# ---------------------------------------------------------------- middleware

def _cookie_do_scope(scope) -> str | None:
    cookies = Headers(scope=scope).get("cookie") or ""
    for parte in cookies.split(";"):
        nome, _, valor = parte.strip().partition("=")
        if nome == COOKIE:
            return valor or None
    return None


def _telas_da_rota(path: str) -> frozenset[str] | None:
    for prefixo, telas in ROTA_TELAS:
        if path.startswith(prefixo):
            return telas
    return None


class AuthMiddleware:
    """ASGI puro (não bufferiza o SSE do copiloto). Protege todo /api/*."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if _rota_publica(path):
            return await self.app(scope, receive, send)

        # digest de alertas: uso do cron local, sem sessão
        if path.startswith("/api/alertas/digest"):
            cliente = (scope.get("client") or ("", 0))[0]
            if _local_direto(Headers(scope=scope), cliente):
                return await self.app(scope, receive, send)

        sess = sessao_atual(_cookie_do_scope(scope))
        if sess is None:
            resp = JSONResponse(status_code=401, content={
                "erro": "nao_autenticado", "mensagem": "Faça login para continuar."})
            return await resp(scope, receive, send)

        if path.startswith("/api/gestao") and not sess["admin"]:
            resp = JSONResponse(status_code=403, content={
                "erro": "sem_permissao",
                "mensagem": "Área restrita ao perfil administrador."})
            return await resp(scope, receive, send)

        telas = _telas_da_rota(path)
        if telas is not None:
            if not sess["admin"] and not (telas & set(sess["telas"])):
                resp = JSONResponse(status_code=403, content={
                    "erro": "sem_permissao",
                    "mensagem": "Seu perfil não tem acesso a esta área."})
                return await resp(scope, receive, send)
        elif (path.startswith("/api/") and not path.startswith("/api/gestao")
              and not rota_sem_tela(path) and not sess["admin"]):
            # fail-closed: rota /api/* sem mapeamento em ROTA_TELAS (nem
            # autoservico de conta, nem /api/gestao — já gated acima) é
            # bloqueada por padrão pra usuário não-admin. Toda rota nova
            # precisa ganhar uma entrada em ROTA_TELAS (ou entrar aqui, se
            # for genuinamente sem tela) — nunca fica aberta por esquecimento.
            resp = JSONResponse(status_code=403, content={
                "erro": "sem_permissao",
                "mensagem": "Rota não mapeada em nenhuma tela — acesso negado."})
            return await resp(scope, receive, send)

        scope.setdefault("state", {})["sessao"] = sess

        # renovação deslizante: reemite o cookie quando passou metade do TTL.
        # NUNCA em /api/auth/*: logout e trocar-senha emitem o próprio Set-Cookie
        # (o cookie de renovação apagaria o delete/trocaria por token_ver antigo).
        novo_cookie: str | None = None
        exp = datetime.fromtimestamp(sess["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(sess["iat"], tz=timezone.utc)
        if not path.startswith("/api/auth/") and datetime.now(timezone.utc) > iat + (exp - iat) / 2:
            https = Headers(scope=scope).get("x-forwarded-proto", scope.get("scheme")) == "https"
            token = _emitir_token(sess["id"], sess["token_ver"])
            tmp = Response()
            _set_cookie(tmp, token, https)
            novo_cookie = tmp.headers["set-cookie"]

        async def send_com_cookie(message):
            if novo_cookie and message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", novo_cookie.encode()))
                message = {**message, "headers": headers}
            await send(message)

        return await self.app(scope, receive, send_com_cookie if novo_cookie else send)


# ------------------------------------------- cadastro: campos opcionais e foto

# Telefone, cargo, setor, ramal e foto são OPCIONAIS. A base de produção já
# tinha usuários quando estes campos nasceram, e um campo obrigatório aqui
# significaria alguém sem conseguir entrar no sistema por causa do próprio
# cadastro — preço alto demais para um dado de conveniência.
#
# "Ausente" e "vazio" são coisas DIFERENTES no payload de edição, e por isso o
# sentinela: a tela de Minha Conta manda só telefone e ramal, e um `.get()`
# comum leria os campos que ela não manda como string vazia, APAGANDO o cargo
# que o administrador preencheu. Chave ausente = não mexe; chave vazia = limpa.
_AUSENTE = object()

# Limites de tamanho: o suficiente para o que existe ("Coordenadora de
# Controladoria" tem 27), curto o bastante para não virar campo de observação.
_CAMPOS_TEXTO = {"cargo": 60, "setor": 60, "ramal": 12}
_ROTULO = {"cargo": "cargo", "setor": "setor", "ramal": "ramal"}


def _cadastro_do_payload(payload: dict) -> tuple[dict, str | None]:
    """Os campos opcionais que vieram no payload, já normalizados.

    O telefone passa pelo MESMO validador do WhatsApp (`api/whatsapp/numeros`):
    ter duas noções de "telefone válido" na casa acabaria com um número que o
    cadastro aceita e o envio recusa — e a pessoa descobrindo isso na hora em
    que a mensagem não chega.
    """
    dados: dict = {}
    if payload.get("telefone", _AUSENTE) is not _AUSENTE:
        bruto = str(payload.get("telefone") or "").strip()
        if not bruto:
            dados["telefone"] = None
        else:
            try:
                dados["telefone"] = telefones.normalizar(bruto)
            except telefones.TelefoneInvalido as exc:
                return {}, str(exc)
    for campo, limite in _CAMPOS_TEXTO.items():
        if payload.get(campo, _AUSENTE) is _AUSENTE:
            continue
        # espaço duplo vindo de copiar-colar não pode virar duas grafias do
        # mesmo setor (mesmo cuidado do Painel de Custos com "1 - FIL  MTZ")
        valor = " ".join(str(payload.get(campo) or "").split())
        if len(valor) > limite:
            return {}, f"O {_ROTULO[campo]} passa de {limite} caracteres."
        dados[campo] = valor or None
    return dados, None


def _gravar_foto(c, usuario_id: int, valor) -> str:
    """Grava (ou remove, se o valor vier vazio) a foto. Devolve o rótulo para a
    trilha de auditoria. Levanta `fotos.FotoInvalida` com a mensagem pronta."""
    if not str(valor or "").strip():
        c.execute("DELETE FROM usuario_fotos WHERE usuario_id=%s", (usuario_id,))
        return "foto_removida"
    dados, mime, largura, altura = fotos.validar(str(valor))
    c.execute(
        """INSERT INTO usuario_fotos(usuario_id, mime, largura, altura, bytes,
                                     atualizado_em)
           VALUES(%s,%s,%s,%s,%s,%s)
           ON CONFLICT(usuario_id) DO UPDATE SET
             mime=EXCLUDED.mime, largura=EXCLUDED.largura,
             altura=EXCLUDED.altura, bytes=EXCLUDED.bytes,
             atualizado_em=EXCLUDED.atualizado_em""",
        (usuario_id, mime, largura, altura, dados, _agora()))
    return f"foto_atualizada ({largura}x{altura}, {len(dados) // 1024} KB)"


# ---------------------------------------------------------------- rotas: auth

router_auth = APIRouter(prefix="/api/auth")

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def _ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


def _sem_usuarios() -> bool:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"] == 0


def _req_local_direto(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1") and not request.headers.get("cf-connecting-ip")


@router_auth.get("/setup-status")
def setup_status(request: Request) -> JSONResponse:
    # via túnel público o setup nunca é oferecido — só no acesso local direto
    return JSONResponse({"precisa_setup": _sem_usuarios() and _req_local_direto(request)})


@router_auth.post("/setup")
def setup(payload: dict, request: Request) -> JSONResponse:
    """Cria o PRIMEIRO administrador. Só com a base vazia e acesso local direto."""
    if not _req_local_direto(request):
        return JSONResponse(status_code=403, content={
            "erro": "somente_local",
            "mensagem": "O primeiro acesso é feito localmente: http://127.0.0.1:8010"})
    if not _sem_usuarios():
        return JSONResponse(status_code=403, content={
            "erro": "setup_ja_feito", "mensagem": "Já existe usuário cadastrado."})
    nome = (payload.get("nome") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    senha = payload.get("senha") or ""
    if not nome or not _EMAIL_RE.match(email):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe nome e e-mail válidos."})
    if len(senha) < cfg("senha_min"):
        return JSONResponse(status_code=422, content={
            "erro": "senha_fraca",
            "mensagem": f"A senha precisa de ao menos {cfg('senha_min')} caracteres."})
    with _conn() as c:
        perfil = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        cur = c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES(%s,%s,%s,%s,1,0,%s) RETURNING id""",
            (nome, email, _ph.hash(senha), perfil["id"], _agora()))
        uid = cur.fetchone()["id"]
    audit(email, "setup_admin", alvo=email, detalhe="primeiro administrador criado",
          ip=_ip(request))
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, _emitir_token(uid, 0), _https(request))
    return resp


@router_auth.post("/login")
def login(payload: dict, request: Request) -> JSONResponse:
    email = (payload.get("email") or "").strip().lower()
    senha = payload.get("senha") or ""
    generico = JSONResponse(status_code=401, content={
        "erro": "credenciais_invalidas", "mensagem": "E-mail ou senha incorretos."})
    if not email or not senha:
        return generico
    with _conn() as c:
        u = c.execute("SELECT * FROM usuarios WHERE email=%s", (email,)).fetchone()
    if not u:
        _ph.hash(senha)  # iguala o tempo de resposta p/ e-mail inexistente
        audit(email, "login_falha", detalhe="usuario_inexistente", ip=_ip(request))
        return generico
    if not u["ativo"]:
        audit(email, "login_falha", detalhe="usuario_inativo", ip=_ip(request))
        return generico
    if u["bloqueado_ate"] and u["bloqueado_ate"] > _agora():
        audit(email, "login_falha", detalhe="conta_bloqueada", ip=_ip(request))
        return JSONResponse(status_code=401, content={
            "erro": "conta_bloqueada",
            "mensagem": f"Conta bloqueada por tentativas até {u['bloqueado_ate'][11:16]}."})
    try:
        _ph.verify(u["senha_hash"], senha)
    except VerifyMismatchError:
        # incremento atômico (evita corrida que esticaria o limite de tentativas)
        with _conn() as c:
            falhas = c.execute(
                "UPDATE usuarios SET falhas=falhas+1 WHERE id=%s RETURNING falhas",
                (u["id"],)).fetchone()["falhas"]
            bloqueio = None
            if falhas >= cfg("max_tentativas"):
                bloqueio = (datetime.now() + timedelta(minutes=cfg("bloqueio_min"))
                            ).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("UPDATE usuarios SET falhas=0, bloqueado_ate=%s WHERE id=%s",
                          (bloqueio, u["id"]))
        audit(email, "login_falha",
              detalhe="senha_incorreta" + ("; conta bloqueada" if bloqueio else ""),
              ip=_ip(request))
        return generico
    with _conn() as c:
        c.execute("UPDATE usuarios SET falhas=0, bloqueado_ate=NULL, ultimo_login=%s WHERE id=%s",
                  (_agora(), u["id"]))
    audit(email, "login_ok", ip=_ip(request))
    token = _emitir_token(u["id"], u["token_ver"])
    sess = sessao_atual(token)
    resp = JSONResponse(_payload_me(sess))
    _set_cookie(resp, token, _https(request))
    return resp


@router_auth.get("/me")
def me(request: Request) -> JSONResponse:
    return JSONResponse(_payload_me(request.state.sessao))


@router_auth.post("/logout")
def logout(request: Request) -> JSONResponse:
    sess = request.state.sessao
    # invalida a sessão no servidor (token roubado deixa de valer, não só o cookie)
    with _conn() as c:
        c.execute("UPDATE usuarios SET token_ver=token_ver+1 WHERE id=%s", (sess["id"],))
    audit(sess["email"], "logout", ip=_ip(request))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router_auth.post("/trocar-senha")
def trocar_senha(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    atual, nova = payload.get("senha_atual") or "", payload.get("senha_nova") or ""
    if len(nova) < cfg("senha_min"):
        return JSONResponse(status_code=422, content={
            "erro": "senha_fraca",
            "mensagem": f"A nova senha precisa de ao menos {cfg('senha_min')} caracteres."})
    with _conn() as c:
        u = c.execute("SELECT senha_hash FROM usuarios WHERE id=%s", (sess["id"],)).fetchone()
    try:
        _ph.verify(u["senha_hash"], atual)
    except VerifyMismatchError:
        return JSONResponse(status_code=401, content={
            "erro": "senha_incorreta", "mensagem": "A senha atual não confere."})
    nova_ver = sess["token_ver"] + 1
    with _conn() as c:
        c.execute("UPDATE usuarios SET senha_hash=%s, deve_trocar_senha=0, token_ver=%s WHERE id=%s",
                  (_ph.hash(nova), nova_ver, sess["id"]))
    audit(sess["email"], "trocar_senha", ip=_ip(request))
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, _emitir_token(sess["id"], nova_ver), _https(request))
    return resp


@router_auth.post("/perfil")
def perfil_editar(payload: dict, request: Request) -> JSONResponse:
    """O que o próprio usuário mexe na conta dele: telefone, ramal e foto.

    NOME, E-MAIL, CARGO E SETOR NÃO ESTÃO AQUI, e a ausência é a decisão. Nome
    e e-mail identificam a pessoa na trilha de auditoria — quem pode reescrever
    o próprio nome reescreve a assinatura de tudo o que já fez. Cargo e setor
    são estrutura da empresa, que outras pessoas leem como se fosse verdade
    conferida; é dado do administrador, não autodeclaração. Telefone e foto são
    contato e rosto: só a própria pessoa sabe.
    """
    sess = request.state.sessao
    dados, erro = _cadastro_do_payload(
        {k: payload[k] for k in ("telefone", "ramal") if k in payload})
    if erro:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": erro})
    detalhes = []
    with _conn() as c:
        if dados:
            campos = ", ".join(f"{k}=%s" for k in dados)
            c.execute(f"UPDATE usuarios SET {campos} WHERE id=%s",
                      (*dados.values(), sess["id"]))
            detalhes += list(dados)
        if payload.get("foto", _AUSENTE) is not _AUSENTE:
            try:
                detalhes.append(_gravar_foto(c, sess["id"], payload["foto"]))
            except fotos.FotoInvalida as exc:
                # o UPDATE acima está na MESMA transação: sem o rollback, a
                # tela diria "foto recusada" e o telefone teria mudado assim
                # mesmo — meia gravação que ninguém pediu
                c.rollback()
                return JSONResponse(status_code=422, content={
                    "erro": "foto_invalida", "mensagem": str(exc)})
    if not detalhes:
        return JSONResponse({"ok": True, "mensagem": "Nada a alterar."})
    audit(sess["email"], "perfil_editar", alvo=sess["email"],
          detalhe="; ".join(detalhes), ip=_ip(request))
    # devolve o `me` já atualizado: a tela usa isso para repintar o avatar e o
    # menu sem uma segunda ida à API
    return JSONResponse(_payload_me(sessao_atual(request.cookies.get(COOKIE)) or sess))


@router_auth.get("/foto/{usuario_id}")
def foto_servir(usuario_id: int, request: Request) -> Response:
    """A foto de um usuário, para o avatar da barra e a lista da Gestão.

    Qualquer usuário logado enxerga a foto de qualquer outro — é o rosto de um
    colega numa tela interna, não dado de escopo. O que NÃO pode é sair sem
    sessão: o middleware cobre isso (a rota está em `_ROTAS_SEM_TELA`, que
    exige sessão e dispensa tela).

    Cache com ETag e não com validade longa: a foto trocada tem de aparecer no
    mesmo dia. A tela ainda assim manda `?v=<carimbo>` na URL, então o 304 aqui
    é a segunda linha de defesa, não a única.
    """
    with _conn() as c:
        f = c.execute(
            "SELECT mime, bytes, atualizado_em FROM usuario_fotos WHERE usuario_id=%s",
            (usuario_id,)).fetchone()
    if not f:
        return JSONResponse(status_code=404, content={
            "erro": "sem_foto", "mensagem": "Este usuário não tem foto de perfil."})
    etag = '"%s"' % str(f["atualizado_em"]).replace('"', "")
    cabecalhos = {"ETag": etag, "Cache-Control": "private, max-age=300"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cabecalhos)
    return Response(content=bytes(f["bytes"]), media_type=f["mime"],
                    headers=cabecalhos)


# ---------------------------------------------------------------- rotas: gestão
# (middleware já garante sessão + admin em tudo que está sob /api/gestao)

router_gestao = APIRouter(prefix="/api/gestao")


@router_gestao.get("/telas")
def telas_registro() -> JSONResponse:
    return JSONResponse({"telas": [
        {"chave": k, "rotulo": rot, "grupo": grp} for k, (rot, grp) in TELAS.items()]})


@router_gestao.get("/usuarios")
def usuarios_lista() -> JSONResponse:
    with _conn() as c:
        rows = c.execute(
            """SELECT u.id, u.nome, u.email, u.perfil_id, p.nome AS perfil,
                      p.admin AS perfil_admin, u.ativo, u.deve_trocar_senha,
                      u.bloqueado_ate, u.criado_em, u.ultimo_login,
                      u.telefone, u.cargo, u.setor, u.ramal,
                      f.atualizado_em AS foto_em
               FROM usuarios u
               JOIN perfis p ON p.id=u.perfil_id
               LEFT JOIN usuario_fotos f ON f.usuario_id=u.id
               ORDER BY u.nome""").fetchall()
    # `foto_em` (e nunca os bytes) é o que a lista precisa: diz se há foto e
    # serve de versão na URL da imagem, para trocar de foto aparecer na hora
    # sem que o navegador precise deixar de cachear as outras.
    usuarios = []
    for r in rows:
        u = dict(r)
        u["telefone_fmt"] = telefones.formatar(u["telefone"]) if u["telefone"] else ""
        usuarios.append(u)
    return JSONResponse({"usuarios": usuarios})


def _valida_usuario_payload(payload: dict, novo: bool) -> tuple[dict | None, str | None]:
    nome = (payload.get("nome") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    if novo and (not nome or not _EMAIL_RE.match(email)):
        return None, "Informe nome e e-mail válidos."
    if email and not _EMAIL_RE.match(email):
        return None, "E-mail inválido."
    extras, erro = _cadastro_do_payload(payload)
    if erro:
        return None, erro
    return {"nome": nome, "email": email, "extras": extras}, None


def _admins_ativos_exceto(c: psycopg.Connection, usuario_id: int) -> int:
    return c.execute(
        """SELECT COUNT(*) AS n FROM usuarios u JOIN perfis p ON p.id=u.perfil_id
           WHERE p.admin=1 AND u.ativo=1 AND u.id<>%s""", (usuario_id,)).fetchone()["n"]


@router_gestao.post("/usuarios")
def usuario_criar(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    dados, erro = _valida_usuario_payload(payload, novo=True)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    # SENHA GERADA quando quem cadastra pede o e-mail de boas-vindas: senha
    # provisória escolhida por gente vira "Mudar@123" em toda a empresa, e aí
    # o elo fraco deixa de ser o e-mail e passa a ser o padrão que todo mundo
    # conhece. Quem prefere entregar a senha pessoalmente continua digitando a
    # sua.
    manda_email = bool(payload.get("enviar_boas_vindas"))
    senha = payload.get("senha_temporaria") or ""
    if manda_email and not senha:
        from api.correio.boas_vindas import gerar_senha
        senha = gerar_senha()
    if len(senha) < cfg("senha_min"):
        return JSONResponse(status_code=422, content={
            "erro": "senha_fraca",
            "mensagem": f"A senha temporária precisa de ao menos {cfg('senha_min')} caracteres."})
    perfil_id = payload.get("perfil_id")
    with _conn() as c:
        if not isinstance(perfil_id, int) or not c.execute(
                "SELECT 1 FROM perfis WHERE id=%s", (perfil_id,)).fetchone():
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "Perfil inexistente."})
        extras = dados["extras"]
        colunas = ", ".join(extras)
        marcas = ", ".join(["%s"] * len(extras))
        try:
            cur = c.execute(
                f"""INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                         deve_trocar_senha, criado_em
                                         {", " + colunas if colunas else ""})
                    VALUES(%s,%s,%s,%s,1,1,%s{", " + marcas if marcas else ""})
                    RETURNING id""",
                (dados["nome"], dados["email"], _ph.hash(senha), perfil_id, _agora(),
                 *extras.values()))
            novo_id = cur.fetchone()["id"]
        except psycopg.errors.UniqueViolation:
            return JSONResponse(status_code=422, content={
                "erro": "email_em_uso", "mensagem": "Já existe usuário com esse e-mail."})
        extra_foto = []
        if payload.get("foto", _AUSENTE) is not _AUSENTE:
            try:
                extra_foto.append(_gravar_foto(c, novo_id, payload["foto"]))
            except fotos.FotoInvalida as exc:
                # o usuário JÁ foi criado nesta transação; recusar a foto agora
                # e deixar o INSERT valer seria criar alguém pela metade sem
                # dizer. A transação inteira volta atrás.
                c.rollback()
                return JSONResponse(status_code=422, content={
                    "erro": "foto_invalida", "mensagem": str(exc)})
    audit(sess["email"], "usuario_criar", alvo=dados["email"],
          detalhe="; ".join([f"perfil_id={perfil_id}", *dados["extras"], *extra_foto]),
          ip=_ip(request))

    # O E-MAIL VEM DEPOIS DO COMMIT, E A FALHA DELE NÃO DESFAZ O CADASTRO.
    # O usuário já existe quando isto roda; se o envio falhar, quem cadastrou
    # precisa SABER para entregar a senha por outro caminho — mas apagar o
    # usuário por causa do e-mail seria trocar um problema pequeno por um
    # grande. A resposta diz as duas coisas separadas.
    resp = {"ok": True, "id": novo_id}
    if manda_email:
        from api.correio import boas_vindas
        with _conn() as c:
            p = c.execute("SELECT nome, admin FROM perfis WHERE id=%s",
                          (perfil_id,)).fetchone() or {}
            tl = [r["tela"] for r in c.execute(
                "SELECT tela FROM perfil_telas WHERE perfil_id=%s",
                (perfil_id,)).fetchall()]
        r = boas_vindas.enviar_boas_vindas(
            dados["email"], dados["nome"], senha, _url_painel(),
            telas=tl, admin=bool(p.get("admin")), perfil=p.get("nome") or "",
            autor=sess["email"])
        resp["email"] = {"ok": bool(r.get("ok")), "erro": r.get("erro") or ""}
        # A SENHA NÃO ENTRA NA TRILHA. Registra-se que o e-mail saiu, para quem
        # e quando — trilha com segredo dentro é pior que o e-mail.
        audit(sess["email"], "usuario_boas_vindas", alvo=dados["email"],
              detalhe="enviado" if r.get("ok") else f"falhou: {r.get('erro','')}",
              ip=_ip(request))
        # Quando o e-mail NÃO saiu, a senha volta para quem cadastrou — é a
        # única forma de a pessoa entrar. Quando saiu, ela não volta: já está
        # na caixa de quem vai usar, e ecoá-la aqui a poria também no log do
        # navegador de quem cadastrou.
        if not r.get("ok"):
            resp["senha_temporaria"] = senha
    return JSONResponse(resp)


def _url_painel() -> str:
    """Endereço público do painel, de `CORTEX_URL`. Sem padrão de propósito."""
    try:
        from api import credenciais
        return (credenciais.ler("CORTEX_URL") or "").strip().rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


@router_gestao.post("/usuarios/{usuario_id}")
def usuario_editar(usuario_id: int, payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    dados, erro = _valida_usuario_payload(payload, novo=False)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    with _conn() as c:
        u = c.execute(
            """SELECT u.*, p.admin AS perfil_admin FROM usuarios u
               JOIN perfis p ON p.id=u.perfil_id WHERE u.id=%s""", (usuario_id,)).fetchone()
        if not u:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Usuário não existe."})

        mudancas, valores, detalhes = [], [], []
        if dados["nome"]:
            mudancas.append("nome=%s"); valores.append(dados["nome"]); detalhes.append("nome")
        if dados["email"] and dados["email"] != u["email"]:
            mudancas.append("email=%s"); valores.append(dados["email"]); detalhes.append("email")

        for campo, valor in dados["extras"].items():
            if valor != u[campo]:
                mudancas.append(f"{campo}=%s"); valores.append(valor)
                detalhes.append(campo if valor else f"{campo} (limpo)")

        if isinstance(payload.get("perfil_id"), int) and payload["perfil_id"] != u["perfil_id"]:
            novo_p = c.execute("SELECT * FROM perfis WHERE id=%s", (payload["perfil_id"],)).fetchone()
            if not novo_p:
                return JSONResponse(status_code=422, content={
                    "erro": "parametro_invalido", "mensagem": "Perfil inexistente."})
            if u["perfil_admin"] and not novo_p["admin"] and u["ativo"] \
                    and _admins_ativos_exceto(c, usuario_id) == 0:
                return JSONResponse(status_code=422, content={
                    "erro": "ultimo_admin",
                    "mensagem": "Não é possível rebaixar o último administrador ativo."})
            mudancas.append("perfil_id=%s"); valores.append(payload["perfil_id"])
            detalhes.append(f"perfil_id={payload['perfil_id']}")
            mudancas.append("token_ver=token_ver+1")  # força novo login com o novo perfil

        if isinstance(payload.get("ativo"), bool) and payload["ativo"] != bool(u["ativo"]):
            if not payload["ativo"]:
                if usuario_id == sess["id"]:
                    return JSONResponse(status_code=422, content={
                        "erro": "auto_desativacao",
                        "mensagem": "Você não pode desativar o próprio usuário."})
                if u["perfil_admin"] and _admins_ativos_exceto(c, usuario_id) == 0:
                    return JSONResponse(status_code=422, content={
                        "erro": "ultimo_admin",
                        "mensagem": "Não é possível desativar o último administrador ativo."})
            mudancas.append("ativo=%s"); valores.append(int(payload["ativo"]))
            mudancas.append("token_ver=token_ver+1")
            detalhes.append("ativado" if payload["ativo"] else "desativado")

        senha_nova = payload.get("resetar_senha") or ""
        if senha_nova:
            if len(senha_nova) < cfg("senha_min"):
                return JSONResponse(status_code=422, content={
                    "erro": "senha_fraca",
                    "mensagem": f"A senha precisa de ao menos {cfg('senha_min')} caracteres."})
            mudancas += ["senha_hash=%s", "deve_trocar_senha=1", "token_ver=token_ver+1",
                         "falhas=0", "bloqueado_ate=NULL"]
            valores.append(_ph.hash(senha_nova))
            detalhes.append("senha_resetada")

        if payload.get("desbloquear"):
            mudancas += ["falhas=0", "bloqueado_ate=NULL"]
            detalhes.append("desbloqueado")

        if payload.get("foto", _AUSENTE) is not _AUSENTE:
            try:
                detalhes.append(_gravar_foto(c, usuario_id, payload["foto"]))
            except fotos.FotoInvalida as exc:
                c.rollback()
                return JSONResponse(status_code=422, content={
                    "erro": "foto_invalida", "mensagem": str(exc)})

        if not mudancas:
            if detalhes:   # só a foto mudou — já gravada acima
                audit(sess["email"], "usuario_editar", alvo=u["email"],
                      detalhe="; ".join(detalhes), ip=_ip(request))
                return JSONResponse({"ok": True})
            return JSONResponse({"ok": True, "mensagem": "Nada a alterar."})
        try:
            c.execute(f"UPDATE usuarios SET {', '.join(mudancas)} WHERE id=%s",
                      (*valores, usuario_id))
        except psycopg.errors.UniqueViolation:
            return JSONResponse(status_code=422, content={
                "erro": "email_em_uso", "mensagem": "Já existe usuário com esse e-mail."})
    audit(sess["email"], "usuario_editar", alvo=u["email"],
          detalhe="; ".join(detalhes), ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.post("/usuarios/{usuario_id}/excluir")
def usuario_excluir(usuario_id: int, request: Request) -> JSONResponse:
    sess = request.state.sessao
    if usuario_id == sess["id"]:
        return JSONResponse(status_code=422, content={
            "erro": "auto_exclusao", "mensagem": "Você não pode excluir o próprio usuário."})
    with _conn() as c:
        u = c.execute(
            """SELECT u.email, u.ativo, p.admin AS perfil_admin FROM usuarios u
               JOIN perfis p ON p.id=u.perfil_id WHERE u.id=%s""", (usuario_id,)).fetchone()
        if not u:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Usuário não existe."})
        if u["perfil_admin"] and u["ativo"] and _admins_ativos_exceto(c, usuario_id) == 0:
            return JSONResponse(status_code=422, content={
                "erro": "ultimo_admin",
                "mensagem": "Não é possível excluir o último administrador ativo."})
        c.execute("DELETE FROM usuarios WHERE id=%s", (usuario_id,))
    audit(sess["email"], "usuario_excluir", alvo=u["email"], ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.get("/perfis")
def perfis_lista() -> JSONResponse:
    with _conn() as c:
        perfis = [dict(r) for r in c.execute(
            """SELECT p.*, (SELECT COUNT(*) FROM usuarios u WHERE u.perfil_id=p.id) AS usuarios
               FROM perfis p ORDER BY p.admin DESC, p.nome""").fetchall()]
        for p in perfis:
            p["telas"] = _telas_do_perfil(c, p["id"], bool(p["admin"]))
    return JSONResponse({"perfis": perfis})


def _valida_perfil_payload(payload: dict) -> tuple[str, list[str], str | None]:
    nome = (payload.get("nome") or "").strip()
    telas = payload.get("telas") or []
    if not nome:
        return "", [], "Informe o nome do perfil."
    if not isinstance(telas, list) or any(t not in TELAS for t in telas):
        return "", [], "Lista de telas inválida."
    return nome, telas, None


@router_gestao.post("/perfis")
def perfil_criar(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    nome, telas, erro = _valida_perfil_payload(payload)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    admin = 1 if payload.get("admin") else 0
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO perfis(nome, descricao, admin, criado_em)"
                " VALUES(%s,%s,%s,%s) RETURNING id",
                (nome, (payload.get("descricao") or "").strip(), admin, _agora()))
            pid = cur.fetchone()["id"]
        except psycopg.errors.UniqueViolation:
            return JSONResponse(status_code=422, content={
                "erro": "nome_em_uso", "mensagem": "Já existe perfil com esse nome."})
        _muitos(c, "INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      [(pid, t) for t in telas])
    audit(sess["email"], "perfil_criar", alvo=nome,
          detalhe=f"admin={admin}; telas={','.join(telas) or '-'}", ip=_ip(request))
    return JSONResponse({"ok": True, "id": pid})


@router_gestao.post("/perfis/{perfil_id}")
def perfil_editar(perfil_id: int, payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    nome, telas, erro = _valida_perfil_payload(payload)
    if erro:
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": erro})
    admin = 1 if payload.get("admin") else 0
    with _conn() as c:
        p = c.execute("SELECT * FROM perfis WHERE id=%s", (perfil_id,)).fetchone()
        if not p:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Perfil não existe."})
        if p["admin"] and not admin:
            outros = c.execute(
                """SELECT COUNT(*) AS n FROM usuarios u JOIN perfis p2 ON p2.id=u.perfil_id
                   WHERE p2.admin=1 AND u.ativo=1 AND p2.id<>%s""", (perfil_id,)).fetchone()["n"]
            if outros == 0:
                return JSONResponse(status_code=422, content={
                    "erro": "ultimo_admin",
                    "mensagem": "Este é o único perfil com administradores ativos — "
                                "crie outro admin antes de rebaixá-lo."})
        try:
            c.execute("UPDATE perfis SET nome=%s, descricao=%s, admin=%s WHERE id=%s",
                      (nome, (payload.get("descricao") or "").strip(), admin, perfil_id))
        except psycopg.errors.UniqueViolation:
            return JSONResponse(status_code=422, content={
                "erro": "nome_em_uso", "mensagem": "Já existe perfil com esse nome."})
        c.execute("DELETE FROM perfil_telas WHERE perfil_id=%s", (perfil_id,))
        _muitos(c, "INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                      [(perfil_id, t) for t in telas])
    audit(sess["email"], "perfil_editar", alvo=nome,
          detalhe=f"admin={admin}; telas={','.join(telas) or '-'}", ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.post("/perfis/{perfil_id}/excluir")
def perfil_excluir(perfil_id: int, request: Request) -> JSONResponse:
    sess = request.state.sessao
    with _conn() as c:
        p = c.execute("SELECT * FROM perfis WHERE id=%s", (perfil_id,)).fetchone()
        if not p:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Perfil não existe."})
        em_uso = c.execute("SELECT COUNT(*) AS n FROM usuarios WHERE perfil_id=%s",
                           (perfil_id,)).fetchone()["n"]
        if em_uso:
            return JSONResponse(status_code=422, content={
                "erro": "perfil_em_uso",
                "mensagem": f"Perfil em uso por {em_uso} usuário(s). Reatribua antes de excluir."})
        c.execute("DELETE FROM perfis WHERE id=%s", (perfil_id,))
    audit(sess["email"], "perfil_excluir", alvo=p["nome"], ip=_ip(request))
    return JSONResponse({"ok": True})


@router_gestao.get("/auditoria")
def auditoria(limite: int = 200, busca: str | None = None) -> JSONResponse:
    limite = max(1, min(limite, 1000))
    busca = (busca or "").strip()
    sql = "SELECT * FROM audit_log"
    params: tuple = ()
    if busca:
        sql += " WHERE usuario LIKE %s OR acao LIKE %s OR alvo LIKE %s OR detalhe LIKE %s"
        like = f"%{busca}%"
        params = (like, like, like, like)
    sql += " ORDER BY id DESC LIMIT %s"
    with _conn() as c:
        rows = c.execute(sql, (*params, limite)).fetchall()
    return JSONResponse({"eventos": [dict(r) for r in rows]})


_CONFIG_LIMITES = {  # chave -> (mínimo, máximo)
    "sessao_ttl_min": (5, 1440 * 7),
    "max_tentativas": (3, 20),
    "bloqueio_min": (1, 1440),
    "senha_min": (6, 64),
}


@router_gestao.get("/config")
def config_get() -> JSONResponse:
    return JSONResponse({k: cfg(k) for k in _CONFIG_PADRAO})


@router_gestao.post("/config")
def config_set(payload: dict, request: Request) -> JSONResponse:
    sess = request.state.sessao
    # valida TUDO antes de gravar QUALQUER coisa (evita commit parcial em erro 422)
    novos: dict[str, int] = {}
    for chave, (lo, hi) in _CONFIG_LIMITES.items():
        if chave not in payload:
            continue
        try:
            valor = int(payload[chave])
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": f"{chave} deve ser inteiro."})
        if not (lo <= valor <= hi):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"{chave} deve estar entre {lo} e {hi}."})
        novos[chave] = valor
    if novos:
        with _conn() as c:
            for chave, valor in novos.items():
                c.execute("INSERT INTO config(chave, valor) VALUES(%s,%s) "
                          "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                          (chave, str(valor)))
        audit(sess["email"], "config_seguranca",
              detalhe="; ".join(f"{k}={v}" for k, v in novos.items()), ip=_ip(request))
    return JSONResponse({"ok": True, "config": {k: cfg(k) for k in _CONFIG_PADRAO}})


# NÃO há `init_db()` no import. Enquanto era SQLite, criar o arquivo custava
# nada; com o Postgres, um DDL no import faz a API INTEIRA não subir se o banco
# estiver fora do ar — e sem API não há nem tela de erro para explicar.
# Quem chama é o `startup` do `api/main.py`, com try/except: a API sobe, e a
# falha aparece na Saúde do Servidor, que é onde se olha.
