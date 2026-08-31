"""Gravação da Smartec no banco local do CÓRTEX.

TRÊS DECISÕES QUE MOLDAM ESTE ARQUIVO
=====================================

1. **Converter no limite do módulo.** Data vira `date`, dinheiro vira `float`,
   `Decimal` não sai daqui. É a regra que a Premiação pagou caro para
   aprender: `JSONResponse` só serializa DEPOIS do `try/except` da rota, então
   um `Decimal` que escapa estoura fora de todo tratamento e chega ao
   navegador como 500 em `text/plain`, sem uma pista do campo, da tela ou do
   banco. Aqui o tipo do banco para de importar.

2. **`ON CONFLICT DO UPDATE`, sempre.** Recoletar é o caso NORMAL — o boleto
   muda de situação ao longo do mês e a coleta roda várias vezes por dia.
   Idempotência aqui é requisito, não otimização.

3. **A COLETA MARCA QUEM VIU, E DEPOIS FECHA QUEM NÃO VIU.** A API só devolve
   infração EM ABERTO: a que foi paga ou cuja defesa foi provida simplesmente
   para de vir, sem nenhuma marca. `fechar_ausentes()` roda no fim de uma
   coleta COMPLETA e carimba `sumiu_em` no que não apareceu.

   E ele só roda se a coleta foi completa — este é o ponto delicado. Se a
   varredura falhou no meio (a Smartec caiu, o token expirou), os veículos não
   visitados devolveriam "nenhuma multa" e o fechamento marcaria a frota
   inteira como resolvida. Um erro de rede viraria "parabéns, zeramos as
   multas". Daí `fechar_ausentes` exigir a lista de renavams efetivamente
   consultados e recusar quando a coleta não terminou.
"""
from __future__ import annotations

import json as _json
import logging
from datetime import date, datetime

from .. import pglocal

log = logging.getLogger(__name__)

# O teste redireciona isto para um schema próprio (fixture `esquema_pg`).
ESQUEMA: str | None = None


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


# ───────────────────────────────────────────────────────── conversores
#
# A Smartec manda data em dd/MM/yyyy e às vezes "00/00/0000", que NÃO é uma
# data — é o jeito dela dizer "não há". Virar `None` aqui evita que a tela
# mostre 30/11/0000 ou que o banco recuse a linha inteira por causa de um
# campo acessório.
def d(valor) -> date | None:
    if valor in (None, "", "00/00/0000", "0000-00-00"):
        return None
    if isinstance(valor, date):
        return valor
    txt = str(valor).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(txt[:len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    return None


def dt(valor) -> datetime | None:
    if not valor:
        return None
    txt = str(valor).strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def f(valor) -> float | None:
    """Dinheiro. Devolve None para ausência, e ZERO CONTINUA SENDO ZERO.

    A distinção importa: IPVA de R$ 0,00 é isenção (medido em semirreboque no
    PR) e é um fato; campo ausente é falta de informação. Colapsar os dois faz
    a tela dizer "isento" onde ninguém consultou.
    """
    if valor is None or valor == "":
        return None
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def i(valor) -> int | None:
    if valor is None or valor == "":
        return None
    try:
        return int(float(str(valor).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def s(valor) -> str:
    """Texto, nunca None — as colunas são NOT NULL DEFAULT ''."""
    if valor is None:
        return ""
    return str(valor).strip()


# ───────────────────────────────────────────────────────── trilha
def carga_abrir(recurso: str, esquema: str | None = None) -> int:
    r = pglocal.um(
        "INSERT INTO smt_carga(recurso) VALUES (%s) RETURNING id",
        (recurso,), esquema=_esq(esquema))
    return int(r["id"]) if r else 0


def carga_fechar(carga_id: int, status: str, itens: int = 0,
                 chamadas: int = 0, mensagem: str = "",
                 esquema: str | None = None) -> None:
    if not carga_id:
        return
    pglocal.executar(
        """UPDATE smt_carga SET fim = now(), status = %s, itens = %s,
                  chamadas = %s, mensagem = %s WHERE id = %s""",
        (status, itens, chamadas, mensagem[:2000], carga_id),
        esquema=_esq(esquema))


# ───────────────────────────────────────────────────────── infrações
_INFRACAO_SQL = """
INSERT INTO smt_infracoes(
    identificador, especie, placa, renavam, ait, ait_sne, ait_detran, renainf,
    ait_originaria, renainf_originaria, data_infracao, hora, local_infracao,
    valor_a_pagar, valor_com_desconto, valor_desconto, codigo_municipio,
    municipio, uf, descricao, codigo_infracao, desdobramento, pontuacao,
    codigo_orgao, orgao, orgao_adesao_sne, vencimento, prazo_indicacao,
    data_pesquisa,
    url_penalidade, url_boleto, codigo_boleto, situacao_boleto,
    descricao_boleto, boleto_valor, linha_digitavel, boleto_vencimento,
    boleto_cedente, boleto_desconto_pct, confirmacao_pagamento,
    motorista_nome, motorista_matricula, visto_em, sumiu_em)
VALUES (%(identificador)s, %(especie)s, %(placa)s, %(renavam)s, %(ait)s,
    %(ait_sne)s, %(ait_detran)s, %(renainf)s, %(ait_originaria)s,
    %(renainf_originaria)s, %(data_infracao)s, %(hora)s, %(local_infracao)s,
    %(valor_a_pagar)s, %(valor_com_desconto)s, %(valor_desconto)s,
    %(codigo_municipio)s, %(municipio)s, %(uf)s, %(descricao)s,
    %(codigo_infracao)s, %(desdobramento)s, %(pontuacao)s, %(codigo_orgao)s,
    %(orgao)s, %(orgao_adesao_sne)s, %(vencimento)s, %(prazo_indicacao)s,
    %(data_pesquisa)s,
    %(url_penalidade)s, %(url_boleto)s, %(codigo_boleto)s,
    %(situacao_boleto)s, %(descricao_boleto)s, %(boleto_valor)s,
    %(linha_digitavel)s, %(boleto_vencimento)s, %(boleto_cedente)s,
    %(boleto_desconto_pct)s, %(confirmacao_pagamento)s, %(motorista_nome)s,
    %(motorista_matricula)s, now(), NULL)
ON CONFLICT (identificador) DO UPDATE SET
    especie = EXCLUDED.especie,
    placa = EXCLUDED.placa,
    valor_a_pagar = EXCLUDED.valor_a_pagar,
    valor_com_desconto = EXCLUDED.valor_com_desconto,
    valor_desconto = EXCLUDED.valor_desconto,
    pontuacao = EXCLUDED.pontuacao,
    vencimento = EXCLUDED.vencimento,
    prazo_indicacao = EXCLUDED.prazo_indicacao,
    data_pesquisa = EXCLUDED.data_pesquisa,
    url_penalidade = EXCLUDED.url_penalidade,
    url_boleto = EXCLUDED.url_boleto,
    codigo_boleto = EXCLUDED.codigo_boleto,
    situacao_boleto = EXCLUDED.situacao_boleto,
    descricao_boleto = EXCLUDED.descricao_boleto,
    boleto_valor = EXCLUDED.boleto_valor,
    linha_digitavel = EXCLUDED.linha_digitavel,
    boleto_vencimento = EXCLUDED.boleto_vencimento,
    boleto_cedente = EXCLUDED.boleto_cedente,
    boleto_desconto_pct = EXCLUDED.boleto_desconto_pct,
    confirmacao_pagamento = EXCLUDED.confirmacao_pagamento,
    motorista_nome = EXCLUDED.motorista_nome,
    motorista_matricula = EXCLUDED.motorista_matricula,
    visto_em = now(),
    -- REABERTURA: a linha voltou a aparecer na coleta, então ela não estava
    -- resolvida. Sem este NULL, uma multa que sumiu por instabilidade da API
    -- ficaria marcada como resolvida para sempre, mesmo voltando no dia
    -- seguinte.
    sumiu_em = NULL
"""


def _linha_infracao(m: dict, especie: str) -> dict:
    return {
        "identificador": s(m.get("IDENTIFICADOR_SMARTEC")),
        "especie": especie,
        "placa": s(m.get("PLACA")).upper(),
        "renavam": s(m.get("RENAVAM")).lstrip("0"),
        "ait": s(m.get("AIT")).upper(),
        "ait_sne": s(m.get("AIT_SNE")).upper(),
        "ait_detran": s(m.get("AIT_DETRAN")).upper(),
        "renainf": s(m.get("RENAINF")),
        "ait_originaria": s(m.get("AIT_ORIGINARIA")).upper(),
        "renainf_originaria": s(m.get("RENAINF_ORIGINARIA")),
        "data_infracao": d(m.get("DATA_INFRACAO")),
        "hora": s(m.get("Hora")),
        # O campo muda de nome entre os dois tipos: MULTAS manda
        # LOCAL_INFRACAO e NOTIFICACOES manda LOCAL. Ler só um deixaria metade
        # das linhas sem o local, sem erro nenhum aparecer.
        "local_infracao": s(m.get("LOCAL_INFRACAO") or m.get("LOCAL")),
        "valor_a_pagar": f(m.get("VALOR_A_PAGAR")),
        "valor_com_desconto": f(m.get("VALOR_COM_DESCONTO")),
        "valor_desconto": f(m.get("VALOR_DESCONTO")),
        "codigo_municipio": s(m.get("CODIGO_MUNICIPIO")),
        "municipio": s(m.get("MUNICIPIO")),
        "uf": s(m.get("UF")),
        "descricao": s(m.get("DESCRICAO")),
        "codigo_infracao": s(m.get("CODIGO_INFRACAO") or m.get("CodigoInfracao")),
        # NORMALIZADO PARA '0' QUANDO VAZIO, e isso é o que faz o catálogo
        # do CTB casar. O catálogo chaveia pelo código CONCATENADO
        # (`CODIGO_DESDOBRAMENTO` = 7455 + 0 = "74550"); a infração manda os
        # dois separados — e a MULTA manda "0" enquanto a NOTIFICAÇÃO manda
        # string vazia para a mesma infração. Sem normalizar, metade das
        # linhas não casaria e a gravidade sairia nula só nelas.
        "desdobramento": s(m.get("DESDOBRAMENTO")) or "0",
        "pontuacao": i(m.get("PONTUACAO")),
        "codigo_orgao": s(m.get("CODIGO_ORGAO")),
        # A notificação chama o mesmo campo de ORGAO_AUTUADOR. Ler só um
        # deixou as 483 notificações com órgão VAZIO, sem erro nenhum.
        "orgao": s(m.get("ORGAO") or m.get("ORGAO_AUTUADOR")),
        "orgao_adesao_sne": i(m.get("ORGAO_ADESAO_SNE")),
        "vencimento": d(m.get("VENCIMENTO_INFRACAO") or m.get("VENCIMENTO")),
        "prazo_indicacao": d(m.get("PRAZO_INDICACAO")),
        "data_pesquisa": d(m.get("DATA_PESQUISA")),
        "url_penalidade": s(m.get("PENALIDADE") or m.get("NOTIFICACAO")),
        "url_boleto": s(m.get("Boleto")),
        "codigo_boleto": i(m.get("CODIGO_BOLETO")),
        "situacao_boleto": s(m.get("SITUACAO_BOLETO")),
        "descricao_boleto": s(m.get("DESCRICAO_BOLETO")),
        "boleto_valor": f(m.get("BOLETO_VALOR")),
        "linha_digitavel": s(m.get("LINHA_DIGITAVEL")),
        "boleto_vencimento": d(m.get("BOLETO_VENCIMENTO")),
        "boleto_cedente": s(m.get("BOLETO_CEDENTE")),
        "boleto_desconto_pct": f(m.get("BOLETO_PORCENTAGEM_DESCONTO")),
        "confirmacao_pagamento": i(m.get("CONFIRMACAO_PAGAMENTO")),
        "motorista_nome": s(m.get("MOTORISTA_NOME")),
        "motorista_matricula": s(m.get("MOTORISTA_MATRICULA")),
    }


def gravar_infracoes(itens: list[dict], especie: str,
                     esquema: str | None = None) -> int:
    """Grava multas ou notificações. Devolve quantas linhas entraram.

    Registro SEM `IDENTIFICADOR_SMARTEC` é DESCARTADO e contado, nunca
    inventado: sem a chave não há como deduplicar, e gerar uma faria a mesma
    infração entrar de novo a cada coleta. Foi o modo de falha da RasterJOR ao
    contrário — lá o UNIQUE sobre coluna nula não restringia nada.
    """
    n = 0
    sem_chave = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for m in itens or []:
            linha = _linha_infracao(m, especie)
            if not linha["identificador"]:
                sem_chave += 1
                continue
            cx.execute(_INFRACAO_SQL, linha)
            n += 1
    if sem_chave:
        log.warning("smartec: %d %s sem IDENTIFICADOR_SMARTEC, descartadas",
                    sem_chave, especie)
    return n


def fechar_ausentes(especie: str, renavams_consultados: list[str],
                    coleta_completa: bool, inicio, esquema: str | None = None) -> int:
    """Carimba `sumiu_em` no que não veio nesta coleta.

    DUAS TRAVAS, e as duas nasceram de defeito.

    1. RECUSA SE A COLETA NÃO FOI COMPLETA. A API só devolve o que está em
       aberto, então "não veio" é o sinal de resolvido — mas uma varredura
       interrompida no meio também produz "não veio" para todo veículo não
       visitado. Sem esta trava, um timeout de rede viraria "parabéns,
       zeramos as multas".

    2. A FRONTEIRA É O INÍCIO DA COLETA, não uma janela fixa. A primeira
       versão usava `visto_em < now() - interval '1 minute'`, e isso é um bug
       de relógio esperando acontecer: a varredura de notificações faz 160
       chamadas, e no dia em que a Smartec ficar lenta e ela passar de um
       minuto, as infrações gravadas no COMEÇO da própria coleta ficariam com
       `visto_em` mais velho que a janela e seriam fechadas — pela coleta que
       acabou de vê-las. Comparar contra o instante em que a passagem começou
       não tem esse modo de falha, seja ela de 5 segundos ou de meia hora.
    """
    if not coleta_completa:
        log.info("smartec: coleta incompleta de %s — nada foi fechado", especie)
        return 0
    if not renavams_consultados or inicio is None:
        return 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        cur = cx.execute(
            """UPDATE smt_infracoes SET sumiu_em = now()
                WHERE especie = %s AND sumiu_em IS NULL
                  AND renavam = ANY(%s)
                  AND visto_em < %s""",
            (especie, list(renavams_consultados), inicio))
        return cur.rowcount or 0


# ───────────────────────────────────────────────────────── veículos
def gravar_veiculos(itens: list[dict], esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for v in itens or []:
            rnv = s(v.get("RENAVAM") or v.get("Renavam")).lstrip("0")
            if not rnv:
                continue
            cx.execute("""
                INSERT INTO smt_veiculos(renavam, placa, frota, prefixo,
                    chassi, tipo, marca, ano_modelo, ano_fabricacao, cor, uf,
                    visto_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (renavam) DO UPDATE SET
                    placa = EXCLUDED.placa, frota = EXCLUDED.frota,
                    prefixo = CASE WHEN EXCLUDED.prefixo <> ''
                                   THEN EXCLUDED.prefixo
                                   ELSE smt_veiculos.prefixo END,
                    chassi = EXCLUDED.chassi, tipo = EXCLUDED.tipo,
                    marca = EXCLUDED.marca, ano_modelo = EXCLUDED.ano_modelo,
                    ano_fabricacao = EXCLUDED.ano_fabricacao,
                    cor = EXCLUDED.cor, uf = EXCLUDED.uf, visto_em = now()
            """, (rnv,
                  s(v.get("PLACA") or v.get("Placa")).upper(),
                  s(v.get("FROTA") or v.get("Frota")),
                  s(v.get("PREFIXO") or v.get("Prefixo")),
                  s(v.get("CHASSI")), s(v.get("TIPO")), s(v.get("MARCA")),
                  i(v.get("ANO_MODELO")), i(v.get("ANO_FABRICACAO")),
                  s(v.get("COR")), s(v.get("UF") or v.get("Uf")).upper()))
            n += 1
    return n


# ───────────────────────────────────────────────────────── licenças
def gravar_licencas(itens: list[dict], esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for v in itens or []:
            rnv = s(v.get("Renavam")).lstrip("0")
            if not rnv:
                continue
            cx.execute("""
                INSERT INTO smt_licencas(renavam, placa, frota, cronotacografo,
                    emtu, csv, pp_civ, pp_cipp_ctpp, visto_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (renavam) DO UPDATE SET
                    placa = EXCLUDED.placa, frota = EXCLUDED.frota,
                    cronotacografo = EXCLUDED.cronotacografo,
                    emtu = EXCLUDED.emtu, csv = EXCLUDED.csv,
                    pp_civ = EXCLUDED.pp_civ,
                    pp_cipp_ctpp = EXCLUDED.pp_cipp_ctpp, visto_em = now()
            """, (rnv, s(v.get("Placa")).upper(), s(v.get("Frota")),
                  d(v.get("Cronotacografo")), d(v.get("Emtu")),
                  d(v.get("Csv")), d(v.get("PpCiv")), d(v.get("PpCippCtpp"))))
            n += 1
    return n


def gravar_licenciamento_calendario(itens: list[dict],
                                    esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for v in itens or []:
            rnv = s(v.get("RENAVAM")).lstrip("0")
            if not rnv:
                continue
            cx.execute("""
                INSERT INTO smt_licenciamento(renavam, placa, uf, tipo, mes,
                       visto_em)
                VALUES (%s,%s,%s,%s,%s, now())
                ON CONFLICT (renavam) DO UPDATE SET
                    placa = EXCLUDED.placa, uf = EXCLUDED.uf,
                    tipo = EXCLUDED.tipo, mes = EXCLUDED.mes, visto_em = now()
            """, (rnv, s(v.get("PLACA")).upper(), s(v.get("UF")).upper(),
                  s(v.get("TIPO")), i(v.get("Mes"))))
            n += 1
    return n


def gravar_licenciamento_valor(itens: list[dict],
                               esquema: str | None = None) -> int:
    """Só a TAXA. Não toca em `mes`, que vem do calendário.

    Um UPSERT que zerasse `mes` aqui apagaria o calendário a cada consulta de
    valor — o campo não vem nesta resposta, e "não veio" não é "é nulo".
    """
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for v in itens or []:
            rnv = s(v.get("Renavam")).lstrip("0")
            if not rnv:
                continue
            cx.execute("""
                INSERT INTO smt_licenciamento(renavam, placa, uf, valor_taxa,
                       guia, linha_digitavel, guia_vencimento, cedente,
                       data_pesquisa, visto_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (renavam) DO UPDATE SET
                    valor_taxa = EXCLUDED.valor_taxa, guia = EXCLUDED.guia,
                    linha_digitavel = EXCLUDED.linha_digitavel,
                    guia_vencimento = EXCLUDED.guia_vencimento,
                    cedente = EXCLUDED.cedente,
                    data_pesquisa = EXCLUDED.data_pesquisa, visto_em = now()
            """, (rnv, s(v.get("Placa")).upper(), s(v.get("Uf")).upper(),
                  f(v.get("Valor")), s(v.get("Guia")),
                  s(v.get("LINHA_DIGITAVEL")), d(v.get("GUIA_VENCIMENTO")),
                  s(v.get("Cedente")), d(v.get("DATA_PESQUISA"))))
            n += 1
    return n


def gravar_ipva(itens: list[dict], esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for v in itens or []:
            rnv = s(v.get("RENAVAM")).lstrip("0")
            if not rnv:
                continue
            cx.execute("""
                INSERT INTO smt_licenciamento(renavam, placa, ipva_valor,
                       data_pesquisa, visto_em)
                VALUES (%s,%s,%s,%s, now())
                ON CONFLICT (renavam) DO UPDATE SET
                    ipva_valor = EXCLUDED.ipva_valor, visto_em = now()
            """, (rnv, s(v.get("PLACA")).upper(), f(v.get("VALOR")),
                  d(v.get("DATA_PESQUISA"))))
            n += 1
    return n


# ───────────────────────────────────────────────────────── restrições
def gravar_restricoes(renavam: str, placa: str, resp: dict,
                      esquema: str | None = None) -> int:
    if not renavam or not isinstance(resp, dict):
        return 0
    resumo = s(resp.get("Restricoes"))
    # "NADA CONSTA" é resposta boa e precisa ser distinguível de resposta
    # vazia: a primeira significa que se consultou e não há; a segunda, que
    # não se sabe.
    tem = bool(resumo) and resumo.upper() not in ("NADA CONSTA", "")
    detalhe = {k: v for k, v in resp.items()
               if k in ("DetranRestricoes", "RenajudRestricoes",
                        "SenatranRestricoes")}
    if any(detalhe.values()):
        tem = True
    pglocal.executar("""
        INSERT INTO smt_restricoes(renavam, placa, resumo, comunicacao_venda,
               agente_financeiro, detalhe, tem_restricao, data_pesquisa,
               visto_em)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
        ON CONFLICT (renavam) DO UPDATE SET
            placa = EXCLUDED.placa, resumo = EXCLUDED.resumo,
            comunicacao_venda = EXCLUDED.comunicacao_venda,
            agente_financeiro = EXCLUDED.agente_financeiro,
            detalhe = EXCLUDED.detalhe,
            tem_restricao = EXCLUDED.tem_restricao, visto_em = now()
    """, (s(renavam).lstrip("0"), s(placa).upper(), resumo,
          s(resp.get("ComunicacaoVenda")), s(resp.get("AgenteFinanceiro")),
          _json.dumps(detalhe, ensure_ascii=False), tem,
          d(resp.get("DataInclusao"))), esquema=_esq(esquema))
    return 1


# ───────────────────────────────────────────────────────── acessos
def gravar_acessos(itens: list[dict], servico: str,
                   esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for a in itens or []:
            cnpj = "".join(ch for ch in s(a.get("CNPJ")) if ch.isdigit())
            if not cnpj:
                continue
            cx.execute("""
                INSERT INTO smt_acessos(servico, cnpj, empresa, codigo,
                       situacao, observacao, data_expiracao, atualizado_em,
                       visto_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (servico, cnpj) DO UPDATE SET
                    empresa = EXCLUDED.empresa, codigo = EXCLUDED.codigo,
                    situacao = EXCLUDED.situacao,
                    observacao = EXCLUDED.observacao,
                    data_expiracao = EXCLUDED.data_expiracao,
                    atualizado_em = EXCLUDED.atualizado_em, visto_em = now()
            """, (servico, cnpj, s(a.get("EMPRESA")), i(a.get("CODIGO")),
                  s(a.get("DESCRICAO") or a.get("STATUS")),
                  s(a.get("OBSERVACAO")), d(a.get("DATA_EXPIRACAO_ACESSO")),
                  dt(a.get("ULTIMA_ATUALIZACAO_EM"))))
            n += 1
    return n


# ───────────────────────────────────────────────────────── ANTT
def gravar_antt(itens: list[dict], esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for a in itens or []:
            ait = s(a.get("AIT")).upper()
            if not ait:
                continue
            cx.execute("""
                INSERT INTO smt_antt(ait, processo, data_infracao, codigo,
                       tipo, descricao, placa, situacao, impeditiva,
                       data_notificacao, local_infracao, valor, vencimento,
                       detalhe, visto_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (ait) DO UPDATE SET
                    processo = EXCLUDED.processo,
                    situacao = EXCLUDED.situacao,
                    impeditiva = EXCLUDED.impeditiva,
                    data_notificacao = EXCLUDED.data_notificacao,
                    valor = EXCLUDED.valor, vencimento = EXCLUDED.vencimento,
                    detalhe = EXCLUDED.detalhe, visto_em = now()
            """, (ait, s(a.get("PROCESSO")), d(a.get("DATA_INFRACAO")),
                  s(a.get("CODIGO")), s(a.get("TIPO")), s(a.get("DESCRICAO")),
                  s(a.get("PLACA")).upper(), s(a.get("SITUACAO")),
                  i(a.get("IMPEDITIVA")), d(a.get("DATA_NOTIFICACAO")),
                  s(a.get("LOCAL")), f(a.get("VALOR")),
                  d(a.get("VENCIMENTO")),
                  _json.dumps(a, ensure_ascii=False)))
            n += 1
    return n


# ───────────────────────────────────────────────────────── catálogos
def gravar_infracoes_ctb(itens: list[dict], esquema: str | None = None) -> int:
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for c in itens or []:
            cod = s(c.get("CODIGO"))
            if not cod:
                continue
            cx.execute("""
                INSERT INTO smt_infracoes_ctb(codigo, desdobramento, infracao,
                       responsavel, valor, orgao, artigo, pontos, gravidade,
                       atualizado_em, visto_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (codigo, desdobramento) DO UPDATE SET
                    infracao = EXCLUDED.infracao,
                    responsavel = EXCLUDED.responsavel,
                    valor = EXCLUDED.valor, orgao = EXCLUDED.orgao,
                    artigo = EXCLUDED.artigo, pontos = EXCLUDED.pontos,
                    gravidade = EXCLUDED.gravidade,
                    atualizado_em = EXCLUDED.atualizado_em, visto_em = now()
            """, (cod, s(c.get("CODIGO_DESDOBRAMENTO")), s(c.get("INFRACAO")),
                  s(c.get("RESPONSAVEL")), f(c.get("VALOR")),
                  s(c.get("ORGAO")), s(c.get("ARTIGO")), i(c.get("PONTOS")),
                  s(c.get("GRAVIDADE")), d(c.get("DATA_ATUALIZACAO"))))
            n += 1
    return n


def gravar_orgaos(itens: list[dict], sne: list[dict] | None = None,
                  esquema: str | None = None) -> int:
    """Grava o catálogo de órgãos e, se vier, a adesão ao SNE.

    Os dois recursos são chamadas diferentes que descrevem a MESMA entidade —
    juntá-los aqui evita uma tabela a mais e faz a coluna `adeso_sne` viver ao
    lado do nome do órgão, que é onde a tela precisa dela.
    """
    adesao = {}
    for a in sne or []:
        adesao[s(a.get("ORGAO_CODE"))] = (i(a.get("ADESO")),
                                          i(a.get("INDICACAO_ONLINE")))
    n = 0
    with pglocal.get_conn(_esq(esquema)) as cx:
        for o in itens or []:
            cod = s(o.get("CODIGO"))
            if not cod:
                continue
            ad, ind = adesao.get(cod, (None, None))
            cx.execute("""
                INSERT INTO smt_orgaos(codigo, orgao, uf, observacao,
                       adeso_sne, indicacao_online, visto_em)
                VALUES (%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (codigo) DO UPDATE SET
                    orgao = EXCLUDED.orgao, uf = EXCLUDED.uf,
                    observacao = EXCLUDED.observacao,
                    adeso_sne = COALESCE(EXCLUDED.adeso_sne,
                                         smt_orgaos.adeso_sne),
                    indicacao_online = COALESCE(EXCLUDED.indicacao_online,
                                                smt_orgaos.indicacao_online),
                    visto_em = now()
            """, (cod, s(o.get("ORGAO")), s(o.get("UF")).upper(),
                  s(o.get("OBS")), ad, ind))
            n += 1
    return n
