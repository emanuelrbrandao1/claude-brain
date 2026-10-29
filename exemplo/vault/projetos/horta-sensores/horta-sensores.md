---
tipo: projeto
status: ativo
pasta: ~/projetos/horta-sensores
verificado_em: 2030-04-12
---

# horta-sensores

Microcontrolador lendo dois sensores capacitivos de umidade e mandando a leitura por MQTT
para um painel local.

## Estado atual (em 2030-04-12)
Leitura travada em 100% no sensor 2; suspeita de curto no divisor resistivo.

## Decisões em vigor
- MQTT local em vez de serviço na nuvem: a horta não precisa de acesso externo.

## Armadilhas conhecidas
- Sensor capacitivo barato varia com a temperatura: calibrar com a terra na mesma hora do dia.

## Código
Firmware em `firmware/`, painel em `painel/`. Testes do conversor em `firmware/test/`.

## Registro e temas
Registro: [[Registro horta-sensores]]
- [[Calibracao de umidade]]: limites seco/molhado a refazer depois da troca do resistor
