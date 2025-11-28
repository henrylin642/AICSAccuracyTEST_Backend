"""Pipeline for processing test items with timing metrics."""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from stt_client import transcribe_file
from chatbase_client import ask_chatbase
from llm_client import evaluate_answer_with_llm
from tts_generate import generate_tts_for_text
from text_utils import normalize_text
from constants import TAIWAN_ANIMALS
from config import get_default_language_code

LOGGER = logging.getLogger(__name__)

@dataclass
class PipelineResult:
    id: int
    question: str
    reference_answer: str
    
    # TTS
    audio_path: Optional[str] = None
    tts_latency: float = 0.0
    
    # STT
    stt_text: str = ""
    stt_latency: float = 0.0
    
    # Chatbase
    ai_answer: str = ""
    chatbase_latency: float = 0.0
    
    # Eval
    score: int = 0
    reason: str = ""
    eval_latency: float = 0.0
    
    # Overall
    total_latency: float = 0.0
    status: str = "pending"  # pending, success, error
    error_msg: Optional[str] = None

class ProcessingPipeline:
    def __init__(self, output_dir: str = "audio"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.language = get_default_language_code()

    def process_item(self, item_id: int, question: str, reference_answer: str, phrase_hints: Optional[list[str]] = None, stt_provider: str = "google", language_code: str = "zh-TW") -> PipelineResult:
        result = PipelineResult(id=item_id, question=question, reference_answer=reference_answer)
        start_total = time.perf_counter()
        
        try:
            # 1. TTS Generation
            import hashlib
            q_hash = hashlib.md5(question.encode("utf-8")).hexdigest()[:8]
            wav_filename = f"q{item_id}_{q_hash}.wav"
            wav_path = self.output_dir / wav_filename
            
            t0 = time.perf_counter()
            if not wav_path.exists():
                # Determine voice based on language if needed
                voice = None
                if language_code.lower().startswith("en"):
                    voice = "en-US-AvaNeural" # Default English voice
                
                generate_tts_for_text(
                    text=question,
                    filename=wav_filename,
                    outdir=str(self.output_dir),
                    language=language_code,
                    voice_name=voice,
                    speed=1.0
                )
            result.tts_latency = time.perf_counter() - t0
            
            # Upload to GCS if configured
            import os
            gcs_bucket = os.getenv("GCS_BUCKET_NAME")
            if gcs_bucket:
                try:
                    from gcs_client import GCSClient
                    gcs = GCSClient(gcs_bucket)
                    # Use a folder prefix in GCS
                    blob_name = f"audio/{wav_filename}"
                    public_url = gcs.upload_file(str(wav_path), blob_name)
                    result.audio_path = public_url # Use URL instead of local path
                except Exception as e:
                    LOGGER.error(f"GCS Upload failed: {e}")
                    result.audio_path = str(wav_path) # Fallback to local
            else:
                result.audio_path = str(wav_path)
            
            # 2. STT
            t0 = time.perf_counter()
            # Use provided hints or fallback to default
            hints = phrase_hints if phrase_hints is not None else TAIWAN_ANIMALS
            # For STT, we still use the local file because it's faster/easier than downloading from URL
            stt_raw = transcribe_file(str(wav_path), language_code=language_code, phrase_hints=hints, provider=stt_provider)
            result.stt_text = normalize_text(stt_raw)
            result.stt_latency = time.perf_counter() - t0
            
            # 3. Chatbase
            t0 = time.perf_counter()
            
            # Append language instruction based on environment
            if stt_provider == "openai":
                # English environment
                query_text = f"{result.stt_text};Please answer in the language: en-US"
            else:
                # Chinese environment (default)
                query_text = f"{result.stt_text} Please answer in the language: zh-TW"
                
            cb_resp = ask_chatbase(query_text)
            result.ai_answer = cb_resp["answer_text"]
            result.chatbase_latency = time.perf_counter() - t0
            
            # 4. Eval
            t0 = time.perf_counter()
            if reference_answer:
                eval_res = evaluate_answer_with_llm(question, reference_answer, result.ai_answer)
                result.score = eval_res["score"]
                result.reason = eval_res["reason"]
            else:
                result.reason = "No reference answer provided"
            result.eval_latency = time.perf_counter() - t0
            
            result.status = "success"
            
        except Exception as e:
            LOGGER.exception(f"Error processing item {item_id}")
            result.status = "error"
            result.error_msg = str(e)
            
        result.total_latency = time.perf_counter() - start_total
        return result
