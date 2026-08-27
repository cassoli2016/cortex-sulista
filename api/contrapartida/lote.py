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

MANUAL SEMPRE; AUTOMÁTICO SÓ SE ALGUÉM LIGAR
--------------------------------------------
A emissão sob demanda — um documento, ou um lote disparado por uma pessoa —
funciona sempre. Já a execução **desassistida** (rotina agendada) só roda se
alguém tiver ligado explicitamente, e o padrão é DESLIGADO.

A diferença não é de conveniência: quando há uma pessoa disparando, existe
alguém para ler o retorno e parar. Desassistido não tem. Ligar e desligar
entra na trilha de auditoria com autor e data, porque é a decisão que muda
quem responde por um documento emitido às três da manhã.

O QUE ELE NÃO FAZ
-----------------
Produção. `emissao.transmitir` recusa, e este módulo não tem como contornar:
ele não escolhe ambiente, repassa. Abrir produção continua sendo decisão de
quem responde pelo fiscal.
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

# Teto de segurança do teto: mesmo que alguém peça mais, o lote não passa
# disto numa execução. Existe para o caso de um `limite` vir de configuração
# errada — não para limitar o uso legítimo, que é recorrente e incremental.
TETO_ABSOLUTO = 500

# CT-e de agregado PJ no período, do mais antigo para o mais novo. A ordem
# importa: numeração de série sai sequencial e acompanhar a fila em ordem
# cronológica é o que um fiscal espera ver.
PENDENTES_SQL = """
SELECT k.chaveacessocte AS chave, k.dtemissao, v.proprietario AS cnpj,
       cd.razaosocial AS nome,
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


_DDL_CONFIG = """
CREATE TABLE IF NOT EXISTS lote_config (
  chave      TEXT PRIMARY KEY,
  valor      TEXT NOT NULL,
  quem       TEXT NOT NULL,
  quando     TEXT NOT NULL
);
"""

CHAVE_AUTOMACAO = "automacao_ativa"


def _conn_config():
    c = emissao._conn()
    c.executescript(_DDL_CONFIG)
    return c


def automacao_ativa() -> bool:
    """A execução desassistida está ligada? PADRÃO: não.

    Ausência de registro significa desligado — nunca o contrário. Um default
    ligado faria a automação começar a emitir por causa de um banco novo ou
    de uma restauração de backup.
    """
    with _conn_config() as c:
        r = c.execute("SELECT valor FROM lote_config WHERE chave=?",
                      (CHAVE_AUTOMACAO,)).fetchone()
    return bool(r) and r["valor"] == "1"


def definir_automacao(ativa: bool, quem: str) -> dict:
    """Liga ou desliga a execução desassistida. Entra na auditoria.

    `quem` é obrigatório: esta é a decisão que define quem responde por um
    documento emitido sem ninguém olhando.
    """
    if not quem:
        raise ValueError("Informe quem está ligando/desligando a automação.")
    agora = datetime.now().isoformat(timespec="seconds")
    with _conn_config() as c:
        c.execute(
            "INSERT INTO lote_config(chave, valor, quem, quando)"
            " VALUES(?,?,?,?) ON CONFLICT(chave) DO UPDATE SET"
            " valor=excluded.valor, quem=excluded.quem, quando=excluded.quando",
            (CHAVE_AUTOMACAO, "1" if ativa else "0", quem, agora))
        cadastro._audita(c, quem, "automacao_emissao", "-",
                         "ligada" if ativa else "desligada")
    log.warning("automacao de emissao %s por %s",
                "LIGADA" if ativa else "desligada", quem)
    return {"ativa": ativa, "quem": quem, "quando": agora}


def _ja_emitidas(ambiente: str) -> set[str]:
    """Chaves de origem que JÁ têm documento autorizado neste ambiente.

    Só as autorizadas contam: uma tentativa recusada não emitiu nada, e o
    CT-e de origem continua pendente.
    """
    with emissao._conn() as c:
        return {r["chave_origem"] for r in c.execute(
            "SELECT DISTINCT chave_origem FROM emissao"
            " WHERE ambiente=? AND cstat='100'", (ambiente,))}


def pendentes(de: str, ate: str, ambiente: str = emissao.HOMOLOGACAO,
              limite: int = 50) -> list[dict]:
    """A fila REAL: CT-e sem contrapartida, de agregado que pode emitir hoje.

    Filtra por prontidão aqui e não na hora de transmitir para que o número
    da fila seja o que dá para fazer — uma fila que inclui quem não tem
    certificado promete trabalho que vai falhar.
    """
    linhas = db.query(PENDENTES_SQL, {"de": de, "ate": ate})
    feitas = _ja_emitidas(ambiente)
    mapa = cadastro.mapa()
    fila: list[dict] = []
    for x in linhas:
        if x["chave"] in feitas:
            continue
        pront = (mapa.get(x["cnpj"]) or {}).get("prontidao") or {}
        if not pront.get("pronto"):
            continue
        fila.append(dict(x, dtemissao=str(x["dtemissao"])[:10]))
        if len(fila) >= min(limite, TETO_ABSOLUTO):
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
    total = len(linhas)
    ja = sum(1 for x in linhas if x["chave"] in feitas)
    sem_prontidao = sum(
        1 for x in linhas if x["chave"] not in feitas
        and not ((mapa.get(x["cnpj"]) or {}).get("prontidao") or {}).get("pronto"))
    return {"ctes_no_periodo": total, "ja_emitidos": ja,
            "sem_agregado_pronto": sem_prontidao,
            "a_emitir": total - ja - sem_prontidao,
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M")}
