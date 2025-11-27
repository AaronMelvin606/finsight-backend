# ============================================
# FINSIGHT AI - DATABASE CONFIGURATION
# ============================================

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
import ssl

from app.core.config import settings

# Convert postgres:// to postgresql+asyncpg:// and handle SSL
database_url = settings.DATABASE_URL

# Handle different URL formats
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Remove sslmode and channel_binding from URL (asyncpg handles SSL differently)
# Parse out query parameters that asyncpg doesn't understand
if "?" in database_url:
    base_url, query_string = database_url.split("?", 1)
    # Remove problematic parameters
    params = query_string.split("&")
    filtered_params = [p for p in params if not p.startswith(("sslmode=", "channel_binding="))]
    if filtered_params:
        database_url = base_url + "?" + "&".join(filtered_params)
    else:
        database_url = base_url

# Create SSL context for Neon (requires SSL)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Create async engine with SSL
engine = create_async_engine(
    database_url,
    poolclass=NullPool,  # Required for serverless environments
    echo=settings.DEBUG,
    connect_args={
        "ssl": ssl_context,
    },
)

# Create async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """
    Dependency that provides a database session.
    Usage: db: AsyncSession = Depends(get_db)
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
