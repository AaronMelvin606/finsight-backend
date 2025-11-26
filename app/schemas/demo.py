"""
FinSight AI - Demo Access Schemas
=================================
Pydantic models for demo access request/response validation.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class DemoAccessRequest(BaseModel):
    """Schema for requesting demo access (email-gated)."""
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    job_title: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    company_size: Optional[str] = Field(None, max_length=50)
    annual_revenue: Optional[str] = Field(None, max_length=100)
    current_erp: Optional[str] = Field(None, max_length=100)
    message: Optional[str] = Field(None, max_length=1000)
    marketing_consent: bool = False
    
    # UTM tracking (optional, from URL params)
    utm_source: Optional[str] = Field(None, max_length=100)
    utm_medium: Optional[str] = Field(None, max_length=100)
    utm_campaign: Optional[str] = Field(None, max_length=100)
    referrer: Optional[str] = Field(None, max_length=500)


class DemoAccessResponse(BaseModel):
    """Schema for demo access response."""
    success: bool
    message: str
    access_token: str  # Token to access demo
    demo_url: str  # Full URL to the demo
    expires_at: Optional[datetime]


class DemoVerifyRequest(BaseModel):
    """Schema for verifying demo access token."""
    access_token: str


class DemoVerifyResponse(BaseModel):
    """Schema for demo verification response."""
    valid: bool
    email: Optional[str]
    demo_url: Optional[str]
    message: str


class ContactInquiryRequest(BaseModel):
    """Schema for contact form submission."""
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    inquiry_type: Optional[str] = Field(None, max_length=50)  # demo, pricing, support, partnership
    message: str = Field(..., min_length=10, max_length=2000)
    annual_revenue: Optional[str] = Field(None, max_length=100)


class ContactInquiryResponse(BaseModel):
    """Schema for contact form response."""
    success: bool
    message: str
    inquiry_id: str
