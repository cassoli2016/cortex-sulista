# -*- coding: utf-8 -*-
"""O CATÁLOGO DE CAMPOS do cadastro de equipamentos, e quem ganha de quem.

ESTE ARQUIVO É O CONTRATO DO MÓDULO
===================================
Todo o resto — consolidação, tela, coleta, conferência — lê daqui. Um campo
novo se acrescenta em UM lugar e aparece nos quatro; e a precedência, que é a
regra mais fácil de espalhar por engano, existe uma vez só.

AS TRÊS FONTES
==============
    manual   >   smartec   >   erp

1. **`manual` sempre primeiro.** É o que faz o cadastro ser do CÓRTEX e não um
   espelho: sem isso a próxima coleta desfaz a correção, e quem corrigiu
   aprende numa semana que corrigir não adianta.
2. **`smartec` antes do `erp` no que é DOCUMENTO.** Ela devolve o registro do
   DENATRAN — chassi, cor, espécie, anos —, e o ERP devolve o que uma pessoa
   digitou. O ERP tem chassi preenchido em 99% da frota, mas preenchido e
   CORRETO são perguntas diferentes, e só a fonte oficial responde a segunda.
3. **`erp` primeiro no que é NOSSO**: vínculo, filial, número de frota,
   capacidade contratada, categoria. O Detran não sabe se um veículo é
   agregado ou terceiro — isso é contrato, não documento.

POR QUE A SMARTEC, E NÃO UM FORNECEDOR DE CONSULTA DE PLACA
===========================================================
Porque a casa já paga por ela. Em 08/09/2026 chegou a existir aqui uma
integração com consulta de placa avulsa (R$ 2,50 por veículo, ~R$ 3.600 pela
frota) e ela foi DESFEITA ao se medir que a Smartec — contratada, configurada
e coletando todo dia — devolve o mesmo. Ver `api/equipamentos/smartec.py`.

O campo `origem` de `eqp_equipamento` grava quem venceu. Não é auditoria
decorativa: é o que torna a saída do Avacorp MENSURÁVEL. "O que quebra se o
AVA sair amanhã?" vira uma consulta — conta os campos cuja origem ainda é
`erp` — em vez de uma leitura de código. Sem instrumento, a independência do
ERP seria uma afirmação; e afirmação sobrevive ao instrumento.

O QUE `so_erp` MARCA
====================
Os campos que HOJE só o ERP sabe responder. São a lista de pendências da
independência: enquanto houver campo `so_erp` em uso, desligar o AVA apaga
esse campo do cadastro. `pendencias_da_independencia()` devolve essa lista a
partir do próprio catálogo — nunca de uma segunda lista escrita à mão, que
envelheceria calada.
"""
from __future__ import annotations

# As fontes, na ordem GERAL de força. Fonte que não aparece aqui não entra na
# consolidação, mesmo que grave em `eqp_fonte` — evita que uma coleta
# experimental altere o cadastro sem alguém decidir.
FONTES = ("manual", "smartec", "erp")

#: Rótulo curto de cada fonte, para a tela dizer de onde veio o número.
ROTULO_FONTE = {
    "manual": "corrigido à mão",
    "smartec": "Smartec (Detran)",
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
    _c("renavam", "RENAVAM", "texto", ("smartec", "erp"), grupo="Identidade"),
    _c("chassi", "Chassi", "texto", ("smartec", "erp"), grupo="Identidade",
       ajuda="A Smartec traz o do DENATRAN; o ERP, o que alguém digitou. O "
             "ERP tem 99% preenchido, mas preenchido não é conferido — "
             "divergência aqui é erro de cadastro."),
    _c("numero_motor", "Número do motor", "texto", ("erp",),
       grupo="Identidade", so_erp=True),
    _c("placa_anterior", "Placa anterior", "texto", ("erp",),
       grupo="Identidade", so_erp=True,
       ajuda="A pré-Mercosul. É ela que explica os números de frota "
             "'repetidos' do ERP: o mesmo veículo cadastrado duas vezes."),

    # ---- o que o equipamento é -------------------------------------------
    _c("categoria", "Categoria", "texto", ("erp",), grupo="Classificação",
       so_erp=True,
       ajuda="Nossa: tração ou implemento. Sai da flag `tracao` do tipo do "
             "ERP — evidência escrita, não palpite. É ela que impede somar "
             "numa média a idade da tração com a do implemento (6,9 contra "
             "12,9 anos)."),
    _c("tipo", "Tipo", "texto", ("erp",), grupo="Classificação", so_erp=True,
       ajuda="O tipo como a Sulista o classifica ('CARRETA 3 EIXOS SIDER'), "
             "com a quantidade de eixos junto. É mais específico que a "
             "espécie do DENATRAN e é o que a operação usa."),
    _c("especie", "Espécie (DENATRAN)", "texto", ("smartec",),
       grupo="Classificação",
       ajuda="Como o Detran classifica: CAMINHÃO TRATOR, SEMIRREBOQUE. É a "
             "classificação oficial, e não a nossa."),
    _c("carroceria", "Carroceria", "texto", ("erp",), grupo="Classificação",
       so_erp=True),

    # ---- modelo -----------------------------------------------------------
    _c("marca", "Marca", "texto", ("erp",), grupo="Modelo", so_erp=True,
       ajuda="Vem do ERP porque lá ela tem TABELA DE DOMÍNIO "
             "(public.marcaveiculo, 40 linhas, casa 100%). Na Smartec a marca "
             "vem embutida no descritor, e parti-lo daria 'SR' num "
             "semirreboque — ver o campo Descritor."),
    _c("modelo", "Modelo", "texto", ("erp",), grupo="Modelo", so_erp=True,
       ajuda="Código do ERP ('2422', '1218'), sem tabela de domínio. Fica "
             "cru: código sem domínio não vira rótulo inventado."),
    _c("versao", "Descritor DENATRAN", "texto", ("smartec",), grupo="Modelo",
       ajuda="O nome completo como o DENATRAN publica: 'VW/19.360 CTC 4X2'. "
             "É marca, modelo e versão numa string só, e é a única fonte da "
             "VERSÃO — que é o que separa dois caminhões de mesmo modelo e "
             "preços muito diferentes."),
    _c("ano_fabricacao", "Ano de fabricação", "inteiro", ("smartec", "erp"),
       grupo="Modelo"),
    _c("ano_modelo", "Ano do modelo", "inteiro", ("smartec", "erp"),
       grupo="Modelo"),
    _c("cor", "Cor", "texto", ("smartec", "erp"), grupo="Modelo",
       ajuda="No ERP o campo de texto está VAZIO em 100% da frota; a cor real "
             "vem de um código que cobre 56%. A Smartec traz a do DENATRAN."),
    _c("combustivel", "Combustível", "texto", ("erp",), grupo="Modelo",
       so_erp=True),

    # ---- capacidade, em unidade de ORIGEM: quilo e litro ----------------
    # Razão e percentual saem da unidade de origem; arredondar para tonelada
    # antes de dividir move o número de lado da fronteira.
    _c("tara_kg", "Tara (kg)", "inteiro", ("erp",), grupo="Capacidade",
       so_erp=True),
    _c("capacidade_carga_kg", "Capacidade de carga (kg)", "inteiro", ("erp",),
       grupo="Capacidade", so_erp=True),
    _c("capacidade_m3", "Capacidade (m³)", "decimal", ("erp",),
       grupo="Capacidade", so_erp=True,
       ajuda="Cubagem é fato do implemento como a Sulista o usa, não do "
             "documento. O Detran não tem."),
    _c("capacidade_tanque_l", "Tanque (L)", "inteiro", ("erp",),
       grupo="Capacidade", so_erp=True),
    _c("eixos", "Eixos", "inteiro", ("erp",), grupo="Capacidade", so_erp=True,
       ajuda="Decide o piso ANTT e a tarifa de pedágio. Errado aqui, erram "
             "os dois."),

    # ---- emplacamento -----------------------------------------------------
    _c("uf", "UF", "texto", ("smartec", "erp"), grupo="Emplacamento"),
    _c("municipio", "Município", "texto", ("erp",), grupo="Emplacamento",
       so_erp=True),

    # ---- propriedade: fato da OPERAÇÃO, o ERP na frente -------------------
    _c("vinculo", "Vínculo", "texto", ("erp",), grupo="Propriedade",
       so_erp=True,
       ajuda="próprio, agregado ou terceiro. O Detran não sabe — isso é "
             "contrato, não documento. É o campo que mais dói perder quando "
             "o ERP sair, e o primeiro que precisa de cadastro próprio."),
    _c("proprietario_doc", "CPF/CNPJ do proprietário", "texto", ("erp",),
       grupo="Propriedade", so_erp=True),
    _c("proprietario_nome", "Proprietário", "texto", ("erp",),
       grupo="Propriedade", so_erp=True),

    # ---- documentação: o que só a fonte oficial sabe ---------------------
    _c("tem_restricao", "Restrição impeditiva", "booleano", ("smartec",),
       grupo="Documentação",
       ajuda="Roubo, furto, Renajud, recall, bloqueio judicial — o que impede "
             "o veículo de rodar. Alienação fiduciária NÃO entra aqui: ela é "
             "campo separado, porque veículo financiado é o estado normal de "
             "boa parte da frota e pintá-lo de vermelho ensina a ignorar o "
             "vermelho. NULO é 'não consultado', diferente de FALSO."),
    _c("alienacao_fiduciaria", "Alienação fiduciária", "texto", ("smartec",),
       grupo="Documentação",
       ajuda="O banco credor, quando o veículo é financiado. Não é alarme: é "
             "informação de ativo — vender exige quitar. Medido em 19 "
             "veículos, 10 tinham restrição e as 10 eram esta."),
    _c("restricoes", "Restrições", "json", ("smartec",),
       grupo="Documentação"),
    _c("licenciamento_mes", "Mês de licenciamento", "inteiro", ("smartec",),
       grupo="Documentação",
       ajuda="O mês em que o veículo licencia. NÃO é a data de vencimento do "
             "CRLV — usar um pelo outro inventaria uma data, e data errada "
             "num vencimento é pior que data nenhuma."),
    _c("cronotacografo_vencimento", "Cronotacógrafo vence em", "data",
       ("smartec",), grupo="Documentação",
       ajuda="Obrigação de frota que não existe em lugar nenhum do ERP."),
    _c("situacao", "Situação no Detran", "texto", (), grupo="Documentação",
       ajuda="Sem fonte hoje. A Smartec não publica a situação da placa, e a "
             "consulta avulsa que a traria foi recusada por custo. Fica "
             "declarado como lacuna em vez de sumir do cadastro — campo que "
             "some é lacuna que ninguém lembra de cobrir."),
    _c("crlv_vencimento", "Vencimento do licenciamento", "data", (),
       grupo="Documentação",
       ajuda="Sem fonte hoje: `smt_licenciamento` traz o MÊS, não a data. "
             "Preenchível à mão."),

    # ---- valor ------------------------------------------------------------
    _c("fipe_valor", "Valor FIPE", "decimal", ("erp",), grupo="Valor",
       so_erp=True,
       ajuda="Do ERP, e sem mês de referência — o que o torna um número sem "
             "data. Existe em 16% do cadastro e em ZERO dos agregados e "
             "terceiros. É a única lacuna que valeria consulta paga: R$ 0,10 "
             "por placa na tabela FIPE por chassi."),

    # ---- estado operacional ----------------------------------------------
    _c("ativo", "Ativo", "booleano", ("erp",), grupo="Operação", so_erp=True),
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

    Sai do próprio catálogo, então acrescentar um campo `so_erp` já o coloca
    aqui, e dar-lhe uma segunda fonte já o tira. Lista escrita à mão que
    descreve o código é lista que envelhece calada.
    """
    return tuple(c for c in CAMPOS if c["so_erp"])


def sem_fonte() -> tuple[dict, ...]:
    """Campos declarados que NENHUMA coleta preenche hoje.

    Existem de propósito, e a tela os mostra como lacuna: campo que some do
    catálogo é lacuna que ninguém lembra de cobrir. Coluna sempre vazia se
    preenche ou se remove — aqui a escolha é preencher (à mão, ou por fonte
    futura), e enquanto isso a ausência fica NOMEADA.
    """
    return tuple(c for c in CAMPOS
                 if [f for f in c["precedencia"] if f != "manual"] == [])


def campos_do_grupo(grupo: str) -> tuple[dict, ...]:
    return tuple(c for c in CAMPOS if c["grupo"] == grupo)
