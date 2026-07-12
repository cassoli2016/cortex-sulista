---
name: relatorio-pdf
description: Gera relatórios PDF profissionais no design system da empresa (amarelo #FFD31C, ink #1E1E1E) via pipeline pandas/matplotlib/WeasyPrint. Use quando o usuário pedir um relatório, dossiê ou export PDF de qualquer análise.
---

# Skill: Relatório PDF (design system)

Pipeline padrão para qualquer relatório do CÓRTEX. Consistência visual é regra.

## Tokens do design system
```
amarelo  = "#FFD31C"   # destaque / marca
ink      = "#1E1E1E"   # texto / títulos
cinza    = "#6B7280"   # secundário
verde    = "#16A34A"   # positivo
vermelho = "#DC2626"   # alerta / negativo
fonte    = "Inter, system-ui, sans-serif"
```

## Estrutura padrão do relatório
1. Capa: logo + título + período + cliente/escopo.
2. Sumário executivo: 3-5 números-chave com seta de tendência.
3. Seções por área (gráficos matplotlib estilizados + tabela).
4. Recomendações acionáveis.
5. Rodapé: fonte do dado + timestamp + "gerado pelo CÓRTEX".

## Pipeline
```python
# 1. dados (pandas) → 2. gráficos (matplotlib, paleta acima, sem grid pesado)
# 3. HTML (template Jinja2 com CSS dos tokens) → 4. PDF (WeasyPrint)
from weasyprint import HTML
HTML(string=html_renderizado).write_pdf("/mnt/user-data/outputs/relatorio.pdf")
```

Regra: todo número no relatório cita a fonte. Gráficos com rótulo direto (sem legenda
desnecessária). Nada de "lorem" — se faltar dado, mostrar "sem dado no período".

## Reuso
Compatível com o pipeline já usado nos relatórios de cliente (BBM, TLGA, etc.) e no
gobrax_roi_app. Manter o mesmo template para consistência de marca.
