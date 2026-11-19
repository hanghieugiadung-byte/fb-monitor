"""
Shared auth dependency — checks X-API-Key header against APP_SECRET_KEY.
If APP_SECRET_KEY is the default placeholder, auth is effectively disabled.
"""
from fastapi import Header, HTTPException, status
from config import settings


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """Dependency: allow request only if X-API-Key matches APP_SECRET_KEY.

    Auth is skipped when APP_SECRET_KEY is set to the default placeholder value,
    so out-of-the-box installs work without configuration.
    """
    secret = settings.app_secret_key
    # Skip auth when key is still the default placeholder
    if secret == "change_this_to_random_string":
        return
    if x_api_key != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
