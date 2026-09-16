# -*- coding: utf-8 -*-
"""O APP DO AGREGADO — o que a Sulista paga aos veículos de um proprietário.

Pedido de quem opera (16/09/2026): *"um aplicativo para agregados, porém quem
vai ter acesso serão os proprietários"*, com o faturamento dos veículos, as
viagens, os abastecimentos, os descontos, as multas, as ocorrências e os
acertos — os finalizados e os em aberto.

═══════════════════════════════════════════════════════════════════════════
O ESCOPO É O DONO, E ELE VEM DA SESSÃO
═══════════════════════════════════════════════════════════════════════════
A chave é o `cadastro.codigo` do proprietário, que é para onde
`veiculo.proprietario` aponta. Toda leitura deste módulo começa nele e NUNCA
recebe "de quem" como parâmetro do navegador: função que aceita o dono como
argumento é função que um dia é chamada com o dono errado, e o defeito é mudo
— a tela responde, bonita, com os veículos de outra pessoa.

═══════════════════════════════════════════════════════════════════════════
O QUE ESTE APP MOSTRA, E O QUE ELE NUNCA MOSTRA
═══════════════════════════════════════════════════════════════════════════
MOSTRA (decisão de quem opera, 16/09/2026 — "só o dinheiro dele"):
  * o que a Sulista PAGA ao veículo dele: frete da viagem, adicionais,
    adiantamentos, descontos, despesas e o líquido do acerto;
  * o acerto fechado e o em aberto, e se a parcela já foi paga;
  * abastecimentos das placas dele (CtaPlus), viagens, lançamentos manuais e
    as ocorrências das cargas que ele levou.

NUNCA MOSTRA:
  * o que o CLIENTE pagou à Sulista (`valorfrete`, receita da viagem), nem
    qualquer margem — a diferença entre os dois é o resultado da casa, e não é
    assunto do fornecedor. Isto não é filtro que alguém esquece: a coluna não
    entra no SELECT;
  * a operação de OUTRO agregado, em nenhuma forma — nem ranking, nem média da
    frota, nem "você está acima do grupo";
  * documento de pessoa nenhuma (o `proprietario_codigo` é CPF para 80 dos 201
    donos) e nenhum dado de motorista além do primeiro nome de quem dirigiu a
    carga dele.

═══════════════════════════════════════════════════════════════════════════
AS REGRAS DURÁVEIS (as mesmas do app do motorista, e pelas mesmas razões)
═══════════════════════════════════════════════════════════════════════════
1. **Identidade separada de `usuarios`.** O dono não abre o painel: tabela
   própria (`agr_vinculos`), cookie próprio (`cortex_agr`, com `path` no
   prefixo da API), sessão em tabela — e o desligamento derruba o acesso na
   requisição seguinte, sem esperar o token vencer.
2. **Rota pública para o middleware, guardada dentro do módulo.** O prefixo
   `/api/agregado/` é liberado em `api/auth.py` porque o porteiro é
   `agregado.sessao.exigir()`, que LEVANTA. Há teste varrendo as rotas do
   prefixo para cobrar isso, porque a falha é MUDA.
3. **O AVA é somente leitura.** Este módulo não escreve nada no ERP. O que o
   dono faz no app (ciência, contestação — se um dia existir) vai para tabela
   da casa, nunca para dentro do acerto.
4. **Recusa legível é 4xx.** 5xx só para falha nossa: o Cloudflare troca o
   corpo de 5xx pela página dele e a mensagem não chega a quem está lendo.
5. **`ESQUEMA` é lido NA CHAMADA**, nunca importado no topo — `from . import
   ESQUEMA` copia o valor, e o teste que redireciona o schema não alcançaria a
   cópia: o módulo escreveria em PRODUÇÃO com a suíte verde.

═══════════════════════════════════════════════════════════════════════════
O QUE FOI MEDIDO ANTES DE ESCREVER (16/09/2026)
═══════════════════════════════════════════════════════════════════════════
  * 298 veículos `utilizacaoveiculo='AGR'` e 201 donos; 154 donos têm um
    veículo só, e o maior tem 15.
  * Os 201 donos têm telefone no cadastro do ERP — por isso a entrada é por
    WhatsApp, como a do motorista, e ninguém fica de fora.
  * 2.892 acertos em 12 meses; `concluido = 1` é o fechado e o resto está em
    aberto (10 hoje). 2.837 parcelas pagas contra 329 em aberto.
  * 12.395 abastecimentos em 12 meses, em 174 das 298 placas (CtaPlus).
  * 569 lançamentos manuais desde 08/2025, com tipo legível e aprovação.
  * Multa de agregado NÃO existe na Smartec (634 em 12 meses, zero em placa
    AGR): o que existe é o desconto no acerto. A tela diz isso — um zero ali
    seria lido como "não tenho multa", que é afirmação que ninguém conferiu.
"""
from __future__ import annotations

#: Schema do banco da casa. `None` = o padrão da conexão. Os testes apontam
#: isto para um schema descartável; por isso cada módulo lê na CHAMADA.
ESQUEMA: str | None = None
