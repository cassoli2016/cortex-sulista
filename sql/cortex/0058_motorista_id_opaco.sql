-- O código de motorista é o CPF, e ele estava saindo do módulo.
--
-- O QUE SE DESCOBRIU (06/09/2026, cadastrando o primeiro usuário no app):
-- `cadastro.codigo` do ERP, para pessoa física, É O CPF. Os 80 vínculos criados
-- guardam CPF em `mot_vinculos.motorista_codigo` — e essa coluna, que nasceu
-- pensada como "a chave que casa com o ERP", tinha virado também o
-- IDENTIFICADOR PÚBLICO do motorista:
--
--   1. ia no `sub` do JWT, dentro do cookie do aparelho dele;
--   2. ia no `audit_log`, como `motorista:<cpf>`;
--   3. **ia para o NAVEGADOR** na lista de "quem está entrando", quando um
--      telefone serve a mais de um motorista — CPF de terceiro num payload.
--
-- A regra da casa é que CPF não entra em URL nem aparece inteiro. O terceiro
-- caso a viola de fato; os outros dois espalham o documento por lugares que
-- não precisam dele. Nenhum deles exposto até hoje (os 80 vínculos não têm
-- telefone repetido, então a lista de escolha nunca foi montada) — mas isso é
-- sorte de cadastro, não desenho.
--
-- A SEPARAÇÃO: o CPF fica onde precisa estar — a coluna que casa com o ERP — e
-- tudo que SAI do módulo passa a usar um id opaco. Quem lê `mot_vinculos` para
-- consultar o AVA continua usando `motorista_codigo`; quem emite token, grava
-- trilha ou responde ao navegador usa `id`.
--
-- POR QUE UM SERIAL E NÃO UM TOKEN ALEATÓRIO: o id não é segredo e não protege
-- nada sozinho — quem protege é a assinatura do JWT. Ele existe para NÃO SER um
-- documento. Um serial cumpre isso, cabe na trilha, é legível para quem
-- administra ("motorista 42") e não custa uma coluna de 32 bytes por linha.
-- Se um dia o id precisar ser imprevisível, aí sim ele vira token — e será
-- outra decisão, escrita.

ALTER TABLE mot_vinculos ADD COLUMN IF NOT EXISTS id bigserial;

-- UNIQUE e não PRIMARY KEY: a chave primária continua sendo o código do ERP,
-- que é o que garante "um vínculo por motorista". Trocar a PK exigiria mexer
-- na FK de `mot_sessoes` sem ganho nenhum — lá o código também não sai para
-- lugar nenhum, é junção interna.
ALTER TABLE mot_vinculos DROP CONSTRAINT IF EXISTS mot_vinculos_id_uk;
ALTER TABLE mot_vinculos ADD CONSTRAINT mot_vinculos_id_uk UNIQUE (id);

COMMENT ON COLUMN mot_vinculos.id IS
    'Identificador OPACO do motorista no app. É ele que vai no `sub` do token,
     no audit_log e em qualquer payload — nunca o `motorista_codigo`, que para
     pessoa física é o CPF. Serial e não token aleatório: ele não é segredo,
     existe para não ser um documento.';

COMMENT ON COLUMN mot_vinculos.motorista_codigo IS
    'O `cadastro.codigo` do ERP — para pessoa física, o CPF. Existe para CASAR
     COM O AVA e não sai deste módulo: quem precisa nomear o motorista para
     fora usa `id`. Guardado como text com cast na entrada porque tabela de
     terceiro não tem contrato de tipo (a `agrupadorgerencial` trocou de
     integer para varchar em 02/09/2026 e matou cinco telas).';
