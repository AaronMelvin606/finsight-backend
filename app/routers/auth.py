"""
FinSight AI - Authentication Router
===================================
API endpoints for user authentication with organisation context.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone, timedelta
import asyncio

from app.core.database import get_db
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_token as security_decode_token,
)
from app.core.config import settings
from app.api.deps import get_current_user
from app.models.user import User
from app.models.organisation import Organisation, OrganisationMember, MemberRole
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    TokenRefresh,
    PasswordReset,
    PasswordResetConfirm,
    PasswordChange,
    UserResponse,
    UserWithOrganisation,
    Token,
)
from app.services.auth_service import (
    authenticate_user,
    create_user_with_organisation,
    create_tokens_for_user,
    get_user_by_email,
)
from app.services.email_service import send_password_reset_email

from app.core.limiter import limiter

import sentry_sdk
import uuid
import logging
import traceback

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_registration_allowed(email: str) -> None:
    """
    Raise HTTP 403 if open registration is disabled and the email
    is not on the allowed list.

    Controlled by the ALLOWED_REGISTRATION_EMAILS environment variable.
    Set to a comma-separated list of permitted emails, e.g.:
        aaron@finsightai.tech,demo@finsightai.tech

    If the variable is empty or unset, ALL registration is blocked.
    This is intentional — FinSight AI is invite-only during stealth.
    """
    raw = getattr(settings, "ALLOWED_REGISTRATION_EMAILS", "") or ""
    allowed = [e.strip().lower() for e in raw.split(",") if e.strip()]

    if not allowed:
        logger.warning(
            f"[REGISTER] Blocked registration attempt for {email} — "
            "ALLOWED_REGISTRATION_EMAILS is empty (invite-only mode active)"
        )
        sentry_sdk.capture_message(
            f"Registration blocked (no allowlist configured): {email}",
            level="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently invite-only. Please contact hello@finsightai.tech.",
        )

    if email.lower() not in allowed:
        logger.warning(
            f"[REGISTER] Blocked unauthorised registration attempt for {email}"
        )
        sentry_sdk.capture_message(
            f"Unauthorised registration attempt blocked: {email}",
            level="warning",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently invite-only. Please contact hello@finsightai.tech.",
        )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user and create their organisation.
    Returns access and refresh tokens with user and organisation info.
    """
    try:
        logger.info(f"[REGISTER] Starting registration for email={user_data.email}")

        # Allowlist check — blocks all unauthorised registration attempts
        _check_registration_allowed(user_data.email)

        # Check if email already exists
        existing_user = await get_user_by_email(db, user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        logger.info("[REGISTER] Email check passed, creating user with organisation")

        # Create user with organisation
        user = await create_user_with_organisation(db, user_data)

        logger.info(f"[REGISTER] User created: id={user.id}, org_id={user.organisation_id}")

        # Notify via Sentry so any new registration is visible immediately
        sentry_sdk.capture_message(
            f"New user registered: {user_data.email} | org: {user_data.organisation_name}",
            level="warning",
        )

        # Create tokens
        tokens = create_tokens_for_user(user)

        logger.info("[REGISTER] Tokens created, building response")

        # Build response
        user_response = UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            job_title=user.job_title,
            is_active=user.is_active,
            is_verified=user.is_verified,
            role=user.role or "member",
            organisation_id=str(user.organisation_id) if user.organisation_id else None,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )

        org_response = None
        if user.organisation:
            org_response = {
                "id": str(user.organisation.id),
                "name": user.organisation.name,
                "slug": user.organisation.slug,
                "subscription_tier": user.organisation.subscription_tier
            }

        logger.info("[REGISTER] Registration successful")

        return Token(
            **tokens,
            user=user_response,
            organisation=org_response
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[REGISTER] Unhandled exception during registration: {type(e).__name__}: {e}")
        logger.error(f"[REGISTER] Full traceback:\n{traceback.format_exc()}")
        raise


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password (JSON body).
    Returns access and refresh tokens with organisation context.
    """
    user = await authenticate_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login timestamp
    user.last_login_at = datetime.utcnow()
    await db.commit()

    # Create tokens
    tokens = create_tokens_for_user(user)

    # Build response
    user_response = UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        is_active=user.is_active,
        is_verified=user.is_verified,
        role=user.role or "member",
        organisation_id=str(user.organisation_id) if user.organisation_id else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )

    org_response = None
    if user.organisation:
        org_response = {
            "id": str(user.organisation.id),
            "name": user.organisation.name,
            "slug": user.organisation.slug,
            "subscription_tier": user.organisation.subscription_tier
        }

    return Token(
        **tokens,
        user=user_response,
        organisation=org_response
    )


@router.post("/login/json", response_model=Token)
@limiter.limit("10/minute")
async def login_json(
    request: Request,
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """
    Login with JSON body (email and password).
    Alternative to form-based login for API clients.
    """
    user = await authenticate_user(db, credentials.email, credentials.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login timestamp
    user.last_login_at = datetime.utcnow()
    await db.commit()

    # Create tokens
    tokens = create_tokens_for_user(user)

    # Build response
    user_response = UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        is_active=user.is_active,
        is_verified=user.is_verified,
        role=user.role or "member",
        organisation_id=str(user.organisation_id) if user.organisation_id else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )

    org_response = None
    if user.organisation:
        org_response = {
            "id": str(user.organisation.id),
            "name": user.organisation.name,
            "slug": user.organisation.slug,
            "subscription_tier": user.organisation.subscription_tier
        }

    return Token(
        **tokens,
        user=user_response,
        organisation=org_response
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    token_data: TokenRefresh,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using a valid refresh token.
    """
    payload = security_decode_token(token_data.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    result = await db.execute(
        select(User)
        .options(selectinload(User.organisation))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = create_tokens_for_user(user)

    return TokenResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.get("/me", response_model=UserWithOrganisation)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current user info including organisation details.
    """
    response = UserWithOrganisation(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        job_title=current_user.job_title,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        role=current_user.role or "member",
        organisation_id=str(current_user.organisation_id) if current_user.organisation_id else None,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at,
    )

    if current_user.organisation:
        org_settings = current_user.organisation.settings or {}
        response.organisation = {
            "id": str(current_user.organisation.id),
            "name": current_user.organisation.name,
            "slug": current_user.organisation.slug,
            "subscription_tier": current_user.organisation.subscription_tier,
            "xero_connected": str(org_settings.get("onboarding_complete", "")).lower() == "true",
            "settings": org_settings,
        }

    return response


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user)
):
    """
    Logout current user.
    Note: With JWT, actual logout is handled client-side by deleting the token.
    """
    return {"message": "Successfully logged out"}


@router.patch("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Allows an authenticated user to change their password."""
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = get_password_hash(data.new_password)
    await db.commit()

    return {"message": "Password updated successfully"}


@router.post("/password-reset")
@limiter.limit("5/minute")
async def request_password_reset(
    request: Request,
    data: PasswordReset,
    db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset email.
    """
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user:
        reset_token = str(uuid.uuid4())
        user.password_reset_token = reset_token
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        user.updated_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(f"[AUTH] Sending reset email to {data.email} via asyncio.to_thread")
        email_sent = await asyncio.to_thread(
            send_password_reset_email,
            to_email=data.email,
            reset_token=reset_token,
        )
        logger.info(f"[AUTH] Email send result for {data.email}: {email_sent}")
        if not email_sent:
            logger.warning(
                f"[AUTH] Reset token generated but email failed "
                f"for {data.email}"
            )

    return {
        "message": "If an account with that email exists, a password reset link has been sent."
    }


@router.post("/password-reset/confirm")
@limiter.limit("5/minute")
async def confirm_password_reset(
    request: Request,
    data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db)
):
    """
    Confirm password reset with token.
    """
    result = await db.execute(
        select(User).where(User.password_reset_token == data.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    user.hashed_password = get_password_hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()

    return {"message": "Password has been reset successfully"}


# ---------------------------------------------------------------------------
# Simple diagnostic endpoints — raw SQL only, no ORM relationships
# ---------------------------------------------------------------------------

@router.post("/register-simple")
@limiter.limit("5/minute")
async def register_simple(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    Minimal registration using raw SQL inserts.
    Bypasses all ORM relationship loading to isolate DB connectivity issues.
    Body: {"email": "...", "password": "...", "full_name": "...", "organisation_name": "..."}
    """
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")
    full_name = payload.get("full_name", "")
    organisation_name = payload.get("organisation_name", "")

    if not all([email, password, full_name, organisation_name]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email, password, full_name, and organisation_name are all required"
        )

    # Allowlist check — same gate as the ORM register endpoint
    _check_registration_allowed(email)

    # Check for existing email with raw SQL
    check_result = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email}
    )
    if check_result.fetchone():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    hashed_pw = get_password_hash(password)

    import re
    slug_base = re.sub(r"[^a-z0-9]+", "-", organisation_name.lower()).strip("-")[:80]
    slug = f"{slug_base}-{org_id[:8]}"

    await db.execute(
        text(
            "INSERT INTO organisations "
            "(id, name, slug, subscription_tier, subscription_status, "
            " max_users, settings, is_active, created_at, updated_at) "
            "VALUES "
            "(:id, :name, :slug, 'essentials', 'trial', 3, '{}', true, now(), now())"
        ),
        {"id": org_id, "name": organisation_name, "slug": slug}
    )

    await db.execute(
        text(
            "INSERT INTO users "
            "(id, email, hashed_password, full_name, is_active, is_verified, "
            " role, organisation_id, created_at, updated_at) "
            "VALUES "
            "(:id, :email, :hashed_password, :full_name, true, false, "
            " 'owner', :organisation_id, now(), now())"
        ),
        {
            "id": user_id,
            "email": email,
            "hashed_password": hashed_pw,
            "full_name": full_name,
            "organisation_id": org_id,
        }
    )

    await db.commit()

    # Notify via Sentry so any new registration is visible immediately
    sentry_sdk.capture_message(
        f"New user registered (simple): {email} | org: {organisation_name}",
        level="warning",
    )

    logger.info(f"[REGISTER-SIMPLE] Created user={user_id} org={org_id} email={email}")
    return {"success": True, "email": email}


@router.post("/login-simple")
@limiter.limit("10/minute")
async def login_simple(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    Minimal login using raw SQL fetch + verify_password + JWT.
    Body: {"email": "...", "password": "..."}
    """
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email and password are required"
        )

    result = await db.execute(
        text(
            "SELECT id, email, hashed_password, full_name, is_active, role, organisation_id "
            "FROM users WHERE email = :email"
        ),
        {"email": email}
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    if not verify_password(password, row.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = {"sub": str(row.id), "email": row.email}
    if row.role:
        token_data["role"] = row.role
    if row.organisation_id:
        token_data["org_id"] = str(row.organisation_id)

    access_token = create_access_token(token_data)

    logger.info(f"[LOGIN-SIMPLE] Successful login for email={email}")
    return {"access_token": access_token, "token_type": "bearer"}