"""
FinSight AI - Authentication Service
=====================================
Authentication service with organisation context.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
import re

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.user import User
from app.models.organisation import Organisation
from app.schemas.auth import UserRegister, TokenData


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_slug(name: str) -> str:
    """Generate URL-safe slug from organisation name."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')[:100]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT token, returning TokenData."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return TokenData(
            user_id=UUID(payload.get("sub")),
            email=payload.get("email", ""),
            organisation_id=UUID(payload.get("org_id")) if payload.get("org_id") else None,
            role=payload.get("role", "member"),
            subscription_tier=payload.get("tier", "essentials")
        )
    except JWTError:
        return None


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Get user by email with organisation loaded."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.organisation))
        .where(User.email == email.lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
    """Get user by ID with organisation loaded."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.organisation))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    """Authenticate user and return user with organisation."""
    user = await get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user


async def create_user_with_organisation(
    db: AsyncSession,
    user_data: UserRegister
) -> User:
    """Create a new user and their organisation."""

    # Determine organisation name
    org_name = user_data.organisation_name or user_data.company_name or f"{user_data.full_name}'s Organisation"

    # Generate unique slug
    base_slug = generate_slug(org_name)
    slug = base_slug
    counter = 1

    while True:
        existing = await db.execute(
            select(Organisation).where(Organisation.slug == slug)
        )
        if not existing.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Create organisation
    organisation = Organisation(
        name=org_name,
        slug=slug,
        subscription_tier="essentials",
        subscription_status="trial",
        settings={}
    )
    db.add(organisation)
    await db.flush()  # Get the organisation ID

    # Create user as owner of the organisation
    user = User(
        email=user_data.email.lower(),
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
        job_title=user_data.job_title,
        organisation_id=organisation.id,
        role="owner",
        is_active=True,
        is_verified=False
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Load the organisation relationship
    await db.refresh(user, ["organisation"])

    return user


def create_tokens_for_user(user: User) -> dict:
    """Create access and refresh tokens with organisation context."""

    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role or "member",
    }

    # Include organisation info if user has one
    if user.organisation_id:
        token_data["org_id"] = str(user.organisation_id)
        if user.organisation:
            token_data["tier"] = user.organisation.subscription_tier

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }
