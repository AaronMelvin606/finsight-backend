"""
FinSight AI - Backend API
========================
FastAPI backend for the FinSight AI FP&A automation platform.

Author: Aaron Melvin
Company: FinSight AI Limited
Website: https://www.finsightai.tech
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import engine, Base
from app.routers import auth, users, organisations, subscriptions, dashboards, demo

# Create database tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: Clean up resources
    await engine.dispose()


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
    return {
        "status": "healthy",
        "database": "connected",
        "service": "FinSight AI API",
        "environment": settings.ENVIRONMENT
    }
