# -*- coding: utf-8 -*-
"""O CATÁLOGO DE CAMPOS do cadastro de equipamentos, e quem ganha de quem.

ESTE ARQUIVO É O CONTRATO DO MÓDULO
===================================
Todo o resto — consolidação, tela, coleta, conferência — lê daqui. Um campo
novo se acrescenta em UM lugar e aparece nos quatro; e a precedência, que é a
regra mais fácil de espalhar por engano, existe uma vez só.

A PRECEDÊNCIA, E POR QUE ELA É ASSIM
====================================
Para cada campo há uma ordem de fontes, e vence a PRIMEIRA que tiver valor:

    manual  >  apibrasil.*  >  smartec  >  erp

1. **`manual` sempre primeiro.** É o que faz o cadastro ser do CÓRTEX e não um
   espelho: sem isso a próxima coleta desfaz a correção, e quem corrigiu
   aprende numa semana que corrigir não adianta.
2. **Detran (`apibrasil`) antes do ERP** nos campos que o Detran é o dono:
   chassi, renavam, situação, restrição. O ERP tem esses campos preenchidos a
   ~100%, mas preenchido é uma coisa e CORRETO é outra — quem digitou o chassi
   no AVA foi uma pessoa, e o Detran é a fonte que decide.
3. **ERP primeiro no que é NOSSO**: vínculo, filial, número de frota,
   capacidade contratada. O Detran não sabe se um veículo é agregado ou
   terceiro; isso é fato da operação, não do documento.

O CAMPO `origem` GRAVA QUEM VENCEU. Não é auditoria decorativa: é o que torna
a saída do Avacorp MENSURÁVEL. "O que quebra se o AVA sair amanhã?" vira uma
consulta — `SELECT count(*) ... WHERE origem->>'marca' = 'erp'` — em vez de
uma leitura de código. Sem instrumento, independência do ERP seria uma
afirmação, e afirmação sobrevive ao instrumento (a lição do 1.0.0).

O QUE `so_erp` MARCA
====================
Os campos que HOJE só o ERP sabe responder. São a lista de pendências da
independência: enquanto houver campo `so_erp=True` em uso, desligar o AVA
apaga esse campo do cadastro. `pendencias_da_independencia()` devolve essa
lista, e é ela que a tela mostra — não como aviso genérico, mas nomeando os
campos.
"""
from __future__ import annotations

# As fontes, na ordem GERAL de força. Fonte que não aparece aqui não entra na
# consolidação, mesmo que grave em `eqp_fonte` — evita que uma coleta
# experimental altere o cadastro sem alguém decidir.
FONTES = ("manual", "apibrasil.dados", "apibrasil.crlv", "apibrasil.fipe",
          "apibrasil.seguranca", "smartec", "erp")

#: Rótulo curto de cada fonte, para a tela dizer de onde veio o número.
ROTULO_FONTE = {
    "manual": "corrigido à mão",
    "apibrasil.dados": "Detran (APIBrasil)",
    "apibrasil.crlv": "CRLV (APIBrasil)",
    "apibrasil.fipe": "FIPE (APIBrasil)",
    "apibrasil.seguranca": "Segurança veicular (APIBrasil)",
    "smartec": "Smartec",
    "erp": "ERP (Avacorp)",
}


def _c(nome, rotulo, tipo, prec, *, grupo, so_erp=False, ajuda=""):
    return {"nome": nome, "rotulo": rotulo, "tipo": tipo, "grupo": grupo,
            "precedencia": ("manual", *prec), "so_erp": so_erp,
            "ajuda": ajuda}


# ─────────────────────────────────────────────────────────────── o catálogo
#
# `tipo` é o que a consolidação usa para converter o texto de `eqp_edicao` e o
# JSON das fontes para a coluna: texto | inteiro | decimal | data | booleano |
# json. Conversão num lugar só, onde o erro tem mensagem.
CAMPOS: tuple[dict, ...] = (
    # ---- identidade: o Detran é o dono, o ERP é o que temos hoje ----------
    _c("renavam", "RENAVAM", "texto", ("apibrasil.dados", "smartec", "erp"),
       grupo="Identidade"),
    _c("chassi", "Chassi", "texto", ("apibrasil.dados", "smartec", "erp"),
       grupo="Identidade",
       ajuda="O Detran decide. O ERP tem 98–100% preenchido, mas preenchido "
             "não é conferido — divergência aqui é erro de digitação no AVA."),
    _c("numero_motor", "Número do motor", "texto",
       ("apibrasil.dados", "erp"), grupo="Identidade"),
    _c("placa_anterior", "Placa anterior", "texto",
       ("apibrasil.dados", "erp"), grupo="Identidade",
       ajuda="A pré-Mercosul. É ela que explica os números de frota "
             "'repetidos' do ERP: o mesmo veículo cadastrado duas vezes."),

    # ---- o que o equipamento é -------------------------------------------
    # DERIVADA, e mesmo assim precisa declarar a fonte que a deriva.
    #
    # Ela nasceu com precedência vazia — "é nossa, não vem de fonte nenhuma" —
    # e o resultado foi `categoria` NULA nas 1.446 linhas, com o cadastro
    # inteiro parecendo certo: `erp.ler()` calculava o valor, gravava em
    # `eqp_fonte`, e a consolidação o descartava porque `erp` não estava na
    # lista. Nenhum erro, nenhum log — só uma coluna vazia.
    #
    # A lição, que vale para todo campo derivado: derivado descreve COMO o
    # valor é calculado, não DE QUEM ele vem. Quem o calcula é uma fonte como
    # qualquer outra, e precisa estar aqui.
    # `apibrasil.dados` NÃO entra aqui, ainda que a `especie` do Detran seja o
    # domínio natural para isto: nenhum candidato de `coleta._CANDIDATOS`
    # produz `categoria` hoje, e declarar uma fonte que nunca preenche o campo
    # é mentira no contrato — a tela diria que o Detran opina sobre algo que
    # ele nunca respondeu. Entra no dia em que o de-para for medido.
    _c("categoria", "Categoria", "texto", ("erp",), grupo="Classificação",
       so_erp=True,
       ajuda="Nossa: tração ou implemento. Sai da flag `tracao` do tipo do "
             "ERP — evidência escrita, não palpite. É ela que impede somar "
             "numa média a idade da tração com a do implemento (6,9 contra "
             "12,9 anos)."),
    _c("tipo", "Tipo", "texto", ("apibrasil.dados", "smartec", "erp"),
       grupo="Classificação"),
    _c("especie", "Espécie", "texto", ("apibrasil.dados", "erp"),
       grupo="Classificação"),
    _c("carroceria", "Carroceria", "texto", ("apibrasil.dados", "erp"),
       grupo="Classificação"),

    # ---- modelo -----------------------------------------------------------
    _c("marca", "Marca", "texto", ("apibrasil.dados", "smartec", "erp"),
       grupo="Modelo"),
    _c("modelo", "Modelo", "texto", ("apibrasil.dados", "erp"),
       grupo="Modelo"),
    _c("versao", "Versão", "texto", ("apibrasil.dados",), grupo="Modelo",
       ajuda="Só a APIBrasil tem. O ERP guarda o modelo sem a versão, e é a "
             "versão que separa dois caminhões de mesmo modelo e preços "
             "muito diferentes."),
    _c("ano_fabricacao", "Ano de fabricação", "inteiro",
       ("apibrasil.dados", "smartec", "erp"), grupo="Modelo"),
    _c("ano_modelo", "Ano do modelo", "inteiro",
       ("apibrasil.dados", "smartec", "erp"), grupo="Modelo"),
    _c("cor", "Cor", "texto", ("apibrasil.dados", "smartec", "erp"),
       grupo="Modelo",
       ajuda="No ERP o campo `corcabine` está VAZIO em 100% da frota; a "
             "Smartec preenche 302 próprios. Para o resto, só o Detran."),
    _c("combustivel", "Combustível", "texto", ("apibrasil.dados", "erp"),
       grupo="Modelo"),
    _c("potencia_cv", "Potência (cv)", "inteiro", ("apibrasil.dados",),
       grupo="Modelo"),
    _c("cilindrada", "Cilindrada", "inteiro", ("apibrasil.dados",),
       grupo="Modelo"),

    # ---- capacidade: unidade de ORIGEM, quilo e litro ---------------------
    _c("tara_kg", "Tara (kg)", "inteiro", ("apibrasil.dados", "erp"),
       grupo="Capacidade"),
    _c("capacidade_carga_kg", "Capacidade de carga (kg)", "inteiro",
       ("apibrasil.dados", "erp"), grupo="Capacidade"),
    _c("capacidade_m3", "Capacidade (m³)", "decimal", ("erp",),
       grupo="Capacidade", so_erp=True,
       ajuda="Cubagem é fato do implemento como a Sulista o usa, não do "
             "documento. O Detran não tem."),
    _c("capacidade_tanque_l", "Tanque (L)", "inteiro", ("erp",),
       grupo="Capacidade", so_erp=True),
    _c("pbt_kg", "Peso bruto total (kg)", "inteiro", ("apibrasil.dados",),
       grupo="Capacidade"),
    _c("cmt_kg", "Capacidade máxima de tração (kg)", "inteiro",
       ("apibrasil.dados",), grupo="Capacidade"),
    _c("eixos", "Eixos", "inteiro", ("apibrasil.dados", "erp"),
       grupo="Capacidade",
       ajuda="Decide o piso ANTT e a tarifa de pedágio. Errado aqui, erram "
             "os dois."),

    # ---- emplacamento -----------------------------------------------------
    _c("uf", "UF", "texto", ("apibrasil.dados", "smartec", "erp"),
       grupo="Emplacamento"),
    _c("municipio", "Município", "texto", ("apibrasil.dados", "erp"),
       grupo="Emplacamento"),

    # ---- propriedade: fato da OPERAÇÃO, o ERP na frente -------------------
    _c("vinculo", "Vínculo", "texto", ("erp",), grupo="Propriedade",
       so_erp=True,
       ajuda="próprio, agregado ou terceiro. O Detran não sabe — isso é "
             "contrato, não documento. É o campo que mais dói perder quando "
             "o ERP sair, e o primeiro que precisa de cadastro próprio."),
    _c("proprietario_doc", "CPF/CNPJ do proprietário", "texto",
       ("apibrasil.dados", "erp"), grupo="Propriedade"),
    _c("proprietario_nome", "Proprietário", "texto",
       ("apibrasil.dados", "erp"), grupo="Propriedade"),

    # ---- situação documental: SÓ o Detran -------------------------------
    _c("situacao", "Situação no Detran", "texto",
       ("apibrasil.crlv", "apibrasil.dados"), grupo="Documentação"),
    _c("crlv_exercicio", "Exercício do CRLV", "inteiro",
       ("apibrasil.crlv",), grupo="Documentação"),
    _c("crlv_vencimento", "Vencimento do licenciamento", "data",
       ("apibrasil.crlv", "smartec"), grupo="Documentação"),
    _c("licenciado", "Licenciado", "booleano",
       ("apibrasil.crlv", "smartec"), grupo="Documentação"),
    _c("tem_restricao", "Tem restrição", "booleano",
       ("apibrasil.seguranca", "apibrasil.crlv", "smartec"),
       grupo="Documentação",
       ajuda="NULL é 'não consultado', e é diferente de false. Não-sei nunca "
             "é pintado de verde."),
    _c("restricoes", "Restrições", "json",
       ("apibrasil.seguranca", "apibrasil.crlv", "smartec"),
       grupo="Documentação"),

    # ---- valor ------------------------------------------------------------
    _c("fipe_codigo", "Código FIPE", "texto", ("apibrasil.fipe",),
       grupo="Valor"),
    _c("fipe_valor", "Valor FIPE", "decimal", ("apibrasil.fipe", "erp"),
       grupo="Valor",
       ajuda="No ERP existe em 51% dos próprios e em 0% de agregado e "
             "terceiro — e sem mês de referência, o que o torna um número "
             "sem data."),
    _c("fipe_referencia", "Mês de referência FIPE", "texto",
       ("apibrasil.fipe",), grupo="Valor",
       ajuda="Valor de mercado sem o mês é número sem data. Por isso o "
             "valor do ERP, que não tem referência, perde para o da FIPE."),

    # ---- estado operacional ----------------------------------------------
    _c("ativo", "Ativo", "booleano", ("erp",), grupo="Operação",
       so_erp=True),
    _c("filial", "Filial", "texto", ("erp",), grupo="Operação", so_erp=True),
    _c("numero_frota", "Número de frota", "texto", ("erp",),
       grupo="Operação", so_erp=True,
       ajuda="Cobertura útil de 46%: em 943 cadastros o campo tem a PLACA "
             "copiada dentro. Ver api/frota_identidade.py."),
)

POR_NOME: dict[str, dict] = {c["nome"]: c for c in CAMPOS}

#: Os grupos na ordem em que a tela os mostra.
GRUPOS: tuple[str, ...] = tuple(dict.fromkeys(c["grupo"] for c in CAMPOS))


def pendencias_da_independencia() -> tuple[dict, ...]:
    """Os campos que HOJE morrem junto com o Avacorp.

    Não é lista escrita à mão: sai do próprio catálogo, então acrescentar um
    campo `so_erp` já o coloca aqui, e dar-lhe uma segunda fonte já o tira.
    Lista escrita à mão que descreve o código é lista que envelhece calada —
    foi como a varredura de agendadores passou a procurar uma thread com o
    nome errado.
    """
    return tuple(c for c in CAMPOS if c["so_erp"])


def campos_do_grupo(grupo: str) -> tuple[dict, ...]:
    return tuple(c for c in CAMPOS if c["grupo"] == grupo)
