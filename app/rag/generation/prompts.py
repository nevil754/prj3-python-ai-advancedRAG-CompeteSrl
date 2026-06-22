# =============================================================
# app/rag/generation/prompts.py
# Carica prompt da prompts.yaml e formatta con i dati di runtime.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from functools import lru_cache  
from pathlib import Path
from typing import Any
import yaml
from loguru import logger


def get_rag_system_prompt(tenant_name: str = "Compet-e Compliance AI") -> str:
    """Ritorna il system prompt per il RAG."""
    prompts = _load_prompts()  
    template = prompts.get("system", {}).get("base", _DEFAULT_SYSTEM)   #cerca system.base nel file yaml, se non c'è usa _DEFAULT_SYSTEM
    return template.format( tenant_name=tenant_name )  #nel template text, sostituisce il pezzo interpolazione {tenant_name} con tenant_name

def get_rag_user_prompt(
    context: str,
    history: str,
    question: str,
) -> str:
    """Formatta il prompt utente con context, history e domanda."""
    prompts = _load_prompts()   #function here qua sotto che ha @lru_cache(maxsize=1)
    template = prompts.get("rag", {}).get("main", _DEFAULT_RAG)  #cerca rag.main nel file yaml, se non c'è usa _DEFAULT_RAG
    return template.format(
        context=context,
        history=history,
        question=question,
    )  #filla con questi valori i placeholder nel template 

def get_no_context_message() -> str:
    prompts = _load_prompts()
    return prompts.get("rag", {}).get("no_context", _DEFAULT_NO_CONTEXT)

@lru_cache(maxsize=1)  #decoratore che trasforma la funzione in un singleton, quindi _load_prompts() ritorna sempre la stessa istanza del dict dei prompts, evitando overhead di lettura file multiple
def _load_prompts() -> dict:
    """Carica prompts.yaml una sola volta."""
    prompt_file = Path("/app/config/prompts.yaml")  #è un file diverso da questo rag/generation/prompts.py
    if not prompt_file.exists():
        logger.warning("prompts.yaml non trovato, uso prompt hardcodati")
        return {}
    with open(prompt_file) as f:
        return yaml.safe_load(f) or {}


_DEFAULT_SYSTEM = """Sei un assistente legale AI per {tenant_name}.
Rispondi sempre in italiano a meno che l'utente non scriva in un'altra lingua.
Sei preciso, professionale e citi sempre le fonti dei documenti.
Non inventare mai informazioni che non sono nei documenti forniti.
Se non trovi la risposta nei documenti, dillo esplicitamente."""

_DEFAULT_RAG = """Usa ESCLUSIVAMENTE le seguenti sezioni di documenti per rispondere.
Per ogni informazione, cita il documento nel formato [Fonte: nome_file, p.X].
Se la risposta non è nei documenti, dì: "Non ho trovato questa informazione nei documenti."

DOCUMENTI:
{context}

STORICO CONVERSAZIONE:
{history}

DOMANDA: {question}

RISPOSTA:"""

_DEFAULT_NO_CONTEXT = ("Non ho trovato documenti rilevanti per rispondere. " "Prova a riformulare la domanda o carica i documenti pertinenti.")
