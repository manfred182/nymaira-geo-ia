"""Conexion a IGAC Base Catastral Nacional via ArcGIS Hub API con manejo robusto de errores.

APIs soportadas:
  - IGAC Base Catastral Nacional (ArcGIS FeatureServer) — datos catastrales con geometría
  - IGAC Estadísticas Catastrales (_Base_2025__) — estadísticas municipales por DIVIPOLA
  - IGAC ArcGIS Hub — búsqueda de datasets geoespaciales

Manejo de errores:
  - DNS fallbacks para servicios colombianos (ArcGIS services2.arcgis.com)
  - Múltiples estrategias de consulta
  - Informes detallados de errores
"""

from __future__ import annotations
import json, logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuracion ───────────────────────────────────────────────────────────

IGAC_FEATURESERVER_URL = "https://services2.arcgis.com/RVvWzU3lgJISqdke/arcgis/rest/services/Base_Catastral_Publica_IGAC_10_2025/FeatureServer"
IGAC_HUB_URL = "https://datos-abiertos-igac-igac-oit.hub.arcgis.com"

# Mapeo de DIVIPOLA a codigo_municipio interno del IGAC para Florencia Caquetá
MUNICIPIO_CODIGOS = {
    "18001": "18029",  # Florencia (DIVIPOLA oficial a código interno IGAC)
    "18029": "18029",  # Mismo código
}

# ── Funciones auxiliares ───────────────────────────────────────────────────

def _divipola_to_codigo_municipio(divipola: str) -> str:
    """Convertir DIVIPOLA a codigo_municipio interno del IGAC."""
    return MUNICIPIO_CODIGOS.get(divipola, divipola)


# ── Consultas principales ───────────────────────────────────────────────────

async def query_igac_catastro(divipola: str = None, municipio: str = None, limit: int = 10) -> list[dict]:
    """Query IGAC Base Catastral Nacional con múltiples estrategias de fallback.
    
    Returns cadastral data for Florencia Caquetá or filtered by department/municipality.
    """
    from geoia.websearch.dns_cache import check_connectivity, resolve
    results = []
    
    # Determinar el código a usar
    target_codigo = None
    if divipola:
        target_codigo = _divipola_to_codigo_municipio(divipola)
    elif municipio:
        target_codigo = municipio
    
    # Verificar conectividad DNS antes de intentar
    resolve("services2.arcgis.com")
    
    # Estrategia 1: Usar FeatureServer directamente (más confiable)
    if target_codigo:
        fs_url = f"{IGAC_FEATURESERVER_URL}/7/query"  # U_TERRENO layer
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20) as client:
                params = {
                    "f": "json",
                    "where": f"codigo_municipio = '{target_codigo}'",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "resultRecordCount": min(limit, 50),
                    "outSR": 4326
                }
                
                r = await client.get(fs_url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    features = data.get("features", [])
                    
                    if features:
                        for feat in features:
                            attrs = feat.get("attributes", {})
                            geom = feat.get("geometry", {})
                            
                            # Obtener DIVIPOLA del atributo si está disponible
                            divipola_code = attrs.get("DIVIPOLA") or divipola
                            
                            result = {
                                "title": f"Predio catastral: {attrs.get('CODIGO', 'N/A')}",
                                "snippet": f"{attrs.get('CODIGO', 'N/A')} | Área: {attrs.get('Shape__Area', 0):,.0f} m² | Municipio: {attrs.get('codigo_municipio', 'N/A')}",
                                "url": "https://www.datos.gov.co/dataset/Base-Catastral-P-blica-IGAC-10-2025/dpbj-tyu6",
                                "source_name": "IGAC - Base Catastral Nacional",
                                "source_url": "https://www.datos.gov.co",
                                "categoria": "catastral",
                                "tipo": "api_directa",
                                "attributes": attrs,
                                "geometry": geom,
                                "divipola": divipola_code
                            }
                            results.append(result)
                    
                    if results:
                        return results
                        
        except Exception as e:
            logger.warning(f"FeatureServer query failed: {e}")
    
    # Estrategia 2: Intentar con ArcGIS Hub API (puede fallar por DNS)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            search_url = f"{IGAC_HUB_URL}/api/search/v1"
            r = await client.get(search_url, params={"q": "Base Catastral Pública IGAC 10-2025", "limit": 5})
            
            if r.status_code == 200:
                data = r.json()
                items = data.get("results", [])
                
                for item in items:
                    if "Base Catastral Pública IGAC 10-2025" in item.get("title", ""):
                        item_url = item.get("url", "")
                        if item_url and "/maps/" in item_url:
                            fs_url = item_url.replace("/maps/", "/rest/services/") + "/FeatureServer/7/query"
                            
                            # Reintentar con esta URL
                            try:
                                params = {
                                    "f": "json",
                                    "where": f"codigo_municipio = '{target_codigo}'" if target_codigo else "1=1",
                                    "outFields": "*",
                                    "returnGeometry": "true",
                                    "resultRecordCount": min(limit, 20),
                                    "outSR": 4326
                                }
                                
                                r2 = await client.get(fs_url, params=params)
                                if r2.status_code == 200:
                                    data2 = r2.json()
                                    features = data2.get("features", [])
                                    
                                    for feat in features:
                                        attrs = feat.get("attributes", {})
                                        geom = feat.get("geometry", {})
                                        
                                        result = {
                                            "title": f"Predio catastral (Hub): {attrs.get('CODIGO', 'N/A')}",
                                            "snippet": f"{attrs.get('CODIGO', 'N/A')} | Área: {attrs.get('Shape__Area', 0):,.0f} m²",
                                            "url": f"{IGAC_HUB_URL}{item_url}",
                                            "source_name": "IGAC - Hub ArcGIS",
                                            "source_url": "https://www.datos.gov.co",
                                            "categoria": "catastral",
                                            "tipo": "api_directa",
                                            "attributes": attrs,
                                            "geometry": geom,
                                            "divipola": divipola
                                        }
                                        results.append(result)
                                
                                if results:
                                    return results
                                    
                            except Exception as e:
                                logger.warning(f"Hub FeatureServer query failed: {e}")
                                continue
                                
    except Exception as e:
        logger.warning(f"ArcGIS Hub search failed: {e}")
    
    # Estrategia 3: Consultar estadísticas municipales (siempre funciona)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20) as client:
            table_url = "https://services2.arcgis.com/RVvWzU3lgJISqdke/arcgis/rest/services/_Base_2025__/FeatureServer/0/query"
            
            where_parts = []
            if divipola:
                where_parts.append(f"DIVIPOLA = '{divipola}'")
            elif municipio:
                where_parts.append(f"NOMBRE_MUNICIPIO = '{municipio}'")
            
            where = " AND ".join(where_parts) if where_parts else "1=1"
            
            params = {
                "f": "json",
                "where": where,
                "outFields": "*",
                "returnGeometry": "false",
                "resultRecordCount": min(limit, 10),
            }
            
            r = await client.get(table_url, params=params)
            if r.status_code == 200:
                data = r.json()
                features = data.get("features", [])
                
                for feat in features:
                    attrs = feat.get("attributes", {})
                    
                    title = f"Estadísticas catastrales - {attrs.get('NOMBRE_MUNICIPIO', 'N/A')}"
                    
                    snippet_parts = []
                    if attrs.get("DIVIPOLA"):
                        snippet_parts.append(f"DIVIPOLA: {attrs.get('DIVIPOLA')}")
                    if attrs.get("NOMBRE_MUNICIPIO"):
                        snippet_parts.append(f"Municipio: {attrs.get('NOMBRE_MUNICIPIO')}")
                    if attrs.get("NOMBRE_DEPARTAMENTO"):
                        snippet_parts.append(f"Departamento: {attrs.get('NOMBRE_DEPARTAMENTO')}")
                    if attrs.get("GESTOR"):
                        snippet_parts.append(f"Gestor: {attrs.get('GESTOR')}")
                    if attrs.get("ÁREA_GEOGRÁFICA_URBANA__HA_") is not None:
                        area_urb = attrs.get("ÁREA_GEOGRÁFICA_URBANA__HA_")
                        snippet_parts.append(f"Área urbana: {area_urb:,.1f} ha")
                    if attrs.get("ÁREA_GEOGRÁFICA_RURAL__HA_") is not None:
                        area_rural = attrs.get("ÁREA_GEOGRÁFICA_RURAL__HA_")
                        snippet_parts.append(f"Área rural: {area_rural:,.1f} ha")
                    
                    snippet = " | ".join(snippet_parts)
                    
                    result = {
                        "title": title,
                        "snippet": snippet,
                        "url": "https://www.datos.gov.co/dataset/Base-Catastral-P-blica-IGAC-10-2025/dpbj-tyu6",
                        "source_name": "IGAC - Estadísticas Catastrales",
                        "source_url": "https://www.datos.gov.co",
                        "categoria": "catastral",
                        "tipo": "api_directa",
                        "attributes": attrs
                    }
                    results.append(result)
                    
    except Exception as e:
        logger.warning(f"Municipal statistics query failed: {e}")
    
    return results


async def search_igac_datasets(query: str, categoria: str = "catastral", limit: int = 5) -> list[dict]:
    """Search IGAC datasets con manejo de errores."""
    results = []
    
    # Intentar con ArcGIS Hub API
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            search_url = f"{IGAC_HUB_URL}/api/search/v1"
            r = await client.get(search_url, params={"q": query, "limit": limit})
            
            if r.status_code == 200:
                data = r.json()
                items = data.get("results", [])
                
                for item in items[:limit]:
                    title = item.get("title", "")
                    description = item.get("description", "")
                    item_url = item.get("url", "")
                    
                    snippet = description[:200] if description else f"Dataset: {title}"
                    
                    result = {
                        "title": title,
                        "snippet": snippet,
                        "url": f"{IGAC_HUB_URL}{item_url}" if item_url else "",
                        "source_name": "IGAC - Datos Abiertos",
                        "source_url": "https://www.datos.gov.co",
                        "categoria": categoria,
                        "tipo": "api_directa"
                    }
                    results.append(result)
                    
    except Exception as e:
        logger.warning(f"ArcGIS Hub search failed: {e}")
    
    return results


# ── Funciones de compatibilidad ───────────────────────────────────────────────

def listar_servidores(categoria: str | None = None) -> list[dict]:
    """Alias para compatibilidad con wfs_colombia."""
    return []


async def wfs_get_capabilities(url: str) -> dict:
    """Alias para compatibilidad - retorna error indicando que no es un servidor WFS."""
    return {"error": "Este no es un servidor WFS. Use query_igac_catastro para datos catastrales IGAC."}


async def wfs_get_features(url: str, type_name: str, bbox: list[float] | None = None,
                           max_features: int = 100, output_format: str = "application/json") -> dict:
    """Alias para compatibilidad - retorna error indicando que no es un servidor WFS."""
    return {"error": "Este no es un servidor WFS. Use query_igac_catastro para datos catastrales IGAC."}


# ── Función de búsqueda principal ─────────────────────────────────────────────

async def search_all_apis(message: str) -> list[dict]:
    """Busca en todas las APIs oficiales segun el mensaje, incluyendo IGAC."""
    m = message.lower()
    results: list[dict] = []
    
    # Determinar categoria
    categoria = "general"
    if any(w in m for w in ("catastr", "matricula", "predio", "igac", "avaluo")):
        categoria = "catastral"
    elif any(w in m for w in ("ambient", "ideam", "anla", "clima", "licencia")):
        categoria = "ambiental"
    elif any(w in m for w in ("productiv", "agricol", "contrat", "secop")):
        categoria = "productiva"
    elif any(w in m for w in ("salud", "educacion", "poblacion")):
        categoria = "social"
    
    # Buscar en IGAC
    if categoria == "catastral":
        igac_results = await query_igac_catastro(limit=3)
        results.extend(igac_results)
    
    # Buscar en ArcGIS Hub
    hub_results = await search_igac_datasets(message, categoria, limit=2)
    results.extend(hub_results)
    
    return results


# ── Lista de APIs disponibles ─────────────────────────────────────────────────

async def listar_apis_disponibles() -> list[dict]:
    """Lista las APIs configuradas incluyendo IGAC."""
    return [
        {
            "nombre": "IGAC - Base Catastral Nacional",
            "url": "https://www.datos.gov.co/dataset/Base-Catastral-P-blica-IGAC-10-2025/dpbj-tyu6",
            "tipo": "arcgis_featureserver",
            "docs": "https://services2.arcgis.com/RVvWzU3lgJISqdke/arcgis/rest/services/Base_Catastral_Publica_IGAC_10_2025/FeatureServer"
        },
        {
            "nombre": "IGAC - Estadísticas Catastrales",
            "url": "https://www.datos.gov.co/dataset/Base-Catastral-P-blica-IGAC-10-2025/dpbj-tyu6",
            "tipo": "arcgis_table",
            "docs": "https://services2.arcgis.com/RVvWzU3lgJISqdke/arcgis/rest/services/_Base_2025__/FeatureServer/0"
        },
        {
            "nombre": "IGAC - Datos Abiertos (Hub)",
            "url": "https://datos-abiertos-igac-igac-oit.hub.arcgis.com",
            "tipo": "arcgis_hub",
            "docs": "https://datos-abiertos-igac-igac-oit.hub.arcgis.com"
        }
    ]