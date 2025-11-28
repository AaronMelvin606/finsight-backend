"""
FinSight AI - Backend API
========================
FastAPI backend for the FinSight AI FP&A automation platform.

Author: Aaron Melvin
Company: FinSight AI Limited
Website: https://www.finsightai.tech
"""

import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, Base
from app.routers import auth, users, organisations, subscriptions, dashboards, demo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create database tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("=" * 50)
    logger.info("FinSight AI Backend Starting")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug Mode: {settings.DEBUG}")
    logger.info(f"Port: {os.getenv('PORT', '8000')}")
    logger.info(f"Database URL configured: {bool(settings.DATABASE_URL)}")
    logger.info("=" * 50)

    try:
        # Startup: Create tables if they don't exist
        logger.info("Connecting to database...")
        async with engine.begin() as conn:
            logger.info("Database connected. Creating tables...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.warning("Application will continue but database operations may fail")

    logger.info("Application startup complete - Ready to accept requests")
    yield

    # Shutdown: Clean up resources
    logger.info("Shutting down application...")
    try:
        await engine.dispose()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# Initialise FastAPI app
app = FastAPI(
    title="FinSight AI API",
    description="""
    Backend API for FinSight AI - The Operating System for Modern Finance.
    
    ## Features
    - User authentication (JWT-based)
    - Organisation management (multi-tenant)
    - Subscription tier management
    - Dashboard access control
    - Demo access with email gating
    
    ## Subscription Tiers
    - **Essentials** (£500/month): Basic dashboards, CSV upload
    - **Professional** (£1,500/month): Advanced analytics, Tableau dashboards
    - **Enterprise** (£3,500/month): Full platform, custom integrations
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Configure CORS for Netlify frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.finsightai.tech",
        "https://finsightai.tech",
        "http://localhost:3000",  # Local development
        "http://localhost:5173",  # Vite dev server
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(organisations.router, prefix="/api/v1/organisations", tags=["Organisations"])
app.include_router(subscriptions.router, prefix="/api/v1/subscriptions", tags=["Subscriptions"])
app.include_router(dashboards.router, prefix="/api/v1/dashboards", tags=["Dashboards"])
app.include_router(demo.router, prefix="/api/v1/demo", tags=["Demo Access"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API health check."""
    return {
        "status": "healthy",
        "service": "FinSight AI API",
        "version": "1.0.0",
        "documentation": "/docs"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check endpoint."""
    logger.debug("Health check requested")
    try:
        # Test database connection
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "disconnected"

    return {
        "status": "healthy",
        "database": db_status,
        "service": "FinSight AI API",
        "environment": settings.ENVIRONMENT,
        "port": os.getenv("PORT", "8000")
    }
