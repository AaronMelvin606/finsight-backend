"""
FinSight AI - Authentication Router
===================================
API endpoints for user authentication with organisation context.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import (
    get_password_hash,
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

import uuid


router = APIRouter()


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user and create their organisation.
    Returns access and refresh tokens with user and organisation info.
    """
    # Check if email already exists
    existing_user = await get_user_by_email(db, user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create user with organisation
    user = await create_user_with_organisation(db, user_data)

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


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password.
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
    user.last_login_at = datetime.now(timezone.utc)
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
async def login_json(
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
    user.last_login_at = datetime.now(timezone.utc)
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
    # Decode and validate refresh token
    payload = security_decode_token(token_data.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    # Verify user still exists and is active
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

    # Generate new tokens with org context
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
        response.organisation = {
            "id": str(current_user.organisation.id),
            "name": current_user.organisation.name,
            "slug": current_user.organisation.slug,
            "subscription_tier": current_user.organisation.subscription_tier,
            "settings": current_user.organisation.settings or {}
        }

    return response


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user)
):
    """
    Logout current user.
    Note: With JWT, actual logout is handled client-side by deleting the token.
    This endpoint can be used for logging/auditing purposes.
    """
    return {"message": "Successfully logged out"}


@router.post("/password-reset")
async def request_password_reset(
    data: PasswordReset,
    db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset email.

    Note: Email sending not implemented yet.
    For now, this just validates the email exists.
    """
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if user:
        # Generate reset token
        reset_token = str(uuid.uuid4())
        user.password_reset_token = reset_token
        user.password_reset_expires = datetime.now(timezone.utc)
        await db.commit()

        # TODO: Send email with reset link

    return {
        "message": "If an account with that email exists, a password reset link has been sent."
    }


@router.post("/password-reset/confirm")
async def confirm_password_reset(
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

    # Update password
    user.hashed_password = get_password_hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()

    return {"message": "Password has been reset successfully"}
