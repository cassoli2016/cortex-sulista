# api/contrapartida/lote.py
"""Emissão automática do CT-e de contrapartida, em lote.

POR QUE ESTE MÓDULO É MAIS DESCONFIADO QUE A EMISSÃO MANUAL
===========================================================
Emitir um documento à mão tem um humano olhando o retorno. Uma rotina que
assina em nome de terceiro, sozinha, milhares de vezes por mês, não tem — e
os erros dela chegam multiplicados. Daí as quatro guardas abaixo, que não
existem no caminho manual porque lá não fazem falta.

  1. **IDEMPOTÊNCIA.** Nunca emitir duas vezes para o mesmo CT-e de origem.
     Documento fiscal duplicado não se apaga: cancela-se, dentro de prazo,
     com justificativa, e some do lugar nenhum. Antes de montar qualquer
     coisa, a rotina pergunta se já existe emissão AUTORIZADA para aquela
     chave naquele ambiente.

  2. **DISJUNTOR.** Falha sistêmica (SEFAZ fora, certificado vencido, uma
     validação nova como o IBS/CBS que apareceu em 26/08) rejeita TUDO. Sem
     disjuntor, um lote de mil queima mil números de série antes de alguém
     perceber. Depois de `MAX_FALHAS_SEGUIDAS` recusas consecutivas o lote
     para e diz por quê.

  3. **TETO POR EXECUÇÃO.** Mesmo tudo certo, o primeiro dia em produção não
     pode despejar o acumulado inteiro. O limite é obrigatório e explícito.

  4. **ENSAIO.** `dry_run=True` percorre tudo — seleção, montagem, guardas —
     e não transmite. É como se confere um lote novo antes de soltar.

  5. **TETO MENOR EM PRODUÇÃO.** Em homologação um lote errado custa tempo;
     em produção custa cancelamento e retificação, documento a documento.

MANUAL SEMPRE; AUTOMÁTICO SÓ SE ALGUÉM LIGAR
--------------------------------------------
A emissão sob demanda — um documento, ou um lote disparado por uma pessoa —
funciona sempre. Já a execução **desassistida** (rotina agendada) só roda se
alguém tiver ligado explicitamente, e o padrão é DESLIGADO.

A diferença não é de conveniência: quando há uma pessoa disparando, existe
alguém para ler o retorno e parar. Desassistido não tem. Ligar e desligar
entra na trilha de auditoria com autor e data, porque é a decisão que muda
quem responde por um documento emitido às três da manhã.

OS DOIS AMBIENTES
-----------------
O lote atende homologação e produção, mas **não decide** qual: repassa o
ambiente para `emissao.transmitir`, que recusa produção enquanto ela não tiver
sido liberada — com confirmação e registro de autor. O padrão aqui continua
sendo homologação.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from api import db
from api.contrapartida import cadastro, documento, emissao

log = logging.getLogger("cortex.contrapartida.lote")

# Recusas seguidas que caracterizam falha sistêmica. Três é o bastante: duas
# podem ser azar (dois cadastros ruins em sequência), três seguidas em
# documentos de agregados diferentes é o ambiente, não o documento.
MAX_FALHAS_SEGUIDAS = 3

# Quantas vezes a MESMA chave pode levar a MESMA recusa antes de sair da fila.
# Rejeicao e deterministica: o mesmo documento, com o mesmo cadastro e o mesmo
# enquadramento, sera recusado com o mesmo codigo para sempre. Tres e o
# bastante para separar "recusa de verdade" de um tropeco pontual.
MAX_TENTATIVAS_MESMA_RECUSA = 3

# Teto de segurança do teto: mesmo que alguém peça mais, o lote não passa
# disto numa execução. Existe para o caso de um `limite` vir de configuração
# errada — não para limitar o uso legítimo, que é recorrente e incremental.
TETO_ABSOLUTO = 500

# Em produção o teto absoluto é MENOR. Um lote errado em homologação custa
# tempo; em produção custa cancelamento e retificação, documento a documento,
# dentro de prazo. Começar devagar é o comportamento correto do primeiro dia —
# e do segundo, até alguém decidir o contrário com número na mão.
TETO_ABSOLUTO_PRODUCAO = 50

# CT-e de agregado PJ no período, do mais antigo para o mais novo. A ordem
# importa: numeração de série sai sequencial e acompanhar a fila em ordem
# cronológica é o que um fiscal espera ver.
PENDENTES_SQL = """
SELECT k.chaveacessocte AS chave, k.dtemissao, v.proprietario AS cnpj,
       cd.razaosocial AS nome, cd.inscricaoestadual AS ie,
       coalesce(k.valortotalprestacao, 0)::float8 AS valor
  FROM conhecimento k
  JOIN veiculo v   ON v.placa = k.veiculo
  JOIN cadastro cd ON cd.codigo = v.proprietario
 WHERE v.utilizacaoveiculo = 'AGR'
   AND coalesce(k.semaforo, 1) = 1
   AND k.dtcancelamento IS NULL
   AND k.chaveacessocte IS NOT NULL
   AND k.dtemissao >= %(de)s::date AND k.dtemissao < %(ate)s::date
   AND length(regexp_replace(coalesce(v.proprietario,''),'[^0-9]','','g')) = 14
 ORDER BY k.dtemissao, k.numero
"""


CHAVE_AUTOMACAO = "automacao_ativa"
CHAVE_INTERVALO = "automacao_intervalo_min"
CHAVE_ULTIMA = "automacao_ultima_execucao"

# Intervalo entre execuções da rotina, em minutos.
#
# O piso não é capricho: cada execução consulta o ERP, lê o cadastro de todos
# os agregados e conversa com a SEFAZ. Rodar de minuto em minuto não emite
# nada mais rápido — a fila só cresce quando um CT-e novo é digitado — e
# transforma uma rotina em carga constante sobre o banco e sobre o órgão.
#
# O teto existe para que "automático" continue significando alguma coisa:
# acima de um dia, é mais honesto rodar manual quando precisar.
INTERVALO_PADRAO_MIN = 60
INTERVALO_MIN = 5
INTERVALO_MAX = 1440


def automacao_ativa() -> bool:
    """A execução desassistida está ligada? PADRÃO: não.

    Ausência de registro significa desligado — nunca o contrário. Um default
    ligado faria a automação começar a emitir por causa de um banco novo ou
    de uma restauração de backup.

    A configuração mora com a da liberação de produção (`emissao`): são
    interruptores da mesma natureza — ligam algo que emite documento sem
    alguém confirmando na hora.
    """
    r = emissao.config_lida(CHAVE_AUTOMACAO)
    return bool(r) and r["valor"] == "1"


def intervalo_min() -> int:
    """Minutos entre execuções da rotina. Padrão: uma hora."""
    r = emissao.config_lida(CHAVE_INTERVALO)
    try:
        v = int((r or {}).get("valor") or INTERVALO_PADRAO_MIN)
    except (TypeError, ValueError):
        # configuração corrompida cai no padrão em vez de derrubar a rotina
        log.warning("intervalo de automacao ilegivel - usando o padrao")
        return INTERVALO_PADRAO_MIN
    return min(max(v, INTERVALO_MIN), INTERVALO_MAX)


def definir_intervalo(minutos: int, quem: str) -> dict:
    """Grava o intervalo, dentro dos limites. Fora deles, RECUSA.

    Recusar em vez de aparar em silêncio: quem digitou 1 minuto quis dizer
    alguma coisa, e aceitar calado gravando 5 esconderia isso.
    """
    if not quem:
        raise ValueError("Informe quem está mudando o intervalo.")
    try:
        v = int(minutos)
    except (TypeError, ValueError):
        raise ValueError("O intervalo é em minutos, um número inteiro.") from None
    if not (INTERVALO_MIN <= v <= INTERVALO_MAX):
        raise ValueError(
            f"Intervalo fora do permitido ({INTERVALO_MIN} a {INTERVALO_MAX} "
            f"minutos). Abaixo do piso a rotina vira carga constante sobre o "
            f"ERP e a SEFAZ sem emitir mais rápido — a fila só cresce quando "
            f"um CT-e novo é digitado.")
    agora = datetime.now().isoformat(timespec="seconds")
    with emissao._conn_config() as c:
        c.execute(
            "INSERT INTO lote_config(chave, valor, quem, quando)"
            " VALUES(?,?,?,?) ON CONFLICT(chave) DO UPDATE SET"
            " valor=excluded.valor, quem=excluded.quem, quando=excluded.quando",
            (CHAVE_INTERVALO, str(v), quem, agora))
        cadastro._audita(c, quem, "intervalo_automacao", "-", f"{v} min")
    return {"intervalo_min": v, "quem": quem, "quando": agora}


def ultima_execucao() -> str | None:
    r = emissao.config_lida(CHAVE_ULTIMA)
    return (r or {}).get("quando")


def registrar_execucao(quem: str) -> None:
    """Marca que a rotina rodou AGORA. Gravado mesmo quando o lote não emitiu
    nada: o que se está medindo é a passagem da rotina, não o resultado —
    senão um período sem fila faria a rotina rodar em looping."""
    agora = datetime.now().isoformat(timespec="seconds")
    with emissao._conn_config() as c:
        c.execute(
            "INSERT INTO lote_config(chave, valor, quem, quando)"
            " VALUES(?,?,?,?) ON CONFLICT(chave) DO UPDATE SET"
            " valor=excluded.valor, quem=excluded.quem, quando=excluded.quando",
            (CHAVE_ULTIMA, agora, quem, agora))


def deve_rodar() -> tuple[bool, str]:
    """Está na hora da próxima execução? Devolve também o PORQUÊ.

    O agendador do sistema dispara em intervalo fixo e curto; quem decide se
    é hora é isto, lendo o intervalo configurado na tela. Assim mudar o
    intervalo tem efeito imediato, sem reinstalar tarefa nenhuma — e a
    configuração continua num lugar só.
    """
    if not automacao_ativa():
        return False, "automação desligada"
    ult = ultima_execucao()
    if not ult:
        return True, "primeira execução"
    try:
        passados = (datetime.now() - datetime.fromisoformat(ult)).total_seconds() / 60
    except ValueError:
        # carimbo ilegível: roda e regrava, em vez de travar para sempre
        return True, "última execução com data ilegível"
    falta = intervalo_min() - passados
    if falta > 0:
        return False, f"faltam {falta:.0f} min para a próxima ({intervalo_min()} min)"
    return True, f"{passados:.0f} min desde a última ({intervalo_min()} min)"


def estado() -> dict:
    """Tudo que a tela de configuração precisa mostrar, num lugar só."""
    a = emissao.config_lida(CHAVE_AUTOMACAO) or {}
    i = emissao.config_lida(CHAVE_INTERVALO) or {}
    return {
        "ambiente": emissao.estado_ambiente(),
        "automacao": {
            "ativa": automacao_ativa(),
            "quem": a.get("quem"), "quando": a.get("quando"),
            "intervalo_min": intervalo_min(),
            "intervalo_quem": i.get("quem"), "intervalo_quando": i.get("quando"),
            "intervalo_limites": [INTERVALO_MIN, INTERVALO_MAX],
            "ultima_execucao": ultima_execucao(),
        },
        "teto": {"homologacao": TETO_ABSOLUTO,
                 "producao": TETO_ABSOLUTO_PRODUCAO},
        "falhas_para_parar": MAX_FALHAS_SEGUIDAS,
    }


def definir_automacao(ativa: bool, quem: str) -> dict:
    """Liga ou desliga a execução desassistida. Entra na auditoria.

    `quem` é obrigatório: esta é a decisão que define quem responde por um
    documento emitido sem ninguém olhando.
    """
    return emissao.config_grava(CHAVE_AUTOMACAO, ativa, quem,
                                "automacao_emissao")


def teto_do(ambiente: str) -> int:
    """Teto absoluto do ambiente. Produção começa devagar, de propósito."""
    return (TETO_ABSOLUTO_PRODUCAO if ambiente == emissao.PRODUCAO
            else TETO_ABSOLUTO)


def _ja_emitidas(ambiente: str) -> set[str]:
    """Chaves de origem que JÁ têm documento autorizado neste ambiente.

    Só as autorizadas contam: uma tentativa recusada não emitiu nada, e o
    CT-e de origem continua pendente.
    """
    with emissao._conn() as c:
        return {r["chave_origem"] for r in c.execute(
            "SELECT DISTINCT chave_origem FROM emissao"
            " WHERE ambiente=? AND cstat='100'", (ambiente,))}


def _quarentena(ambiente: str) -> dict[str, dict]:
    """Chaves que a SEFAZ já recusou tantas vezes que insistir é desperdício.

    REJEIÇÃO É DETERMINÍSTICA. O mesmo documento, com o mesmo cadastro e o
    mesmo enquadramento, será recusado com o mesmo código para sempre — não
    existe "tentar de novo mais tarde" como existe para uma indisponibilidade.
    Sem esta guarda a rotina reapresenta o mesmo documento a cada rodada, e
    como as recusas são consecutivas, o DISJUNTOR dispara nelas e o lote morre
    antes de chegar em quem estava certo mais atrás na fila.

    Foi medido: três CT-e recusados 14 vezes cada, no topo da fila por serem
    os mais antigos, derrubando o lote toda rodada — e os dois documentos
    atrás deles nunca chegaram a ser tentados.

    Só entra quem NUNCA foi autorizado: uma chave autorizada já sai pela
    idempotência, e uma recusa antiga seguida de autorização não pode
    ressuscitar como quarentena.
    """
    with emissao._conn() as c:
        linhas = [dict(r) for r in c.execute(
            "SELECT chave_origem, cstat, xmotivo, count(*) AS n,"
            "       max(quando) AS ultima"
            "  FROM emissao"
            " WHERE ambiente=? AND chave_origem IS NOT NULL"
            "   AND cstat IS NOT NULL AND cstat NOT LIKE 'CANC:%'"
            " GROUP BY chave_origem, cstat", (ambiente,))]
    autorizadas = {r["chave_origem"] for r in linhas if str(r["cstat"]) == "100"}
    fora: dict[str, dict] = {}
    for r in linhas:
        ch = r["chave_origem"]
        if ch in autorizadas or str(r["cstat"]) == "100":
            continue
        if (r["n"] or 0) >= MAX_TENTATIVAS_MESMA_RECUSA:
            fora[ch] = {"cstat": r["cstat"], "xmotivo": r["xmotivo"],
                        "tentativas": r["n"], "ultima": r["ultima"]}
    return fora


def _impedimento(x: dict, mapa: dict, desligados) -> str | None:
    """Por que este CT-e NAO pode virar contrapartida agora — ou None.

    Uma funcao so, usada pela fila e pelo resumo, porque as duas ja divergiram:
    a fila conferia apenas certificado e procuracao, e o cadastro do ERP ficava
    para a tela. Resultado: agregado com certificado valido e SEM INSCRICAO
    ESTADUAL entrava na fila todo dia e a SEFAZ recusava com "229 - IE do
    emitente nao informada", um documento por vez, ate o disjuntor de tres
    falhas seguidas derrubar o lote inteiro — levando junto os agregados que
    estavam certos e vinham depois na ordem.
    """
    if not ((mapa.get(x["cnpj"]) or {}).get("prontidao") or {}).get("pronto"):
        return "sem procuração, certificado ou senha"
    if not cadastro.ie_utilizavel(x.get("ie")):
        return "sem inscrição estadual utilizável no cadastro do ERP"
    if x["cnpj"] in desligados:
        return "envio desligado para este agregado"
    return None


def pendentes(de: str, ate: str, ambiente: str = emissao.HOMOLOGACAO,
              limite: int = 50) -> list[dict]:
    """A fila REAL: CT-e sem contrapartida, de agregado que pode emitir hoje.

    Filtra por prontidão aqui e não na hora de transmitir para que o número
    da fila seja o que dá para fazer — uma fila que inclui quem não tem
    certificado promete trabalho que vai falhar.
    """
    linhas = db.query(PENDENTES_SQL, {"de": de, "ate": ate})
    feitas = _ja_emitidas(ambiente)
    presos = _quarentena(ambiente)
    mapa = cadastro.mapa()
    desligados = emissao.envios_desligados()
    fila: list[dict] = []
    for x in linhas:
        if x["chave"] in feitas or x["chave"] in presos:
            continue
        if _impedimento(x, mapa, desligados):
            continue
        fila.append(dict(x, dtemissao=str(x["dtemissao"])[:10]))
        if len(fila) >= min(limite, teto_do(ambiente)):
            break
    return fila


def processar_lote(de: str, ate: str, enq: documento.Enquadramento, *,
                   quem: str, limite: int, ambiente: str = emissao.HOMOLOGACAO,
                   dry_run: bool = False, desassistido: bool = False) -> dict:
    """Emite a fila do período. Devolve o que aconteceu, documento a documento.

    `limite` e `quem` são obrigatórios: um lote sem teto e sem autor é
    exatamente o que não se quer rodando sozinho.

    `desassistido=True` é o modo da rotina agendada, e só roda se a automação
    estiver ligada. O disparo por uma pessoa não depende disso — manual
    sempre funciona.
    """
    if not quem:
        raise ValueError("Informe quem está disparando o lote.")
    if limite <= 0:
        raise ValueError("O lote precisa de um teto positivo.")
    if desassistido and not automacao_ativa():
        raise PermissionError(
            "A emissão automática está DESLIGADA. Ela não liga sozinha e não "
            "tem padrão ligado: alguém precisa habilitá-la, e esse alguém "
            "fica registrado. A emissão manual continua disponível.")

    fila = pendentes(de, ate, ambiente, limite)
    resultado = {"periodo": {"de": de, "ate": ate}, "ambiente": ambiente,
                 "dry_run": dry_run, "fila": len(fila),
                 "autorizados": 0, "recusados": 0, "erros": 0,
                 "interrompido": None, "itens": []}
    seguidas = 0

    for item in fila:
        if dry_run:
            resultado["itens"].append(dict(item, situacao="ensaio"))
            continue
        try:
            r = emissao.transmitir(item["chave"], enq, quem=quem,
                                   ambiente=ambiente)
            ok = r.get("autorizado")
            resultado["autorizados" if ok else "recusados"] += 1
            seguidas = 0 if ok else seguidas + 1
            resultado["itens"].append(dict(
                item, situacao="autorizado" if ok else "recusado",
                cstat=r.get("cStat"), xmotivo=r.get("xMotivo"),
                protocolo=r.get("protocolo"), chave_nova=r.get("chave")))
        except Exception as exc:  # noqa: BLE001
            # Erro ANTES da SEFAZ (cadastro, montagem, certificado) conta para
            # o disjuntor do mesmo jeito: se todos falham, o lote nao deve
            # continuar tentando.
            seguidas += 1
            resultado["erros"] += 1
            resultado["itens"].append(dict(item, situacao="erro",
                                           xmotivo=str(exc)[:300]))
            log.warning("lote: %s falhou: %s", item["chave"], exc)

        if seguidas >= MAX_FALHAS_SEGUIDAS:
            resultado["interrompido"] = (
                f"{seguidas} falhas seguidas — o lote parou para não queimar "
                f"numeração de série. Isso costuma ser problema de ambiente "
                f"(SEFAZ fora, certificado, validação nova), não do documento: "
                f"confira o motivo da última antes de repetir.")
            log.error("lote interrompido: %s", resultado["interrompido"])
            break

    resultado["restante"] = max(0, len(fila) - len(resultado["itens"]))
    return resultado


def resumo_fila(de: str, ate: str,
                ambiente: str = emissao.HOMOLOGACAO) -> dict:
    """Quanto há para fazer, sem montar nada. Para a tela e para o agendador
    decidirem se vale disparar."""
    linhas = db.query(PENDENTES_SQL, {"de": de, "ate": ate})
    feitas = _ja_emitidas(ambiente)
    mapa = cadastro.mapa()
    desligados = emissao.envios_desligados()
    presos = _quarentena(ambiente)
    total = len(linhas)
    ja = sum(1 for x in linhas if x["chave"] in feitas)
    quarentena = sum(1 for x in linhas
                     if x["chave"] not in feitas and x["chave"] in presos)
    # MESMO criterio da fila, pela mesma funcao: quando o resumo contava por
    # conta propria, ele prometia "16 a emitir" e a fila entregava rejeicao.
    faltas = [_impedimento(x, mapa, desligados) for x in linhas
              if x["chave"] not in feitas and x["chave"] not in presos]
    sem_prontidao = sum(1 for f in faltas if f and f.startswith("sem procuração"))
    sem_cadastro = sum(1 for f in faltas if f and f.startswith("sem inscrição"))
    fora = sum(1 for f in faltas if f and f.startswith("envio desligado"))
    return {"ctes_no_periodo": total, "ja_emitidos": ja,
            "sem_agregado_pronto": sem_prontidao,
            "sem_cadastro": sem_cadastro,
            "envio_desligado": fora,
            "em_quarentena": quarentena,
            "a_emitir": sum(1 for f in faltas if not f),
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M")}


def pilha_fiscal() -> tuple[bool, str]:
    """A pilha que monta, assina e transmite está instalada?

    Existe porque a ausência dela é INVISÍVEL no caminho normal: a rotina
    passava, marcava a passagem, e só então cada documento morria com
    "No module named 'erpbrasil'". Do lado de fora não havia diferença entre
    "não havia nada a emitir" e "o sistema perdeu a capacidade de emitir" —
    e a segunda durou de um deploy até alguém reparar, porque o `uv sync` do
    AutoDeploy desinstalava a pilha a cada atualização de dependências.

    Conferir na entrada custa um import e transforma isso num estado que a
    tela mostra e o agendador registra como falha.
    """
    try:
        import erpbrasil.assinatura  # noqa: F401
        import erpbrasil.edoc  # noqa: F401
        import nfelib  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""
