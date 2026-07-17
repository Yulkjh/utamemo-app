"""Lyria AI music generation client."""

from __future__ import annotations

import base64
import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import slugify

try:
    from google import genai
except ImportError:  # pragma: no cover - dependency is validated at runtime
    genai = None

logger = logging.getLogger(__name__)


class LyriaAIGenerator:
    """Lyria music generation wrapper built on the Google GenAI SDK."""

    def __init__(self):
        self.api_key = (getattr(settings, 'GEMINI_API_KEY', '') or '').strip()
        self.default_model = getattr(settings, 'LYRIA_MODEL', 'lyria-3-pro-preview')
        self.use_real_api = bool(self.api_key and genai)
        self.client = genai.Client(api_key=self.api_key) if self.use_real_api else None

        if self.use_real_api:
            logger.info("LyriaAIGenerator: Google GenAI client configured.")
        else:
            logger.info("LyriaAIGenerator: API key not set or google-genai is unavailable.")

    def generate_song(self, lyrics, title="", genre="pop", vocal_style="female", model="", music_prompt=""):
        """Generate a song with Lyria and save the output audio locally."""
        if not self.client:
            raise Exception(
                "Lyria API is not configured. Set GEMINI_API_KEY and install google-genai."
            )

        resolved_model = model or self.default_model
        prompt = self._build_prompt(title, genre, vocal_style, lyrics, music_prompt)

        logger.info("Sending request to Lyria via Google GenAI SDK")
        interaction = self.client.interactions.create(
            model=resolved_model,
            input=prompt,
        )

        audio_bytes, audio_mime_type = self._extract_audio_bytes(interaction)
        if not audio_bytes:
            raise Exception("Lyria response did not include audio output")

        audio_url = self._save_audio_file(audio_bytes, title, audio_mime_type)
        lyrics_text = self._extract_text_output(interaction) or lyrics

        return {
            'song_id': self._extract_song_id(interaction),
            'title': title or 'AI Generated Song',
            'artist': 'Lyria AI',
            'audio_url': audio_url,
            'duration': None,
            'cover_image': None,
            'lyrics': lyrics_text,
            'genre': genre,
            'status': 'completed',
            'api_provider': 'lyria',
            'provider_model': resolved_model,
            'raw_response': self._summarize_interaction(interaction),
        }

    def _build_prompt(self, title, genre, vocal_style, lyrics, music_prompt):
        parts = []
        if title:
            parts.append(f"Song title: {title}")
        if genre:
            parts.append(f"Genre: {genre}")
        if vocal_style:
            parts.append(f"Vocal style: {vocal_style}")
        if music_prompt:
            parts.append(f"Creative direction: {music_prompt}")
        if lyrics:
            parts.append(f"Lyrics:\n{lyrics}")
        parts.append(
            "Create a full song with a clear intro, verse, chorus, bridge, and outro. "
            "Keep the arrangement polished and coherent."
        )
        return "\n\n".join(parts)

    def _extract_audio_bytes(self, interaction):
        generated_audio = getattr(interaction, 'output_audio', None)
        audio_bytes, audio_mime_type = self._decode_audio_block(generated_audio)
        if audio_bytes:
            return audio_bytes, audio_mime_type

        for step in getattr(interaction, 'steps', []) or []:
            if getattr(step, 'type', None) != 'model_output':
                continue
            for content_block in getattr(step, 'content', []) or []:
                if getattr(content_block, 'type', None) == 'audio':
                    audio_bytes, audio_mime_type = self._decode_audio_block(content_block)
                    if audio_bytes:
                        return audio_bytes, audio_mime_type

        return None, None

    def _decode_audio_block(self, audio_block):
        if not audio_block:
            return None, None

        audio_data = getattr(audio_block, 'data', None)
        if not audio_data:
            return None, None

        if isinstance(audio_data, bytes):
            decoded = base64.b64decode(audio_data)
        else:
            decoded = base64.b64decode(str(audio_data))

        mime_type = getattr(audio_block, 'mime_type', None) or getattr(audio_block, 'mimeType', None)
        return decoded, mime_type

    def _extract_text_output(self, interaction):
        output_text = getattr(interaction, 'output_text', None)
        if output_text:
            if isinstance(output_text, list):
                return "\n".join(str(item).strip() for item in output_text if str(item).strip())
            return str(output_text).strip()

        collected = []
        for step in getattr(interaction, 'steps', []) or []:
            if getattr(step, 'type', None) != 'model_output':
                continue
            for content_block in getattr(step, 'content', []) or []:
                if getattr(content_block, 'type', None) == 'text':
                    text = getattr(content_block, 'text', '')
                    if text:
                        collected.append(str(text).strip())

        return "\n".join(part for part in collected if part)

    def _extract_song_id(self, interaction):
        return getattr(interaction, 'id', None) or getattr(interaction, 'name', None)

    def _save_audio_file(self, audio_bytes, title, mime_type=None):
        safe_title = slugify(title or 'lyria-song') or 'lyria-song'
        extension = 'wav' if mime_type and 'wav' in mime_type.lower() else 'mp3'
        filename = f"generated_audio/{safe_title}-{uuid.uuid4().hex[:12]}.{extension}"
        saved_name = default_storage.save(filename, ContentFile(audio_bytes))
        try:
            return default_storage.url(saved_name)
        except Exception:
            return f"/media/{saved_name}"

    def _summarize_interaction(self, interaction):
        return {
            'id': self._extract_song_id(interaction),
            'has_output_audio': bool(getattr(interaction, 'output_audio', None)),
            'has_output_text': bool(getattr(interaction, 'output_text', None)),
        }