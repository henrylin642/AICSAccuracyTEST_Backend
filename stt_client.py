"""Google Cloud Speech-to-Text helper functions."""
from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Iterable, Sequence

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import speech

from config import get_default_language_code, get_gcp_config

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# Ensure configuration is validated on import for early failure.
get_gcp_config()


def _detect_sample_rate(path: Path) -> int:
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.getframerate()


from gcs_client import get_gcs_credentials

def _build_speech_client() -> speech.SpeechClient:
    creds = get_gcs_credentials()
    if creds:
        return speech.SpeechClient(credentials=creds)
    return speech.SpeechClient()


from openai import OpenAI
from config import get_openai_config

def _build_openai_client() -> OpenAI:
    config = get_openai_config()
    return OpenAI(api_key=config.api_key)

def transcribe_file_openai(wav_path: str, language_code: str | None = None) -> str:
    """Transcribe a WAV file using OpenAI Whisper."""
    client = _build_openai_client()
    path = Path(wav_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {wav_path}")
        
    LOGGER.info("Transcribing %s with OpenAI Whisper (language=%s)", wav_path, language_code)
    
    with path.open("rb") as audio_file:
        # Map Google language codes to Whisper ISO-639-1 if needed, 
        # but Whisper handles "en", "zh" etc. well. 
        # "en-US" -> "en", "zh-TW" -> "zh" might be safer.
        iso_lang = "en" if language_code and "en" in language_code.lower() else "zh"
        
        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            language=iso_lang
        )
        
    return transcript.text

def transcribe_file(
    wav_path: str,
    language_code: str | None = None,
    phrase_hints: Sequence[str] | None = None,
    provider: str = "google",
) -> str:
    """Transcribe a WAV file using the specified provider.
    
    Args:
        wav_path: Path to the WAV/LINEAR16 audio file.
        language_code: Optional language code. Defaults to DEFAULT_LANGUAGE_CODE.
        phrase_hints: Optional phrase hints to boost accuracy (Google only).
        provider: 'google' or 'openai'. Defaults to 'google'.
    """
    if provider == "openai":
        return transcribe_file_openai(wav_path, language_code)
        
    # Default to Google
    path = Path(wav_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {wav_path}")

    language = language_code or get_default_language_code()
    sample_rate_hz = _detect_sample_rate(path)

    LOGGER.info("Transcribing %s (sample_rate=%s, language=%s)", wav_path, sample_rate_hz, language)

    client = _build_speech_client()

    audio = speech.RecognitionAudio(content=path.read_bytes())

    speech_contexts: Iterable[speech.SpeechContext] | None = None
    if phrase_hints:
        speech_contexts = [speech.SpeechContext(phrases=list(phrase_hints))]

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate_hz,
        language_code=language,
        enable_automatic_punctuation=True,
        speech_contexts=speech_contexts,
    )

    try:
        response = client.recognize(config=config, audio=audio)
    except GoogleAPICallError as exc:
        raise RuntimeError(f"Google STT API call failed for {wav_path}: {exc}") from exc

    if not response.results:
        raise RuntimeError(f"No transcription results returned for {wav_path}.")

    top_result = response.results[0]
    if not top_result.alternatives:
        raise RuntimeError(f"STT result had no alternatives for {wav_path}.")

    transcript = top_result.alternatives[0].transcript.strip()
    if not transcript:
        raise RuntimeError(f"Empty transcript returned for {wav_path}.")

    return transcript


__all__ = ["transcribe_file", "transcribe_file_openai"]
