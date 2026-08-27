# api/contrapartida/sql.py
"""CT-e de contrapartida do agregado — conciliacao.

O QUE ESTA TELA MEDE
====================
Para cada CT-e que a Sulista emite com veiculo de AGREGADO, existe (ou deveria
existir) um CT-e emitido PELO agregado contra a Sulista. Hoje nao existe
nenhum: a tela dimensiona a fila e prepara a emissao, nao a executa.

DUAS POPULACOES QUE NAO PODEM SER SOMADAS
-----------------------------------------
Medido em 26/08/2026 nos veiculos com utilizacaoveiculo='AGR':

  proprietario PJ   119 donos · 203 placas  -> emite CT-e
  proprietario CPF   79 donos ·  92 placas  -> TAC, NAO emite CT-e

O TAC (Transportador Autonomo de Cargas, Lei 11.442) nao e sujeito passivo do
CT-e: a documentacao dele e CIOT + RPA. Juntar os dois numa fila unica de
"CT-e a emitir" produziria um passivo falso de um terco do volume e mandaria a
operacao atras de um documento que nao existe.

Por isso o CNPJ/CPF do proprietario e classificado no SQL e a tela separa as
duas trilhas desde o primeiro numero.
"""
from __future__ import annotations

# 14 digitos = CNPJ (PJ, emite CT-e); 11 = CPF (TAC, nao emite).
# `proprietario` guarda o documento ja sem mascara na maioria das linhas, mas
# ha registros com ponto e barra - o regexp_replace normaliza os dois casos.
_DOC = "regexp_replace(coalesce(v.proprietario,''),'[^0-9]','','g')"

_CLASSE = f"""
  CASE WHEN length({_DOC}) = 14 THEN 'pj'
       WHEN length({_DOC}) = 11 THEN 'tac'
       ELSE 'indefinido' END"""

# semaforo = 1 exclui o cancelado. Sem isso o passivo conta documento que nao
# existe mais - o mesmo cuidado que a tela de Agregados ja aplica nos acertos.
_BASE = f"""
FROM conhecimento k
JOIN veiculo v ON v.placa = k.veiculo
-- LEFT e nao INNER: agregado sem cadastro nao pode SUMIR da fila; ele aparece
-- sem nome e entra na lista de pendencia cadastral, que e o proximo passo.
LEFT JOIN cadastro cd ON cd.codigo = v.proprietario
WHERE v.utilizacaoveiculo = 'AGR'
  AND coalesce(k.semaforo, 1) = 1
  AND k.dtcancelamento IS NULL
  AND k.dtemissao >= %(de)s::date AND k.dtemissao < %(ate)s::date
"""

# Fila por MES e por CLASSE do proprietario.
POR_MES_SQL = f"""
SELECT to_char(k.dtemissao,'YYYY-MM') AS mes,{_CLASSE} AS classe,
       count(*)::int AS ctes,
       count(DISTINCT v.proprietario)::int AS agregados,
       count(DISTINCT k.veiculo)::int AS placas,
       coalesce(sum(coalesce(k.valortotalprestacao,0)),0)::float8 AS valor
{_BASE}
GROUP BY 1, 2 ORDER BY 1, 2
"""

# Fila por AGREGADO: e por aqui que a operacao ataca, um agregado de cada vez.
# Traz tambem o que a EMISSAO vai exigir (razao social, IE, RNTRC, municipio):
# agregado sem esses campos nao emite, e descobrir isso na hora da transmissao
# custa uma rejeicao por documento.
POR_AGREGADO_SQL = f"""
SELECT v.proprietario AS documento,{_CLASSE} AS classe,
       max(cd.razaosocial) AS nome,
       max(cd.inscricaoestadual) AS ie,
       -- RNTRC e obrigatorio no CT-e: sem ele a transmissao e
       -- rejeitada documento a documento
       max(cd.numerorntrc) AS rntrc,
       -- 1 = contribuinte de ICMS, 9 = nao contribuinte. Separa
       -- contradicao de cadastro de isencao real.
       max(cd.indicadorinscricaoestadual) AS ind_ie,
       max(cd.cidade) AS cidade,
       max(cd.uf) AS uf,
       count(*)::int AS ctes,
       count(DISTINCT k.veiculo)::int AS placas,
       coalesce(sum(coalesce(k.valortotalprestacao,0)),0)::float8 AS valor,
       min(k.dtemissao)::date AS primeiro,
       max(k.dtemissao)::date AS ultimo
{_BASE}
  AND v.proprietario IS NOT NULL
GROUP BY v.proprietario,{_CLASSE}
ORDER BY 9 DESC
"""

# Universo cadastral, independente de ter havido CT-e no periodo: e o que
# dimensiona o cadastro de certificados a montar.
FROTA_AGR_SQL = f"""
SELECT{_CLASSE} AS classe,
       count(DISTINCT v.proprietario)::int AS donos,
       count(*)::int AS placas
FROM veiculo v
WHERE v.utilizacaoveiculo = 'AGR'
GROUP BY 1
"""

# Passivo historico, para a conversa com a contabilidade. CT-e NAO se emite
# retroativo (a SEFAZ recusa data fora da janela), entao isto nao vira fila de
# trabalho - vira numero para decisao juridica.
PASSIVO_SQL = f"""
SELECT to_char(k.dtemissao,'YYYY') AS ano,{_CLASSE} AS classe,
       count(*)::int AS ctes,
       coalesce(sum(coalesce(k.valortotalprestacao,0)),0)::float8 AS valor
{_BASE}
GROUP BY 1, 2 ORDER BY 1, 2
"""
