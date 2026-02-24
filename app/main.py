"""
FinSight AI - Backend API
========================
FastAPI backend for the FinSight AI FP&A automation platform.

Author: Aaron Melvin
Company: FinSight AI Limited
Website: https://www.finsightai.tech
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.database import engine, Base
from app.routers import auth, users, organisations, subscriptions, dashboards, demo, financial_data

logger = logging.getLogger(__name__)

# Create database tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    import asyncio
    try:
        # Startup: Create tables if they don't exist
        logger.info("=" * 80)
        logger.info("STARTING FINSIGHT AI BACKEND")
        logger.info("=" * 80)
        logger.info("Connecting to database and creating tables...")

        # Add timeout to prevent indefinite hanging
        async def create_tables():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        try:
            # 60 second timeout for table creation
            await asyncio.wait_for(create_tables(), timeout=60.0)
            logger.info("✓ Database tables created successfully")
        except asyncio.TimeoutError:
            logger.warning("⚠ Database table creation timed out after 60 seconds")
            logger.warning("⚠ Tables may already exist or database is slow - continuing startup")
            # Continue anyway - tables might already exist
        except Exception as db_error:
            logger.error(f"⚠ Database table creation error: {str(db_error)}")
            logger.warning("⚠ Continuing startup - tables may already exist")
            # Continue anyway - in production, tables should already exist

        logger.info("✓ Application startup complete")
        logger.info("=" * 80)
        yield
        # Shutdown: Clean up resources
        logger.info("Shutting down application...")
        await engine.dispose()
        logger.info("✓ Database connections closed")
    except Exception as e:
        logger.error("=" * 80)
        logger.error("STARTUP ERROR - Application failed to start!")
        logger.error("=" * 80)
        logger.error(f"Error: {str(e)}")
        logger.error("")
        logger.error("Possible causes:")
        logger.error("  1. Database connection failed (check DATABASE_URL)")
        logger.error("  2. Database is unreachable")
        logger.error("  3. Database credentials are incorrect")
        logger.error("=" * 80)
        raise


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

# Allowed origins for CORS
origins = [
    "https://finsightai.tech",
    "https://www.finsightai.tech",
    "https://finsightai-dashboard.netlify.app",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
]

# Add CORS middleware FIRST - before any other middleware or exception handlers
# so that all responses (including errors) pass through it
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def _get_cors_headers(request: Request) -> dict:
    """Build CORS headers if the request origin is allowed."""
    origin = request.headers.get("origin", "")
    if origin in origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    return {}


# Exception handlers that include CORS headers as a safety net.
# Without these, error responses (4xx/5xx) can bypass CORSMiddleware
# and arrive at the browser without Access-Control-Allow-Origin.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    headers = _get_cors_headers(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    headers = _get_cors_headers(request)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
        headers=headers,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    headers = _get_cors_headers(request)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


# Explicit OPTIONS handler for preflight requests as a fallback
@app.options("/{rest_of_path:path}")
async def preflight_handler(request: Request, rest_of_path: str):
    headers = _get_cors_headers(request)
    return JSONResponse(content={"message": "OK"}, headers=headers)


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(organisations.router, prefix="/api/v1/organisations", tags=["Organisations"])
app.include_router(subscriptions.router, prefix="/api/v1/subscriptions", tags=["Subscriptions"])
app.include_router(dashboards.router, prefix="/api/v1/dashboards", tags=["Dashboards"])
app.include_router(demo.router, prefix="/api/v1/demo", tags=["Demo Access"])
app.include_router(financial_data.router, prefix="/api/v1/data", tags=["Financial Data"])


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
    """Fast health check endpoint for Cloud Run deployment."""
    return {
        "status": "healthy",
        "service": "FinSight AI API",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0"
    }


@app.get("/health/detailed", tags=["Health"])
async def detailed_health_check():
    """Detailed health check endpoint with database connection test."""
    import asyncio
    from sqlalchemy import text

    db_status = "unknown"
    db_details = None

    try:
        # Test database connection with timeout
        async with engine.connect() as conn:
            result = await asyncio.wait_for(
                conn.execute(text("SELECT 1")),
                timeout=5.0
            )
            db_status = "connected"
            db_details = "Database connection successful"
    except asyncio.TimeoutError:
        db_status = "timeout"
        db_details = "Database connection timed out after 5 seconds"
        logger.warning(f"Health check: {db_details}")
    except Exception as e:
        db_status = "error"
        db_details = f"Database error: {str(e)}"
        logger.error(f"Health check: {db_details}")

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "database_details": db_details,
        "service": "FinSight AI API",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0"
    }
