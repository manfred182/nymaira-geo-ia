"""Servicios WFS/WMS de entidades geograficas colombianas.

Catalogo de servidores OGC oficiales: IGAC, ICDE, IDEAM, Catastro Bogota,
IDECA, SGC, UPRA, DANE, ANT, MinAmbiente, etc.
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Catalogo de servidores OGC colombianos ──────────────────────

SERVIDORES_WFS: list[dict[str, Any]] = [
    {
        "id": "humboldt",
        "nombre": "Instituto Alexander von Humboldt",
        "url_wfs": "https://geoservicios.humboldt.org.co/geoserver/ows",
        "url_wms": "https://geoservicios.humboldt.org.co/geoserver/wms",
        "categoria": "ambiental",
        "descripcion": "Biodiversidad, ecosistemas, páramos, humedales, cobertura del suelo",
        "capas_conocidas": ["humboldt:biodiversidad", "humboldt:ecosistemas", "humboldt:paramos"],
    },
    {
        "id": "idesc_cali",
        "nombre": "IDESC - Santiago de Cali",
        "url_wfs": "https://ws-idesc.cali.gov.co/geoserver/wfs",
        "url_wms": "https://ws-idesc.cali.gov.co/geoserver/wms",
        "categoria": "catastral",
        "descripcion": "Catastro urbano de Cali, cultura, DAGMA, movilidad, salud",
        "capas_conocidas": ["idesc:catastro", "idesc:cultura", "idesc:dagma"],
    },
    {
        "id": "igac",
        "nombre": "IGAC - Instituto Geográfico Agustín Codazzi",
        "url_wfs": "https://geoportal.igac.gov.co/geoserver/wfs",
        "url_wms": "https://geoportal.igac.gov.co/geoserver/wms",
        "categoria": "catastral",
        "descripcion": "Cartografía básica, catastro, límites municipales/departamentales",
    },
    {
        "id": "ideam",
        "nombre": "IDEAM - Instituto de Hidrología, Meteorología y Estudios Ambientales",
        "url_wfs": "https://www.ideam.gov.co/geoserver/wfs",
        "url_wms": "https://www.ideam.gov.co/geoserver/wms",
        "categoria": "ambiental",
        "descripcion": "Clima, hidrología, calidad del aire, bosques, ecosistemas",
    },
    {
        "id": "sgc",
        "nombre": "SGC - Servicio Geológico Colombiano",
        "url_wfs": "https://datos.sgc.gov.co/geoserver/wfs",
        "url_wms": "https://datos.sgc.gov.co/geoserver/wms",
        "categoria": "ambiental",
        "descripcion": "Geología, amenazas, recursos minerales, volcanes, sismicidad",
    },
    {
        "id": "upra",
        "nombre": "UPRA - Unidad de Planificación Rural Agropecuaria",
        "url_wfs": "https://upra.gov.co/geoserver/wfs",
        "url_wms": "https://upra.gov.co/geoserver/wms",
        "categoria": "productiva",
        "descripcion": "Frontera agrícola, aptitud de suelos, ordenamiento productivo",
    },
]

SERVIDORES_WMS_SIN_WFS: list[dict[str, Any]] = [
    {
        "id": "parques",
        "nombre": "Parques Nacionales Naturales",
        "url_wms": "https://gis.parquesnacionales.gov.co/geoserver/wms",
        "categoria": "ambiental",
        "descripcion": "Áreas protegidas, parques nacionales",
    },
    {
        "id": "invias",
        "nombre": "INVIAS - Vías Nacionales",
        "url_wms": "https://gis.invias.gov.co/geoserver/wms",
        "categoria": "infraestructura",
        "descripcion": "Red vial nacional, carreteras, puentes",
    },
    {
        "id": "anla",
        "nombre": "ANLA - Autoridad Nacional de Licencias Ambientales",
        "url_wfs": "https://geoportal.anla.gov.co/geoserver/wfs",
        "url_wms": "https://geoportal.anla.gov.co/geoserver/wms",
        "categoria": "ambiental",
        "descripcion": "Licencias ambientales, proyectos, áreas de influencia",
    },
]


def listar_servidores(categoria: str | None = None) -> list[dict]:
    """Lista servidores WFS/WMS, opcionalmente filtrados por categoria."""
    todos = SERVIDORES_WFS + SERVIDORES_WMS_SIN_WFS
    if categoria:
        return [s for s in todos if s.get("categoria") == categoria]
    return todos


def servidor_por_id(sid: str) -> dict | None:
    for s in SERVIDORES_WFS + SERVIDORES_WMS_SIN_WFS:
        if s["id"] == sid:
            return s
    return None


def servidores_por_categoria() -> dict[str, list[dict]]:
    """Agrupa por categoria."""
    from collections import defaultdict
    g = defaultdict(list)
    for s in SERVIDORES_WFS + SERVIDORES_WMS_SIN_WFS:
        g[s.get("categoria", "otras")].append(s)
    return dict(g)


# ── Cliente WFS ─────────────────────────────────────────────────

async def wfs_get_capabilities(url: str) -> dict[str, Any]:
    """Obtiene las capabilities de un servidor WFS, probando versiones 2.0.0 y 1.1.0."""
    from geoia.websearch.dns_cache import check_connectivity
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    if host and not check_connectivity(host, port=443, timeout=5):
        logger.debug(f"Saltando {host}: sin conectividad DNS/TCP")
    import httpx
    for version in ("2.0.0", "1.1.0"):
        params = {"service": "WFS", "request": "GetCapabilities", "version": version}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                result = _parse_wfs_capabilities(r.text)
                if result["capas"]:
                    return result
        except Exception:
            continue
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params={"service": "WFS", "request": "GetCapabilities", "version": "2.0.0"})
            r.raise_for_status()
            return _parse_wfs_capabilities(r.text)
    except Exception as e:
        return {"error": str(e), "servidor": url}


def _parse_wfs_capabilities(xml_text: str) -> dict:
    """Extrae lista de capas (FeatureTypes) del XML de capabilities."""
    import xml.etree.ElementTree as ET
    result = {"titulo": "", "capas": []}
    root = ET.fromstring(xml_text)
    ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""

    # Titulo
    for ns_ows in ("http://www.opengis.net/ows/1.1", "http://www.opengis.net/ows"):
        title_els = root.findall(f".//{{{ns_ows}}}Title")
        if title_els:
            result["titulo"] = title_els[0].text or ""

    # FeatureTypes
    ns_wfs = ns if ns else "http://www.opengis.net/wfs/2.0"
    for ft in root.findall(f".//{{{ns_wfs}}}FeatureType"):
        name_el = ft.find(f"{{{ns_wfs}}}Name")
        if name_el is None:
            alt_ns = "http://www.opengis.net/wfs" if ns_wfs == "http://www.opengis.net/wfs/2.0" else "http://www.opengis.net/wfs/2.0"
            name_el = ft.find(f"{{{alt_ns}}}Name")
        title_el = ft.find(f"{{{ns_wfs}}}Title")
        if title_el is None:
            alt_ns = "http://www.opengis.net/wfs" if ns_wfs == "http://www.opengis.net/wfs/2.0" else "http://www.opengis.net/wfs/2.0"
            title_el = ft.find(f"{{{alt_ns}}}Title")
        if name_el is not None:
            result["capas"].append({
                "name": name_el.text if name_el.text else "",
                "title": title_el.text if title_el is not None and title_el.text else "",
            })

    return result


async def wfs_get_features(url: str, type_name: str, bbox: list[float] | None = None,
                           max_features: int = 100, output_format: str = "application/json") -> dict:
    """Consulta features de un WFS, opcionalmente por BBOX."""
    import httpx
    params = {
        "service": "WFS",
        "request": "GetFeature",
        "version": "2.0.0",
        "typeNames": type_name,
        "outputFormat": output_format,
        "count": max_features,
    }
    if bbox and len(bbox) == 4:
        params["bbox"] = ",".join(str(b) for b in bbox)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            return {
                "type": "FeatureCollection",
                "features": data.get("features", data.get("FeatureCollection", {}).get("features", [])),
                "count": len(data.get("features", data.get("FeatureCollection", {}).get("features", []))),
                "servidor": url,
                "type_name": type_name,
            }
    except Exception as e:
        return {"error": str(e), "servidor": url, "type_name": type_name}


# ── Cliente WMS ─────────────────────────────────────────────────

async def wms_get_capabilities(url: str) -> dict[str, Any]:
    """Obtiene capabilities de un servidor WMS."""
    import httpx
    params = {"service": "WMS", "request": "GetCapabilities", "version": "1.3.0"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return _parse_wms_capabilities(r.text)
    except Exception as e:
        return {"error": str(e)}


def _parse_wms_capabilities(xml_text: str) -> dict:
    """Extrae capas del XML de capabilities WMS."""
    import xml.etree.ElementTree as ET
    ns = {
        "wms": "http://www.opengis.net/wms",
        "wms13": "http://www.opengis.net/wms",
    }
    result = {"titulo": "", "capas": []}
    root = ET.fromstring(xml_text)

    service = root.find("{http://www.opengis.net/wms}Service")
    if service is None:
        service = root.find("Service")
    if service is not None:
        title_el = service.find("Title")
        if title_el is not None:
            result["titulo"] = title_el.text or ""

    # Extraer capas jerarquicas
    def extract_layers(parent, path=""):
        for layer in parent.findall("{http://www.opengis.net/wms}Layer"):
            name_el = layer.find("{http://www.opengis.net/wms}Name")
            title_el = layer.find("{http://www.opengis.net/wms}Title")
            name = name_el.text if name_el is not None else ""
            title = title_el.text if title_el is not None else ""
            if name:
                result["capas"].append({"name": name, "title": title, "path": path})
            # Hijos recursivos
            extract_layers(layer, path + "/" + (name or title))

    capability = root.find("{http://www.opengis.net/wms}Capability")
    if capability is not None:
        extract_layers(capability)

    return result


async def wms_get_map(url: str, layers: str, bbox: list[float],
                      width: int = 800, height: int = 600,
                      srs: str = "EPSG:4326", img_format: str = "image/png") -> bytes | None:
    """Obtiene una imagen de mapa de un WMS."""
    import httpx
    params = {
        "service": "WMS",
        "request": "GetMap",
        "version": "1.3.0",
        "layers": layers,
        "bbox": ",".join(str(b) for b in bbox),
        "width": width,
        "height": height,
        "srs": srs,
        "format": img_format,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.content
    except Exception as e:
        logger.warning(f"Error WMS GetMap: {e}")
        return None
