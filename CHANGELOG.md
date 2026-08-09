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

### Alterado
- Torre de Controle e Saúde do Servidor: a recarga automática (120 s e 5 s) deixou de esmaecer a tela e de desabilitar o botão Atualizar. O clique manual continua acusando carregamento.

### Corrigido
- Ferramentas de teste (pytest, playwright) declaradas no grupo "test" do pyproject. Sem isso, um `uv sync` — que o AutoDeploy roda a cada mudança no pyproject — desinstalava as duas e levava a suíte junto.

## [0.1.0] — 08/08/2026  ·  CX-08/08/2026-v0.1.0

### Adicionado
- Marco do estado em produção. Painel com 45 telas sobre o ERP AVA (PostgreSQL 9.3, leitura via túnel SSH) e a folha no GLOBUS (Oracle): financeiro e fluxo de caixa, DRE gerencial e por cliente, comercial, operação e torre de controle, frota, jornada, suprimentos, RH e folha, orçamento, premiação de motoristas, extrato bancário, previsão de fechamento do mês, painéis de TV, copiloto e administração com RBAC.
- O histórico anterior a esta versão está nos commits, não aqui.
