# =============================================================
# tests/conftest.py
# Fixtures pytest condivise tra tutti i test.
# =============================================================

from __future__ import annotations  #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import asyncio
import pytest  #plugin x test
from httpx import AsyncClient, ASGITransport   #AsyncClient x creare client async, ASGITransport x chiamare fastapi senza server reale
from main import create_app   #function x creare istanza fastapi app
from app.core.settings import get_settings


@pytest.fixture(scope="session")  #@pytest.fixture dice che è un obj riutilizzabile nel test, scope=session dice che viene creato 1 sola volta per tutta la sessione di test
def event_loop():
    """Event loop condiviso per tutti i test async della sessione."""
    loop = asyncio.new_event_loop()  #crei manualmente il loop, xk python di default non gestisce bene async
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def app():
    """Istanza FastAPI per i test."""
    return create_app()  #crea 1 sola istanza di app per tutti i test

@pytest.fixture
async def client(app):   #async client x testare le route fastapi senza server reale, usa ASGITransport che non fa http reale ma chiama direttamente l'app fastapi in memoria
    """Client HTTP async per chiamare le API nei test."""
    async with AsyncClient(
        transport=ASGITransport( app=app ),
        base_url="http://test"   #serve solo per costruire URL coerenti
    ) as ac:
        yield ac

@pytest.fixture
def tenant_context():    #crea utente finto multi-tenant
    """Contesto tenant fake per i test unitari."""
    from app.api.deps import TenantContext
    return TenantContext(
        tenant_id="test-tenant-uuid",
        tenant_slug="test-tenant",
        user_id="test-user-uuid",
        user_role="admin",
        user_email="test@example.com",
    )

@pytest.fixture
def sample_chunks():   #rappresenta un chunck estratto da qdrant
    """2 chunks fake per i test di retrieval e generation."""
    from app.rag.retrieval.retriever import RetrievedChunk
    return [
        RetrievedChunk(
            text="Il contratto scade il 31 dicembre 2024 salvo rinnovo tacito.",
            score=0.92,
            chunk_id="chunk-001",
            document_id="doc-001",
            filename="contratto_acme.pdf",
            page_number=3,
            chunk_index=0,
            doc_type="contract",
            metadata={},
        ),
        RetrievedChunk(
            text="Le parti concordano un corrispettivo mensile di 5.000 euro.",
            score=0.87,
            chunk_id="chunk-002",
            document_id="doc-001",
            filename="contratto_acme.pdf",
            page_number=4,
            chunk_index=1,
            doc_type="contract",
            metadata={},
        ),
    ]

