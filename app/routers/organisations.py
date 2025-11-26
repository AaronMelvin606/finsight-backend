"""
FinSight AI - Organisations Router
==================================
API endpoints for organisation management (multi-tenant).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.organisation import Organisation, OrganisationMember, MemberRole
from app.models.data_source import DataSource
from app.schemas.organisation import (
    OrganisationCreate,
    OrganisationUpdate,
    OrganisationResponse,
    OrganisationDetailResponse,
    MemberInvite,
    MemberResponse,
    MemberRoleUpdate,
    SubscriptionInfo,
    TIER_FEATURES,
    SubscriptionTierEnum,
    SubscriptionStatusEnum,
)

import uuid
import re


router = APIRouter()


def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return f"{slug}-{str(uuid.uuid4())[:8]}"


@router.get("/", response_model=List[OrganisationResponse])
async def list_my_organisations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all organisations the current user belongs to.
    """
    result = await db.execute(
        select(Organisation)
        .join(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
    )
    organisations = result.scalars().all()
    
    return [
        OrganisationResponse(
            id=str(org.id),
            name=org.name,
            slug=org.slug,
            industry=org.industry,
            size=org.size,
            website=org.website,
            subscription_tier=org.subscription_tier,
            subscription_status=org.subscription_status,
            trial_ends_at=org.trial_ends_at,
            created_at=org.created_at,
        )
        for org in organisations
    ]


@router.post("/", response_model=OrganisationResponse, status_code=status.HTTP_201_CREATED)
async def create_organisation(
    org_data: OrganisationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new organisation.
    
    The current user becomes the owner.
    """
    # Generate slug if not provided
    slug = org_data.slug or generate_slug(org_data.name)
    
    # Check if slug is unique
    result = await db.execute(select(Organisation).where(Organisation.slug == slug))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An organisation with this slug already exists"
        )
    
    # Create organisation
    new_org = Organisation(
        name=org_data.name,
        slug=slug,
        industry=org_data.industry,
        size=org_data.size,
        website=org_data.website,
        billing_email=org_data.billing_email or current_user.email,
        subscription_tier="trial",
        subscription_status="trial",
    )
    
    db.add(new_org)
    await db.flush()
    
    # Add current user as owner
    membership = OrganisationMember(
        organisation_id=new_org.id,
        user_id=current_user.id,
        role=MemberRole.OWNER.value,
    )
    
    db.add(membership)
    await db.commit()
    await db.refresh(new_org)
    
    return OrganisationResponse(
        id=str(new_org.id),
        name=new_org.name,
        slug=new_org.slug,
        industry=new_org.industry,
        size=new_org.size,
        website=new_org.website,
        subscription_tier=new_org.subscription_tier,
        subscription_status=new_org.subscription_status,
        trial_ends_at=new_org.trial_ends_at,
        created_at=new_org.created_at,
    )


@router.get("/{org_id}", response_model=OrganisationDetailResponse)
async def get_organisation(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get organisation details.
    
    User must be a member of the organisation.
    """
    # Verify user is a member
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.organisation_id == org_id)
        .where(OrganisationMember.user_id == current_user.id)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    # Get organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    # Get member count
    member_count_result = await db.execute(
        select(func.count(OrganisationMember.id))
        .where(OrganisationMember.organisation_id == org_id)
    )
    member_count = member_count_result.scalar()
    
    # Get data source count
    ds_count_result = await db.execute(
        select(func.count(DataSource.id))
        .where(DataSource.organisation_id == org_id)
    )
    data_source_count = ds_count_result.scalar()
    
    return OrganisationDetailResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        industry=org.industry,
        size=org.size,
        website=org.website,
        subscription_tier=org.subscription_tier,
        subscription_status=org.subscription_status,
        trial_ends_at=org.trial_ends_at,
        created_at=org.created_at,
        billing_email=org.billing_email,
        member_count=member_count,
        data_source_count=data_source_count,
    )


@router.patch("/{org_id}", response_model=OrganisationResponse)
async def update_organisation(
    org_id: str,
    updates: OrganisationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update organisation details.
    
    Only admins and owners can update.
    """
    # Verify user is admin or owner
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.organisation_id == org_id)
        .where(OrganisationMember.user_id == current_user.id)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership or membership.role not in [MemberRole.OWNER.value, MemberRole.ADMIN.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this organisation"
        )
    
    # Get organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    # Apply updates
    if updates.name is not None:
        org.name = updates.name
    if updates.industry is not None:
        org.industry = updates.industry
    if updates.size is not None:
        org.size = updates.size
    if updates.website is not None:
        org.website = updates.website
    if updates.billing_email is not None:
        org.billing_email = updates.billing_email
    if updates.billing_address is not None:
        org.billing_address = updates.billing_address
    
    await db.commit()
    await db.refresh(org)
    
    return OrganisationResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        industry=org.industry,
        size=org.size,
        website=org.website,
        subscription_tier=org.subscription_tier,
        subscription_status=org.subscription_status,
        trial_ends_at=org.trial_ends_at,
        created_at=org.created_at,
    )


@router.get("/{org_id}/members", response_model=List[MemberResponse])
async def list_organisation_members(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all members of an organisation.
    """
    # Verify user is a member
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.organisation_id == org_id)
        .where(OrganisationMember.user_id == current_user.id)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    # Get all members with user info
    members_result = await db.execute(
        select(OrganisationMember, User)
        .join(User, OrganisationMember.user_id == User.id)
        .where(OrganisationMember.organisation_id == org_id)
    )
    members = members_result.all()
    
    return [
        MemberResponse(
            id=str(m.OrganisationMember.id),
            user_id=str(m.User.id),
            email=m.User.email,
            full_name=m.User.full_name,
            role=m.OrganisationMember.role,
            joined_at=m.OrganisationMember.joined_at,
        )
        for m in members
    ]


@router.get("/{org_id}/subscription", response_model=SubscriptionInfo)
async def get_subscription_info(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get subscription information for an organisation.
    """
    # Verify user is a member
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.organisation_id == org_id)
        .where(OrganisationMember.user_id == current_user.id)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    # Get organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    # Get tier features
    tier = SubscriptionTierEnum(org.subscription_tier)
    tier_info = TIER_FEATURES.get(tier, TIER_FEATURES[SubscriptionTierEnum.TRIAL])
    
    return SubscriptionInfo(
        tier=tier,
        status=SubscriptionStatusEnum(org.subscription_status),
        trial_ends_at=org.trial_ends_at,
        features=tier_info["features"],
        limits=tier_info["limits"],
    )
