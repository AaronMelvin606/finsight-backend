"""
Entry point for Google Cloud Run buildpack.
Imports the FastAPI app from the app package.
"""
from app.main import app

# This allows the buildpack to find the app
__all__ = ["app"]
