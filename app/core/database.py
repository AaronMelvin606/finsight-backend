# ============================================
# FINSIGHT AI - DATABASE CONFIGURATION
# ============================================

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
import ssl
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


# Convert postgres:// to postgresql+asyncpg:// for async driver
logger.info("Configuring database connection...")
database_url = settings.DATABASE_URL

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    logger.info("✓ Converted postgres:// to postgresql+asyncpg://")
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    logger.info("✓ Converted postgresql:// to postgresql+asyncpg://")

# Remove sslmode and channel_binding from URL (asyncpg handles SSL differently)
if "?" in database_url:
    base_url, query_string = database_url.split("?", 1)
    params = query_string.split("&")
    # Filter out parameters that asyncpg doesn't understand
    filtered_params = [p for p in params if not p.startswith(("sslmode=", "channel_binding=", "ssl="))]
    if filtered_params:
        database_url = base_url + "?" + "&".join(filtered_params)
    else:
        database_url = base_url
    logger.info("✓ Removed incompatible SSL parameters from URL")

# Create SSL context for Neon (requires SSL)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

logger.info("✓ Created SSL context for database connection")

# Create async engine with SSL
try:
    engine = create_async_engine(
        database_url,
        echo=settings.DEBUG,
        poolclass=NullPool,  # Recommended for serverless PostgreSQL
        connect_args={
            "ssl": ssl_context,
        },
    )
    logger.info("✓ Database engine created successfully")
except Exception as e:
    logger.error(f"✗ Failed to create database engine: {str(e)}")
    raise

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# Base class for all models
class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


async def get_db() -> AsyncSession:
    """
    Dependency that provides a database session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
