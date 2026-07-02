from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from geoia.models_manager import manager

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    model: str = ""
    session_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    model: str
    provider: str


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    await manager.discover()
    messages = [{"role": "user", "content": req.message}]
    try:
        resp = await manager.chat(messages, model=req.model)
        ep = manager.get_endpoint(req.model) or {}
        return ChatResponse(
            response=resp,
            model=req.model or "fallback",
            provider=ep.get("provider", "local"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_models():
    await manager.discover()
    return {"endpoints": manager.health()}


@router.post("/discover")
async def discover():
    await manager.discover()
    return {"endpoints": len(manager.endpoints), "models": manager.list_models()}
