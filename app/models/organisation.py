"""
FinSight AI - Organisation Model
================================
SQLAlchemy models for organisations (tenants) and memberships.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class SubscriptionTier(str, enum.Enum):
    """Subscription tier levels."""
    TRIAL = "trial"
    ESSENTIALS = "essentials"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, enum.Enum):
    """Subscription status values."""
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class MemberRole(str, enum.Enum):
    """Organisation member roles."""
    OWNER = "owner"      # Full access, can delete org
    ADMIN = "admin"      # Full access, cannot delete org
    MEMBER = "member"    # Standard access
    VIEWER = "viewer"    # Read-only access


class Organisation(Base):
    """
    Organisation model - represents a tenant/company in the system.
    
    Each organisation has its own data isolation (multi-tenancy).
    """
    __tablename__ = "organisations"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Organisation details
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    
    # Company information
    company_registration = Column(String(50), nullable=True)  # e.g., UK company number
    industry = Column(String(100), nullable=True)
    size = Column(String(50), nullable=True)  # e.g., "1-10", "11-50", "51-200"
    website = Column(String(255), nullable=True)
    
    # Billing contact
    billing_email = Column(String(255), nullable=True)
    billing_address = Column(Text, nullable=True)
    
    # Subscription
    subscription_tier = Column(
        String(50),
        default=SubscriptionTier.TRIAL.value,
        nullable=False
    )
    subscription_status = Column(
        String(50),
        default=SubscriptionStatus.TRIAL.value,
        nullable=False
    )
    trial_ends_at = Column(DateTime, nullable=True)
    
    # Stripe
    stripe_customer_id = Column(String(255), nullable=True, unique=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    members = relationship(
        "OrganisationMember",
        back_populates="organisation",
        cascade="all, delete-orphan"
    )
    data_sources = relationship(
        "DataSource",
        back_populates="organisation",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self):
        return f"<Organisation {self.name}>"


class OrganisationMember(Base):
    """
    Organisation membership - links users to organisations.
    
    A user can belong to multiple organisations with different roles.
    """
    __tablename__ = "organisation_members"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Foreign keys
    organisation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Role within organisation
    role = Column(
        String(50),
        default=MemberRole.MEMBER.value,
        nullable=False
    )
    
    # Invitation tracking
    invited_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )
    invitation_token = Column(String(255), nullable=True)
    invitation_accepted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    organisation = relationship("Organisation", back_populates="members")
    user = relationship("User", back_populates="organisation_memberships", foreign_keys=[user_id])
    invited_by = relationship("User", foreign_keys=[invited_by_id])
    
    def __repr__(self):
        return f"<OrganisationMember org={self.organisation_id} user={self.user_id}>"
