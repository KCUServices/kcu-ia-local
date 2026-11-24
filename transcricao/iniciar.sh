#!/usr/bin/env sh
# Arranca o servidor de transcricao (Linux / macOS). Corre a partir desta pasta depois de criares o venv.
set -e
cd "$(dirname "$0")"
export TRANSCRICAO_HOST="${TRANSCRICAO_HOST:-127.0.0.1}"
export TRANSCRICAO_PORTA="${TRANSCRICAO_PORTA:-8000}"
export PYTHONUTF8=1
exec ./.venv/bin/python servidor_transcricao.py
