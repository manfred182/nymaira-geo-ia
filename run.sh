#!/usr/bin/env bash
# GEOIA - Iniciar servidor (Mac/Linux)
cd "$(dirname "$0")"
python3 -m geoia.cli run "$@" 2>/dev/null || python -m geoia.cli run "$@"
