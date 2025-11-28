"""
FinSight AI - Configuration Settings
====================================
Environment-based configuration using Pydantic Settings.
"""

from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "FinSight AI"
    ENVIRONMENT: str = "development"  # development, staging, production
    DEBUG: bool = True

    # Database (Neon PostgreSQL)
    DATABASE_URL: str  # Required - your Neon connection string

    # JWT Authentication
    SECRET_KEY: str  # Required - generate with: openssl rand -hex 32
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Stripe (for subscriptions)
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_ESSENTIALS: Optional[str] = None  # Stripe Price ID
    STRIPE_PRICE_PROFESSIONAL: Optional[str] = None
    STRIPE_PRICE_ENTERPRISE: Optional[str] = None
    
    # Email (for notifications - optional for MVP)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    FROM_EMAIL: str = "hello@finsightai.tech"
    
    # Frontend URLs
    FRONTEND_URL: str = "https://www.finsightai.tech"
    
    # Demo Dashboard URL (Streamlit)
    DEMO_DASHBOARD_URL: Optional[str] = None
    
    # OpenAI (for AI commentary in dashboards)
    OPENAI_API_KEY: Optional[str] = None
    
    # File Storage (for CSV uploads - future)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET: Optional[str] = None
    AWS_REGION: str = "eu-west-2"  # London
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance with validation."""
    try:
        logger.info("Loading application settings...")
        settings = Settings()
        logger.info(f"✓ Settings loaded successfully")
        logger.info(f"  - Environment: {settings.ENVIRONMENT}")
        logger.info(f"  - Database URL: {'*' * 20}...{settings.DATABASE_URL[-20:] if len(settings.DATABASE_URL) > 20 else '***'}")
        logger.info(f"  - Secret Key: {'*' * 10}... (hidden)")
        return settings
    except Exception as e:
        logger.error("=" * 80)
        logger.error("CONFIGURATION ERROR - Application cannot start!")
        logger.error("=" * 80)
        logger.error(f"Error: {str(e)}")
        logger.error("")
        logger.error("Required environment variables:")
        logger.error("  - DATABASE_URL: PostgreSQL connection string (from Neon)")
        logger.error("  - SECRET_KEY: JWT secret key (generate with: openssl rand -hex 32)")
        logger.error("")
        logger.error("Please set these environment variables in your Railway dashboard:")
        logger.error("  1. Go to your Railway project")
        logger.error("  2. Click on your service")
        logger.error("  3. Go to 'Variables' tab")
        logger.error("  4. Add DATABASE_URL and SECRET_KEY")
        logger.error("=" * 80)
        sys.exit(1)


settings = get_settings()
