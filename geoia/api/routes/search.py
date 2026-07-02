from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from geoia.websearch import searcher
from geoia.websearch.colombia import search_colombia, search_all_categories, FUENTES
from geoia.websearch.api_colombia import search_soda, query_arcgis_hub, search_all_apis, listar_apis_disponibles, ENDPOINTS

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    num_results: int = 5


class SearchResponse(BaseModel):
    results: list[dict]
    count: int


class ColombiaSearchRequest(BaseModel):
    query: str
    categoria: str = "catastral"
    num_por_fuente: int = 2


class ColombiaSearchResponse(BaseModel):
    results: list[dict]
    count: int
    categoria: str


class ColombiaMultiResponse(BaseModel):
    catastral: list[dict]
    ambiental: list[dict]
    productiva: list[dict]
    social: list[dict]
    economica: list[dict]
    infraestructura: list[dict]
    gobierno: list[dict]


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    try:
        results = await searcher.search(req.query, req.num_results)
        return SearchResponse(results=results, count=len(results))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/colombia", response_model=ColombiaSearchResponse)
async def search_colombia_endpoint(req: ColombiaSearchRequest):
    try:
        results = await search_colombia(req.query, req.categoria, req.num_por_fuente)
        return ColombiaSearchResponse(results=results, count=len(results), categoria=req.categoria)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/colombia/todas", response_model=ColombiaMultiResponse)
async def search_colombia_todas(query: str = Query(...), num_por_fuente: int = Query(1)):
    try:
        result = await search_all_categories(query, num_por_fuente)
        return ColombiaMultiResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/colombia/fuentes")
async def listar_fuentes():
    return FUENTES


@router.post("/colombia/api")
async def search_colombia_api(query: str = Query(...), categoria: str = Query("catastral")):
    """Busca directamente en APIs oficiales colombianas (datos.gov.co SODA, ICDE, API-Colombia)."""
    try:
        results = await search_all_apis(query)
        if categoria != "todas":
            results = [r for r in results if r.get("categoria") == categoria or r.get("categoria") == "general"]
        return {"results": results, "count": len(results), "categoria": categoria}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/colombia/apis")
async def listar_apis():
    """Lista las APIs oficiales disponibles para consulta directa."""
    return {"apis": listar_apis_disponibles()}


@router.get("/health")
async def health():
    return await searcher.health()
