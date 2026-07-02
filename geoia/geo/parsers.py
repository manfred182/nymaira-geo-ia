"""Parsers geoespaciales para formatos vectoriales y raster.

Soporta: GeoJSON, Shapefile (zip), KML, KMZ, FileGDB (zip),
GeoPackage, GeoTIFF, CSV/Excel con coordenadas.
"""

from __future__ import annotations
import io, json, logging, os, tempfile, zipfile
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Helpers ─────────────────────────────────────────────────────


def _es_zip(content: bytes) -> bool:
    return content[:4] == b"PK\x03\x04"


def _safe_gdf(gdf) -> dict[str, Any]:
    """Convierte GeoDataFrame a dict serializable, limita tamano."""
    if gdf is None or gdf.empty:
        return {"type": "FeatureCollection", "features": [], "crs": "EPSG:4326", "count": 0}

    crs = str(gdf.crs) if gdf.crs else "EPSG:4326"
    # Reproject a WGS84 si es necesario
    if gdf.crs and str(gdf.crs).upper() not in ("EPSG:4326", "OGC:CRS84", "WGS 84", ""):
        try:
            gdf = gdf.to_crs("EPSG:4326")
        except Exception:
            pass

    # Limitar features
    n = len(gdf)
    if n > 500:
        logger.warning(f"Demasiadas features ({n}), truncando a 500")
        gdf = gdf.head(500)

    try:
        geojson = json.loads(gdf.to_json())
    except Exception as e:
        return {"type": "FeatureCollection", "features": [], "crs": crs, "count": 0, "error": str(e)}

    # Resumir columnas
    cols = [c for c in gdf.columns if c != "geometry"]

    return {
        "type": "FeatureCollection",
        "features": geojson.get("features", []),
        "crs": crs,
        "count": n,
        "columnas": cols[:20],
        "bounds": _bounds(gdf),
    }


def _bounds(gdf) -> list[float] | None:
    try:
        b = gdf.total_bounds
        return [round(float(b[0]), 6), round(float(b[1]), 6),
                round(float(b[2]), 6), round(float(b[3]), 6)]
    except Exception:
        return None


def _resumen_atributos(gdf) -> dict:
    """Genera resumen estadistico de columnas numericas."""
    res = {}
    for col in gdf.select_dtypes(include=[np.number]).columns[:10]:
        try:
            res[col] = {
                "min": round(float(gdf[col].min()), 2),
                "max": round(float(gdf[col].max()), 2),
                "mean": round(float(gdf[col].mean()), 2),
            }
        except Exception:
            pass
    return res


# ── Parser principal ────────────────────────────────────────────

def parse_vector(content: bytes, filename: str = "") -> dict[str, Any]:
    """Lee cualquier archivo vectorial y retorna GeoJSON + metadatos."""
    import geopandas as gpd

    ext = os.path.splitext(filename)[1].lower()
    name = os.path.splitext(os.path.basename(filename))[0]
    tmpdir: str | None = None

    try:
        # ── GeoJSON ──
        if ext == ".geojson" or ext == ".json":
            gdf = gpd.read_file(io.BytesIO(content), driver="GeoJSON")
            return _safe_gdf(gdf)

        # ── KML ──
        elif ext == ".kml":
            gdf = gpd.read_file(io.BytesIO(content), driver="KML")
            return _safe_gdf(gdf)

        # ── KMZ (zip con KML dentro) ──
        elif ext == ".kmz":
            tmpdir = tempfile.mkdtemp()
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                z.extractall(tmpdir)
                kml_files = list(Path(tmpdir).rglob("*.kml"))
                if not kml_files:
                    return {"error": "No se encontro archivo KML dentro del KMZ"}
                gdf = gpd.read_file(str(kml_files[0]), driver="KML")
            return _safe_gdf(gdf)

        # ── Shapefile (zip con .shp + .dbf + .prj + .shx) ──
        elif ext == ".zip" or ext in (".shp", ".dbf", ".prj", ".shx"):
            tmpdir = tempfile.mkdtemp()
            if _es_zip(content):
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    z.extractall(tmpdir)
            else:
                # Archivo individual, guardar en tmp
                out = Path(tmpdir) / filename
                out.write_bytes(content)
                # Si es .shp directamente
                if ext == ".shp":
                    pass  # geopandas lo lee
                else:
                    # Si es .dbf, .prj, .shx solo, no podemos leer
                    return {"error": f"Archivo {ext} debe estar acompanado de .shp. Sube un ZIP con todos los componentes del shapefile."}

            # Buscar .shp
            shp_files = list(Path(tmpdir).rglob("*.shp"))
            if not shp_files:
                return {"error": "No se encontro archivo .shp en el ZIP"}
            gdf = gpd.read_file(str(shp_files[0]))
            return _safe_gdf(gdf)

        # ── File GeoDataBase (zip con .gdb dentro) ──
        elif ext == ".gdb" or ".gdb" in filename:
            tmpdir = tempfile.mkdtemp()
            if _es_zip(content):
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    z.extractall(tmpdir)
                # Encontrar la GDB
                gdb_dirs = list(Path(tmpdir).rglob("*.gdb"))
                if not gdb_dirs:
                    # Buscar carpeta que tiene .gdbtable
                    for p in Path(tmpdir).rglob("*.gdbtable"):
                        gdb_dirs = [p.parent]
                        break
                if not gdb_dirs:
                    return {"error": "No se encontro File GeoDataBase en el ZIP"}
                gdf = gpd.read_file(str(gdb_dirs[0]), driver="OpenFileGDB")
                return _safe_gdf(gdf)
            else:
                return {"error": "Para FileGDB, sube un ZIP con la carpeta .gdb dentro"}

        # ── GeoPackage ──
        elif ext == ".gpkg":
            gdf = gpd.read_file(io.BytesIO(content), driver="GPKG")
            return _safe_gdf(gdf)

        # ── CSV o Excel con coordenadas ──
        elif ext == ".csv":
            import pandas as pd
            df = pd.read_csv(io.BytesIO(content))
            return _parse_tabular_coords(df, filename)

        elif ext in (".xlsx", ".xls"):
            import pandas as pd
            df = pd.read_excel(io.BytesIO(content))
            return _parse_tabular_coords(df, filename)

        else:
            # Intentar deteccion automatica
            try:
                gdf = gpd.read_file(io.BytesIO(content))
                return _safe_gdf(gdf)
            except Exception:
                return {"error": f"Formato no soportado: {ext}"}

    except Exception as e:
        logger.warning(f"Error parseando {filename}: {e}")
        return {"error": str(e), "filename": filename}

    finally:
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_tabular_coords(df, filename: str) -> dict[str, Any]:
    """Intenta convertir CSV/Excel con columnas X,Y o lat,lon a GeoJSON."""
    import geopandas as gpd
    from shapely.geometry import Point

    cols_lower = [c.lower().strip() for c in df.columns]
    x_col = y_col = None

    # Buscar columnas de coordenadas
    for i, c in enumerate(cols_lower):
        if c in ("x", "longitud", "long", "lon", "coord_x", "coordenada_x", "este", "easting"):
            x_col = df.columns[i]
        if c in ("y", "latitud", "lat", "coord_y", "coordenada_y", "norte", "northing"):
            y_col = df.columns[i]

    if x_col and y_col:
        try:
            df = df.dropna(subset=[x_col, y_col])
            geometry = [Point(float(row[x_col]), float(row[y_col])) for _, row in df.iterrows()]
            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
            return _safe_gdf(gdf)
        except Exception as e:
            return {"error": f"No se pudieron interpretar coordenadas: {e}"}

    return {"error": "CSV/Excel sin columnas de coordenadas detectables (X,Y o lat,lon)"}


# ── Raster (GeoTIFF) ────────────────────────────────────────────

def parse_raster(content: bytes, filename: str = "") -> dict[str, Any]:
    """Lee GeoTIFF y retorna metadatos."""
    import rasterio
    from rasterio.io import MemoryFile

    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".tif", ".tiff", ".geotiff"):
        return {"error": f"Formato raster no soportado: {ext}"}

    try:
        with MemoryFile(content) as mem:
            with mem.open() as src:
                meta = {
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,
                    "crs": str(src.crs) if src.crs else None,
                    "bounds": [round(float(b), 6) for b in src.bounds],
                    "dtype": str(src.dtypes[0]) if src.dtypes else None,
                    "nodata": src.nodata,
                    "res": [round(float(r), 6) for r in src.res],
                }
                # Sample estadistico
                band1 = src.read(1)
                meta["stats"] = {
                    "min": round(float(np.nanmin(band1)), 2),
                    "max": round(float(np.nanmax(band1)), 2),
                    "mean": round(float(np.nanmean(band1)), 2),
                    "std": round(float(np.nanstd(band1)), 2),
                }
                return meta
    except Exception as e:
        return {"error": str(e)}


# ── Metadatos de cualquier archivo espacial ─────────────────────

def info_archivo_espacial(content: bytes, filename: str) -> dict:
    """Detecta el tipo de archivo y retorna metadatos basicos."""
    ext = os.path.splitext(filename)[1].lower()
    result = {"filename": filename, "size_kb": len(content) // 1024, "ext": ext}

    if ext in (".geojson", ".json", ".kml", ".kmz", ".zip", ".shp", ".dbf", ".prj", ".shx", ".gdb", ".gpkg", ".csv", ".xlsx", ".xls"):
        parsed = parse_vector(content, filename)
        if "error" in parsed:
            result["error"] = parsed["error"]
        else:
            result["type"] = "vector"
            result["count"] = parsed.get("count", 0)
            result["crs"] = parsed.get("crs")
            result["bounds"] = parsed.get("bounds")
            result["columnas"] = parsed.get("columnas", [])
            # Incluir GeoJSON solo si es pequeno
            n_bytes = len(json.dumps(parsed))
            if n_bytes < 500_000:
                result["geojson"] = parsed
            else:
                result["geojson"] = {"type": "FeatureCollection", "features": parsed.get("features", [])[:100], "truncado": True}
    elif ext in (".tif", ".tiff", ".geotiff"):
        meta = parse_raster(content, filename)
        if "error" in meta:
            result["error"] = meta["error"]
        else:
            result["type"] = "raster"
            result["meta"] = meta
    else:
        result["error"] = f"Formato no reconocido: {ext}"

    return result
