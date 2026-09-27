"""Reusable MiMo client. Credentials are resolved only when a request is made."""
from .client import synthesize, voices

__all__ = ["synthesize", "voices"]
