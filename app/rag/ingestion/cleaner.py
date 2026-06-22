# =============================================================
# app/rag/ingestion/cleaner.py
# Pulizia testo estratto dal parser prima del chunking.
# =============================================================

from __future__ import annotations   #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import re   #x regex per pulizia testo


def clean_text(text: str) -> str:
    """
    Pulisce il testo estratto dal parser rimuovendo artefatti
    comuni nei PDF/DOCX e normalizzando il whitespace.
    """
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)   #rimuove null bytes e caratteri di controllo (tranne newline e tab!)
    text = text.replace("\r\n", "\n").replace("\r", "\n")   #normalizza line endings. \r serve per andare a inizio linea
    text = re.sub(r"^\s*-?\s*\d+\s*-?\s*$", "", text, flags=re.MULTILINE)  #rimuove linee che sono solo numeri di pagine (e.g. "- 42 -" -> 42)

    # Rimuovi header/footer ripetuti (3+ occorrenze della stessa riga)
    lines = text.split("\n")  #splitta in fette, basandoti sui '\n'
    line_counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()  #rimuove spazi laterali
        if len(stripped) > 5:  #considera solo le linee con >5 chars!!
            line_counts[stripped] = line_counts.get(stripped, 0) + 1  #per key line_counts[stripped], controlla se gia esiste la key se esiste allora prende il value e fa +1, altrimenti il value è 0.

    #rimuovi linee che appaiono più di 5 volte (probabili header/footer)
    repeated = { line for  line, count in line_counts.items() if count > 5 }  #se ci sono >5 elems(ogni elem è un key-value) in dict line_counts, quindi per ciascun key-value fa unapack in line-count.  line for iniziale è un Set comprehension, quindi crea un Set 
    if repeated:
        lines = [l for  l in lines if l.strip() not in repeated]
        text = "\n".join(lines)  #update var
    text = re.sub(r"[ \t]+", " ", text)   #collassa spaces multipli in 1 (ma non newline)
    text = re.sub(r"\n{3,}", "\n\n", text)  #collassa piu di 3 newline consecutive in 2 
    text = "\n".join(line.rstrip() for line in text.split("\n"))  #rimuove spazi ad inizio e fine di ogni riga
    return text.strip()

def normalize_whitespace(text: str) -> str:
    """Normalizzazione leggera — solo whitespace, nessuna rimozione di contenuto"""
    text = re.sub(r"[ \t]+", " ", text)  #spaces multipli
    text = re.sub(r"\n{3,}", "\n\n", text)  #newline
    return text.strip()

