# =============================================================
# tests/integration/test_health.py
# Test endpoint /health e /ready.
# Questi non richiedono autenticazione.
# =============================================================

import pytest


@pytest.mark.asyncio   #dice a pytest che questo test è async -> usa event loop
async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200   #assert equivale a  'if not condition: raise AssertionError()'. quindi endpoint deve funzionare altrimenti raise the error
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "uptime_seconds" in data


@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    """Health check non richiede token."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ready_has_checks(client):
    """Ready endpoint deve avere checks per ogni servizio."""
    response = await client.get("/ready")
    # Può essere 200 o 503 a seconda se i servizi sono up
    assert response.status_code in (200, 503)
    data = response.json()
    assert "checks" in data
    assert "redis" in data["checks"]
    assert "sqlserver" in data["checks"]
    assert "qdrant" in data["checks"]

