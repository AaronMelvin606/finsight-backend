"""
FinSight AI - Configuration Settings
====================================
Environment-based configuration using Pydantic Settings.
"""

from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


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
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
