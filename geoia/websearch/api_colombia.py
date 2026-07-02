"""Conexion directa a APIs oficiales del gobierno colombiano.

APIs soportadas:
  - datos.gov.co (Socrata SODA) — miles de datasets abiertos
  - ICDE / IGAC (ArcGIS REST) — datos geoespaciales
  - DANE API — estadisticas nacionales
  - BanRep API — indicadores economicos
  - API-Colombia — informacion general del pais
  - Catastro Bogota (CKAN) — datos abiertos de Bogota
"""

from __future__ import annotations
import json, logging
from urllib.parse import quote_plus
import httpx

logger = logging.getLogger(__name__)

# ── Configuracion de endpoints ──────────────────────────────────

ENDPOINTS = {
    "datos_gov_co": {
        "nombre": "Datos Abiertos Colombia",
        "url": "https://www.datos.gov.co",
        "api_base": "https://www.datos.gov.co/resource",
        "tipo": "socrata",
        "docs": "https://dev.socrata.com/docs/queries/",
    },
    "icde_igac": {
        "nombre": "ICDE - Datos Geoespaciales",
        "url": "https://datos.icde.gov.co",
        "api_base": "https://datos-abiertos-igac-igac-oit.hub.arcgis.com",
        "tipo": "arcgis",
        "docs": "https://developers.arcgis.com/rest/",
    },
    "dane": {
        "nombre": "DANE - Estadisticas",
        "url": "https://www.dane.gov.co",
        "api_base": "https://api.dane.gov.co",
        "tipo": "rest",
        "docs": "https://www.dane.gov.co/",
    },
    "banrep": {
        "nombre": "Banco de la Republica",
        "url": "https://www.banrep.gov.co",
        "api_base": "https://www.banrep.gov.co/estadisticas",
        "tipo": "rest",
        "docs": "https://www.banrep.gov.co/es/estadisticas",
    },
    "api_colombia": {
        "nombre": "API Colombia",
        "url": "https://api-colombia.com",
        "api_base": "https://api-colombia.com/api/v1",
        "tipo": "rest",
        "docs": "https://docs.api-colombia.com/",
    },
    "catastro_bogota": {
        "nombre": "Datos Abiertos Bogota",
        "url": "https://datosabiertos.bogota.gov.co",
        "api_base": "https://datosabiertos.bogota.gov.co/api/3/action",
        "tipo": "ckan",
        "docs": "https://docs.ckan.org/",
    },
    "sgc": {
        "nombre": "Servicio Geologico Colombiano",
        "url": "https://www.sgc.gov.co",
        "api_base": "https://datos.sgc.gov.co",
        "tipo": "arcgis",
        "docs": "https://datos.sgc.gov.co/",
    },
}

# ── Datasets importantes de datos.gov.co (SODA) ────────────────

DATASETS_SODA = {
    "catastral": [
        ("Base Catastral Nacional", "https://www.datos.gov.co/resource/9aea0ac639824f2ebb24115182fec59b.json"),
        ("Predios Catastrales IGAC", "https://www.datos.gov.co/resource/5fe8e741db1a4ffe906f1b80635f4062.json"),
        ("Avaluos Catastrales", "https://www.datos.gov.co/resource/72nf-y4v3.json"),
        # IGAC Base Catastral Nacional 10-2025 (ArcGIS FeatureServer - no es SODA)
        ("Base Catastral Nacional IGAC 10-2025", "https://services2.arcgis.com/RVvWzU3lgJISqdke/arcgis/rest/services/Base_Catastral_Publica_IGAC_10_2025/FeatureServer"),
        # IGAC Estadísticas Catastrales (_Base_2025__)
        ("Estadísticas Catastrales IGAC", "https://services2.arcgis.com/RVvWzU3lgJISqdke/arcgis/rest/services/_Base_2025__/FeatureServer/0"),
    ],
    "ambiental": [
        ("Calidad del Aire", "https://www.datos.gov.co/resource/ts8a-9hrk.json"),
        ("Licencias Ambientales", "https://www.datos.gov.co/resource/f7bh-2smd.json"),
    ],
    "productiva": [
        ("SECOP II - Contratacion", "https://www.datos.gov.co/resource/p6dx-8zbt.json"),
        ("Registro Unico de Proponentes", "https://www.datos.gov.co/resource/8qtb-3c6s.json"),
    ],
    "social": [
        ("Afiliados Salud", "https://www.datos.gov.co/resource/s9s6-2m4f.json"),
        ("Matriculas Educacion", "https://www.datos.gov.co/resource/msmm-hs8i.json"),
    ],
    "general": [
        ("Presupuesto General Nacion", "https://www.datos.gov.co/resource/4hj5-4xri.json"),
        ("Indice de Precios al Consumidor", "https://www.datos.gov.co/resource/3adb-q2tv.json"),
    ],
}


async def query_soda(dataset_url: str, limit: int = 5, where: str = "") -> list[dict]:
    """Consulta un dataset del portal datos.gov.co via API SODA."""
    url = dataset_url.rstrip(".json") + ".json"
    params = {"$limit": limit, "$order": ":id"}
    if where:
        params["$where"] = where
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()[:limit]
    except Exception as e:
        logger.warning(f"Error consultando SODA {dataset_url}: {e}")
    return []


async def search_soda(query: str, categoria: str = "catastral", limit: int = 3) -> list[dict]:
    """Busca en datasets de datos.gov.co por palabra clave."""
    results: list[dict] = []
    datasets = DATASETS_SODA.get(categoria, DATASETS_SODA["general"])
    for nombre, dset_url in datasets:
        data = await query_soda(dset_url, limit=limit, where=f"lower({_get_search_field(dset_url)}) like '%{query.lower()}%'")
        if not data:
            data = await query_soda(dset_url, limit=limit)
        for row in data[:2]:
            results.append({
                "title": f"{nombre}: {_format_soda_row(row)}",
                "url": dset_url,
                "snippet": json.dumps(row, ensure_ascii=False)[:300],
                "source_name": f"datos.gov.co - {nombre}",
                "source_url": "https://www.datos.gov.co",
                "categoria": categoria,
                "tipo": "api_directa",
            })
    return results


def _get_search_field(url: str) -> str:
    """Intenta adivinar un campo de texto para filtrar."""
    return "nombre" if "nombre" in url else "departamento"


def _format_soda_row(row: dict) -> str:
    """Formatea una fila SODA como texto resumido."""
    parts = []
    for k in ("nombre", "departamento", "municipio", "ciudad", "descripcion", "direccion"):
        if k in row and row[k]:
            parts.append(str(row[k]))
            break
    if not parts:
        vals = [str(v) for v in list(row.values())[:3] if v]
        parts = vals
    return (parts[0][:100] if parts else "sin detalle")


async def query_arcgis_hub(hub_url: str, query: str, limit: int = 3) -> list[dict]:
    """Busca en un portal ArcGIS Hub por palabra clave."""
    search_url = f"{hub_url.rstrip('/')}/api/search/v1"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(search_url, params={"q": query, "limit": limit})
            if r.status_code == 200:
                data = r.json()
                results = []
                for item in data.get("results", [])[:limit]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("description", "")[:200],
                        "source_name": "ICDE / IGAC",
                        "source_url": hub_url,
                        "tipo": "api_directa",
                    })
                return results
    except Exception as e:
        logger.warning(f"Error ArcGIS Hub {hub_url}: {e}")
    return []


async def query_api_colombia(endpoint: str = "Department", limit: int = 5) -> list[dict]:
    """Consulta la API publica de Colombia."""
    try:
        url = f"{ENDPOINTS['api_colombia']['api_base']}/{endpoint}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data[:limit]
                return [data]
    except Exception as e:
        logger.warning(f"Error API-Colombia: {e}")
    return []


async def search_all_apis(message: str) -> list[dict]:
    """Busca en todas las APIs oficiales segun el mensaje."""
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

    # Buscar en datos.gov.co
    soda_results = await search_soda(message, categoria, limit=2)
    results.extend(soda_results)

    # Buscar en ICDE ArcGIS Hub
    icde_results = await query_arcgis_hub(ENDPOINTS["icde_igac"]["api_base"], message, limit=2)
    for r in icde_results:
        r["categoria"] = categoria
    results.extend(icde_results)

    # Buscar en IGAC Base Catastral Nacional (ArcGIS FeatureServer)
    if categoria == "catastral":
        from geoia.websearch.datos_gov_co import query_igac_catastro
        igac_results = await query_igac_catastro(limit=3)
        results.extend(igac_results)

    # Buscar en API-Colombia si es sobre geografia
    if any(w in m for w in ("departamento", "municipio", "region", "colombia")):
        api_co = await query_api_colombia("Department", limit=3)
        for item in api_co:
            results.append({
                "title": f"Departamento: {item.get('name', '')}",
                "url": f"https://api-colombia.com/api/v1/Department/{item.get('id', '')}",
                "snippet": f"Capital: {item.get('capital', '')} | Area: {item.get('area', '')} km2",
                "source_name": "API Colombia",
                "source_url": "https://api-colombia.com",
                "categoria": "general",
                "tipo": "api_directa",
            })

    return results


def listar_apis_disponibles() -> list[dict]:
    """Lista las APIs configuradas."""
    return [
        {"nombre": v["nombre"], "url": v["url"], "tipo": v["tipo"], "docs": v["docs"]}
        for v in ENDPOINTS.values()
    ]
