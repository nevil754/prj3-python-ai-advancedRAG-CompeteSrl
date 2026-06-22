#!/usr/bin/env python3   
  #chiamate SHEBANG dice all'os di eseguire questo file con python

# =============================================================
# scripts/create_tenant.py
# 🔥🔥CLI per creare un nuovo tenant da terminale.
# l'utente da riga di comando scrive questo e.g.:
#`
#   python scripts/create_tenant.py \
#     --slug acme-corp \
#     --name "Acme Corporation" \
#     --plan pro \
#     --admin-email admin@acme.com \
#     --admin-password SecurePass123!
# `
# =============================================================

import argparse   #!!serve x leggere comandi da linea di comando
import asyncio   #x async funct
import sys   #x os
from pathlib import Path   #x manipolare paths

sys.path.insert(
    0, 
    str(Path(__file__).parent.parent)  #__file__ è il path di questo script, poi sali su con parent e ancora con parent ed arrivi a root prj
)  #aggiunge il path all'inizio del PYTHONPATH, così quando importi moduli python cerca prima qui

async def main():
    parser = argparse.ArgumentParser(description="Crea un nuovo tenant RAG")  #crea parser CLI. ora se da cli runni 'python create_tenant.py --help' vedrai result "Crea un nuovo tenant RAG"
    parser.add_argument("--slug", required=True, help="Slug univoco (e.g. acme-corp)")   #obbligatorio, e.g. runni '--slug acme-corp' allora return args.slug
    parser.add_argument("--name", required=True, help="Nome visualizzato")
    parser.add_argument("--plan", default="starter", choices=["starter", "pro", "enterprise"])    #se non specificato diventa args.plan == "starter". ammessi solo starter,pro,enterprise
    parser.add_argument("--admin-email", help="Email admin (opzionale)")
    parser.add_argument("--admin-password", help="Password admin (opzionale)")
    args = parser.parse_args()   #🔥qui argparse LEGGE i parametri reali!!

    from app.services.tenant_service import provision_tenant  #ur custom

    print(f"Provisioning tenant: {args.slug}...")
    result = await provision_tenant(
        slug=args.slug,
        display_name=args.name,
        plan=args.plan,
        admin_email=args.admin_email,
        admin_password=args.admin_password,
    )
    print(f"✓ Tenant creato: {result}")

if __name__ == "__main__":  #SOLO se questo script è eseguito direttamente (python create_tenant.py)(non importato come modulo) allora esegui main()
    asyncio.run(main())

