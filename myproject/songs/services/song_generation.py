"""Provider-agnostic helpers for song generation services."""

from django.conf import settings

from .lyria import LyriaAIGenerator
from .mureka import MurekaAIGenerator

SUPPORTED_SONG_PROVIDERS = ('mureka', 'lyria')


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
    if provider == 'lyria':
        return getattr(settings, 'LYRIA_MODEL', 'lyria-3-pro-preview')
    return getattr(settings, 'MUREKA_DEFAULT_MODEL', 'mureka-v8')


def get_song_generator(provider=None):
    provider = normalize_song_provider(provider or get_default_song_generation_provider())
    if provider == 'lyria':
        return LyriaAIGenerator()
    return MurekaAIGenerator()