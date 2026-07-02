from __future__ import annotations
import logging, json, os, subprocess, tempfile, shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_QGIS_DIR: Path | None = None
_QGIS_PROCESS: str | None = None


def _find_qgis() -> tuple[Path, str]:
    global _QGIS_DIR, _QGIS_PROCESS
    if _QGIS_DIR and _QGIS_PROCESS:
        return _QGIS_DIR, _QGIS_PROCESS

    candidates = [
        Path("C:/Program Files/QGIS 3.44.11"),
        Path("C:/Program Files/QGIS 3.34.11"),
        Path("C:/Program Files/QGIS 3.28.15"),
        Path("C:/OSGeo4W"),
    ]
    for base in candidates:
        proc = base / "bin" / "qgis_process-qgis-ltr.bat"
        if proc.exists():
            _QGIS_DIR = base
            _QGIS_PROCESS = str(proc)
            logger.info(f"QGIS encontrado en {base}")
            return _QGIS_DIR, _QGIS_PROCESS

    _QGIS_DIR = Path("")
    _QGIS_PROCESS = ""
    return _QGIS_DIR, _QGIS_PROCESS


def _qgis_env() -> dict[str, str]:
    env = os.environ.copy()
    qdir, _ = _find_qgis()
    if qdir:
        bin_dir = qdir / "bin"
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["QGIS_PREFIX_PATH"] = str(qdir)
    return env


def qgis_available() -> bool:
    _, proc = _find_qgis()
    return bool(proc)


def qgis_algorithms() -> list[dict]:
    if not qgis_available():
        return []
    try:
        r = subprocess.run(
            [_QGIS_PROCESS, "list"],
            capture_output=True, text=True, timeout=30, env=_qgis_env()
        )
        lines = r.stdout.split("\n")
        algs = []
        for line in lines:
            line = line.strip()
            if ":" in line and not line.startswith("[") and not line.startswith("Q") and line[0].islower():
                parts = line.split(":", 1)
                algs.append({"id": parts[0].strip(), "name": parts[1].strip()})
        return algs
    except Exception as e:
        logger.warning(f"Error listando algoritmos QGIS: {e}")
        return []


def qgis_run(algorithm: str, params: dict) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}
    try:
        cmd = [_QGIS_PROCESS, "run", algorithm, "--"]
        for k, v in params.items():
            if v is None or (isinstance(v, (list, dict)) and not v):
                continue
            if isinstance(v, bool):
                cmd.append(f"{k}={str(v).lower()}")
            elif isinstance(v, (int, float)):
                cmd.append(f"{k}={v}")
            else:
                cmd.append(f"{k}={v}")

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=_qgis_env())

        if r.returncode != 0:
            return {"error": r.stderr[:500]}

        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return {"stdout": r.stdout[:2000], "stderr": r.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout en algoritmo QGIS"}
    except Exception as e:
        return {"error": str(e)}


def _gdal_cmd(name: str) -> str | None:
    qdir, _ = _find_qgis()
    if not qdir:
        return None
    cmd = qdir / "bin" / f"{name}.exe"
    return str(cmd) if cmd.exists() else None


def ogr2ogr_convert(input_path: str, output_path: str | None = None,
                    format: str = "GeoJSON", layer: str | None = None,
                    where: str | None = None, s_srs: str | None = None,
                    t_srs: str | None = None, clip_srs: str | None = None,
                    clip_sql: str | None = None) -> dict:
    cmd_path = _gdal_cmd("ogr2ogr")
    if not cmd_path:
        return {"error": "ogr2ogr no disponible"}

    if not output_path:
        ext = ".geojson" if format == "GeoJSON" else ".gpkg"
        output_path = tempfile.mktemp(suffix=ext)

    cmd = [cmd_path, "-f", format, "-overwrite"]
    if s_srs:
        cmd += ["-s_srs", s_srs]
    if t_srs:
        cmd += ["-t_srs", t_srs]
    if where:
        cmd += ["-where", where]
    if layer:
        cmd += ["-nln", layer]
    if clip_srs:
        cmd += ["-clipsrc", clip_srs]
    if clip_sql:
        cmd += ["-clipsrcsql", clip_sql]

    cmd += [output_path, input_path]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=_qgis_env())
        if r.returncode != 0:
            return {"error": r.stderr[:500]}
        return {"output": output_path, "format": format}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout en ogr2ogr"}
    except Exception as e:
        return {"error": str(e)}


def buffer(input_geojson: dict, distance: float, dissolve: bool = False) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        params = {
            "INPUT": in_file,
            "DISTANCE": distance,
            "DISSOLVE": dissolve,
            "SEGMENTS": 5,
            "END_CAP_STYLE": 1,
            "JOIN_STYLE": 1,
            "MITER_LIMIT": 2,
            "OUTPUT": out_file,
        }
        result = qgis_run("native:buffer", params)
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def clip(input_geojson: dict, mask_geojson: dict) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    mask_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)
        with open(mask_file, "w", encoding="utf-8") as f:
            json.dump(mask_geojson, f)

        params = {"INPUT": in_file, "OVERLAY": mask_file, "OUTPUT": out_file}
        result = qgis_run("native:clip", params)
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, mask_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def _overlay_op(input_geojson: dict, overlay_geojson: dict, algorithm: str) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}
    in_file = tempfile.mktemp(suffix=".geojson")
    overlay_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)
        with open(overlay_file, "w", encoding="utf-8") as f:
            json.dump(overlay_geojson, f)
        params = {"INPUT": in_file, "OVERLAY": overlay_file, "OUTPUT": out_file}
        result = qgis_run(algorithm, params)
        if "error" in result:
            return result
        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, overlay_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def overlay_intersection(input_geojson: dict, overlay_geojson: dict) -> dict:
    return _overlay_op(input_geojson, overlay_geojson, "native:intersection")


def union(input_geojson: dict, overlay_geojson: dict) -> dict:
    return _overlay_op(input_geojson, overlay_geojson, "native:union")


def difference(input_geojson: dict, overlay_geojson: dict) -> dict:
    return _overlay_op(input_geojson, overlay_geojson, "native:difference")


def symmetrical_difference(input_geojson: dict, overlay_geojson: dict) -> dict:
    return _overlay_op(input_geojson, overlay_geojson, "native:symmetricaldifference")


def dissolve(input_geojson: dict, field: str | None = None) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        params: dict[str, Any] = {"INPUT": in_file, "OUTPUT": out_file}
        if field:
            params["FIELD"] = [field]
        result = qgis_run("native:dissolve", params)
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def centroids(input_geojson: dict) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        result = qgis_run("native:centroids", {"INPUT": in_file, "OUTPUT": out_file})
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def convex_hull(input_geojson: dict) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        result = qgis_run("native:convexhull", {"INPUT": in_file, "OUTPUT": out_file})
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def reproject(input_geojson: dict, target_crs: str = "EPSG:4326") -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        params = {"INPUT": in_file, "TARGET_CRS": target_crs, "OUTPUT": out_file}
        result = qgis_run("native:reprojectlayer", params)
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def fix_geometries(input_geojson: dict) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        result = qgis_run("native:fixgeometries", {"INPUT": in_file, "OUTPUT": out_file})
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def simplify_geometries(input_geojson: dict, tolerance: float = 1.0) -> dict:
    if not qgis_available():
        return {"error": "QGIS no disponible"}

    in_file = tempfile.mktemp(suffix=".geojson")
    out_file = tempfile.mktemp(suffix=".geojson")
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(input_geojson, f)

        params = {
            "INPUT": in_file, "METHOD": 0, "TOLERANCE": tolerance,
            "OUTPUT": out_file,
        }
        result = qgis_run("native:simplifygeometries", params)
        if "error" in result:
            return result

        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    finally:
        for f in [in_file, out_file]:
            try:
                os.unlink(f)
            except Exception:
                pass


def gdal_raster_info(raster_path: str) -> dict:
    cmd_path = _gdal_cmd("gdalinfo")
    if not cmd_path:
        return {"error": "gdalinfo no disponible"}
    try:
        r = subprocess.run([cmd_path, "-json", raster_path],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"error": r.stderr[:300]}
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)}


def gdal_warp(input_path: str, output_path: str | None = None,
              t_srs: str | None = None, te: str | None = None,
              tr: str | None = None, of: str = "GTiff") -> dict:
    cmd_path = _gdal_cmd("gdalwarp")
    if not cmd_path:
        return {"error": "gdalwarp no disponible"}
    if not output_path:
        output_path = tempfile.mktemp(suffix=".tif")
    cmd = [cmd_path, "-of", of, "-overwrite"]
    if t_srs:
        cmd += ["-t_srs", t_srs]
    if te:
        cmd += ["-te"] + te.split()
    if tr:
        cmd += ["-tr"] + tr.split()
    cmd += [input_path, output_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"error": r.stderr[:300]}
        return {"output": output_path}
    except Exception as e:
        return {"error": str(e)}


def polygonize(input_raster: str, output_geojson: str | None = None,
               band: int = 1) -> dict:
    cmd_path = _gdal_cmd("gdal_polygonize.py")
    if not cmd_path:
        cmd_path = _gdal_cmd("gdal_polygonize")
    if not cmd_path:
        return {"error": "gdal_polygonize no disponible"}
    if not output_geojson:
        output_geojson = tempfile.mktemp(suffix=".geojson")
    try:
        r = subprocess.run(
            ["python", cmd_path, input_raster, "-b", str(band),
             output_geojson, "-f", "GeoJSON"],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            return {"error": r.stderr[:300]}
        return {"output": output_geojson}
    except Exception as e:
        return {"error": str(e)}
