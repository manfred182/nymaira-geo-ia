from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Any
import json
import tempfile

from geoia.geo.processing import (
    qgis_available, qgis_algorithms,
    buffer, clip, dissolve, centroids, convex_hull,
    overlay_intersection, union, difference, symmetrical_difference,
    reproject, fix_geometries,
    simplify_geometries, ogr2ogr_convert,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ProcessingInput(BaseModel):
    geojson: dict[str, Any]
    params: dict[str, Any] = {}


class OverlayInput(BaseModel):
    input_geojson: dict[str, Any]
    overlay_geojson: dict[str, Any]


@router.get("/processing/status")
async def processing_status():
    return {
        "qgis_available": qgis_available(),
    }


@router.get("/processing/algorithms")
async def list_algorithms():
    algs = qgis_algorithms()
    return {"count": len(algs), "algorithms": algs[:50]}


@router.post("/processing/buffer")
async def api_buffer(data: ProcessingInput):
    distance = data.params.get("distance", 10)
    dissolve = data.params.get("dissolve", False)
    result = buffer(data.geojson, distance, dissolve)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/clip")
async def api_clip(data: OverlayInput):
    result = clip(data.input_geojson, data.overlay_geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/intersection")
async def api_intersection(data: OverlayInput):
    result = overlay_intersection(data.input_geojson, data.overlay_geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/union")
async def api_union(data: OverlayInput):
    result = union(data.input_geojson, data.overlay_geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/difference")
async def api_difference(data: OverlayInput):
    result = difference(data.input_geojson, data.overlay_geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/symmetrical-difference")
async def api_symmetrical_difference(data: OverlayInput):
    result = symmetrical_difference(data.input_geojson, data.overlay_geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/dissolve")
async def api_dissolve(data: ProcessingInput):
    field = data.params.get("field")
    result = dissolve(data.geojson, field)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/centroids")
async def api_centroids(data: ProcessingInput):
    result = centroids(data.geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/convex-hull")
async def api_convex_hull(data: ProcessingInput):
    result = convex_hull(data.geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/reproject")
async def api_reproject(data: ProcessingInput):
    crs = data.params.get("crs", "EPSG:4326")
    result = reproject(data.geojson, crs)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/fix-geometries")
async def api_fix_geometries(data: ProcessingInput):
    result = fix_geometries(data.geojson)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/simplify")
async def api_simplify(data: ProcessingInput):
    tolerance = data.params.get("tolerance", 1.0)
    result = simplify_geometries(data.geojson, tolerance)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/processing/convert")
async def api_convert(file: UploadFile = File(...), target_format: str = Form("GeoJSON")):
    ext_map = {"GeoJSON": ".geojson", "GPKG": ".gpkg", "ESRI Shapefile": ".shp", "GML": ".gml"}
    ext = ext_map.get(target_format, ".geojson")

    in_path = tempfile.mktemp(suffix=".tmp")
    out_path = tempfile.mktemp(suffix=ext)

    try:
        content = await file.read()
        with open(in_path, "wb") as f:
            f.write(content)

        result = ogr2ogr_convert(in_path, out_path, format=target_format)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f) if target_format == "GeoJSON" else {"path": out_path}

        return {"output": data, "format": target_format}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
