# -*- coding: utf-8 -*-
"""ESCREVER movimento de pneu no CÓRTEX — o que torna o módulo nosso.

Até aqui tudo era leitura: o instantâneo, o histórico, as inspeções, as tabelas
de domínio. Isso replica a Prolog, não substitui. Substituir é poder dizer
"este pneu foi montado neste veículo, nesta posição, com este hodômetro" AQUI —
e continuar dizendo no dia em que a integração acabar.

O QUE SEPARA ISTO DE UM FORMULÁRIO: as validações. Um cadastro que aceita o que
for digitado não é um módulo próprio, é um caderno. Cada regra abaixo existe
porque a alternativa é um dado que ninguém consegue confiar depois:

1. **A posição tem de existir naquele veículo.** É para isso que os 44
   diagramas foram replicados. Sem essa checagem, "3DE" numa carreta de dois
   eixos entra e fica.
2. **A posição tem de estar LIVRE.** Dois pneus na mesma posição é um erro que
   não se descobre: o inventário fecha, o CPK divide por um km que só um dos
   dois rodou, e a conta some no meio de oito mil pneus.
3. **O pneu tem de estar em estado que permita.** Montar um pneu que está
   sucateado, ou remover um que está no estoque, é dedo trocado — e aceitar
   isso faz o estado do parque virar ficção em poucas semanas.
4. **O hodômetro tem a mesma faixa física do resto do módulo.** 1 km e 7,3
   milhões já apareceram no mesmo campo vindos do fornecedor; do teclado
   aparecem também.
5. **O motivo da sucata vem da tabela**, não de texto livre. Motivo digitado
   vira dez grafias da mesma coisa e nenhum agrupamento funciona.

TUDO ENTRA NO `audit_log`, antes de qualquer efeito — é a regra da casa, e aqui
ela vale dobrado: movimento de pneu é o registro de onde sai o CPK, e CPK
decide compra.

ORIGEM `cortex`, e não `prolog`. A coluna existe justamente para que, no
futuro, se saiba qual pedaço da história é importado e qual é nosso — e para
que a coleta da Prolog nunca sobrescreva o que foi digitado aqui.
"""
from __future__ import annotations

import logging

from .. import pglocal

log = logging.getLogger("cortex.pneus.movimento")

#: A mesma faixa física do hodômetro do resto do módulo.
ODO_MIN, ODO_MAX = 1000, 3_000_000

#: Os estados a partir dos quais cada movimento faz sentido. Não é burocracia:
#: montar um pneu sucateado ou remover um que está no estoque é dedo trocado, e
#: aceitar isso faz o estado do parque virar ficção em poucas semanas.
ESTADOS_PARA = {
    "instalacao": {"estoque", "analise"},
    "remocao": {"rodando"},
    "sucata": {"estoque", "analise", "rodando"},
}

#: Para onde o pneu vai depois de cada movimento.
ESTADO_APOS = {"instalacao": "rodando", "remocao": "estoque",
               "sucata": "sucata"}


class MovimentoInvalido(Exception):
    """Recusa LEGÍVEL, não erro nosso. Vira 409 na rota, nunca 500 — e a
    mensagem chega inteira ao usuário (o Cloudflare troca o corpo de 5xx)."""


def _odometro(v):
    if v in (None, ""):
        return None
    try:
        v = int(float(str(v).replace(".", "").replace(",", ".")))
    except (TypeError, ValueError):
        raise MovimentoInvalido("Hodômetro inválido.") from None
    if not (ODO_MIN <= v <= ODO_MAX):
        raise MovimentoInvalido(
            "Hodômetro fora da faixa possível (%s a %s km)."
            % (format(ODO_MIN, ","), format(ODO_MAX, ",")))
    return v


POSICOES_SQL = """
SELECT array_agg(DISTINCT p.posicao_atual ORDER BY p.posicao_atual) AS pos,
       max(d.id) AS diagrama_id, max(d.nome) AS diagrama,
       max(coalesce(soma.pneus, 0)) AS pneus_do_diagrama
FROM pne_veiculo alvo
JOIN pne_diagrama d       ON d.id = alvo.diagrama_id
JOIN pne_veiculo irmao    ON irmao.diagrama_id = d.id
JOIN pne_pneu p           ON upper(trim(p.placa_atual)) = irmao.placa
                         AND p.posicao_atual IS NOT NULL
LEFT JOIN LATERAL (
  SELECT sum((e->>'pneus')::int) AS pneus
  FROM jsonb_array_elements(d.posicoes) e) soma ON true
WHERE alvo.placa = %s
"""


def posicoes_do_veiculo(placa: str) -> dict:
    """As siglas de posição que aquele veículo aceita, e de onde elas vieram.

    OBSERVADAS, NÃO INVENTADAS, e esta é a segunda versão: a primeira montava a
    sigla a partir da estrutura do diagrama (`eixo` + lado + face) e produzia
    `2DE` para um cavalo. O parque usa `TDE` e `RDE` ali — letras, não números.
    Implemento numera o eixo; tração usa letra. A regra da casa é clara: código
    sem tabela de domínio não vira rótulo inventado.

    Então o vocabulário sai do que os VEÍCULOS IRMÃOS — os que usam o mesmo
    diagrama — realmente têm montado. São 203 carretas de 3 eixos e 36 trucks,
    o que torna a união confiável.

    O DIAGRAMA CONTINUA VALENDO, como CONFERÊNCIA: ele diz quantos pneus o
    veículo tem, e a contagem de posições observadas (fora estepe) tem de bater.
    Quando não bate, a resposta diz isso em vez de fingir que sabe.
    """
    r = pglocal.query(POSICOES_SQL, ((placa or "").strip().upper(),))
    if not r or not r[0]["pos"]:
        return {"posicoes": [], "diagrama": None,
                "motivo": "não há diagrama ou nenhum veículo igual tem pneu "
                          "montado para servir de referência"}
    pos = [x for x in r[0]["pos"] if x]
    eixo = [x for x in pos if not x.startswith("ES")]
    esperados = int(r[0]["pneus_do_diagrama"] or 0)
    fora = {"posicoes": pos, "diagrama": r[0]["diagrama"],
            "de_eixo": len(eixo), "esperados": esperados,
            "estepes": len(pos) - len(eixo)}
    if esperados and len(eixo) != esperados:
        # SE DECLARA em vez de recusar: o vocabulário observado ainda serve
        # para validar, e o desencontro é informação para quem cuida do
        # cadastro — não motivo para travar uma montagem legítima.
        fora["aviso"] = ("o diagrama %s prevê %d pneus de eixo e o parque "
                         "mostra %d posições" % (r[0]["diagrama"], esperados,
                                                 len(eixo)))
    return fora


def _pneu(cur, pneu_id: int) -> dict:
    cur.execute("""
        SELECT id, serie, status, vida_atual, placa_atual, posicao_atual
        FROM pne_pneu WHERE id = %s""", (pneu_id,))
    p = cur.fetchone()
    if not p:
        raise MovimentoInvalido("Pneu não encontrado.")
    return dict(p)


def _exigir_estado(p: dict, tipo: str) -> None:
    permitidos = ESTADOS_PARA[tipo]
    if p["status"] not in permitidos:
        raise MovimentoInvalido(
            "O pneu %s está como '%s' e isso não permite %s. Estados que "
            "permitem: %s." % (p["serie"], p["status"], tipo,
                               ", ".join(sorted(permitidos))))


def _gravar(cur, pneu_id, tipo, placa, posicao, km, motivo, obs, usuario):
    cur.execute("""
        INSERT INTO pne_evento
            (pneu_id, tipo, ocorrido_em, placa, posicao, km_veiculo, motivo,
             observacao, origem, usuario)
        VALUES (%s,%s, now(), %s,%s,%s,%s,%s,'cortex',%s)
        RETURNING id""",
        (pneu_id, tipo, placa, posicao, km, motivo, obs, usuario))
    return cur.fetchone()["id"]


def _auditar(usuario, acao, alvo, detalhe, ip):
    """A trilha vem ANTES do efeito. Se o banco cair no meio, é melhor ter a
    intenção registrada sem o efeito do que o efeito sem a intenção."""
    try:
        from .. import auth
        auth.audit(usuario or "?", acao, alvo, detalhe, ip or "")
    except Exception:  # noqa: BLE001
        log.warning("pneus: trilha de auditoria falhou em %s", acao)


def instalar(pneu_id: int, placa: str, posicao: str, km=None,
             usuario: str = "", ip: str = "") -> dict:
    """Monta um pneu num veículo, numa posição. Recusa com motivo."""
    placa = (placa or "").strip().upper()
    posicao = (posicao or "").strip().upper()
    km = _odometro(km)
    if not placa or not posicao:
        raise MovimentoInvalido("Informe a placa e a posição.")

    d = posicoes_do_veiculo(placa)
    validas = d["posicoes"]
    if not validas:
        raise MovimentoInvalido(
            "Não sabemos as posições de %s (%s). Sem isso não dá para validar "
            "a montagem." % (placa, d.get("motivo") or "sem referência"))
    if posicao not in validas:
        raise MovimentoInvalido(
            "A posição %s não existe em %s (%s). As posições dele são: %s."
            % (posicao, placa, d.get("diagrama") or "sem diagrama",
               ", ".join(validas)))

    _auditar(usuario, "pneu_instalar", "pneu:%s" % pneu_id,
             "%s em %s" % (posicao, placa), ip)
    with pglocal.get_conn() as conn, conn.cursor() as cur:
        p = _pneu(cur, pneu_id)
        _exigir_estado(p, "instalacao")
        # POSIÇÃO OCUPADA é o erro que não se descobre: o inventário fecha, e o
        # CPK divide por um km que só um dos dois pneus rodou.
        cur.execute("""
            SELECT serie FROM pne_pneu
            WHERE placa_atual = %s AND posicao_atual = %s AND id <> %s""",
            (placa, posicao, pneu_id))
        ocupada = cur.fetchone()
        if ocupada:
            raise MovimentoInvalido(
                "A posição %s de %s já está com o pneu %s. Remova-o antes."
                % (posicao, placa, ocupada["serie"]))

        ident = _gravar(cur, pneu_id, "instalacao", placa, posicao, km,
                        None, None, usuario)
        cur.execute("""
            UPDATE pne_pneu SET placa_atual = %s, posicao_atual = %s,
                   status = %s, atualizado_em = now() WHERE id = %s""",
            (placa, posicao, ESTADO_APOS["instalacao"], pneu_id))
    return {"ok": True, "evento": ident, "pneu": pneu_id,
            "placa": placa, "posicao": posicao}


def remover(pneu_id: int, km=None, motivo: str = "", usuario: str = "",
            ip: str = "") -> dict:
    """Tira o pneu do veículo e devolve ao estoque."""
    km = _odometro(km)
    _auditar(usuario, "pneu_remover", "pneu:%s" % pneu_id, motivo or "", ip)
    with pglocal.get_conn() as conn, conn.cursor() as cur:
        p = _pneu(cur, pneu_id)
        _exigir_estado(p, "remocao")
        ident = _gravar(cur, pneu_id, "remocao", p["placa_atual"],
                        p["posicao_atual"], km, motivo or None, None, usuario)
        cur.execute("""
            UPDATE pne_pneu SET placa_atual = NULL, posicao_atual = NULL,
                   status = %s, atualizado_em = now() WHERE id = %s""",
            (ESTADO_APOS["remocao"], pneu_id))
    return {"ok": True, "evento": ident, "pneu": pneu_id,
            "de": p["placa_atual"], "posicao": p["posicao_atual"]}


def sucatear(pneu_id: int, motivo_id: int, usuario: str = "",
             ip: str = "") -> dict:
    """Baixa o pneu, com motivo VINDO DA TABELA.

    Motivo digitado vira dez grafias da mesma coisa e nenhum agrupamento
    funciona — e é justamente o agrupamento que responde "por que os pneus
    estão morrendo".
    """
    _auditar(usuario, "pneu_sucatear", "pneu:%s" % pneu_id,
             "motivo:%s" % motivo_id, ip)
    with pglocal.get_conn() as conn, conn.cursor() as cur:
        p = _pneu(cur, pneu_id)
        _exigir_estado(p, "sucata")
        cur.execute("SELECT rotulo FROM pne_motivo "
                    "WHERE id = %s AND especie = 'descarte' AND ativo",
                    (motivo_id,))
        m = cur.fetchone()
        if not m:
            raise MovimentoInvalido(
                "Motivo de descarte inválido ou inativo.")
        ident = _gravar(cur, pneu_id, "sucata", p["placa_atual"],
                        p["posicao_atual"], None, m["rotulo"], None, usuario)
        cur.execute("""
            UPDATE pne_pneu SET placa_atual = NULL, posicao_atual = NULL,
                   status = %s, atualizado_em = now() WHERE id = %s""",
            (ESTADO_APOS["sucata"], pneu_id))
    return {"ok": True, "evento": ident, "pneu": pneu_id,
            "motivo": m["rotulo"]}


def inspecionar(pneu_id: int, sulcos: list, pressao=None, km=None,
                usuario: str = "", ip: str = "") -> dict:
    """Registra uma medição feita por nós.

    QUATRO SULCOS, NA ORDEM (interno, meio interno, meio externo, externo) —
    a mesma ordem do fornecedor, porque é ela que faz o array significar algo e
    é dela que sai o MENOR sulco, que é o que a lei mede.
    """
    vs = [v for v in (sulcos or []) if v is not None]
    if not vs and pressao is None:
        raise MovimentoInvalido("Informe ao menos um sulco ou a pressão.")
    for v in vs:
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise MovimentoInvalido("Sulco inválido.") from None
        # FAIXA FÍSICA DO SULCO: pneu de carga sai de fábrica com 14 a 20 mm e
        # é descartado bem antes de zero. Fora disso é dedo trocado, e um sulco
        # errado vira uma taxa de desgaste errada, que vira uma data de troca.
        if not (0 <= f <= 30):
            raise MovimentoInvalido("Sulco fora da faixa possível (0 a 30 mm).")
    km = _odometro(km)

    _auditar(usuario, "pneu_inspecionar", "pneu:%s" % pneu_id, "", ip)
    with pglocal.get_conn() as conn, conn.cursor() as cur:
        p = _pneu(cur, pneu_id)
        cur.execute("""
            INSERT INTO pne_inspecao
                (pneu_id, medido_em, sulcos_mm, pressao_psi, placa, posicao,
                 km_veiculo, origem, usuario)
            VALUES (%s, now(), %s,%s,%s,%s,%s,'cortex',%s)
            RETURNING id""",
            (pneu_id, sulcos or None, pressao, p["placa_atual"],
             p["posicao_atual"], km, usuario))
        ident = cur.fetchone()["id"]
    return {"ok": True, "inspecao": ident, "pneu": pneu_id}
