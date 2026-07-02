#!/usr/bin/env bash
# GEOIA - Descargar Modelos (Mac/Linux)
cd "$(dirname "$0")"
echo "============================================"
echo "  GEOIA - Descarga de Modelos"
echo "============================================"
echo ""
echo "  Modelos:"
echo "    [1] sentence-transformers/all-MiniLM-L6-v2"
echo "    [2] google/vit-base-patch16-224"
echo ""
python3 -m geoia.cli download-models 2>/dev/null || python -m geoia.cli download-models
