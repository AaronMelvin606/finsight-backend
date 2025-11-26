"""
FinSight AI - Pydantic Schemas
==============================
Export all schemas.
"""

from app.schemas.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    TokenRefresh,
    PasswordReset,
    PasswordResetConfirm,
    PasswordChange,
    UserResponse,
    UserUpdate,
)

from app.schemas.organisation import (
    OrganisationCreate,
    OrganisationUpdate,
    OrganisationResponse,
    OrganisationDetailResponse,
    MemberInvite,
    MemberResponse,
    MemberRoleUpdate,
    SubscriptionInfo,
    SubscriptionTierEnum,
    SubscriptionStatusEnum,
    MemberRoleEnum,
    TIER_FEATURES,
)

from app.schemas.demo import (
    DemoAccessRequest,
    DemoAccessResponse,
    DemoVerifyRequest,
    DemoVerifyResponse,
    ContactInquiryRequest,
    ContactInquiryResponse,
)


__all__ = [
    # Auth
    "UserRegister",
    "UserLogin",
    "TokenResponse",
    "TokenRefresh",
    "PasswordReset",
    "PasswordResetConfirm",
    "PasswordChange",
    "UserResponse",
    "UserUpdate",
    
    # Organisation
    "OrganisationCreate",
    "OrganisationUpdate",
    "OrganisationResponse",
    "OrganisationDetailResponse",
    "MemberInvite",
    "MemberResponse",
    "MemberRoleUpdate",
    "SubscriptionInfo",
    "SubscriptionTierEnum",
    "SubscriptionStatusEnum",
    "MemberRoleEnum",
    "TIER_FEATURES",
    
    # Demo
    "DemoAccessRequest",
    "DemoAccessResponse",
    "DemoVerifyRequest",
    "DemoVerifyResponse",
    "ContactInquiryRequest",
    "ContactInquiryResponse",
]
