"""
FinSight AI - Core Module
=========================
Export core utilities.
"""

from app.core.config import settings, get_settings
from app.core.database import get_db, engine, Base, AsyncSessionLocal
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_current_active_user,
    require_subscription_tier,
)

__all__ = [
    # Config
    "settings",
    "get_settings",
    
    # Database
    "get_db",
    "engine",
    "Base",
    "AsyncSessionLocal",
    
    # Security
    "get_password_hash",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_current_user",
    "get_current_active_user",
    "require_subscription_tier",
]
