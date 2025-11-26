"""
FinSight AI - Dashboards Router
===============================
API endpoints for dashboard access based on subscription tier.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.core.database import get_db
from app.core.security import get_current_user, require_subscription_tier
from app.models.user import User
from app.models.organisation import Organisation, OrganisationMember
from app.schemas.organisation import SubscriptionTierEnum, TIER_FEATURES


router = APIRouter()


# Dashboard definitions with tier requirements
DASHBOARDS = {
    # Essentials tier dashboards (Streamlit)
    "budget-vs-actual": {
        "id": "budget-vs-actual",
        "name": "Budget vs Actual",
        "description": "Compare actual performance against budget with variance analysis",
        "tier_required": "essentials",
        "type": "streamlit",
        "category": "core",
    },
    "cash-flow": {
        "id": "cash-flow",
        "name": "Cash Flow Analysis",
        "description": "13-week rolling cash flow forecast and analysis",
        "tier_required": "essentials",
        "type": "streamlit",
        "category": "core",
    },
    "pl-analysis": {
        "id": "pl-analysis",
        "name": "P&L Analysis",
        "description": "Profit & Loss breakdown with trend analysis",
        "tier_required": "essentials",
        "type": "streamlit",
        "category": "core",
    },
    "kpi-overview": {
        "id": "kpi-overview",
        "name": "KPI Dashboard",
        "description": "Key performance indicators at a glance",
        "tier_required": "essentials",
        "type": "streamlit",
        "category": "core",
    },
    "variance-analysis": {
        "id": "variance-analysis",
        "name": "Variance Analysis",
        "description": "Detailed variance breakdown by department and account",
        "tier_required": "essentials",
        "type": "streamlit",
        "category": "core",
    },
    
    # Professional tier dashboards (Tableau)
    "scenario-planning": {
        "id": "scenario-planning",
        "name": "Scenario Planning",
        "description": "What-if analysis with multiple scenarios",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    "rolling-forecast": {
        "id": "rolling-forecast",
        "name": "Rolling Forecast",
        "description": "18-month rolling forecast with AI predictions",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    "department-analysis": {
        "id": "department-analysis",
        "name": "Department Analysis",
        "description": "Deep dive into department-level performance",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    "executive-summary": {
        "id": "executive-summary",
        "name": "Executive Summary",
        "description": "Board-ready executive financial summary",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    "cost-centre-analysis": {
        "id": "cost-centre-analysis",
        "name": "Cost Centre Analysis",
        "description": "Detailed cost centre performance tracking",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    "revenue-analysis": {
        "id": "revenue-analysis",
        "name": "Revenue Analysis",
        "description": "Revenue breakdown by product, region, and customer",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    "working-capital": {
        "id": "working-capital",
        "name": "Working Capital",
        "description": "Working capital analysis and optimisation",
        "tier_required": "professional",
        "type": "tableau",
        "category": "advanced",
    },
    
    # Enterprise tier dashboards
    "predictive-analytics": {
        "id": "predictive-analytics",
        "name": "Predictive Analytics",
        "description": "ML-powered financial predictions and anomaly detection",
        "tier_required": "enterprise",
        "type": "tableau",
        "category": "enterprise",
    },
    "multi-entity": {
        "id": "multi-entity",
        "name": "Multi-Entity Consolidation",
        "description": "Consolidated view across multiple entities",
        "tier_required": "enterprise",
        "type": "tableau",
        "category": "enterprise",
    },
    "custom-reports": {
        "id": "custom-reports",
        "name": "Custom Reports",
        "description": "Fully customisable reporting templates",
        "tier_required": "enterprise",
        "type": "tableau",
        "category": "enterprise",
    },
    "audit-trail": {
        "id": "audit-trail",
        "name": "Audit Trail",
        "description": "Complete audit trail and compliance reporting",
        "tier_required": "enterprise",
        "type": "streamlit",
        "category": "enterprise",
    },
}


# Tier hierarchy for access control
TIER_HIERARCHY = {
    "trial": 0,
    "essentials": 1,
    "professional": 2,
    "enterprise": 3,
}


def can_access_dashboard(user_tier: str, required_tier: str) -> bool:
    """Check if user's tier can access a dashboard."""
    user_level = TIER_HIERARCHY.get(user_tier, 0)
    required_level = TIER_HIERARCHY.get(required_tier, 0)
    return user_level >= required_level


@router.get("/available")
async def list_available_dashboards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all dashboards available to the current user based on their subscription tier.
    """
    # Get user's organisation and subscription tier
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
        .limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organisation"
        )
    
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == membership.organisation_id)
    )
    org = org_result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found"
        )
    
    user_tier = org.subscription_tier
    
    # Categorise dashboards
    available = []
    locked = []
    
    for dashboard_id, dashboard in DASHBOARDS.items():
        dashboard_info = {
            **dashboard,
            "accessible": can_access_dashboard(user_tier, dashboard["tier_required"]),
        }
        
        if dashboard_info["accessible"]:
            available.append(dashboard_info)
        else:
            locked.append(dashboard_info)
    
    return {
        "current_tier": user_tier,
        "available_dashboards": available,
        "locked_dashboards": locked,
        "total_available": len(available),
        "total_locked": len(locked),
    }


@router.get("/{dashboard_id}")
async def get_dashboard_info(
    dashboard_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get information about a specific dashboard.
    """
    if dashboard_id not in DASHBOARDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard not found"
        )
    
    dashboard = DASHBOARDS[dashboard_id]
    
    # Get user's organisation and subscription tier
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
        .limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organisation"
        )
    
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == membership.organisation_id)
    )
    org = org_result.scalar_one_or_none()
    
    user_tier = org.subscription_tier if org else "trial"
    accessible = can_access_dashboard(user_tier, dashboard["tier_required"])
    
    return {
        **dashboard,
        "accessible": accessible,
        "current_tier": user_tier,
        "upgrade_required": None if accessible else dashboard["tier_required"],
    }


@router.get("/{dashboard_id}/access")
async def get_dashboard_access(
    dashboard_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get access URL for a specific dashboard.
    
    Returns the Streamlit or Tableau URL based on the dashboard type.
    """
    if dashboard_id not in DASHBOARDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard not found"
        )
    
    dashboard = DASHBOARDS[dashboard_id]
    
    # Get user's organisation and subscription tier
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
        .limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organisation"
        )
    
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == membership.organisation_id)
    )
    org = org_result.scalar_one_or_none()
    
    user_tier = org.subscription_tier if org else "trial"
    
    # Check access
    if not can_access_dashboard(user_tier, dashboard["tier_required"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This dashboard requires {dashboard['tier_required']} subscription or higher. "
                   f"Your current tier: {user_tier}"
        )
    
    # Generate access URL based on dashboard type
    # In production, these would be real Streamlit/Tableau URLs
    if dashboard["type"] == "streamlit":
        # Streamlit Cloud or self-hosted URL
        base_url = "https://finsightai.streamlit.app"  # Update with your Streamlit URL
        access_url = f"{base_url}/{dashboard_id}?org={org.id}&user={current_user.id}"
    else:
        # Tableau URL
        base_url = "https://tableau.finsightai.tech"  # Update with your Tableau URL
        access_url = f"{base_url}/views/{dashboard_id}?org={org.id}"
    
    return {
        "dashboard_id": dashboard_id,
        "dashboard_name": dashboard["name"],
        "type": dashboard["type"],
        "access_url": access_url,
        "organisation_id": str(org.id),
    }


@router.get("/categories/overview")
async def get_dashboard_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get dashboards organised by category.
    """
    # Get user's subscription tier
    membership_result = await db.execute(
        select(OrganisationMember)
        .where(OrganisationMember.user_id == current_user.id)
        .limit(1)
    )
    membership = membership_result.scalar_one_or_none()
    
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == membership.organisation_id)
    ) if membership else None
    org = org_result.scalar_one_or_none() if org_result else None
    
    user_tier = org.subscription_tier if org else "trial"
    
    # Organise by category
    categories = {
        "core": {"name": "Core Dashboards", "description": "Essential FP&A dashboards", "dashboards": []},
        "advanced": {"name": "Advanced Analytics", "description": "Professional-tier analytics", "dashboards": []},
        "enterprise": {"name": "Enterprise Features", "description": "Full platform capabilities", "dashboards": []},
    }
    
    for dashboard_id, dashboard in DASHBOARDS.items():
        category = dashboard.get("category", "core")
        dashboard_info = {
            **dashboard,
            "accessible": can_access_dashboard(user_tier, dashboard["tier_required"]),
        }
        categories[category]["dashboards"].append(dashboard_info)
    
    return {
        "current_tier": user_tier,
        "categories": categories,
    }
