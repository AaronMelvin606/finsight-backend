"""
FinSight AI - Demo Access Model
===============================
SQLAlchemy model for demo access requests (email-gated demo).
"""

import uuid
from datetime import datetime, timedelta
from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class DemoAccess(Base):
    """
    Demo access model - tracks users who have requested demo access.
    
    This implements the email-gated demo requirement.
    Users must submit their email to view the demo dashboard.
    """
    __tablename__ = "demo_access"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Contact information
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    job_title = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    
    # Lead qualification
    company_size = Column(String(50), nullable=True)  # e.g., "1-10", "11-50"
    annual_revenue = Column(String(100), nullable=True)  # e.g., "£2M-£10M"
    current_erp = Column(String(100), nullable=True)  # e.g., "Xero", "NetSuite"
    
    # Interest/Message
    message = Column(Text, nullable=True)
    
    # Access token (for demo URL)
    access_token = Column(String(255), unique=True, index=True, nullable=False)
    
    # Access tracking
    demo_viewed = Column(Boolean, default=False)
    demo_viewed_at = Column(DateTime, nullable=True)
    demo_view_count = Column(String(10), default="0")
    
    # Token expiry (optional - demo access for 7 days)
    expires_at = Column(DateTime, nullable=True)
    
    # Marketing consent
    marketing_consent = Column(Boolean, default=False)
    
    # Source tracking
    utm_source = Column(String(100), nullable=True)
    utm_medium = Column(String(100), nullable=True)
    utm_campaign = Column(String(100), nullable=True)
    referrer = Column(String(500), nullable=True)
    
    # Conversion tracking
    converted_to_trial = Column(Boolean, default=False)
    converted_at = Column(DateTime, nullable=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # Link if they sign up
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def is_expired(self) -> bool:
        """Check if demo access has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def __repr__(self):
        return f"<DemoAccess {self.email}>"


class ContactInquiry(Base):
    """
    Contact inquiry model - stores contact form submissions.
    
    For the Contact Us page (separate from demo access).
    """
    __tablename__ = "contact_inquiries"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Contact information
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    
    # Inquiry details
    inquiry_type = Column(String(50), nullable=True)  # demo, pricing, support, partnership
    message = Column(Text, nullable=False)
    
    # Lead qualification
    annual_revenue = Column(String(100), nullable=True)
    
    # Status tracking
    status = Column(String(50), default="new")  # new, contacted, qualified, converted, closed
    assigned_to = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Response tracking
    responded_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ContactInquiry {self.email}>"
