"""Modelos (templates) de mensagem de WhatsApp — o texto escrito uma vez.

O PROBLEMA QUE ISTO RESOLVE não é economizar digitação. É que a mensagem sai
com o número da empresa, para um cliente, e cada pessoa que a reescreve de
cabeça inventa um tom, esquece o nome da transportadora ou manda um "vc pode
pagar hj?" que é exatamente o tipo de texto que o destinatário denuncia — e
denúncia é o que derruba o número. O modelo é escrito, revisado, e reusado.

TRÊS DECISÕES QUE PARECEM DETALHE E NÃO SÃO:

1. **O CONTEXTO decide quais variáveis existem, e é validado na gravação.**
   Um modelo escrito para a régua de cobrança conhece `{{titulo}}` e
   `{{vencimento}}`; a torre de controle não teria com que preencher esses
   campos. Sem essa amarra, o mesmo texto disparado da tela errada chegaria ao
   cliente com buracos — "Prezado , seu título vence em ." — e o defeito só
   apareceria no celular de outra pessoa. Por isso o catálogo `CONTEXTOS` mora
   aqui, ao lado da validação, e não numa tabela: em linha de banco ele viraria
   dado editável, e a validação passaria a depender do que ninguém revisa.

2. **Variável que não veio NÃO vira string vazia.** `renderizar()` levanta
   `VariavelFaltando`. A alternativa silenciosa manda mensagem quebrada para
   cliente real, e o sistema reporta sucesso — pior que não enviar.

3. **A substituição é por expressão regular, NUNCA por `str.format()` ou
   f-string.** `"{0.__class__.__mro__}".format(obj)` alcança atributo de
   objeto: aplicar `format` a texto que um usuário escreveu é dar a ele um
   pedaço do interpretador. O `_VAR` abaixo só reconhece `{{nome_simples}}`, e
   qualquer outra chave fica como está.

O CATÁLOGO É UM CONTRATO, e `consumidores` diz a verdade sobre ele: contexto
sem tela que o dispare ainda é um texto pronto esperando quem o use — a tela
mostra isso em vez de sugerir que já está em operação. Quem for ligar a tela
preenche EXATAMENTE as chaves declaradas aqui.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from .. import migracoes, pglocal

# Manopla de redirecionamento (mesmo padrão dos outros stores).
ESQUEMA: str | None = None

# WhatsApp corta mensagem de texto em 4.096 caracteres. O corpo tem teto MENOR
# porque ele ainda cresce duas vezes antes de sair: as variáveis viram valores
# (`{{cliente}}` tem 13 caracteres, "TUPY FUNDIÇÕES DO BRASIL LTDA" tem 29) e a
# assinatura é acrescentada no envio. Validar só o corpo deixaria passar o
# modelo que estoura depois de preenchido — daí `renderizar()` conferir o
# tamanho FINAL também.
CORPO_MAX = 3000
TEXTO_MAX = 4096
NOME_MAX = 60
DESCRICAO_MAX = 200
CHAVE_MAX = 40

# `{{nome}}` com espaço opcional. Só letra minúscula, dígito e sublinhado: o
# nome da variável é identificador, não texto livre — assim a mensagem de erro
# pode dizer "variável desconhecida" em vez de tentar adivinhar intenção.
_VAR = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
# Sobra de chave dupla que NÃO casou com o formato acima ({{ Cliente }},
# {{2via}}, {{ }}). É erro de digitação de quem escreveu o modelo, e precisa
# aparecer na hora — senão sai literal na mensagem do cliente.
_VAR_SOLTA = re.compile(r"\{\{.*?\}\}", re.S)


class ModeloInvalido(ValueError):
    """A mensagem desta exceção vai direto para a tela de quem edita."""


class VariavelFaltando(ValueError):
    """Faltou valor para uma variável do corpo. NUNCA é preenchida com vazio."""


def _v(chave: str, rotulo: str, exemplo: str) -> dict:
    return {"chave": chave, "rotulo": rotulo, "exemplo": exemplo}


# Contexto -> de onde o modelo é disparado. `consumidores` são as telas que já
# mandam mensagem com este contexto HOJE; lista vazia é dito na tela, não
# escondido.
CONTEXTOS: dict[str, dict] = {
    "livre": {
        "rotulo": "Livre (sem variáveis)",
        "ajuda": "Mensagem avulsa, escrita inteira. É a que o formulário de "
                 "Gestão › WhatsApp usa.",
        "consumidores": ["Gestão › WhatsApp"],
        "variaveis": [],
    },
    "cobranca": {
        "rotulo": "Cobrança",
        "ajuda": "Aviso de título a vencer ou vencido. Assunto financeiro é o "
                 "que a Z-API aponta como de maior risco de denúncia — vale "
                 "escrever com o nome da empresa e sem urgência artificial.",
        "consumidores": [],
        "variaveis": [
            _v("cliente", "Nome do cliente", "TUPY FUNDIÇÕES"),
            _v("documento", "Número do documento/fatura", "123456"),
            _v("emissao", "Data de emissão", "01/08/2026"),
            _v("vencimento", "Data de vencimento", "15/08/2026"),
            _v("dias_atraso", "Dias em atraso", "13"),
            _v("valor", "Valor do título", "R$ 12.480,00"),
            _v("total_vencido", "Total vencido do cliente", "R$ 48.230,00"),
            _v("filial", "Filial que emitiu", "FIL MTZ"),
        ],
    },
    "viagem": {
        "rotulo": "Viagem / Torre de Controle",
        "ajuda": "Posição, previsão de chegada e ocorrência de uma viagem.",
        "consumidores": [],
        "variaveis": [
            _v("cliente", "Cliente da carga", "VOLVO"),
            _v("numero", "Número da viagem", "88213"),
            _v("placa", "Placa do veículo", "ABC1D23"),
            _v("motorista", "Motorista", "João da Silva"),
            _v("origem", "Origem", "Joinville/SC"),
            _v("destino", "Destino", "Curitiba/PR"),
            _v("previsao", "Previsão de chegada", "28/08/2026 14:30"),
            _v("situacao", "Situação da viagem", "Em trânsito"),
        ],
    },
    "sac": {
        "rotulo": "SAC / Freetime",
        "ajuda": "Retorno de ocorrência e aviso de prazo de freetime.",
        "consumidores": [],
        "variaveis": [
            _v("cliente", "Cliente", "FORVIA"),
            _v("protocolo", "Protocolo do atendimento", "SAC-2026-0412"),
            _v("placa", "Placa do veículo", "ABC1D23"),
            _v("ocorrencia", "Ocorrência", "Aguardando descarga"),
            _v("abertura", "Abertura", "27/08/2026 09:10"),
            _v("prazo", "Prazo / fim do freetime", "29/08/2026 18:00"),
        ],
    },
    "frota": {
        "rotulo": "Frota / Manutenção",
        "ajuda": "Aviso de manutenção preventiva ou documento vencendo. "
                 "Destinatário costuma ser interno (motorista, agregado).",
        "consumidores": [],
        "variaveis": [
            _v("placa", "Placa", "ABC1D23"),
            _v("veiculo", "Veículo", "VOLVO FH 460"),
            _v("motorista", "Motorista", "João da Silva"),
            _v("servico", "Serviço previsto", "Troca de óleo"),
            _v("previsto", "Data prevista", "05/09/2026"),
            _v("odometro", "Odômetro atual", "531.970 km"),
            _v("faltam", "Quanto falta", "1.240 km"),
        ],
    },
}

CONTEXTO_PADRAO = "livre"


def contextos() -> list[dict]:
    """O catálogo, pronto para a tela. `consumidores` vazio é informação."""
    return [{"chave": k, **v} for k, v in CONTEXTOS.items()]


def variaveis_do_contexto(contexto: str) -> set[str]:
    ctx = CONTEXTOS.get(contexto or CONTEXTO_PADRAO)
    return {v["chave"] for v in (ctx or {}).get("variaveis", [])}


def exemplos_do_contexto(contexto: str) -> dict[str, str]:
    ctx = CONTEXTOS.get(contexto or CONTEXTO_PADRAO) or {}
    return {v["chave"]: v["exemplo"] for v in ctx.get("variaveis", [])}


# ------------------------------------------------------------------ chave

def slugificar(texto: str) -> str:
    """`Cobrança — 1º aviso` -> `cobranca-1-aviso`."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode(
        "ascii", "ignore").decode()
    limpo = re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()
    return limpo[:CHAVE_MAX].strip("-")


# ------------------------------------------------------------- renderização

def variaveis_usadas(corpo: str) -> list[str]:
    """Na ordem em que aparecem, sem repetir — é a ordem em que a tela pede os
    valores, e pedir fora da ordem do texto confunde quem preenche."""
    vistas, fora = set(), []
    for nome in _VAR.findall(corpo or ""):
        if nome not in vistas:
            vistas.add(nome)
            fora.append(nome)
    return fora


def _chaves_malformadas(corpo: str) -> list[str]:
    return [t for t in _VAR_SOLTA.findall(corpo or "") if not _VAR.fullmatch(t)]


def renderizar(corpo: str, valores: dict | None = None, *,
               estrito: bool = True) -> str:
    """Troca `{{var}}` pelos valores. Levanta `VariavelFaltando` se faltar.

    `estrito=False` só serve para a PRÉVIA da tela, onde a variável sem valor
    aparece como `[nome]` para o autor enxergar o buraco. Envio é sempre
    estrito: mensagem com lacuna vai para um cliente de verdade.
    """
    valores = {k: ("" if v is None else str(v)) for k, v in (valores or {}).items()}
    faltando: list[str] = []

    def troca(m: re.Match) -> str:
        nome = m.group(1)
        valor = valores.get(nome, "").strip()
        if not valor:
            if estrito:
                faltando.append(nome)
                return m.group(0)
            return f"[{nome}]"
        return valor

    texto = _VAR.sub(troca, corpo or "")
    if faltando:
        raise VariavelFaltando(
            "Falta preencher: " + ", ".join(dict.fromkeys(faltando)) + ".")
    if estrito and len(texto) > TEXTO_MAX:
        raise VariavelFaltando(
            f"A mensagem ficou com {len(texto)} caracteres depois de "
            f"preenchida — o WhatsApp corta em {TEXTO_MAX}.")
    return texto


def previa(corpo: str, contexto: str) -> str:
    """Como a mensagem fica com os exemplos do catálogo. Nunca levanta: é o que
    o autor vê enquanto digita, e erro de digitação no meio da frase não pode
    apagar a prévia inteira."""
    return renderizar(corpo, exemplos_do_contexto(contexto), estrito=False)


# ------------------------------------------------------------------ validação

def validar(dados: dict) -> dict:
    """Normaliza e valida o modelo. Levanta `ModeloInvalido` com o motivo."""
    nome = " ".join(str(dados.get("nome") or "").split())
    if not nome:
        raise ModeloInvalido("Dê um nome ao modelo.")
    if len(nome) > NOME_MAX:
        raise ModeloInvalido(f"O nome passa de {NOME_MAX} caracteres.")

    contexto = str(dados.get("contexto") or CONTEXTO_PADRAO).strip()
    if contexto not in CONTEXTOS:
        raise ModeloInvalido(f"Contexto “{contexto}” não existe.")

    corpo = str(dados.get("corpo") or "").strip()
    if not corpo:
        raise ModeloInvalido("Escreva o texto da mensagem.")
    if len(corpo) > CORPO_MAX:
        raise ModeloInvalido(
            f"O texto tem {len(corpo)} caracteres — o limite é {CORPO_MAX}, "
            "para sobrar espaço quando as variáveis forem preenchidas.")

    soltas = _chaves_malformadas(corpo)
    if soltas:
        raise ModeloInvalido(
            f"“{soltas[0]}” não é uma variável válida. Use {{{{nome_da_variavel}}}} "
            "em minúsculas, sem acento e sem espaço.")

    permitidas = variaveis_do_contexto(contexto)
    usadas = variaveis_usadas(corpo)
    desconhecidas = [v for v in usadas if v not in permitidas]
    if desconhecidas:
        rotulo = CONTEXTOS[contexto]["rotulo"]
        disponiveis = ", ".join(sorted(permitidas)) or "nenhuma"
        raise ModeloInvalido(
            f"A variável {{{{{desconhecidas[0]}}}}} não existe no contexto "
            f"“{rotulo}”. Quem dispara daí não teria com que preencher, e a "
            f"mensagem sairia com um buraco. Disponíveis: {disponiveis}.")

    chave = slugificar(str(dados.get("chave") or "") or nome)
    if not chave:
        raise ModeloInvalido(
            "Não foi possível gerar a chave a partir do nome — use ao menos "
            "uma letra ou número.")

    return {
        "chave": chave, "nome": nome, "contexto": contexto,
        "descricao": " ".join(str(dados.get("descricao") or "").split())[:DESCRICAO_MAX],
        "corpo": corpo,
        "ativo": 0 if str(dados.get("ativo", 1)) in ("0", "False", "false") else 1,
        "variaveis": usadas,
    }


# ------------------------------------------------------------------- store

def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _enriquecer(m: dict) -> dict:
    ctx = CONTEXTOS.get(m["contexto"]) or {}
    m["contexto_rotulo"] = ctx.get("rotulo", m["contexto"])
    m["variaveis"] = variaveis_usadas(m["corpo"])
    m["previa"] = previa(m["corpo"], m["contexto"])
    m["ativo"] = int(m["ativo"] or 0)
    return m


def listar(esquema: str | None = None, *, contexto: str | None = None,
           so_ativos: bool = False) -> list[dict]:
    init_db(esquema)
    onde, params = [], []
    if contexto:
        onde.append("contexto=%s")
        params.append(contexto)
    if so_ativos:
        onde.append("ativo=1")
    sql = ("SELECT id, chave, nome, contexto, descricao, corpo, ativo,"
           " criado_em, criado_por, atualizado_em, atualizado_por"
           " FROM zap_modelos"
           + (" WHERE " + " AND ".join(onde) if onde else "")
           + " ORDER BY contexto, nome")
    return [_enriquecer(dict(r))
            for r in pglocal.query(sql, tuple(params), esquema=_esq(esquema))]


def obter(chave: str, esquema: str | None = None) -> dict | None:
    init_db(esquema)
    r = pglocal.um(
        "SELECT id, chave, nome, contexto, descricao, corpo, ativo,"
        " criado_em, criado_por, atualizado_em, atualizado_por"
        " FROM zap_modelos WHERE chave=%s", (str(chave or ""),),
        esquema=_esq(esquema))
    return _enriquecer(dict(r)) if r else None


def gravar(dados: dict, *, usuario: str = "", modelo_id: int | None = None,
           esquema: str | None = None) -> dict:
    """Cria ou atualiza. Levanta `ModeloInvalido`.

    A chave duplicada é recusada com nome próprio em vez de deixar a violação
    de UNIQUE subir como erro 500: quem está editando precisa saber que já
    existe um modelo com esse nome, não que "algo deu errado".
    """
    init_db(esquema)
    d = validar(dados)
    agora, esq = _agora(), _esq(esquema)

    existente = pglocal.um("SELECT id FROM zap_modelos WHERE chave=%s",
                           (d["chave"],), esquema=esq)
    if existente and (modelo_id is None or int(existente["id"]) != int(modelo_id)):
        raise ModeloInvalido(
            f"Já existe um modelo com a chave “{d['chave']}”. Mude o nome ou "
            "edite o modelo que já existe.")

    if modelo_id is None:
        r = pglocal.um(
            "INSERT INTO zap_modelos(chave, nome, contexto, descricao, corpo,"
            " ativo, criado_em, criado_por, atualizado_em, atualizado_por)"
            " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (d["chave"], d["nome"], d["contexto"], d["descricao"], d["corpo"],
             d["ativo"], agora, usuario or "", agora, usuario or ""),
            esquema=esq)
        d["id"] = int(r["id"])
    else:
        r = pglocal.um(
            "UPDATE zap_modelos SET chave=%s, nome=%s, contexto=%s,"
            " descricao=%s, corpo=%s, ativo=%s, atualizado_em=%s,"
            " atualizado_por=%s WHERE id=%s RETURNING id",
            (d["chave"], d["nome"], d["contexto"], d["descricao"], d["corpo"],
             d["ativo"], agora, usuario or "", int(modelo_id)), esquema=esq)
        if not r:
            raise ModeloInvalido("Este modelo não existe mais — recarregue a tela.")
        d["id"] = int(r["id"])
    return d


def excluir(modelo_id: int, esquema: str | None = None) -> dict | None:
    """Devolve o modelo excluído (para a auditoria dizer o que sumiu)."""
    init_db(esquema)
    r = pglocal.um("DELETE FROM zap_modelos WHERE id=%s RETURNING chave, nome",
                   (int(modelo_id),), esquema=_esq(esquema))
    return dict(r) if r else None
