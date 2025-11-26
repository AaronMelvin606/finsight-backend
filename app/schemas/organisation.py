"""
FinSight AI - Organisation Schemas
==================================
Pydantic models for organisation request/response validation.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum
import re


class SubscriptionTierEnum(str, Enum):
    """Subscription tier levels."""
    TRIAL = "trial"
    ESSENTIALS = "essentials"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SubscriptionStatusEnum(str, Enum):
    """Subscription status values."""
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class MemberRoleEnum(str, Enum):
    """Organisation member roles."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class OrganisationCreate(BaseModel):
    """Schema for creating an organisation."""
    name: str = Field(..., min_length=2, max_length=255)
    slug: Optional[str] = Field(None, max_length=100)
    industry: Optional[str] = Field(None, max_length=100)
    size: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=255)
    billing_email: Optional[EmailStr] = None
    
    @field_validator('slug')
    @classmethod
    def validate_slug(cls, v: Optional[str]) -> Optional[str]:
        """Validate slug format."""
        if v is None:
            return v
        if not re.match(r'^[a-z0-9-]+$', v):
            raise ValueError('Slug must contain only lowercase letters, numbers, and hyphens')
        return v


class OrganisationUpdate(BaseModel):
    """Schema for updating an organisation."""
    name: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    size: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=255)
    billing_email: Optional[EmailStr] = None
    billing_address: Optional[str] = None


class OrganisationResponse(BaseModel):
    """Schema for organisation response."""
    id: str
    name: str
    slug: str
    industry: Optional[str]
    size: Optional[str]
    website: Optional[str]
    subscription_tier: str
    subscription_status: str
    trial_ends_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class OrganisationDetailResponse(OrganisationResponse):
    """Schema for detailed organisation response (includes members)."""
    billing_email: Optional[str]
    member_count: int = 0
    data_source_count: int = 0


class MemberInvite(BaseModel):
    """Schema for inviting a member to an organisation."""
    email: EmailStr
    role: MemberRoleEnum = MemberRoleEnum.MEMBER


class MemberResponse(BaseModel):
    """Schema for member response."""
    id: str
    user_id: str
    email: str
    full_name: Optional[str]
    role: str
    joined_at: datetime
    
    class Config:
        from_attributes = True


class MemberRoleUpdate(BaseModel):
    """Schema for updating a member's role."""
    role: MemberRoleEnum


class SubscriptionInfo(BaseModel):
    """Schema for subscription information."""
    tier: SubscriptionTierEnum
    status: SubscriptionStatusEnum
    trial_ends_at: Optional[datetime]
    features: List[str]
    limits: dict


# Feature definitions per tier
TIER_FEATURES = {
    SubscriptionTierEnum.TRIAL: {
        "features": [
            "Basic Budget vs Actual Dashboard",
            "CSV Upload (single file)",
            "7-day access",
        ],
        "limits": {
            "users": 1,
            "data_sources": 1,
            "dashboards": 1,
            "records": 1000,
        }
    },
    SubscriptionTierEnum.ESSENTIALS: {
        "features": [
            "3-5 Core Dashboards",
            "Monthly Data Refresh",
            "CSV Upload",
            "1 ERP Integration",
            "Email Support (48hr)",
            "Streamlit Dashboards",
        ],
        "limits": {
            "users": 3,
            "data_sources": 2,
            "dashboards": 5,
            "records": 50000,
        }
    },
    SubscriptionTierEnum.PROFESSIONAL: {
        "features": [
            "8-12 Advanced Dashboards",
            "Weekly Data Refresh",
            "Up to 3 Integrations",
            "Scenario Planning",
            "AI-Powered Insights",
            "Tableau Dashboards",
            "Monthly Strategy Call",
            "Priority Email Support",
        ],
        "limits": {
            "users": 10,
            "data_sources": 5,
            "dashboards": 15,
            "records": 250000,
        }
    },
    SubscriptionTierEnum.ENTERPRISE: {
        "features": [
            "Unlimited Dashboards",
            "Real-time/Daily Refresh",
            "Unlimited Integrations",
            "Full Scenario Modelling",
            "Predictive Analytics",
            "Custom Dashboards",
            "Dedicated CSM",
            "Bi-weekly Strategy Calls",
            "White-glove Onboarding",
        ],
        "limits": {
            "users": -1,  # Unlimited
            "data_sources": -1,
            "dashboards": -1,
            "records": -1,
        }
    }
}
