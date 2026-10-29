# Modelos de nota

Nomes de arquivo sem acento; só letras, números, espaço e hífen.

## Registro do projeto

Arquivo: `projetos/<projeto>/Registro <projeto>.md`

```markdown
---
tipo: registro
created_at: AAAA-MM-DD
updated_at: AAAA-MM-DD
---

# Registro <projeto>

Projeto: [[<projeto>]]

## AAAA-MM-DD · <Título do que foi feito no dia>
Temas: [[<Tema>]]
%% sessões: <session_id> %%

**Objetivo:** ...
**O que foi feito:** ...
**Decisões:** ...
**Estado no fim do dia:** ...
**Pendências:** ...
```

- Entradas em ordem decrescente de data.
- `Temas:` só quando o dia tocou algum tema; `%% sessões %%` sempre (lista separada por vírgula
  se o dia teve mais de uma conversa). É por ela que o hook acha a conversa no vault.

## Tema (frente que se repete)

Arquivo: `projetos/<projeto>/temas/<Tema>.md`

```markdown
---
tipo: frente
created_at: AAAA-MM-DD
updated_at: AAAA-MM-DD
---

# <Tema>

Projeto: [[<projeto>]]

<Um parágrafo: que frente é essa e onde está o material.>

## Estado atual (em AAAA-MM-DD)
## Decisões em vigor
## Armadilhas conhecidas
## Dias
- [[Registro <projeto>#AAAA-MM-DD · Título]]: o que o dia fez nessa frente
```

## Nota de projeto

Arquivo: `projetos/<pasta>/<pasta>.md`

```markdown
---
tipo: projeto
status: ativo            # ativo | parado | concluido
pasta: /caminho/absoluto/da/pasta
outras_pastas: []        # opcional
verificado_em: AAAA-MM-DD
---

# <pasta>

<Um parágrafo: o que é e para que serve.>

## Estado atual (em AAAA-MM-DD)
## Decisões em vigor
## Armadilhas conhecidas
## Código
## Registro e temas
Registro: [[Registro <pasta>]]
- [[<Tema>]]: estado em uma linha
```

`pasta:` precisa ser absoluta, existir e ficar dentro das raízes configuradas (por padrão, a
home). Diretório de sistema, disco montado ou a própria home são ignorados pelos hooks (senão
toda conversa casaria com o projeto).

## Conversas avulsas

Arquivo: `conversas-avulsas/conversas-avulsas.md`, mesmo formato de entrada do registro, sem
`Temas:`. Num dia com mais de um assunto, um bloco `### <assunto>` por assunto.
