# Changelog

Gerado de `docs/versoes.yaml` por `scripts/gerar_changelog.py` — não editar à mão.
Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [0.29.0] — 24/08/2026  ·  CX-24/08/2026-v0.29.0

### Adicionado
- A Saude do Servidor passou a monitorar o Oracle da folha (GLOBUS). Sao DOIS bancos externos e so um estava vigiado: se o Oracle caisse, as telas de RH e Custo de Folha paravam e a Saude continuava toda verde. Nao configurado aparece como informacao, nao como falha - pintar de vermelho um recurso que a instalacao nao usa treina a ignorar alarme.
- Card novo com as oito bases locais do CORTEX (usuarios e auditoria, orcamento, antecipacoes, extrato, telemetria, previsao, e-mails e push). E nelas que fica tudo o que o sistema escreve, ja que o ERP e replica somente-leitura, e nenhuma aparecia: se uma travasse ou perdesse permissao de escrita, a falha so apareceria na tela que depende dela, uma de cada vez. Mostra tamanho, integridade e quando foi escrita.

### Corrigido
- A tela de Documentacao era a unica sem moldura: titulo, busca e indice lateral ficavam soltos, colados na margem. Ganharam a mesma superficie de card do resto do painel, e o indice lateral agora rola sozinho em vez de esticar a pagina.

## [0.28.0] — 24/08/2026  ·  CX-24/08/2026-v0.28.0

### Adicionado
- Os limites de credito agora se editam pela tela, no fim do Fluxo Consolidado: banco, tipo, limite, taxa mensal e vencimento. Antes so dava para mexer no arquivo, e a taxa do Itau muda todo mes. Salvar recarrega a tela, porque os chips de cada periodo e os avisos do topo dependem do limite que acabou de mudar.
- O orcamento planejado passou a ser importado pela aba Montagem do Orcamento. O arquivo e CONFERIDO antes de gravar: a tela mostra quanto entrou, quanto ficou de fora e por que, o rateio de cada agrupador contra o plano, e so entao oferece o botao de importar. Nada e gravado na conferencia.

### Corrigido
- Clicar em Portais de Antecipacao recolhia o menu inteiro. A tela nao estava no mapa de grupos, e o acordeao fechava todos por nao achar o dela. Alem da correcao, tela sem grupo conhecido agora nao mexe no menu em vez de fechar tudo.
- Os insights do Fluxo Consolidado foram para o fim da tela, como ja estao os da Antecipacao.
- Botoes de formularios escondidos apareciam mesmo assim: o atributo "hidden" do HTML perde para qualquer regra de estilo com display, e os rodapes de formulario usam display flex. Corrigido para toda a aplicacao - havia remendos pontuais espalhados que eram sintoma disso.
- Uma sessao sem a lista de telas derrubava a checagem de permissao e acendia a tarja vermelha de erro no topo. Agora, sem a lista, o acesso e negado (que e o comportamento seguro) em vez de quebrar a tela.

## [0.27.0] — 24/08/2026  ·  CX-24/08/2026-v0.27.0

### Adicionado
- Os limites de cheque empresa entraram no Fluxo de Caixa e no Fluxo Consolidado. Saldo negativo deixou de ser uma coisa so: no grafico do fluxo aparece agora uma FAIXA entre o zero e os R$ 485 mil de limite - enquanto a linha esta dentro dela o mes se resolve com rotativo (caro, mas contratado); abaixo dela nao ha cobertura. O KPI diz quanto existe contratado, em quais bancos e a que taxa efetiva, e avisa que e piso e nao caixa.
- No Fluxo Consolidado cada periodo negativo passou a dizer se cabe no limite ("no limite") ou se passa dele ("sem cobertura", com o valor que falta). Um aviso no topo resume quantos periodos estouram, qual o maior descoberto e lembra que antecipar recebivel sai por ~2% a.m. contra ~15,7% do rotativo - de seis a oito vezes mais barato.
- Limite proximo do vencimento vira aviso nas duas telas: perder a folga do Santander em 25/10 derruba a reserva de emergencia de R$ 485 mil para R$ 340 mil, e isso nao aparece olhando saldo.

### Corrigido
- O confronto do limite com a projecao ignora o trecho em que os pagaveis lancados desabam (mesma regra que o grafico ja usava) e o balde de vencidos. Sem esse corte a tela anunciava "descoberto de R$ 10,4 milhoes em jul/2027", que nao era falta de dinheiro e sim falta de faturamento lancado - os meses distantes ficam negativos por construcao. A tela diz ate onde olhou.

## [0.26.0] — 24/08/2026  ·  CX-24/08/2026-v0.26.0

### Adicionado
- O orcamento de 2026 passou a ser o PLANEJADO pela diretoria, importado da planilha, e nao mais deduzido do historico. A planilha e por agrupador e o orcamento e por conta, entao o valor de cada agrupador e rateado entre as contas dele na proporcao do historico: o total bate ao centavo com o plano e o detalhe por conta continua existindo. Entrou como versao NOVA - a derivada do historico fica para comparacao.
- A receita entra como linha unica no total, por decisao da diretoria: o plano poe os R$ 144 mi todos em FROTA/LOCADOS e zero nas outras modalidades, enquanto a DRE realizada separa. Linha a linha, o acompanhamento acusaria FROTA estourando o orcamento e AGREGADOS 100% abaixo - duas variacoes enormes e as duas falsas.

### Corrigido
- A tela de Antecipacao passou a mostrar os insights no FIM, e nao antes dos numeros: eram ate seis tarjas de texto empurrando KPI e grafico para baixo da dobra. Insight e conclusao - vem depois do que ele conclui.
- As Operacoes de antecipacao sugeridas ganharam leitura: quatro KPIs com volume, custo e prazo medio do plano, os sacados na propria linha (antes era preciso abrir cada operacao para saber com quem ela se fecha) e barra proporcional no valor para achar as grandes sem ler numero por numero.
- A tela de Portais de Antecipacao mostrava um envio da Adient que nunca foi importado - sujeira de teste que entrou no banco de producao. Foi removida, e a lista de clientes com convenio agora diz explicitamente quem esta SEM planilha importada, que era a informacao que faltava.

## [0.25.0] — 24/08/2026  ·  CX-24/08/2026-v0.25.0

### Alterado
- Ter convenio de antecipacao nao basta: o titulo precisa estar LANCADO no portal do cliente. Como nao existe API para consultar isso, a planilha importada passou a ser a prova - so o que esta nela pode ser antecipado. A tela agora separa tres coisas que antes viravam um numero so: o que da para antecipar hoje, o que destravaria pedindo a planilha ao cliente (com o nome de cada um e o valor) e o que e de cliente sem convenio. Cliente que ja tem planilha mas com titulos de fora aparece separado - nesse caso a nota nao foi lancada no portal ou o arquivo esta velho.
- A Antecipacao parou de dizer "busque outra fonte" sem dizer qual. Os limites de cheque empresa (Itau, Santander e Sicredi) entraram no sistema com limite, taxa e vencimento, e a tela mostra quanto do buraco eles cobrem, por qual banco e a que custo mensal - consumindo sempre do mais barato para o mais caro. O rotativo custa de 12,90% a 16,20% ao mes contra ~2% da antecipacao, o que inverte a prioridade: antecipar e o primeiro recurso, nao o ultimo. Limite proximo do vencimento vira aviso.
- As ordens de compra passaram a ser cobradas pela DATA DE PREVISAO DE ENTREGA, e nao pela idade da emissao. OC emitida ha 200 dias com entrega marcada para o mes que vem esta em dia; OC de 40 dias com previsao vencida ha 30 nao esta. Das 186 em aberto sem nota, 93 tem previsao futura (curso normal) e 93 ja venceram - e a acao sai graduada: ate 30 dias cobrar, acima de 30 validar, acima de 90 candidata a suspensao.

### Corrigido
- Importar o mesmo arquivo duas vezes nao duplicava numero (a tela sempre leu so o ultimo envio), mas acumulava copias no banco. Arquivo identico agora e reconhecido e avisa em vez de gravar de novo. No caminho apareceu um defeito maior: com mais de um portal, so o ultimo importado aparecia na tela - importar a planilha da Tupy faria a da Maxion sumir. Agora cada portal tem sua posicao vigente e todas somam.

## [0.24.0] — 24/08/2026  ·  CX-24/08/2026-v0.24.0

### Adicionado
- Tela nova "Portais de Antecipacao": arraste a planilha que o cliente exporta do portal de risco sacado e o CORTEX le, confere e concilia com o ERP. O layout e reconhecido pelo CABECALHO, nao pelo nome do arquivo, e cada portal novo entra como um modelo - o primeiro e o da Iochpe Maxion. O total do rodape da planilha e conferido contra a soma dos titulos: arquivo que nao fecha vira aviso vermelho antes de qualquer numero aparecer.
- Conciliacao com o contas a receber pelo numero da nota: quanto do arquivo existe no ERP, quais titulos tem VENCIMENTO diferente entre os dois (a divergencia que erra o fluxo de caixa sem ninguem notar) e quais so existem no portal. No primeiro arquivo real: 215 de 226 titulos casaram, 48 com vencimento 7 dias adiantado em relacao ao ERP e 11 titulos (R$ 236 mil) sem correspondente em aberto.

### Alterado
- As Operacoes de antecipacao sugeridas passaram a respeitar QUEM aceita antecipacao. Antes o plano supunha que qualquer recebivel podia ser antecipado e por isso fechava sempre - um plano que nao existe. Agora so entra recebivel de cliente com convenio, e a tela avisa quanto do total isso representa e quantos dias continuam descobertos mesmo antecipando tudo o que da. Cliente entra na lista sozinho ao importar a planilha dele, e pode ser ligado ou desligado a mao.
- O aviso "Fora do horizonte" da tela de Antecipacao aparecia sem cor nenhuma (a classe de estilo nao existia) e se confundia com texto solto.

### Corrigido
- As planilhas com dado de cliente (pasta antecipacoes/ e Planila_Fluxo/) estavam sendo versionadas no repositorio do codigo, que e PUBLICO. Foram removidas do rastreamento e entraram no .gitignore. O historico anterior ainda as contem - ver a nota da versao no CHANGELOG.

## [0.23.0] — 24/08/2026  ·  CX-24/08/2026-v0.23.0

### Adicionado
- As operacoes de antecipacao sugeridas agora abrem e mostram QUAIS documentos cada uma consome: o resumo por sacado - que e com quem a operacao se fecha - e a lista dos titulos, do maior para o menor. Antes a tela mandava "antecipar R$ 396 mil que vencem em 27/08" e quem opera nao sabia o que levar ao banco. Uma operacao pode consumir 461 documentos de 7 clientes, entao o resumo por sacado e completo e a lista traz os 40 maiores, com o contador dizendo quanto ficou de fora.
- O documento que a simulacao corta pela metade sai marcado como "parcial", com aviso: no banco o titulo vai INTEIRO, entao o volume real da operacao fica um pouco acima do sugerido.

### Corrigido
- Com o menu recolhido, o campo de busca e os rotulos de tema do Financeiro ("A RECEBER", "A PAGAR") transbordavam a barra de 64px e apareciam cortados. A busca virou um botao de lupa que expande o menu e ja deixa o cursor no campo; os rotulos de tema viraram a linha divisoria que eles desenhavam - o agrupamento continua visivel, so nao nomeado.

## [0.22.0] — 24/08/2026  ·  CX-24/08/2026-v0.22.0

### Adicionado
- O periodo expandido do Fluxo Consolidado agora traz o SALDO DIA A DIA: barras de entrada e saida de cada dia e a linha do saldo acumulado, abrindo no saldo do periodo. O menor saldo fica marcado com a data e o valor. E o que separa "a semana fecha em -R$ 2 mi" de "o caixa fura na quinta" - o fechamento pode ate ser positivo e ainda assim haver um dia no vermelho no meio, e e essa data que define para quando antecipar. Fim de semana sai com fundo esmaecido, e cada dia tem o detalhe no hover.

### Corrigido
- O envio de e-mail estava configurado com o servidor e a porta de LEITURA da caixa postal (outlook.office365.com na porta 995, que e POP3) em vez dos de envio, e todo teste falhava. O sistema agora recusa essa combinacao na hora de salvar, dizendo qual servidor e qual porta usar no lugar; e, quando um envio falha, a mensagem passou a dizer contra qual host, porta e seguranca a tentativa foi feita. Antes voltava apenas "Erro do servidor SMTP: SMTPConnectError.", que nao permitia consertar nada. Falha de autenticacao no Microsoft 365 tambem avisa que o SMTP autenticado vem desligado por padrao na caixa postal.

## [0.21.0] — 24/08/2026  ·  CX-24/08/2026-v0.21.0

### Adicionado
- No Fluxo Consolidado, abrir um periodo agora mostra os TITULOS que o compoem: as maiores saidas (vencimento, fornecedor, natureza e valor) e as maiores entradas agrupadas por cliente. Antes a expansao so dizia a natureza do gasto - "Divida financeira R$ 900 mil" - sem dizer qual parcela, de quem e em que dia. Agora a semana que fecha negativa se explica em duas linhas: a parcela do banco vence quinta e o pedagio na quarta. Os titulos sao buscados ao expandir, nao junto com a tela.

### Alterado
- Nenhuma tela do menu compartilha mais o icone de outra. Quatorze telas dividiam desenho com uma vizinha - Balanco, Orcamento e Fechamento usavam o mesmo grafico da DRE; Fluxo Consolidado, Fluxo de Caixa e Antecipacao o mesmo predio de banco; Lancamentos, Extrato e Contabilidade o mesmo livro razao. Como o olho procura a forma e nao le o rotulo, cada uma ganhou um icone proprio (balanca, calculadora, calendario com visto, rota, hidrante de combustivel etc.). A busca global usa os mesmos icones do menu, entao a lista de resultados tambem deixou de repetir.

## [0.20.0] — 24/08/2026  ·  CX-24/08/2026-v0.20.0

### Adicionado
- O Fluxo Consolidado passou a mostrar, na mesma tela, as três pontas da decisão: o saldo de cada banco, o estoque de recebíveis e quanto precisaria ser antecipado (com o custo estimado). Antes era preciso abrir três telas para juntar a mesma história. O plano operação a operação continua na tela de Antecipação, com link direto.
- O saldo aparece banco a banco, com a data da posição de CADA conta — elas não são todas do mesmo dia, e somar sem mostrar isso esconde defasagem.
- O recebível em aberto aparece por inteiro, não só a parte que cai no horizonte: são perguntas diferentes, e só o horizonte faz o lastro parecer menor do que é.

### Alterado
- O menu Financeiro, que chegou a nove telas, ganhou divisões por tema — Caixa, A receber, A pagar e Bancos — em vez de uma lista corrida na ordem em que as telas foram criadas.

### Corrigido
- Clicar numa semana do fluxo período a período não abria a composição do período — a linha alternava uma classe que o CSS não reconhecia. Agora abre e mostra entradas por tipo de documento e saídas por natureza.
- Na busca global, todas as telas apareciam com o mesmo ícone. Agora cada resultado usa o ícone da própria tela, lido do menu.

## [0.19.0] — 24/08/2026  ·  CX-24/08/2026-v0.19.0

### Adicionado
- Busca global no topo do menu, com atalho Ctrl+K (ou apenas "/"). São 56 telas hoje — procurar virou mais rápido que navegar. Setas para escolher, Enter para abrir, Esc para fechar.
- A busca entende SINÔNIMO, não só o nome da tela: digitar "inadimplência" leva à Régua de Cobrança, "eco" ou "embalo" à Condução Econômica, "factoring" à Antecipação. Quem procura raramente usa o nome exato da tela.
- Digitar uma PLACA abre direto a ficha daquele veículo, já com a consulta disparada. Digitar um nome oferece consultar aquele cliente. A busca deixou de ser índice de menu e virou atalho de trabalho.
- Só aparece o que o usuário pode abrir: a busca respeita as permissões de tela. Resultado que leva a uma tela sem acesso é pior que resultado nenhum — a pessoa clica e é jogada para outro lugar.

### Corrigido
- Os grupos Telemetria e ANTT não abriam sozinhos no menu ao navegar para uma tela deles; estavam fora do mapa que controla o acordeão. Passava despercebido antes da busca, que agora navega para qualquer tela.

## [0.18.0] — 24/08/2026  ·  CX-24/08/2026-v0.18.0

### Alterado
- Os quatro cartões do topo da Torre de Controle passaram a mostrar TELEMETRIA: consumo da frota contra o alvo, quantos veículos estão abaixo do alvo, freadas bruscas por mil quilômetros e velocidade média. Antes mostravam viagens em trânsito, atrasadas e sem posição — informação que continua na tela, no resumo do mapa e na tabela de viagens, que já ordena as atrasadas primeiro e marca em âmbar e vermelho quem parou de transmitir.
- O consumo da frota é o km total dividido pelos litros totais, não a média das médias — assim um veículo que rodou 200 km não pesa igual a um que rodou 20 mil. Veículo com leitura implausível fica fora da conta e o cartão diz quantos foram descartados.
- A freada brusca aparece por mil quilômetros, não em total absoluto: o total só diz quem rodou mais, e o que interessa é quem dirige com mais risco.
- Todos os quatro cartões dizem de quando é a coleta, e um selo avisa quando ela tem mais de dois dias. A telemetria vem de coleta em segundo plano, enquanto o mapa é ao vivo — sem esse aviso, dado de dias atrás seria lido como do momento numa tela em que todo o resto é.

## [0.17.1] — 24/08/2026  ·  CX-24/08/2026-v0.17.1

### Alterado
- Os formulários de configuração (E-mail e Políticas de segurança, em Administração › Gestão) ganharam margem interna. Os campos e os botões encostavam na borda do cartão — era o único bloco do painel sem esse espaçamento, e destoava do resto.
- A tela de e-mail explica, logo no topo, a diferença entre POP e SMTP: POP e IMAP só recebem, quem envia é o SMTP, e toda conta POP vem com um servidor SMTP de saída (normalmente o mesmo endereço trocando "pop" por "smtp", na porta 587). É a dúvida que aparece na hora de configurar, e agora a resposta está no lugar onde ela surge.

## [0.17.0] — 24/08/2026  ·  CX-24/08/2026-v0.17.0

### Adicionado
- Nova tela no Financeiro: Lançamentos Recorrentes. Mostra as contas que entram todo mês e que ainda NÃO foram lançadas neste — hoje são 66 atrasadas, somando cerca de R$ 1,6 milhão, entre elas folha, diárias de motoristas, FGTS e combustível. Cada linha diz até que dia a conta costuma entrar, quantos meses seguidos ela aparece e quanto costuma ser.
- Separa o que está atrasado do que ainda está no prazo: só entra como atraso quem já passou do dia MAIS TARDIO em que a conta já foi lançada, não da média — assim fornecedor de data irregular não vira alarme falso.
- As já lançadas aparecem com o valor deste mês ao lado da média, com a variação destacada. Diferença grande pode ser reajuste, consumo atípico ou erro de digitação, e fica visível sem precisar procurar.
- A recorrência é deduzida do próprio histórico (fornecedor × tipo de título nos últimos meses), porque o ERP não tem um cadastro utilizável para isso. A lista se mantém sozinha: quem passa a lançar todo mês entra e quem deixa de lançar sai, sem ninguém cadastrar nada.

## [0.16.1] — 24/08/2026  ·  CX-24/08/2026-v0.16.1

### Alterado
- As ordens de compra passaram a exibir a FILIAL junto do número, com o nome e não só o código. O número da ordem se repete entre filiais (existe a mesma ordem 6 na filial 1 e na 2), então o número sozinho é ambíguo.

### Corrigido
- CORREÇÃO IMPORTANTE no monitoramento de ordens de compra: a versão anterior acusava 461 ordens paradas somando R$ 1,05 milhão, e 84% disso era falso positivo. O painel somava o valor recebido para decidir se a ordem tinha nota, mas esse campo vem vazio em parte dos registros — então ordem já faturada aparecia como nunca recebida. A maior de todas (R$ 259 mil, Ticket Log) tinha a nota vinculada e mesmo assim entrava no alarme; foi conferida na tela do próprio ERP. Agora o critério é a EXISTÊNCIA do vínculo com a nota, que é binária e confiável. O número real são 33 ordens e R$ 145 mil.
- Todas as 33 ordens paradas há mais de 180 dias já citam o número da nota na própria observação — ou seja, a mercadoria veio e foi faturada, e o que falta é amarrar a nota à ordem no ERP. A tela passou a mostrar isso num indicador próprio, para não cobrar entrega de fornecedor que já entregou.

## [0.16.0] — 24/08/2026  ·  CX-24/08/2026-v0.16.0

### Adicionado
- Ordens de Compra passou a monitorar o pedido que foi feito e nunca chegou: quantas OCs estão em aberto sem nota, há quanto tempo, de quais fornecedores e quais nunca foram aprovadas. São 648 ordens e R$ 2,0 milhões em aberto, das quais 461 (R$ 1,05 milhão) estão paradas há mais de 180 dias — a mais antiga é de junho de 2023.
- Lista das OCs mais antigas primeiro, com o fornecedor e o saldo que falta chegar, mais o ranking de fornecedores com pedido parado. É a ordem da cobrança: ou entrega, ou emite a nota, ou a ordem é cancelada.

### Corrigido
- As ordens SUSPENSAS no ERP ficam fora do alarme e aparecem num cartão à parte. Sem essa separação o painel acusaria 3.740 ordens e R$ 17,3 milhões em aberto, quando 83% disso está suspenso de propósito — seria transformar cadastro em crise, como já aconteceu com os rastreadores.
- O bloco ignora o filtro de período da tela e diz isso num selo visível: ordem emitida há dois anos e ainda sem nota é justamente o que se procura, e o filtro de emissão a esconderia.

## [0.15.0] — 24/08/2026  ·  CX-24/08/2026-v0.15.0

### Adicionado
- Nova tela no Financeiro: Fluxo de Caixa Consolidado, no formato da planilha de tesouraria que a equipe já usa. O saldo é encadeado (o final de um período é o inicial do seguinte) e pode ser consolidado por dia, semana, mês, trimestre ou semestre — a mesma informação para a decisão do dia e para a reunião de estratégia. Clicando no período abre a composição: entradas por tipo de documento e saídas por natureza.
- Os títulos VENCIDOS aparecem num bloco separado, como no rodapé da planilha, agrupados por natureza. São R$ 15,4 milhões, dos quais R$ 10,2 milhões são tributos — misturar isso no dia a dia faria a operação parecer inviável todos os dias.
- Três números de decisão no topo: necessidade operacional (o da tesouraria do dia), total vencido e necessidade geral (o da reunião de estratégia).
- Contas a Pagar e a Receber passaram a mostrar a composição por natureza. Dos R$ 69 milhões a pagar em aberto, 47% é dívida financeira (capital de giro e empréstimos) e 37% são tributos; fornecedores são 14%. O aging e a lista de maiores credores sozinhos faziam tudo parecer dívida de fornecedor.

### Corrigido
- Em horizonte longo (trimestre, semestre) os períodos sem faturamento lançado aparecem esmaecidos e hachurados, e ficam fora do cálculo da necessidade. Sem isso a tela mostrava uma queda de R$ 13 milhões que era ausência de dado — nota ainda não emitida — e não previsão de caixa.
- A tela declara o que ainda não enxerga (bloqueio judicial, cheques a compensar e conta investimento, que a planilha controla à mão), porque sem esses o saldo mostrado pode ser MAIOR que o disponível de verdade.

## [0.14.2] — 24/08/2026  ·  CX-24/08/2026-v0.14.2

### Corrigido
- O AutoDeploy não registra mais "ERRO" num deploy que deu certo. O arquivo de log fica aberto por quem o acompanha, e no Windows isso basta para a gravação falhar; a linha de sucesso caía no tratamento de erro e o log dizia o oposto do que tinha acontecido — a API estava no ar. Agora a gravação tenta de novo e, se ainda assim não conseguir, segue em silêncio: perder uma linha de log é irrelevante perto de marcar como falho um deploy bem-sucedido.

## [0.14.1] — 24/08/2026  ·  CX-24/08/2026-v0.14.1

### Corrigido
- O AutoDeploy voltou a funcionar: ele estava falhando a cada 2 minutos e por isso a API precisava ser reiniciada à mão a cada entrega. As tarefas agendadas rodam como SISTEMA e o repositório pertence ao usuário, o que faz o Git recusar a pasta por segurança ("dubious ownership") e devolver resposta vazia — o script quebrava logo depois, com uma mensagem que não dizia nada sobre a causa. Agora toda chamada ao Git autoriza a pasta explicitamente.
- Quando o Git não responde, o AutoDeploy passa a registrar no log o comando e o motivo em vez de um erro genérico — foi o que fez a falha passar despercebida por dias.
- O AutoDeploy só marca uma versão como implantada DEPOIS de confirmar que a API voltou a responder. Antes ele marcava assim que mandava reiniciar: se a API não subisse, o ciclo seguinte concluía que não havia nada novo e nunca mais tentava, deixando o painel fora do ar em silêncio.
- Atualização de dependências volta a ser aplicada no deploy. O AutoDeploy procurava o instalador apenas no perfil de quem executa, e como SISTEMA ele não existe lá — mudança de dependência passava com um aviso e a API subia sem o pacote novo.

## [0.14.0] — 24/08/2026  ·  CX-24/08/2026-v0.14.0

### Adicionado
- Nova tela no Financeiro: Antecipação de Recebíveis. Responde "quanto preciso antecipar para o caixa não furar", projetando o saldo DIA A DIA — o fluxo mensal escondia o buraco, porque um mês pode fechar positivo e quebrar no dia 5 se o grosso do recebimento cai no dia 25. A tela mostra o pior saldo do horizonte, em que dia ele acontece, quanto antecipar, quanto isso custa na taxa que você informar, e o plano operação a operação (qual vencimento puxar e quantos dias adianta).
- Filtros de horizonte (30 a 180 dias), reserva mínima de caixa e taxa de deságio. A reserva permite calcular para manter um colchão em conta, não só para não ficar negativo.

### Alterado
- A tela usa um saldo de partida mais restrito que o resto do painel: só contas ATIVAS e marcadas como "considerar fluxo de caixa" no cadastro do ERP. O Fluxo de Caixa soma todas as contas que aparecem no razão, o que hoje inclui contas operacionais que o próprio ERP manda ignorar (vale- pedágio, −R$ 2,89 mi) e uma conta que saiu do cadastro com saldo de 2014. A diferença entre as duas bases é de R$ 920 mil.

### Corrigido
- Contas a pagar e a receber já VENCIDAS ficam fora da projeção por padrão, dos dois lados, e o valor de cada uma aparece em aviso na tela. Havia R$ 15,9 milhões a pagar vencido — mais que os 90 dias futuros inteiros — concentrado em imposto parcelado; jogar isso no dia de hoje criaria um rombo que não corresponde à operação. Um filtro permite simular com eles.

## [0.13.0] — 24/08/2026  ·  CX-24/08/2026-v0.13.0

### Adicionado
- O CÓRTEX passou a enviar e-mail. Em Administração › Gestão › E-mail o administrador configura o servidor (host, porta, segurança, remetente), guarda a senha no mesmo cofre do token da Gobrax — de onde ela não volta para a tela — e dispara um teste para o próprio e-mail antes de confiar na configuração.
- Tela de últimos envios: tudo que o sistema tentou mandar, com autor, destinatário, assunto e resultado. A tentativa que FALHOU também aparece, com o motivo — é o registro dela que responde "o destinatário diz que não recebeu". Mensagem de erro traduzida para algo acionável (autenticação recusada, servidor fora do ar, remetente recusado) em vez do texto cru do servidor.

## [0.12.1] — 24/08/2026  ·  CX-24/08/2026-v0.12.1

### Alterado
- Na Régua de Cobrança, os títulos de cada cliente passaram a sair do mais antigo para o mais novo — que é a ordem em que se cobra. Antes saíam por valor, o que empurrava para o fim da lista dívida antiga de valor baixo (um cliente tinha um título parado há 320 dias fora das primeiras linhas). Quando a lista é cortada, o aviso agora diz que o que ficou de fora são os títulos mais recentes.

## [0.12.0] — 20/08/2026  ·  CX-20/08/2026-v0.12.0

### Adicionado
- Nova tela na Controladoria: Balanço Patrimonial (ativo, passivo, patrimônio líquido e liquidez corrente), com evolução mensal e o detalhe por grupo de conta. O dado já existia pronto no ERP (balancodemonstracaocontabil) e nunca tinha virado tela. A tela avisa em destaque quando o fechamento contábil disponível está atrasado — hoje o último fechado é dezembro/2025, 8 meses atrás — em vez de deixar parecer que é a posição de hoje.

## [0.11.0] — 20/08/2026  ·  CX-20/08/2026-v0.11.0

### Adicionado
- Lançamentos Bancários ganhou busca por nome no histórico — dá para achar tudo que foi recebido de um cliente ou pago a um fornecedor (ex.: buscar "Tupy" já cobre TED, PIX e boleto que citam o nome no histórico do banco). Não é uma busca por cadastro de cliente/fornecedor — o código que ligaria o lançamento ao cadastro está preenchido em menos de 0,1% dos casos — mas o texto do banco carrega o nome na maioria dos recebimentos e pagamentos por título.
- Extrato Bancário ganhou um card novo: Conciliação nativa do ERP. O AVA tem um feed automático de extrato bancário separado do import manual OFX/CSV desta tela, com farol próprio (Pendente/Conciliado/Oculto) marcado pela Contabilidade dentro do ERP. Hoje esse feed cobre só uma conta e 93,9% do que ela recebeu desde 2023 está Pendente — incluindo lançamentos deste mês, ou seja, não é só atraso histórico.

## [0.10.0] — 20/08/2026  ·  CX-20/08/2026-v0.10.0

### Adicionado
- Nova tela no Financeiro: Lançamentos Bancários. O painel só mostrava o SALDO diário de bancos e caixa; agora dá para ver o razão bancário lançamento a lançamento (crédito e débito, mês a mês, por conta e por categoria), com destaque para quanto do movimento é transferência entre contas próprias — que não é receita nem despesa.

## [0.9.0] — 19/08/2026  ·  CX-19/08/2026-v0.9.0

### Adicionado
- O Copiloto passou a enxergar as telas novas. Antes ele respondia sobre 12 recortes do painel; agora são 17 — entraram piso mínimo da ANTT, situação do RNTRC, consumo da telemetria contra o abastecimento, premiação de motoristas e previsão de fechamento do mês. Perguntar sobre qualquer uma delas deixou de cair em "não tenho esse dado".
- A lista de telas que o Copiloto conhece passou a sair do próprio cadastro de permissões, em vez de uma lista escrita à mão que envelhecia a cada tela nova. São 48 telas hoje, e tela nova entra sozinha.

### Alterado
- As respostas ficaram mais honestas sobre o que o Copiloto sabe: ele agora diz que enxerga um retrato de até 10 minutos atrás, não afirma tendência quando só tem o número de hoje, e avisa quando a fonte tem cobertura parcial em vez de dar o número como fechado.

### Corrigido
- O Copiloto respondia com erro quando a cadeia de modelos gratuitos tinha um modelo desativado no topo: dos preferidos, só dois ainda existiam. A lista foi limpa e o desempate passou a preferir o modelo maior.
- Com o ERP fora do ar, o Copiloto ficava até 4 minutos mudo antes da primeira palavra — cada uma das 17 fontes esperava o próprio tempo de desistência da conexão, uma depois da outra. Agora, à primeira falha de conexão, ele para de tentar as demais e responde com o que tem.

## [0.8.1] — 19/08/2026  ·  CX-19/08/2026-v0.8.1

### Corrigido
- O botão "Atualizar dados" da Premiação devolvia erro genérico quando a Gobrax não respondia: as rotas ainda tratavam o erro do cliente antigo, e qualquer falha virava "Erro ao atualizar a premiação" sem dizer o motivo.
- O comparativo mensal da Premiação não carregava — ainda pedia a média de consumo da frota, que a regra nova não calcula. Agora mostra o prêmio total e os motoristas premiados por mês, marcando com asterisco o mês que foi pago pela regra anterior.
- O rodapé do card da Premiação ainda descrevia a regra antiga (litros economizados × meta de consumo).

## [0.8.0] — 19/08/2026  ·  CX-19/08/2026-v0.8.0

### Adicionado
- Tela Consumo e Estatísticas: o km/l medido pela telemetria da Gobrax lado a lado com o km/l calculado pelos abastecimentos do ERP, por veículo, com a diferença entre as duas medidas.
- Tela Condução Econômica: faixa econômica, piloto automático e eco-roll de um veículo, com duração, percentual e nota, e os motoristas que estiveram nele no período.
- Tela Hodômetro e Rastro: leitura direta do odômetro de cada veículo, com a data da última leitura, e o trajeto do dia desenhado no mapa.

### Alterado
- A comparação de consumo só vale quando a telemetria cobriu a maior parte do período e quando as duas medidas são fisicamente possíveis. Veículo com rastreador mudo aparece como "telemetria incompleta", e não como divergência de consumo — sem essa regra, 25 veículos apareceriam como problema de combustível quando o problema é de sinal.

## [0.7.0] — 19/08/2026  ·  CX-19/08/2026-v0.7.0

### Adicionado
- Aba Integrações em Administração › Gestão: o token da Gobrax pode ser colado e trocado pela tela, sem editar arquivo no servidor nem reiniciar a API. O valor fica guardado na própria máquina com permissão restrita e nunca é devolvido para a tela — depois de salvo só se veem as pontas.
- Grupo Telemetria no menu, reunindo o que vem da plataforma Gobrax. A Premiação de Motoristas saiu de Frota e passou a viver nele.
- A Premiação passou a usar a nota da Gobrax e o km rodado, com valor por km, nota mínima e km mínimo configuráveis na própria tela.
- Quem não recebeu prêmio continua na lista, com o motivo — nota abaixo da mínima ou km abaixo do mínimo — e o detalhe de cada motorista mostra a conta que gerou o valor.

### Alterado
- A premiação deixou de ser calculada por litros economizados: a API pública da Gobrax não fornece a média de consumo por motorista. Meses já pagos continuam exibindo o valor com que foram pagos, e a tela avisa quando está mostrando um mês da regra antiga.
- A coleta deixou de fazer login na plataforma e passou a usar a API oficial com token: uma chamada por mês no lugar de quase cem, o que elimina o bloqueio por excesso de logins que já custou um mês de dados.

## [0.6.0] — 18/08/2026  ·  CX-18/08/2026-v0.6.0

### Adicionado
- Filtro por órgão autuador na tela de Multas: PRF, DER-SP, ANTT, DNIT e prefeituras aparecem no select com a contagem de autos de cada um.
- Coluna de vencimento no detalhe de cada veículo, com destaque para o que já venceu e o que vence em até sete dias, e a coluna do órgão que autuou.
- Indicador "Vencidos em aberto", com valor e quantos vencem na semana.

### Alterado
- O indicador de vencidos diz explicitamente que fala do CADASTRO e não do caixa: a baixa do auto quase nunca volta para o ERP, porque a defesa é conduzida por escritório externo. Serve para achar auto esquecido, nunca como saldo devedor.

## [0.5.0] — 18/08/2026  ·  CX-18/08/2026-v0.5.0

### Adicionado
- Tela RNTRC dos Transportadores: mostra quais transportadores contratados nos últimos 12 meses estão com o registro na ANTT fora de "ativo", e quanto já foi pago a cada um.
- Botão "Atualizar base da ANTT" busca a competência mais recente do cadastro nacional de transportadores e guarda apenas os que a Sulista contrata — o casamento é pelo número de registro, não por CNPJ ou CPF.
- A tela de Agregados e Terceiros ganhou a coluna RNTRC, com a situação do registro de cada transportador.

### Alterado
- Quem não aparece na base da ANTT conta como risco a investigar, e não como regular: a base pública só publica os registros ativos e pendentes, então um registro baixado simplesmente não aparece.

## [0.4.0] — 18/08/2026  ·  CX-18/08/2026-v0.4.0

### Adicionado
- Grupo ANTT no menu, com a tela Piso Mínimo de Frete: cada viagem paga a agregado ou terceiro é conferida contra o piso mínimo legal da ANTT vigente na data da viagem.
- A tela mostra quantas viagens ficaram abaixo do piso, para quais transportadores e quanto isso soma em exposição — com a cobertura sempre declarada, no formato "conferido em X de Y viagens".
- Veículo cujo tipo ou carroceria não permite deduzir número de eixos e tipo de carga aparece em "Pendências de cadastro", em vez de sumir da conta e inflar a aderência.
- Na tela de Agregados e Terceiros, cada transportador ganhou a coluna "vs piso ANTT", que mostra a exposição quando o mesmo período já foi conferido.

### Alterado
- Deslocamento vazio só é cobrado como retorno vazio obrigatório quando a carga é conteinerizada; nos demais casos a viagem entra como isenta e não conta contra o transportador.

## [0.3.0] — 10/08/2026  ·  CX-10/08/2026-v0.3.0

### Adicionado
- Botão de report no canto inferior direito de toda tela: relate um bug ou peça uma melhoria sem sair do painel.
- O report captura o print da tela pelo próprio navegador (fiel, com mapa e gráfico), aceita imagem colada com Ctrl+V, arquivo arrastado e até 5 anexos somando 15 MB.
- Cada report vira uma issue num repositório PRIVADO, já com a tela e os filtros que estavam ativos, a versão do sistema, o navegador, quem reportou e os erros de JavaScript recentes — antes de enviar, o modal mostra exatamente o que vai junto.
- Gravidade em três níveis, com rótulo que muda conforme seja bug ("Trava meu trabalho") ou melhoria ("Muito importante").

### Alterado
- O botão só aparece quando o servidor tem a configuração do GitHub; sem ela o recurso fica desligado, sem erro na tela.

## [0.2.0] — 08/08/2026  ·  CX-08/08/2026-v0.2.0

### Adicionado
- Indicador de carregamento em todas as telas e ações: barra animada sobre a borda da topbar, cobrindo as 41 cargas de tela e as ~37 ações internas (drill-down, ficha, exportação, modais).
- Contador de tempo decorrido a partir de 3 s ("consultando o banco… 12s"), para que consulta longa ao AVA não se leia como travamento.
- Tela Documentação (#doc) com o manual do sistema e o histórico de versões.
- Versão do build no rodapé da sidebar, no formato CX-DD/MM/AAAA-vX.Y.Z.
- CHANGELOG.md e versionamento SemVer a partir do docs/versoes.yaml.
- Integração contínua no GitHub Actions: a suíte inteira (Python, Node e a verificação estrutural do painel) passa a rodar a cada push e pull request.
- A verificação estrutural do index.html virou scripts/verificar_estrutura.py. Estava em scratchpad/, que é ignorado pelo git — o CLAUDE.md mandava rodá-la e ela nunca vinha no checkout.

### Alterado
- Torre de Controle e Saúde do Servidor: a recarga automática (120 s e 5 s) deixou de esmaecer a tela e de desabilitar o botão Atualizar. O clique manual continua acusando carregamento.

### Corrigido
- Ferramentas de teste (pytest, playwright) declaradas no grupo "test" do pyproject. Sem isso, um `uv sync` — que o AutoDeploy roda a cada mudança no pyproject — desinstalava as duas e levava a suíte junto.
- Topbar voltou a ficar fixa no topo ao rolar no celular, em todas as telas: a regra nova do indicador de carregamento vinha depois da regra de mobile no arquivo e a desligava.
- Torre de Controle não trava mais quando a recarga automática cai no meio de um clique em Atualizar — a tela ficava esmaecida e sem cliques até trocar de tela.
- Documentação da Saúde do Servidor mostrava 22 cards em vez de 7, com trechos de código e da tela de login misturados.
- A documentação passou a respeitar o perfil do usuário: cada um vê apenas as telas a que tem acesso, sem links para telas que não consegue abrir.
- Leitor de tela deixou de repetir o contador de segundos a cada tique durante uma consulta longa.
- No celular a versão do sistema não aparecia em lugar nenhum (ficava só no rodapé do menu lateral, que é escondido no mobile) e a Documentação estava enterrada dentro do acordeão de Administração. Agora as duas ficam no rodapé fixo da gaveta, e tocar na versão abre a Documentação.
- Documentação saiu de dentro de Administração, no menu e na gaveta — no celular ela aparecia duas vezes. Fica no rodapé, junto da versão.
- A versão no rodapé da gaveta deixou de aparecer colada nos botões e com moldura de item selecionado.
- Nome da empresa corrigido para Transportadora Sulista S/A na abertura da Documentação.
- Um teste do Extrato Bancário comparava uma data fixa com a data de hoje e quebraria sozinho na virada do dia, sem ninguém ter mexido em nada — foi o primeiro defeito que a integração contínua pegou.

## [0.1.0] — 08/08/2026  ·  CX-08/08/2026-v0.1.0

### Adicionado
- Marco do estado em produção. Painel com 45 telas sobre o ERP AVA (PostgreSQL 9.3, leitura via túnel SSH) e a folha no GLOBUS (Oracle): financeiro e fluxo de caixa, DRE gerencial e por cliente, comercial, operação e torre de controle, frota, jornada, suprimentos, RH e folha, orçamento, premiação de motoristas, extrato bancário, previsão de fechamento do mês, painéis de TV, copiloto e administração com RBAC.
- O histórico anterior a esta versão está nos commits, não aqui.
