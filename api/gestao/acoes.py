"""Planos de ação em 5W2H — o compromisso, e o histórico dele.

O QUE ESTE MÓDULO PROTEGE é a diferença entre uma lista de boas intenções e um
plano de ação. Três regras fazem esse trabalho, e as três já foram erradas em
sistemas de gestão que viraram planilha abandonada:

1. **ATRASO É DERIVADO, NUNCA GRAVADO.** Não existe status 'atrasada' na
   tabela. `_enriquecer()` calcula `atrasada` e `dias_atraso` a cada leitura, a
   partir de `prazo` e `status`. Um status de atraso gravado precisa de rotina
   para virar, e no dia em que a rotina não roda a tela diz que está tudo em
   dia — é a mesma classe do marcador de manutenção preventiva parado em 77.534
   km com o odômetro em 531.970, que fazia o veículo nunca disparar alerta.

2. **PRORROGAR PRAZO DEIXA RASTRO.** Mudar o `prazo` grava um andamento
   dizendo a data antiga e a nova. Sem isso, a ação que foi adiada seis vezes é
   indistinguível da que nasceu ontem, e o acompanhamento perde justamente o
   caso que precisa de atenção. `prorrogacoes` conta isso e vai para a tela.

3. **CONCLUIR EXIGE DATA, E REABRIR A APAGA.** `concluida_em` é carimbado na
   transição para 'concluida' e volta a NULL se a ação for reaberta — senão o
   tempo de ciclo passaria a medir a primeira conclusão de uma tarefa que
   continuou aberta por mais dois meses.

O HISTÓRICO É APPEND-ONLY. Não há função de editar nem de apagar andamento:
andamento que se reescreve deixa de ser prova de que a ação andou.
"""
from __future__ import annotations

from datetime import date

from .. import pglocal
from .comum import (PRIORIDADES, STATUS_ACAO, TITULO_MAX, DadoInvalido, _esq,
                    agora, data_br, escolha, hoje, init_db, inteiro, iso,
                    pessoa, texto, valor_br)

# Lista de colunas NUM LUGAR SÓ. Estava repetida em `listar` e `obter` no
# módulo de modelos do WhatsApp, e acrescentar campo em uma e esquecer da outra
# faria a rota de edição trabalhar com a ação pela metade.
_COLUNAS = """
    a.id, a.reuniao_id, a.o_que, a.por_que, a.como, a.onde, a.quanto,
    a.responsavel_id, a.responsavel_nome, a.prazo, a.area, a.prioridade,
    a.status, a.percentual, a.concluida_em,
    a.criado_por, a.criado_em, a.alterado_por, a.alterado_em,
    coalesce(u.nome, a.responsavel_nome) AS responsavel,
    u.email        AS responsavel_email,
    r.codigo       AS reuniao_codigo,
    r.titulo       AS reuniao_titulo,
    (SELECT count(*) FROM ges_andamentos n WHERE n.acao_id = a.id)::int
                   AS andamentos,
    (SELECT max(n.ts) FROM ges_andamentos n WHERE n.acao_id = a.id)
                   AS ultimo_andamento,
    (SELECT count(*) FROM ges_andamentos n
      WHERE n.acao_id = a.id AND n.texto LIKE 'Prazo alterado%%')::int
                   AS prorrogacoes
"""
_FROM = """
FROM ges_acoes a
LEFT JOIN usuarios     u ON u.id = a.responsavel_id
LEFT JOIN ges_reunioes r ON r.id = a.reuniao_id
"""

ABERTAS = ("aberta", "em_andamento")


def _enriquecer(a: dict, ref: date | None = None) -> dict:
    """Acrescenta o que NÃO se guarda: atraso, urgência e idade.

    `ref` existe para o teste poder fixar a data — e para o relatório por
    e-mail poder perguntar "como estava na segunda?" sem mentir.
    """
    ref = ref or hoje()
    prazo = a.get("prazo")
    if isinstance(prazo, str):
        prazo = date.fromisoformat(prazo)
    aberta = a.get("status") in ABERTAS
    dias = (prazo - ref).days if prazo else None

    a["atrasada"] = bool(aberta and dias is not None and dias < 0)
    a["dias_atraso"] = -dias if a["atrasada"] else 0
    a["dias_para_prazo"] = dias if (aberta and dias is not None and dias >= 0) else None
    a["vence_em_7"] = bool(aberta and dias is not None and 0 <= dias <= 7)

    # Semáforo — DISCRETO, nunca degradê: o design system não tem tom
    # intermediário e um tom intermediário não diz em que estado o dado está.
    if a.get("status") == "concluida":
        a["farol"] = "ok"
    elif a.get("status") == "cancelada":
        a["farol"] = "neutro"
    elif a["atrasada"]:
        a["farol"] = "critico"
    elif a["vence_em_7"]:
        a["farol"] = "atencao"
    else:
        a["farol"] = "ok"

    # "Parada há N dias" usa o último andamento e, na falta dele, a criação:
    # ação sem nenhum andamento não é ação em dia, é ação de que ninguém falou.
    marco = a.get("ultimo_andamento") or a.get("criado_em") or ""
    a["parada_dias"] = None
    if aberta and marco[:10]:
        try:
            a["parada_dias"] = (ref - date.fromisoformat(marco[:10])).days
        except ValueError:
            pass
    if a.get("quanto") is not None:
        a["quanto"] = float(a["quanto"])
    # por último: o cálculo acima precisa do `date`, a rota precisa do texto
    return iso(a, "prazo")


def validar(dados: dict, esquema: str | None = None) -> dict:
    """Recusa na GRAVAÇÃO, não no uso. Erro que só aparece na cobrança
    semanal é erro que ninguém vê a tempo de consertar."""
    d = {
        "o_que": texto(dados.get("o_que"), "o que será feito",
                       maximo=TITULO_MAX, obrigatorio=True),
        "por_que": texto(dados.get("por_que"), "o motivo"),
        "como": texto(dados.get("como"), "como será feito"),
        "onde": texto(dados.get("onde"), "onde", maximo=200),
        "quanto": valor_br(dados.get("quanto"), "o valor"),
        "area": texto(dados.get("area"), "a área", maximo=80),
        "prioridade": escolha(dados.get("prioridade"), PRIORIDADES,
                              "A prioridade", "media"),
        "status": escolha(dados.get("status"), STATUS_ACAO, "O status",
                          "aberta"),
        "percentual": inteiro(dados.get("percentual"), "o percentual",
                              minimo=0, maximo=100, padrao=0),
    }
    d["prazo"] = data_br(dados.get("prazo"), "o prazo", obrigatorio=True)
    d["responsavel_id"], d["responsavel_nome"] = pessoa(
        dados.get("responsavel_id"), dados.get("responsavel_nome"),
        "Responsável", esquema)

    rid = dados.get("reuniao_id")
    d["reuniao_id"] = int(rid) if rid not in (None, "", 0, "0") else None
    if d["reuniao_id"] is not None:
        existe = pglocal.um("SELECT 1 AS x FROM ges_reunioes WHERE id=%s",
                            (d["reuniao_id"],), esquema=_esq(esquema))
        if not existe:
            raise DadoInvalido("A ata escolhida não existe mais.")

    # Coerência entre status e percentual. Não é firula: uma ação 'concluída'
    # com 40% e outra 'aberta' com 100% tornam as duas colunas inúteis, porque
    # o leitor deixa de saber em qual acreditar.
    if d["status"] == "concluida":
        d["percentual"] = 100
    elif d["percentual"] == 100 and d["status"] in ABERTAS:
        raise DadoInvalido(
            "Percentual 100% com a ação ainda aberta. Marque como concluída "
            "ou informe um percentual menor.")
    elif d["status"] == "aberta" and d["percentual"] > 0:
        d["status"] = "em_andamento"      # começou a andar: o status acompanha
    return d


def listar(esquema: str | None = None, *, status: str | None = None,
           responsavel_id: int | None = None, area: str | None = None,
           reuniao_id: int | None = None, atrasadas: bool = False,
           prazo_de=None, prazo_ate=None, busca: str = "",
           limite: int = 500) -> list[dict]:
    """A fila. Ordenada por URGÊNCIA, não por id.

    A ordem é: atrasada primeiro, depois o prazo mais próximo, depois a
    prioridade. Ação encerrada vai para o fim — lista dominada por registro
    encerrado enterra o que precisa de ação, que foi a lição do CRM (135 de
    150 projetos 'Entregue' escondiam os 9 em andamento).
    """
    onde, p = ["1=1"], {}
    if status:
        if status == "abertas":
            onde.append("a.status IN ('aberta','em_andamento')")
        else:
            onde.append("a.status = %(status)s")
            p["status"] = escolha(status, STATUS_ACAO, "O status")
    if responsavel_id:
        onde.append("a.responsavel_id = %(rid)s")
        p["rid"] = int(responsavel_id)
    if area:
        onde.append("a.area = %(area)s")
        p["area"] = area
    if reuniao_id:
        onde.append("a.reuniao_id = %(reu)s")
        p["reu"] = int(reuniao_id)
    if atrasadas:
        onde.append("a.prazo < current_date "
                    "AND a.status IN ('aberta','em_andamento')")
    if prazo_de:
        onde.append("a.prazo >= %(pde)s")
        p["pde"] = data_br(prazo_de, "o prazo inicial")
    if prazo_ate:
        onde.append("a.prazo <= %(pate)s")
        p["pate"] = data_br(prazo_ate, "o prazo final")
    if (busca or "").strip():
        onde.append("(a.o_que ILIKE %(q)s OR a.como ILIKE %(q)s "
                    "OR a.por_que ILIKE %(q)s "
                    "OR coalesce(u.nome, a.responsavel_nome) ILIKE %(q)s)")
        p["q"] = f"%{busca.strip()}%"

    sql = f"""
    SELECT {_COLUNAS} {_FROM}
    WHERE {' AND '.join(onde)}
    ORDER BY
      CASE WHEN a.status IN ('aberta','em_andamento') THEN 0 ELSE 1 END,
      CASE WHEN a.status IN ('aberta','em_andamento')
                AND a.prazo < current_date THEN 0 ELSE 1 END,
      a.prazo,
      CASE a.prioridade WHEN 'critica' THEN 0 WHEN 'alta' THEN 1
                        WHEN 'media' THEN 2 ELSE 3 END,
      a.id DESC
    LIMIT {int(limite)}
    """
    return [_enriquecer(r) for r in pglocal.query(sql, p, esquema=_esq(esquema))]


def contar(esquema: str | None = None, **filtros) -> int:
    """Quantas existem no recorte, sem o LIMIT — é o 'X de Y' do hint.

    Top-N em tabela sem contador vira total falso: era o que fazia o hint de
    Veículos dizer '1.373 veículos' quando os ativos eram 1.414.
    """
    filtros.pop("limite", None)
    return len(listar(esquema, limite=100000, **filtros))


def obter(acao_id: int, esquema: str | None = None) -> dict | None:
    r = pglocal.um(f"SELECT {_COLUNAS} {_FROM} WHERE a.id = %s",
                   (int(acao_id),), esquema=_esq(esquema))
    if not r:
        return None
    r = _enriquecer(r)
    r["historico"] = andamentos(acao_id, esquema)
    return r


def andamentos(acao_id: int, esquema: str | None = None) -> list[dict]:
    return pglocal.query(
        "SELECT id, ts, usuario, texto, status_de, status_para, percentual "
        "FROM ges_andamentos WHERE acao_id=%s ORDER BY ts DESC, id DESC",
        (int(acao_id),), esquema=_esq(esquema))


def _andamento(cur, acao_id: int, usuario: str, texto_: str, *,
               status_de=None, status_para=None, percentual=None) -> None:
    cur.execute(
        "INSERT INTO ges_andamentos"
        "(acao_id, ts, usuario, texto, status_de, status_para, percentual) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (acao_id, agora(), usuario, texto_, status_de, status_para, percentual))


def gravar(dados: dict, *, usuario: str = "", acao_id: int | None = None,
           esquema: str | None = None) -> dict:
    """Cria ou edita. A criação já entra com um andamento de abertura, para
    que `parada_dias` nasça em zero em vez de nulo."""
    init_db(esquema)
    d = validar(dados, esquema)
    ts = agora()
    with pglocal.get_conn(_esq(esquema)) as cx:
        cur = cx.cursor()
        if acao_id:
            ant = pglocal.um(
                "SELECT status, percentual, prazo, o_que, responsavel_id, "
                "       responsavel_nome, concluida_em "
                "FROM ges_acoes WHERE id=%s", (int(acao_id),),
                esquema=_esq(esquema))
            if not ant:
                raise DadoInvalido("Esta ação não existe mais.")

            # concluida_em: carimba ao concluir, LIMPA ao reabrir. Manter o
            # carimbo antigo faria o tempo de ciclo medir a primeira conclusão
            # de uma tarefa que seguiu aberta por mais dois meses.
            concl = ant["concluida_em"]
            if d["status"] == "concluida" and ant["status"] != "concluida":
                concl = ts
            elif d["status"] != "concluida":
                concl = None

            cur.execute("""
                UPDATE ges_acoes SET
                  reuniao_id=%(reuniao_id)s, o_que=%(o_que)s,
                  por_que=%(por_que)s, como=%(como)s, onde=%(onde)s,
                  quanto=%(quanto)s, responsavel_id=%(responsavel_id)s,
                  responsavel_nome=%(responsavel_nome)s, prazo=%(prazo)s,
                  area=%(area)s, prioridade=%(prioridade)s, status=%(status)s,
                  percentual=%(percentual)s, concluida_em=%(concl)s,
                  alterado_por=%(quem)s, alterado_em=%(ts)s
                WHERE id=%(id)s
            """, {**d, "id": int(acao_id), "quem": usuario, "ts": ts,
                  "concl": concl})

            # As mudanças que MERECEM linha no histórico. Não é toda edição:
            # corrigir uma vírgula no "como" não é andamento, e poluir o
            # histórico com isso faz ninguém ler o histórico.
            if d["prazo"] != ant["prazo"]:
                _andamento(cur, int(acao_id), usuario,
                           f"Prazo alterado de {ant['prazo']:%d/%m/%Y} "
                           f"para {d['prazo']:%d/%m/%Y}.")
            if d["status"] != ant["status"] or d["percentual"] != ant["percentual"]:
                _andamento(cur, int(acao_id), usuario, "",
                           status_de=ant["status"], status_para=d["status"],
                           percentual=d["percentual"])
            if (d["responsavel_id"] != ant["responsavel_id"]
                    or d["responsavel_nome"] != ant["responsavel_nome"]):
                _andamento(cur, int(acao_id), usuario,
                           f"Responsável alterado de "
                           f"{ant['responsavel_nome'] or '—'} para "
                           f"{d['responsavel_nome']}.")
            novo_id = int(acao_id)
        else:
            cur.execute("""
                INSERT INTO ges_acoes
                  (reuniao_id, o_que, por_que, como, onde, quanto,
                   responsavel_id, responsavel_nome, prazo, area, prioridade,
                   status, percentual, concluida_em,
                   criado_por, criado_em, alterado_por, alterado_em)
                VALUES
                  (%(reuniao_id)s, %(o_que)s, %(por_que)s, %(como)s, %(onde)s,
                   %(quanto)s, %(responsavel_id)s, %(responsavel_nome)s,
                   %(prazo)s, %(area)s, %(prioridade)s, %(status)s,
                   %(percentual)s, %(concl)s,
                   %(quem)s, %(ts)s, %(quem)s, %(ts)s)
                RETURNING id
            """, {**d, "quem": usuario, "ts": ts,
                  "concl": ts if d["status"] == "concluida" else None})
            novo_id = cur.fetchone()["id"]
            _andamento(cur, novo_id, usuario, "Ação criada.",
                       status_para=d["status"], percentual=d["percentual"])
        cx.commit()
    return obter(novo_id, esquema)


def registrar_andamento(acao_id: int, texto_: str, *, usuario: str = "",
                        status: str | None = None, percentual=None,
                        esquema: str | None = None) -> dict:
    """O caminho curto do acompanhamento: escrever o que andou e, de quebra,
    mexer em status/percentual sem abrir o formulário inteiro.

    Existe separado de `gravar` porque é a operação FREQUENTE — quem acompanha
    faz isto toda semana e edita a ação uma vez. Obrigar o formulário completo
    para dizer "falei com o fornecedor, chega dia 12" é o que faz o histórico
    ficar vazio.
    """
    init_db(esquema)
    ant = pglocal.um("SELECT status, percentual FROM ges_acoes WHERE id=%s",
                     (int(acao_id),), esquema=_esq(esquema))
    if not ant:
        raise DadoInvalido("Esta ação não existe mais.")

    txt = texto(texto_, "o andamento", maximo=5000)
    novo_status = escolha(status, STATUS_ACAO, "O status", ant["status"]) \
        if status else ant["status"]
    novo_pct = (inteiro(percentual, "o percentual", minimo=0, maximo=100,
                        padrao=ant["percentual"])
                if percentual not in (None, "") else ant["percentual"])
    if novo_status == "concluida":
        novo_pct = 100
    elif novo_pct == 100 and novo_status in ABERTAS:
        novo_pct = 99   # aqui NÃO recusa: quem só escreve nota não deve
                        # apanhar de validação. 100% é dito com o status.
    if not txt and novo_status == ant["status"] and novo_pct == ant["percentual"]:
        raise DadoInvalido("Escreva o andamento ou mude o status.")

    ts = agora()
    with pglocal.get_conn(_esq(esquema)) as cx:
        cur = cx.cursor()
        mudou = (novo_status != ant["status"] or novo_pct != ant["percentual"])
        if mudou:
            concl = ts if novo_status == "concluida" else None
            cur.execute(
                "UPDATE ges_acoes SET status=%s, percentual=%s, "
                "concluida_em=%s, alterado_por=%s, alterado_em=%s WHERE id=%s",
                (novo_status, novo_pct, concl, usuario, ts, int(acao_id)))
        _andamento(cur, int(acao_id), usuario, txt,
                   status_de=ant["status"] if mudou else None,
                   status_para=novo_status if mudou else None,
                   percentual=novo_pct if mudou else None)
        cx.commit()
    return obter(acao_id, esquema)


def excluir(acao_id: int, esquema: str | None = None) -> dict | None:
    """Exclusão de verdade, com o registro devolvido para a auditoria.

    Cancelar é o caminho normal (preserva o histórico e continua contando);
    excluir é para a ação criada por engano. Quem chama decide, e a tela
    oferece cancelar primeiro.
    """
    a = obter(acao_id, esquema)
    if not a:
        return None
    pglocal.executar("DELETE FROM ges_acoes WHERE id=%s", (int(acao_id),),
                     esquema=_esq(esquema))
    return a
