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

from api import segredo_arquivo

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

    # TomTom — trânsito. SÃO DOIS CAMPOS, e a razão é uma armadilha real:
    #
    # A chave do OVERLAY vai para o NAVEGADOR (o Leaflet baixa os tiles direto,
    # e proxiar tile é caro), então a defesa recomendada pela própria TomTom é
    # restringi-la por domínio/referrer no painel deles. Só que uma chave
    # restrita por domínio **não funciona chamada pelo servidor** — a coleta
    # voltaria 403, e um 403 lê-se como "chave errada", mandando conferir o que
    # está certo.
    #
    # Por isso a chave do SERVIDOR é campo próprio e OPCIONAL: sem ela a coleta
    # cai na do overlay e a Saúde AVISA que, se aquela estiver restrita por
    # domínio, a coleta vai falhar — em vez de deixar a pessoa descobrir pelo
    # 403.
    "TOMTOM_API_KEY": {
        "rotulo": "Chave do mapa (navegador)",
        "descricao": "Usada no overlay de trânsito dos painéis. Vai para o "
                     "navegador — restrinja por domínio no painel da TomTom"},
    "TOMTOM_API_KEY_SERVIDOR": {
        "rotulo": "Chave da coleta (servidor)", "obrigatorio": False,
        "descricao": "Chave SEM restrição de domínio, para o CÓRTEX consultar "
                     "trânsito e ETA. Sem ela a coleta usa a do mapa, que "
                     "falha se estiver restrita"},

    # QualP — praças de pedágio, tarifa vigente e piso ANTT.
    #
    # NÃO É CHAVE DE API: a autenticação é usuário e senha, trocados por um par
    # `login_cod` + `login_token` em `/api/site/login/authenticate`. Lido do
    # cliente do próprio site, não da documentação — que não descreve o formato.
    #
    # E é OPCIONAL de propósito: o endpoint funciona sem conta nenhuma, com
    # teto de **três consultas por dia, por IP** (a quarta volta HTTP 402, em
    # português). Marcar como obrigatório faria a Saúde acusar falha numa
    # integração que está funcionando no regime gratuito — o mesmo erro do
    # alarme que acende sem haver problema.
    "QUALP_USUARIO": {
        "rotulo": "Usuário", "obrigatorio": False, "segredo": False,
        "descricao": "Usuário da conta QualP. Sem conta, a consulta funciona "
                     "no modo aberto: três por dia, por IP"},
    "QUALP_SENHA": {
        "rotulo": "Senha", "obrigatorio": False,
        "descricao": "Senha da conta QualP. Com ela o teto de três consultas "
                     "diárias deixa de valer"},

    "SMTP_SENHA": {
        "rotulo": "Senha do servidor",
        "descricao": "Senha do servidor de e-mail (envio pelo CÓRTEX)"},

    # Z-API — envio de WhatsApp. Os TRÊS campos são segredo, inclusive o id da
    # instância: na Z-API a credencial é a própria URL
    # (/instances/{id}/token/{token}), então o id é metade da chave — e não a
    # parte pública que "id" sugere. Mascarado (`3d2f…a91b`) ainda dá para
    # conferir qual instância está configurada, que é o motivo de o resto do
    # catálogo abrir campo de configuração.
    "ZAPI_INSTANCIA": {
        "rotulo": "ID da instância",
        "descricao": "O {id} de /instances/{id}/token/… no painel Z-API"},
    "ZAPI_TOKEN": {
        "rotulo": "Token da instância",
        "descricao": "Token daquela instância — junto com o id, forma o endereço"},
    "ZAPI_CLIENT_TOKEN": {
        "rotulo": "Token de segurança da conta", "obrigatorio": False,
        "descricao": "Aba Segurança do painel Z-API. Só é obrigatório se a "
                     "validação por token estiver ATIVADA lá — e aí sem ele "
                     "toda chamada volta 'null not allowed'"},

    # SEGUNDA INSTÂNCIA (número reserva). É outro aparelho, outro número e —
    # o que mais importa — OUTRA REPUTAÇÃO no WhatsApp: o limite diário de
    # destinatários distintos é contado separadamente para cada uma, porque
    # banir um número não tem relação com o que o outro fez. Opcional: quem
    # não tiver reserva deixa os três em branco e nada muda.
    "ZAPI2_INSTANCIA": {
        "rotulo": "ID da instância (reserva)", "obrigatorio": False,
        "descricao": "O {id} da SEGUNDA instância, se houver número reserva"},
    "ZAPI2_TOKEN": {
        "rotulo": "Token da instância (reserva)", "obrigatorio": False,
        "descricao": "Token da segunda instância — com o id, forma o endereço"},
    "ZAPI2_CLIENT_TOKEN": {
        "rotulo": "Token de segurança da conta (reserva)", "obrigatorio": False,
        "descricao": "Só se a validação por token estiver ativada na conta da "
                     "segunda instância"},

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

    # Endereço público do painel. Existe para UMA coisa: o e-mail de
    # boas-vindas precisa dizer ONDE entrar, e um e-mail de acesso sem
    # endereço é papel picado. Fica em configuração e não em constante porque
    # o host muda com o túnel, e um endereço errado num e-mail de acesso manda
    # gente nova para lugar nenhum no primeiro contato com o sistema.
    "CORTEX_URL": {
        "rotulo": "Endereço do painel", "segredo": False,
        "descricao": "URL pública do CÓRTEX, usada no e-mail de boas-vindas",
        "placeholder": "https://cortex.exemplo.com.br"},

    # RasterJOR — jornada do motorista. A URL NÃO TEM PADRÃO de propósito:
    # adivinhar host de fornecedor no melhor caso dá 404 e no pior acerta o
    # endpoint de outra empresa. Sem ela a coleta recusa dizendo o que falta.
    "SMARTEC_TOKEN": {
        "rotulo": "Token de API",
        "descricao": "Vai no CORPO de cada requisição, não em cabeçalho. "
                     "Pode ser o mesmo token que o ERP usa para importar "
                     "infração — se for, revogá-lo derruba as duas coisas"},
    "RASTERJOR_API_BASE_URL": {
        "rotulo": "URL base da API", "segredo": False,
        "descricao": "Endereço da API da RasterJOR, sem barra no fim",
        "placeholder": "https://www.rasterjor.com.br"},
    "RASTERJOR_TOKEN": {
        "rotulo": "Token de API",
        "descricao": "Vai no cabeçalho Authorization como Bearer"},
    "RASTERJOR_USUARIO": {
        "rotulo": "Usuário", "segredo": False, "obrigatorio": False,
        "descricao": "Só se a conta usar Basic em vez de token"},
    "RASTERJOR_SENHA": {
        "rotulo": "Senha", "obrigatorio": False,
        "descricao": "Só se a conta usar Basic em vez de token"},
    "RASTERJOR_AUTH_HEADER": {
        "rotulo": "Cabeçalho do token", "segredo": False, "obrigatorio": False,
        "descricao": "Padrão Authorization — trocar só se a RasterJOR mudar",
        "placeholder": "Authorization"},
    "RASTERJOR_AUTH_PREFIXO": {
        "rotulo": "Prefixo do token", "segredo": False, "obrigatorio": False,
        "descricao": "Padrão Bearer; vazio se o token vai cru no cabeçalho",
        "placeholder": "Bearer"},
    "RASTERJOR_PATH_JORNADAS": {
        "rotulo": "Caminho da jornada", "segredo": False, "obrigatorio": False,
        "descricao": "Padrão /external-api/productivity-report",
        "placeholder": "/external-api/productivity-report"},
    "RASTERJOR_PATH_INCONFORMIDADES": {
        "rotulo": "Caminho das inconformidades", "segredo": False,
        "obrigatorio": False, "descricao": "Padrão /external-api/unconformities/",
        "placeholder": "/external-api/unconformities/"},
    "RASTERJOR_PATH_MOTORISTAS": {
        "rotulo": "Caminho dos motoristas", "segredo": False,
        "obrigatorio": False, "descricao": "Padrão /external-api/drivers/",
        "placeholder": "/external-api/drivers/"},
    "RASTERJOR_PATH_AUSENCIAS": {
        "rotulo": "Caminho das ausências", "segredo": False,
        "obrigatorio": False, "descricao": "Padrão /external-api/absences/",
        "placeholder": "/external-api/absences/"},

    # RasterIntegra — o webservice de GERENCIAMENTO DE RISCO da Raster/Logae
    # (NÃO confundir com a RasterJOR acima: mesmo fornecedor, outro serviço,
    # outra autenticação). Login+senha vão no CORPO de cada requisição
    # DataSnap. Credencial EXCLUSIVA do CÓRTEX: a que o ERP usa foi
    # encontrada exposta no próprio banco e o mesmo login em dois
    # consumidores dobra o consumo do rate-limit (30s/15s) que o ERP já fura.
    "RASTERINTEGRA_URL": {
        "rotulo": "URL base do webservice", "segredo": False,
        "obrigatorio": False,
        "descricao": "Padrão https://integra.logaegr.com.br:8443 (TLS); o "
                     "ERP usa o alias integra.rastergr.com.br:8888 — mesmo "
                     "serviço. Sem barra no fim",
        "placeholder": "https://integra.logaegr.com.br:8443"},
    "RASTERINTEGRA_LOGIN": {
        "rotulo": "Login", "segredo": False,
        "descricao": "Vai no CORPO de cada requisição (padrão DataSnap da "
                     "Raster). Peça credencial exclusiva do CÓRTEX — nunca "
                     "reusar a do ERP"},
    "RASTERINTEGRA_SENHA": {
        "rotulo": "Senha",
        "descricao": "Vai no CORPO junto do login. Guardada no cofre, "
                     "protegida por ACL, nunca em log"},

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
    # NÃO É INTEGRAÇÃO — é ajuste do próprio CÓRTEX, e está aqui porque é
    # aqui que a tela de configuração lê. Campo que não entra em serviço
    # nenhum fica invisível e ninguém descobre por que o e-mail não sai.
    {
        "chave": "cortex",
        "nome": "CÓRTEX",
        "resumo": "Endereço público do painel. Ele entra nos e-mails que o "
                  "sistema envia — sem ele, o e-mail de boas-vindas não tem "
                  "como dizer onde entrar.",
        "alimenta": "E-mail de boas-vindas",
        "modos": [{"chave": "url", "rotulo": "Endereço do painel",
                   "dica": "a mesma URL que você usa no navegador",
                   "campos": ["CORTEX_URL"]}],
        "ajustes": [],
    },
    {
        "chave": "tomtom",
        "nome": "TomTom",
        "resumo": "Trânsito em tempo real: velocidade atual contra a de fluxo "
                  "livre no trecho onde cada caminhão está, incidentes na "
                  "rota (obra, acidente, bloqueio) e tempo estimado até o "
                  "destino já com o trânsito do momento.",
        "alimenta": "Torre de Controle · Painéis de TV",
        "modos": [{"chave": "chave", "rotulo": "Chave de API",
                   "dica": "a mesma do painel developer.tomtom.com",
                   "campos": ["TOMTOM_API_KEY"]}],
        "ajustes": ["TOMTOM_API_KEY_SERVIDOR"],
    },
    {
        "chave": "qualp",
        "nome": "QualP",
        "resumo": "Praças de pedágio de uma rota com a TARIFA VIGENTE por eixo "
                  "— inclusive retroativa, para conferir uma viagem antiga "
                  "contra o preço que valia no dia dela. Traz também as "
                  "balanças do trajeto e a tabela de piso da ANTT, com a "
                  "resolução em vigor.",
        "alimenta": "Validação de Pedágio",
        # O ÚNICO FORNECEDOR QUE FUNCIONA SEM CREDENCIAL. Sem conta, a consulta
        # responde no modo aberto — três por dia, por IP. Por isso o modo é
        # OPCIONAL: marcar a integração como "desligada" quando ela está
        # respondendo seria mentir sobre o estado, e acender vermelho onde não
        # há problema ensina a ignorar o vermelho.
        "modos": [{"chave": "conta", "rotulo": "Usuário e senha",
                   "dica": "a mesma conta de qualp.com.br. Sem ela a consulta "
                           "funciona, com teto de três por dia",
                   "campos": ["QUALP_USUARIO", "QUALP_SENHA"]}],
        "ajustes": [],
        # MEDIDO: a conta do site NÃO levanta o teto. O login funciona e a
        # quarta consulta do dia continua recusada — quem levanta é chave da
        # API comercial (api.qualp.com.br), produto separado. Dizer o
        # contrário no cartão convidaria a planejar em cima de um limite que
        # não existe.
        "regime": lambda: ("conta configurada — mas o teto de três consultas "
                           "por dia CONTINUA: ele é do endpoint do site, não "
                           "da conta"
                           if (ler("QUALP_USUARIO") and ler("QUALP_SENHA"))
                           else "sem conta: três consultas por dia, por IP"),
    },
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
        "chave": "smartec",
        "nome": "Smartec",
        "resumo": "Infrações de trânsito (multas e notificações com valor, "
                  "boleto e pontuação), autuações da ANTT, vencimento de "
                  "licenças e do acesso ao SNE. O ERP já importa a infração "
                  "por outro caminho, mas sem valor, sem boleto e sem baixa.",
        "alimenta": "Smartec · Multas",
        "modos": [{"chave": "token", "rotulo": "Token de API",
                   "dica": "gerado no painel da Smartec, em /api/Token",
                   "campos": ["SMARTEC_TOKEN"]}],
        "ajustes": [],
    },
    {
        "chave": "rasterjor",
        "nome": "RasterJOR",
        "resumo": "Jornada do motorista — jornada apurada, inconformidades "
                  "nomeadas, hora extra e repouso faltante. A coleta grava no "
                  "banco local do CÓRTEX e toda passagem fica em jor_carga, "
                  "para uma parada virar alerta no dia em que acontece.",
        "alimenta": "Jornada RasterJOR",
        "modos": [
            {"chave": "token", "rotulo": "Token de API",
             "campos": ["RASTERJOR_API_BASE_URL", "RASTERJOR_TOKEN"]},
            {"chave": "basic", "rotulo": "Usuário e senha",
             "campos": ["RASTERJOR_API_BASE_URL", "RASTERJOR_USUARIO",
                        "RASTERJOR_SENHA"]},
        ],
        "ajustes": ["RASTERJOR_AUTH_HEADER", "RASTERJOR_AUTH_PREFIXO",
                    "RASTERJOR_PATH_JORNADAS", "RASTERJOR_PATH_INCONFORMIDADES",
                    "RASTERJOR_PATH_MOTORISTAS", "RASTERJOR_PATH_AUSENCIAS"],
    },
    {
        "chave": "rasterintegra",
        "nome": "RasterIntegra (Gerenciamento de Risco)",
        "resumo": "O webservice de GR da Raster/Logae — consolidado de risco "
                  "por viagem (pânico, desvio de rota, violação de painel e "
                  "antena), km visto pela GR e, no futuro, emissão de SM. "
                  "Outro serviço da mesma Raster da jornada: a credencial "
                  "NÃO é a mesma, e deve ser exclusiva do CÓRTEX.",
        "alimenta": "Gerenciamento de Risco",
        "modos": [
            {"chave": "senha", "rotulo": "Login e senha",
             "campos": ["RASTERINTEGRA_LOGIN", "RASTERINTEGRA_SENHA"]},
        ],
        "ajustes": ["RASTERINTEGRA_URL"],
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
    {
        # Editada na aba WhatsApp, que tem o interruptor, os limites de envio
        # e a trilha. Aqui aparece no panorama pelo mesmo motivo do SMTP:
        # quem abre "Integrações" para conferir o que está ligado tem de ver
        # todas, e não descobrir que uma mora em outra aba.
        "chave": "zapi",
        "nome": "Z-API (WhatsApp)",
        "resumo": "Envio de mensagens de WhatsApp. NÃO é a API oficial: "
                  "conecta um número real da empresa, que pode ser banido por "
                  "disparo em volume — por isso o envio tem limite diário.",
        "alimenta": "WhatsApp",
        "modos": [{"chave": "instancia", "rotulo": "Instância e token",
                   "dica": "os dois compõem a URL da Z-API",
                   "campos": ["ZAPI_INSTANCIA", "ZAPI_TOKEN"]}],
        "ajustes": ["ZAPI_CLIENT_TOKEN", "ZAPI2_INSTANCIA", "ZAPI2_TOKEN",
                    "ZAPI2_CLIENT_TOKEN"],
        "aba": "whatsapp",
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
            # O REGIME, para o fornecedor que FUNCIONA SEM CREDENCIAL.
            #
            # O QualP responde sem conta nenhuma, com teto de três consultas
            # por dia. Sem esta linha o cartão diria "ativa" nos dois casos e
            # esconderia a única diferença que importa — e "desligada" seria
            # pior ainda, porque ele não está desligado, está limitado.
            "regime": svc.get("regime", lambda: None)(),
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
    # `chmod` sozinho NÃO protege no Windows (só liga o somente-leitura;
    # quem decide acesso é a ACL). `proteger` faz o certo em cada
    # plataforma e, na dúvida sobre quem manter, NÃO mexe — ACL escrita
    # pela metade tranca o SYSTEM e derruba a API.
    segredo_arquivo.proteger(CAMINHO)
    return status(nome)
