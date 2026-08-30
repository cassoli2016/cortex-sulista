"""CRM comercial — o funil da Sulista, com a receita real do ERP ao lado.

Sete módulos, separados pela pergunta que respondem:

- `comum`         — vocabulário, tetos e o redirecionamento de schema.
- `ava`           — a PONTE com o ERP: receita real por grupo econômico, e a
                    situação da conta derivada dela.
- `contas`        — a empresa e as pessoas: cadastro, ficha 360, contatos.
- `oportunidades` — o negócio e as LANES que o compõem.
- `precificacao`  — R$/km, piso mínimo da ANTT e margem contra o CKM da casa.
- `atividades`    — o compromisso (tarefa) e o que aconteceu (interação).
- `contratos`     — vigência, reajuste e a tabela de preço vigente.
- `mensagens`     — falar com o contato por WhatsApp/e-mail, com registro
                    automático da interação.
- `painel`        — a leitura: funil, previsão, carteira e o que exige ação.

O QUE DISTINGUE ESTE CRM DE UM CRM GENÉRICO, e por que ele mora dentro do
CÓRTEX:

1. **A unidade é a LANE, não o negócio.** Em FTL ninguém vende "R$ 400 mil por
   mês": vende Joinville→Betim, carreta de 6 eixos, 22 viagens, R$ 4.800 a
   viagem. É na lane que existe km, e portanto R$/km, piso mínimo da ANTT e
   margem contra o CKM.

2. **A cotação já sabe se o preço é LEGAL.** O piso da Lei 13.703/2018 é
   calculado enquanto o vendedor digita, com a tabela vigente na data — e não
   depois, quando a proposta já saiu.

3. **"Cliente ativo" é lido do faturamento, não de um campo.** A situação da
   conta sai da programação de embarque do AVA a cada leitura. Nenhum status
   comercial é gravado, em lugar nenhum deste módulo: status gravado envelhece
   sozinho e passa a mentir sem que nada pareça errado.

A BASE DO AVACORP CONTINUA. A tela antiga (leitura de `sulista.gestaocomercial`,
`pipelineprojetos` e `pipelineprojetos_repactuacoes`) segue viva numa sub-aba,
intocada. Nada é copiado de lá: o vínculo entre os dois mundos é o
`crm_contas.ava_agrupamento`, e duas verdades sobre o mesmo lead seria o preço
de uma importação que ninguém pediu.
"""
