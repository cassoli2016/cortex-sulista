# Changelog

Gerado de `docs/versoes.yaml` por `scripts/gerar_changelog.py` — não editar à mão.
Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
versionamento [SemVer](https://semver.org/lang/pt-BR/).

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
