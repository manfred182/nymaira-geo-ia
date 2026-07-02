import pytest
from geoia.chatbot.engine import ChatbotEngine


@pytest.mark.asyncio
async def test_chatbot_responde():
    engine = ChatbotEngine()
    respuesta = await engine.chat("¿Qué es una matrícula inmobiliaria?")
    assert len(respuesta) > 0
    assert "matrícula" in respuesta.lower() or "inmobiliaria" in respuesta.lower()


@pytest.mark.asyncio
async def test_chatbot_mantiene_memoria():
    engine = ChatbotEngine()
    await engine.chat("Hola", session_id="test1")
    await engine.chat("¿Qué es el avalúo catastral?", session_id="test1")
    assert len(engine.sessions["test1"]) == 4


@pytest.mark.asyncio
async def test_chatbot_resetea_sesion():
    engine = ChatbotEngine()
    await engine.chat("Hola", session_id="test2")
    engine.reset_session("test2")
    assert "test2" not in engine.sessions
