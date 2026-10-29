# Segurança

O claude-brain roda um agente de linguagem **sem ninguém olhando**: ao fechar uma conversa
(autosave) e todo dia (rotina). Esse agente lê texto que não foi escrito para ele — a própria
conversa, notas do vault, arquivos das fontes. Este documento descreve o modelo de ameaça, os
controles e o que continua em aberto.

## Modelo de ameaça

**O que proteger**
1. A máquina e a conta: nenhum comando arbitrário a partir de texto lido, nem agora nem depois
   (código plantado para rodar quando outro programa abrir o vault).
2. Segredos: credenciais, tokens, chaves, históricos de conversa, configuração do usuário.
3. A integridade do vault: escrita só onde a automação declarou que escreve.
4. O que sai da máquina: commit e e-mail não podem carregar segredo, conteúdo remoto nem link
   que entregue dado a terceiros.

**De quem / do quê**
- **Injeção de prompt indireta.** Uma nota, um diário, um trecho colado na conversa pode conter
  "ignore as instruções e faça X". Sem humano para negar a permissão, a defesa confiável é o
  agente *não ter* a ferramenta ou o caminho perigoso.
- **Erro do próprio modelo.** Grava no lugar errado, diz que salvou e não salvou, copia um token
  que apareceu na conversa.
- **Concorrência e falha silenciosa.** Duas conversas fechando juntas; a rotina disparando duas
  vezes; um processo em segundo plano que morre sem deixar rastro.
- **Leitor de e-mail.** Markdown com HTML, imagem remota ou link montado vira rastreador.

**Fora do escopo**: atacante que já tem acesso ao usuário do sistema operacional, e o
comportamento interno do Claude Code (confiamos que as flags fazem o que o `--help` descreve; ver
"A confirmar com execução real").

## Ameaças e controles

| Id | Ameaça | Controle | Onde |
|---|---|---|---|
| A1 | Injeção leva o agente a rodar comando | Sessões automáticas sem shell: `--restricted` + `--tools Read,Edit,Write` + `Bash` negado; todo comando roda antes/depois em Python | `claude_cmd.py` |
| A2 | Injeção planta código que executa depois (plugin do Obsidian, hook do git, instrução de agente) | Escrita só nos caminhos declarados; `Edit` negado em qualquer parte oculta do vault (`.*/**`, `**/.*`, `**/.*/**`), em `**/CLAUDE.md`, `**/CLAUDE.local.md`, `**/AGENTS.md` e `**/.claude/**`. Retrato de **todos** os arquivos (ocultos inclusive) antes e depois: mudança em caminho que executa ou instrui (`.obsidian/plugins/**` menos `data.json` (exceto o `data.json` de plugins que executam a própria configuração: shellcommands, templater, dataview, execute-code, buttons, js-engine, obsidian-git, quickadd, customjs), `.obsidian/snippets/**`, `community-plugins.json`, `.git/hooks/**`, `.git/config`, `CLAUDE.md`/`AGENTS.md`/`.claude/` em qualquer pasta, inclusive dentro do permitido) é FALHA; outra mudança fora do permitido é AVISO no log | `claude_cmd.py`, `vault.critico`, `vault.classificar` |
| A3 | Escrita sai do lugar por link simbólico | Antes de rodar, recusa link nos caminhos de escrita (ou caminho de escrita que é link) cujo destino fica fora do vault, fora dos próprios caminhos de escrita ou numa parte oculta | `vault.links_inseguros` |
| A4 | Agente lê credencial ou histórico | Leitura negada em `~/.config`, `~/.claude`, `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.netrc`, `~/.pgpass` e, dentro de cada pasta liberada, em `.env*`, `.envrc`, `.netrc`, `.pgpass`, `id_*`, `*.pem`, `*.key`; no vault, `.obsidian/` e `.git/`; a transcrição é lida só pelo Python do hook | `claude_cmd.py` |
| A5 | Agente herda permissões e hooks do usuário | `--restricted` ignora settings de usuário/projeto/local; `--strict-mcp-config` sem `--mcp-config`; `--disable-slash-commands`; `--settings '{"disableAllHooks": true}'` | `claude_cmd.py` |
| A6 | Variável de ambiente com segredo chega ao agente | Ambiente filho sem a variável da senha SMTP e sem variável cujo nome tenha, entre as partes separadas por `_`, `PASS`, `PAT`, `KEY` (ou termine em `KEY`) ou contenha `SENHA/PASSWORD/PASSWD/TOKEN/SECRET/CREDENTIAL`, nem `DATABASE_URL`. Ficam as que o Claude Code precisa: autenticação (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_FOUNDRY_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, as da AWS para Bedrock), `GOOGLE_APPLICATION_CREDENTIALS` (Vertex), limites terminados em `_TOKENS` e `CLAUDE_CODE_CLIENT_*` (mTLS) | `claude_cmd.variavel_sensivel`, `variavel_preservada` |
| A7 | Nota ou fonte é tratada como instrução | `--append-system-prompt` e o início do pedido (stdin) dizem que conteúdo lido é dado; o aviso do SessionStart é visível para a pessoa (`systemMessage`) e repete a regra | `claude_cmd.py`, `retomada.py` |
| A8 | `pasta:` ou configuração ampla demais casa com tudo | Caminho absoluto, existente, **estritamente dentro de uma raiz configurada** (padrão: a home), fora de diretório de sistema, sem ser ponto de montagem; links são resolvidos antes | `comum.validar_pasta` |
| A9 | Caminho de nota injeta texto no contexto | Caminho com caractere de controle ou crase é recusado; o aceito entra serializado em JSON | `retomada.py` |
| A10 | Temporário legível por outros ou dado no `ps` | Resumos em `TemporaryDirectory` (0700), arquivos `O_EXCL` 0600, apagados ao fim; pedido e payload por stdin | `autosave.py` |
| A11 | "Salvei" sem ter salvo; sucesso por mudança alheia | Autosave: OK só se uma nota **dentro dos caminhos de escrita** com o marcador `%% sessões: <id> %%` mudou durante a sessão (pelo retrato, não pelo relógio); rotina: o `Registro analise.md` mudou, o relatório existe; `--output-format json` para ler erro | `autosave.avaliar`, `rotina.py` |
| A12 | Execuções simultâneas corrompem estado ou geram FALHA falsa | Autosave e rotina seguram o **mesmo** lock do vault (`estado_dir/vault.lock`) durante toda a sessão automática; `flock -n` + `timeout` no `rotina.sh` (lock de instância em `estado_dir`; tempo padrão = 3 × `rotina.tempo_max_s` + 300 s, cobrindo espera do lock, ingest e relatório; SIGTERM do `timeout` vira FALHA no log e notificação); lock no registro de sessões de foco; estado gravado com temporário + `os.replace` | `comum.trava_do_vault`, `rotina.sh`, `foco.py` |
| A13 | Processo em segundo plano morre calado | Autosave e rotina envolvem a execução: exceção vira `FALHA excecao <tipo>` no log e notificação; lock ocupado também notifica | `autosave.processar_protegido`, `rotina.executar_protegido` |
| A14 | Segredo vai para commit ou e-mail | Varredura antes de commit/e-mail: chaves AWS/Google/Stripe, tokens GitHub/GitLab/Slack, `sk-`, JWT, chave privada, credencial em URL, `senha/password/token/secret… = valor` (aspas, crase, tabela, "é"), e-mails, e termos de um arquivo fora do repositório. Quantificadores limitados e padrões ancorados no início da palavra (sem retrocesso explosivo: linha hostil de 100 mil caracteres em centésimos de segundo); linha longa é varrida inteira, os padrões de formato fixo de uma vez e o resto (senha atribuída, e-mail, termos) em janelas de 4000 caracteres com 400 de sobreposição (maior que o maior casamento possível); casamento que encosta na borda de uma janela é ignorado ali e lido inteiro na vizinha, para um pedaço cortado não esconder o achado completo. Só bloqueia o que a sessão **acrescentou**: a contagem por tipo é comparada com o texto da nota antes da sessão (até 1 MB por nota); o que já estava vira aviso. Prosa ("a senha é armazenada…", `token: nenhum`) não conta: valor sem aspas precisa de dígito ou símbolo, salvo depois de `=` | `privacidade.py` |
| A15 | Commit leva arquivo que não devia; relatório se perde | `git add -- <arquivos>` e `git commit -- <arquivos>` só com o que a rotina gerou em `analise/`; nunca `-A`. Falha ou achado: nada é commitado nem enviado, fica pendente e é retentado (e revarrido) na próxima execução limpa; pendência de arquivo que sumiu (e não está no git) é descartada com log. O relatório da última semana fechada é gerado a partir do dia configurado mesmo se a execução daquele dia não rodou ou o ingest falhou | `rotina.py` |
| A16 | E-mail carrega HTML ativo, rastreador ou link que exfiltra | Markdown sem HTML cru; imagem só local, dentro da pasta do relatório (`realpath`), por `cid:`; link vira texto com a URL visível, sem `href`, salvo domínios de uma lista vazia por padrão | `enviar_email.py` |
| A17 | Conexão SMTP interceptada; senha exposta | `ssl.create_default_context()` em SMTPS ou STARTTLS; senha por variável de ambiente, keyring, ou arquivo do usuário com modo 0600 | `enviar_email.py` |
| A18 | Notificação vira injeção de comando | `notify-send -- …`; AppleScript fixo com `on run argv`; PowerShell com script fixo lendo `$env:`; texto limpo e nunca começando com `-`. Desligada por padrão | `notificar.py` |
| A19 | Log guarda conteúdo sensível | Só status, códigos, contagens e nomes de arquivo; arquivo 0600 em pasta 0700; rotação por tamanho; horário no fuso da configuração | `comum.Log` |
| A20 | Entrada malformada derruba ou engana scripts | `argparse` em todos; tabela de foco validada linha a linha com número e motivo; nenhum `except` vazio | todos |
| A21 | Nota escrita pela automação executa código quando o Obsidian a abre (injeção que vira RCE pelo **conteúdo**, sem tocar em pasta oculta) | Na varredura dos arquivos alterados, sintaxes de **plugins conhecidos** são bloqueantes (FALHA, nada commitado nem enviado): cercas ```` ```dataviewjs ````, ```` ```js-engine ````, ```` ```meta-bind-js-view ````, ```` ```run-… ````, ```` ```button ````, ```` ```templater… ```` (também com `~~~`, dentro de citação/callout `>` e de item de lista), inline `` `$=…` `` (com ou sem espaço depois da crase) e `<%…%>` (Templater). Bloco de shell (```` ```sh ````, ```` ```bash ```` …) é só aviso: plugins como o Execute Code só o rodam com clique, e bloquear tiraria das notas o registro de comandos, que é o uso mais comum. Só bloqueia código executável **novo ou alterado**: cada região (bloco cercado inteiro, cada `<% … %>`, cada `$=…`) é comparada por hash com as da nota antes da sessão; região idêntica à que a pessoa já tinha vira aviso, região com o corpo mudado ou a mais bloqueia, região removida não conta. As skills também proíbem esses blocos | `privacidade.EXECUTAVEL`, skills |

## Detalhes

### O comando das sessões automáticas

Montado em `scripts/claude_cmd.py` e testado em `tests/test_claude_cmd.py`:

| Flag | Para quê |
|---|---|
| `-p` | modo não interativo |
| `--restricted` | remove as ferramentas que executam código e o WebFetch, ignora os settings de usuário, projeto e local e prende as ferramentas de arquivo ao cwd e às pastas do `--add-dir` |
| `--tools Read,Edit,Write` | só essas três ferramentas existem na sessão |
| `--allowedTools 'Read(//abs/**)' 'Edit(//abs/projetos/**)' …` | leitura e escrita só nos caminhos declarados; `//` é caminho absoluto na sintaxe de permissão; a regra `Edit` vale para Edit e Write |
| `--disallowedTools Bash WebFetch WebSearch Agent NotebookEdit 'Edit(//vault/.*/**)' …` | negações explícitas (A1, A2, A4), redundantes de propósito |
| `--permission-mode dontAsk`, `--permission-prompts none` | o que não foi liberado é negado na hora, sem esperar resposta |
| `--strict-mcp-config` (sem `--mcp-config`) | nenhum servidor MCP é carregado |
| `--disable-slash-commands` | o pedido manda ler o `SKILL.md` pelo caminho |
| `--settings '{"disableAllHooks": true}'` | defesa extra contra recursão de hooks |
| `--output-format json` | detectar erro (`is_error`, `subtype`) em vez de confiar no código de saída |
| `--no-session-persistence` | a sessão automática não grava transcrição nova |
| `--resume <id> --fork-session` | (autosave) carrega a conversa numa cópia; a original não recebe o pedido automático |
| `--system-prompt-snapshot off` | (autosave) a conversa retomada traz o prompt de sistema gravado; sem snapshot, o aviso do `--append-system-prompt` entra |
| `--add-dir` | só as pastas fora do cwd: a skill, as fontes, a pasta temporária dos resumos |
| `--max-budget-usd`, `--model` | opcionais, da configuração |

Todas aparecem em `claude --help`; o teste `test_flags_existem_no_help` confere quando o Claude
Code está instalado (no CI ele é pulado). Escolhas onde havia alternativa:
- `--restricted` em vez de `--setting-sources`: o primeiro ignora settings de usuário, projeto e
  local de forma documentada; lista vazia no segundo não é documentada.
- MCP é cortado com `--strict-mcp-config` sem `--mcp-config`, porque um padrão de negação como
  `mcp__*` não é documentado.
- `disableAllHooks` é chave de configuração, não flag; se uma versão não a reconhecer, o
  `--restricted` já impede os hooks do usuário de carregar.

### Escopo de escrita

| Sessão | Pode escrever | Pode ler |
|---|---|---|
| autosave | `autosave.escrita` (padrão: `projetos/`, `conversas-avulsas/`, `Inicio.md`) | vault (sem `.obsidian/`, `.git/`), skill, resumos temporários |
| rotina | `analise.pasta` | vault (idem), skill, fontes declaradas |

O cwd das sessões automáticas é sempre o vault. Isso evita que, ao iniciar, o Claude Code carregue
o `CLAUDE.md` ou o `.claude/` da pasta de código; mas a conversa retomada pelo autosave **já
contém** o que o `CLAUDE.md` do projeto contribuiu na sessão original. Por isso as regras da
automação não dependem do cwd: valem pelas flags e pelo aviso no pedido. O `CLAUDE.md` que
existir dentro do vault não pode ser editado pela automação (A2).

### Retrato e pós-condição

O retrato registra `(mtime, tamanho, modo)` de **todo** arquivo e link do vault, sem seguir links.
Depois da sessão, cada mudança cai numa de três classes:
- **crítica** (FALHA): caminho que executa código ou instrui um agente, mesmo dentro do permitido;
- **permitida**: dentro dos caminhos de escrita, sem parte oculta; é o que se varre e commita;
- **aviso** (só log): o resto. É o caso normal de plugins do Obsidian gravando `data.json`,
  `graph.json`, `.trash/`, do `.git/` de um plugin de sincronização, ou da pessoa editando à mão.
`autosave.ignorar_mudancas` silencia de vez alguns arquivos (padrão: os `workspace*.json`).
Como autosave e rotina seguram o mesmo lock do vault, uma não vê a escrita da outra como alheia.

## Riscos residuais

- **O vault é legível pela automação.** Uma nota maliciosa pode induzir o modelo a copiar
  conteúdo de outra nota para o relatório, que pode sair por e-mail para o destino configurado.
  Mitigações: um só destino, configurado por você; varredura antes do envio; links sem `href`.
  Se o vault tem material que nunca pode sair, deixe `email.ativo = false` ou use a lista de
  termos proibidos.
- **A conversa retomada contém o que você digitou.** Segredo colado na conversa pode ser
  registrado; a varredura pega formatos conhecidos, não todos.
- **Regex não é DLP.** Há falso negativo e falso positivo:
  - formato desconhecido não é pego;
  - um segredo que **substitui** outro do mesmo tipo numa nota sem aumentar a contagem passa como
    preexistente (código executável não tem essa brecha: é comparado por conteúdo);
  - nome de senha com mais de 80 caracteres antes dele (`muito.longo…password = x`) não é pego;
  - e-mail com parte local maior que 64 caracteres (o limite do padrão de e-mail) não é pego;
  - um valor sem aspas com dígito depois de `senha:` bloqueia até você reescrever a frase.
- **Conteúdo executável é lista de plugins conhecidos.** A varredura cobre as sintaxes dos plugins
  mais comuns que executam código de nota (Dataview JS, Templater, JS Engine, Meta Bind, Execute
  Code, Buttons). Plugin que execute outra sintaxe não é reconhecido: revise os plugins que você
  instala e, se usar um desses, considere restringir a pasta da automação no próprio plugin.
- **`<%` dentro de código também bloqueia.** Um exemplo de ERB ou EJS num bloco de código cai na
  regra do Templater, porque o Templater lê o texto cru da nota, sem respeitar blocos de código.
  Só a ocorrência nova bloqueia; se a sessão precisar registrar algo assim, que descreva em prosa.
- **Nota grande é tratada como nova.** O texto anterior é guardado até 1 MB por nota; acima disso,
  tudo que a varredura achar na nota conta como novo e bloqueia.
- **Custo do texto anterior.** Antes de cada sessão automática, todas as notas dos caminhos de
  escrita (até 1 MB cada) são lidas para a memória. Num vault com milhares de notas em `projetos/`
  isso custa alguns segundos e a memória equivalente ao tamanho dessas notas; se pesar, restrinja
  `autosave.escrita` a pastas menores.
- **Pendência é revarrida inteira.** Arquivo que ficou pendente numa execução com falha não ganha
  o desconto de "preexistente" na próxima: precisa passar limpo para ser commitado ou enviado.
- **`data.json` de plugin comum é só AVISO.** Quem impede a escrita em `.obsidian/` é a negação de
  `Edit` em parte oculta (A2); a pós-condição é a segunda linha e trata como crítico apenas o
  `data.json` dos plugins que executam a própria configuração (lista em `vault.py`).
- **O caminho do clone e o temporário entram nas regras.** Com espaço ou vírgula neles a
  configuração recusa (clone o repositório num caminho sem espaço).
- **Inline `$=` que atravessa linhas.** A região executável de um `$=` vai até o fim da linha (no
  máximo 2000 caracteres); numa inline preexistente que continua na linha seguinte, ou passa desse
  tamanho, uma alteração depois do corte vira só AVISO.
- **Cerca de fechamento indentada.** Uma linha com crases indentada 4 espaços ou mais dentro de um
  bloco executável preexistente é lida como fechamento; o que vem depois dela fica fora da
  comparação por conteúdo. Caso artificial, mas possível.
- **Termo proibido muito longo em linha longa.** Linhas com mais de 4000 caracteres são lidas em
  janelas com sobreposição de 400; um termo seu cujo casamento tenha 400 caracteres ou mais pode
  escapar quando cair sobre a emenda entre duas janelas (os padrões internos têm no máximo cerca de
  360 caracteres e ficam cobertos).

## A confirmar com execução real

Os testes garantem o comando montado, não o que o Claude Code faz com ele. Depois de instalar ou
atualizar o Claude Code, rode uma vez de verdade e confira:
1. `--resume <id>` encontra a conversa com cwd = vault (diferente do cwd original).
2. `--resume` + `--fork-session` + `--no-session-persistence` + `--system-prompt-snapshot off`
   juntos: a conversa original não recebe o pedido e o aviso do `--append-system-prompt` aparece
   (o aviso também está no começo do pedido, por garantia).
3. As regras de negação com glob de arquivo oculto (`Edit(//vault/**/.*)`) e de `**/AGENTS.md`
   bloqueiam de fato a escrita — a pós-condição pega se não bloquearem, mas depois do fato.
4. Uma regra de `--allowedTools` com caminho absoluto longo é aceita como item único (por isso
   caminhos com espaço ou vírgula são recusados na configuração).
5. A chave `disableAllHooks` do `--settings` é reconhecida.
