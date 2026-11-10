"""Additive provider routing; the original MiMo client remains directly callable."""
import os
from pathlib import Path
from .client import MimoError, synthesize as mimo_synthesize, voices as mimo_voices

CONFIG = Path('D:/AppData/MimoTTS/provider.json')

def selected_provider():
    import json
    value = os.environ.get('TTS_PROVIDER')
    if not value and CONFIG.exists(): value = json.loads(CONFIG.read_text(encoding='utf-8-sig')).get('provider')
    value = value or 'mimo'
    if value not in ('openai', 'mimo'): raise MimoError('Unknown TTS provider.')
    return value

def openai_key():
    value = os.environ.get('OPENAI_API_KEY')
    if not value:
        p = Path(os.environ.get('OPENAI_ENV_FILE', 'D:/AppData/OpenAI/.env.local'))
        if p.exists():
            value = next((s.split('=', 1)[1].strip().strip('\"\'') for s in p.read_text(encoding='utf-8-sig').splitlines() if s.startswith('OPENAI_API_KEY=')), None)
    if not value: raise MimoError('OpenAI API credential is missing.')
    return value

def voices():
    if selected_provider() != 'openai': return mimo_voices()
    return [{'id': v, 'language': 'en', 'gender': 'female' if v == 'marin' else 'male'} for v in ('marin', 'cedar')]

def synthesize(text, out, *, provider=None, **kwargs):
    provider = provider or selected_provider()
    if provider == 'mimo': return mimo_synthesize(text, out, **kwargs)
    if provider != 'openai': raise MimoError('Unknown TTS provider.')
    from .openai_audio import synthesize as openai_synthesize
    try:
        return openai_synthesize(text, out, **kwargs)
    except MimoError:
        raise
    except Exception:
        raise MimoError('OpenAI audio transport or output processing failed.') from None
