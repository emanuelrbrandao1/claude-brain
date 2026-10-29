---
tipo: registro
created_at: 2030-03-02
updated_at: 2030-04-12
---

# Registro horta-sensores

Projeto: [[horta-sensores]]

## 2030-04-12 · Diagnóstico da leitura travada em 100%
Temas: [[Calibracao de umidade]]
%% sessões: exemplo-sessao-1 %%

**Objetivo:** entender por que o sensor 2 lê 100% o tempo todo.
**O que foi feito:** medida a tensão no pino analógico com o sensor fora da terra: 0 V, o que
descarta o sensor e aponta para o divisor resistivo.
**Estado no fim do dia:** resistor de 10 kΩ suspeito; trocar e recalibrar.

## 2030-03-02 · Primeira leitura pelo MQTT
%% sessões: exemplo-sessao-0 %%

**O que foi feito:** firmware publicando a cada 5 min no tópico `horta/umidade/<n>`.
**Decisões:** intervalo de 5 min, porque a terra muda devagar e a bateria dura mais.
