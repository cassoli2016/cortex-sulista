# -*- coding: utf-8 -*-
"""RasterIntegra — o webservice de Gerenciamento de Risco da Raster/Logae.

FASE 1 (v0.204.0): o módulo LÊ o que o ERP já recebe do hub de rastreamento
(o AVA consome o RasterIntegra desde sempre: 6,1 milhões de retornos em
`rastreadora_retorno`, eventos parseados em `ocorrenciarastreamento`) — a
tela `gr` nasce disso, sem credencial nova e sem chamada ao fornecedor.

FASE 2 (planejada): coleta própria de `getEventoFimViagem` (pânico, desvio
de rota, violação de painel/antena, área de risco — o consolidado de risco
por viagem), `getKMRodado` e `getMensagens`, com credencial NOVA e
exclusiva (`RASTERINTEGRA_*`): a credencial que o ERP usa foi encontrada
EXPOSTA em texto plano no próprio banco e deve ser tratada como
comprometida — e reusar o mesmo login dobraria o rate-limit (30s/15s) que
o ERP já fura (CodErro 102 medido). O manual completo (190 páginas) está
em data/manuais/RasterIntegra_13.1.pdf; o mapa da API, na spec de
01/09/2026.

NÃO confundir com o RasterJOR (api/jornada/): mesmo fornecedor, OUTRO
serviço — E-Ponto External API, Bearer token; a credencial não serve aqui.
"""
