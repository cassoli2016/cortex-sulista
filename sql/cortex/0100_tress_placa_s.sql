-- 0100 · O 'S' no fim da placa da 3S: juntar o que já está gravado.
--
-- MEDIDO EM 18/09/2026, a pedido de quem opera ("algumas placas na 3S foi
-- colocado um S no final da placa; veja se isso interfere em algo"): 19 das
-- 235 carretas do espelho estavam gravadas com oito caracteres — `JOK3001S`.
-- A chave da casa é a PLACA, então essas 19 não casavam com NADA: nem com o
-- cadastro do ERP, nem com a lista de rastreadores, nem com a régua diária.
-- Elas comunicavam todo dia e o painel dizia "nunca comunicou".
--
-- A coleta já normaliza daqui para frente (`api/tress/coleta._placa`). Esta
-- migration arruma o PASSADO — e o passado tem duas histórias diferentes
-- dentro dele, medidas uma a uma antes de escrever isto:
--
-- 1. SETE são a MESMA linha com a placa corrigida na 3S entre uma coleta e
--    outra (mesmo `idEquipamento`, `idVeiculo`, `NumSerie` e chassi; a forma
--    com 'S' recebeu `sumiu_em` no mesmo minuto em que a forma sem 'S'
--    apareceu). Alguém do outro lado já está corrigindo o cadastro.
-- 2. CINCO são DOIS RASTREADORES no MESMO chassi — o antigo, de série curta
--    (`4632…`), e o novo (`8626320…`), os dois vivos na conta. Aqui a placa é
--    a mesma no mundo real e o cadastro é que está em duplicata.
-- As SETE restantes só existem na forma com 'S': para essas, basta renomear.
--
-- AS TRÊS REGRAS DA JUNÇÃO, e por que são estas:
--
-- * O DIA É O QUE NÃO SE RECOLETA. `tress_posicao` guarda só a ÚLTIMA posição
--   e a coleta a repõe em meia hora; `tress_visto_dia` é histórico e, se
--   sumir, some para sempre — são os 219 dias que responderiam "comunicou no
--   dia 2?" e que hoje estão pendurados numa placa que não existe. Por isso
--   os dias são a PRIMEIRA coisa a mudar de dono, e por `ON CONFLICT DO
--   NOTHING`: o mesmo dia pelas duas formas é um dia só.
-- * A POSIÇÃO QUE FICA É A MAIS RECENTE das duas, nunca "a que sobrou". É a
--   mesma regra do `gravar_posicoes` ("a posição só avança") — sem ela, a
--   junção faria uma carreta que comunicou hoje voltar para 2024.
-- * O CADASTRO QUE MANDA É O MAIS NOVO, pelo `idVeiculo`, que na 3S é um
--   carimbo de tempo (`20260814145635`); e VIVO vence SUMIDO, porque a linha
--   que a coleta vai continuar atualizando é a da placa normalizada.
--
-- A FK ganha `ON UPDATE CASCADE` porque sem ela corrigir uma placa exige
-- apagar a posição antes — e apagar posição para arrumar texto é perder a
-- resposta de "está comunicando?" durante o conserto.

ALTER TABLE tress_posicao DROP CONSTRAINT IF EXISTS tress_posicao_placa_fkey;
ALTER TABLE tress_posicao
  ADD CONSTRAINT tress_posicao_placa_fkey FOREIGN KEY (placa)
  REFERENCES tress_veiculo(placa) ON UPDATE CASCADE ON DELETE CASCADE;

-- Os candidatos saem das TRÊS tabelas, não só do cadastro: placa que saiu da
-- conta continua com dias gravados, e ela é justamente a que ninguém olharia.
-- O corte é condicional, igual ao da coleta: só cai o 'S' quando os sete que
-- sobram formam placa brasileira válida (três letras, dígito, letra ou
-- dígito, dois dígitos). `AAA1234S` sem isso viraria adivinhação.
CREATE TEMP TABLE _placa_s ON COMMIT DROP AS
WITH todas AS (
  SELECT placa FROM tress_veiculo
  UNION SELECT placa FROM tress_posicao
  UNION SELECT placa FROM tress_visto_dia
)
SELECT placa AS com_s, substr(placa, 1, 7) AS base
  FROM todas
 WHERE length(placa) = 8
   AND right(placa, 1) = 'S'
   AND substr(placa, 1, 7) ~ '^[A-Z]{3}[0-9][0-9A-Z][0-9]{2}$';

-- 1) os DIAS mudam de dono (o que não se recoleta vai primeiro)
INSERT INTO tress_visto_dia (placa, dia)
SELECT s.base, d.dia
  FROM tress_visto_dia d
  JOIN _placa_s s ON d.placa = s.com_s
ON CONFLICT (placa, dia) DO NOTHING;

DELETE FROM tress_visto_dia d
 USING _placa_s s
 WHERE d.placa = s.com_s;

-- 2) a POSIÇÃO da base, quando a base já é um veículo conhecido
INSERT INTO tress_posicao
  (placa, id_posicao, dt, latitude, longitude, velocidade, ignicao,
   satelites, uf, cidade, bairro, endereco, coletado_em)
SELECT s.base, p.id_posicao, p.dt, p.latitude, p.longitude, p.velocidade,
       p.ignicao, p.satelites, p.uf, p.cidade, p.bairro, p.endereco,
       p.coletado_em
  FROM tress_posicao p
  JOIN _placa_s s ON p.placa = s.com_s
 WHERE EXISTS (SELECT 1 FROM tress_veiculo v WHERE v.placa = s.base)
   AND NOT EXISTS (SELECT 1 FROM tress_posicao b WHERE b.placa = s.base);

UPDATE tress_posicao b
   SET id_posicao = p.id_posicao, dt = p.dt,
       latitude = p.latitude, longitude = p.longitude,
       velocidade = p.velocidade, ignicao = p.ignicao,
       satelites = p.satelites, uf = p.uf, cidade = p.cidade,
       bairro = p.bairro, endereco = p.endereco,
       coletado_em = p.coletado_em
  FROM tress_posicao p
  JOIN _placa_s s ON p.placa = s.com_s
 WHERE b.placa = s.base
   AND p.dt > b.dt;                      -- a posição só AVANÇA

-- 3) o CADASTRO: o mais novo manda, e vivo vence sumido
UPDATE tress_veiculo b
   SET frota = coalesce(a.frota, b.frota),
       modelo = coalesce(a.modelo, b.modelo),
       tipo = coalesce(a.tipo, b.tipo),
       id_equipamento = a.id_equipamento,
       id_veiculo = a.id_veiculo,
       num_serie = a.num_serie,
       chassi = coalesce(a.chassi, b.chassi)
  FROM tress_veiculo a
  JOIN _placa_s s ON a.placa = s.com_s
 WHERE b.placa = s.base
   AND coalesce(a.id_veiculo, '') > coalesce(b.id_veiculo, '');

UPDATE tress_veiculo b
   SET visto_em = greatest(b.visto_em, a.visto_em),
       sumiu_em = CASE WHEN a.sumiu_em IS NULL OR b.sumiu_em IS NULL
                       THEN NULL ELSE greatest(a.sumiu_em, b.sumiu_em) END
  FROM tress_veiculo a
  JOIN _placa_s s ON a.placa = s.com_s
 WHERE b.placa = s.base;

-- 4) quem só existe com 'S' é RENOMEADO (a posição vai junto, pela cascata)
UPDATE tress_veiculo v
   SET placa = s.base
  FROM _placa_s s
 WHERE v.placa = s.com_s
   AND NOT EXISTS (SELECT 1 FROM tress_veiculo b WHERE b.placa = s.base);

-- 5) e as duplicatas que sobraram saem (a cascata leva a posição com 'S')
DELETE FROM tress_veiculo v
 USING _placa_s s
 WHERE v.placa = s.com_s;

-- 6) A CONFERÊNCIA MORA AQUI DENTRO, na mesma transação: migration que
-- arruma dado e não confere o resultado é migration que se lê como feita.
DO $$
DECLARE sobrou integer;
BEGIN
  SELECT count(*) INTO sobrou FROM (
    SELECT placa FROM tress_veiculo
    UNION ALL SELECT placa FROM tress_posicao
    UNION ALL SELECT placa FROM tress_visto_dia
  ) t
  WHERE length(placa) = 8 AND right(placa, 1) = 'S'
    AND substr(placa, 1, 7) ~ '^[A-Z]{3}[0-9][0-9A-Z][0-9]{2}$';
  IF sobrou > 0 THEN
    RAISE EXCEPTION 'a junção do S deixou % linha(s) para trás', sobrou;
  END IF;
END $$;
