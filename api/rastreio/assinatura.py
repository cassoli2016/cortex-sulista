# -*- coding: utf-8 -*-
"""Inscrição para receber a carga por WhatsApp, pedida na página pública.

O RISCO QUE ESTE ARQUIVO EXISTE PARA CONTER. Uma página aberta que aceita um
telefone e passa a mandar mensagem de hora em hora é, sem cuidado, um jeito
confortável de importunar alguém: basta ter um número de CT-e e o telefone da
pessoa. Nada aqui identifica quem se inscreveu — não há login, não há conta.

As quatro contenções, e o que cada uma cobre:

1. **O segundo fator vale aqui também.** Inscrever exige o mesmo documento em
   mãos e os quatro dígitos do CNPJ que a busca exige. Não impede quem tem os
   dois; tira do caminho quem só tem o telefone da vítima.
2. **Um telefone por carga**, garantido no banco. Sem isso o mesmo número
   entraria dez vezes e receberia dez mensagens por hora — e o freio da casa,
   que conta destinatários DISTINTOS, não veria problema nenhum nisso.
3. **Teto de inscrições por telefone e por janela.** Quem tentar usar a página
   como disparador esbarra antes de conseguir volume.
4. **Toda mensagem carrega como sair**, e sair não exige nada além do próprio
   telefone. Opt-out difícil é opt-out que vira bloqueio do número da empresa.

E UMA DECISÃO DE PRODUTO QUE PROTEGE O NÚMERO DA CASA: o aviso é de hora em
hora, mas mensagem IDÊNTICA à anterior não é reenviada. Caminhão parado geraria
a mesma frase 24 vezes por dia, a pessoa bloquearia o número — e o estrago não
é a mensagem, é a reputação do número que atende todos os outros clientes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .. import pglocal
from ..whatsapp import numeros
from . import consulta, mensagem

log = logging.getLogger("cortex.rastreio.assinatura")

#: Quanto tempo a inscrição dura sem ninguém renovar. Ninguém volta para
#: cancelar: a carga chega, a pessoa esquece, e o aviso seguiria para sempre.
DIAS_VALIDADE = 15

#: Quantas cargas dá para acompanhar AO MESMO TEMPO. É teto de produto, não de
#: segurança: cancelar libera a vaga na hora. A mensagem horária é uma só com
#: todas as cargas dentro, então o custo de cinco é uma mensagem, não cinco.
MAX_ATIVAS_POR_FONE = 5

#: Quantas inscrições dá para CRIAR num dia. Este é o teto antiabuso: cada
#: inscrição manda uma mensagem na hora, então cadastrar-e-cancelar em laço
#: seria um jeito de encher o WhatsApp de um número que não é seu.
MAX_CRIADAS_24H = 12

#: Nome antigo, mantido porque testes e a Saúde ainda o citam.
MAX_POR_FONE = MAX_ATIVAS_POR_FONE
JANELA_FONE_H = 24

#: Teto de telefones acompanhando a MESMA carga. Uma carga tem remetente,
#: destinatário e quem espera na doca — não trinta pessoas.
MAX_POR_CARGA = 8

#: Quanto tempo entre uma mensagem e a seguinte, PARA O MESMO TELEFONE.
#:
#: O relógio é o DELE, não o do servidor: quem pediu às 12h38 recebe 13h38,
#: 14h38… e não 13h00, 14h00. A diferença aparece no primeiro ciclo — antes
#: disto, quem se inscrevia às 12h58 recebia a mensagem de cadastro e OUTRA
#: dois minutos depois, porque o ciclo da hora cheia não sabia que a pessoa
#: acabara de ser avisada.
#:
#: A ÂNCORA É O TELEFONE, NÃO A CARGA, e isso é consequência do agrupamento:
#: as cargas de um mesmo número saem numa mensagem só. Ancorar por carga faria
#: quem acompanha duas receber duas mensagens por hora, em minutos diferentes
#: — desfazendo exatamente o que o agrupamento existe para evitar.
INTERVALO_MIN = 60

#: AS JANELAS QUE A PAGINA OFERECE, por NOME e nunca por hora crua digitada.
#:
#: A diferença importa. Se a tela mandasse "07:00" escolhido num seletor, ela
#: estaria prometendo um horário que a casa talvez não permita — a janela geral
#: é configurável (`data/whatsapp_config.json`) e já foi de 08:00 a 06:00 num
#: mesmo dia. Mandando um NOME, quem resolve é o servidor, e "qualquer horário"
#: quer dizer exatamente "o que a casa permitir", hoje e depois.
#:
#: `None` é gravado como NULO e significa SEGUE A CASA — nunca "sem restrição".
#: É a regra da casa para campo de regra opcional, e aqui ela paga: quando a
#: janela geral mudar, quem não escolheu nada acompanha sozinho.
JANELAS: dict[str, tuple[str, str] | None] = {
    "qualquer":  None,
    "comercial": ("08:00", "18:00"),
    "manha":     ("06:00", "12:00"),
    "tarde":     ("12:00", "18:00"),
}
JANELA_PADRAO = "qualquer"

#: QUANTA COISA É NOTÍCIA para este telefone.
#:
#: NENHUMA DELAS AFROUXA FREIO. A cadência só torna a régua de "o que mudou"
#: mais exigente ou espaça mais as mensagens — nunca o contrário. Não há opção
#: "me mande sempre": ela recriaria, a pedido do próprio cliente, o defeito que
#: custou catorze mensagens iguais em 06/09/2026, e o estrago não seria dele —
#: seria a reputação do número que fala com todos os outros clientes.
#: OS INTERVALOS SAO MULTIPLOS DO PISO, escritos assim de propósito: o piso
#: continua sendo uma constante só (`INTERVALO_MIN`), e nenhuma cadência pode
#: descer abaixo dele por distração de quem editar a tabela — um `30` digitado
#: aqui seria um freio afrouxado sem ninguém perceber. Guard próprio cobra.
CADENCIAS: dict[str, dict] = {
    "tudo":   {"intervalo_min": INTERVALO_MIN,     "so_marcos": False},
    "menos":  {"intervalo_min": INTERVALO_MIN * 3, "so_marcos": False},
    "marcos": {"intervalo_min": INTERVALO_MIN,     "so_marcos": True},
}
CADENCIA_PADRAO = "tudo"


def preferencia(ins: dict) -> dict:
    """A preferência EFETIVA de uma inscrição, com os padrões aplicados.

    UM SÓ LUGAR RESOLVE O NULO. Espalhar `or CADENCIA_PADRAO` pelos chamadores
    é como o padrão vira dois padrões diferentes no dia em que um deles muda.
    """
    cad = (ins.get("cadencia") or CADENCIA_PADRAO)
    if cad not in CADENCIAS:
        cad = CADENCIA_PADRAO
    return {"cadencia": cad,
            "inicio": ins.get("janela_inicio") or None,
            "fim": ins.get("janela_fim") or None,
            **CADENCIAS[cad]}


def janela_efetiva(inicio: str | None, fim: str | None) -> tuple[str, str]:
    """A INTERSEÇÃO entre a janela da casa e a que o cliente pediu.

    É AQUI QUE A ESCOLHA DO CLIENTE SÓ RESTRINGE, e a conta é feita no ENVIO e
    não no cadastro de propósito: a janela geral pode mudar depois, e quem
    escolheu "de manhã" ontem não pode passar a receber às 5h porque alguém
    ampliou a configuração da casa hoje.
    """
    from ..whatsapp import config as wcfg
    c = wcfg.ler()
    casa_i, casa_f = c["janela_inicio"], c["janela_fim"]
    if not inicio or not fim:
        return casa_i, casa_f
    return max(casa_i, inicio), min(casa_f, fim)


def dentro_da_janela(ins: dict, agora=None) -> bool:
    """Este telefone aceita mensagem AGORA?

    Janela vazia (o cliente pediu uma faixa que não encosta na da casa) responde
    NÃO — e é o certo: a alternativa seria ignorar a escolha dele e mandar assim
    mesmo, que é como um recurso de preferência vira motivo de denúncia.
    """
    from ..whatsapp import config as wcfg
    p = preferencia(ins)
    ini, fim = janela_efetiva(p["inicio"], p["fim"])
    if ini > fim:
        return False
    return wcfg.dentro_da_janela(agora, inicio=ini, fim=fim)


def _agora():
    return datetime.now(timezone.utc)


def _chaves(termo: str, cnpj4: str, carga_id: str):
    """As chaves do documento da carga escolhida, ou None.

    Refaz a busca de propósito: é ela que prova o direito. O identificador
    opaco só escolhe QUAL carga — nunca prova nada sozinho.
    """
    linhas, motivo = consulta.buscar_cru(termo, cnpj4)
    if motivo:
        return None, motivo
    for r in linhas:
        if consulta.token(r["grupo"], r["empresa"], r["filial"],
                          r["numero"], r["serie"]) == carga_id:
            return r, None
    return None, None


def inscrever(termo: str, cnpj4: str, carga_id: str, telefone: str,
              ip: str = "", janela: str = "", cadencia: str = "") -> dict:
    """Passa a avisar este telefone sobre esta carga. Nunca levanta.

    `janela` e `cadencia` são NOMES do catálogo (`JANELAS`, `CADENCIAS`), nunca
    horas ou minutos vindos da tela: quem resolve o que "de manhã" significa é
    o servidor, contra a configuração da casa. Nome desconhecido cai no padrão
    em silêncio — é formulário público, e recusar o cadastro inteiro por causa
    de um seletor que veio errado puniria a pessoa por um defeito nosso.
    """
    if len(consulta._so_digitos(termo)) < 3 or \
            len(consulta._so_digitos(cnpj4)) != 4:
        return {"ok": False, "motivo": "informe o documento e o CNPJ"}

    # UM ÚNICO VALIDADOR DE TELEFONE NA CASA, e é o do WhatsApp. Repetir a
    # regra aqui faria os dois discordarem no primeiro caso de borda.
    if not numeros.valido(telefone) or numeros.e_grupo(telefone):
        return {"ok": False,
                "motivo": "Informe um celular válido com DDD."}
    fone = numeros.normalizar(telefone)

    alvo, motivo = _chaves(termo, cnpj4, carga_id)
    if motivo:
        return {"ok": False, "motivo": motivo}
    if not alvo:
        # MESMA RESPOSTA de "não achei" — ver `consulta.buscar`.
        return {"ok": False, "motivo": "Não encontramos essa carga."}

    try:
        with pglocal.get_conn() as conn, conn.cursor() as cur:
            # DOIS TETOS DIFERENTES, e confundi-los prendeu uma pessoa fora do
            # próprio cadastro. O primeiro é de PRODUTO: quantas cargas dá para
            # acompanhar ao mesmo tempo. O segundo é ANTIABUSO: quantas
            # inscrições dá para criar num dia.
            #
            # A regra original contava só as CRIADAS em 24h, e com isso quem
            # cadastrava e cancelava cinco vezes ficava trancado até o dia
            # seguinte — sem ter nenhuma ativa. Cancelar tem de LIBERAR a vaga,
            # senão "sair quando quiser" custa o direito de voltar.
            cur.execute("""
                SELECT count(*)::int AS n FROM rst_inscricao
                WHERE telefone = ANY(%s) AND ativo AND expira_em > now()""",
                (numeros.variantes(fone),))
            if cur.fetchone()["n"] >= MAX_ATIVAS_POR_FONE:
                return {"ok": False,
                        "motivo": "Este número já acompanha %d cargas, que é o "
                                  "máximo. Responda SAIR e o número de uma "
                                  "delas no WhatsApp para abrir uma vaga."
                                  % MAX_ATIVAS_POR_FONE}

            # O TETO ANTIABUSO CONTINUA, e é ele que impede a página de virar
            # disparador: cada inscrição manda uma mensagem na hora, então
            # cadastrar-e-cancelar em laço seria um jeito de encher o WhatsApp
            # de alguém. Ele é folgado o bastante para não atrapalhar quem
            # troca de carga várias vezes no mesmo dia.
            cur.execute("""
                SELECT count(*)::int AS n FROM rst_inscricao
                WHERE telefone = ANY(%s)
                  AND criado_em > now() - make_interval(hours => %s)""",
                (numeros.variantes(fone), JANELA_FONE_H))
            if cur.fetchone()["n"] >= MAX_CRIADAS_24H:
                return {"ok": False,
                        "motivo": "Este número fez muitos cadastros hoje. "
                                  "Tente novamente amanhã."}

            cur.execute("""
                SELECT count(*)::int AS n FROM rst_inscricao
                WHERE grupo=%s AND empresa=%s AND filial=%s AND numero=%s
                  AND serie=%s AND ativo""",
                (alvo["grupo"], alvo["empresa"], alvo["filial"],
                 alvo["numero"], alvo["serie"]))
            if cur.fetchone()["n"] >= MAX_POR_CARGA:
                return {"ok": False,
                        "motivo": "Esta carga já tem o máximo de "
                                  "acompanhamentos."}

            cur.execute("""
                INSERT INTO rst_inscricao
                    (grupo, empresa, filial, numero, serie, telefone,
                     criado_ip, expira_em)
                VALUES (%s,%s,%s,%s,%s,%s,%s, now() + make_interval(days => %s))
                ON CONFLICT (grupo, empresa, filial, numero, serie, telefone)
                DO UPDATE SET
                    ativo = TRUE, cancelado_em = NULL, cancelado_por = NULL,
                    expira_em = now() + make_interval(days => %s)
                RETURNING id""",
                (alvo["grupo"], alvo["empresa"], alvo["filial"],
                 alvo["numero"], alvo["serie"], fone, (ip or "")[:60],
                 DIAS_VALIDADE, DIAS_VALIDADE))
            ident = cur.fetchone()["id"]

            # A PREFERENCIA E DO TELEFONE, e por isso a escrita alcança TODAS
            # as inscrições ativas dele — não só a que acabou de nascer. As
            # cargas de um mesmo número saem numa mensagem só; guardar uma
            # janela por carga criaria o caso sem resposta (duas cargas, duas
            # janelas, uma mensagem). Quem escolhe, escolhe para o número.
            faixa = JANELAS.get(janela or JANELA_PADRAO, None)
            cad = cadencia if cadencia in CADENCIAS else CADENCIA_PADRAO
            cur.execute("""
                UPDATE rst_inscricao
                   SET janela_inicio = %s, janela_fim = %s, cadencia = %s
                 WHERE telefone = ANY(%s) AND ativo AND expira_em > now()""",
                (faixa[0] if faixa else None, faixa[1] if faixa else None,
                 cad, numeros.variantes(fone)))
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: inscrição falhou: %s", type(exc).__name__)
        return {"ok": False, "motivo": "Não foi possível cadastrar agora."}

    # A PRIMEIRA MENSAGEM SAI AGORA, e isso nao e cortesia.
    #
    # Ela confirma para quem cadastrou que deu certo — mas o motivo forte e
    # outro: se alguem cadastrou um numero que NAO E DELE, o dono descobre no
    # mesmo minuto e responde SAIR, em vez de descobrir uma hora depois com a
    # segunda mensagem. Numa pagina aberta, essa e a diferenca entre um
    # engano de digitacao e uma hora de importuno.
    #
    # A falha do envio NAO desfaz a inscricao: o cadastro esta gravado, a
    # tarefa horaria pega o proximo ciclo, e a tela diz o que aconteceu.
    texto_inicial, assin_inicial = _primeira_mensagem(alvo, fone, cad)
    primeira = bool(texto_inicial)
    if primeira:
        # ISTO É O QUE ANCORA O RELÓGIO NO PEDIDO. Sem gravar, a inscrição
        # nasce "nunca avisada" e o próximo ciclo a trata como atrasada — e
        # sem a ASSINATURA junto ele não teria com o que comparar, repetindo
        # na primeira hora a mensagem que a pessoa acabou de ler.
        marcar_envio(ident, texto_inicial, assin=assin_inicial)

    # A CONFIRMACAO DIZ O QUE FOI COMBINADO, e nao uma frase fixa. Ela
    # prometia "uma atualização por hora" para todo mundo — inclusive para quem
    # acabou de escolher receber só os marcos, ou só de manhã. Promessa que a
    # tela faz e o envio não cumpre é o jeito mais barato de a pessoa achar que
    # o recurso quebrou.
    ini, fim = janela_efetiva(faixa[0] if faixa else None,
                              faixa[1] if faixa else None)
    quando_txt = "entre %s e %s" % (ini, fim)
    ritmo = {"tudo": "a cada hora, quando houver novidade",
             "menos": "a cada três horas, quando houver novidade",
             "marcos": "quando a carga mudar de etapa"}[cad]
    return {"ok": True, "id": ident,
            "telefone": numeros.formatar(fone),
            "dias": DIAS_VALIDADE,
            "primeira_enviada": primeira,
            "janela": [ini, fim],
            "cadencia": cad,
            "aviso": ("Pronto! Acabamos de enviar a primeira mensagem. "
                      "Avisamos %s, %s." % (ritmo, quando_txt)
                      if primeira else
                      "Cadastro feito. Avisamos %s, %s — a primeira mensagem "
                      "sai no próximo ciclo." % (ritmo, quando_txt))}


def _primeira_mensagem(alvo: dict, fone: str,
                       cadencia: str = CADENCIA_PADRAO) -> tuple[str | None, str]:
    """Manda o estado da carga agora. Devolve `(texto, assinatura)`.

    DEVOLVE O QUE FOI DITO, E NÃO UM BOOLEANO, porque quem chama precisa
    GRAVÁ-LO. Sem isso a inscrição nascia sem âncora — e o ciclo seguinte, sem
    ter com o que comparar, mandava tudo de novo. Medido em 05/09/2026: a
    inscrição das 12h38 recebeu a mensagem de cadastro e outra às 13h00, vinte
    e dois minutos depois, com o mesmo conteúdo.

    E DEVOLVE OS DOIS, não só o texto: é a ASSINATURA que o próximo ciclo
    compara. Ancorar só o texto deixaria a primeira hora de toda inscrição sem
    proteção nenhuma — exatamente a hora em que a pessoa acabou de dar o número
    e está mais propensa a bloquear.
    """
    try:
        from . import aviso
        carga = aviso._carga_da_inscricao({
            "grupo": alvo["grupo"], "empresa": alvo["empresa"],
            "filial": alvo["filial"], "numero": alvo["numero"],
            "serie": alvo["serie"]})
        texto = aviso._texto(carga) if carga else None
        if not texto:
            # SEM O QUE DIZER nao vira mensagem vazia nem "cadastro efetuado":
            # a primeira coisa que a pessoa recebe tem de ser a carga dela.
            return None, ""
        # A ANCORA NASCE NA CADENCIA ESCOLHIDA. Ancorar com a régua "tudo" e
        # comparar depois com a régua "marcos" faria a primeira comparação
        # falhar sempre — e a pessoa que pediu menos mensagens receberia uma a
        # mais logo de saída, que é o contrário do que ela escolheu.
        assin = mensagem.assinatura(
            [carga], so_marcos=CADENCIAS.get(cadencia, {}).get("so_marcos",
                                                              False))
        from ..whatsapp import envio as wa
        # JANELA PROPRIA, e so para ESTA mensagem.
        #
        # A janela geral (08:00-20:00) existe para a empresa nao disparar
        # mensagem em cliente de madrugada, e continua valendo para o aviso
        # horario. Mas esta aqui nao e disparo: e resposta a um botao que a
        # pessoa apertou ha dois segundos, com o celular na mao. Bloquea-la
        # faz o recurso parecer quebrado — medido as 23h08, a inscricao gravou
        # e a mensagem foi recusada com "fora da janela".
        #
        # A casa ja preve isso: `regras_efetivas` deixa o modelo AMPLIAR a
        # janela, e documenta que quem edita decide. Aqui quem decide e este
        # comentario.
        # `regras` SUBSTITUI a configuracao inteira, nao remenda: passar so a
        # janela derruba o envio num KeyError em `c["ativo"]`. Entao parte-se
        # da geral e troca-se UM campo — assim o interruptor, o limite do dia e
        # o teto por numero continuam valendo, que e o ponto.
        from ..whatsapp import resposta
        r = wa.enviar(fone, texto + aviso.RODAPE, usuario="rastreio",
                      origem="rastreio_cadastro", regras=resposta.regras())
        # O TEXTO CRU, sem o rodapé: é o que quem atende vê como "a última
        # mensagem", e o rodapé muda de uma mensagem para outra (leva o número
        # do documento). Quem compara é a assinatura, que já nasce limpa disso.
        return (texto, assin) if r.get("ok") else (None, "")
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: primeira mensagem falhou: %s",
                    type(exc).__name__)
        return None, ""


def cancelar(termo: str, cnpj4: str, carga_id: str, telefone: str) -> dict:
    """Para de avisar. Nunca levanta.

    SAIR É MAIS FÁCIL QUE ENTRAR, de propósito: basta o telefone e a carga.
    Opt-out difícil não reduz cancelamento — vira bloqueio do número da
    empresa, e aí todos os outros clientes param de receber também.
    """
    if not numeros.valido(telefone):
        return {"ok": False, "motivo": "Informe o celular usado no cadastro."}
    fone = numeros.normalizar(telefone)
    alvo, motivo = _chaves(termo, cnpj4, carga_id)
    if motivo:
        return {"ok": False, "motivo": motivo}
    if not alvo:
        return {"ok": False, "motivo": "Não encontramos essa carga."}
    try:
        pglocal.executar("""
            UPDATE rst_inscricao
               SET ativo = FALSE, cancelado_em = now(), cancelado_por = 'pagina'
             WHERE grupo=%s AND empresa=%s AND filial=%s AND numero=%s
               AND serie=%s AND telefone=%s AND ativo""",
            (alvo["grupo"], alvo["empresa"], alvo["filial"], alvo["numero"],
             alvo["serie"], fone))
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: cancelamento falhou: %s", type(exc).__name__)
        return {"ok": False, "motivo": "Não foi possível cancelar agora."}
    # RESPOSTA IGUAL tenha havido inscrição ou não: diferenciar as duas diria a
    # quem chutou um telefone que ele acompanha esta carga.
    return {"ok": True, "aviso": "Se este número estava cadastrado, ele não "
                                 "receberá mais avisos desta carga."}


def cancelar_por_telefone(telefone: str, numero: int | None = None) -> int:
    """Tira o telefone das cargas. Devolve quantas saíram.

    SEM `numero`, tira de TODAS: quem responde só "SAIR" quer parar com tudo, e
    exigir que ele liste as cargas uma a uma seria transformar a saída em
    formulário — quem não consegue sair bloqueia o número.

    COM `numero`, tira de UMA. Com várias cargas acompanhadas, a pessoa quase
    sempre quer parar a que já chegou e continuar com as outras; oferecer só o
    "tudo ou nada" faz quem queria sair de uma sair de todas, e essa pessoa não
    volta a se cadastrar.
    """
    # AS DUAS FORMAS DO MESMO NUMERO. O WhatsApp guarda contas antigas SEM o
    # nono digito, entao a mesma pessoa e `5541984251704` quando digita na
    # pagina e `554184251704` quando responde a mensagem. Procurar so pela
    # normalizada fazia o SAIR chegar, ser processado e nao achar inscricao
    # nenhuma — "nao funciona" de fora, silencio de dentro.
    formas = numeros.variantes(telefone)
    if not formas:
        return 0
    try:
        if numero is None:
            return pglocal.executar("""
                UPDATE rst_inscricao
                   SET ativo = FALSE, cancelado_em = now(),
                       cancelado_por = 'whatsapp'
                 WHERE telefone = ANY(%s) AND ativo""",
                (formas,)) or 0
        # O NUMERO SOZINHO NAO E CHAVE — a chave e (grupo, empresa, filial,
        # numero, serie). Mas quem responde no WhatsApp digita o que esta na
        # mensagem, que e so o numero; casar por ele DENTRO das inscricoes
        # daquele telefone e seguro, porque o alcance ja esta limitado a quem
        # pediu.
        return pglocal.executar("""
            UPDATE rst_inscricao
               SET ativo = FALSE, cancelado_em = now(),
                   cancelado_por = 'whatsapp'
             WHERE telefone = ANY(%s) AND numero = %s AND ativo""",
            (formas, numero)) or 0
    except Exception:  # noqa: BLE001
        return 0


#: A CONSULTA QUE O AVISO LÊ, num lugar só e não dentro da função.
#:
#: Ela é constante porque tem um GUARD que a executa contra um schema
#: descartável (`tests/rastreio/test_ancora_do_telefone.py`): o piso de uma
#: mensagem por hora é uma regra de banco, escrita em SQL, e regra em SQL que
#: nenhum teste roda é regra que se confere lendo — foi assim que o
#: arredondamento abaixo passou catorze dias no ar.
#:
#: `floor`, E NÃO `::int`. O cast de `double precision` para `int` no Postgres
#: ARREDONDA: `59m31s` virava `60`, e o piso de 60 minutos era, na prática,
#: 59min30s. Não é teoria — em 06/09/2026 o telefone final 9121 recebeu duas
#: mensagens separadas por 59,9 minutos. O piso existe para o número da empresa
#: não ser bloqueado; um piso que arredonda para baixo é um freio que afrouxa
#: sozinho, sem ninguém decidir isso.
ATIVAS_SQL = """
    SELECT id, grupo, empresa, filial, numero, serie, telefone,
           ultimo_texto, ultima_assinatura, ultimo_envio, envios,
           criado_em, janela_inicio, janela_fim, cadencia,
           -- A ÂNCORA DO TELEFONE, calculada no banco para não
           -- depender do relógio de quem lê. `max(ultimo_envio)` é a
           -- última vez que FALAMOS com ele; quando nunca falamos,
           -- vale o pedido mais ANTIGO — quem está esperando desde as
           -- 12h38 não pode ir para o fim da fila porque pediu uma
           -- segunda carga às 14h.
           (SELECT floor(extract(epoch FROM now() - coalesce(
                     max(i2.ultimo_envio), min(i2.criado_em)))/60)
              FROM rst_inscricao i2
             WHERE i2.telefone = i.telefone
               AND i2.ativo AND i2.expira_em > now())::int
             AS desde_min
    FROM rst_inscricao i
    WHERE ativo AND expira_em > now()
    ORDER BY coalesce(ultimo_envio, criado_em)"""


def ativas(esquema: str | None = None) -> list[dict]:
    """As inscrições que ainda valem. A tarefa de aviso parte daqui.

    `esquema` existe para o GUARD, que precisa rodar esta consulta contra um
    schema descartável. Produção nunca passa nada — e é de propósito que o
    padrão seja `None`: um teste que esqueça de redirecionar lê e escreve em
    cima do cliente de verdade.
    """
    try:
        return [dict(r) for r in pglocal.query(ATIVAS_SQL, esquema=esquema)]
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: leitura de inscrições falhou: %s",
                    type(exc).__name__)
        return []


def marcar_envio(ident: int, texto: str, *, assin: str = "") -> None:
    """Grava o que saiu. `assin` é o que decide o PRÓXIMO envio.

    OS DOIS TÊM PAPÉIS DIFERENTES e por isso são duas colunas: `ultimo_texto` é
    para quem atende saber o que o cliente recebeu; `ultima_assinatura` é a
    comparação do ciclo seguinte. Guardar só o texto foi o defeito de
    06/09/2026 — ele muda a cada ciclo pelo frescor da posição, e a comparação
    nunca casava.

    `assin` é NOMEADO e tem padrão vazio porque o valor certo é sempre
    calculado por quem tem as cargas em mãos. Um posicional a mais seria
    preenchido com o texto por engano no primeiro chamador distraído — e o
    sintoma disso é mudo: volta a mandar mensagem repetida, sem erro nenhum.
    """
    try:
        pglocal.executar("""
            UPDATE rst_inscricao
               SET ultimo_envio = now(), ultimo_texto = %s,
                   ultima_assinatura = %s, envios = envios + 1
             WHERE id = %s""", (texto, assin, ident))
    except Exception:  # noqa: BLE001
        pass


def encerrar(ident: int, motivo: str) -> None:
    """Fecha a inscrição — entrega feita, ou carga que não se acompanha mais."""
    try:
        pglocal.executar("""
            UPDATE rst_inscricao
               SET ativo = FALSE, cancelado_em = now(), cancelado_por = %s
             WHERE id = %s""", (motivo[:40], ident))
    except Exception:  # noqa: BLE001
        pass


def listar_por_telefone(telefone: str) -> list[dict]:
    """As cargas que um telefone acompanha AGORA. Nunca levanta.

    É o que a palavra CARGAS no WhatsApp responde. Sem isto, a única lista que
    existia era a mensagem horária — e quem quisesse sair de uma no meio da
    noite não tinha como saber o número dela sem rolar a conversa para trás.

    A BUSCA ACEITA AS DUAS FORMAS do número (com e sem o nono dígito), pela
    mesma razão do cancelamento: o WhatsApp identifica contas antigas sem ele.
    """
    formas = numeros.variantes(telefone)
    if not formas:
        return []
    try:
        return [dict(r) for r in pglocal.query("""
            SELECT id, grupo, empresa, filial, numero, serie, telefone,
                   ultimo_texto, ultimo_envio, envios, criado_em
            FROM rst_inscricao
            WHERE telefone = ANY(%s) AND ativo AND expira_em > now()
            ORDER BY criado_em""", (formas,))]
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: listagem por telefone falhou: %s",
                    type(exc).__name__)
        return []
