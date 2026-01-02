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
    UserWithOrganisation,
    TokenData,
    Token,
)

from app.schemas.organisation import (
    OrganisationCreate,
    OrganisationUpdate,
    OrganisationResponse,
    OrganisationDetailResponse,
    OrganisationWithStats,
    MemberInvite,
    MemberResponse,
    MemberRoleUpdate,
    SubscriptionInfo,
    SubscriptionTierEnum,
    SubscriptionStatusEnum,
    MemberRoleEnum,
    TIER_FEATURES,
)

from app.schemas.financial_data import (
    FinancialDataBase,
    FinancialDataCreate,
    FinancialDataUpdate,
    FinancialDataResponse,
    FinancialDataBulkCreate,
    UploadResponse,
    DataUploadStatus,
    DashboardSummary,
    MonthlyTrend,
    CategoryBreakdown,
    KPIMetricBase,
    KPIMetricCreate,
    KPIMetricResponse,
    KPIDashboard,
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
    "UserWithOrganisation",
    "TokenData",
    "Token",

    # Organisation
    "OrganisationCreate",
    "OrganisationUpdate",
    "OrganisationResponse",
    "OrganisationDetailResponse",
    "OrganisationWithStats",
    "MemberInvite",
    "MemberResponse",
    "MemberRoleUpdate",
    "SubscriptionInfo",
    "SubscriptionTierEnum",
    "SubscriptionStatusEnum",
    "MemberRoleEnum",
    "TIER_FEATURES",

    # Financial Data
    "FinancialDataBase",
    "FinancialDataCreate",
    "FinancialDataUpdate",
    "FinancialDataResponse",
    "FinancialDataBulkCreate",
    "UploadResponse",
    "DataUploadStatus",
    "DashboardSummary",
    "MonthlyTrend",
    "CategoryBreakdown",
    "KPIMetricBase",
    "KPIMetricCreate",
    "KPIMetricResponse",
    "KPIDashboard",

    # Demo
    "DemoAccessRequest",
    "DemoAccessResponse",
    "DemoVerifyRequest",
    "DemoVerifyResponse",
    "ContactInquiryRequest",
    "ContactInquiryResponse",
]
