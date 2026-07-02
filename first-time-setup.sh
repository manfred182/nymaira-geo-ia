#!/usr/bin/env bash
# GEOIA - Instalacion Completa (Mac/Linux)
cd "$(dirname "$0")"
echo "============================================"
echo "  GEOIA - INSTALACION COMPLETA"
echo "============================================"
echo ""
python3 -m geoia.cli setup --dev 2>/dev/null || python -m geoia.cli setup --dev
if [ $? -eq 0 ]; then
    echo ""
    echo "Descargando modelos..."
    python3 -m geoia.cli download-models 2>/dev/null || python -m geoia.cli download-models
fi
echo ""
echo "============================================"
echo "  LISTO - Ejecuta: bash run.sh"
echo "============================================"
