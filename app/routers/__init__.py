"""
FinSight AI - API Routers
=========================
Export all routers.
"""

from app.routers import auth, users, organisations, subscriptions, dashboards, demo

__all__ = [
    "auth",
    "users",
    "organisations",
    "subscriptions",
    "dashboards",
    "demo",
]
