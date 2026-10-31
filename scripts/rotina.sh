#!/usr/bin/env bash
# Rotina diária do claude-brain: uma execução por vez (flock -n) e tempo máximo (timeout).
# A lógica fica no rotina.py; este arquivo só garante o ambiente. O lock fica em
# `estado_dir/rotina.lock`, lido da mesma configuração que o rotina.py usa.
#
# Uso: rotina.sh [--config ARQ] [--dry-run] [--so-ingest] [--sem-email] [--forcar-relatorio]
# Variáveis: CLAUDE_BRAIN_PYTHON (padrão: .venv do repositório), CLAUDE_BRAIN_CONFIG (padrão:
#            config.toml do repositório), CLAUDE_BRAIN_TIMEOUT (s; padrão calculado pelo rotina.py:
#            3 × 2 × autosave.tempo_max_s + 60 (até 3 retentativas, cada uma esperando o lock e
#            rodando) + 3 × rotina.tempo_max_s (lock, ingest, relatório) + 300 de folga).
# Ao estourar o tempo, o `timeout` manda SIGTERM: o rotina.py registra FALHA no log e notifica
# antes de sair; 60 s depois, se ainda estiver vivo, vem o SIGKILL.
set -euo pipefail
umask 077

AQUI=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${CLAUDE_BRAIN_PYTHON:-"$AQUI/../.venv/bin/python"}

# Repassa só --config (nas formas `--config ARQ` e `--config=ARQ`) para descobrir o lock;
# o resto dos argumentos é da rotina. A expansão ${CONFIG[@]+...} funciona com array vazio
# também no bash 3.2 (macOS) sob `set -u`.
CONFIG=()
ANTERIOR=""
for ARG in "$@"; do
  if [[ $ANTERIOR == --config ]]; then CONFIG=(--config "$ARG"); fi
  if [[ $ARG == --config=* ]]; then CONFIG=(--config "${ARG#--config=}"); fi
  ANTERIOR=$ARG
done
LOCK=$("$PY" -I "$AQUI/rotina.py" ${CONFIG[@]+"${CONFIG[@]}"} --caminho-lock)
TEMPO=${CLAUDE_BRAIN_TIMEOUT:-$("$PY" -I "$AQUI/rotina.py" ${CONFIG[@]+"${CONFIG[@]}"} --tempo-total)}

# Sessões criadas pela rotina não disparam os hooks (defesa extra: elas já rodam sem hooks).
export CLAUDE_BRAIN_SEM_AUTOSAVE=1 CLAUDE_BRAIN_SEM_RETOMADA=1

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "rotina já está rodando; saindo sem fazer nada" >&2
  exit 0
fi
# O descritor 9 (o lock) passa para o processo abaixo e só é solto quando ele termina.
exec timeout --kill-after=60 "$TEMPO" "$PY" -I "$AQUI/rotina.py" "$@"
