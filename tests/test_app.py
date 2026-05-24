import pytest
from httpx import ASGITransport, AsyncClient

from laws_api_mirror.api.app import app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_root_returns_metadata() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "laws-api-mirror"
    assert body["base_path"] == "/api/2"


@pytest.mark.asyncio
async def test_openapi_schema_available() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "laws-api-mirror"
