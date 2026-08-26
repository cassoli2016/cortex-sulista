# api/contrapartida/servico.py

"""Conciliacao do CT-e de contrapartida do agregado.



Hoje NENHUMA contrapartida e emitida (confirmado pelo usuario em 26/08/2026).

Entao esta tela nao mede cobertura - ela dimensiona a fila, separa quem PODE

emitir de quem NAO PODE, e prepara o cadastro que a emissao vai exigir.



O QUE ELA NAO FAZ, E POR QUE

---------------------------

Nao emite nada. Emissao de CT-e em nome de terceiro exige procuracao vigente,

certificado A1 e enquadramento fiscal definido - e nenhuma dessas tres coisas e

decisao de software. A tela existe para essas decisoes serem tomadas com o

numero na mao.



E nao trata o passivo historico como fila de trabalho: CT-e NAO se emite

retroativo (a SEFAZ recusa data de emissao fora da janela). O acumulado sai

num bloco separado, rotulado como numero para decisao juridica.

"""

from __future__ import annotations



import logging

from datetime import date, datetime, timedelta



from api import db

from api.contrapartida import cadastro
from api.contrapartida.sql import (FROTA_AGR_SQL, PASSIVO_SQL,

                                   POR_AGREGADO_SQL, POR_MES_SQL)



log = logging.getLogger("cortex.contrapartida")



# Rotulos das duas populacoes. Escritos aqui e nao no front porque a diferenca

# e FISCAL, nao de apresentacao: somar as duas produz um passivo falso.

CLASSES = {

    "pj": "PJ — emite CT-e",

    "tac": "TAC (CPF) — não emite CT-e",

    "indefinido": "documento do proprietário indefinido",

}



# O TAC nao e sujeito passivo do CT-e (Lei 11.442): a documentacao dele e

# CIOT + RPA. Isto nao e limitacao da rotina - e do documento.

NOTA_TAC = ("Transportador Autônomo de Cargas não emite CT-e — a documentação "

            "dele é CIOT (Lei 11.442) e RPA. Estes CT-e não entram na fila de "

            "contrapartida por natureza do documento, não por falta de "

            "certificado.")





def _janela(de: str | None, ate: str | None) -> tuple[str, str]:

    hoje = date.today()

    d_ate = date.fromisoformat(ate) if ate else hoje

    d_de = date.fromisoformat(de) if de else (d_ate.replace(day=1)

                                              - timedelta(days=180))

    if d_de > d_ate:

        d_de, d_ate = d_ate, d_de

    return d_de.isoformat(), (d_ate + timedelta(days=1)).isoformat()





def _serial(linhas) -> list[dict]:
    """date -> 'AAAA-MM-DD'. O JSONResponse nao serializa datetime.date e
    devolve 500 - e o teste que so olhava os KPIs nunca chegava na
    serializacao, entao o defeito so apareceu na tela."""
    saida = []
    for r in linhas:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (date, datetime)):
                d[k] = v.isoformat()[:10] if isinstance(v, date) else v.isoformat()
        saida.append(d)
    return saida


def get_contrapartida(de: str | None = None, ate: str | None = None) -> dict:

    d_de, d_ate = _janela(de, ate)

    par = {"de": d_de, "ate": d_ate}

    mes = db.query(POR_MES_SQL, par)

    agreg = db.query(POR_AGREGADO_SQL, par)

    frota = db.query(FROTA_AGR_SQL, {})

    passivo = db.query(PASSIVO_SQL, {"de": "2022-01-01", "ate": d_ate})



    def _soma(linhas, classe, campo):

        return sum(x[campo] for x in linhas if x["classe"] == classe)



    # PRONTIDAO: procuracao vigente + certificado A1 valido + senha no cofre.
    # Sem isto a fila diz "14 mil CT-e a emitir" sem dizer que a emissao ainda
    # nao esta autorizada para ninguem - numero grande sem o que o desarma.
    try:
        pront = cadastro.mapa()
    except Exception as exc:  # noqa: BLE001
        log.warning("cadastro de procuracao/certificado indisponivel: %s", exc)
        pront = {}
    for x in agreg:
        p = pront.get(x["documento"]) or {}
        x["prontidao"] = p.get("prontidao") or {
            "pronto": False, "faltas": ["sem procuração cadastrada",
                                        "sem certificado cadastrado"],
            "alertas": []}

    pj = [x for x in agreg if x["classe"] == "pj"]

    tac = [x for x in agreg if x["classe"] == "tac"]

    indef = [x for x in agreg if x["classe"] == "indefinido"]



    # PENDENCIA CADASTRAL: o que a emissao exige e o cadastro pode nao ter.

    # Descobrir isso na transmissao custa uma rejeicao POR DOCUMENTO - com

    # 3 mil CT-e/mes, e o tipo de erro que para a operacao.

    faltando = [{"documento": x["documento"], "nome": x["nome"],

                 "falta": [c for c, v in (("razão social", x["nome"]),

                                          ("inscrição estadual", x["ie"]),

                                          ("RNTRC", x["rntrc"]),

                                          ("município/UF", x["cidade"]))

                           if not v]}

                for x in pj]

    faltando = [x for x in faltando if x["falta"]]



    return {

        "periodo": {"de": d_de, "ate": d_ate},

        "kpis": {

            "ctes_pj": _soma(mes, "pj", "ctes"),

            "valor_pj": round(_soma(mes, "pj", "valor"), 2),

            "agregados_pj": len(pj),

            "ctes_tac": _soma(mes, "tac", "ctes"),

            "valor_tac": round(_soma(mes, "tac", "valor"), 2),

            "agregados_tac": len(tac),

            "ctes_indefinido": _soma(mes, "indefinido", "ctes"),

            "agregados_indefinido": len(indef),

            "pendencia_cadastral": len(faltando),
            "prontos_para_emitir": sum(1 for x in pj
                                       if (x.get("prontidao") or {}).get("pronto")),

            "emitidas": 0,   # nenhuma contrapartida emitida ate hoje

        },
        "por_mes": _serial(mes),
        "por_agregado": _serial(agreg),
        "frota": _serial(frota),
        "passivo": _serial(passivo),
        "pendencia_cadastral": faltando,

        "classes": CLASSES,

        "avisos": _avisos(pj, tac, indef, faltando, passivo),

        "fonte": {

            "tabela": "conhecimento × veiculo (utilizacaoveiculo='AGR') × cadastro",

            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),

        },

    }





def _br(v: float, casas: int = 2) -> str:
    """Numero em pt-BR. Existe para NAO precisar mexer na string ja montada:
    aplicar replace na frase inteira comeu as virgulas do texto do aviso."""
    inteiro, _, dec = f"{v:,.{casas}f}".partition(".")
    inteiro = inteiro.replace(",", ".")
    return f"{inteiro},{dec}" if dec else inteiro


def _avisos(pj, tac, indef, faltando, passivo) -> list[str]:

    av: list[str] = []

    av.append(

        "Nenhuma contrapartida emitida até hoje: esta tela dimensiona a fila, "

        "não mede cobertura. O número de emitidas é zero por confirmação da "

        "própria operação, não por falta de dado.")

    if tac:

        av.append(f"{len(tac)} dos {len(pj) + len(tac) + len(indef)} agregados "

                  f"do período são pessoa física. " + NOTA_TAC)

    if indef:

        av.append(

            f"{len(indef)} agregados com documento de proprietário fora do "

            "padrão de CNPJ ou CPF: não dá para dizer se emitem CT-e. "

            "Conferir o cadastro do veículo antes de incluí-los em qualquer fila.")

    if faltando:

        quais = ", ".join(f"{x['nome'] or x['documento']} ({', '.join(x['falta'])})"

                          for x in faltando[:4])

        av.append(

            f"{len(faltando)} agregados PJ com cadastro incompleto para emitir: "

            f"{quais}{'...' if len(faltando) > 4 else ''}. Campo faltando vira "

            "rejeição documento a documento na transmissão.")

    # CT-e de centavos quase certamente e documento de AJUSTE (anulacao,
    # complementar), nao prestacao. Se for, nao deveria puxar contrapartida -
    # mas isso e definicao fiscal, nao suposicao minha: a tela conta e
    # pergunta, em vez de filtrar por conta propria e esconder o caso.
    centavos = [x for x in pj if (x.get("valor") or 0) < 1.0]
    if centavos:
        av.append(
            f"{len(centavos)} agregado(s) PJ com CT-e somando menos de R$ 1,00 no "
            "período (há caso de 4 CT-e totalizando R$ 0,04). Documento de "
            "valor simbólico costuma ser anulação ou complementar, não "
            "prestação — se for, não deveria entrar na fila de contrapartida. "
            "Confirmar com a contabilidade antes de emitir para eles.")

    naopronto = [x for x in pj if not (x.get("prontidao") or {}).get("pronto")]
    if naopronto:
        av.append(
            f"{len(naopronto)} dos {len(pj)} agregados PJ ainda não estão "
            "autorizados a emitir: falta procuração vigente, certificado A1 "
            "válido ou a senha dele no cofre. Enquanto isso, a fila é "
            "diagnóstico — nenhum documento pode ser emitido.")

    velho = [x for x in passivo if x["classe"] == "pj"

             and x["ano"] < str(date.today().year)]

    if velho:

        n = sum(x["ctes"] for x in velho)

        v = sum(x["valor"] for x in velho)

        # formata SO o numero. Aplicar replace(",", ".") na frase inteira

        # comeu as virgulas do texto - a mesma armadilha da substituicao em

        # massa que o CLAUDE.md descreve, em miniatura.

        av.append(

            f"Passivo de anos anteriores: {_br(n, 0)} CT-e de agregado PJ, "

            f"R$ {_br(v, 0)} de prestação. CT-e NÃO se emite retroativo (a "

            "SEFAZ recusa data de emissão fora da janela), então isto não é "

            "fila de trabalho — é número para a decisão da contabilidade e do "

            "jurídico.")

    return av

