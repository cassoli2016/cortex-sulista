# -*- coding: utf-8 -*-
"""App do Motorista — a operação DELE, no celular dele.

Escopo, fases e o que fica de fora: `docs/APP_MOTORISTA.md`. Este docstring é
o CONTRATO do módulo: as regras abaixo valem para tudo que entrar aqui depois,
e quem precisar quebrar uma delas quebra por escrito.

═══════════════════════════════════════════════════════════════════════════
A TERCEIRA PERGUNTA DE ACESSO
═══════════════════════════════════════════════════════════════════════════
O RBAC da casa responde "que tela você abre" (perfil × tela). O portal do
cliente acrescentou "quais linhas são suas" (raiz de CNPJ). Aqui é a mais
estreita: **qual motorista você é** — as linhas de UMA pessoa, que é PII
inteira (jornada, documentos, e adiante premiação, que é salário indireto).

**Identidade separada, de propósito.** O motorista NÃO é uma linha em
`usuarios`; ele vive em `mot_vinculos`, com cookie próprio e sessão própria.
As três razões estão no comentário de `sql/cortex/0057_motorista.sql`, e a
consequência prática é a que importa: **uma sessão de motorista não alcança
rota nenhuma do painel**. Ela não é lida por `auth.sessao_atual`, não vira
`scope["state"]["sessao"]`, e o middleware do painel continua fail-closed
para ela como para qualquer desconhecido.

O preço é uma SEGUNDA autenticação para manter — e é por isso que ela mora
inteira em `sessao.py` e `entrada.py`, com guards próprios, em vez de espalhada
por rota.

═══════════════════════════════════════════════════════════════════════════
AS ROTAS SÃO PÚBLICAS PARA O MIDDLEWARE, E GUARDADAS AQUI
═══════════════════════════════════════════════════════════════════════════
`/api/motorista/*` entra em `_PUBLICAS_MOTORISTA` (`api/auth.py`) porque o
middleware do painel só sabe validar cookie de painel — ele responderia 401 a
uma sessão de motorista perfeitamente válida. É o mesmo arranjo do rastreio
público, com uma diferença que precisa ficar dita: **lá a porta é aberta de
verdade; aqui ela só troca de porteiro.** Toda rota deste módulo, exceto as
duas de entrada, começa por `sessao.exigir(request)`, que levanta.

Rota nova aqui sem `exigir()` é rota aberta ao mundo. Há teste que varre as
rotas `/api/motorista/*` e cobra isso — porque a falha é MUDA: a rota
funciona, devolve dado certo, e não pergunta quem está lendo.

═══════════════════════════════════════════════════════════════════════════
A QUARTA PERGUNTA: E QUEM CONFERE?
═══════════════════════════════════════════════════════════════════════════
Desde 07/09/2026 o app diz coisas sobre uma pessoa que vêm de junções frágeis
(multa casada pela janela da viagem, indicador casado pelo nome na Gobrax) — e
o único leitor de cada tela é justamente quem menos pode conferir se ela está
certa. Erro assim vive escondido: cada motorista vê só a dele.

O **código mestre** (`mestre.py`) resolve isso abrindo uma sessão NORMAL na
conta de quem for escolhido — mesmas rotas, mesmo escopo vindo da sessão —,
marcada `mestre`, com prazo de horas e tarja obrigatória na tela. Não é um
perfil de administração dentro do app: **não existe rota que devolva a
operação de vários motoristas de uma vez.** A única lista é de id e nome, para
escolher, e ela não abre sessão nenhuma.

═══════════════════════════════════════════════════════════════════════════
O QUE NÃO SAI DAQUI
═══════════════════════════════════════════════════════════════════════════
Valor de frete, custo, CKM, resultado, e a operação de QUALQUER outro
motorista. O leitor vê a viagem dele: para onde vai, com que placa, para que
cliente. `TORRE_TRANSITO_SQL` (a mesma viagem, na tela da torre) devolve
`valorfrete` e `km`; a consulta daqui é outra de propósito, e não é a mesma com
um filtro a mais — filtro se esquece, coluna que não existe na query não vaza.

**A ÚNICA EXCEÇÃO DE DINHEIRO É O VALOR DA MULTA**, decidida por quem opera em
07/09/2026: não é dinheiro da empresa, é o número que está no auto, no boleto e
na conversa que ele vai ter com a torre. Esconder faria a tela valer menos que
o papel que ele já recebe. Pontuação de CNH entra pelo mesmo motivo — o ponto é
dele.

**A ÚNICA COMPARAÇÃO COM COLEGAS É A POSIÇÃO NO RANKING DA GOBRAX**, e ela só
cabe porque a premiação já é pública entre eles. Produtividade se compara com
os 30 dias anteriores DELE; nunca com a média da frota.

O CPF do motorista não entra em URL, não vai no payload e não vira chave: a
chave é `cadastro.codigo`, que é um código de cadastro e não um documento.

═══════════════════════════════════════════════════════════════════════════
O QUE ESTE APP NÃO ESCREVE
═══════════════════════════════════════════════════════════════════════════
**O AVA é somente leitura, e o app não escreve no ERP.** Quando a fase 2
trouxer os apontamentos, eles vão para `mot_*` no banco da casa com
`origem='app'`, e a torre concilia mostrando OS DOIS LADOS. Fundir os dois num
número só é como se descobre, seis meses depois, que metade da operação está
sendo medida por um apontamento que ninguém validou.

**Jornada não se aponta duas vezes.** A RasterJOR é a fonte legal e é ela que
vai para a folha. Este app LÊ e AVISA; não marca, não corrige, não justifica.
"""
from __future__ import annotations

#: Schema do banco local. `None` = o padrão (`cortex`). Os testes apontam para
#: um schema descartável — ver a fixture `esquema_pg`. Cada módulo que grava
#: tem o seu, e o teste que esquece de redirecionar UM deles escreve em
#: produção: aconteceu com a Monkey em 01/09/2026.
ESQUEMA: str | None = None
