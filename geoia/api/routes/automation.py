from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_engine = None
def get_engine():
    global _engine
    if _engine is None:
        from geoia.automation.engine import AutomationEngine
        _engine = AutomationEngine()
    return _engine


class BoundaryRequest(BaseModel):
    coordinates: list[list[float]]


class BoundaryResponse(BaseModel):
    area: float
    perimeter: float
    is_valid: bool
    warnings: list[str]


@router.post("/validate-boundary", response_model=BoundaryResponse)
async def validate_boundary(req: BoundaryRequest):
    try:
        engine = get_engine()
        result = engine.validate_boundary(req.coordinates)
        return BoundaryResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
