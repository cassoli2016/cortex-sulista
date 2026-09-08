# -*- coding: utf-8 -*-
"""A movimentação do veículo, contada pelas macros que o rastreador manda.

DE ONDE VEM. O ERP já recebe as macros do hub de rastreamento em
`ocorrenciarastreamento`, com o rótulo em TEXTO no `parametrorecebimento` —
vivo ao minuto, 5.161 eventos em 7 dias, 92 placas (medido em 06/09/2026). Não
é preciso o webservice da RasterIntegra nem o `MACROS.xls` que segue pendente
com eles: o nome do evento já chega escrito.

O QUE ISSO ACRESCENTA à página. As datas do CT-e dizem o que estava PREVISTO;
a macro diz o que ACONTECEU, com cidade e hora — "chegou no cliente em
Resende/RJ às 06:08", "início da descarga às 07:35". É a diferença entre um
cronograma e uma narrativa, e é a pergunta que quem espera a carga faz.

--------------------------------------------------------------------------
A REGRA DE SEGURANÇA DESTE ARQUIVO, e ela é a razão de ele existir separado
--------------------------------------------------------------------------
NO MESMO CAMPO VÊM COMANDOS DA CENTRAL DE RISCO, com o que só pode ser código
de liberação: `DESBLOQUEAR VEICULO||3389|3398`, `DESLIGAR SIRENE||1432|1144`,
`ENTREGA DO VEICULO||3650|0323|174488`. Numa página pública isso não é um
rótulo feio — é incidente de segurança. E "ENTREGA DO VEICULO" é o exemplo que
prova por que a leitura tem de ser explícita: pelo nome parece a entrega da
carga; é a passagem do veículo, com senha embutida.

DUAS CONTENÇÕES, e a segunda é a que vale:

1. **LISTA BRANCA, nunca lista negra.** Uma lista de proibidos deixa passar o
   que for criado depois — e macro nova é cadastrada pela central de risco,
   não por nós. O que não está em `PUBLICAS` não sai, mesmo que ninguém tenha
   pensado nele.
2. **SAI O NOSSO RÓTULO, NUNCA O TEXTO DO ERP.** Este módulo devolve o texto
   que ESCREVEMOS, e o do fornecedor nunca atravessa a fronteira. É isso que
   torna a contenção robusta a um formato que mude: se amanhã chegar
   `CHEGADA NO CLIENTE|<código>`, o corte no primeiro `|` casa a chave e o que
   sai continua sendo "Chegou no cliente" — o código não tem por onde vazar.

--------------------------------------------------------------------------
COBERTURA: METADE DAS VIAGENS, E A METADE TEM NOME
--------------------------------------------------------------------------
Medido em 06/09/2026 sobre as 120 viagens mais recentes:

    FROTA        11 de 11   (100%)
    LOCACAO      17 de 17   (100%)
    AGREGADOS    34 de 91   ( 37%)
    TERCEIROS     0 de  1
    ------------------------------
    total        62 de 120  ( 52%)

O rastreador da frota própria reporta SEMPRE; o agregado é o buraco, e é
esperado — ele usa o rastreador dele, que nem sempre está no hub da Sulista.

O QUE ISSO OBRIGA: ausência de macro NÃO é "veículo parado" nem "sem
movimentação". É ausência de leitura, e a tela simplesmente não mostra o bloco
— zero que é falta de coleta não vira informação. Inventar uma linha "sem
movimentação registrada" faria metade dos clientes ler imobilidade onde só há
um rastreador que não fala com a gente.
"""
from __future__ import annotations

import logging
import unicodedata

from . import consulta

log = logging.getLogger("cortex.rastreio.macros")

#: AS MACROS QUE PODEM SAIR, e o texto que sai no lugar delas.
#:
#: A chave é o rótulo do hub ATÉ O PRIMEIRO `|`; o valor é o que o cliente lê.
#: Reescrever não é enfeite: `FIM DE CARGA E/OU DESCARGA` é linguagem de
#: operação, e quem espera a carga não tem de decifrar a barra nem o "E/OU".
#:
#: O QUE FICOU DE FORA, e por quê:
#: - `DESBLOQUEAR VEICULO`, `DESLIGAR SIRENE`, `ENTREGA DO VEICULO`: comandos
#:   da central de risco, com código embutido no próprio texto.
#: - `INICIO JORNADA` / `FIM DE JORNADA`: são do MOTORISTA, não da carga. A
#:   página fala da mercadoria; a rotina de trabalho de uma pessoa não é
#:   assunto do cliente dela.
PUBLICAS: dict[str, str] = {
    "INICIO DE VIAGEM":              "Viagem iniciada",
    "REINICIO DE VIAGEM":            "Viagem retomada",
    "CHEGADA NO CLIENTE":            "Chegou no cliente",
    "INICIO DE CARGA E/OU DESCARGA": "Início da carga/descarga",
    "FIM DE CARGA E/OU DESCARGA":    "Carga/descarga concluída",
    "FIM DE VIAGEM":                 "Viagem encerrada",
    "CHEGADA NA MATRIZ OU FILIAL":   "Chegou na base da transportadora",
    "PARADA TRANSITO":               "Parado no trânsito",
    "PARADA PARA ABASTECIMENTO":     "Parada para abastecer",
    "PARADA PARA REFEICAO":          "Parada para refeição",
    "PARADA PARA DESCANSO":          "Parada para descanso",
    "PARADA PARA PERNOITE":          "Parada para pernoite",
    "PARADA POSTO FISCAL":           "Parada em posto fiscal",
    "PARADA PARA MANUTENCAO":        "Parada para manutenção",
}

#: As que a operação trata como MARCO da viagem — as que mudam o que quem
#: espera a carga vai fazer. Separadas das paradas porque é por elas que o
#: aviso de WhatsApp decide mandar mensagem na cadência mais seca.
MARCOS = frozenset({
    "INICIO DE VIAGEM", "CHEGADA NO CLIENTE", "INICIO DE CARGA E/OU DESCARGA",
    "FIM DE CARGA E/OU DESCARGA", "FIM DE VIAGEM",
})

#: A MACRO QUE ENCERRA O ACOMPANHAMENTO, e as que dizem que o veículo voltou a
#: rodar. Estão nomeadas porque a regra de encerramento compara uma a uma — e
#: `CHEGADA NO CLIENTE`, sozinha, NÃO significa o que o nome promete: o mesmo
#: evento é mandado quando o caminhão encosta no cliente para CARREGAR. Ver
#: `chegada_no_destino`, que é onde as três condições moram.
CHEGADA = "CHEGADA NO CLIENTE"
INICIOS_DE_VIAGEM = frozenset({"INICIO DE VIAGEM", "REINICIO DE VIAGEM"})

#: Os mesmos dois, já no NOSSO rótulo — que é a forma em que `recentes()`
#: devolve. Derivados de `PUBLICAS` de propósito: reescrevê-los à mão criaria
#: uma segunda grafia de "Chegou no cliente" que ninguém veria discordar, e a
#: regra pararia de disparar no dia em que a redação mudasse, sem erro nenhum.
_ROTULO_CHEGADA = PUBLICAS[CHEGADA]
_ROTULOS_INICIO = frozenset(PUBLICAS[k] for k in INICIOS_DE_VIAGEM)

#: Janela de leitura. `dtinc` é a coluna indexada — a tabela tem 1 milhão de
#: linhas e o AVA é 9.3 com `statement_timeout`. Medido: 0,24 s por placa
#: (mediana de 10) com esta janela.
DIAS = 10

#: Quantas linhas cruas trazer para achar as permitidas. Um caminhão gera muita
#: `DESBLOQUEAR VEICULO` num dia movimentado; 40 sobra para achar 6 públicas.
LIMITE_CRU = 40

# A JANELA E MULTIPLICACAO, e nao `interval '<n> days'` montado com o
# parametro: sinal de porcentagem dentro da constante de consulta vira
# placeholder do psycopg — a regra da casa, e ela pega ate COMENTARIO. Escrever
# a explicacao dentro do SQL custou uma hora aqui: o psycopg recusou a consulta
# inteira com "only '%s', '%b', '%t' are allowed as placeholders", o `except`
# do modulo devolveu lista vazia como manda o contrato, e o resultado foi
# "nenhuma placa tem movimentacao" — plausivel, silencioso e falso. Por isso a
# explicacao mora AQUI, em Python, fora da string.
#
# `make_interval` seria mais limpo e NAO EXISTE no 9.3, que e a versao do AVA.
SQL = """
SELECT trim(o.parametrorecebimento)                     AS macro,
       o.dtrecebimento                                  AS quando,
       coalesce(nullif(trim(o.cidadeposicaoveiculo),''), '') AS cidade,
       coalesce(o.ufposicaoveiculo, '')                 AS uf
FROM ocorrenciarastreamento o
WHERE o.veiculo = %(placa)s
  AND o.sentido = 2
  AND o.dtinc >= current_timestamp - (%(dias)s * interval '1 day')
  AND (%(desde)s::timestamp IS NULL OR o.dtrecebimento >= %(desde)s::timestamp)
  AND (%(ate)s::timestamp IS NULL OR o.dtrecebimento <= %(ate)s::timestamp)
ORDER BY o.dtrecebimento DESC
LIMIT %(limite)s
"""

#: A SAIDA DA VIAGEM ABERTA desta placa — o mesmo recorte que o `KM_SQL` do
#: detalhe usa para dizer qual viagem e "a de agora". Duas definicoes de viagem
#: corrente na mesma tela e como o km de uma viagem aparece ao lado da
#: movimentacao de outra.
SAIDA_SQL = """
SELECT max(p.dtsaida) AS saida
FROM programacaoembarque p
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND (trim(p.veiculo) = %(placa)s OR trim(p.carreta1) = %(placa)s)
  AND p.dtsaida IS NOT NULL AND p.dtchegada IS NULL
"""


def saida_da_viagem(placa: str):
    """Quando a viagem aberta desta placa comecou, ou None."""
    if not placa:
        return None
    from .. import db
    try:
        r = db.query(SAIDA_SQL, {"placa": placa})
    except Exception:  # noqa: BLE001
        return None
    return (r[0] or {}).get("saida") if r else None


def chave(bruto: str) -> str:
    """O rótulo do hub até o primeiro `|`, normalizado.

    O CORTE VEM ANTES DA CONSULTA À LISTA, e é ele que faz a lista branca
    funcionar com o formato real: o hub manda `PARADA TRANSITO||WC` e
    `PARADA PARA REFEICAO||12.25|13.25` — o mesmo evento com um sufixo que
    varia. Sem o corte, cada variação seria uma chave nova e a lista branca
    barraria eventos legítimos enquanto crescia sem fim.
    """
    return (bruto or "").split("|")[0].strip().upper()


def rotulo(bruto: str) -> str | None:
    """O texto que o cliente lê, ou None quando a macro não pode sair.

    DEVOLVE O NOSSO TEXTO, NUNCA O DO ERP — ver o cabeçalho. É esta linha que
    garante que um código de liberação não tem por onde atravessar, mesmo que
    o formato do fornecedor mude amanhã.
    """
    return PUBLICAS.get(chave(bruto))


def e_marco(bruto: str) -> bool:
    return chave(bruto) in MARCOS


def recentes(placa: str, desde=None, ate=None, limite: int = 6) -> list[dict]:
    """As últimas movimentações públicas desta placa. NUNCA levanta.

    A JANELA E O QUE IMPEDE A NARRATIVA DE OUTRO CLIENTE de aparecer aqui. O
    mesmo cavalo faz três viagens por semana, para embarcadores diferentes:
    sem recorte, quem abrir a carga de hoje leria as paradas da viagem de
    ontem, que não é dele. `desde` é a saída da viagem; `ate` é a entrega,
    para a carga já entregue não continuar "andando" com a viagem seguinte.

    Falha de leitura devolve lista VAZIA, e a tela trata vazio como "não há o
    que mostrar". É o certo aqui: a movimentação é um acréscimo, e derrubar o
    detalhe inteiro de uma carga porque a tabela de macros não respondeu seria
    trocar uma informação a mais por a informação toda.
    """
    placa = (placa or "").strip().upper()
    if not placa:
        return []
    from .. import db
    try:
        linhas = db.query(SQL, {"placa": placa, "dias": DIAS, "desde": desde,
                                "ate": ate, "limite": LIMITE_CRU})
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: leitura de macros falhou: %s",
                    type(exc).__name__)
        return []

    fora = []
    for r in linhas:
        rot = rotulo(r.get("macro"))
        if not rot:
            continue
        fora.append({
            "rotulo": rot,
            "marco": e_marco(r.get("macro")),
            # O LUGAR VAI COMO CIDADE/UF e nunca como coordenada: a página já
            # arredonda a posição do veículo de propósito, e uma cidade é o
            # mesmo grão que o cliente lê no resto da tela.
            #
            # E SAI PELO FORMATADOR DA CASA (`consulta._lugar`), nao por uma
            # juncao propria: a minha trocava espaco por barra e escrevia
            # "Campina/Grande/Do/Sul/PR". Duas telas formatando o mesmo campo
            # de dois jeitos e como a mesma cidade passa a ter dois nomes.
            "onde": consulta._lugar(r.get("cidade"), r.get("uf")),
            "em": r["quando"].isoformat() if r.get("quando") else None,
        })
        if len(fora) >= limite:
            break
    return fora


# --------------------------------------------------------------------------
# a chegada que ENCERRA o acompanhamento
# --------------------------------------------------------------------------
def _cru(lugar: str) -> str:
    """"São Leopoldo/RS" e "SAO LEOPOLDO/RS" são o MESMO município.

    E não é preciosismo: o cadastro do destinatário no ERP escreve a cidade
    SEM acento (`SAO LEOPOLDO`) e o hub de rastreamento escreve COM
    (`SÃO LEOPOLDO`). Medido no CT-e 94540 em 08/09/2026 — comparando os dois
    textos crus, a chegada no destino nunca casaria, e o encerramento
    automático seria um recurso que nunca dispara. Falha muda, das piores:
    ninguém reclama de uma mensagem que continua chegando.
    """
    t = unicodedata.normalize("NFKD", (lugar or "").strip().upper())
    return "".join(c for c in t if not unicodedata.combining(c))


def mesmo_lugar(a: str | None, b: str | None) -> bool:
    """Os dois textos falam da mesma cidade? Vazio nunca casa com nada."""
    return bool(a) and bool(b) and _cru(a) == _cru(b)


def chegada_no_destino(movs: list[dict], destino: str | None) -> dict | None:
    """A chegada no cliente que ENCERRA o acompanhamento, ou None.

    O EVENTO SOZINHO NÃO SERVE, e é por isso que esta função existe em vez de
    um `if rotulo == "Chegou no cliente"` no aviso. O rastreador manda a mesma
    `CHEGADA NO CLIENTE` quando o caminhão encosta para CARREGAR — a viagem do
    CT-e 94540 tem a de Joinville (coleta, 05/09 07:02) e a de São Leopoldo
    (entrega, 08/09 05:05), com o mesmo texto e a mesma tabela. Encerrar na
    primeira mataria o acompanhamento antes de a carga sair da origem, e o
    cliente descobriria isso não recebendo nada.

    TRÊS CONDIÇÕES, e cada uma cobre um jeito diferente de errar:

    1. **Depois de a viagem ter começado** — há um `INICIO DE VIAGEM` (ou
       `REINICIO`) ANTERIOR à chegada. É o pedido literal de quem opera: a
       chegada que interessa é a de quem já estava rodando.
    2. **No lugar do destinatário.** É esta que separa a coleta da entrega
       quando as duas caem dentro da janela — Joinville não é São Leopoldo. Sem
       cidade dos dois lados a função devolve None: preferir o silêncio é
       manter o comportamento antigo (avisar até a entrega ser gravada), e o
       erro para o outro lado custa o acompanhamento de quem está esperando.
    3. **Sem ter voltado a rodar depois.** Um `INICIO DE VIAGEM` mais recente
       que a chegada diz que o caminhão saiu de novo — foi buscar outra coisa,
       trocou de doca, seguiu para o próximo. A carga não chegou; ela passou.

    `movs` vem de `recentes()`, do MAIS RECENTE para o mais antigo — a mesma
    ordem da consulta. E vem com O NOSSO RÓTULO, nunca com o texto do hub: a
    lista branca de `PUBLICAS` já filtrou, e comparar aqui contra o texto cru
    reabriria a porta que este módulo existe para fechar.
    """
    if not destino:
        return None
    for i, m in enumerate(movs):
        rot = m.get("rotulo")
        if rot in _ROTULOS_INICIO:
            # Condição 3: o mais recente dos dois é um início de viagem.
            return None
        if rot != _ROTULO_CHEGADA:
            continue
        if not mesmo_lugar(m.get("onde"), destino):
            return None                                        # condição 2
        # A HORA É A DA PRIMEIRA CHEGADA DO BLOCO, não a da última repetição.
        # O rastreador manda a mesma macro várias vezes enquanto o veículo fica
        # parado no cliente: no CT-e 94540 foram CINCO entre 05:05 e 07:34, e
        # dizer "chegou às 07:34" seria contar como chegada a última vez que o
        # equipamento repetiu — duas horas e meia depois de o caminhão encostar,
        # para quem estava esperando na doca.
        j = i
        while (j + 1 < len(movs)
               and movs[j + 1].get("rotulo") == _ROTULO_CHEGADA
               and mesmo_lugar(movs[j + 1].get("onde"), destino)):
            j += 1
        if any(x.get("rotulo") in _ROTULOS_INICIO for x in movs[j + 1:]):
            return movs[j]                                     # condição 1
        return None
    return None

