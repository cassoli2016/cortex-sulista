# Changelog

Gerado de `docs/versoes.yaml` por `scripts/gerar_changelog.py` — não editar à mão.
Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [0.101.0] — 27/08/2026  ·  CX-27/08/2026-v0.101.0

### Adicionado
- Mais dois bancos locais foram para o PostgreSQL: as inscricoes de notificacao no celular (push) e a trilha de e-mails enviados. Com o RNTRC, sao tres dos dez - e nenhuma tela mudou de aparencia, que e o objetivo de uma migracao bem feita.

### Alterado
- Toda tabela do banco novo passou a levar o prefixo do modulo. A trilha de e-mail e a de antecipacoes se chamam "envios" nas duas origens: no banco unico elas disputariam o mesmo nome, e a segunda migracao apagaria a primeira. A colisao apareceu ao escrever a migration, antes de qualquer dado se perder.

### Corrigido
- O modulo de notificacao criava as tabelas no momento em que era carregado. Com o banco de arquivo isso nao custava nada; com o PostgreSQL, o banco fora do ar faria a API INTEIRA nao subir - por causa do recurso mais acessorio do sistema. As tabelas passam a nascer na primeira inscricao, e antes disso a tela mostra zero, que e a verdade.

## [0.100.0] — 27/08/2026  ·  CX-27/08/2026-v0.100.0

### Alterado
- As tabelas do Extrato Bancario passaram a mostrar o NOME do banco - Itau, Bradesco, Caixa, C6 - no lugar do codigo. Vale no cartao "Saldo nos bancos", na tabela "Situacao por conta", no seletor de conta e no cabecalho da conciliacao linha a linha. O nome sai da tabela de bancos do proprio ERP, a mesma que a Conciliacao nativa ja usava, entao banco novo aparece sozinho.
- O NUMERO da conta continua ao lado do nome, sempre. Nao e detalhe: a empresa tem duas contas no mesmo banco (duas no Bradesco e duas no Santander), e so o nome nao distingue uma da outra - foi exatamente essa confusao que fez duas contas serem vinculadas a conta errada do ERP. Razao social comprida e cortada com reticencias e aparece inteira no hover, com o codigo do banco e o vinculo com o ERP junto; o numero da conta nunca e cortado.
- Conta ainda sem vinculo com o ERP tambem mostra o nome do banco, tirado do proprio arquivo importado - e justamente quando falta o vinculo que se precisa saber de que banco a conta e, para escolher o certo. Com o ERP fora do ar a tela volta ao rotulo antigo, que ao menos traz o codigo.

## [0.99.2] — 27/08/2026  ·  CX-27/08/2026-v0.99.2

### Corrigido
- O validador repetia o mesmo agregado varias vezes. Cada campo virava uma linha propria, entao "sem procuracao cadastrada" e "sem certificado cadastrado" - que sao o mesmo item de trabalho - apareciam separados: 34 dos 38 agregados duplicados, 72 linhas para 38 problemas. Agora e uma linha por agregado em cada categoria, com os motivos juntos.
- A acao sugerida passou a sair da natureza da falta, e nao de um texto unico: certificado vencido se RENOVA, ausente se COLETA com o agregado e senha se CADASTRA no cofre. O texto unico mandava pedir ao agregado o arquivo que ja estava aqui.

## [0.99.1] — 27/08/2026  ·  CX-27/08/2026-v0.99.1

### Adicionado
- O backup do banco novo virou tarefa agendada de verdade (scripts/instalar_tarefa_backup.ps1, diaria as 03:20), e ela aparece na lista de tarefas da Saude do Servidor. Script de backup que ninguem roda e pior que nao ter backup, porque parece que tem.

### Corrigido
- O primeiro uso do banco local nao funcionava: para saber se o banco respondia, o sistema perguntava em que versao o schema estava - e num banco recem-criado essa tabela ainda nao existe. O erro subia como "sem conexao" e o comando se recusava a aplicar justamente a criacao da tabela. Agora sao duas perguntas separadas, e banco de pe com schema vazio aparece como "aplicar as migrations", nao como banco caido.

## [0.99.0] — 27/08/2026  ·  CX-27/08/2026-v0.99.0

### Adicionado
- Botao "Varrer o ERP agora" na tela de CT-e de Contrapartida. A consulta sempre foi ao vivo; o que faltava era poder repetir sem trocar um filtro nem recarregar a pagina. O rotulo muda para "Varrendo o ERP..." enquanto roda, porque a consulta leva segundos e o esmaecimento da tela sozinho nao distingue consultando de travado. O rodape passou a dizer a hora da varredura.
- A fila passou a colocar em QUARENTENA o CT-e que a SEFAZ ja recusou tres vezes com o mesmo retorno, e o aviso diz quantos sao e por que. Rejeicao nao muda sozinha: o mesmo documento, com o mesmo cadastro, sera recusado igual para sempre.

### Corrigido
- A FILA ESTAVA TRAVADA. Tres CT-e impossiveis de autorizar em homologacao eram reapresentados a cada rodada; como sao os mais antigos, ficavam no topo, e as tres recusas seguidas disparavam o disjuntor toda vez. Os documentos atras deles NUNCA chegaram a ser tentados. Cada um ja tinha sido recusado 14 vezes quando isso foi percebido.
- Data e hora na tela agora seguem dd/mm/aaaa hh:mm:ss. A tabela de documentos transmitidos mostrava "27T13:51:03/08/2026": a hora vinda com o separador ISO nao era separada da data. Os segundos aparecem quando a origem os tem - completar com ":00" o que veio so com minuto inventaria precisao, e num registro fiscal isso mente sobre a ordem dos eventos.

## [0.99.0] — 27/08/2026  ·  CX-27/08/2026-v0.99.0

### Adicionado
- Comecou a migracao dos dez bancos locais para um PostgreSQL na propria maquina, um por vez. O plano inteiro - o que migra, o que nao migra, em que ordem e por que - esta em docs/MIGRACAO_POSTGRES.md. O RNTRC da ANTT e o primeiro: 223 linhas, o menor risco possivel para provar o caminho.
- A Saude do Servidor ganhou a linha do banco novo, ao lado da replica do ERP e do Oracle da folha. Sao tres bancos agora, e a tela diz qual e qual: sem o banco local configurado a instalacao segue inteira no SQLite (Info); configurado e fora do ar, as telas ja migradas ficam sem dado (Falha, em vermelho).
- Backup do banco novo com pg_dump e retencao de 14 dias (scripts/backup_cortex.ps1). Enquanto o dado morava em SQLite, backup era copiar um arquivo; o script existe ANTES do primeiro store migrar porque, na ordem inversa, a mudanca pioraria a seguranca do dado - e pioraria calada.

### Alterado
- Nas telas ja migradas, banco fora do ar deixou de virar "sem base". No RNTRC isso era grave: "sem base" significa "nunca sincronizou", e um modulo de compliance dizendo isso com o banco caido faria parecer que ninguem foi conferido - quando na verdade nada pode ser afirmado. Tabela que ainda nao existe continua sendo base vazia; falha de conexao sobe como erro.

## [0.98.0] — 27/08/2026  ·  CX-27/08/2026-v0.98.0

### Adicionado
- Validador do cadastro na tela de CT-e de Contrapartida: roda, agregado por agregado, as mesmas conferencias que a emissao vai fazer - antes dela. Cada linha diz o que esta errado E o que fazer, porque os motivos pedem coisas diferentes de pessoas diferentes.
- Os achados vem separados por categoria e a lista abre em CADASTRO NO ERP, que e o que se resolve digitando. Sem isso, os 76 achados de "sem certificado" - verdadeiros, e ja contados no cartao de prontidao - afogariam os 9 de cadastro.
- A contradicao INVERSA passou a aparecer: agregado com inscricao estadual valida marcado como nao contribuinte. Nao impede a emissao hoje, mas decide se ele entra ou nao na fila, e passava despercebido porque so se olhava para a falta de inscricao.
- Quem esta marcado como nao contribuinte sai da lista de impedimentos e vai para uma categoria propria. Nao ha o que corrigir: ele nao emite CT-e por natureza do documento, e mante-lo como pendencia criaria uma fila que ninguem consegue zerar.

### Alterado
- O codigo de rejeicao da SEFAZ so aparece onde foi MEDIDO na transmissao (229, inscricao do emitente). Nos demais campos o efeito e descrito sem numero - dar codigo a um palpite faria a tela parecer mais certa do que e.

## [0.97.0] — 27/08/2026  ·  CX-27/08/2026-v0.97.0

### Adicionado
- O cronometro ganhou dois estados que faltavam. "Parada" em vermelho quando a biblioteca de assinatura nao esta instalada - nenhum documento sai enquanto isso durar. E "atrasado", com o tempo acumulado, quando a hora da proxima rodada passou de dois disparos do agendador: sinal de que a tarefa nao esta rodando. Antes os dois casos apareciam como "liberado", que se le como se estivesse tudo bem.

### Corrigido
- TODO DEPLOY DESLIGAVA A EMISSAO. A biblioteca que assina e transmite estava declarada num grupo opcional, e a atualizacao automatica do servidor nao instala grupo: sempre que uma dependencia mudava, ela era DESINSTALADA e a emissao parava. Sem sinal nenhum - a rotina continuava passando na hora certa e cada documento morria por dentro. Ficou parada das 12h35 as 13h10 de hoje exatamente assim. A pilha fiscal virou dependencia de producao, que e o que ela e desde que o sistema passou a emitir de verdade.
- A rotina agendada agora confere essa biblioteca ANTES de marcar que passou. Antes ela marcava a passagem e so depois falhava documento a documento, o que de fora e identico a "nao havia nada para emitir". Agora sai com erro, o agendador do Windows registra a falha e o cronometro da tela passa a acusar atraso.

## [0.96.0] — 27/08/2026  ·  CX-27/08/2026-v0.96.0

### Adicionado
- A tela de CT-e de Contrapartida ganhou o cronometro da emissao automatica: quanto falta para a proxima rodada, quando foi a ultima passagem, o intervalo configurado e em que ambiente ela esta emitindo. O relogio corre de segundo em segundo sem consultar o servidor - o estado e buscado a cada 30 segundos, que e o que basta para perceber que a rotina rodou.
- O cartao diz que sao DOIS relogios. O agendador do Windows dispara de 5 em 5 minutos e o CORTEX so entao pergunta se ja passou o intervalo, entao a emissao pode sair ate 5 minutos depois do cronometro zerar. Sem isso escrito, o contador chega a zero, nada acontece e a tela parece travada. Ao zerar ele mostra "liberado", nao "00:00".
- Com a automacao desligada o cronometro PARA, em vez de contar para um disparo que nao vem, e diz onde se liga. Emissao manual nao depende dele - sao interruptores diferentes.

## [0.95.0] — 27/08/2026  ·  CX-27/08/2026-v0.95.0

### Adicionado
- A emissao automatica do CT-e de contrapartida passou a rodar de verdade. A tarefa agendada do Windows nunca tinha sido criada: o interruptor na tela estava ligado, o intervalo configurado, e nada chamava a rotina. Agora a tarefa dispara de 5 em 5 minutos e quem decide se e hora continua sendo o CORTEX, lendo o intervalo da tela.
- A fila do lote passou a conferir a INSCRICAO ESTADUAL do agregado antes de emitir, do mesmo jeito que a tela ja conferia. O resumo da fila diz quantos ficaram de fora por isso, separado de quem nao tem certificado - sao pendencias de areas diferentes.

### Corrigido
- O CT-e de agregado do Parana era recusado com "851 - Endereco do site da UF da Consulta via QR Code diverge do previsto". O endereco do QR Code estava sendo colado depois do endereco do servidor da SEFAZ, virando uma URL dentro da outra no documento assinado. So acontecia em estado com SEFAZ propria; Sao Paulo nunca passou por esse caminho. Com a correcao saiu a primeira autorizacao do Parana.
- A rotina automatica ignorava o intervalo configurado e rodava a cada disparo do agendador - de 5 em 5 minutos, fosse qual fosse o valor escolhido na tela. Ela nunca registrava a propria passagem, entao toda execucao se achava a primeira. A passagem passou a ser marcada ANTES de emitir: lote que trava no meio nao volta a disparar em cinco minutos.
- Agregado com certificado valido mas SEM inscricao estadual no cadastro do ERP entrava na fila e era recusado pela SEFAZ documento a documento, ate o disjuntor de tres falhas seguidas derrubar o lote inteiro - e levar junto os agregados que estavam certos e vinham depois na fila.
- O cartao "Ler com atencao" abria afirmando que nenhuma contrapartida havia sido emitida ate hoje. Era um texto fixo, escrito quando era verdade, e continuou la depois das primeiras emissoes - inclusive a de producao. Agora ele sai da contagem real e separa o que foi emitido em homologacao (sem valor fiscal) do que valeu.

## [0.95.0] — 27/08/2026  ·  CX-27/08/2026-v0.95.0

### Adicionado
- O Extrato Bancario passou a ler o extrato do C6, que so existe em PDF - aquele banco nao oferece OFX no internet banking. Era a unica conta que nao aparecia como divergente e sim como ausente, por nao ter como entrar. O arquivo traz o saldo ao fim de cada dia movimentado, e a tela confere sozinha se esse saldo bate com o movimento; quando nao bater, ela avisa, porque e o sinal de que o banco mudou o layout do relatorio.
- Conciliacao LANCAMENTO A LANCAMENTO, num cartao novo da mesma tela. A comparacao que ja existia diz se o dia bate no total; esta diz qual lancamento do extrato e qual linha do razao do ERP, e o que sobrou dos dois lados. Casa por mesmo dia e mesmo valor, e depois por mesmo valor a ate tres dias de distancia - que e o atraso de compensacao e, sozinho, fecha a conta do Sicredi por inteiro.
- Cada dia recebe um diagnostico em vez de so um numero: "conciliado", "so granularidade", "diverge", "ERP nao lancou" e "so no ERP". A distincao que mais muda o trabalho e a do meio: e comum sobrar linha dos dois lados e o valor do dia fechar mesmo assim, porque o razao lanca em detalhe o que o banco mostra agrupado - na Caixa, um dia tem 15 linhas no extrato contra 372 no razao e a diferenca e de tres centavos. Isso nao e pendencia, e a tela diz isso com todas as letras.
- Cartao "Saldo nos bancos" no topo da tela: quanto ha em cada conta segundo o extrato, ao lado da ultima posicao que o ERP tem da mesma conta, e a diferenca. E a primeira pergunta de quem sobe o extrato todo dia. Ele NAO segue o filtro de periodo da tela de proposito - saldo e posicao, nao movimento de janela.
- Coluna "Envio", que diz por conta se o extrato esta em dia. A conta e em dias UTEIS pulados, nao corridos: a rotina e subir o extrato do dia anterior, entao sabado, domingo e o proprio dia de hoje nao contam.
- O total dos bancos declara o que ficou de fora: quantas contas nao tem saldo utilizavel (essas ficam FORA da soma, marcadas "nao informado" - um saldo ausente nunca vira R$ 0,00) e, quando as posicoes sao de dias diferentes, ele avisa em vez de fingir uma foto de um instante so. A diferenca contra o ERP so sai em vermelho quando as duas posicoes sao do MESMO dia: em dias distintos ela mistura divergencia com defasagem de lancamento.

### Alterado
- O resumo da importacao passou a dizer tudo o que aconteceu com o arquivo: alem de novos e duplicados, quantos lancamentos futuros ficaram de fora, quantos saldos do banco entraram e se a conferencia do PDF nao fechou.

### Corrigido
- A importacao de extrato descartava lancamento em silencio. Sete arquivos reais de agosto (Bradesco, Caixa, Itau, Safra, Santander e Sicredi) mostraram 53 de 756 lancamentos sumindo, contados na tela como "duplicados" - so na Caixa foram 50, somando R$ 2,46 milhoes de credito, com TEDs de R$ 287 mil, R$ 327 mil e R$ 377 mil entre eles. A causa: o identificador de transacao do arquivo, que deveria ser unico por conta, vinha repetido (a Caixa grava ali o codigo do banco de origem da TED). A identificacao de duplicata deixou de depender so desse campo.
- Itau e Safra mandam o SALDO do dia como se fosse um lancamento, e ele entrava somando. O movimento do mes do Itau aparecia como R$ 157 mil quando o real e R$ 4 mil - trinta e nove vezes maior. Agora essas linhas viram ancora de saldo, o que melhora a conferencia em vez de piorar: as duas contas passaram de um unico saldo conferido no mes para dezoito.
- Enviar o extrato dia a dia corrompia o saldo de dias ja importados. O arquivo de cada dia repete o saldo final do banco, e ele costuma vir com a data de um dia ANTERIOR - entao o envio de hoje reescrevia o saldo de ontem. No Safra o efeito era trocar R$ 657,38 (o saldo da conta corrente, que e o que o ERP guarda) por R$ 10.502,92 (a posicao consolidada, com a aplicacao junto): a conta passava a divergir em R$ 9.845,54 por um numero que o proprio arquivo ja tinha certo. So acontecia no envio diario.
- O arquivo de COMPROMISSOS do Bradesco (DARF, boletos e conta de luz com vencimento futuro) e identico ao do extrato e entrava como se fosse movimento realizado. Pior: fazia o sistema achar que a conta estava em dia para sempre, porque o "ultimo dia com extrato" passava a ser uma data futura e o aviso de extrato velho nunca mais disparava. Lancamento com data futura agora fica de fora e e informado no resumo da importacao.
- O saldo do Bradesco nao aparecia na comparacao. O arquivo grava a data do saldo zerada, e o sistema aceitava isso como um dia que nao existe - entao aquele saldo nunca casava com dia nenhum do ERP e sumia sem aviso.
- O aviso de "extrato sem atualizacao" so acendia depois de SETE dias corridos. Numa rotina diaria isso e uma semana inteira de silencio, e ainda castigava a segunda-feira, quando tres dias corridos de atraso sao zero dia util. Agora acende ao pular mais de um dia util, e o alerta diz os dois numeros - "ha 4 dias sem extrato (1 dia util de movimento sem enviar)". Feriado bancario nao e conhecido pelo sistema e aparece como um dia de atraso.

## [0.94.0] — 27/08/2026  ·  CX-27/08/2026-v0.94.0

### Adicionado
- A coluna de autorizacao na fila por agregado ganhou o estado VENCIDO, separado de "nao autorizado". Sao situacoes diferentes e pedem acoes diferentes: nao autorizado e cadastro que FALTA, vencido e cadastro que EXISTE e caducou - um se preenche, o outro se renova. Quem esta pronto mas com vencimento proximo aparece em ambar com o prazo, em vez do verde liso de antes.
- As colunas da fila por agregado passaram a ordenar por clique no cabecalho, com a seta indicando o sentido. Coluna numerica comeca decrescente e coluna de texto crescente, que e o que se espera de cada uma.
- Cadastro e autorizacao ordenam por URGENCIA e nao por texto: pendente antes de completo, e vencido antes de nao autorizado. Ordenar essas duas alfabeticamente nao ajudaria ninguem.

### Alterado
- A ordenacao acontece sobre a lista que ja esta na tela, sem refazer a consulta - o ERP leva segundos para responder e reordenar nao muda o dado. O rodape diz por qual coluna e em que sentido a lista esta.

## [0.93.1] — 27/08/2026  ·  CX-27/08/2026-v0.93.1

### Corrigido
- A suite de testes falhava NO SERVIDOR e passava na maquina de quem nunca configurou nada. O teste do "modo nao configurado" da Premiacao limpava so a variavel de ambiente, e o cofre da tela de Gestao vence a variavel: onde existe token guardado de verdade, a integracao continuava ligada e o teste acusava falha que nao existia.

## [0.93.0] — 27/08/2026  ·  CX-27/08/2026-v0.93.0

### Adicionado
- Botao de CANCELAR em cada documento transmitido e autorizado. Pede a justificativa, confirma antes - cancelar nao se desfaz - e some quando o documento ja esta cancelado, que aparece com marcador proprio.
- Linhas de evento (cancelamento) aparecem marcadas e ficam fora da contagem de transmissoes: evento nao e documento, e conta-lo junto inflaria a fila e estragaria a taxa de retorno.

### Alterado
- O marcador de PRODUCAO nos documentos transmitidos ficou verde.

### Corrigido
- O botao de reativar o envio de um agregado nao funcionava - o clique dava erro e nada acontecia. A funcao estava escrita na margem esquerda, mas DENTRO de outra: indentacao nao define escopo, e o clique de um botao e avaliado no escopo global, onde ela nao existia.
- O registro do cancelamento ficava sem protocolo. O evento REGISTROU na SEFAZ, mas a leitura da resposta procurava um nivel que so existe no retorno de autorizacao - e a segunda tentativa, recusada por duplicidade, trazia o protocolo do primeiro no proprio texto. Agora esse protocolo e extraido, e duplicidade de evento passa a contar como cancelado: o evento existe, so nao foi aquele envio que o criou.

## [0.93.0] — 27/08/2026  ·  CX-27/08/2026-v0.93.0

### Adicionado
- A Saude do Servidor passou a acompanhar tambem a Gobrax e a Monkey. Antes so a Prolog aparecia entre as integracoes de fornecedor: telemetria parada ou portal de antecipacao sem coletar nao apareciam em lugar nenhum, e a tela envelhecia calada.
- Gobrax: competencia, quantos veiculos e ha quanto tempo foi a coleta. Vale sempre a MAIS ATRASADA entre estatisticas e odometro - as duas se cruzam na Torre, e uma fresca ao lado de outra parada faz o cruzamento mentir sem parecer. Passar de duas janelas da tarefa agendada (3 em 3 horas) vira alerta; foi assim que o cache ficou cinco dias parado sem ninguem notar.
- Gobrax sao DUAS credenciais no mesmo fornecedor - o token move a telemetria e o login do portal move a premiacao - e uma pode estar de pe com a outra caida. Faltando o login, a linha avisa que a nota x km parou de atualizar mesmo com a telemetria em dia.
- Monkey: quantos titulos, qual o saldo e de quando e a posicao gravada - que e a que a tela de Antecipacoes mostra. AMBIENTE DE HOMOLOGACAO vira alerta explicito: os titulos sao de teste e a tela de Antecipacoes nao tem como saber isso sozinha.

### Alterado
- Integracao sem credencial aparece como "Info", nunca como falha - o recurso apenas nao existe nesta instalacao, e vermelho todo dia treina quem opera a ignorar alarme. Quando falta algo, a linha diz o que falta e onde configurar.
- Nenhuma dessas linhas consulta a API do fornecedor: Prolog tem cota, Gobrax leva 73 segundos por volta e a tela recarrega de 5 em 5 segundos. O que se mede e a idade do instantaneo que as telas mostram.

## [0.92.0] — 27/08/2026  ·  CX-27/08/2026-v0.92.0

### Adicionado
- Cancelamento de CT-e ja autorizado. Ato fiscal com PRAZO: passado o prazo da UF o documento nao se cancela mais, e resolve-se por outros meios, mais caros. A justificativa tem minimo de 15 caracteres - exigencia da SEFAZ, e o que alguem vai ler daqui a um ano para entender por que o documento caiu.
- Cancelar NAO exige a liberacao de producao. Liberar existe para impedir que se EMITA sem querer; exigi-la para cancelar seria pedir para destravar a emissao a fim de corrigir uma emissao. Desfazer tem de ser mais facil que fazer.
- O ambiente do cancelamento sai do REGISTRO do documento, nao de quem chama: cancelar em homologacao um documento de producao nao faz nada e daria a impressao de ter resolvido.
- O CT-e emitido em duplicidade foi CANCELADO e a SEFAZ confirmou: consultado o documento, o duplicado responde "cancelamento homologado" e o valido segue autorizado.

### Corrigido
- A leitura da resposta do evento procurava um nivel que so existe no retorno de autorizacao. O cancelamento REGISTROU na SEFAZ e o sistema leu como falha - a segunda tentativa e que revelou, ao ser recusada por duplicidade de evento. Falha silenciosa que dizia o contrario do que acontecera.

## [0.91.0] — 27/08/2026  ·  CX-27/08/2026-v0.91.0

### Adicionado
- PRIMEIRO CT-e DE CONTRAPARTIDA EMITIDO EM PRODUCAO, autorizado pela SEFAZ de Sao Paulo. Emitido pelo agregado RODRIGO ANTONIO PARIZOTTO contra a Sulista, referenciando o CT-e de origem. Documento real, com valor fiscal.

### Corrigido
- O ambiente viajava como TEXTO no sistema e a biblioteca o comparava como NUMERO. Producao caia no endereco de homologacao dizendo ser de producao, e a SEFAZ recusava com uma mensagem que nao aponta onde esta o erro ("Ambiente informado diverge do Ambiente de recebimento").
- O protocolo de autorizacao era remontado a partir do objeto lido, e saia com o nome da CLASSE no lugar do nome do elemento - arquivo que nao importa em lugar nenhum. Agora e guardado exatamente como a SEFAZ enviou, que e o que se arquiva.
- A verificacao de "ja existe contrapartida para este CT-e" vivia so no caminho em LOTE; o caminho de um documento passava por fora. Foi assim que a mesma prestacao ganhou DOIS documentos autorizados em producao. A guarda passou para o ponto por onde todo envio passa, e vem ANTES de reservar numero de serie - barrar depois ja teria gasto um.
- Repetir a emissao para a mesma origem agora exige pedido explicito, e a recusa diz qual documento ja existe e lembra que o primeiro continua valendo ate ser cancelado.

## [0.90.0] — 27/08/2026  ·  CX-27/08/2026-v0.90.0

### Adicionado
- Botao de ATIVAR e DESATIVAR envio por agregado, na linha de cada certificado. Serve para testar com um de cada vez e para tirar da fila quem esta sendo recusado sempre - sem apagar certificado nem autorizacao, que sao registros de outra natureza e nao deveriam ser removidos por conveniencia operacional. Cada mudanca fica na trilha com autor e data.
- A contagem da fila passou a mostrar quantos CT-e estao fora por envio desativado, separado de quantos estao fora por falta de certificado. Sao motivos diferentes e pedem acoes diferentes.

### Alterado
- Este interruptor e o unico do modulo em que a AUSENCIA de registro significa LIGADO. Nos outros o padrao seguro e desligado; aqui o padrao seguro e o comportamento de hoje, porque um padrao desligado esvaziaria a fila em silencio - e fila vazia parece trabalho concluido.

## [0.89.0] — 27/08/2026  ·  CX-27/08/2026-v0.89.0

### Adicionado
- Botao de DOWNLOAD em cada documento transmitido, na tela. Baixa o arquivo completo - XML assinado com o protocolo -, que e o que o ERP importa e o que se arquiva. Aparece so onde ha arquivo guardado.
- Documento recusado nao gera arquivo: o download responde "nao existe" em vez de devolver um XML vazio, que seria um arquivo com cara de valido.

### Alterado
- Ao emitir para o Parana a SEFAZ recusou com "IE do emitente nao informada". Nao e defeito: e o orgao confirmando o que a tela ja apontava - aquele agregado esta entre os 17 sem inscricao estadual, e sem inscricao nao se emite CT-e.

### Corrigido
- A emissao para agregado do PARANA morria ANTES de chegar a SEFAZ. Cada estado descreve o campo do envio de um jeito: Sao Paulo aceita o pacote comprimido como texto simples, e o Parana exige que ele venha tipado. Mas trocar para o formato do Parana quebrava Sao Paulo, que passava a recusar com "falha na descompactacao". Agora o envio tenta o caminho simples - o provado - e so troca de formato quando a UF reclama do tipo. Conferido nos dois: Sao Paulo autorizou, Parana chegou a SEFAZ.
- Adaptar na hora em vez de manter uma lista de estados: lista de UF com excecao envelhece calada, e o defeito volta na primeira UF nova.

## [0.88.0] — 27/08/2026  ·  CX-27/08/2026-v0.88.0

### Adicionado
- A SEFAZ AUTORIZOU o primeiro CT-e de contrapartida com o grupo da Reforma Tributaria - protocolo 135260006389275, em homologacao. Era o bloqueio que restava do lado tecnico.
- O que destravou foi um XML do proprio ERP, de um CT-e da Sulista autorizado em PRODUCAO. Ele mostrou tres coisas que nenhuma consulta tinha revelado.
- PRIMEIRA: a aliquota do IBS da UF nao estava zerada - estava numa tabela PROPRIA, que o sistema nao lia. Havia uma tabela de IBS geral com aliquota zero, e outra so do IBS da UF com 0,1000. Lendo a errada, a emissao parava dizendo que o imposto nao estava configurado, quando estava.
- SEGUNDA: o IBS MUNICIPAL nao existe neste ERP e vem zerado - e a SEFAZ aceita assim. Nao e pendencia de cadastro, e como a operacao e hoje.
- TERCEIRA: a base do IBS/CBS EXCLUI os tributos que ele vem substituir - ICMS, PIS e COFINS. A regra foi conferida em seis documentos, todos exatos. Antes o sistema usava o valor cheio, o que declararia imposto a mais.

### Alterado
- Descoberto no caminho um segundo problema, ainda em aberto e sem relacao com o IBS: a emissao para agregado do PARANA falha no envio, antes mesmo de chegar a SEFAZ. O envio compactado que Sao Paulo aceita e recusado na montagem da mensagem para o Parana. Sao Paulo segue funcionando.

### Corrigido
- O aviso de que o IBS nao estava configurado deixou de existir, porque a premissa dele estava errada. No lugar ficou uma verificacao por documento: aliquota zerada agora aponta para o imposto vinculado AQUELE CT-e, e lembra que a definicao de exportacao e zero por natureza.

## [0.87.0] — 27/08/2026  ·  CX-27/08/2026-v0.87.0

### Adicionado
- Grafico de documentos transmitidos por dia na tela de CT-e de Contrapartida, com 30 dias. Sao QUATRO series empilhadas e nao duas: homologacao e producao nao se somam, porque uma nao tem valor fiscal, e autorizado e recusado tambem nao, porque recusado nao emitiu nada. Juntar qualquer par produziria uma barra que parece trabalho feito e nao e.
- Indicador de RETORNO DA SEFAZ: o percentual de transmissoes autorizadas, com a contagem embaixo e quantas foram em producao. Verde a partir de 95, ambar de 70 a 94, vermelho abaixo.
- Cartao de faixas de vencimento dos certificados - vencido, ate 15 dias, 16 a 30, 31 a 60, mais de 60. As duas ultimas linhas aparecem separadas porque NAO sao faixa de prazo: "sem validade informada" nao tem data, e A3 nao se resolve esperando.

### Alterado
- Sem nenhuma transmissao, o retorno da SEFAZ mostra travessao e nao "0%". Zero por cento de acerto sem nenhuma tentativa e um numero que acusa alguem por um trabalho que nao existiu.
- O cartao de "contrapartidas emitidas" deu lugar ao de retorno: ele dizia "nenhuma rotina de emissao no ar", o que deixou de ser verdade, e a contagem de producao virou subtitulo do novo.

## [0.86.0] — 27/08/2026  ·  CX-27/08/2026-v0.86.0

### Adicionado
- Exportacao dos CT-e de contrapartida para importar no ERP. Sai um arquivo por documento no formato completo - o XML assinado MAIS o protocolo de autorizacao -, que e o que um importador espera: o documento sozinho nao prova que foi autorizado.
- O protocolo passou a ser guardado em XML, e nao so o numero. Sem ele a autorizacao existe e nao se prova: nao da para importar, arquivar nem responder a uma fiscalizacao.
- Arquivos separados por AMBIENTE, em pastas diferentes. Misturar homologacao com producao e o caminho mais curto para alguem importar um documento de teste como se valesse.
- Nomeados pela CHAVE, que e como todo importador de CT-e procura, e o que impede um documento de sobrescrever outro. Reexportar e seguro: reescreve o mesmo arquivo com o mesmo conteudo.

### Alterado
- Documento recusado NAO vira arquivo. Um processo montado sobre documento recusado seria um arquivo com cara de valido - e alguem o importaria.
- A exportacao conta a parte os autorizados SEM arquivo guardado. Hoje sao 12: foram emitidos antes de o sistema passar a guardar o XML, entao nao ha o que gerar. Sem esse numero, o total exportado pareceria menor do que deveria sem explicacao.
- Os arquivos ficam em data/, que esta fora do controle de versao - o repositorio do codigo e publico e documento fiscal carrega CNPJ, valor e chave. Ha teste garantindo que ninguem reexclua essa pasta do ignore.

## [0.85.2] — 27/08/2026  ·  CX-27/08/2026-v0.85.2

### Corrigido
- O controle de vencimento de certificado mostrava apenas UM dos dois cadastrados - e escondia justamente o que vence primeiro. A lista saia dos agregados COM CT-e no periodo, e a tela abre no dia de hoje: quem simplesmente nao rodou hoje desaparecia do controle. Certificado vence no calendario, nao na janela que a tela esta mostrando.
- O cartao passou a listar TODOS os certificados cadastrados, e leva um selo dizendo que ignora o filtro de periodo - card que nao segue os filtros tem de anunciar isso, senao o numero parece furado.
- O volume continua sendo do periodo, porque e ele que responde "quanto para se este certificado vencer". Mas quem nao teve movimento no recorte aparece como "fora do periodo" em vez de zero: zero e "nao rodou", nao "nao importa", e a diferenca some se o numero aparecer pelado.

## [0.85.1] — 27/08/2026  ·  CX-27/08/2026-v0.85.1

### Corrigido
- O GitHub mandava e-mail de falha a cada envio. Cinco testes novos, os do IBS/CBS, montavam o documento sem o marcador que os faz pular quando as bibliotecas fiscais nao estao instaladas. Aqui na maquina passavam, porque o grupo esta instalado; no servidor de testes - que instala exatamente o que producao instala - quebravam todos. O aviso chegou por e-mail, nao pela suite, que e o pior jeito de descobrir.
- Entrou uma guarda que le a propria suite e acusa qualquer teste que monte documento sem estar protegido. Ela distingue CHAMAR de mencionar - um teste que so inspeciona a assinatura da funcao nao precisa das bibliotecas - e aceita tanto o marcador quanto um pulo proprio.

## [0.85.0] — 27/08/2026  ·  CX-27/08/2026-v0.85.0

### Adicionado
- Controle de vencimento dos certificados digitais na tela de CT-e de Contrapartida. Certificado A1 vale UM ANO: vencendo em silencio, a emissao para sozinha e a empresa descobre pelo agregado.
- O semaforo e GRADUADO e nao binario - vencido, ate 15 dias, ate 30, ate 60 -, porque "vence em 2 dias" e "vence em 29" pedem acoes diferentes e um aviso igual para os dois nao prioriza nada. Sessenta dias e o momento de comprar, nao de correr.
- A lista mostra o VOLUME que cada certificado sustenta, e ordena por urgencia e, dentro dela, por volume. Sem isso a ordem por data esconde o que importa: um certificado que vence em 40 dias e responde por metade da fila urge mais que um vencendo em 10 que nunca emitiu nada. O caso real de hoje e esse - o certificado que vence primeiro sustenta 822 CT-e do trimestre.
- Validade nao informada NAO conta como "ok": conta como desconhecida, em vermelho. Tratar ausencia de data como boa noticia e exatamente o que faz a emissao parar sem aviso. Certificado A3 aparece como IMPEDIMENTO e nao como prazo - ele mora em token fisico e nao se resolve esperando.
- Certificado sem a senha no cofre e marcado na propria linha: sem ela o arquivo nao assina, e a data de validade sozinha daria a impressao de que esta tudo certo.

## [0.84.0] — 27/08/2026  ·  CX-27/08/2026-v0.84.0

### Adicionado
- Tarefa agendada da emissao do CT-e de contrapartida (scripts/instalar_tarefa_contrapartida.ps1). Ela dispara de 5 em 5 minutos, mas NAO emite de 5 em 5 minutos: ela PERGUNTA se e hora, lendo o intervalo configurado na tela. Mudar o intervalo em Administracao > Integracoes tem efeito imediato, sem reinstalar tarefa nenhuma.
- Instalar a tarefa e seguro mesmo com tudo desligado: se a automacao estiver desligada, o script sai sem fazer nada. A tarefa existir nao liga a emissao - sao dois interruptores diferentes, e o segundo esta na tela.
- A tarefa tambem NAO escolhe o ambiente. Deixar homologacao ou producao no argumento criaria uma segunda fonte da verdade que ninguem lembraria de conferir - o ambiente sai da mesma tela.

### Alterado
- Quando nao e hora de rodar, o script sai com sucesso e nao com erro: para o Windows a tarefa foi bem-sucedida, e o historico do agendador nao enche de "falha" a cada cinco minutos.
- A passagem da rotina e registrada mesmo quando nada foi emitido - o que se mede e a rotina ter rodado, nao o resultado. Sem isso, um periodo sem fila faria a tarefa tentar de novo a cada cinco minutos.
- Carimbo de ultima execucao ilegivel faz a rotina RODAR, nao travar: um valor corrompido nao pode deixar a emissao parada indefinidamente.

## [0.83.0] — 27/08/2026  ·  CX-27/08/2026-v0.83.0

### Adicionado
- Os interruptores da emissao sairam da linha de comando e foram para a tela, em Administracao > Integracoes: trocar de HOMOLOGACAO para PRODUCAO, ligar ou desligar a emissao AUTOMATICA e definir de quanto em quanto tempo a rotina roda. So administrador enxerga e muda.
- O intervalo da rotina agora e configuravel, de 5 minutos a 24 horas, com uma hora de padrao. Valor fora dos limites e RECUSADO em vez de aparado em silencio: quem digitou 1 minuto quis dizer alguma coisa, e gravar 5 caladamente esconderia isso. O piso existe porque cada execucao consulta o ERP, le o cadastro inteiro e conversa com a SEFAZ - rodar de minuto em minuto nao emite mais rapido, ja que a fila so cresce quando um CT-e novo e digitado.
- O cartao mostra o ambiente ativo, se a automacao esta ligada, de quanto em quanto tempo, e QUEM mudou cada coisa e quando - que e a informacao procurada meses depois.

### Alterado
- Trocar para producao pela tela exige a mesma frase de confirmacao da linha de comando, e o campo so aparece quando se esta indo para producao. Pedir a frase sempre treinaria a digita-la por reflexo, que e o oposto do atrito que ela existe para criar. Voltar para homologacao nao pede nada.
- O AUTOR da mudanca sai da sessao no servidor, nunca do corpo do pedido: quem responde por ligar producao nao pode ser um campo que o proprio cliente preenche. Ha teste garantindo isso.
- Configuracao corrompida ou ausente cai sempre no lado seguro - ambiente de homologacao e automacao desligada. Banco novo ou backup restaurado nao comeca emitindo documento de verdade.

## [0.82.0] — 26/08/2026  ·  CX-26/08/2026-v0.82.0

### Adicionado
- Os DOIS AMBIENTES da emissao passaram a existir: homologacao, que segue sendo o padrao de tudo, e producao. Homologacao e o ambiente de teste da SEFAZ - o documento autorizado la nao tem valor fiscal, nao e escriturado e nao gera obrigacao. Producao emite documento real, em nome de outra empresa.
- Producao NASCE TRAVADA e nao destrava sozinha. Liberar exige uma frase de confirmacao digitada por inteiro, e fica registrado quem liberou e quando. A frase existe porque uma opcao de linha de comando e facil demais de digitar por engano, e o engano aqui custa cancelamento e retificacao: CT-e autorizado errado nao se apaga - cancela-se, dentro de prazo, com justificativa, e repercute na escrituracao dos dois lados.
- DESLIGAR producao nao pede frase nenhuma. Desligar e sempre seguro e nao pode depender de lembrar de uma frase no meio de um problema.
- O teto do lote em producao e MENOR que em homologacao (50 contra 500): lote errado em teste custa tempo, em producao custa cancelamento documento a documento. Comecar devagar e o comportamento correto do primeiro dia.
- A numeracao ja era separada por ambiente, entao o primeiro documento de producao nao nasce com um numero gasto em teste.

## [0.81.0] — 26/08/2026  ·  CX-26/08/2026-v0.81.0

### Adicionado
- Emissao em LOTE do CT-e de contrapartida: a rotina varre o periodo, monta e transmite os documentos da fila, um agregado de cada vez, em ordem cronologica. Continua so em homologacao.
- A emissao MANUAL funciona sempre. A execucao DESASSISTIDA - rotina agendada, sem ninguem olhando - so roda se alguem tiver ligado, e o padrao e DESLIGADO. Ausencia de configuracao significa desligado, nunca o contrario: um padrao ligado faria a rotina comecar a emitir sozinha por causa de um banco novo ou de uma restauracao de backup. Ligar e desligar entra na trilha com autor e data.
- Quatro guardas que a emissao manual nao precisa, porque la existe uma pessoa lendo o retorno. IDEMPOTENCIA: nunca emite duas vezes para o mesmo CT-e de origem, e so conta como feita a que foi AUTORIZADA - uma tentativa recusada nao emitiu nada. DISJUNTOR: tres falhas seguidas param o lote, porque falha sistemica rejeita tudo e um lote de mil queimaria mil numeros de serie antes de alguem perceber. TETO por execucao, obrigatorio. E ENSAIO, que percorre tudo sem transmitir.
- O disjuntor foi conferido contra o bloqueio real do IBS: o lote parou no terceiro documento e preservou os dois restantes.
- A fila ja desconta quem nao pode emitir. No periodo testado, dos 494 CT-e de agregado PJ, 390 sao de agregado sem certificado - contar esses prometeria um trabalho que falharia documento a documento.

## [0.80.0] — 26/08/2026  ·  CX-26/08/2026-v0.80.0

### Adicionado
- No lugar entrou PRONTIDAO DA FILA, que olha para a frente: de tudo que entrou no periodo, quanto da para emitir agora e o que trava o resto. Separa DOIS PORTOES que sao diferentes e costumam ser confundidos - ter o CADASTRO completo (inscricao, RNTRC, municipio) e estar AUTORIZADO (certificado A1 valido, senha no cofre, autorizacao vigente). Cadastro impecavel sem certificado nao emite nada, e hoje e o caso de 29 dos 31 com cadastro em ordem.
- Os travados aparecem separados por um detalhe que muda o encaminhamento: quem esta sem inscricao mas marcado como CONTRIBUINTE de ICMS e contradicao de cadastro (se e contribuinte, tem inscricao - da para corrigir), e quem esta marcado como NAO CONTRIBUINTE e coerente, e provavelmente sai da fila em vez de virar pendencia eterna.
- As barras sao proporcionais ao VOLUME DE CT-e e nao ao numero de agregados, e o rodape diz isso: dois agregados autorizados respondem por um quinto da fila, e uma barra por contagem esconderia justamente isso.

### Alterado
- O bloco de PASSIVO ACUMULADO saiu da tela de CT-e de Contrapartida, e o aviso que o citava tambem. CT-e nao se emite retroativo - a SEFAZ recusa data fora da janela -, entao aquele numero nunca virava trabalho: so ocupava espaco numa tela cuja pergunta e "o que preciso emitir agora". O valor segue registrado no documento da contabilidade, que e onde ele serve, e a tela ficou mais rapida por uma consulta a menos - ela varria desde 2022.

## [0.79.1] — 26/08/2026  ·  CX-26/08/2026-v0.79.1

### Corrigido
- O sistema ficava TRAVADO. A tabela de transmissoes da versao anterior foi escrita por substituicao de texto que atravessou DUAS funcoes e comeu uma chave de fechamento: o JavaScript parou de compilar e, no navegador, isso nao quebra so aquela tela - mata o script inteiro no carregamento, e o app inteiro fica parado. Quem encontrou foi o usuario.
- Nada pegava esse tipo de defeito: a verificacao de estrutura olha atributos e classes do HTML, o smoke conta cartoes, e os testes de tela carregavam a pagina sem falhar por erro de console. Entrou teste que compila o JavaScript do arquivo, e outro que conta o bloco novo para acusar duplicacao - a mesma fatia que quebrou o arquivo tambem havia duplicado o trecho.

## [0.79.0] — 26/08/2026  ·  CX-26/08/2026-v0.79.0

### Adicionado
- O XML ASSINADO de cada transmissao passou a ser guardado. Sem ele um documento autorizado nao se reconstroi: a chave e o protocolo provam que ele existe, mas quem precisa IMPORTAR no ERP, arquivar ou responder a uma fiscalizacao precisa do arquivo. A tela mostra, documento a documento, se o arquivo esta guardado - e conta a parte quantos foram autorizados SEM ele, que e a situacao a corrigir.
- A tabela de transmissoes ganhou cor e as colunas que faltavam: situacao com o codigo e o motivo da SEFAZ, chave (abreviada, inteira ao passar o mouse), protocolo e arquivo. Verde so quando a SEFAZ autorizou; todo o resto e vermelho, porque codigo diferente de autorizado significa que NADA foi emitido - um tom intermediario faria "recusado" parecer "quase la". Homologacao segue com marcador proprio e fora da contagem de emitidas.

### Corrigido
- A trilha das transmissoes gravava o e-mail pessoal de quem rodou o comando. Passou a gravar a identidade do sistema (noreply@sulista.com.br) quando a emissao parte de script ou rotina - quem executa na bancada varia, e a trilha tem de dizer que foi o CORTEX. Emissao pela TELA continua exigindo o usuario logado, e nao ha valor padrao para isso.

## [0.78.0] — 26/08/2026  ·  CX-26/08/2026-v0.78.0

### Adicionado
- O CT-e de contrapartida passou a montar o grupo de IBS/CBS da Reforma Tributaria, que a SEFAZ comecou a exigir no meio dos testes de hoje. Situacao tributaria, classificacao e aliquotas saem do que o ERP JA calcula - a mesma regra do ICMS, nada inventado. Entrou junto o total do documento eletronico, que a SEFAZ passou a cobrar na mesma leva.
- A base do IBS/CBS e o valor DESTE documento. Nao se tentou reproduzir a base que o ERP usa no CT-e da Sulista: la o total carrega taxas, pedagio e seguro, e a base observada (R$ 1.340,00 sobre R$ 1.494,02) nao sai de nenhuma combinacao desses componentes - ha uma regra que nao conhecemos. O documento do agregado tem um componente so.

### Corrigido
- ACHADO QUE PASSA DO NOSSO MODULO: o IBS nao esta configurado no ERP. Existe UMA aliquota cadastrada, zerada, com o imposto marcado como nao configurado - enquanto a CBS ja esta, com 0,9. A SEFAZ recusa aliquota de IBS zerada, e a emissao para com essa explicacao em vez de tentar e levar rejeicao. Vale o alerta: essa mesma configuracao serve a emissao da PROPRIA Sulista no dia em que o orgao ligar a validacao em producao.
- Comentario dentro de consulta SQL nao pode conter o sinal de porcentagem: o driver o interpreta como marcador de parametro e a consulta nem chega ao banco. Custou uma rodada.

## [0.77.1] — 26/08/2026  ·  CX-26/08/2026-v0.77.1

### Corrigido
- A tela de CT-e de Contrapartida abria com "Erro ao montar a conciliacao". Ao acrescentar a contagem de transmissoes, a linha que faz esse calculo nao entrou no lugar certo - o resultado era usado sem existir, e a tela inteira caia. Quem encontrou foi o usuario, no celular.
- A suite passava com 209 testes verdes. O motivo e que os testes exercitavam as PECAS da tela - formatacao, avisos, serializacao - e nenhum chamava a montagem inteira, que e o que a tela chama. Entrou teste que roda o caminho todo com o banco simulado e serializa o resultado, mais um que derruba de proposito o registro de transmissoes para garantir que a conciliacao continua aparecendo sem ele.

## [0.77.0] — 26/08/2026  ·  CX-26/08/2026-v0.77.0

### Adicionado
- A tributacao do CT-e de contrapartida passou a sair do proprio ERP, documento a documento, como a area pediu. A regra tem duas fontes e a ordem importa: o REGIME DO EMITENTE manda - optante do Simples nao destaca ICMS, ponto - e, nao sendo optante, aproveita-se a situacao tributaria e a aliquota que o ERP ja calculou para aquela rota. Copiar a situacao do CT-e da Sulista para um agregado optante poria destaque de imposto num documento que nao pode ter.
- Situacao tributaria que nao esteja no de-para PARA a emissao dizendo qual e, em vez de traduzir por semelhanca - traduzir codigo fiscal por parecenca e inventar tributacao. E operacao marcada como tributada com aliquota zero tambem para: emitir assim declararia imposto zero onde ha imposto.
- Tela de CT-e de Contrapartida mostra agora os DOCUMENTOS TRANSMITIDOS - quando, por quem, em que ambiente, serie e numero, o retorno da SEFAZ e o protocolo. Homologacao aparece com marcador proprio e NAO entra na contagem de emitidas: e ambiente de teste, o documento nao tem valor fiscal, e somar os dois faria a tela anunciar uma fila resolvida que nao foi.

### Corrigido
- A SEFAZ de Sao Paulo passou a exigir IBS/CBS (Reforma Tributaria) no CT-e durante os proprios testes de hoje: uma transmissao autorizou e a seguinte, minutos depois, voltou com "310 - IBS/CBS nao informado". A emissao esta bloqueada por isso ate que o grupo seja montado. O dado existe no ERP - os 2.395 CT-e do ultimo mes tem os impostos de IBS, CBS e IBS municipal vinculados - entao vale a mesma decisao de aproveitar o que ja esta calculado, mas as aliquotas e a classificacao tributaria precisam de confirmacao antes de virar documento.

## [0.76.0] — 26/08/2026  ·  CX-26/08/2026-v0.76.0

### Alterado
- Confirmado que o valor do contrato de transporte no PEF e a COLUNA DO FRETE DE COMPRA - a mesma que o sistema ja usava. A definicao do valor esta fechada e NENHUM codigo precisou mudar. Fica so a CST do ICMS pendente do lado fiscal.
- Antes de confirmar, procuramos um valor de PEF proprio na base, e vale registrar por que nenhum serve: o PEF do embarque cobre 65% das viagens e seu campo de valor soma R$ 26,37 no total; o PEF do acerto cobre 4,4% com valores sem proporcao estavel; as parcelas de adiantamento estao vazias; e o valor total de frete do transporte chega a 3,7 vezes o valor do CT-e. Emitir por qualquer um deles produziria documento varias vezes maior que a operacao - e a SEFAZ autorizaria, porque ela nao sabe quanto vale o servico.
- Fica registrado o efeito da definicao, que nao e pendencia mas e consequencia: emitindo pelo valor pago, os documentos passam a registrar formalmente o frete praticado, e no trimestre as viagens de agregado foram pagas em R$ 14,7 milhoes contra um piso minimo da ANTT de R$ 18,7 milhoes - 78,6% do piso, com 89% das viagens conferidas abaixo do minimo legal. Hoje isso so existe no controle interno; a partir da emissao, passa a existir documento a documento.

## [0.75.0] — 26/08/2026  ·  CX-26/08/2026-v0.75.0

### Adicionado
- Criterio de rateio definido e implementado: quando varios CT-e dividem a mesma viagem, cada um recebe a MESMA FATIA que teve no valor cobrado dos clientes naquela viagem. Com isso os 48% da fila que estavam retidos passaram a ser emitiveis - um deles ja foi autorizado pela SEFAZ em homologacao: viagem com 8 documentos, R$ 1.591,50 pagos ao agregado, e o CT-e saiu com R$ 46,11 por representar 2,9% do que se cobrou na viagem.
- Os outros criterios (peso, valor da mercadoria, partes iguais) NAO foram implementados, de proposito. Todos fecham a soma, entao nenhum "erra" numa conferencia - o que muda e quanto imposto cada documento carrega. Num caso real de 3 CT-e numa viagem de R$ 3.398,36, o mesmo documento valeria R$ 201,70 por peso e R$ 1.132,79 em partes iguais: 5,6 vezes. Trocar tem de ser decisao registrada, nao conveniencia de codigo.

### Alterado
- O arredondamento acontece DEPOIS de ratear e por documento: cada CT-e e independente, emitido em momento proprio, e nao um lote que precise fechar. A soma das fatias pode diferir do valor da viagem em centavos, e isso e do arredondamento.
- Dois casos continuam parando em vez de emitir: viagem com valor cobrado total zero (nao ha proporcao a calcular) e CT-e com valor cobrado zero dentro de uma viagem com outros documentos - pelo criterio ele receberia R$ 0,00, e documento fiscal de valor zero nao e prestacao.

## [0.74.0] — 26/08/2026  ·  CX-26/08/2026-v0.74.0

### Adicionado
- A resposta veio como "o valor pago a ele (frete minimo)", e os dois nomes NAO descrevem o mesmo numero. Medimos: no trimestre, as viagens de agregado foram pagas em R$ 14,7 milhoes contra um piso minimo da ANTT de R$ 18,7 milhoes para as mesmas viagens - 78,6% do piso, com 5.081 de 5.735 viagens conferidas (89%) pagas ABAIXO do minimo legal.
- A escolha tem consequencia direta e por isso voltou como pergunta: pelo valor efetivamente pago, cada documento passa a registrar formalmente um frete abaixo do piso legal, um a um; pelo piso da ANTT, o valor do documento nao bate com o que o financeiro pagou. O sistema nao arbitra entre os dois.

### Alterado
- A contabilidade reviu a base do valor: o CT-e do agregado sai pelo VALOR PAGO A ELE, e nao mais pelo cobrado do cliente. A mudanca foi aplicada, e com ela o rateio volta a ser necessario - o pagamento e lancado por VIAGEM e o documento e por CT-e, entao os 3.159 de 6.594 CT-e do trimestre (48%) que dividem viagem com outro documento voltam a ficar retidos ate que o criterio de divisao seja definido.
- Os 52% restantes - os CT-e que sao o unico documento da viagem - nao dependem desse criterio e podem seguir.

## [0.73.0] — 26/08/2026  ·  CX-26/08/2026-v0.73.0

### Adicionado
- Base do valor definida (em carater provisorio): o CT-e do agregado sai pelo valor COBRADO DO CLIENTE. Com isso o rateio deixa de existir - cada documento ja tem o seu proprio valor, e os 48% que dividiam viagem com outro documento deixam de ser problema. Um CT-e que o sistema recusava justamente por esse motivo ja foi emitido e autorizado em teste.
- Levantamento de prontidao da fila, que ninguem tinha: dos 47 agregados PJ com movimento no trimestre, TODOS tem RNTRC e CEP cadastrados, e dos 2.372 CT-e do ultimo mes nenhum esta sem nota fiscal com chave. Ou seja, o unico bloqueio de cadastro que sobrou sao os 17 sem inscricao estadual.

### Alterado
- Os 17 agregados sem inscricao estadual sairam do rodape e passaram a ser o CAMINHO CRITICO: eles respondem por 1.872 dos 6.375 CT-e do trimestre (29% da fila). Nao e questao fiscal, e cadastral - ou o cadastro esta desatualizado, ou eles realmente nao emitem CT-e e saem da conta.
- Os outros 30 agregados estao PRONTOS: cerca de 4.500 documentos no trimestre, R$ 13,4 milhoes de prestacao, sem nenhuma pendencia. Assim que a CST for definida, da para comecar por eles sem esperar os 17.
- O documento da contabilidade foi enxugado: sobrou UMA pergunta fiscal (a CST) e um levantamento de cadastro. O que ja foi decidido continua no texto, marcado como respondido, para nao perder o historico.

## [0.72.0] — 26/08/2026  ·  CX-26/08/2026-v0.72.0

### Adicionado
- Enquadramento do CT-e de contrapartida DEFINIDO: nao ha dispensa (o agregado emite) e a operacao e SUBCONTRATACAO. Com isso restam duas definicoes, e sao a mesma conversa - a base do valor e a CST do ICMS.
- Achado que so apareceu ao emitir em trecho real, e que muda a maioria dos documentos: quando a viagem COMECA fora do estado onde o agregado e inscrito, o CFOP passa obrigatoriamente para a familia 932. A SEFAZ recusa qualquer outro ("524 - CFOP invalido, informar 5932 ou 6932"). Isso nunca aparece nos CT-e da Sulista, porque a filial que emite e sempre a da origem; com o agregado como emitente vira a MAIORIA - ele e inscrito num estado e roda em todos.
- A distribuicao no trimestre: 3.694 documentos (58%) usam 6932; 1.931 (30%) usam 6351; 724 (11%) usam 5351; e 17 usam 5932. Um CFOP fixo, como estava, erraria seis em cada dez documentos. O sistema passou a escolher sozinho, e os dois casos principais ja foram autorizados pela SEFAZ em homologacao.

### Corrigido
- O CFOP era um valor unico e fixo. Alem da familia 932 acima, faltava o basico: 5xxx dentro do mesmo estado e 6xxx cruzando divisa. Entrou tambem uma guarda que recusa trocar um pelo outro - a SEFAZ ACEITA o documento com o CFOP do trecho errado, entao quem reclamaria seria a fiscalizacao, meses depois.
- O documento da contabilidade foi reorganizado: o que ja foi respondido aparece marcado como tal, o historico das recusas virou anexo no fim, e a unica pergunta viva - a base do valor - ganhou secao propria explicando o que sao os dois numeros, por que a escolha nao e indiferente e por que ela arrasta um criterio de rateio para metade da fila.

## [0.71.0] — 26/08/2026  ·  CX-26/08/2026-v0.71.0

### Adicionado
- A aba Integracoes da Gestao passou a ter um CARTAO POR FORNECEDOR - Gobrax, Prolog, Monkey Exchange e o servidor de e-mail - com o estado de cada um no titulo: ativa, incompleta ou desligada. Antes era uma lista unica de 22 campos, todos com a mesma cara.
- Cada cartao diz o que a integracao alimenta ("alimenta Pneus"), como esta autenticando no momento e o que exatamente falta para ligar. O topo da aba conta quantas estao ativas e chama pelo nome a que alguem comecou e nao terminou - integracao pela metade deixa a tela que ela alimenta sem dado, calada.
- Seletor de FORMA DE AUTENTICACAO no cartao de quem aceita mais de uma. A Prolog aceita token, usuario e senha ou OAuth2, e mostrar os onze campos de uma vez fazia a integracao inteira parecer desconfigurada. So os campos da forma escolhida aparecem, e a que ja esta pronta leva selo.
- Aviso de PRECEDENCIA ao trocar de forma: o sistema usa a primeira que estiver completa, entao preencher o OAuth2 com um token ja salvo nao troca nada. Sem esse aviso o operador configurava e jurava que nao funcionava.
- Campo de configuracao (ambiente, URL base, ids de filial, cabecalho do token) agora aparece PREENCHIDO e da para conferir - eles nao sao segredo, e mascarar "hmg" como pontinhos so impedia enxergar o que estava valendo. Token, senha e client_secret continuam entrando e nunca voltando da tela.

### Alterado
- A senha do SMTP nao e mais pedida em dois lugares. Na aba Integracoes ela aparece so no panorama, com o caminho para a aba E-mail, onde ficam servidor, porta, remetente e a trilha de envio.
- Salvar agora e por fornecedor e manda so o que mudou, em vez de um botao por campo. Campo de segredo em branco significa "nao mexi", nunca "apague" - apagar continua sendo o link ao lado do proprio campo.

### Corrigido
- "Limites de credito contratados", no Fluxo de Caixa, voltou a carregar e a salvar. O codigo das integracoes tinha funcoes com o MESMO NOME das do cartao de limites (credCarregar/credSalvar) e, como a tela e um script so, a segunda declaracao vencia a primeira: a tabela de limites ficava vazia e "Salvar limites" caia no cofre de tokens, reclamando de token nao colado.
- Saiu da tela o campo "Codigo da empresa na Prolog", que era oferecido para preenchimento e nenhum codigo do sistema lia.

## [0.70.0] — 26/08/2026  ·  CX-26/08/2026-v0.70.0

### Adicionado
- Serie 900 aprovada e em uso: o primeiro CT-e de contrapartida da serie nova foi autorizado pela SEFAZ em homologacao. Serie alta e reservada afasta a colisao com o que o agregado ja emita por conta propria - e numero repetido e rejeitado documento a documento, no meio de um lote de milhares, sem que se possa levantar antes o que cada um ja gastou.

### Alterado
- Perguntaram se o tomador nao poderia sair do CT-e original. Nao diretamente: o tomador do NOSSO documento e quem contratou a Sulista, e o documento do agregado precisa dizer quem contratou o AGREGADO - sao elos diferentes da mesma cadeia. Mas a pergunta levou a uma resposta melhor: em 5.987 dos 6.596 CT-e do trimestre (91%) o pagamento da viagem sai da Sulista para o dono do veiculo. Quem contrata e paga e a Sulista, e isso o ERP ja registra.
- Com isso, "prestacao normal" fica descartada pelos FATOS e nao por preferencia: o tomador e a Sulista, e a SEFAZ so aceita a Sulista nessa posicao em subcontratacao ou redespacho. A pergunta a contabilidade encolheu de tres opcoes para duas.
- E um dado que ajuda a escolher entre as duas: o redespacho pressupoe carga ja em transito, entregue a outro transportador para completar o percurso. Nos CT-e de agregado, apenas 28 de 6.365 (0,4%) registram documento de transporte anterior - em praticamente todos, o agregado faz o percurso inteiro.

## [0.69.0] — 26/08/2026  ·  CX-26/08/2026-v0.69.0

### Adicionado
- Chegaram as primeiras respostas da area sobre o CT-e de contrapartida, e uma delas foi testada contra a SEFAZ antes de virar codigo. A resposta "prestacao normal" e INCOMPATIVEL com o que o modulo se propoe: nesse enquadramento o orgao nao aceita a Sulista como tomadora (rejeicao 746) nem o vinculo com o CT-e dela (747). O documento sairia contra o CLIENTE, e sem nada que o ligue ao nosso CT-e - ou seja, deixaria de ser contrapartida. A unica combinacao que a SEFAZ autorizou E descreve a operacao real e a subcontratacao. O documento da contabilidade foi atualizado pedindo a reconfirmacao, com a tabela do que foi testado.
- As duas combinacoes recusadas viraram GUARDA no codigo, com o numero da rejeicao e a consequencia de negocio na mensagem. Sem isso, cada uma custaria uma transmissao e um numero de serie queimado para ser redescoberta - e o texto da SEFAZ, sozinho, nao diz o que esta em jogo.
- Sugestao de serie e numeracao, que a area pediu: serie 900, exclusiva, numeracao propria por agregado. Serie alta e reservada afasta de vez a colisao com o que o agregado ja emita por conta propria (numero repetido e rejeitado documento a documento) e deixa auditavel, so de olhar, que aquele documento saiu pela Sulista em nome dele.

### Alterado
- Com a decisao "um documento por CT-e", medimos o tamanho do problema de rateio: 3.159 dos 6.594 CT-e do trimestre - QUASE METADE - dividem a viagem com outro documento, e o valor pago ao agregado e lancado por viagem. Se a base do valor for o que a Sulista paga, metade da fila precisa de um criterio de rateio; se for o que ela cobra do cliente, o problema desaparece. As duas perguntas estavam separadas no documento e na verdade sao uma so.

## [0.68.1] — 26/08/2026  ·  CX-26/08/2026-v0.68.1

### Adicionado
- Documento para a contabilidade em docs/contrapartida-perguntas-contabilidade.md, escrito para ser encaminhado: o que precisa ser definido antes de emitir o CT-e do agregado, na ordem em que as respostas destravam o trabalho, e com os numeros medidos. A primeira pergunta e se ha dispensa de emissao pelo subcontratado - se houver, nao existe fila nenhuma a emitir e todas as outras perguntas caem.

### Corrigido
- A suite de testes ficava VERMELHA no servidor por dependencia que producao nao instala de proposito. Os testes que montam o CT-e precisam do grupo fiscal, e um deles chegava a derrubar a coleta inteira - a suite parava de rodar por completo, e nao so aquele teste. Agora eles sao pulados com o motivo dito, e o resto roda.

## [0.68.0] — 26/08/2026  ·  CX-26/08/2026-v0.68.0

### Adicionado
- A SEFAZ de Sao Paulo AUTORIZOU o primeiro CT-e de contrapartida emitido pelo agregado RODRIGO ANTONIO PARIZOTTO contra a Sulista, em ambiente de HOMOLOGACAO: "100 - Autorizado o uso do CT-e", protocolo 135260006358665. A pilha inteira esta provada de ponta a ponta - montagem, assinatura com o certificado do agregado, QR Code, compressao, transmissao e leitura da resposta.
- Homologacao e o ambiente de teste da SEFAZ: o documento autorizado la NAO tem valor fiscal, nao escritura nada e nao gera obrigacao para ninguem. Producao continua FECHADA no codigo, com a razao escrita no proprio erro - depende do enquadramento fiscal, que a contabilidade ainda nao respondeu.
- Toda transmissao fica registrada com quem, quando, ambiente, numero, chave e o retorno da SEFAZ. Assinar em nome de terceiro tem de ser respondivel meses depois, inclusive contra o proprio CORTEX. E a numeracao e separada por ambiente, senao o primeiro CT-e de producao nasceria com um numero gasto em teste.
- Tres guardas antes de qualquer assinatura: autorizacao vigente e certificado valido do agregado; conferencia de que o CNPJ do emitente do documento e o dono do certificado; e numero inedito na serie.

### Corrigido
- Chegar ao "autorizado" custou seis rejeicoes da SEFAZ, e nenhuma delas aparece numa validacao local - o schema aceita o documento sem esses campos, quem os exige e a regra de negocio. Faltavam as notas fiscais transportadas (693), o remetente e o destinatario (469) e o QR Code (850).
- Em homologacao a razao social carimbada e a do REMETENTE e a do DESTINATARIO, nao a do tomador - e a grafia e "CTE EMITIDO...", sem hifen, diferente da que a nota fiscal usa. Com o hifen a rejeicao e a MESMA de nao ter carimbado nada, o que faz a tentativa parecer sem efeito.
- Mais dois defeitos no caminho de CT-e da biblioteca, ambos invisiveis na consulta de status e so visiveis ao emitir de verdade: a serializacao desviava ate texto simples para o caminho novo (e a assinatura serializa uma segunda vez), e o envio comprimido era tratado como se fosse XML.

## [0.67.1] — 26/08/2026  ·  CX-26/08/2026-v0.67.1

### Corrigido
- Na tela de CT-e de Contrapartida, os blocos "Volume por mes", "Passivo acumulado" e "Ler com atencao" corriam de borda a borda do cartao. As barras encostavam nos dois lados e o texto da direita chegava a ser CORTADO pela borda - "617 TAC" aparecia sem o C. Os tres entravam no cartao como div cru, e o cartao nao tem espacamento proprio de proposito: cada bloco poe o seu, e estes tres nao punham.
- O espacamento lateral casa com o do titulo do cartao. Barra que comeca antes do titulo que a nomeia faz o cartao parecer torto mesmo com a borda perfeita.
- O vao ate a borda de baixo era diferente nos tres (10px num, nenhum no outro, 8px no terceiro), porque cada bloco pendurava uma margem propria na ultima barra. Agora o espacamento entre barras e do container, entao a ultima nao pendura nada e os tres cartoes fecham igual.

## [0.67.0] — 26/08/2026  ·  CX-26/08/2026-v0.67.0

### Adicionado
- O CORTEX passou a MONTAR o CT-e de contrapartida do agregado. O documento sai completo a partir da chave do CT-e que a Sulista emitiu, e valida contra o schema oficial da SEFAZ com um unico erro: falta a assinatura. Ela falta de proposito - montar o documento e uma coisa, assinar como terceiro e outra, e a segunda continua fora do modulo, com teste de arvore sintatica garantindo.
- O que o ERP responde sozinho, e que ninguem vai digitar: razao social, inscricao estadual, RNTRC e endereco do agregado; CNPJ, inscricao e endereco da filial que emitiu o original; municipio de inicio e fim; peso, valor da carga e a chave do CT-e de referencia.
- Certificado do agregado RODRIGO ANTONIO PARIZOTTO conferido contra a SEFAZ de SAO PAULO: "107 - Servico em Operacao". A prova anterior tinha sido feita com o certificado de outro agregado, entao o dele ainda nao tinha conversado com a SEFAZ da UF dele.

### Alterado
- O enquadramento fiscal continua pendente com a contabilidade, e o codigo foi escrito para que isso nao possa ser esquecido: as seis definicoes (CFOP, tipo de servico, grupo e CST de ICMS, base do valor, tomador e se referencia o CT-e original) sao campos obrigatorios sem NENHUM valor padrao. Nao ha caminho de codigo que monte um CT-e sem alguem ter respondido as seis.
- Evidencia nova para essa conversa, tirada do proprio ERP: em 90 dias, 30 CT-e da Sulista sao emitidos com CFOP 6351 e tipo de servico "subcontratacao", com tomador que nao e nem remetente nem destinatario. Ou seja, a propria Sulista ja emite hoje um documento com exatamente esta forma quando ela e a subcontratada. O documento do agregado contra a Sulista e o espelho desse caso.
- Duas medidas que mudam o tamanho da fila e vao para a mesma conversa. O valor que a Sulista PAGA ao agregado nao esta no CT-e - esta no embarque (no CT-e piloto, R$ 1.066,32 contra R$ 1.494,02 de prestacao cobrada do cliente). E o embarque nao e um por CT-e: em 90 dias, 6.578 CT-e de agregado PJ vieram de 3.834 embarques, 1,7 por embarque. Quando o embarque tem mais de um documento, a montagem PARA em vez de ratear: dividir por conta propria inventaria base de ICMS.

### Corrigido
- O CEP do ERP e um numero INTEIRO, e por isso perde o zero da frente: Santo Andre volta como 9280200 em vez de 09280200. Em Sao Paulo isso vale para o estado inteiro. CEP com sete digitos e rejeicao na validacao do documento, e o erro nao diz que o problema e o zero.
- Nao existe codigo de municipio do IBGE no cadastro do ERP, e o CT-e identifica a prestacao por ele. O codigo e buscado pelo NOME do municipio, que o cadastro grava sem acento (SANTO ANDRE) e a tabela oficial grava com (SANTO ANDRE com acento): por nome exato casam 34 das 51 cidades dos agregados, e sem acento casam as 51. Municipio que nao casar PARA a montagem dizendo qual e - chutar o codigo produziria um documento que fecha no schema e mente sobre onde o frete aconteceu.

## [0.66.1] — 26/08/2026  ·  CX-26/08/2026-v0.66.1

### Corrigido
- A coluna Cadastro continuava mostrando "completo" nos 17 agregados sem inscricao estadual, mesmo depois da correcao anterior. A tela montava a propria lista de pendencias em JavaScript, com a regra antiga, enquanto o servidor ja usava a nova - duas copias da mesma regra, que divergiram no mesmo dia. A lista passou a vir pronta do servidor, que e quem conhece a regra.

## [0.66.0] — 26/08/2026  ·  CX-26/08/2026-v0.66.0

### Corrigido
- A tela de CT-e de Contrapartida dizia "cadastro completo" para 17 dos 53 agregados PJ que estao com o texto "ISENTO" na inscricao estadual. A verificacao so olhava se o campo estava vazio, e "ISENTO" e texto - entao passava. Era pior que nao ter verificacao nenhuma: dava confianca falsa sobre um terco da fila, e a versao anterior chegou a reportar "zero pendencias cadastrais" como boa noticia.
- CT-e e documento de ICMS: transportadora emitente precisa ser inscrita. Ou o cadastro do ERP esta desatualizado, ou esses 17 nao emitem CT-e - e nesse caso a fila real e de 36 agregados, nao 53. O aviso diz os dois numeros e recomenda conferir no SINTEGRA antes de tratar como pendencia de sistema.
- A pendencia mostra o VALOR encontrado ("inscricao estadual (ISENTO)") em vez de so o nome do campo: sem isso parece campo em branco, e o operador preencheria em vez de conferir.

## [0.65.0] — 26/08/2026  ·  CX-26/08/2026-v0.65.0

### Adicionado
- Prova de conceito da emissao propria concluida: o CORTEX conversa com a SEFAZ. Consultando o servico do Parana em homologacao com o certificado do agregado FABRETINA, veio "107 - Servico em Operacao". A pilha inteira fecha - certificado, TLS mutuo, endereco da UF certa, envio e leitura da resposta. Nenhum documento foi emitido: a consulta de status nao produz nada, nem em homologacao.
- A camada de compatibilidade ficou em api/contrapartida/sefaz.py, com as QUATRO correcoes que a biblioteca exigiu no caminho de CT-e. Todas de infraestrutura, nenhuma de regra fiscal - resolvidas, nao voltam. E cada uma verifica antes de agir: quando a biblioteca corrigir o defeito, o remendo some sozinho.
- scripts/spike_sefaz.py consulta a SEFAZ da UF de qualquer agregado cadastrado. Serve para conferir um certificado novo antes de confiar nele e para saber se a SEFAZ esta fora antes de culpar o codigo.

### Alterado
- O que a prova de conceito NAO resolve: montar e assinar o CT-e. O provado e a infraestrutura. A montagem do documento e codigo bem mais exercitado do lado da NF-e e bem menos do lado do CT-e, e deve pedir mais correcoes do mesmo tipo - isso entra na conta de quem decidir manter a emissao em casa.

## [0.64.0] — 26/08/2026  ·  CX-26/08/2026-v0.64.0

### Adicionado
- Busca de agregado por nome ou CNPJ no filtro da tela. Com 85 agregados na lista, achar um especifico exigia rolar a tabela inteira.

### Alterado
- A tela de CT-e de Contrapartida passou a abrir no DIA DE HOJE, e nao nos ultimos seis meses. A fila e trabalho diario: o CT-e sai hoje e o documento do agregado tem de sair junto, entao a pergunta da tela e "o que preciso emitir agora" e nao "quanto acumulou". O acumulado continua a um clique no filtro, e o bloco de passivo nunca dependeu dele.
- O rodape do filtro avisa quando o recorte e de um dia so, para "20 CT-e aguardando" nao parecer que o passivo evaporou.

## [0.63.0] — 26/08/2026  ·  CX-26/08/2026-v0.63.0

### Adicionado
- scripts/testar_assinatura.py prova que o certificado de um agregado SERVE PARA ASSINAR, sem emitir nem transmitir nada. Abrir o arquivo com a senha so prova que a senha esta certa; assinar e outra coisa, e a diferenca so apareceria na transmissao, documento a documento.
- O teste confere quatro coisas que passam despercebidas no cadastro: se a chave privada esta mesmo no arquivo (um .pfx pode trazer so a parte publica), se a extensao de uso permite assinatura digital (sem ela a SEFAZ recusa), se a cadeia ate a ICP-Brasil veio junto, e se uma adulteracao do conteudo invalida a assinatura - sem essa ultima, uma verificacao que aceita qualquer coisa passaria por sucesso.
- Validado com o certificado real da FABRETINA: RSA 2048, emitido por AC SyngularID sob ICP-Brasil, valido ate 05/02/2027, com tres certificados intermediarios e uso para assinatura habilitado. Assinou, conferiu contra a propria chave publica e recusou o conteudo alterado.

## [0.62.1] — 26/08/2026  ·  CX-26/08/2026-v0.62.1

### Corrigido
- O formulario de autorizacao nao tinha botao Fechar. Ele fecha por Esc e por clique fora, mas nem todo mundo descobre isso - e num dialogo que grava certificado, nao saber como sair e pior que um botao a mais.

## [0.62.0] — 26/08/2026  ·  CX-26/08/2026-v0.62.0

### Alterado
- "Procuracao" passou a se chamar "Autorizacao para emitir". O usuario apontou, com razao, que o certificado ja habilita tecnicamente a assinatura - procuracao nao e requisito de software. O instrumento (procuracao, clausula do contrato de agregamento ou termo) e decisao do juridico, e o rotulo deixou de presumir qual.
- O que o sistema continua exigindo, e por que: ESCOPO, porque o certificado assina qualquer coisa e nao so CT-e; e VALIDADE, porque sem data de fim a rotina nao sabe PARAR quando o agregado sai da frota. O formulario explica isso na propria tela.
- O registro que ja existia foi migrado, nao descartado - o dado perdido seria justamente a autorizacao de alguem.

## [0.61.2] — 26/08/2026  ·  CX-26/08/2026-v0.61.2

### Corrigido
- Gravar o certificado do agregado dava erro. A senha estava indo para o cofre geral de credenciais, que recusa qualquer chave fora de uma lista fixa - e com razao: aquele cofre existe para credenciais nomeadas e unicas (token da Gobrax, senha do e-mail), que a tela de Gestao edita uma a uma. Senha de certificado e uma POR AGREGADO. Agora tem cofre proprio, com a mesma disciplina: arquivo com permissao restrita, fora do git, e o valor entra e nao volta para a tela.
- O certificado chegava a ser gravado antes do erro da senha, entao o agregado ficava com certificado e sem senha. A tela ja tratava isso corretamente - aparece como nao autorizado, com o motivo "senha do certificado nao cadastrada" - mas vale saber que basta reenviar.

## [0.61.1] — 26/08/2026  ·  CX-26/08/2026-v0.61.1

### Corrigido
- A banda de indicadores da tela de CT-e de Contrapartida tinha CINCO cartoes numa grade de quatro, entao o quinto caia sozinho numa linha. O valor da prestacao virou subtitulo do primeiro cartao, que e onde ele significa alguma coisa, e a banda voltou a ter quatro. Entrou teste que conta os cartoes de cada banda - a regra ja estava escrita no manual do projeto e mesmo assim foi quebrada.

## [0.61.0] — 26/08/2026  ·  CX-26/08/2026-v0.61.0

### Adicionado
- Formulario de autorizacao na tela de CT-e de Contrapartida: clicando no selo de "nao autorizado" de qualquer agregado abre o cadastro da procuracao (escopo e validade) e do certificado digital. A acao fica onde o problema aparece, em vez de num formulario solto que exigiria copiar o CNPJ.
- O arquivo .pfx e ABERTO com a senha no momento do cadastro, e titular, CNPJ e validade saem do proprio certificado - dado que nao precisa ser digitado e por isso nao pode ser digitado errado. Senha incorreta vira erro na hora, e nao rejeicao documento a documento na transmissao (com 3 mil CT-e por mes, esse erro some no meio de um lote).
- Conferencia de titularidade: se o CNPJ dentro do certificado for diferente do cadastro do agregado, a tela AVISA. Nao bloqueia, porque ha matriz assinando por filial e ha certificado cujo titular nao carrega o numero - mas certificado trocado assina o documento errado, e isso nao aparece em conferencia nenhuma depois.

### Alterado
- O .pfx e a senha viajam no CORPO do POST, nunca em endereco ou cabecalho: os dois aparecem em log de servidor e de proxy, e senha de certificado em log e vazamento permanente. O arquivo e gravado com permissao restrita e a senha vai para o cofre, de onde nao volta - nem mascarada para a tela.
- A trilha de auditoria passou a registrar o e-mail de quem cadastrou. Ela gravava um ponto de interrogacao, o que nao serve para nada meses depois - que e exatamente quando ela e consultada.

## [0.60.0] — 26/08/2026  ·  CX-26/08/2026-v0.60.0

### Adicionado
- A tela de CT-e de Contrapartida passou a mostrar, por agregado, se ele esta AUTORIZADO a ter documento emitido em nome dele: procuracao vigente, certificado A1 valido, arquivo enviado e senha no cofre. Hoje sao 0 de 54 - e o KPI diz isso em vermelho, porque enquanto ninguem estiver autorizado a fila de 14 mil CT-e e diagnostico, nao trabalho.
- Quem nao esta pronto mostra O QUE FALTA na propria linha, no lugar de um "nao" que obrigaria a abrir outra tela para descobrir. Certificado A3 aparece como IMPEDIMENTO e nao como pendencia: ele mora em token fisico e exige presenca a cada assinatura, entao nao se resolve preenchendo campo.
- Monitor de vencimento: certificado A1 vale um ano, e vencer em silencio pararia a emissao sem ninguem perceber. Faltando 30 dias ou menos, a linha avisa - mas nao bloqueia, porque bloquear antes de vencer pararia sem motivo.

### Alterado
- A senha do certificado NUNCA entra no banco do modulo, nem mascarada: vai para o cofre local (arquivo 0600, fora do git) pela mesma regra do token da Gobrax - entra e nao volta. O repositorio do codigo e publico, e senha em banco versionado seria vazamento permanente. Ha teste de arvore sintatica garantindo que nenhuma funcao do modulo devolve senha.
- Toda gravacao de procuracao ou certificado entra numa trilha de auditoria com quem, quando e o que: autorizar emissao em nome de terceiro tem de ser respondivel meses depois, inclusive contra o proprio CORTEX.

## [0.59.2] — 26/08/2026  ·  CX-26/08/2026-v0.59.2

### Adicionado
- Aviso novo: agregados cujos CT-e somam menos de R$ 1,00 no periodo. Documento de valor simbolico costuma ser anulacao ou complementar, nao prestacao - e se for, nao deveria puxar contrapartida. A tela conta e pergunta em vez de filtrar por conta propria, porque isso e definicao fiscal.

### Corrigido
- O cabecalho das telas CT-e de Contrapartida e Permanencia na Planta ficava em "carregando..." para sempre. O carimbo global de atualizacao e preenchido pelos loaders das telas SEM filtro proprio; estas duas tem filtro proprio e nao entraram na lista que o esconde. Lido de longe, parecia tela travada. Entrou teste para nao repetir.
- Valor abaixo de R$ 1,00 aparecia como "R$ 0" na fila por agregado. Ha um agregado com 4 CT-e somando R$ 0,04 - arredondado, parecia erro de sistema quando o dado esta certo e o estranho e o documento. Agora mostra os centavos.

## [0.59.1] — 26/08/2026  ·  CX-26/08/2026-v0.59.1

### Corrigido
- A tela de CT-e de Contrapartida abria com "Erro ao montar a conciliacao". As colunas de primeira e ultima emissao voltam do banco como data, e a resposta da API nao serializa esse tipo - devolvia 500. O teste que existia olhava so os indicadores e nunca chegava na serializacao, entao o defeito so apareceu quando a tela foi aberta no navegador. Entrou teste que serializa a resposta inteira.

## [0.59.0] — 26/08/2026  ·  CX-26/08/2026-v0.59.0

### Adicionado
- Tela nova em Controladoria: CT-e de Contrapartida. Para cada CT-e que a Sulista emite com veiculo de agregado existe (ou deveria existir) um CT-e emitido PELO agregado contra a Sulista. Hoje nenhum e emitido, e a tela dimensiona essa fila: 12.482 CT-e nos ultimos 6 meses, de 53 agregados PJ, somando R$ 34,7 milhoes de prestacao.
- A tela separa duas populacoes que nao podem ser somadas. Dos 83 agregados do periodo, 30 sao pessoa fisica - e o Transportador Autonomo de Cargas NAO emite CT-e (Lei 11.442): a documentacao dele e CIOT e RPA. Somar os 6.020 CT-e deles inflaria a fila em 48% com documento que nao pode existir. Eles aparecem esmaecidos, marcados, e fora de todo total.
- Bloco de passivo acumulado, separado e rotulado: 34.188 CT-e de agregado PJ desde 2022, R$ 108,7 milhoes de prestacao. NAO e fila de trabalho - CT-e nao se emite retroativo, porque a SEFAZ recusa data de emissao fora da janela. E numero para a decisao da contabilidade e do juridico.
- Conferencia de cadastro por agregado (razao social, inscricao estadual, RNTRC e municipio): campo ausente vira rejeicao documento a documento na transmissao, e com 3 mil CT-e por mes e o erro que para a operacao. Hoje os 53 PJ estao completos - nada trava do lado do cadastro.

### Alterado
- A tela e SO LEITURA e continua sendo: nao emite, nao assina e nao transmite. Emissao em nome de terceiro depende de procuracao vigente, certificado A1 e enquadramento fiscal definido, e nenhuma das tres e decisao de software. Ha teste de arvore sintatica garantindo que o modulo nao alcanca assinatura nem transmissao.

## [0.58.0] — 26/08/2026  ·  CX-26/08/2026-v0.58.0

### Alterado
- As perguntas de sempre do chat da Operacao MWM deixaram de passar pelo modelo: maior atraso, maior permanencia, top N de fornecedores ou placas e resumo do periodo passaram a ser CALCULADAS e respondem na hora, sem espera. O modelo continua atendendo o que e aberto ("por que essa coleta demorou?").
- A razao esta medida. Num A/B entre dois modelos locais, toda dimensao pre-calculada os dois acertaram, e toda dimensao deixada para o modelo os dois erraram - com resposta confiante, especifica e errada: perguntado onde o veiculo ficou mais parado, um respondeu "MARTINREA, 212,5 min" com coleta, placa e data formatadas, quando o certo era outro fornecedor com 307,4 min, valor que estava no contexto duas vezes. Onde o numero E a resposta, nao ha o que o modelo interprete.

### Corrigido
- O ranking por placa vinha sempre vazio: a placa fica na coleta e nao no ponto, e a agregacao procurava no lugar errado. "Quais placas ficam mais paradas" morria calado.
- "Em qual ponto o veiculo ficou mais tempo parado" era entendido como pedido de ranking por placa (por conter "veiculo" e "tempo" perto um do outro) e devolvia uma lista em vez do maximo.

## [0.57.1] — 26/08/2026  ·  CX-26/08/2026-v0.57.1

### Adicionado
- scripts/ab_modelo_milkrun.py compara dois modelos locais nas mesmas perguntas, com GABARITO calculado do proprio contexto - o teste confere se a resposta traz a placa e o numero da coleta certos, nao se ela parece boa. Modelo que escreve bem e erra a placa e pior que modelo seco e certo.

### Corrigido
- O chat da Operacao MWM errava "qual coleta teve o maior atraso". O contexto tinha ranking pronto de PERMANENCIA e nenhum de ATRASO, entao o modelo precisava varrer os pontos - e nao achava: num teste A/B em 26/08, um modelo devolveu resposta VAZIA e o outro respondeu com a maior permanencia achando que era o maior atraso. Agora vai a tabela `piores_atrasos` pronta, ordenada, com coleta, placa e local, e o prompt avisa que atraso e permanencia sao coisas diferentes.

## [0.57.0] — 26/08/2026  ·  CX-26/08/2026-v0.57.0

### Alterado
- A tela "Milk Run - MWM" passou a se chamar "Operacao MWM". O termo milk run continua valendo como conceito - solicitacao com mais de uma parada, que e o que separa do frete simples no filtro.

### Corrigido
- Filtrar uma semana na tela levava 40 segundos. As consultas ao banco somam 1,3 segundo: o resto era processamento. A funcao que detecta a chegada e a saida pelo rastro roda uma vez POR PONTO, e a primeira coisa que fazia era filtrar e reordenar a lista inteira de posicoes do veiculo - 63 mil linhas, 153 vezes, sendo que elas ja chegavam ordenadas do banco. Agora a ordenacao e paga uma vez por placa, e um teste de caixa descarta as posicoes distantes antes do calculo de distancia. Uma semana caiu de 40,5 s para 1,8 s e um mes inteiro passou a responder em 5,7 s.

## [0.56.1] — 26/08/2026  ·  CX-26/08/2026-v0.56.1

### Alterado
- O nome do modelo saiu da tela: e detalhe de implementacao e nao ajuda quem le a resposta. A procedencia que importa - roda na maquina, sem nome de motorista - continua no i do cartao.

### Corrigido
- O chat do Milk Run respondia "nao esta disponivel no contexto" a perguntas de ranking, como "top 5 fornecedores em tempo medio parado". Duas causas somadas: no recorte padrao (hoje) as paradas ainda estao pendentes e nao tem permanencia medida, e mesmo com dado, agrupar 163 pontos de JSON e ordenar e trabalho que um modelo de 8B erra. Agora o ranking por fornecedor e por placa vai PRONTO no contexto, ordenado, com mediana e media lado a lado e o numero de paradas de que cada linha foi tirada.
- Quando o periodo filtrado nao tem nenhuma parada concluida, o chat passou a explicar isso e sugerir ampliar o periodo, em vez de dizer que o dado nao existe - o que fazia parecer que a tela nao tinha a informacao.
- O contexto passou a ter ORCAMENTO. A janela de 7 dias produzia ~15 mil tokens contra o limite de 16.384 do modelo local: passar do teto nao levanta erro, apenas empurra o inicio do contexto (as REGRAS) para fora da janela, e o modelo responde pior sem nada indicar. Acima do teto o detalhe ponto a ponto e reduzido as paradas notaveis (atraso, frustrada, permanencia longa), os rankings agregados NUNCA sao podados, e o que foi reduzido fica declarado para o modelo poder dizer que nao viu tudo.

## [0.56.0] — 26/08/2026  ·  CX-26/08/2026-v0.56.0

### Adicionado
- A tela Milk Run - MWM ganhou um chat proprio, restrito ao roteiro do periodo filtrado. Ele enxerga cada parada com o horario combinado, a chegada e a saida DETECTADAS pelo rastreador, a permanencia e o atraso - e responde coisas como "qual coleta teve o maior atraso", citando numero da coleta e placa. Perguntou de outro assunto do painel, ele aponta o Copiloto Cortex em vez de tentar responder.

### Alterado
- Este chat roda SEMPRE no modelo local da maquina, sem alternativa. O Copiloto Cortex manda ao modelo apenas KPIs escalares justamente porque pode cair num modelo externo; aqui o contexto leva placa e fornecedor, que e o que torna a resposta util e o que nao pode sair daqui. Com o modelo local fora, o chat DIZ que esta indisponivel e explica por que - responder pior calado pareceria funcionar e seria pior.
- O nome do motorista nao e enviado nem ao modelo local. Placa, fornecedor e horario respondem tudo que a tela pergunta, e o nome e o dado mais pessoal do conjunto.

## [0.55.1] — 26/08/2026  ·  CX-26/08/2026-v0.55.1

### Corrigido
- A tela Permanência na Planta não abria: clicar nela levava de volta à Visão Geral, sem erro nenhum. Faltava registrá-la em `VIEWS`, que é o registro que o roteador consulta antes de navegar - ela tinha link no menu, rota, permissão e dado, e mesmo assim era inalcançável.
- O item do menu estava sem ícone: o `data-ic` apontava para uma chave inexistente, e ícone desconhecido não levanta erro, só deixa o espaço vazio. A tela ganhou ícone próprio (contorno de área com um ponto dentro) em vez de repetir o da Torre de Controle, que faria duas linhas do mesmo grupo parecerem a mesma tela.
- Quatro guardas novas para que isso não se repita: toda tela do menu tem de estar em `VIEWS`, toda tela de `VIEWS` tem de ter seção no HTML, todo ícone referenciado tem de existir e toda tela do menu tem de ter loader. Os dois defeitos acima falhavam em SILÊNCIO - já havia teste para a gaveta do celular e para o acordeão do menu, e nenhum para o registro que de fato autoriza a navegação.

## [0.55.0] — 26/08/2026  ·  CX-26/08/2026-v0.55.0

### Adicionado
- Tela nova em Operação: Permanência na Planta. Mostra quanto tempo o veículo passa dentro da planta da Tupy em Joinville e onde esse tempo é gasto, polígono a polígono - data e hora de entrada e saída, permanência por visita e ranking dos pontos que mais consomem tempo.
- O número que a tela existe para mostrar, medido em agosto/26: a mediana de permanência é de 6h50 por visita com atendimento, e 75% disso é passado FORA de qualquer polígono mapeado - 1h33 nos pontos contra 5h06 em fila, manobra ou área ainda sem polígono. O ranking abre com Almox Inflamáveis (35 min de mediana), Expedição Usinagem (32 min) e Expedição Blocos (31 min); a Portaria 1, com 540 visitas, resolve em 5 min.

### Alterado
- A tela NÃO usa a tabela sulista.valida_poligono_tupy, que já existia: ela é um retrato estático que parou em 11/07/2026 e cobre 12 dos 18 polígonos - faltam justamente a Portaria 1 (a mais movimentada, com 64 placas) e o PERÍMETRO da planta, que é o que permite separar atendimento de fila. A tela sai da posição crua do rastreador cruzada com o cadastro de polígonos, e por isso enxerga até a última posição recebida.

### Corrigido
- Permanência não é a última leitura menos a primeira. Com o rastreador lendo a cada 3 a 5 minutos, o veículo entra antes da primeira leitura e sai depois da última, e uma visita com uma leitura só mediria ZERO minuto - 34% das visitas do período estão nessa situação. A estimativa estende até metade do caminho para a leitura de fora, com teto de 3 minutos por lado (sem o teto, uma placa cuja leitura anterior foi há 40 min ganhava 20 minutos de portaria que não existiram). As visitas estimadas vêm marcadas na tabela.

## [0.54.1] — 26/08/2026  ·  CX-26/08/2026-v0.54.1

### Corrigido
- A faixa pessimista/otimista do Fechamento do Mes estava larga demais para decidir qualquer coisa: R$ 6,49 mi de amplitude em volta de um resultado de -R$ 68 mil. A faixa sai de uma calibracao gerada por backtest, e a que estava no ar era de 04/08 - ou seja, descrevia o erro do modelo ANTIGO. Duas linhas faziam 72% da largura, e as duas eram exatamente os defeitos corrigidos na 0.54.0: OUTRAS DESPESAS/RECEITAS carregava +1650% (o evento de R$ 1,46 mi de maio) e CUSTO VARIAVEL carregava 40 pontos (o erro do combustivel). Recalibrado, a faixa caiu para R$ 3,06 mi.
- O backtest nao montava o contexto do diesel do agregado, entao media o combustivel pelo caminho ANTIGO mesmo depois da 0.54.0 - calibrava a faixa contra um modelo que nao existe mais. Passou a reconstruir tambem a recuperacao do diesel "as-of" a data (por dtinc, como ja fazia com o razao) e o km do agregado.

## [0.54.0] — 25/08/2026  ·  CX-25/08/2026-v0.54.0

### Alterado
- Fechamento do Mes: o combustivel deixou de ser projetado como um numero so. O agrupador CV - COMBUSTIVEL e um LIQUIDO (diesel da frota MENOS o diesel repassado ao agregado, que volta no acerto), e as duas pernas se comportam de forma completamente diferente. Medido nos seis meses fechados: o diesel bruto varia 9% em torno do nivel (R$ 1,53 mi a R$ 1,93 mi) e a recuperacao sai a R$ 1,31 por km rodado de agregado (desvio de R$ 0,18) - mas o LIQUIDO, que e a diferenca dos dois, foi de R$ 249 mil a R$ 835 mil, 3,4x de amplitude. Projetar o liquido era projetar o ruido. Agora o diesel bruto vai pelo nivel historico (com piso no que o razao ja lancou) e a recuperacao vai pelo km do agregado.
- Ainda no combustivel: o liquido era dividido pela curva de completude, que e montada sobre o MOVIMENTO das duas pernas e no dia 24 do mes vale de 19% a 77% conforme o mes. Em agosto isso projetava R$ 2,50 mi de diesel bruto - 30% acima do pior mes ja registrado, num mes de km normal.
- O aviso "Combustivel diverge" comparava os abastecimentos no cartao contra o LIQUIDO do agrupador e disparava praticamente todo mes: o cartao e uma PARTE do diesel proprio, e contra o liquido ele valeu de 44% a 235% nos seis meses fechados. Agora compara a PARTICIPACAO do cartao no diesel BRUTO (42% em fevereiro, 28% nos tres ultimos meses) contra a mediana dos meses fechados, e so avisa quando ela sai da faixa.
- O aviso de escrituracao dizia que "o resultado previsto tende a PIORAR quando o razao alcancar". Nao e o previsto que se move: o custo fixo sai do nivel historico e o bloco de frete sai das viagens do mes. Quem se move e o REALIZADO, e e ele que engana - em julho a coluna mostrava +R$ 1,7 mi no dia 4 e o mes fechou em -R$ 945 mil. O texto passou a dizer isso.

### Corrigido
- Um evento de R$ 1,46 mi lancado em OUTRAS RECEITAS em maio virava receita de TODO mes projetado. A estrategia sazonal tirava a media dos seis meses e esse unico lancamento - 250 vezes a mediana dos outros cinco - punha R$ 245 mil de receita que nao existe em cada mes, fazendo a linha DESPESAS aparecer R$ 211 mil menor do que a operacao comporta. O mes fora da serie agora fica de fora do nivel e sai NOMEADO na premissa do card. Custo em rajada continua contando inteiro (indenizacao trabalhista sai em dois meses do semestre e e real): o corte separa os dois casos com folga.
- Efeito no numero: a previsao de agosto saiu de -R$ 1,13 mi de resultado operacional para -R$ 240 mil. Conferindo contra um modelo independente (a mesma receita com a estrutura de custo mediana da empresa), que aponta -R$ 330 mil, os dois metodos agora ficam R$ 90 mil um do outro - antes eram R$ 806 mil.

## [0.53.1] — 25/08/2026  ·  CX-25/08/2026-v0.53.1

### Corrigido
- A previsao do custo de agregado tomava o frete CONTRATADO como se fosse o valor contabil, 1 para 1. Ele nao e: entre contratar e lancar entram glosa, acerto e diferenca de pedagio. Medido em seis meses fechados, o contabil e 95,5% do contratado (94,9 / 96,1 / 100,4 / 94,2 / 92,6 / 96,5), com desvio de 2,4 pontos.
- Como o frete de agregado e o maior componente do custo variavel, o erro ia inteiro para o resultado. So em agosto eram R$ 223 mil: o resultado previsto passou de -R$ 1,57 milhao para -R$ 1,34 milhao.

## [0.53.0] — 25/08/2026  ·  CX-25/08/2026-v0.53.0

### Adicionado
- CARTAO DO RESULTADO OPERACIONAL (LOP 1) no Fechamento do Mes. E o resultado da operacao - ja tirou impostos, custo e despesa, e ainda nao entrou juros da divida nem evento nao recorrente. E o numero que diz se o negocio se paga rodando caminhao.
- Ele vem com a MEDIANA dos meses fechados ao lado, porque sozinho nao decide nada: "-R$ 1,4 milhao" so vira informacao quando se sabe que o mes tipico e -R$ 295 mil. Hoje o cartao mostra "4,6x o mes tipico".
- O semaforo compara com a MEDIANA, nao com zero. Prejuizo operacional e o normal nesta operacao - cinco dos seis meses fechados este ano deram negativo - e pintar de vermelho por ser negativo daria alarme todo mes, ate ninguem mais olhar. Vermelho e quando o mes esta ao menos duas vezes pior que o tipico.

## [0.52.0] — 25/08/2026  ·  CX-25/08/2026-v0.52.0

### Adicionado
- A tela de FECHAMENTO DO MES passou a mostrar QUANTO do mes ja esta lancado no razao, e a quebra por bloco. Em 25/08, com 81% do mes corrido: receita 81% escriturada, custo variavel 50%, custo fixo 45%.
- O cartao fica VERMELHO quando o custo esta muito atras da receita - nao quando o total e baixo. Um mes 60% escriturado por igual e confiavel; um com receita em 81% e custo em 45% nao e, mesmo com total parecido.
- Aviso novo: "custo fixo escriturado em 45% contra 81% da receita, o resultado previsto tende a PIORAR quando o razao alcancar". Isso explica o comportamento que parecia defeito do modelo.

### Corrigido
- O percentual de escrituracao so era calculado quando o mes ja tinha virado - justamente quando a pergunta importa menos. No mes corrente ele vinha VAZIO, e a tela mostrava "resultado previsto" sem dizer se falava de um mes quase escriturado ou de metade de um.

## [0.51.0] — 25/08/2026  ·  CX-25/08/2026-v0.51.0

### Adicionado
- GRAFICO DE PNEUS RODANDO POR VIDA, com o CPK de cada uma ao lado. Ele mostra a economia da recapagem em numero: R$ 0,021 por km na 2a vida, R$ 0,016 na 3a e R$ 0,013 na 4a. Hoje sao 1.322 pneus novos, 1.124 na 2a vida, 603 na 3a, 147 na 4a, 22 na 5a e 4 na 6a. Cada linha diz sobre quantos pneus a mediana foi calculada - a da 6a vida sai atenuada porque se apoia em um unico pneu.
- O COPILOTO passou a enxergar as quatro telas novas: Pneus, People Analytics, Ferias e CNH dos Motoristas. Ele ja sabia que elas existiam (a lista de telas sai sozinha do cadastro de permissoes), mas nao via os numeros delas.
- A tarefa agendada de Pneus entrou na lista da Saude do Servidor. Sem isso, uma coleta que parasse envelheceria o painel sem ninguem ver.

### Corrigido
- A tarefa agendada de coleta estava FALHANDO em toda execucao. Ela chamava o script por caminho relativo, e o diretorio de trabalho nao chega ate o interpretador: a tarefa tentava abrir o arquivo dentro de C:\Windows\System32 e morria com "arquivo nao encontrado". Agora usa o Python do proprio projeto com caminho absoluto, como a tarefa da API ja fazia.
- O resumo impresso ao fim da coleta quebrava por conta de nomes de campo antigos - a coleta terminava certa e a tarefa registrava erro assim mesmo, o pior dos dois mundos.

## [0.50.1] — 25/08/2026  ·  CX-25/08/2026-v0.50.1

### Corrigido
- O instantaneo de pneus podia MENTIR sobre o proprio conteudo. Rodando sem argumento - que e exatamente como a tarefa agendada roda - a coleta herdava o rotulo do recorte anterior mas consultava a API sem filtro nenhum. O arquivo se declarava "so instalados" carregando 3.204 pneus sucateados dentro, e a tela acreditaria nele. Agora a consulta segue o recorte gravado, e sem argumento a coleta CONTINUA o recorte em vez de trocar.

## [0.50.0] — 25/08/2026  ·  CX-25/08/2026-v0.50.0

### Adicionado
- TELA NOVA: PEOPLE ANALYTICS (Recursos Humanos). Ela nao repete o Headcount - quadro, admissoes e turnover continuam la. Aqui entra o que nenhuma tela de RH respondia: quem esta afastado e ha quanto tempo, onde esta o risco de sucessao, quanto custa cada area, qual a dispersao salarial dentro do mesmo cargo e quais funcoes tem um unico ocupante.
- Quadro hoje: 196 ativos e 12 AFASTADOS contados a parte, massa de R$ 682.175 em salario base, salario mediano de R$ 3.010, idade mediana de 39,6 anos, tempo de casa mediano de 2,7 anos e 24% de mulheres.
- Dois riscos que a tela torna visiveis: 24 pessoas com 60 anos ou mais (12,2% do quadro), que e horizonte de sucessao e nao previsao de saida; e 37 de 59 cargos com UM unico ocupante, ordenados pelo salario, porque o ponto unico de falha mais caro costuma ser o mais dificil de repor.
- Afastamento aberto ha mais de cinco anos ganha marca - sao 2 hoje. Nao e acusacao de erro: auxilio-doenca longo existe. E pedido de conferencia.
- A INTEGRACAO DA PROLOG entrou na tela de Saude do Servidor, mostrando o quanto do parque de pneus ja foi varrido e ha quanto tempo. Ela nao chama a API para isso: gastaria requisicao da mesma cota que a coleta precisa.

### Alterado
- "Saida por tempo de casa" NAO entrou na tela, de proposito. A unica data de desligamento disponivel devolveu 18 saidas em 12 meses todas na mesma faixa e zero nas demais - distribuicao que nao existe. Publicar seria inventar um achado; a razao ficou escrita no codigo.

## [0.49.0] — 25/08/2026  ·  CX-25/08/2026-v0.49.0

### Adicionado
- A integracao da Prolog ENTROU NO AR. O token funciona e a tela de Pneus ja mostra dado real: 8.572 pneus cadastrados nas quatro filiais, dos quais 3.222 rodando. Nos primeiros 1.000 lidos ha 7 abaixo do minimo legal de sulco, nenhum no eixo direcional, e o sulco esta medido em 996 deles - cobertura excelente.
- Coleta AGENDADA e RETOMAVEL, de 20 em 20 minutos. A Prolog limita a pagina em 100 registros e tem cota de cerca de dez requisicoes por janela: uma volta completa custa 86 requisicoes, entao a coleta avanca oito paginas por vez e fecha a volta em cerca de quatro horas. A tela le o instantaneo, nunca a API.
- Enquanto o retrato nao fecha, a tela DIZ isso: "retrato ainda incompleto, 1.000 de 3.222 (31%)". Sem esse aviso, "7 pneus abaixo do legal" pareceria a frota inteira quando ainda e um terco dela.

### Corrigido
- O conector pedia pagina de 200 registros e a Prolog recusa acima de 100 - toda coleta teria falhado com um erro 400 que pareceria filtro errado.
- Erro 429 (cota esgotada) deixou de ser tratado como credencial invalida. Sao coisas diferentes: a cota se recupera sozinha e mandaria conferir o token a toa.

## [0.48.1] — 25/08/2026  ·  CX-25/08/2026-v0.48.1

### Alterado
- A integracao da Prolog passou a aceitar a URL base com barra no fim (`.../prolog/`), que e como ela e entregue, e o nome de variavel que a Prolog usa (PROLOG_API_BASE_URL). Sem isso a chamada sairia com barra dupla e um 404 dai pareceria credencial errada.
- O FORMATO do token virou configuracao. Ele pode ir como "Bearer", puro, ou num cabecalho proprio como X-API-Key, e nada disso esta na documentacao da Prolog - agora se resolve na tela de credenciais em vez de mexer em codigo no dia em que o token chegar.

## [0.48.0] — 25/08/2026  ·  CX-25/08/2026-v0.48.0

### Adicionado
- MODULO NOVO: PNEUS (grupo Frota), com integracao a Prolog. A tela mede o que decide troca e parada de veiculo: sulco abaixo do minimo legal, pressao fora da faixa, pneus no fim da vida util e custo por quilometro.
- "Acao imediata" ordena por GRAVIDADE e nao por posicao: circular com sulco abaixo de 1,6 mm e ilegal (CONTRAN), pressao baixa nao e. Dentro da mesma gravidade o eixo DIRECIONAL vem primeiro, porque ali nao existe agendamento de troca - existe parada.
- So o pneu INSTALADO conta como rodando. Pressao de pneu no estoque nao e pressao baixa e sulco de pneu sucateado nao e risco; um denominador que juntasse os quatro estados produziria alarme falso.
- Cada indicador que depende de campo preenchivel mostra a COBERTURA. CPK e custo de compra sao os mais expostos: valem zero ate alguem lancar a nota na Prolog, e um CPK mediano calculado sobre 3 de 800 pneus nao e o CPK da frota.
- `uv run python scripts/verificar_prolog.py` diz o que falta para a integracao funcionar e, havendo credencial sem filial, LISTA as filiais disponiveis com os ids - que e o dado que a consulta de pneus exige.

## [0.47.1] — 25/08/2026  ·  CX-25/08/2026-v0.47.1

### Alterado
- ADMINISTRACAO foi para o fim do menu. E configuracao, nao trabalho do dia, e abrir o menu com ela em cima empurrava para baixo tudo o que se usa. Agora os dois extremos sao posicionais - Visao Geral e Copiloto no topo, Administracao no fim - e o miolo e alfabetico.

### Corrigido
- No celular, as telas da ANTT (Piso Minimo de Frete e RNTRC dos Transportadores) apareciam dentro do grupo OPERACAO, enquanto no computador a ANTT e grupo proprio. Quem aprendeu o caminho num aparelho nao achava no outro. Os dois menus passam a ter os mesmos 11 grupos com as mesmas telas em cada um.

## [0.47.0] — 25/08/2026  ·  CX-25/08/2026-v0.47.0

### Alterado
- O MENU INTEIRO passou para ordem alfabetica - os grupos entre si e as telas dentro de cada grupo. Visao Geral e Copiloto Cortex continuam no topo, fora da ordenacao, porque sao a porta de entrada e procura-los na letra V e na C seria pior.
- Sairam as subsecoes de tema do Financeiro (Caixa, A receber, A pagar, Bancos). Com a lista em ordem alfabetica esses cabecalhos so atrapalhavam a busca visual.
- A gaveta do celular foi ordenada junto: ela e uma lista escrita a parte, e ficando na ordem antiga a mesma pessoa veria dois menus diferentes no computador e no telefone.

### Corrigido
- O .gitignore estava excluindo CODIGO do repositorio. O padrao "antecipacoes/", criado para barrar a pasta de planilhas na raiz, casava em qualquer nivel e levava junto "api/antecipacoes/" - o modulo inteiro, 6 arquivos, nunca entrou no git. O mesmo tirou "api/orcamento/plano.py". Reconstruir o servidor a partir do repositorio teria produzido um sistema sem o modulo de antecipacao, sem aviso nenhum. Os padroes foram ancorados na raiz e o codigo entrou.

## [0.46.0] — 25/08/2026  ·  CX-25/08/2026-v0.46.0

### Adicionado
- A coleta da Monkey passa a GRAVAR a posicao da Tupy no mesmo lugar onde a planilha grava, entao Tupy (API), Maxion e Adient (planilha) convivem na mesma tela. Cada posicao guarda de onde veio: "lida ha 10 minutos" e uma garantia diferente de "planilha de 24/08", e a tela precisa poder dizer qual e qual.
- Coleta que nao encontrou mudanca NAO cria registro novo. A identificacao e pelo conteudo (documento, vencimento, valor e situacao), nao pelo horario: a coleta agendada roda de tempos em tempos e, se o portal nao mudou, criar um registro faria a lista de importacoes mentir sobre a frequencia com que o dado realmente muda. Mudanca de situacao de um titulo - de disponivel para vendido, por exemplo - conta como posicao nova.
- Titulo sem data de vencimento e rejeitado, como ja acontece na planilha: sem vencimento nao ha antecipacao possivel nem posicao no fluxo de caixa. A contagem de rejeitados volta no resumo da coleta.

## [0.45.0] — 25/08/2026  ·  CX-25/08/2026-v0.45.0

### Adicionado
- CONECTOR DA MONKEY EXCHANGE, a plataforma de antecipacao da Tupy. Ele substitui a planilha do portal por dado ao vivo: le os recebiveis pela API, pagina sozinho e entrega no MESMO formato que a tela de Portais ja usa, entao a conciliacao e a simulacao de antecipacao nao precisam saber se o portal veio de arquivo ou de API.
- A API traz duas coisas que a planilha nunca teve: a SITUACAO de cada titulo (disponivel, ofertado, vendido, liquidado, recusado, em custodia, atrasado) e a TAXA da operacao. Com isso o "disponivel para antecipar" deixa de contar titulo que ja foi vendido.
- Falta so a credencial. A autenticacao ficou PLUGAVEL porque a documentacao publica da Monkey nao diz qual e: aceita token estatico ou OAuth2 client_credentials, e vale o que estiver configurado - sem mexer em codigo quando a resposta chegar. O ambiente padrao e HOMOLOGACAO; apontar para producao e um ato deliberado.
- `uv run python scripts/verificar_monkey.py` diz exatamente o que falta para a integracao funcionar, sem imprimir segredo nenhum.

## [0.44.0] — 25/08/2026  ·  CX-25/08/2026-v0.44.0

### Adicionado
- TELA NOVA: FERIAS - VENCIMENTO (Recursos Humanos). A data que manda nao e o fim do periodo aquisitivo - e ele MAIS 12 MESES, que e o limite do periodo concessivo. Passar dele faz as ferias serem pagas em DOBRO (art. 137 da CLT), e e por esse limite que a fila ordena e colore.
- Situacao hoje: 196 funcionarios ativos, ZERO em dobra, 1 chegando ao limite em 90 dias e 65 com direito adquirido a agendar. Diferente da tela de CNH, aqui o dado e completo - ha ficha de ferias para 196 de 196 ativos -, entao a tela pode liderar pelo vencimento em vez de pela cobertura do cadastro.
- Card "Em ferias agora e agendadas": 19 pessoas com data marcada, 6 de ferias hoje. E a leitura operacional de quem nao esta no posto.
- Card "Fichas de ferias paradas no cadastro" para 2 registros cujo limite venceu ha 23 e 19 anos. Ninguem fica duas decadas em dobra: nesses dois o periodo aquisitivo atual e a data de gozo estao vazios, ou seja a ficha nunca foi processada. Ficam FORA do indicador de dobra - conta-los anunciaria um passivo trabalhista que nao existe - mas aparecem em lista propria, senao essas pessoas nunca entrariam em alerta nenhum.
- O cartao "Ferias em DOBRA" so fica verde quando nao ha ficha parada. Havendo, ele diz sobre quantas fichas a afirmacao vale ("nenhuma entre as 194 fichas em dia") - com 2 fichas de estado desconhecido, verde afirmaria demais.

## [0.43.0] — 25/08/2026  ·  CX-25/08/2026-v0.43.0

### Corrigido
- A tela de CNH contava MOTORISTA DEMITIDO como ativo. As duas visoes do cadastro do GLOBUS discordam sobre quem esta na empresa: 187 pessoas com funcao de motorista aparecem como ATIVAS numa e DEMITIDAS na outra, e a folha desempata - a maioria nao recebe ha meses. A tela usava a visao errada. Numeros antes e depois: 294 motoristas viraram 104, a cobertura do cadastro subiu de 27,6% para 77,9%, e as "213 pendencias" viraram 23. O alarme era quase todo falso, sobre gente que ja saiu da empresa.
- O criterio de "funcionario ativo" passa a ser o MESMO do Headcount. Duas telas de RH com nocoes diferentes de quem trabalha na empresa e defeito por construcao, e um teste passou a falhar se as duas divergirem.
- O AUTODEPLOY estava parado desde a reescritura do historico do repositorio, falhando a cada 2 minutos sem reiniciar a API. O efeito era o pior possivel para quem usa: a tela NOVA (servida do disco) chamando o backend VELHO, entao a pagina existia e a consulta dela respondia 404. Agora um commit que nao existe mais no repositorio nao interrompe o deploy.

## [0.42.1] — 25/08/2026  ·  CX-25/08/2026-v0.42.1

### Corrigido
- O cabecalho da tela de CNH ficava preso em "carregando..." — a tela nunca preenchia o carimbo de hora, e um topo parado nesse texto e indistinguivel de tela travada. Agora mostra a hora e a data da leitura do banco da folha, como as demais telas.

## [0.42.0] — 25/08/2026  ·  CX-25/08/2026-v0.42.0

### Adicionado
- TELA NOVA: CNH DOS MOTORISTAS (Recursos Humanos), alimentada pelo banco da folha (GLOBUS). Ela lidera pela COBERTURA e nao pelo vencimento, e o motivo esta nos dados: dos 294 motoristas ativos, 81 (27,6%) tem a data de vencimento cadastrada. Entre esses, NENHUM esta com CNH vencida e 2 vencem em 90 dias. Abrir com "0 vencidas" em verde afirmaria "frota em dia" sobre uma base que enxerga 28% da operacao.
- A lacuna do cadastro tem DONO, e esse e o achado util da tela: Garuva e Matriz preenchem 100%, enquanto Cruzeiro fica em 20%, Curitiba em 20% e Pouso Alegre em 11%. Onde a cobertura e total existe um processo que funciona e pode ser repetido nas outras unidades.
- Card "Sem CNH cadastrada" com os 213 nomes, os que estao lotados em area de motorista primeiro (121) - e a lista de trabalho do RH, nao so o diagnostico.
- Na tela de login, opcao "Lembrar meu e-mail neste computador". O e-mail volta preenchido na proxima visita e o cursor cai direto na senha.

### Corrigido
- A PREMIACAO DE MOTORISTAS abria com erro. Duas causas independentes: o arquivo do mes de agosto foi gravado com a data em formato ISO (2026-08-19T14:41:36) e o leitor so aceitava o formato antigo (2026-07-27 16:48), derrubando a tela inteira; e o menu estava mapeado para o grupo Frota enquanto o item vive em Telemetria, entao clicar nela abria o menu da area errada.
- A SENHA passou a ser oferecida ao gerenciador do proprio navegador. Os campos do login estavam soltos, sem formulario, e sem isso o navegador nunca pergunta "deseja salvar a senha?". Quem aceitar tera e-mail e senha preenchidos - guardados no cofre do sistema, nunca em texto puro na pagina.

## [0.41.0] — 25/08/2026  ·  CX-25/08/2026-v0.41.0

### Adicionado
- FILTRO TIPO no Milk Run, separando o roteiro de coleta do frete ponto a ponto: milk run e a solicitacao com MAIS DE UMA coleta. Em agosto, 87 das 234 solicitacoes da MWM tem parada unica e nao sao milk run. A tela abre so no milk run e diz no cartao quantas ficaram de fora.
- VEICULOS NO MAPA, com icone de caminhao na posicao de AGORA (ultima posicao do rastreador, mesma fonte da Torre). Caminhao vazado significa posicao com mais de duas horas - nao afirma "esta aqui" sobre um rastreador que calou.
- Botao EXPANDIR o mapa para a tela inteira, com Esc para voltar.
- LEGENDA INTERATIVA: clicar numa situacao esconde ou mostra aqueles pontos no mapa, duplo clique isola so ela, e o mesmo vale para os veiculos. O que esta escondido fica apagado na legenda em vez de sumir - sumindo, nao haveria caminho de volta. O filtro e so do mapa e nao mexe nos filtros da tela.

### Alterado
- Solicitacao cujas paradas sao TODAS o mesmo endereco (4 das 147 no periodo, tres delas na propria planta da MWM) fica marcada num aviso em vez de reclassificada: pela regra de contagem sao milk run, na pratica sao varias cargas no mesmo lugar. Definir isso e da operacao.

### Corrigido
- O "% realizado" do Milk Run estava INFLADO. A conta era coletadas sobre coletadas+frustradas, entao a coleta que passou da hora e nao aconteceu simplesmente saia do denominador em vez de pesar. Em 21/08 a tela dizia 100% num dia com 14 coletas, 8 feitas e 6 perdidas. Agora o denominador e o que JA TINHA DE ESTAR RESOLVIDO - feitas, frustradas e as pendentes ja vencidas. Numeros do periodo 11 a 25/08: 21/08 caiu de 100% para 57,1%, 14/08 de 87,5% para 58,3% e o total de 93% para 87,9%.
- Dia AINDA EM ANDAMENTO deixou de sair pintado como dia concluido. Hoje as 11h30 havia 4 de 15 coletas feitas e 9 com horario a frente: o indice dizia 100% em verde. O percentual continua certo (e 100% do que venceu), mas agora sai em tom neutro com a marca "em andamento - faltam 9".
- No grafico de Saldo projetado do Fluxo Consolidado, os rotulos do fim do eixo se sobrepunham. O ultimo periodo era desenhado sempre, mesmo colado no anterior; por semana isso acontecia quase sempre - 26 semanas em bandas de 33 px com rotulos de 66 px. Agora a colisao e medida e a prioridade e do ultimo periodo, que e o que se procura no grafico.

## [0.40.0] — 25/08/2026  ·  CX-25/08/2026-v0.40.0

### Adicionado
- LEGENDA no mapa do Milk Run, no canto inferior esquerdo: cada situacao com a cor e quantos pontos ela tem no recorte filtrado. Situacao que nao ocorre no periodo nao entra na legenda - item zerado ocupa espaco e ainda sugere que ha ponto daquele tipo escondido em algum lugar do mapa.

### Alterado
- Os pontos do mapa deixaram de ser circulos lisos e passaram a ser pinos com o NUMERO DA PARADA dentro. A cor continua dizendo a situacao, mas num milk run a ordem decide a leitura - "a terceira parada e a que travou" - e o mapa nao tinha como dizer isso.
- O balao do ponto ganhou a cidade/UF e passou a dizer "sem chegada detectada" no lugar de "nao chegou": sao coisas diferentes, e a segunda acusava a operacao por uma falha que pode ser de rastreamento.

## [0.39.0] — 25/08/2026  ·  CX-25/08/2026-v0.39.0

### Alterado
- As solicitacoes do Milk Run agora abrem sempre RECOLHIDAS - o resumo por dia e os indicadores ja dao a visao do todo, e quem precisa do detalhe expande. Num dia com 17 solicitacoes a tela caiu de 4.550 para 2.254 pixels. O cabecalho de cada solicitacao passou a mostrar o horario da primeira e da ultima coleta, para dizer o que ha dentro sem abrir.
- Sairam da tela os horarios DIGITADOS: fica so o que o rastreamento produz. Coleta que o rastreamento nao detectou passa a mostrar travessao em vez de uma hora que alguem digitou - e assim que a falta de calibragem aparece, em vez de ficar escondida.
- No lugar do antigo indicador de comparacao entrou "Sem rastreamento", que e a lista de calibragem: no periodo de 18 a 24/08 sao 32 de 147 coletas. Um aviso no rodape separa as que tem veiculo e coordenada (e portanto so precisam de ajuste de raio ou da coordenada corrigida) das que nem tem o que rastrear.
- O desfecho continua vindo da operacao: coletada e frustrada nao sao deduziveis do rastreamento, que veria uma visita normal nos dois casos.

## [0.38.1] — 25/08/2026  ·  CX-25/08/2026-v0.38.1

### Alterado
- Os indicadores do Milk Run passaram a usar a linguagem da operacao: SOLICITACAO e o documento e COLETA e a parada no fornecedor. Antes a tela dizia "paradas" e obrigava a traduzir de cabeca.
- Sao oito indicadores agora, em duas faixas. A de cima e o volume: solicitacoes no periodo, coletas pedidas, coletadas e frustradas. A de baixo e o desempenho: pendentes, % realizado, permanencia mediana em cada fornecedor e o quanto o horario digitado difere do rastreamento.
- As quatro situacoes SOMAM o total de coletas pedidas (coletadas + frustradas + pendentes + no local), entao a faixa pode ser conferida de olho, sem ninguem se perguntar onde foi parar o resto. No periodo de 18 a 24/08: 130 + 7 + 10 + 0 = 147.

## [0.38.0] — 25/08/2026  ·  CX-25/08/2026-v0.38.0

### Adicionado
- O Milk Run passou a trabalhar por PERIODO, nao mais um dia so, com filtros de data, fornecedor, veiculo e situacao. Tudo na tela obedece ao recorte: os indicadores do topo, o resumo por dia e as tabelas saem do mesmo conjunto.
- Resumo por dia: uma linha por data com quantas solicitacoes, quantas paradas, quantas coletadas, frustradas e pendentes, mais o % realizado com barra. Clicar na data abre as solicitacoes daquele dia.
- Indicadores no topo: % realizado, paradas no periodo, frustradas e permanencia mediana em cada fornecedor. O % realizado conta so as paradas que ja tiveram desfecho - parada que ainda nem venceu fica fora do calculo, senao a manha pareceria um desastre so porque a tarde ainda nao aconteceu.
- As solicitacoes agora mostram a data e, quando o periodo tem mais de um dia, abrem recolhidas: com sete dias a pagina passava de 14.600 pixels.

### Corrigido
- A tela do Milk Run e a de Portais de Antecipacao nao apareciam no celular. O menu do celular tem lista propria, separada da barra lateral, e as duas telas novas so tinham entrado na barra. Passa a haver verificacao automatica para isso nao se repetir.
- O perfil de acesso "Cliente - Milk Run" existia no codigo mas nunca era criado no banco: os perfis-modelo sao semeados uma unica vez e a marca ja estava gravada desde julho.
- A tela mostrava menos coletas do que existiam - 17 solicitacoes viravam 2 - porque um filtro interno era sobrescrito pelo veiculo da ultima linha lida. Nao dava erro nenhum, so devolvia menos dado.

## [0.37.0] — 25/08/2026  ·  CX-25/08/2026-v0.37.0

### Alterado
- A tela do Milk Run passou a mostrar TODAS as paradas de cada solicitacao, agrupadas pelo numero da coleta. Cada solicitacao vira um bloco com placa, motorista e o resumo do roteiro; dentro dele, uma linha por parada na ordem em que foi agendada. Uma solicitacao pode ter ate quatro paradas, e ver as linhas soltas perdia a nocao de rota.
- Entraram as coletas FRUSTRADAS - aquelas em que o caminhao foi ao fornecedor e voltou sem carga. O rastreamento sozinho nao distingue isso (veria uma visita normal), entao o desfecho vem do apontamento da operacao e manda sobre o detectado.
- Filtros por situacao no topo: todos, pendentes, coletados, frustradas e no local agora, cada um com a contagem.
- O horario DIGITADO no sistema agora aparece ao lado do detectado pelo rastreamento, com a diferenca destacada quando passa de 5 minutos. E a medida direta do ganho da automacao: no dia 24/08 a diferenca mediana foi de 1 minuto em 35 paradas, mas ha casos de mais de 2 horas.

## [0.36.0] — 25/08/2026  ·  CX-25/08/2026-v0.36.0

### Adicionado
- Tela nova "Milk Run - MWM": a operacao do dia ponto a ponto, com o horario COMBINADO na solicitacao de carga ao lado do horario REAL de chegada e saida em cada fornecedor - e o real vem do rastreamento, sem ninguem digitar. Mostra tambem quanto tempo o veiculo ficou em cada ponto e a que distancia do endereco cadastrado ele parou.
- Perfil de acesso "Cliente - Milk Run": uma unica tela, somente leitura, sem acesso a nenhum outro dado da Sulista. E o que permite a MWM acompanhar a operacao em tempo real com login proprio.
- A tela separa o que e atraso de operacao do que e falta de cadastro: ponto sem veiculo alocado ou sem coordenada do fornecedor aparece com o motivo, em vez de virar "aguardando" e parecer culpa do motorista.

## [0.35.0] — 25/08/2026  ·  CX-25/08/2026-v0.35.0

### Adicionado
- Primeira parte da automacao do milk run da MWM: o motor que descobre sozinho a que horas o veiculo chegou e saiu de cada fornecedor, a partir do rastreamento, sem ninguem digitar. Validado contra o rastro real - em metade das viagens conferidas o horario detectado bateu no SEGUNDO exato com o que o sistema ja registra.
- A conferencia mostrou por que a automacao e necessaria: nos ultimos 30 dias ha 1.462 viagens entre cidades DIFERENTES com duracao menor que 15 minutos (uma delas Sao Paulo a Limeira em 1 minuto) e 46% das chegadas terminam com segundo zerado, que e a marca de hora digitada a mao.

## [0.34.0] — 25/08/2026  ·  CX-25/08/2026-v0.34.0

### Adicionado
- Uma conferencia automatica que cruza os numeros do sistema com ele mesmo: o saldo tem de ser o mesmo na Visao Geral, no Fluxo Consolidado e na Antecipacao; o total do a receber tem de fechar com o aging; a cascata do fluxo tem de encadear periodo a periodo; a DRE tem de fechar linha por linha e mes a mes; as faixas das ordens de compra tem de somar o total. Nasceu do defeito do saldo bancario, em que duas telas mostravam R$ 914 mil de diferenca para a mesma coisa sem ninguem perceber. Sao 22 verificacoes; na primeira rodada completa nenhuma acusou divergencia.

## [0.33.0] — 25/08/2026  ·  CX-25/08/2026-v0.33.0

### Corrigido
- O saldo bancario aparecia DIFERENTE na Visao Geral e no Fluxo Consolidado - R$ 914 mil de diferenca. A Visao Geral e o Fluxo de Caixa somavam TODA conta que aparece no ERP, enquanto o Fluxo Consolidado e a Antecipacao ja usavam a marca do proprio ERP ("considerar no fluxo de caixa"). Entravam a mais contas de gestao de pedagio (REPOM, PAMCARD, e-Frete), que nao sao caixa disponivel, e uma conta antiga do Banco do Brasil com posicao de 2014 que nem consta no cadastro de contas. As telas agora mostram o mesmo numero.
- A data da posicao mentia: mostrava a mais RECENTE de todas as contas como se fosse a de todo o saldo. Dizia "posicao de hoje" somando conta parada ha meses. Agora aparece a mais recente E a mais antiga, com a quantidade de dias - em 25/08 a mais atrasada era de 17/08.
- Extrato parado passou a virar aviso. Quando a conta mais atrasada passa de tres dias, a tela avisa: o saldo e toda a projecao de caixa saem dali, entao lancamento velho desloca o furo previsto sem que nada na tela indique isso.
- O valor das contas que ficam FORA do fluxo aparece declarado, com a quantidade de contas e o motivo. Antes ele simplesmente entrava na soma; sumir com ele em silencio seria trocar um erro por outro.

## [0.32.0] — 24/08/2026  ·  CX-24/08/2026-v0.32.0

### Alterado
- No Painel TV da Operacao, o bloco de quatro cartoes do alto a DIREITA passou a mostrar a telemetria da Gobrax: consumo da frota contra o alvo, quantos veiculos estao abaixo dele, freada brusca por mil km e velocidade media. Cada um diz de quando e a coleta, porque em TV nao ha como passar o mouse para descobrir. Excesso de velocidade, cercas e CNH vencida continuam rodando no letreiro do rodape.
- O bloco de KM do mes parou de espremer o conteudo. O percentual de retorno vazio virou barra com a marca do limite de 20% em vez de um terceiro numero grande disputando espaco, o gasto de combustivel do mes passou a aparecer ali, e a lista de modalidades mostra tres em vez de quatro - a quarta era o que estourava a altura e cortava o conteudo.

### Corrigido
- Um valor de modalidade fora do esperado derrubava METADE do Painel TV em silencio: km do mes, chegadas, letreiro e velocimetro da meta ficavam todos em branco, sem nenhum aviso na tela. Agora o rotulo desconhecido aparece cru e o painel segue de pe.
- Numero de cartao da TV nao quebra mais em duas linhas ("2,1 km/l" virava duas), o que comia a altura util do cartao.

## [0.31.1] — 24/08/2026  ·  CX-24/08/2026-v0.31.1

### Corrigido
- O instalador da tarefa de coleta agora pede a elevacao sozinho, com o aviso do Windows, em vez de so avisar que ela falta. A mensagem antiga se parecia com um erro qualquer no meio da saida, e a instalacao dava a impressao de ter funcionado sem a tarefa existir. Ao final ele confere se a tarefa foi mesmo criada e dispara a primeira coleta.

## [0.31.0] — 24/08/2026  ·  CX-24/08/2026-v0.31.0

### Corrigido
- A telemetria da Torre estava com CINCO DIAS de atraso porque nao existia nenhuma coleta automatica: as rotinas so rodavam quando alguem abria uma tela pedindo atualizacao. Agora ha um coletor proprio, que busca o mes corrente e o anterior (a Gobrax fecha dados com atraso) e roda de 3 em 3 horas. A coleta foi executada e a Torre voltou a mostrar dado do dia.
- A Torre mostrava a competencia do mes PASSADO depois de uma coleta dupla. O sistema pegava a ultima coleta GRAVADA em vez da mais recente: como o coletor busca o mes corrente e depois o anterior, o anterior virava "o atual". Passou a valer sempre a competencia mais nova.
- A tarefa de coleta entrou no monitoramento da Saude do Servidor. Tarefa que nao aparece la e tarefa que pode morrer em silencio - foi exatamente o que aconteceu.

## [0.30.0] — 24/08/2026  ·  CX-24/08/2026-v0.30.0

### Alterado
- A Torre de Controle voltou a mostrar os numeros da OPERACAO ao lado dos da telemetria Gobrax: viagens em transito, atrasadas, quantas estao sem posicao ha mais de 6 horas e o km rodando agora. Eles tinham saido da tela quando os cartoes viraram telemetria e sobreviviam so no texto do mapa - uma torre de controle sem "quantas rodando e quantas atrasadas" perde o essencial. Sao oito cartoes, quatro de operacao e quatro de telemetria.
- A tabela de viagens em transito tinha dez colunas e estourava a largura: a coluna Status saia CORTADA no meio ("Atrasada · 5,0 (") justamente nas viagens que precisam de acao. Origem e destino viraram uma coluna so, e saida e previsao tambem - e sobrou espaco para o Km da viagem, que estava no dado e nao aparecia em lugar nenhum.

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
