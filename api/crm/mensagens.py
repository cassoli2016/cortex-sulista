"""Falar com o contato pelo CRM — e o registro automático disso.

O ganho não é o botão: é a INTERAÇÃO nascer sozinha. Um CRM em que registrar o
contato é uma segunda tarefa manual é um CRM com histórico vazio, e o histórico
vazio quebra o único número que justifica o sistema — "há quanto tempo ninguém
fala com este cliente".

QUATRO REGRAS, todas herdadas de erros já pagos na casa:

1. **Ninguém escreve o telefone aqui.** O destino vem do CONTATO cadastrado,
   pelo id. Campo livre de telefone numa tela de CRM é o caminho para disparar
   para número que ninguém conferiu, sem passar pelo cadastro.

2. **O envio é o MESMO caminho de sempre** (`api/whatsapp/envio.py`), com a
   mesma trilha, o mesmo limite diário, a mesma janela de horário e a mesma
   auditoria. Não existe "modo CRM" mais frouxo — um caminho paralelo viraria o
   atalho para disparar sem as regras, exatamente como o teste de e-mail teria
   virado.

3. **Recusa é 4xx, não 5xx.** "O envio está desligado", "o limite do dia
   acabou", "a instância não está pareada": em todos o CÓRTEX funcionou e está
   dizendo NÃO. O Cloudflare TROCA o corpo das respostas 5xx pela página de
   erro dele, e a explicação nunca chegaria a quem precisa lê-la. Quem chama
   (a rota) usa `HTTP_RECUSA`.

4. **Registrar a interação NÃO pode derrubar a confirmação do envio.** A
   mensagem já saiu; falhar aqui e reportar erro faria a pessoa reenviar, e o
   cliente receber duas vezes. A falha do registro é reportada COMO TAL, ao
   lado do sucesso do envio.
"""
from __future__ import annotations

from .. import pglocal
from . import atividades
from .comum import DadoInvalido, RESUMO_MAX, _esq, texto

# Marca na trilha do WhatsApp/e-mail. Serve para recuperar o id do registro
# recém-criado e para que a auditoria distinga o disparo do CRM do envio
# avulso — origens diferentes têm donos diferentes quando algo dá errado.
ORIGEM = "crm"


def _contato(contato_id: int, esq: str | None) -> dict:
    r = pglocal.um("""
        SELECT ct.id, ct.nome, ct.email, ct.telefone, ct.conta_id,
               c.nome AS conta_nome, ct.ativo
        FROM crm_contatos ct
        JOIN crm_contas c ON c.id = ct.conta_id
        WHERE ct.id = %s
    """, (int(contato_id),), esquema=esq)
    if not r:
        raise DadoInvalido("Este contato não existe mais.")
    if not r["ativo"]:
        raise DadoInvalido(
            f"{r['nome']} está marcado como inativo em {r['conta_nome']}. "
            f"Reative o contato antes de escrever para ele — inativo costuma "
            f"significar que a pessoa saiu da empresa.")
    return r


def _id_da_trilha(telefone: str, esq: str | None) -> int | None:
    """Recupera o id que `envio.enviar` acabou de gravar em `zap_envios`.

    `enviar` devolve o `message_id` da Z-API, não o id da nossa trilha — e
    mudar a assinatura dele para isso mexeria num caminho crítico usado por
    cinco áreas. A recuperação por (telefone, origem) é boa o bastante: o
    disparo do CRM é um contato por vez, e o pior caso de uma corrida é a
    interação apontar para o envio vizinho do MESMO número.

    Devolve None sem drama se não achar. O vínculo é conveniência de navegação;
    a interação vale por si.
    """
    try:
        r = pglocal.um(
            "SELECT id FROM zap_envios WHERE telefone=%s AND origem=%s "
            "ORDER BY id DESC LIMIT 1", (telefone, ORIGEM), esquema=esq)
        return int(r["id"]) if r else None
    except Exception:  # noqa: BLE001 — trilha é acessório, não pode derrubar
        return None


def whatsapp(contato_id: int, *, mensagem: str = "", modelo: str = "",
             valores: dict | None = None, oportunidade_id: int | None = None,
             usuario: str = "", instancia: str | None = None,
             registrar_interacao: bool = True, http=None,
             esquema: str | None = None) -> dict:
    """Manda um WhatsApp para o contato e registra a interação.

    Com `modelo`, o que viaja é a CHAVE e os VALORES — nunca o texto pronto.
    Quem monta a mensagem final é o servidor, a partir do modelo gravado:
    aceitar texto pronto junto com a chave deixaria gravar "veio do modelo de
    cobrança" numa trilha em que o texto é outro qualquer, e a coluna `modelo`
    deixaria de ser prova.
    """
    esq = _esq(esquema)
    ct = _contato(contato_id, esq)
    if not ct["telefone"]:
        raise DadoInvalido(
            f"{ct['nome']} não tem telefone cadastrado. Preencha na ficha do "
            f"contato — o CRM não aceita número digitado direto no envio, "
            f"justamente para que todo disparo saia de um cadastro conferido.")
    from ..whatsapp import envio as we

    if modelo:
        r = we.enviar_modelo([ct["telefone"]], modelo, valores or {},
                             usuario=usuario, origem=ORIGEM,
                             instancia=instancia, http=http, esquema=esq)
        # `enviar_modelo` responde no formato de lote mesmo para um destino.
        resultado = (r.get("resultados") or [r])[0] if isinstance(r, dict) else r
    else:
        corpo = texto(mensagem, "a mensagem", maximo=RESUMO_MAX,
                      obrigatorio=True)
        resultado = we.enviar(ct["telefone"], corpo, usuario=usuario,
                              origem=ORIGEM, instancia=instancia, http=http,
                              esquema=esq)

    saida = {"envio": resultado, "contato": ct["nome"],
             "conta_id": ct["conta_id"]}
    if not resultado.get("ok"):
        # Recusa não vira interação: nada saiu para fora, e uma interação
        # gravada aqui faria o "dias sem contato" da conta contar um contato
        # que não houve — mentindo justamente para o lado que esconde o
        # problema. A trilha do WhatsApp já registrou a recusa.
        saida["interacao"] = None
        return saida

    if registrar_interacao:
        try:
            saida["interacao"] = atividades.registrar(
                {"conta_id": ct["conta_id"], "oportunidade_id": oportunidade_id,
                 "contato_id": ct["id"], "canal": "whatsapp", "sentido": "saida",
                 "resumo": _resumo_envio(modelo, mensagem)},
                usuario=usuario, automatica=True,
                zap_envio_id=_id_da_trilha(ct["telefone"], esq), esquema=esq)
            saida["interacao_erro"] = None
        except Exception as exc:  # noqa: BLE001 — regra 4 do cabeçalho
            saida["interacao"] = None
            saida["interacao_erro"] = type(exc).__name__
    return saida


def _resumo_envio(modelo: str, mensagem: str) -> str:
    """O que fica no histórico.

    Guarda o TEXTO enviado (cortado), não só "mensagem enviada": quem lê o
    histórico seis meses depois precisa saber o que foi dito, e a trilha do
    WhatsApp é de auditoria, não de leitura comercial.
    """
    if modelo:
        return f"Modelo “{modelo}” enviado por WhatsApp."
    m = (mensagem or "").strip()
    return m if len(m) <= 500 else m[:497] + "…"


def email(contato_id: int, *, assunto: str, corpo: str,
          oportunidade_id: int | None = None, usuario: str = "",
          registrar_interacao: bool = True,
          esquema: str | None = None) -> dict:
    """Manda um e-mail para o contato e registra a interação.

    O corpo vai pelo layout único da casa (`api/correio/painel.py`), e não em
    HTML próprio — é assim que a regra "e-mail do CÓRTEX não tem área escura"
    vale para o PRÓXIMO e-mail sem ninguém precisar lembrar dela. O e-mail é
    lido no Outlook, que renderiza com o motor do Word: `flex`, `grid` e
    `<style>` são ignorados calados, e a mensagem chega desmontada sem que
    ninguém fique sabendo.
    """
    esq = _esq(esquema)
    ct = _contato(contato_id, esq)
    if not ct["email"]:
        raise DadoInvalido(
            f"{ct['nome']} não tem e-mail cadastrado. Preencha na ficha do "
            f"contato.")
    ass = texto(assunto, "o assunto", maximo=200, obrigatorio=True)
    txt = texto(corpo, "a mensagem", maximo=RESUMO_MAX, obrigatorio=True)

    from ..correio import envio as ce
    from ..correio import painel as layout
    # `documento()` é o ENVELOPE, e passar por ele é obrigatório: `cabecalho` e
    # `paragrafo` devolvem `<tr><td>…</td></tr>` — linhas de uma tabela que só
    # existe dentro do envelope. Concatená-los direto produz `<tr>` órfão, que
    # o Outlook (motor do Word) descarta ou renderiza fora de ordem, e a
    # mensagem chega desmontada sem ninguém ficar sabendo.
    html = layout.documento(
        ass, [layout.cabecalho(ass, ct["conta_nome"])]
        + [layout.paragrafo(p) for p in txt.split("\n") if p.strip()],
        origem="CRM")
    r = ce.enviar([ct["email"]], ass, txt, corpo_html=html, usuario=usuario,
                  origem=ORIGEM)

    saida = {"envio": r, "contato": ct["nome"], "conta_id": ct["conta_id"]}
    if not r.get("ok"):
        saida["interacao"] = None
        return saida
    if registrar_interacao:
        try:
            saida["interacao"] = atividades.registrar(
                {"conta_id": ct["conta_id"], "oportunidade_id": oportunidade_id,
                 "contato_id": ct["id"], "canal": "email", "sentido": "saida",
                 "resumo": f"E-mail “{ass}”: {txt[:400]}"},
                usuario=usuario, automatica=True, esquema=esq)
            saida["interacao_erro"] = None
        except Exception as exc:  # noqa: BLE001
            saida["interacao"] = None
            saida["interacao_erro"] = type(exc).__name__
    return saida


def canais_disponiveis() -> dict:
    """O que está LIGADO agora, para a tela não oferecer botão que recusa.

    Botão que sempre falha é pior que botão ausente: ensina que o sistema está
    quebrado. A tela desabilita e diz por quê, com o caminho do conserto — que
    é sempre em Gestão, e sempre de administrador.

    NÃO consulta a Z-API aqui: `cliente.estado()` tem TTL de 60 s e é chamado
    pela Saúde a cada 5 s; o que interessa nesta tela é se há credencial e se o
    interruptor está ligado, que é leitura local.
    """
    saida = {"whatsapp": {"disponivel": False, "motivo": ""},
             "email": {"disponivel": False, "motivo": ""}}
    try:
        from ..whatsapp import cliente as wc
        from ..whatsapp import config as wcfg
        c = wcfg.ler()
        if not wc.configurado():
            saida["whatsapp"]["motivo"] = (
                "Credenciais da Z-API não configuradas "
                "(Gestão › Integrações).")
        elif not c.get("ativo"):
            saida["whatsapp"]["motivo"] = (
                "O envio de WhatsApp está DESLIGADO em Gestão › WhatsApp.")
        else:
            saida["whatsapp"]["disponivel"] = True
    except Exception as exc:  # noqa: BLE001
        saida["whatsapp"]["motivo"] = f"Indisponível ({type(exc).__name__})."
    try:
        from ..correio import config as ccfg
        if ccfg.configurado():
            saida["email"]["disponivel"] = True
        else:
            saida["email"]["motivo"] = (
                "Servidor SMTP não configurado (Gestão › E-mail).")
    except Exception as exc:  # noqa: BLE001
        saida["email"]["motivo"] = f"Indisponível ({type(exc).__name__})."
    return saida
