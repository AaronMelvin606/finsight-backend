"""
FinSight AI - Configuration Settings
====================================
Environment-based configuration using Pydantic Settings.
"""

from pydantic_settings import BaseSettings
from pydantic import model_validator
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
    # Defaults allow the container to start for health checks even without env vars
    DATABASE_URL: str = "postgresql://localhost/finsight"

    # JWT Authentication
    SECRET_KEY: str = "CHANGE-ME-set-SECRET_KEY-env-var"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 60 minutes for Swagger/manual testing; override via env in prod if needed
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
    
    # OpenAI (for AI commentary in dashboards — legacy)
    OPENAI_API_KEY: Optional[str] = None

    # Anthropic (for Claude AI commentary generation)
    ANTHROPIC_API_KEY: Optional[str] = None
    
    # File Storage (for CSV uploads - future)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET: Optional[str] = None
    AWS_REGION: str = "eu-west-2"  # London

    # Sentry (error monitoring)
    SENTRY_DSN: Optional[str] = None

    @model_validator(mode='after')
    def validate_secret_key(self) -> 'Settings':
        placeholder = "CHANGE-ME-set-SECRET_KEY-env-var"
        if self.SECRET_KEY == placeholder and \
                self.ENVIRONMENT in ("staging", "production"):
            raise RuntimeError(
                f"SECRET_KEY is using the placeholder default. "
                f"Set the SECRET_KEY environment variable before "
                f"deploying to {self.ENVIRONMENT}."
            )
        return self

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

        # Warn if using default placeholder values
        if settings.SECRET_KEY == "CHANGE-ME-set-SECRET_KEY-env-var":
            logger.warning("⚠ SECRET_KEY is using a default value! Set the SECRET_KEY environment variable.")
        if settings.DATABASE_URL == "postgresql://localhost/finsight":
            logger.warning("⚠ DATABASE_URL is using a default value! Set the DATABASE_URL environment variable.")

        return settings
    except Exception as e:
        logger.error("=" * 80)
        logger.error("CONFIGURATION ERROR")
        logger.error("=" * 80)
        logger.error(f"Error: {str(e)}")
        logger.error("")
        logger.error("Required environment variables:")
        logger.error("  - DATABASE_URL: PostgreSQL connection string (from Neon)")
        logger.error("  - SECRET_KEY: JWT secret key (generate with: openssl rand -hex 32)")
        logger.error("")
        logger.error("Set these in your Cloud Run service configuration.")
        logger.error("=" * 80)
        # Return settings with defaults so the container can still start
        # for health checks. API endpoints will fail gracefully.
        return Settings()


settings = get_settings()
