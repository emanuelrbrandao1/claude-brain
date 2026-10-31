#!/usr/bin/env bash
# Teste de ponta a ponta com o Claude Code de verdade. Custa dinheiro (3 sessões curtas, com teto
# por sessão) e cria uma conversa curta no histórico do Claude Code. Ver o cabeçalho de rodar_e2e.py.
#
# Uso: tests/e2e/rodar_e2e.sh            (CLAUDE_BRAIN_E2E_MODELO, _ORCAMENTO, _TEMPO opcionais)
set -euo pipefail
AQUI=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY=${CLAUDE_BRAIN_PYTHON:-"$AQUI/../../.venv/bin/python"}
CLAUDE_BRAIN_E2E=1 exec "$PY" "$AQUI/rodar_e2e.py"
