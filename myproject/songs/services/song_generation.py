"""Provider-agnostic helpers for song generation services."""

from django.conf import settings

from .lyria import LyriaAIGenerator

SUPPORTED_SONG_PROVIDERS = ('lyria',)


def normalize_song_provider(provider):
    provider = (provider or '').strip().lower()
    if provider in SUPPORTED_SONG_PROVIDERS:
        return provider
    return 'lyria'


def get_default_song_generation_provider():
    configured = getattr(settings, 'DEFAULT_SONG_GENERATION_PROVIDER', 'lyria')
    return normalize_song_provider(configured)


def get_default_song_generation_model(provider=None):
    provider = normalize_song_provider(provider or get_default_song_generation_provider())
    return getattr(settings, 'LYRIA_MODEL', 'lyria-3-pro-preview')


def get_song_generator(provider=None):
    normalize_song_provider(provider or get_default_song_generation_provider())
    return LyriaAIGenerator()