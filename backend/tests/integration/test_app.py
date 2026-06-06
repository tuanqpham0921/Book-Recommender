import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_app_smoke():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as ac:
        response = await ac.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["timestamp"] is not None