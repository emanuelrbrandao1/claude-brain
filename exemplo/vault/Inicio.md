---
tipo: indice
---

# Início

Vault de exemplo do claude-brain. Tudo aqui é fictício: a persona é uma desenvolvedora
que mantém três projetos paralelos no tempo livre e registra sessões de foco.

## Convenções (o contrato entre as notas e a automação)

- Nota principal de projeto: `projetos/<nome>/<nome>.md`, com `tipo: projeto` e `pasta:`
  (caminho absoluto da pasta de código; é por ele que o hook de início acha a nota).
- Histórico: um `Registro <nome>.md` por projeto, uma entrada por dia, a mais nova em cima,
  cabeçalho `## AAAA-MM-DD · Título`.
- Frentes que se repetem: `projetos/<nome>/temas/<Tema>.md` (`tipo: frente`).
- Conversas sem projeto: `conversas-avulsas/conversas-avulsas.md`.
- Sessões de foco: `foco/Sessoes de foco.md`.
- Análise e relatórios automáticos: `analise/`.

## Projetos

| Projeto | O que é | Status |
|---|---|---|
| [[horta-sensores]] | sensores de umidade para uma horta de varanda | ativo |
| [[leitor-rss]] | leitor de RSS de linha de comando | ativo |
| [[receitas-api]] | API pequena de receitas para estudar testes | parado |
