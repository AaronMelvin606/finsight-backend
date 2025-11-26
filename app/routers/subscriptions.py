"""
FinSight AI - Subscriptions Router
==================================
API endpoints for subscription management (Stripe integration).
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import stripe

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.models.organisation import Organisation, OrganisationMember, MemberRole
from app.schemas.organisation import (
    SubscriptionInfo,
    SubscriptionTierEnum,
    SubscriptionStatusEnum,
    TIER_FEATURES,
)


router = APIRouter()

# Initialise Stripe
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY


# Pricing configuration (move to config in production)
STRIPE_PRICES = {
    "essentials": settings.STRIPE_PRICE_ESSENTIALS,
    "professional": settings.STRIPE_PRICE_PROFESSIONAL,
    "enterprise": settings.STRIPE_PRICE_ENTERPRISE,
}

TIER_PRICES_GBP = {
    "essentials": 500,
    "professional": 1500,
    "enterprise": 3500,
}


@router.get("/plans")
async def list_subscription_plans():
    """
    List available subscription plans with pricing.
    """
    plans = []
    
    for tier, price in TIER_PRICES_GBP.items():
        tier_enum = SubscriptionTierEnum(tier)
        tier_info = TIER_FEATURES.get(tier_enum, {})
        
        plans.append({
            "tier": tier,
            "name": tier.title(),
            "price_monthly_gbp": price,
            "features": tier_info.get("features", []),
            "limits": tier_info.get("limits", {}),
            "stripe_price_id": STRIPE_PRICES.get(tier),
            "popular": tier == "professional",  # Mark Professional as popular
        })
    
    return {"plans": plans}


@router.post("/create-checkout-session")
async def create_checkout_session(
    tier: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe Checkout session for subscription.
    """
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured"
        )
    
    # Validate tier
    if tier not in STRIPE_PRICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier. Must be one of: {list(STRIPE_PRICES.keys())}"
        )
    
    stripe_price_id = STRIPE_PRICES.get(tier)
    if not stripe_price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stripe price not configured for tier: {tier}"
        )
    
    # Get user's organisation
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
        .where(OrganisationMember.role.in_([MemberRole.OWNER.value, MemberRole.ADMIN.value]))
        .limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be an organisation owner or admin to manage subscriptions"
        )
    
    # Get organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == membership.organisation_id)
    )
    org = org_result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    try:
        # Get or create Stripe customer
        if org.stripe_customer_id:
            customer_id = org.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=org.name,
                metadata={
                    "organisation_id": str(org.id),
                    "user_id": str(current_user.id),
                }
            )
            customer_id = customer.id
            org.stripe_customer_id = customer_id
            await db.commit()
        
        # Create Checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": stripe_price_id,
                    "quantity": 1,
                }
            ],
            mode="subscription",
            success_url=f"{settings.FRONTEND_URL}/dashboard?checkout=success",
            cancel_url=f"{settings.FRONTEND_URL}/pricing?checkout=cancelled",
            metadata={
                "organisation_id": str(org.id),
                "tier": tier,
            },
            subscription_data={
                "metadata": {
                    "organisation_id": str(org.id),
                    "tier": tier,
                }
            },
            allow_promotion_codes=True,
        )
        
        return {
            "checkout_url": checkout_session.url,
            "session_id": checkout_session.id,
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stripe error: {str(e)}"
        )


@router.post("/create-portal-session")
async def create_portal_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe Customer Portal session for managing subscription.
    """
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment processing is not configured"
        )
    
    # Get user's organisation
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
        .where(OrganisationMember.role.in_([MemberRole.OWNER.value, MemberRole.ADMIN.value]))
        .limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be an organisation owner or admin to manage subscriptions"
        )
    
    # Get organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == membership.organisation_id)
    )
    org = org_result.scalar_one_or_none()
    
    if not org or not org.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No subscription found. Please subscribe first."
        )
    
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=f"{settings.FRONTEND_URL}/dashboard/settings",
        )
        
        return {"portal_url": portal_session.url}
        
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stripe error: {str(e)}"
        )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Stripe webhook events.
    
    This endpoint receives events from Stripe (subscription created, updated, cancelled, etc.)
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not configured"
        )
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        await handle_checkout_completed(session, db)
    
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        await handle_subscription_updated(subscription, db)
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        await handle_subscription_deleted(subscription, db)
    
    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        await handle_payment_failed(invoice, db)
    
    return {"status": "success"}


async def handle_checkout_completed(session: dict, db: AsyncSession):
    """Handle successful checkout."""
    org_id = session.get("metadata", {}).get("organisation_id")
    tier = session.get("metadata", {}).get("tier")
    subscription_id = session.get("subscription")
    
    if not org_id or not tier:
        return
    
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if org:
        org.subscription_tier = tier
        org.subscription_status = "active"
        org.stripe_subscription_id = subscription_id
        org.trial_ends_at = None
        await db.commit()


async def handle_subscription_updated(subscription: dict, db: AsyncSession):
    """Handle subscription update (upgrade/downgrade)."""
    org_id = subscription.get("metadata", {}).get("organisation_id")
    tier = subscription.get("metadata", {}).get("tier")
    status = subscription.get("status")
    
    if not org_id:
        return
    
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if org:
        if tier:
            org.subscription_tier = tier
        org.subscription_status = status
        await db.commit()


async def handle_subscription_deleted(subscription: dict, db: AsyncSession):
    """Handle subscription cancellation."""
    org_id = subscription.get("metadata", {}).get("organisation_id")
    
    if not org_id:
        return
    
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if org:
        org.subscription_status = "cancelled"
        org.stripe_subscription_id = None
        await db.commit()


async def handle_payment_failed(invoice: dict, db: AsyncSession):
    """Handle failed payment."""
    customer_id = invoice.get("customer")
    
    if not customer_id:
        return
    
    result = await db.execute(
        select(Organisation).where(Organisation.stripe_customer_id == customer_id)
    )
    org = result.scalar_one_or_none()
    
    if org:
        org.subscription_status = "past_due"
        await db.commit()
