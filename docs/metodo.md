# Método

O projeto foi conduzido com [Spec Kit](https://github.com/github/spec-kit): primeiro os
princípios, depois a especificação do *quê*, o plano do *como*, a lista de tarefas e só então o
código. Este documento resume o caminho, incluindo uma especificação que foi jogada fora.

## 1. Constituição (os princípios que não se negociam)

1. **Histórico de conversa é privado.** Transcrições nunca vão para git, nuvem ou serviço
   externo. A automação lê a transcrição localmente e grava só o destilado.
2. **O humano no controle.** Nada sai da máquina (commit remoto, e-mail para terceiros) sem
   configuração explícita. Opt-in por pasta no autosave; notificação e e-mail desligados por
   padrão; ações destrutivas nunca são automáticas.
3. **Automação isolada e idempotente.** Sessão sem humano não tem shell nem rede; roda numa
   execução por vez; rodar duas vezes não duplica entrada; falha é registrada e avisada, nunca
   engolida.
4. **Convenções do vault são contrato.** `tipo:`, `pasta:`, a entrada `## AAAA-MM-DD · …` e o
   marcador `%% sessões %%` são interface entre as notas, os hooks e as skills. Mudar formato é
   mudar contrato: exige migração e teste.
5. **Determinístico onde dá.** Contar, validar e calcular é código testado; o modelo só faz o que
   código não faz bem — destilar.

## 2. Especificação

Histórias centrais:
- Ao fechar uma conversa de projeto, o que foi decidido e o estado final aparecem no vault, sem
  pedir.
- Ao abrir uma conversa na pasta de um projeto, o assistente sabe onde está o estado dele.
- Uma vez por dia, as fontes novas viram análise; uma vez por semana, um relatório com números.
- Sessões de foco registradas em texto simples, com alvos e melhores marcas calculados.

Critérios de aceite escritos como testes: "sessão que termina depois da meia-noite conta para o dia de foco certo", "imagem
fora da pasta do relatório não vai no e-mail", "o comando da sessão automática não contém Bash".

## 3. A mudança de rumo

A primeira especificação previa um **bot de mensageiro com servidor próprio**: a pessoa mandaria
mensagens para o bot, que guardaria as notas, rodaria o resumo e responderia com os números.

A fase de pesquisa do plano levantou o custo real disso: um servidor sempre ligado, um webhook
exposto na internet, token do mensageiro para guardar, autenticação de quem fala com o bot,
fila para não perder mensagem, e um segundo lugar onde o conteúdo das notas trafegaria. Cada
item era superfície de ataque nova para resolver um problema que já tinha solução: o Claude Code
já roda em segundo plano (`-p`), retoma conversas por id, tem hooks de início e fim, e pode ser
usado pela nuvem quando a pessoa está longe do computador.

A especificação foi **substituída**, não remendada: o bot saiu, entraram os hooks locais e a
rotina agendada. O resultado tem menos peças, nenhuma porta aberta e custo zero de
infraestrutura. O registro da decisão ficou no plano, com o motivo, para ninguém propor o bot de
novo sem os mesmos números.

## 4. Plano

Decisões técnicas que saíram do plano:
- Python ≥ 3.11 só com biblioteca padrão nos hooks (rodam sem venv); `markdown` e `matplotlib`
  só onde precisa.
- Um módulo monta o comando do `claude -p`; ninguém mais monta argv à mão.
- Uma configuração TOML validada no carregamento; nenhum caminho fixo no código.
- Um parser só para a tabela de foco, usado pelos totais, pelo cálculo de ritmo e pelos gráficos (a versão
  anterior tinha dois parsers que divergiam).

## 5. Tarefas e revisão

Cada tarefa fechava com teste. Uma auditoria de segurança no meio do caminho achou que as sessões
automáticas ainda tinham shell liberado por lista de comandos permitidos; a correção foi
estrutural (mover todo comando para fora da sessão), não aumentar a lista de negações. Os achados
e o tratamento de cada um estão em [seguranca.md](seguranca.md).
