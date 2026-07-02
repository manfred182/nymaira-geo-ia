from __future__ import annotations
from shapely.geometry import Polygon
from shapely.validation import explain_validity


class AutomationEngine:
    def validate_boundary(self, coordinates: list[list[float]]) -> dict:
        if len(coordinates) < 3:
            return {
                "area": 0.0,
                "perimeter": 0.0,
                "is_valid": False,
                "warnings": ["Se necesitan al menos 3 coordenadas para formar un polígono"],
            }

        polygon = Polygon(coordinates)

        if not polygon.is_valid:
            return {
                "area": 0.0,
                "perimeter": 0.0,
                "is_valid": False,
                "warnings": [explain_validity(polygon)],
            }

        area_sq_units = polygon.area
        perimeter_units = polygon.length

        warnings = []
        if area_sq_units <= 0:
            warnings.append("El área calculada es cero o negativa")

        return {
            "area": round(area_sq_units, 4),
            "perimeter": round(perimeter_units, 4),
            "is_valid": True,
            "warnings": warnings,
        }

    def calculate_area_from_coords(
        self, coordinates: list[list[float]], crs: str = "EPSG:4326"
    ) -> dict:
        polygon = Polygon(coordinates)
        if not polygon.is_valid:
            return {"error": "Polígono no válido", "valid": False}

        area = polygon.area
        return {
            "area": round(area, 4),
            "crs": crs,
            "valid": True,
            "note": "Área en unidades del CRS actual. Para área en m² use EPSG:3857 o una proyección local.",
        }
