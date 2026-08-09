# Changelog

Gerado de `docs/versoes.yaml` por `scripts/gerar_changelog.py` — não editar à mão.
Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
versionamento [SemVer](https://semver.org/lang/pt-BR/).

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
- Nome da empresa corrigido para Transportadora Sulista S/A na abertura da Documentação.
- Um teste do Extrato Bancário comparava uma data fixa com a data de hoje e quebraria sozinho na virada do dia, sem ninguém ter mexido em nada — foi o primeiro defeito que a integração contínua pegou.

## [0.1.0] — 08/08/2026  ·  CX-08/08/2026-v0.1.0

### Adicionado
- Marco do estado em produção. Painel com 45 telas sobre o ERP AVA (PostgreSQL 9.3, leitura via túnel SSH) e a folha no GLOBUS (Oracle): financeiro e fluxo de caixa, DRE gerencial e por cliente, comercial, operação e torre de controle, frota, jornada, suprimentos, RH e folha, orçamento, premiação de motoristas, extrato bancário, previsão de fechamento do mês, painéis de TV, copiloto e administração com RBAC.
- O histórico anterior a esta versão está nos commits, não aqui.
