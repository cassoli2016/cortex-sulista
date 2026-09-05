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
from . import consulta

log = logging.getLogger("cortex.rastreio.assinatura")

#: Quanto tempo a inscrição dura sem ninguém renovar. Ninguém volta para
#: cancelar: a carga chega, a pessoa esquece, e o aviso seguiria para sempre.
DIAS_VALIDADE = 15

#: Teto de inscrições por telefone numa janela. Quem quiser usar a página como
#: disparador esbarra aqui antes de conseguir volume.
MAX_POR_FONE = 5
JANELA_FONE_H = 24

#: Teto de telefones acompanhando a MESMA carga. Uma carga tem remetente,
#: destinatário e quem espera na doca — não trinta pessoas.
MAX_POR_CARGA = 8


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
              ip: str = "") -> dict:
    """Passa a avisar este telefone sobre esta carga. Nunca levanta."""
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
            cur.execute("""
                SELECT count(*)::int AS n FROM rst_inscricao
                WHERE telefone = %s AND criado_em > now() - make_interval(hours => %s)""",
                (fone, JANELA_FONE_H))
            if cur.fetchone()["n"] >= MAX_POR_FONE:
                return {"ok": False,
                        "motivo": "Este número já tem muitos acompanhamentos "
                                  "hoje. Tente novamente amanhã."}

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
    primeira = _primeira_mensagem(alvo, fone)

    return {"ok": True, "id": ident,
            "telefone": numeros.formatar(fone),
            "dias": DIAS_VALIDADE,
            "primeira_enviada": primeira,
            "aviso": ("Pronto! Acabamos de enviar a primeira mensagem. "
                      "Você recebe uma atualização por hora enquanto a carga "
                      "estiver em viagem."
                      if primeira else
                      "Cadastro feito. A primeira mensagem sai no próximo "
                      "ciclo de envio.")}


def _primeira_mensagem(alvo: dict, fone: str) -> bool:
    """Manda o estado da carga agora. Devolve se saiu. Nunca levanta."""
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
            return False
        from ..whatsapp import envio as wa
        r = wa.enviar(fone, texto + aviso.RODAPE, usuario="rastreio",
                      origem="rastreio_cadastro")
        return bool(r.get("ok"))
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: primeira mensagem falhou: %s",
                    type(exc).__name__)
        return False


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


def cancelar_por_telefone(telefone: str) -> int:
    """Tira o telefone de TODAS as cargas. É o que a palavra SAIR no WhatsApp
    aciona — quem pede para parar quer parar com tudo, não com uma carga."""
    if not numeros.valido(telefone):
        return 0
    try:
        return pglocal.executar("""
            UPDATE rst_inscricao
               SET ativo = FALSE, cancelado_em = now(), cancelado_por = 'whatsapp'
             WHERE telefone = %s AND ativo""",
            (numeros.normalizar(telefone),)) or 0
    except Exception:  # noqa: BLE001
        return 0


def ativas() -> list[dict]:
    """As inscrições que ainda valem. A tarefa de aviso parte daqui."""
    try:
        return [dict(r) for r in pglocal.query("""
            SELECT id, grupo, empresa, filial, numero, serie, telefone,
                   ultimo_texto, ultimo_envio, envios
            FROM rst_inscricao
            WHERE ativo AND expira_em > now()
            ORDER BY coalesce(ultimo_envio, criado_em)""")]
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: leitura de inscrições falhou: %s",
                    type(exc).__name__)
        return []


def marcar_envio(ident: int, texto: str) -> None:
    try:
        pglocal.executar("""
            UPDATE rst_inscricao
               SET ultimo_envio = now(), ultimo_texto = %s, envios = envios + 1
             WHERE id = %s""", (texto, ident))
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
