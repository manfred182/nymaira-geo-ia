#!/usr/bin/env python3
"""Procura automática de servidores WFS colombianos.

Escanea la lista de WFS colombianos, verifica conectividad y recupera capas automaticamente.
Usado por Nymaira para Geo IA, conexión con WFS temprana durante cruce espacial.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

# Add parent to path for imports
import sys

logger = logging.getLogger(__name__)

async def discover_wfs_servers(conn_timeout: int = 10) -> List[Dict[str, Any]]:
    """Explora todos los proveedores WFS colombianos, verifica conectividad y recupera capacidades."""
    try:
        from geoia.websearch.wfs_colombia import listar_servidores, wfs_get_capabilities
    except ImportError:
        logger.error("No se pudo importar wfs_colombia")
        return []

    servidores = listar_servidores()
    logger.info(f"Explorando {len(servidores)} servidores WFS colombianos...")

    resultados = []
    for servidor in servidores:
        url = servidor.get("url_wfs")
        if not url:
            continue

        try:
            caps = await asyncio.wait_for(
                wfs_get_capabilities(url),
                timeout=conn_timeout
            )

            if "capas" in caps and caps["capas"]:
                resultados.append({
                    "id": servidor["id"],
                    "nombre": servidor["nombre"],
                    "url": url,
                    "categoria": servidor.get("categoria", ""),
                    "descripcion": servidor.get("descripcion", ""),
                    "capas": caps["capas"],
                    "capacidad": len(caps["capas"]),
                    "titulo": caps.get("titulo", ""),
                    "saludable": True
                })
                logger.info(f"✓ {servidor['nombre']} - {len(caps['capas'])} capas")
            else:
                resultados.append({
                    "id": servidor["id"],
                    "nombre": servidor["nombre"],
                    "url": url,
                    "categoria": servidor.get("categoria", ""),
                    "descripcion": servidor.get("descripcion", ""),
                    "capas": [],
                    "capacidad": 0,
                    "titulo": "",
                    "saludable": False
                })
                logger.warning(f"✗ {servidor['nombre']} - sin capas disponibles")

        except asyncio.TimeoutError:
            resultados.append({
                "id": servidor["id"],
                "nombre": servidor["nombre"],
                "url": url,
                "categoria": servidor.get("categoria", ""),
                "descripcion": servidor.get("descripcion", ""),
                "capas": [],
                "capacidad": 0,
                "titulo": "",
                "saludable": False
            })
            logger.warning(f"⏱️ {servidor['nombre']} - timeout de conexión")

        except Exception as e:
            resultados.append({
                "id": servidor["id"],
                "nombre": servidor["nombre"],
                "url": url,
                "categoria": servidor.get("categoria", ""),
                "descripcion": servidor.get("descripcion", ""),
                "capas": [],
                "capacidad": 0,
                "titulo": "",
                "saludable": False,
                "error": str(e)
            })
            logger.error(f"✗ {servidor['nombre']} - error: {e}")

    resultados.sort(key=lambda x: x["capacidad"], reverse=True)
    return resultados


def format_discovery_result(resultados: List[Dict[str, Any]]) -> str:
    """Formatea el resultado del descubrimiento para visualización."""
    if not resultados:
        return "No se encontraron servidores WFS accesibles"

    lines = ["🌐 Servidores WFS colombianos (ordenados por capacidad):\n\n"]

    healthy_count = sum(1 for r in resultados if r["saludable"])
    lines.append(f"✅ {healthy_count} de {len(resultados)} servidores están disponibles\n")

    for resultado in resultados:
        if resultado["saludable"]:
            status = "🟢"
        elif "error" in resultado:
            status = "🔴"
        else:
            status = "🟡"

        lines.append(f"{status} **{resultado['nombre']}** ({resultado['categoria']})")
        lines.append(f"   {resultado['descripcion']}")
        lines.append(f"   {resultado['url']}")
        lines.append(f"   Capas: {resultado['capacidad']}")
        if resultado["titulo"]:
            lines.append(f"   Título: {resultado['titulo']}")
        lines.append("")

    lines.append("\n📋 Lista de servidores disponibles:")
    for resultado in resultados:
        status = "✅" if resultado["saludable"] else "❌"
        lines.append(f"{status} {resultado['nombre']} ({resultado['categoria']}) - {resultado['capacidad']} capas")

    return "\n".join(lines)


def main():
    """Función principal de descubrimiento."""
    print("🔍 Descubriendo servidores WFS colombianos...")
    print("=" * 60)

    resultados = asyncio.run(discover_wfs_servers())
    output = format_discovery_result(resultados)

    print(output)

    # Escribir resultados a archivo para uso por el frontend si es necesario
    resultados_path = Path("wfs_discovery_resultados.json")
    import json
    with open(resultados_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"\n📄 Resultados guardados en: {resultados_path}")


if __name__ == "__main__":
    main()
