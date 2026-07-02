#!/usr/bin/env bash
# GEOIA - Instalacion (Mac/Linux)
cd "$(dirname "$0")"
python3 -m geoia.cli setup --dev "$@" 2>/dev/null || python -m geoia.cli setup --dev "$@"
