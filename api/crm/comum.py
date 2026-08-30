"""Vocabulário, tetos e peças compartilhadas do CRM.

O SCHEMA É REDIRECIONADO NUM LUGAR SÓ, aqui — mesma convenção da Gestão. São
seis módulos sobre as mesmas sete tabelas, e seis variáveis `ESQUEMA` seriam
seis chances de um teste redirecionar cinco e gravar a sexta no schema de
produção. Quem procurar `ESQUEMA` em `contas.py` não o encontra: está aqui, e é
daqui que sai o `_esq()` que todos usam.

Os validadores vêm de `api/validacao.py`, que é a implementação única da casa.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import migracoes, pglocal
from ..validacao import (DadoInvalido, data_br, escolha, inteiro, iso,
                         texto, valor_br)
from ..validacao import decimal as decimais
from ..validacao import pessoa as _pessoa
from ..validacao import usuarios_ativos as _usuarios_ativos

ESQUEMA: str | None = None

TITULO_MAX = 200
NOME_MAX = 120
RESUMO_MAX = 4000

# ------------------------------------------------------------------ funil --
# Os estágios NA ORDEM, que é o que a tela usa para desenhar o kanban e o que o
# painel usa para calcular conversão. Tupla e não set: aqui a ordem É a
# informação.
#
# Cinco estágios abertos seria demais e três, de menos. Estes quatro separam as
# perguntas que de fato mudam o que o vendedor faz: ainda estou entendendo o
# problema (qualificação), estou levantando rota e volume para poder cotar
# (levantamento), a proposta está na mesa (proposta), estamos discutindo preço e
# condição (negociação).
ESTAGIOS = ("qualificacao", "levantamento", "proposta", "negociacao")
ESTAGIOS_FECHADOS = ("ganha", "perdida")
ESTAGIOS_TODOS = ESTAGIOS + ESTAGIOS_FECHADOS

ROTULO_ESTAGIO = {
    "qualificacao": "Qualificação", "levantamento": "Levantamento",
    "proposta": "Proposta", "negociacao": "Negociação",
    "ganha": "Ganha", "perdida": "Perdida"}

# Probabilidade PADRÃO do estágio — o palpite da casa quando ninguém opinou.
# O vendedor sobrepõe por oportunidade (coluna `probabilidade`), e é por isso
# que ela existe: previsão ponderada com probabilidade fixa por estágio é
# previsão do PROCESSO, não do negócio. Uma proposta parada há 40 dias e uma
# entregue ontem estão no mesmo estágio e não valem o mesmo.
PROB_PADRAO = {"qualificacao": 10, "levantamento": 25, "proposta": 50,
               "negociacao": 75, "ganha": 100, "perdida": 0}

TIPOS_OPORTUNIDADE = ("spot", "contrato", "renovacao", "expansao", "bid")
ROTULO_TIPO_OPO = {"spot": "Spot", "contrato": "Contrato",
                   "renovacao": "Renovação", "expansao": "Expansão",
                   "bid": "Licitação/BID"}

# Motivos de perda. Lista FECHADA (há CHECK no banco) porque é o único campo do
# CRM cujo valor só existe para ser AGRUPADO: "perdemos por preço em 60% dos
# casos" é acionável, e um campo livre com 40 grafias de "preço alto" não é.
# O detalhe em texto continua existindo ao lado, para o que a lista não cobre.
MOTIVOS_PERDA = ("preco", "prazo", "capacidade", "concorrente",
                 "sem_orcamento", "sem_retorno", "requisito_tecnico",
                 "area_nao_atendida", "nao_qualificado", "outro")
ROTULO_MOTIVO = {
    "preco": "Preço", "prazo": "Prazo de entrega", "capacidade": "Capacidade",
    "concorrente": "Perdeu para concorrente", "sem_orcamento": "Sem orçamento",
    "sem_retorno": "Cliente parou de responder",
    "requisito_tecnico": "Requisito técnico", "area_nao_atendida": "Região não atendida",
    "nao_qualificado": "Não qualificado", "outro": "Outro"}

PAPEIS_CONTATO = ("decisor", "influenciador", "operacional", "financeiro",
                  "comprador")
ROTULO_PAPEL = {"decisor": "Decisor", "influenciador": "Influenciador",
                "operacional": "Operacional", "financeiro": "Financeiro",
                "comprador": "Comprador"}

TIPOS_ATIVIDADE = ("ligacao", "visita", "reuniao", "email", "whatsapp",
                   "proposta", "cotacao", "outro")
ROTULO_ATIVIDADE = {"ligacao": "Ligação", "visita": "Visita",
                    "reuniao": "Reunião", "email": "E-mail",
                    "whatsapp": "WhatsApp", "proposta": "Proposta",
                    "cotacao": "Cotação", "outro": "Outro"}
STATUS_ATIVIDADE = ("aberta", "concluida", "cancelada")

CANAIS = ("ligacao", "visita", "reuniao", "email", "whatsapp", "proposta",
          "outro")
SENTIDOS = ("entrada", "saida")

# MINÚSCULA, como todo domínio da casa: `escolha()` normaliza a entrada para
# minúscula, então 'IPCA' aqui recusaria o 'IPCA' que a tela manda. O rótulo
# bonito é problema do `ROTULO_INDICE`.
INDICES_REAJUSTE = ("ipca", "igpm", "inpc", "diesel", "negociado",
                    "sem_reajuste")
ROTULO_INDICE = {"ipca": "IPCA", "igpm": "IGP-M", "inpc": "INPC",
                 "diesel": "Repasse de diesel", "negociado": "Negociado",
                 "sem_reajuste": "Sem reajuste"}

# Segmentos e origens são SUGESTÃO (campo de texto livre, sem CHECK): engessar
# obrigaria migration para cada segmento novo, e o custo de uma grafia
# divergente aqui é um filtro com duas linhas parecidas, não um número errado.
# É a mesma escolha que a Gestão fez com `AREAS`.
SEGMENTOS = ("Automotivo", "Siderurgia e metalurgia", "Papel e celulose",
             "Química e petroquímica", "Alimentos e bebidas", "Agronegócio",
             "Construção civil", "Bens de consumo", "Eletroeletrônicos",
             "Máquinas e equipamentos", "Embalagens", "Têxtil",
             "Farmacêutico", "Logística e e-commerce", "Outro")

ORIGENS = ("Prospecção ativa", "Indicação", "Cliente antigo", "Inbound (site)",
           "Feira ou evento", "Licitação", "Parceiro", "Outro")

# Classes de carga da ANTT, com os rótulos que a Res. 5.867/2020 usa. É a MESMA
# lista de `api/antt/coeficientes.py` — importada de lá, para que uma classe
# nova na tabela oficial não precise ser lembrada aqui.
from ..antt.coeficientes import TIPOS_CARGA  # noqa: E402

ROTULO_CARGA = {
    "carga_geral": "Carga geral", "granel_solido": "Granel sólido",
    "granel_liquido": "Granel líquido", "frigorificada": "Frigorificada",
    "conteinerizada": "Conteinerizada", "neogranel": "Neogranel",
    "granel_pressurizada": "Granel pressurizada",
    "perigosa_granel_solido": "Perigosa — granel sólido",
    "perigosa_granel_liquido": "Perigosa — granel líquido",
    "perigosa_frigorificada": "Perigosa — frigorificada",
    "perigosa_conteinerizada": "Perigosa — conteinerizada",
    "perigosa_carga_geral": "Perigosa — carga geral"}

# Composições típicas da operação, com os eixos que a ANTT conta. Existe para
# que o vendedor escolha "Carreta LS 3 eixos" e não tenha de saber que a
# composição soma 6 — errar o eixo muda o coeficiente e portanto o piso.
VEICULOS = {
    "Truck": 3, "Bitruck": 4, "Carreta LS (2 eixos)": 5,
    "Carreta LS (3 eixos)": 6, "Vanderleia": 6, "Bitrem": 7,
    "Rodotrem": 9, "Toco": 2, "VUC": 2}


class SemAcesso(RuntimeError):
    """O banco local não está configurado — instalação sem o CRM."""


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hoje() -> date:
    return date.today()


def pessoa(usuario_id, nome, rotulo: str, esquema: str | None = None) -> tuple:
    return _pessoa(usuario_id, nome, rotulo, esquema=_esq(esquema))


def usuarios_ativos(esquema: str | None = None) -> list[dict]:
    return _usuarios_ativos(esquema=_esq(esquema))


def uf(valor, rotulo: str) -> str:
    """UF em duas letras maiúsculas, ou vazio.

    Recusa em vez de aceitar 'santa catarina': a UF entra em rótulo de lane
    ('Joinville/SC → Betim/MG') e em agrupamento por corredor, e uma coluna com
    'SC', 'sc' e 'Santa Catarina' faz o mesmo corredor aparecer três vezes no
    ranking, cada um com um terço do volume.
    """
    s = texto(valor, rotulo, maximo=40).upper()
    if not s:
        return ""
    if len(s) != 2 or not s.isalpha():
        raise DadoInvalido(f"{rotulo[0].upper()}{rotulo[1:]} deve ser a sigla "
                           f"de duas letras (ex.: SC).")
    return s


def telefone(valor, rotulo: str = "telefone") -> str:
    """Telefone de contato, NORMALIZADO pelo validador do WhatsApp.

    Não é formatação: é o que garante que o número cadastrado aqui seja o mesmo
    que o disparo aceita. Duas noções de "telefone válido" na casa dariam
    número que o cadastro aceita e o envio recusa — descoberto na hora em que a
    mensagem não chega, que é tarde.

    Vazio é permitido: contato sem telefone é normal (só e-mail), e exigir o
    campo faria alguém digitar zeros para conseguir salvar.
    """
    from ..whatsapp import numeros
    s = texto(valor, rotulo, maximo=40)
    if not s:
        return ""
    try:
        return numeros.normalizar(s)
    except numeros.TelefoneInvalido as exc:
        raise DadoInvalido(f"{rotulo[0].upper()}{rotulo[1:]}: {exc}") from None


def telefone_fmt(numero: str) -> str:
    if not numero:
        return ""
    from ..whatsapp import numeros
    return numeros.formatar(numero)


def email(valor, rotulo: str = "e-mail") -> str:
    """Confere a forma mínima e nada além.

    Validação de e-mail por regex elaborada recusa endereço válido (o RFC é
    mais permissivo do que se imagina) e não impede o erro que acontece de
    verdade, que é digitar o domínio errado. Quem diz se o endereço existe é o
    envio — e o correio da casa já reporta a falha.
    """
    s = texto(valor, rotulo, maximo=200)
    if not s:
        return ""
    if s.count("@") != 1 or " " in s or "." not in s.split("@")[1]:
        raise DadoInvalido(f"{rotulo[0].upper()}{rotulo[1:]} não parece um "
                           f"endereço válido.")
    return s.lower()


def cnpj(valor, rotulo: str = "CNPJ") -> str:
    """Só os dígitos, com os dois tamanhos aceitos (CNPJ e CPF).

    NÃO confere dígito verificador de propósito: o CRM cadastra prospect a
    partir do que o vendedor conseguiu, e recusar um CNPJ que ele leu do site
    do cliente com um dígito trocado o impediria de registrar a oportunidade —
    que é pior do que guardar um documento a conferir. Quem valida de verdade
    é o cadastro fiscal, na hora de faturar.
    """
    s = "".join(c for c in str(valor or "") if c.isdigit())
    if not s:
        return ""
    if len(s) not in (11, 14):
        raise DadoInvalido(f"{rotulo} deve ter 11 dígitos (CPF) ou 14 (CNPJ) "
                           f"— vieram {len(s)}.")
    return s


def cnpj_fmt(doc: str) -> str:
    d = "".join(c for c in str(doc or "") if c.isdigit())
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


def proximo_codigo(tabela: str, prefixo: str, ano: int | None = None,
                   esquema: str | None = None) -> tuple[int, int, str]:
    """`(ano, sequência, codigo)` para a referência humana — OPO-2026-014.

    Existe pela mesma razão do `codigo` de `ges_reunioes`: é assim que uma
    oportunidade é citada em e-mail e em reunião, e "a #43" não sobrevive a uma
    restauração de backup que reordene ids.

    A corrida é possível e o banco a recusa (UNIQUE em (ano, sequencia)) — num
    volume de dezenas de oportunidades por mês ela é improvável, e recusar é
    muito melhor que gravar duas OPO-2026-014. Quem chama trata o erro do banco
    como "tente de novo", não como falha.
    """
    a = ano or hoje().year
    r = pglocal.um(
        f"SELECT coalesce(max(sequencia), 0) AS s FROM {tabela} WHERE ano=%s",
        (a,), esquema=_esq(esquema))
    seq = int((r or {}).get("s") or 0) + 1
    return a, seq, f"{prefixo}-{a}-{seq:03d}"


def dias_desde(carimbo: str | None) -> int | None:
    """Dias entre um carimbo ISO gravado e hoje. None quando nunca houve.

    None e 0 são coisas MUITO diferentes aqui: 0 é "falaram hoje", None é
    "nunca falaram", e a tela mostra os dois de forma diferente — um número
    grande em cinza e a palavra "nunca" em âmbar.
    """
    if not carimbo:
        return None
    try:
        d = datetime.fromisoformat(str(carimbo)).date()
    except ValueError:
        return None
    return (hoje() - d).days


__all__ = [
    "CANAIS", "DadoInvalido", "ESQUEMA", "ESTAGIOS", "ESTAGIOS_FECHADOS",
    "ESTAGIOS_TODOS", "INDICES_REAJUSTE", "MOTIVOS_PERDA", "NOME_MAX",
    "ORIGENS", "PAPEIS_CONTATO", "PROB_PADRAO", "RESUMO_MAX", "ROTULO_ATIVIDADE",
    "ROTULO_CARGA", "ROTULO_ESTAGIO", "ROTULO_INDICE", "ROTULO_MOTIVO",
    "ROTULO_PAPEL", "ROTULO_TIPO_OPO", "SEGMENTOS", "SENTIDOS", "SemAcesso",
    "STATUS_ATIVIDADE", "TIPOS_ATIVIDADE", "TIPOS_CARGA", "TIPOS_OPORTUNIDADE",
    "TITULO_MAX", "VEICULOS", "_esq", "agora", "cnpj", "cnpj_fmt", "data_br",
    "decimais", "dias_desde", "email", "escolha", "hoje", "init_db", "inteiro",
    "iso", "pessoa", "proximo_codigo", "telefone", "telefone_fmt", "texto",
    "uf", "usuarios_ativos", "valor_br",
]
