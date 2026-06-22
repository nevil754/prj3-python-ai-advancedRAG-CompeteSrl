# app/core/security.py
# Tutto ciò che riguarda autenticazione e crittografia.
# JWT encode/decode, password hashing con bcrypt, API key generation.
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import hashlib  #x hashing
import secrets  #x generazione chiavi sicure
from datetime import datetime, timedelta, timezone
from typing import Any  #x type hints generici
from jose import JWTError, jwt  #lib jwt, gia installata con "pip install python-jose[cryptography]"
from loguru import logger  
from passlib.context import CryptContext   #lib hashing psw
from app.core.settings import get_settings  #ur custom

settings = get_settings()

# bcrypt con cost factor 12 — buon bilanciamento sicurezza/velocità
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)  #bcrypt è algh hashing psw, deprecated="auto" per migrazioni future e.g. bycript -> argon2 allora Passlib riesce a riconoscere hash vecchi e migrarli, bcrypt__rounds=12 è cost factor piu è alto piu è sicuro: 12 è un buon bilanciamento

def hash_password(plain: str) -> str:
    """
    Genera hash bcrypt della password.
    Mai salvare password in chiaro — sempre chiamare questa funzione!
    """
    return _pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    """
    Confronta password in chiaro con hash bcrypt.
    Ritorna True se corrispondono, False altrimenti.
    è Timing-safe cioe non vulnerabile a timing attacks(malintenzionato misura il tempo di risposta e con questo puo indovinare hash/psw char-by-char)
    """
    return _pwd_context.verify(plain, hashed)

def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Crea un JWT access token firmato con HS256.
    Args:
        data: payload del token. Deve includere almeno:
              - sub: user_id (stringa)
              - tenant_id: ID del tenant
              - role: ruolo utente (admin/user/viewer)
        expires_delta: durata validità. Default: 'jwt_expire_minutes' da config.py
    Returns:
        JWT token come stringa.
    e.g. payload decodificato:
        {
            "sub": "uuid-utente",
            "tenant_id": "uuid-tenant",
            "tenant_slug": "acme-corp",
            "role": "admin",
            "exp": 1234567890
        }
    """
    to_encode = data.copy()  #clone che modifichi
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)   #issued at
    token = jwt.encode(   #firma token
        to_encode,    #payload cloned&edited
        settings.jwt_secret_key,  #la secret key serve x firma!
        algorithm=settings.jwt_algorithm,  #e.g. HS256
    )
    return token

def decode_access_token(token: str) -> dict[str, Any] | None:   #check validation & DECODFICA il token e return il payload
    """
    Decodifica e valida un JWT token.
    Returns:
        Payload del token se valido, None se scaduto o invalido.
    """
    try:
        payload = jwt.decode(  #verifica firma-scadenza-algh
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.debug(f"JWT decode fallito: {e}")
        return None

def extract_tenant_from_token(token: str) -> tuple[str, str] | None:
    """
    Estrae (tenant_id, tenant_slug) dal JWT.
    Returns:
        Tuple (tenant_id, tenant_slug) se token valido, None altrimenti.
    """
    payload = decode_access_token(token)
    if not payload:
        return None
    tenant_id = payload.get("tenant_id")   #lo prende dal payload recuperato
    tenant_slug = payload.get("tenant_slug")   #lo prende dal payload recuperato
    if not tenant_id or not tenant_slug:
        logger.warning("Token JWT senza tenant_id o tenant_slug")
        return None
    return tenant_id, tenant_slug

def generate_api_key(length: int | None = None) -> tuple[str, str]:   #genera api key sicura
    """
    Genera una API key casuale e il suo hash SHA-256.
    Nel database salvi solo l'hash, mai la key in chiaro.
    Returns:
        Tuple (api_key_plain, api_key_hash)
        api_key_plain: mostrata UNA SOLA VOLTA all'utente
        api_key_hash:  salvata nel DB nella tabella shared.api_keys
    """
    key_length = length or settings.api_key_length
    api_key = f"rag_{secrets.token_urlsafe(key_length)}"  #genera random crittofigramente sicuro🔥
    key_hash = hash_api_key(api_key)
    return api_key, key_hash

def hash_api_key(api_key: str) -> str:
    """Hash SHA-256 di una API key. Deterministico — stesso input = stesso output."""
    return hashlib.sha256(api_key.encode()).hexdigest()  #trasforma stringa api key in hash SHA-256(ricorda che lavora con bytes, quindi prima dovresti devi fare api_key.encode() ) irreversibile in formato esadecimale. il risultato di sha-256 è attualmente binario quindi hexdigest() lo converte in str leggibile esadecimale.

def verify_api_key(plain_key: str, stored_hash: str) -> bool:
    """Verifica una API key confrontando il suo hash con quello salvato."""
    return secrets.compare_digest( hash_api_key(plain_key), stored_hash )

def extract_bearer_token(authorization_header: str | None) -> str | None:
    """
    Estrae il token dall'header Authorization.
    Args:
        authorization_header: valore header, es. "Bearer eyJ..."
    Returns:
        Token puro senza "Bearer ", oppure None se header assente/malformato.
    """
    if not authorization_header:
        return None
    parts = authorization_header.split(" ")   #divide portando 'Bearer' in [0] e il resto in [1]
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


