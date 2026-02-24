"""
FinSight AI - User Model
========================
SQLAlchemy model for users.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """
    User model for authentication and profile information.
    
    Users can belong to multiple organisations through OrganisationMember.
    """
    __tablename__ = "users"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    
    # Authentication
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # Profile
    full_name = Column(String(255), nullable=True)
    job_title = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)  # Email verification
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    
    # Password reset
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires = Column(DateTime, nullable=True)
    
    # Email verification
    verification_token = Column(String(255), nullable=True)

    # Multi-tenancy fields
    organisation_id = Column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=True)
    role = Column(String(50), default="member")  # owner, admin, member, viewer

    # Relationships
    organisation = relationship("Organisation", back_populates="users", foreign_keys=[organisation_id])
    organisation_memberships = relationship(
        "OrganisationMember",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="OrganisationMember.user_id"
    )
    
    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def is_org_owner(self):
        return self.role == "owner"

    @property
    def is_org_admin(self):
        return self.role in ["owner", "admin"]

    @property
    def can_upload_data(self):
        return self.role in ["owner", "admin", "member"]

    @property
    def can_view_data(self):
        return self.role in ["owner", "admin", "member", "viewer"]
