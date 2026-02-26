"""
FinSight AI - Authentication Service
=====================================
Authentication service with organisation context.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
import re
import logging
import traceback

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import verify_password, get_password_hash
from app.models.user import User
from app.models.organisation import Organisation, OrganisationMember
from app.schemas.auth import UserRegister, TokenData

logger = logging.getLogger(__name__)


def generate_slug(name: str) -> str:
    """Generate URL-safe slug from organisation name."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')[:100]


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
    try:
        logger.info(f"[AUTH_SERVICE] get_user_by_email called for email={email.lower()}")
        result = await db.execute(
            select(User)
            .options(selectinload(User.organisation))
            .where(User.email == email.lower())
        )
        user = result.scalar_one_or_none()
        logger.info(f"[AUTH_SERVICE] get_user_by_email result: {'found' if user else 'not found'}")
        return user
    except Exception as e:
        logger.error(f"[AUTH_SERVICE] get_user_by_email FAILED: {type(e).__name__}: {e}")
        logger.error(f"[AUTH_SERVICE] Full traceback:\n{traceback.format_exc()}")
        raise


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
    """
    Create a new user, their organisation, and an owner membership record.

    Each step is individually instrumented so that Cloud Run logs will
    show the exact step and exception that causes any failure.
    """
    logger.info(
        f"[REGISTER] create_user_with_organisation START — email={user_data.email.lower()}"
    )

    # ── Step 0: derive org name and find a unique slug ────────────────────
    try:
        org_name = (
            user_data.organisation_name
            or user_data.company_name
            or f"{user_data.full_name}'s Organisation"
        )
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
        logger.info(
            f"[REGISTER] Step 0 OK — org_name={org_name!r}, slug={slug!r}"
        )
    except Exception as exc:
        logger.error(
            f"[REGISTER] Step 0 FAILED (slug generation): "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        raise

    # ── Step 1: create Organisation, flush to obtain PK ───────────────────
    try:
        organisation = Organisation(
            name=org_name,
            slug=slug,
            subscription_tier="essentials",
            subscription_status="trial",
            settings={},
        )
        db.add(organisation)
        await db.flush()
        logger.info(
            f"[REGISTER] Step 1 OK — Organisation flushed: id={organisation.id}"
        )
    except Exception as exc:
        logger.error(
            f"[REGISTER] Step 1 FAILED (create Organisation): "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        raise

    # ── Step 2: create User, flush to obtain PK ───────────────────────────
    try:
        hashed_pw = get_password_hash(user_data.password)
        user = User(
            email=user_data.email.lower(),
            hashed_password=hashed_pw,
            full_name=user_data.full_name,
            job_title=user_data.job_title,
            organisation_id=organisation.id,
            role="owner",
            is_active=True,
            is_verified=False,
        )
        db.add(user)
        await db.flush()
        logger.info(f"[REGISTER] Step 2 OK — User flushed: id={user.id}")
    except Exception as exc:
        logger.error(
            f"[REGISTER] Step 2 FAILED (create User): "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        raise

    # ── Step 3: create OrganisationMember record, flush ───────────────────
    try:
        member = OrganisationMember(
            organisation_id=organisation.id,
            user_id=user.id,
            role="owner",
        )
        db.add(member)
        await db.flush()
        logger.info(
            f"[REGISTER] Step 3 OK — OrganisationMember flushed: id={member.id}"
        )
    except Exception as exc:
        logger.error(
            f"[REGISTER] Step 3 FAILED (create OrganisationMember): "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        raise

    # ── Step 4: commit the transaction ────────────────────────────────────
    try:
        await db.commit()
        logger.info("[REGISTER] Step 4 OK — transaction committed")
    except Exception as exc:
        logger.error(
            f"[REGISTER] Step 4 FAILED (commit): "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        raise

    # ── Step 5: re-query user with organisation eager-loaded ──────────────
    # After commit all ORM attributes are expired; use a fresh SELECT with
    # selectinload so the organisation relationship is populated without any
    # lazy-load (which would raise MissingGreenlet in async context).
    try:
        result = await db.execute(
            select(User)
            .options(selectinload(User.organisation))
            .where(User.id == user.id)
        )
        user = result.scalar_one()
        logger.info(
            f"[REGISTER] Step 5 OK — User re-queried: id={user.id}, "
            f"organisation_id={user.organisation_id}, "
            f"organisation_loaded={user.organisation is not None}"
        )
    except Exception as exc:
        logger.error(
            f"[REGISTER] Step 5 FAILED (re-query user): "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        raise

    logger.info(
        f"[REGISTER] create_user_with_organisation COMPLETE — user.id={user.id}"
    )
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
