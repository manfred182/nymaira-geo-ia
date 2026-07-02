from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

router = APIRouter()

_classifier = None
def get_classifier():
    global _classifier
    if _classifier is None:
        from geoia.geo.classifier import GeoClassifier
        _classifier = GeoClassifier()
    return _classifier


class ClassifyResponse(BaseModel):
    class_name: str
    confidence: float


class VectorUploadResponse(BaseModel):
    filename: str
    type: str
    count: int
    crs: str | None = None
    bounds: list[float] | None = None
    columnas: list[str] = []
    geojson: dict | None = None
    error: str | None = None


class RasterInfoResponse(BaseModel):
    filename: str
    type: str
    meta: dict | None = None
    error: str | None = None


class WfsServidoresResponse(BaseModel):
    servidores: list[dict]


class WfsCapabilitiesResponse(BaseModel):
    servidor: str
    titulo: str
    capas: list[dict]
    error: str | None = None


class WfsQueryResponse(BaseModel):
    type: str
    features: list[dict]
    count: int
    error: str | None = None
    type_name: str | None = None


class WmsCapabilitiesResponse(BaseModel):
    servidor: str
    titulo: str
    capas: list[dict]
    error: str | None = None


# ── Clasificacion de imagenes ───────────────────────────────────

@router.post("/classify", response_model=ClassifyResponse)
async def classify(file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = get_classifier().classify_image(content)
        return ClassifyResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/segment")
async def segment(file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = get_classifier().segment_image(content)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Carga de archivos espaciales ────────────────────────────────

@router.post("/upload-vector", response_model=VectorUploadResponse)
async def upload_vector(file: UploadFile = File(...)):
    try:
        content = await file.read()
        from geoia.geo.parsers import info_archivo_espacial
        result = info_archivo_espacial(content, file.filename or "archivo")
        return VectorUploadResponse(
            filename=result.get("filename", file.filename or "archivo"),
            type=result.get("type", "desconocido"),
            count=result.get("count", 0),
            crs=result.get("crs"),
            bounds=result.get("bounds"),
            columnas=result.get("columnas", []),
            geojson=result.get("geojson"),
            error=result.get("error"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-raster")
async def upload_raster(file: UploadFile = File(...)):
    try:
        content = await file.read()
        from geoia.geo.parsers import parse_raster
        meta = parse_raster(content, file.filename or "archivo")
        return RasterInfoResponse(
            filename=file.filename or "archivo",
            type="raster",
            meta=meta if "error" not in meta else None,
            error=meta.get("error"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Servicios WFS/WMS Colombia ──────────────────────────────────

@router.get("/wfs/servidores", response_model=WfsServidoresResponse)
async def listar_wfs(categoria: str | None = None):
    from geoia.websearch.wfs_colombia import listar_servidores
    return WfsServidoresResponse(servidores=listar_servidores(categoria))


@router.post("/wfs/capabilities", response_model=WfsCapabilitiesResponse)
async def wfs_capabilities(url: str = Query(...)):
    from geoia.websearch.wfs_colombia import wfs_get_capabilities
    result = await wfs_get_capabilities(url)
    if "error" in result:
        return WfsCapabilitiesResponse(servidor=url, titulo="", capas=[], error=result["error"])
    return WfsCapabilitiesResponse(
        servidor=url,
        titulo=result.get("titulo", ""),
        capas=result.get("capas", []),
    )


@router.post("/wfs/query", response_model=WfsQueryResponse)
async def wfs_query(url: str = Query(...), type_name: str = Query(...),
                    bbox: str | None = Query(None), max_features: int = Query(100)):
    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x) for x in bbox.split(",")]
            if len(bbox_list) != 4:
                bbox_list = None
        except Exception:
            pass
    from geoia.websearch.wfs_colombia import wfs_get_features
    result = await wfs_get_features(url, type_name, bbox=bbox_list, max_features=max_features)
    if "error" in result:
        return WfsQueryResponse(type="FeatureCollection", features=[], count=0,
                                error=result["error"], type_name=type_name)
    return WfsQueryResponse(
        type="FeatureCollection",
        features=result.get("features", []),
        count=result.get("count", 0),
        type_name=type_name,
    )


@router.post("/wms/capabilities", response_model=WmsCapabilitiesResponse)
async def wms_capabilities(url: str = Query(...)):
    from geoia.websearch.wfs_colombia import wms_get_capabilities
    result = await wms_get_capabilities(url)
    if "error" in result:
        return WmsCapabilitiesResponse(servidor=url, titulo="", capas=[], error=result["error"])
    return WmsCapabilitiesResponse(
        servidor=url,
        titulo=result.get("titulo", ""),
        capas=result.get("capas", []),
    )


@router.post("/wms/map")
async def wms_map(url: str = Query(...), layers: str = Query(...),
                  bbox: str = Query(""), width: int = Query(800), height: int = Query(600)):
    from fastapi.responses import Response
    if not bbox:
        raise HTTPException(status_code=400, detail="bbox requerido (minx,miny,maxx,maxy)")
    try:
        bbox_list = [float(x) for x in bbox.split(",")]
    except Exception:
        raise HTTPException(status_code=400, detail="bbox debe ser 4 numeros separados por coma")
    from geoia.websearch.wfs_colombia import wms_get_map
    img = await wms_get_map(url, layers, bbox_list, width=width, height=height)
    if img is None:
        raise HTTPException(status_code=502, detail="Error al obtener mapa del servidor WMS")
    return Response(content=img, media_type="image/png")


# ── Catalogo de fuentes colombianas ─────────────────────────────

@router.get("/colombia/capas-disponibles")
async def capas_disponibles(servidor_id: str | None = None):
    """Catalogo de capas geoespaciales colombianas."""
    from geoia.websearch.wfs_colombia import listar_servidores, servidor_por_id
    if servidor_id:
        s = servidor_por_id(servidor_id)
        if not s:
            raise HTTPException(status_code=404, detail=f"Servidor no encontrado: {servidor_id}")
        return {"servidores": [s]}
    # Agrupar por categoria
    servs = listar_servidores()
    from collections import defaultdict
    agrupado = defaultdict(list)
    for s in servs:
        agrupado[s.get("categoria", "otras")].append({
            "id": s["id"],
            "nombre": s["nombre"],
            "url_wfs": s.get("url_wfs", ""),
            "url_wms": s.get("url_wms", ""),
            "descripcion": s.get("descripcion", ""),
        })
    return dict(agrupado)


# ── Consulta espacial sobre datos cargados ──────────────────────

class SpatialQueryRequest(BaseModel):
    geojson: dict
    operation: str = "info"  # info, buffer, area, centroide
    buffer_distance: float = 0.0
    buffer_crs: str = "EPSG:4326"

class SpatialQueryResponse(BaseModel):
    operation: str
    result: dict
    error: str | None = None


@router.post("/spatial-query", response_model=SpatialQueryResponse)
async def spatial_query(req: SpatialQueryRequest):
    try:
        import geopandas as gpd
        from shapely.geometry import shape

        gdf = gpd.GeoDataFrame.from_features(req.geojson.get("features", []), crs="EPSG:4326")
        if gdf.empty:
            return SpatialQueryResponse(operation=req.operation, result={}, error="Sin geometrias")

        result = {}

        if req.operation == "info":
            result["count"] = len(gdf)
            result["crs"] = str(gdf.crs)
            if not gdf.empty:
                result["bounds"] = [round(float(b), 6) for b in gdf.total_bounds]
                result["area_km2"] = round(float(gdf.to_crs("EPSG:3857").area.sum()) / 1_000_000, 2)

        elif req.operation == "buffer" and req.buffer_distance > 0:
            buffered = gdf.to_crs("EPSG:3857").buffer(req.buffer_distance).to_crs("EPSG:4326")
            gdf_buf = gpd.GeoDataFrame(geometry=buffered, crs="EPSG:4326")
            result["geojson"] = json.loads(gdf_buf.to_json())
            result["count"] = len(gdf_buf)

        elif req.operation == "centroide":
            centroids = gdf.centroid
            result["centroides"] = [[round(float(p.x), 6), round(float(p.y), 6)] for p in centroids]

        elif req.operation == "area":
            area_m2 = float(gdf.to_crs("EPSG:3857").area.sum())
            result["area_m2"] = round(area_m2, 2)
            result["area_ha"] = round(area_m2 / 10_000, 2)
            result["area_km2"] = round(area_m2 / 1_000_000, 2)

        return SpatialQueryResponse(operation=req.operation, result=result)

    except Exception as e:
        return SpatialQueryResponse(operation=req.operation, result={}, error=str(e))


# ── Cruce de informacion espacial (overlay entre 2 capas) ───────

class SpatialOverlayRequest(BaseModel):
    layer_a: dict  # GeoJSON FeatureCollection
    layer_b: dict  # GeoJSON FeatureCollection
    operation: str = "intersection"  # intersection, union, difference, symmetric_difference
    layer_a_label: str = "Capa A"
    layer_b_label: str = "Capa B"

class SpatialOverlayResponse(BaseModel):
    operation: str
    result_geojson: dict | None = None
    count: int = 0
    summary: str = ""
    error: str | None = None


@router.post("/spatial-overlay", response_model=SpatialOverlayResponse)
async def spatial_overlay(req: SpatialOverlayRequest):
    """Cruza dos capas espaciales: interseccion, union, diferencia, diferencia simetrica."""
    try:
        import geopandas as gpd
        from shapely.ops import unary_union

        gdf_a = gpd.GeoDataFrame.from_features(req.layer_a.get("features", []), crs="EPSG:4326")
        gdf_b = gpd.GeoDataFrame.from_features(req.layer_b.get("features", []), crs="EPSG:4326")

        if gdf_a.empty or gdf_b.empty:
            return SpatialOverlayResponse(
                operation=req.operation, error="Una de las capas esta vacia"
            )

        # Reproject a 3857 for accurate operations, then back
        gdf_a_m = gdf_a.to_crs("EPSG:3857")
        gdf_b_m = gdf_b.to_crs("EPSG:3857")

        op = req.operation
        result_gdf = None

        if op == "intersection":
            result_gdf = gpd.overlay(gdf_a_m, gdf_b_m, how="intersection")
        elif op == "union":
            result_gdf = gpd.overlay(gdf_a_m, gdf_b_m, how="union")
        elif op == "difference":
            result_gdf = gpd.overlay(gdf_a_m, gdf_b_m, how="difference")
        elif op == "symmetric_difference":
            result_gdf = gpd.overlay(gdf_a_m, gdf_b_m, how="symmetric_difference")
        else:
            return SpatialOverlayResponse(operation=op, error=f"Operacion no soportada: {op}")

        if result_gdf is None or result_gdf.empty:
            return SpatialOverlayResponse(
                operation=op, count=0,
                summary=f"Las capas no tienen areas en comun para la operacion '{op}'",
                result_geojson={"type": "FeatureCollection", "features": []}
            )

        result_gdf = result_gdf.to_crs("EPSG:4326")
        area_m2 = float(result_gdf.to_crs("EPSG:3857").area.sum())

        geojson_out = json.loads(result_gdf.to_json())
        count = len(result_gdf)

        summary = (
            f"✅ **{op}** entre '{req.layer_a_label}' y '{req.layer_b_label}': "
            f"{count} geometrías resultantes, "
            f"{area_m2:,.0f} m² ({area_m2/10_000:,.1f} ha | {area_m2/1_000_000:,.2f} km²)"
        )

        return SpatialOverlayResponse(
            operation=op,
            result_geojson=geojson_out,
            count=count,
            summary=summary,
        )

    except Exception as e:
        return SpatialOverlayResponse(operation=req.operation, error=str(e))
