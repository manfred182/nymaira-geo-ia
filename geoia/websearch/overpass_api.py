"""Fallback geoespacial usando Overpass API (OpenStreetMap).

Cuando los servidores WFS colombianos no responden, usa Overpass API
para obtener datos geoespaciales públicos de OpenStreetMap.
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_URL = OVERPASS_URLS[0]


async def overpass_query(bbox: list[float], feature_type: str = "all",
                         limit: int = 50) -> dict[str, Any]:
    """Consulta Overpass API con un bounding box.

    Args:
        bbox: [minx, miny, maxx, maxy] en EPSG:4326
        feature_type: 'nodes', 'ways', 'relations' o 'all'
        limit: maximo de elementos
    """
    import httpx

    minx, miny, maxx, maxy = bbox
    south, west, north, east = miny, minx, maxy, maxx

    # Mapear feature_type a Overpass tags
    tag_map = {
        "catastral": '["building"]',
        "ambiental": '["natural"]',
        "productiva": '["landuse"]',
        "all": '',
    }
    tag = tag_map.get(feature_type, "")

    query = f'[out:json][timeout:15];(node{tag}({south},{west},{north},{east}););out body {limit};'

    try:
        last_error = None
        for url in OVERPASS_URLS:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(url, 
                        content=query.encode("utf-8"),
                        headers={"User-Agent": "Nymaira/1.0", "Content-Type": "text/plain"})
                    if r.status_code == 200:
                        data = r.json()
                        elements = data.get("elements", [])
                        logger.info(f"overpass: {len(elements)} elementos via {url}")
                        return {"elements": elements, "count": len(elements)}
                    else:
                        last_error = f"HTTP {r.status_code}"
                        logger.warning(f"overpass: {last_error} en {url}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"overpass: {last_error} en {url}")
        return {"elements": [], "count": 0, "error": last_error or "todos los servidores fallaron"}
    except Exception as e:
        logger.warning(f"overpass: {e}")
        return {"elements": [], "count": 0, "error": str(e)}


def overpass_to_geojson(data: dict) -> dict:
    """Convierte resultados de Overpass a GeoJSON FeatureCollection."""
    elements = data.get("elements", [])
    features = []

    # Indexar nodos por id
    nodes = {}
    for el in elements:
        if el["type"] == "node":
            nodes[el["id"]] = el

    for el in elements:
        if el["type"] == "node":
            # Nodo individual - incluir siempre
            tags = el.get("tags", {})
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [el["lon"], el["lat"]]
                },
                "properties": {**tags, "_osm_id": el["id"], "_osm_type": "node"}
            })
        elif el["type"] in ("way", "relation"):
            # Way o relation - reconstruir geometría
            tags = el.get("tags", {})
            coords = _build_way_coords(el, nodes)
            if coords and tags:
                geom_type = "Polygon" if el.get("type") == "way" and coords[0] == coords[-1] else "LineString"
                if geom_type == "Polygon":
                    coords = [coords]
                features.append({
                    "type": "Feature",
                    "geometry": {"type": geom_type, "coordinates": coords},
                    "properties": {**tags, "_osm_id": el["id"], "_osm_type": el["type"]}
                })

    return {"type": "FeatureCollection", "features": features}


def _build_way_coords(way: dict, nodes: dict) -> list[list[float]]:
    """Construye lista de coordenadas desde un way y sus nodos."""
    coords = []
    for nid in way.get("nodes", []):
        node = nodes.get(nid)
        if node:
            coords.append([node["lon"], node["lat"]])
    return coords


async def buscar_entidades_cercanas(bbox: list[float], categoria: str = "all",
                                     limit: int = 30) -> dict[str, Any]:
    """Busca entidades geográficas cercanas al bbox usando Overpass.

    Returns:
        dict con 'geojson', 'count', 'resumen'
    """
    data = await overpass_query(bbox, categoria, limit)
    geojson = overpass_to_geojson(data)

    # Generar resumen
    resumen = {}
    for f in geojson.get("features", []):
        props = f.get("properties", {})
        # Detectar tipo por tags
        for key in ("building", "landuse", "natural", "water", "highway", "amenity"):
            if key in props:
                val = props[key]
                resumen[key] = resumen.get(key, 0) + 1
                break

    return {
        "geojson": geojson,
        "count": geojson.get("count", len(geojson.get("features", []))),
        "resumen": resumen,
        "fuente": "OpenStreetMap/Overpass",
    }
