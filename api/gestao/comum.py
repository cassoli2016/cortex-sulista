"""Peças compartilhadas por `atas` e `acoes` — e só as compartilhadas.

Os VALIDADORES saíram daqui em 30/08/2026, quando o CRM passou a precisar dos
mesmos: hoje moram em `api/validacao.py` e são reexportados abaixo com os mesmos
nomes, então quem importava de `gestao.comum` não precisa saber que mudaram de
casa. O que sobrou aqui é o que é MESMO da Gestão — os status de ação e de ata,
os rótulos e a lista de áreas.

O que continua valendo: o par (`usuario_id`, `nome`) tem UMA resposta na casa.
Ele aparece em participante de reunião, em responsável de ação e agora em dono
de conta do CRM, e as três regras têm de ser a mesma: id quando a pessoa tem
login, nome quando não tem, nunca nenhum dos dois. Duas implementações
divergiriam no dia em que uma delas aceitasse o registro sem dono — que é
justamente o registro que ninguém cobra.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import migracoes
from ..validacao import (NOME_MAX, TEXTO_MAX, DadoInvalido, data_br, escolha,
                         inteiro, iso, texto, valor_br)
from ..validacao import pessoa as _pessoa
from ..validacao import usuarios_ativos as _usuarios_ativos

__all__ = ["AREAS", "DadoInvalido", "ESQUEMA", "NOME_MAX", "PRIORIDADES",
           "ROTULO_PRIORIDADE", "ROTULO_STATUS", "ROTULO_TIPO", "STATUS_ACAO",
           "STATUS_ATA", "TEXTO_MAX", "TIPOS_REUNIAO", "TITULO_MAX", "agora",
           "data_br", "escolha", "hoje", "init_db", "inteiro", "iso", "pessoa",
           "texto", "usuarios_ativos", "valor_br"]

ESQUEMA: str | None = None

# Tetos de texto. Não são preciosismo: `o_que` vai para o assunto do e-mail de
# cobrança e para a coluna da tabela, e um parágrafo colado ali quebra os dois.
# Quem tem mais a dizer usa `como` e os andamentos, que são campos longos.
TITULO_MAX = 200

STATUS_ACAO = ("aberta", "em_andamento", "concluida", "cancelada")
PRIORIDADES = ("baixa", "media", "alta", "critica")
STATUS_ATA = ("rascunho", "publicada")
TIPOS_REUNIAO = ("diretoria", "area", "projeto", "comite", "cliente", "outra")

# Rótulos em português para tela, e-mail e auditoria — num lugar só, senão a
# tela diz "em_andamento" em algum canto que ninguém revisou.
ROTULO_STATUS = {"aberta": "Aberta", "em_andamento": "Em andamento",
                 "concluida": "Concluída", "cancelada": "Cancelada"}
ROTULO_PRIORIDADE = {"baixa": "Baixa", "media": "Média",
                     "alta": "Alta", "critica": "Crítica"}
ROTULO_TIPO = {"diretoria": "Diretoria", "area": "Área", "projeto": "Projeto",
               "comite": "Comitê", "cliente": "Cliente", "outra": "Outra"}

# Áreas sugeridas no formulário. Lista ABERTA de propósito (o campo é texto
# livre): engessar em CHECK obrigaria migration para cada área nova, e o custo
# de uma grafia divergente aqui é um filtro com duas linhas parecidas, não um
# número errado.
AREAS = ("Financeiro", "Comercial", "Operação", "Frota", "Controladoria",
         "Suprimentos", "Recursos Humanos", "Tecnologia", "Diretoria",
         "Qualidade", "Jurídico")


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hoje() -> date:
    return date.today()


def pessoa(usuario_id, nome, rotulo: str, esquema: str | None = None) -> tuple:
    """`validacao.pessoa` com o redirecionamento de schema da Gestão."""
    return _pessoa(usuario_id, nome, rotulo, esquema=_esq(esquema))


def usuarios_ativos(esquema: str | None = None) -> list[dict]:
    """`validacao.usuarios_ativos` com o redirecionamento de schema da Gestão."""
    return _usuarios_ativos(esquema=_esq(esquema))
