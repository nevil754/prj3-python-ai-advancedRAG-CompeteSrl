#!/usr/bin/env python
   #chiamate SHEBANG dice all'os di eseguire questo file con python

# =============================================================
# scripts/seed_demo_data.py
# Inserisce dati demo per il tenant demo-corp.
# Utile per avere dati di test senza caricare documenti reali.
# Uso: python scripts/seed_demo_data.py
# =============================================================

import asyncio   #x async funct, gia incluso w python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   #__file__ è il path di questo script, poi sali su con parent e ancora con parent ed arrivi a root prj. aggiunge il path all'inizio del PYTHONPATH così quando importi moduli python cerca prima qui

DEMO_TENANT_SLUG = "demo-corp"
DEMO_USER_EMAIL = "demo@demo-corp.com"
DEMO_USER_PASSWORD = "Demo123456!"
DEMO_DOCUMENTS = [
    {
        "filename": "contratto_fornitura_2024.pdf",
        "content": """
            # Contratto di Fornitura Software
            **Parti:**
            - Fornitore: Compete Srl, Via Roma 1, Milano
            - Cliente: Demo Corporation Srl, Via Milano 5, Roma
            **Oggetto:** Fornitura di software RAG Enterprise Legal
            **Durata:** Dal 01/01/2024 al 31/12/2024, con rinnovo tacito annuale.
            **Corrispettivo:** Euro 5.000 mensili + IVA, pagabili entro 30 giorni dalla fattura.
            **Risoluzione:** Possibile con preavviso scritto di 90 giorni.
            **Foro competente:** Milano
        """,
    },
    {
        "filename": "privacy_policy_gdpr.pdf",
        "content": """
            # Informativa Privacy GDPR
            **Titolare del Trattamento:** Demo Corporation Srl
            **Finalità del trattamento:**
            - Erogazione dei servizi contrattuali
            - Adempimenti fiscali e contabili
            - Marketing previo consenso
            **Base giuridica:** Esecuzione del contratto (art. 6 lett. b GDPR)
            **Periodo di conservazione:** 10 anni per documenti fiscali, 2 anni per dati di marketing.
            **Diritti dell'interessato:** Accesso, rettifica, cancellazione, opposizione, portabilità.
            **Responsabile Protezione Dati (DPO):** dpo@demo-corp.com
        """,
    },
]

async def main():
    print(f"Seeding dati demo per tenant: {DEMO_TENANT_SLUG}")
    from app.db.sqlserver import tenant_db
    from app.core.security import hash_password
    from sqlalchemy import text
    from uuid import uuid4

    async with tenant_db.aget_session(DEMO_TENANT_SLUG) as session:
        existing = await session.execute(   #check se utente esiste 
            text("SELECT id FROM users WHERE email = :email"),
            {"email": DEMO_USER_EMAIL}
        )
        if not existing.fetchone():  #se non riesce a fetcharne neanche 1, allora ...
            await session.execute(
                text("""
                    INSERT INTO users (id, email, role, password_hash, full_name)
                    VALUES (:id, :email, 'admin', :pwd, 'Demo User')
                """),
                {
                    "id": str(uuid4()),
                    "email": DEMO_USER_EMAIL,
                    "pwd": hash_password(DEMO_USER_PASSWORD),
                }
            )
            print(f"✓ Utente demo creato: {DEMO_USER_EMAIL} / {DEMO_USER_PASSWORD}")
        else:
            print(f"  Utente demo già esistente: {DEMO_USER_EMAIL}")

    # Salva documenti demo su disco e ingestionali
    import tempfile
    import os
    from app.rag.ingestion.pipeline import run_ingestion_pipeline    #ur custom

    async with tenant_db._async_factory() as session:
        row = await session.execute(
            text("SELECT id FROM shared.tenants WHERE slug = :slug"),
            {"slug": DEMO_TENANT_SLUG}
        )
        tenant_id = str( row.fetchone().id )  #prendi solo l'id dalla row fetchata
    for doc in DEMO_DOCUMENTS:   #sono solo 2
        # Salva come file temporaneo
        with tempfile.NamedTemporaryFile(  #CREA UN FILE FISICO temp
            suffix=".txt",
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as f:
            f.write( doc["content"] )  #scrive sul documento
            tmp_path = f.name  #e.g. C:\Temp\tmp123.txt
        try:
            doc_id = str(uuid4())
            async with tenant_db.aget_session(DEMO_TENANT_SLUG) as session:
                await session.execute(
                    text("""
                        INSERT INTO documents
                            (id, filename, original_name, file_hash, file_size, mime_type, status, uploaded_by)
                        VALUES (:id, :fname, :orig, NEWID(), :size, 'text/plain', 'pending', NULL)
                    """),
                    {
                        "id": doc_id,
                        "fname": doc["filename"],
                        "orig": doc["filename"],
                        "size": len(doc["content"].encode()),
                    }
                )
            result = run_ingestion_pipeline(
                tenant_id=tenant_id,
                tenant_slug=DEMO_TENANT_SLUG,
                document_id=doc_id,
                file_path=tmp_path,
            )
            print(f"✓ Documento ingestito: {doc['filename']} ({result['chunk_count']} chunk)")
        finally:
            os.unlink(tmp_path)  #target path viene cancellato da filesystem. quindi (se non ci sono altri riferimenti) immediatamente viene automaticamente liberato spazio su disco.  
    print("\nSeeding completato! Puoi fare login con:")
    print(f"  Email: {DEMO_USER_EMAIL}")
    print(f"  Password: {DEMO_USER_PASSWORD}")
    print(f"  Tenant: {DEMO_TENANT_SLUG}")

if __name__ == "__main__":
    asyncio.run(main())


