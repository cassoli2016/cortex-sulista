"""Envio de WhatsApp: a regra antes da chamada.

Duas garantias iguais às do `correio/envio.py`, porque o resto do sistema
depende delas:

1. **Nunca levanta exceção para o chamador.** Devolve sempre
   `{"ok": bool, "erro": str, ...}`. Uma rotina agendada que estoura exceção
   morre inteira por causa de um número mal digitado na quinta linha.
2. **Sempre grava na trilha**, inclusive quando recusa antes de chamar a
   Z-API — é o registro da recusa que responde "por que não saiu".

O QUE ESTE ARQUIVO REALMENTE FAZ é uma sequência de seis recusas antes de
qualquer chamada. Elas não são validação de formulário: são o que impede que o
número de WhatsApp da Sulista seja banido, e cada uma existe por um motivo
documentado pelo próprio fornecedor.

    1. número inválido      erro de digitação vira mensagem para outra pessoa
    2. mensagem vazia       não existe motivo legítimo
    3. sem credencial       nada a fazer
    4. integração desligada configurar não é autorizar a disparar
    5. fora da janela       mensagem de empresa às 3 da manhã vira denúncia,
                            e denúncia de usuário é o que o WhatsApp lê
    6. limite do dia        o fator nº 1 de banimento é a quantidade de
                            DESTINATÁRIOS DISTINTOS numa janela curta
    7. celular desconectado a Z-API responde 200 e ENFILEIRA até 1.000
                            mensagens, disparando tudo quando o aparelho
                            voltar — a cobrança de terça chegando sábado à
                            noite, em lote
    8. variável por preencher texto com `{{cliente}}` literal chegando a um
                            cliente de verdade

A sétima é a menos óbvia e a mais cara: sem ela o sistema reporta "enviado com
sucesso" para uma mensagem que ninguém recebeu ainda e que vai chegar na pior
hora possível.

A oitava nasceu com os modelos e vale para TODO envio, não só para quem usa
modelo: é a última rede antes do texto sair. Quem monta a mensagem já valida os
valores, mas quem monta a mensagem é código de área — e a chamada errada de uma
delas não pode virar "Prezado {{cliente}}" no celular do cliente.

DUAS INSTÂNCIAS. `instancia=` escolhe o aparelho — "principal" (padrão) ou
"backup". Ela atravessa TUDO: o cliente HTTP (outro par de credenciais), o
freio (contador de destinatários próprio, porque a reputação é de cada número)
e a trilha (para "por qual número saiu isso?" ter resposta). Não há troca
automática de uma para a outra: se o sistema disparasse pelo reserva sozinho
quando o principal cai, queimaria o segundo número também — e ter reserva é
justamente para não ficar sem nenhum. Quem envia escolhe.
"""
from __future__ import annotations

from . import cliente, config as cfg, modelos, numeros, registro


def _resultado(telefone_bruto: str, erro: str = "", *, telefone: str = "",
               ok: bool = False, message_id: str = "") -> dict:
    return {"ok": ok, "erro": erro, "telefone": telefone or telefone_bruto,
            "informado": telefone_bruto, "message_id": message_id}


def _recusar(bruto: str, normalizado: str, motivo: str, *, usuario: str,
             origem: str, registrar: bool, esquema: str | None,
             modelo: str = "", instancia: str = "principal") -> dict:
    """A recusa entra na trilha SEM o texto da mensagem, ao contrário do que o
    correio faz com o e-mail que falhou.

    Não é descuido: aqui a recusa é quase sempre PRÉ-ENVIO (limite do dia,
    janela de horário, integração desligada) e o motivo explica sozinho o que
    aconteceu. Guardar o corpo de toda tentativa barrada encheria a tabela de
    texto que nunca saiu — e, num disparo em lote recusado no meio, seriam
    centenas de cópias da mesma mensagem.
    """
    if registrar:
        registro.gravar(normalizado or numeros.so_digitos(bruto), "",
                        usuario=usuario, origem=origem, ok=False, erro=motivo,
                        modelo=modelo, instancia=instancia, esquema=esquema)
    return _resultado(bruto, motivo, telefone=normalizado)


def montar_texto(mensagem: str) -> str:
    """Acrescenta a assinatura configurada.

    Sem ela o destinatário recebe um texto de um número que não tem salvo e
    não sabe quem está falando — que é exatamente o perfil de mensagem que as
    pessoas denunciam, e denúncia é o que derruba o número.
    """
    texto = (mensagem or "").strip()
    assinatura = (cfg.ler().get("assinatura") or "").strip()
    if assinatura and assinatura.lower() not in texto.lower():
        texto = f"{texto}\n\n{assinatura}"
    return texto


def enviar(telefone: str, mensagem: str, *, usuario: str = "",
           origem: str = "manual", registrar: bool = True, modelo: str = "",
           instancia: str | None = None, http=None,
           esquema: str | None = None) -> dict:
    """Envia UMA mensagem por UMA instância. Nunca levanta."""
    bruto = str(telefone or "").strip()
    c = cfg.ler()
    inst = cliente.qual_valida(instancia)
    # os mesmos seis argumentos em todas as recusas: com oito pontos de saída,
    # repeti-los à mão é exatamente onde um deles fica para trás — foi assim que
    # `modelo` quase não chegou à trilha da RECUSA, só à do sucesso
    recusa = dict(usuario=usuario, origem=origem, registrar=registrar,
                  esquema=esquema, modelo=modelo, instancia=inst)

    try:
        numero = numeros.normalizar(bruto)
    except numeros.TelefoneInvalido as exc:
        return _recusar(bruto, "", str(exc), **recusa)

    texto = montar_texto(mensagem)
    if not texto:
        return _recusar(bruto, numero, "Mensagem vazia.", **recusa)

    # Rede final: `{{algo}}` que sobrou no texto é variável que ninguém
    # preencheu. Chega aqui quando uma área monta a mensagem sem passar por
    # `enviar_modelo` — e o que sairia é "Prezado {{cliente}}".
    sobrando = modelos.variaveis_usadas(texto)
    if sobrando:
        return _recusar(
            bruto, numero,
            "A mensagem ainda tem variável sem preencher: "
            + ", ".join("{{%s}}" % v for v in sobrando)
            + ". Ela sairia assim, literal, para o destinatário.", **recusa)

    if not cliente.configurado(inst):
        de = ("" if inst == cliente.PADRAO
              else f" da instância {cliente.ROTULOS[inst].lower()}")
        return _recusar(bruto, numero,
                        f"WhatsApp não configurado{de}. Configure a Z-API em "
                        "Gestão › WhatsApp.", **recusa)

    if not c["ativo"]:
        return _recusar(bruto, numero,
                        "Envio por WhatsApp está DESLIGADO em Gestão › "
                        "WhatsApp.", **recusa)

    if not cfg.dentro_da_janela():
        return _recusar(
            bruto, numero,
            f"Fora da janela de envio ({c['janela_inicio']}–{c['janela_fim']}). "
            "Mensagem de empresa fora do horário comercial gera reclamação — "
            "ajuste a janela em Gestão › WhatsApp se for mesmo o caso.",
            **recusa)

    # O limite conta destinatários NOVOS do dia. Continuar uma conversa já
    # aberta hoje não consome cota: é o caso de menor risco que existe, e
    # bloqueá-lo faria o freio atrapalhar justamente o uso legítimo.
    if not registro.ja_falou_hoje(numero, esquema=esquema, instancia=inst):
        usados = registro.contar_destinatarios_hoje(esquema=esquema,
                                                    instancia=inst)
        if usados >= c["limite_dia"]:
            # o limite é DESTA instância: dizer qual evita o engano de achar
            # que o sistema inteiro travou quando o outro número está livre
            return _recusar(
                bruto, numero,
                f"Limite diário atingido no número {cliente.ROTULOS[inst].lower()}: "
                f"{usados} destinatários diferentes hoje (máximo "
                f"{c['limite_dia']}). O limite existe para o número não ser "
                "banido pelo WhatsApp; ele zera à meia-noite.",
                **recusa)

    # A Z-API aceita e enfileira quando o celular está fora — 200 sem entrega.
    est = cliente.estado(http=http, qual=inst)
    if not est.get("conectado"):
        detalhe = est.get("erro") or "o aparelho não está conectado"
        return _recusar(
            bruto, numero,
            f"A instância {cliente.ROTULOS[inst].lower()} da Z-API não está "
            f"conectada ({detalhe}). A mensagem NÃO foi enviada — se tivesse "
            "sido, ficaria na fila deles e dispararia toda de uma vez quando o "
            "aparelho voltasse.",
            **recusa)

    try:
        r = cliente.Cliente(http=http, qual=inst).enviar_texto(
            numero, texto, intervalo_seg=c["intervalo_seg"])
        message_id = str(r.get("messageId") or r.get("id") or "")
        if registrar:
            registro.gravar(numero, texto, usuario=usuario, origem=origem,
                            ok=True, message_id=message_id, modelo=modelo,
                            instancia=inst, esquema=esquema)
        fora = _resultado(bruto, telefone=numero, ok=True,
                          message_id=message_id)
        fora["instancia"] = inst
        return fora
    except (cliente.ZapiIndisponivel, cliente.ZapiNaoConfigurado) as exc:
        # `str(exc)` aqui é seguro: quem levanta já sanitizou. A garantia está
        # em cliente._sanitizar, com teste próprio.
        return _recusar(bruto, numero, str(exc), **recusa)
    except Exception as exc:   # noqa: BLE001 - contrato: nunca levanta
        return _recusar(bruto, numero,
                        f"Falha inesperada no envio: {type(exc).__name__}.",
                        **recusa)


def enviar_varios(telefones, mensagem: str, *, usuario: str = "",
                  origem: str = "manual", modelo: str = "",
                  instancia: str | None = None, http=None,
                  esquema: str | None = None) -> dict:
    """Manda para vários e devolve o resultado de CADA um.

    O limite é reavaliado a cada destinatário, de propósito: uma lista de 200
    números precisa parar no 60º com a explicação, não passar direto porque a
    checagem foi feita uma vez no começo.
    """
    alvos = numeros.separar(telefones)
    if not alvos:
        return {"ok": False, "erro": "Informe ao menos um telefone.",
                "enviados": 0, "falhas": 0, "resultados": []}

    resultados = [enviar(t, mensagem, usuario=usuario, origem=origem,
                         modelo=modelo, instancia=instancia, http=http,
                         esquema=esquema)
                  for t in alvos]
    enviados = sum(1 for r in resultados if r["ok"])
    return {"ok": enviados > 0, "erro": "" if enviados else resultados[0]["erro"],
            "enviados": enviados, "falhas": len(resultados) - enviados,
            "resultados": resultados}


def enviar_modelo(telefones, chave: str, valores: dict | None = None, *,
                  usuario: str = "", origem: str = "",
                  instancia: str | None = None, http=None,
                  esquema: str | None = None) -> dict:
    """ESTA é a porta que as outras áreas do sistema usam.

    Chama-se pela CHAVE do modelo, nunca pelo id nem pelo nome: o id muda se um
    backup for restaurado noutra ordem, e o nome muda no dia em que alguém
    reescrever o título do modelo na tela. A chave é o contrato.

    As três recusas próprias daqui acontecem ANTES de qualquer regra de envio,
    porque nenhuma delas depende do destinatário — e errar aqui é erro de quem
    chamou, não do operador:

        modelo não existe   a área pede um texto que ninguém cadastrou
        modelo desligado    alguém desligou o texto de propósito; respeitar
                            isso é o que faz o interruptor existir
        variável faltando   `renderizar()` estrito, para a mensagem não sair
                            com buraco no lugar do nome do cliente

    Recusa daqui NÃO entra na trilha `zap_envios`: nada foi tentado contra
    número nenhum, e uma linha por chamada errada de código encheria a trilha
    que existe para responder "o que saiu para fora da empresa".
    """
    modelo = modelos.obter(chave, esquema=esquema)
    if not modelo:
        return {"ok": False, "erro": f"Modelo “{chave}” não existe.",
                "enviados": 0, "falhas": 0, "resultados": []}
    if not modelo["ativo"]:
        return {"ok": False,
                "erro": f"O modelo “{modelo['nome']}” está desligado.",
                "enviados": 0, "falhas": 0, "resultados": []}
    try:
        texto = modelos.renderizar(modelo["corpo"], valores)
    except modelos.VariavelFaltando as exc:
        return {"ok": False, "erro": str(exc), "enviados": 0, "falhas": 0,
                "resultados": []}

    return enviar_varios(telefones, texto, usuario=usuario,
                         origem=origem or f"modelo:{modelo['chave']}",
                         modelo=modelo["chave"], instancia=instancia,
                         http=http, esquema=esquema)
