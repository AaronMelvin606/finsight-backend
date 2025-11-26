"""
FinSight AI - Demo Access Router
================================
API endpoints for email-gated demo access.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
import uuid
import secrets

from app.core.database import get_db
from app.core.config import settings
from app.models.demo import DemoAccess, ContactInquiry
from app.schemas.demo import (
    DemoAccessRequest,
    DemoAccessResponse,
    DemoVerifyRequest,
    DemoVerifyResponse,
    ContactInquiryRequest,
    ContactInquiryResponse,
)


router = APIRouter()


def generate_access_token() -> str:
    """Generate a secure random access token."""
    return secrets.token_urlsafe(32)


@router.post("/request-access", response_model=DemoAccessResponse)
async def request_demo_access(
    data: DemoAccessRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Request access to the demo dashboard.
    
    This is the email-gated demo signup endpoint.
    Users must provide their email to access the demo.
    """
    # Check if email already has access
    result = await db.execute(
        select(DemoAccess).where(DemoAccess.email == data.email)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Return existing access if not expired
        if not existing.is_expired:
            demo_url = f"{settings.FRONTEND_URL}/demo?token={existing.access_token}"
            return DemoAccessResponse(
                success=True,
                message="You already have demo access. Check your email for the link.",
                access_token=existing.access_token,
                demo_url=demo_url,
                expires_at=existing.expires_at,
            )
        else:
            # Refresh expired access
            existing.access_token = generate_access_token()
            existing.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            existing.demo_viewed = False
            await db.commit()
            
            demo_url = f"{settings.FRONTEND_URL}/demo?token={existing.access_token}"
            return DemoAccessResponse(
                success=True,
                message="Your demo access has been refreshed.",
                access_token=existing.access_token,
                demo_url=demo_url,
                expires_at=existing.expires_at,
            )
    
    # Create new demo access
    access_token = generate_access_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)  # 7 day access
    
    new_access = DemoAccess(
        email=data.email,
        full_name=data.full_name,
        company_name=data.company_name,
        job_title=data.job_title,
        phone=data.phone,
        company_size=data.company_size,
        annual_revenue=data.annual_revenue,
        current_erp=data.current_erp,
        message=data.message,
        access_token=access_token,
        expires_at=expires_at,
        marketing_consent=data.marketing_consent,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        referrer=data.referrer,
    )
    
    db.add(new_access)
    await db.commit()
    
    # Build demo URL
    demo_url = f"{settings.FRONTEND_URL}/demo?token={access_token}"
    
    # TODO: Send confirmation email with demo link
    # For now, we just return the access token
    
    return DemoAccessResponse(
        success=True,
        message="Demo access granted! You can now view the demo.",
        access_token=access_token,
        demo_url=demo_url,
        expires_at=expires_at,
    )


@router.post("/verify-access", response_model=DemoVerifyResponse)
async def verify_demo_access(
    data: DemoVerifyRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Verify a demo access token.
    
    Called by the frontend to check if a token is valid before showing the demo.
    """
    result = await db.execute(
        select(DemoAccess).where(DemoAccess.access_token == data.access_token)
    )
    access = result.scalar_one_or_none()
    
    if not access:
        return DemoVerifyResponse(
            valid=False,
            email=None,
            demo_url=None,
            message="Invalid access token. Please request demo access again."
        )
    
    if access.is_expired:
        return DemoVerifyResponse(
            valid=False,
            email=access.email,
            demo_url=None,
            message="Your demo access has expired. Please request access again."
        )
    
    # Mark as viewed
    if not access.demo_viewed:
        access.demo_viewed = True
        access.demo_viewed_at = datetime.now(timezone.utc)
    
    # Increment view count
    current_count = int(access.demo_view_count or "0")
    access.demo_view_count = str(current_count + 1)
    
    await db.commit()
    
    # Get the actual demo dashboard URL (Streamlit)
    demo_dashboard_url = settings.DEMO_DASHBOARD_URL or f"{settings.FRONTEND_URL}/demo-dashboard"
    
    return DemoVerifyResponse(
        valid=True,
        email=access.email,
        demo_url=demo_dashboard_url,
        message="Access verified. Welcome to the demo!"
    )


@router.get("/stats")
async def get_demo_stats(db: AsyncSession = Depends(get_db)):
    """
    Get demo access statistics.
    
    Admin endpoint - should be protected in production.
    """
    from sqlalchemy import func
    
    # Total signups
    total_result = await db.execute(select(func.count(DemoAccess.id)))
    total_signups = total_result.scalar()
    
    # Viewed demo
    viewed_result = await db.execute(
        select(func.count(DemoAccess.id))
        .where(DemoAccess.demo_viewed == True)
    )
    viewed_count = viewed_result.scalar()
    
    # Converted to trial
    converted_result = await db.execute(
        select(func.count(DemoAccess.id))
        .where(DemoAccess.converted_to_trial == True)
    )
    converted_count = converted_result.scalar()
    
    # Signups today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(func.count(DemoAccess.id))
        .where(DemoAccess.created_at >= today_start)
    )
    today_signups = today_result.scalar()
    
    return {
        "total_signups": total_signups,
        "demo_viewed": viewed_count,
        "converted_to_trial": converted_count,
        "signups_today": today_signups,
        "view_rate": f"{(viewed_count / total_signups * 100) if total_signups > 0 else 0:.1f}%",
        "conversion_rate": f"{(converted_count / total_signups * 100) if total_signups > 0 else 0:.1f}%",
    }


@router.post("/contact", response_model=ContactInquiryResponse)
async def submit_contact_inquiry(
    data: ContactInquiryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Submit a contact form inquiry.
    
    This is for the Contact Us page (separate from demo access).
    """
    new_inquiry = ContactInquiry(
        email=data.email,
        full_name=data.full_name,
        company_name=data.company_name,
        phone=data.phone,
        inquiry_type=data.inquiry_type,
        message=data.message,
        annual_revenue=data.annual_revenue,
        status="new",
    )
    
    db.add(new_inquiry)
    await db.commit()
    await db.refresh(new_inquiry)
    
    # TODO: Send notification email to hello@finsightai.tech
    # TODO: Send confirmation email to the user
    
    return ContactInquiryResponse(
        success=True,
        message="Thank you for your inquiry. We'll be in touch within 24 hours.",
        inquiry_id=str(new_inquiry.id),
    )
