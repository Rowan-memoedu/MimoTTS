"""Shared TTS routing. Original MiMo remains available through mimo_tts.client."""
from .router import synthesize, voices

__all__ = ["synthesize", "voices"]
