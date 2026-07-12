# Austral Design System

Sistema de design da **Austral Transportes & Logística** — marca fictícia/original criada para o setor de transporte rodoviário de cargas, armazenagem e telemetria de frota no Brasil. Identidade própria, criada do zero nesta conversa (nenhuma fonte externa de marca foi usada; um logo de terceiro foi recusado por questões de propriedade intelectual).

Superfícies cobertas: **site institucional**, **dashboard web** (rastreamento e gestão de frota) e **app mobile**.

## Marca
- Nome: Austral Transportes & Logística
- Tagline: "Sua carga no rumo certo."
- Marca gráfica: wordmark tipográfico "AUSTRAL" em Saira ExtraBold, precedido de duplo-chevron laranja (›› em `assets/marca.svg`). Não existe logo desenhado além disso — onde um símbolo for necessário, use o wordmark em tipo puro.

## CONTENT FUNDAMENTALS
- Idioma: português (pt-BR). Tom **institucional/corporativo**: sóbrio, direto, primeira pessoa do plural ("nós"/"a Austral"), tratando o cliente por "você" ou "sua empresa".
- Frases curtas, verbos concretos: "Rastreie sua frota em tempo real." / "Reduza custos com telemetria embarcada."
- Sentence case em body e títulos; UPPERCASE apenas em kickers/labels curtos ("NOSSOS SERVIÇOS").
- Sem emoji. Sem exclamações em série. Números com formato brasileiro (1.250 km; R$ 4,7 mi).
- Códigos operacionais (placas, CT-e, nº de rastreio) sempre em mono: `RTX-4B21`.

## VISUAL FOUNDATIONS
- **Cores**: marinho profundo (--navy-700 #17344F) como cor institucional; laranja de sinalização (--orange-500 #E85D10) como acento único para ações primárias e destaques. Neutros frios. Semânticas: verde/âmbar/vermelho para status operacional.
- **Tipo**: Saira em todo o sistema (display 700/800, body 400/500); IBM Plex Mono para códigos e dados tabulares. Kickers uppercase com tracking 0.12em.
- **Fundos**: páginas em --surface-page (cinza claro); heróis e rodapés em --navy-800 com texto branco; sem gradientes decorativos.
- **Fotografia**: colorida, tons quentes de estrada/pátio; sempre com overlay marinho (rgba(11,25,38,.45+)) quando há texto por cima. Placeholders quando não houver foto real.
- **Cantos**: raio pequeno e técnico — 4/6/10px; pills apenas em badges de status.
- **Bordas e cards**: card = fundo branco, borda 1px --border-default, sombra --shadow-sm; hover eleva para --shadow-md.
- **Sombras**: tingidas de marinho, discretas (tokens --shadow-*).
- **Animação**: mínima — transições 120–180ms ease padrão em hover/focus; sem bounces, sem parallax.
- **Hover**: escurecer um passo do ramp (500→600); press: mais um passo (→700). Links: marinho, sublinham no hover.
- **Transparência/blur**: não usados, exceto overlay sobre fotografia.
- **Layout**: container 1200px; grid 12 colunas com gap 24px; seções separadas por espaçamento (64–96px), não por réguas.

## ICONOGRAFIA
- Set: **Lucide** via CDN (https://unpkg.com/lucide@latest) — traço 2px, combina com o caráter técnico. Ícones típicos: truck, map-pin, route, gauge, warehouse, package, radio-tower.
- Sem emoji, sem ícones desenhados à mão. Unicode apenas para o chevron da marca (››).
- Nenhum ícone proprietário existe; se o usuário fornecer um set, substituir o CDN.

## Fontes (aviso)
Saira e IBM Plex Mono são carregadas do Google Fonts em `tokens/typography.css`. Se preferir binários locais (offline), forneça os .woff2 que eu converto para @font-face local.

## Índice
- `styles.css` — ponto de entrada (só @imports)
- `tokens/` — colors.css, typography.css, spacing.css, effects.css
- `guidelines/` — specimen cards de fundações
- `components/` — primitivas React (forms/, surfaces/, feedback/, navigation/)
- `ui_kits/site|dashboard|mobile` — telas de exemplo por produto
- `assets/` — marca.svg (chevrons da marca)
- `SKILL.md` — uso como Agent Skill

### Adições intencionais
Sistema criado sem fonte externa; o inventário de componentes segue o set padrão (Button…Tooltip) dimensionado para as três superfícies.
