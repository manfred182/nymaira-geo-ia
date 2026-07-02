#!/usr/bin/env bash
# GEOIA - Portable (Mac/Linux)
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
    echo "============================================"
    echo "  GEOIA - Primer inicio"
    echo "============================================"
    echo ""
    echo "  Configurando entorno automaticamente..."
    echo ""
    python3 -m geoia.cli setup --dev 2>/dev/null || python -m geoia.cli setup --dev
fi
python3 -m geoia.cli run 2>/dev/null || python -m geoia.cli run
