import os
from fastapi import HTTPException, Security, Request
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key(api_key: str = Security(api_key_header)):
    """Validate API key from header if SUPPORT_API_KEY env var is set.
    If no expected key configured, allows open access (dev mode)."""
    expected = os.getenv("SUPPORT_API_KEY")
    if os.getenv('ALLOW_UNAUTH_LOCAL') == '1':
        return None
    if not expected:
        return None  # open mode
    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return api_key