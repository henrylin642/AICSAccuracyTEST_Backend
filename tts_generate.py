"""CLI sample: python tts_generate.py --input zoo_dataset.csv --outdir audio --language zh-TW"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import Any, List

import pandas as pd

from config import get_azure_config, get_default_language_code


COLUMN_ALIASES = {
    "id": ["id", "編號"],
    "question": ["zh_question", "中文問題", "Q-ch", "Q_CH", "Q_ch", "QCH"],
    "Ans-ch": ["Ans-ch", "中文回答", "Answer-ch", "A-ch"],
}


def _get_speech_sdk():
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:  # pragma: no cover - import time guard
        raise RuntimeError(
            "azure-cognitiveservices-speech is required. Please install dependencies."
        ) from exc
    return speechsdk


def _build_speech_config(language: str | None, voice: str | None):
    speechsdk = _get_speech_sdk()
    azure_cfg = get_azure_config()
    resolved_language = language or get_default_language_code()
    resolved_voice = voice or azure_cfg.voice
    speech_config = speechsdk.SpeechConfig(
        subscription=azure_cfg.key,
        region=azure_cfg.region,
    )
    speech_config.speech_synthesis_language = resolved_language
    speech_config.speech_synthesis_voice_name = resolved_voice
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
    )
    return speechsdk, speech_config, resolved_language, resolved_voice


def _synthesize_to_file(
    speechsdk,
    synthesizer,
    ssml: str,
    output_path: Path,
) -> None:
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = getattr(result, "cancellation_details", None)
        detail_msg = f" reason={result.reason}"
        if details:
            detail_msg += f", code={details.error_code}, message={details.error_details}"
        raise RuntimeError(f"Azure TTS synthesis failed:{detail_msg}")

    audio_data = result.audio_data
    if not audio_data:
        raise RuntimeError("Azure TTS returned empty audio data")

    output_path.write_bytes(audio_data)


def _build_ssml(
    text: str,
    voice_name: str,
    language_code: str,
    rate: float,
) -> str:
    rate_value = rate if rate > 0 else 1.0
    escaped_text = html.escape(text)
    return (
        f"<speak version='1.0' xml:lang='{language_code}'>"
        f"<voice name='{voice_name}'>"
        f"<prosody rate='{rate_value}'>"
        f"{escaped_text}"
        "</prosody></voice></speak>"
    )


def _resolve_column(columns: list[str], preferred: str, key: str) -> str:
    """Resolve a flexible column name using preferred name plus known aliases."""

    normalized = {str(col).strip(): str(col).strip() for col in columns}
    normalized_lower = {name.lower(): name for name in normalized}

    search_order: List[str] = []
    if preferred:
        search_order.append(preferred)
    search_order.extend(COLUMN_ALIASES.get(key, []))

    for candidate in search_order:
        candidate = str(candidate).strip()
        if not candidate:
            continue
        if candidate in normalized:
            return normalized[candidate]
        candidate_lower = candidate.lower()
        if candidate_lower in normalized_lower:
            resolved = normalized_lower[candidate_lower]
            return normalized[resolved]

    raise ValueError(
        f"找不到需要的欄位 '{preferred}' (aliases: {COLUMN_ALIASES.get(key, [])})"
    )


def _parse_question_id(value: Any) -> int:
    """Convert a dataset id cell into an integer for consistent naming."""

    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError(f"無法解析題目編號: {value}")

    text = str(value).strip()
    if not text:
        raise ValueError("題目編號不可為空白")

    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"無法解析題目編號: {value}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-generate WAV files via Azure TTS.")
    parser.add_argument("--input", default="zoo_dataset.csv", help="Dataset CSV path")
    parser.add_argument("--outdir", default="audio", help="Directory for generated audio")
    parser.add_argument("--language", default=None, help="Azure synthesis language code")
    parser.add_argument("--voice", default=None, help="Azure TTS voice name")
    parser.add_argument("--id-column", default="id", help="欄位名稱或別名，例如 '編號'")
    parser.add_argument(
        "--question-column",
        default="zh_question",
        help="題目文字欄位名稱，例如 '中文問題'",
    )
    parser.add_argument("--version-tag", default="v1", help="Version tag for file naming")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows")
    parser.add_argument(
        "--generate-testset",
        action="store_true",
        help="Emit a baseline stt_testset.csv alongside audio files",
    )
    parser.add_argument(
        "--testset-output",
        default="stt_testset.csv",
        help="Destination CSV for generated STT testset",
    )
    parser.add_argument("--speaker-type", default="azure_tts", help="Speaker type label")
    parser.add_argument("--noise-level", default="quiet", help="Noise level label")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing WAV files")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="語速倍率，1.0 為原速，>1.0 偏快，<1.0 偏慢",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    dataset_path = Path(args.input)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    df = pd.read_csv(dataset_path, low_memory=False)
    df.columns = [str(col).strip() for col in df.columns]

    id_column = _resolve_column(df.columns.tolist(), args.id_column, "id")
    question_column = _resolve_column(df.columns.tolist(), args.question_column, "question")
    if args.limit:
        df = df.head(args.limit)

    audio_dir = Path(args.outdir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    speechsdk, speech_config, resolved_language, resolved_voice = _build_speech_config(
        args.language, args.voice
    )
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)

    testset_rows: List[dict] = []

    for _, row in df.iterrows():
        try:
            question_id = _parse_question_id(row[id_column])
        except ValueError as exc:
            print(f"Skipping row due to invalid id: {exc}")
            continue

        text = str(row[question_column]).strip()
        if not text:
            print(f"Skipping id={question_id} due to empty question text")
            continue
        filename = f"q{question_id}_{args.version_tag}.wav"
        output_path = audio_dir / filename
        if output_path.exists() and not args.overwrite:
            print(f"Skipping existing file: {output_path}")
        else:
            print(f"Synthesizing {question_id} -> {output_path}")
            ssml = _build_ssml(text, resolved_voice, resolved_language, args.speed)
            _synthesize_to_file(speechsdk, synthesizer, ssml, output_path)

        if args.generate_testset:
            testset_rows.append(
                {
                    "id": question_id,
                    "wav_path": str(output_path),
                    "speaker_type": args.speaker_type,
                    "noise_level": args.noise_level,
                    "ref_transcript": text,
                    "canonical_query_id": question_id,
                }
            )

    if args.generate_testset and testset_rows:
        testset_path = Path(args.testset_output)
        testset_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(testset_rows).to_csv(testset_path, index=False)
        print(f"Wrote STT testset to {testset_path}")

    print("Azure TTS generation complete.")
    return 0


def generate_tts_for_text(
    text: str,
    filename: str,
    outdir: str,
    language: str | None = None,
    voice_name: str | None = None,
    speed: float = 1.0,
) -> None:
    """Helper to generate TTS for a single text string."""
    audio_dir = Path(outdir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_path = audio_dir / filename
    
    speechsdk, speech_config, resolved_language, resolved_voice = _build_speech_config(
        language, voice_name
    )
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    
    ssml = _build_ssml(text, resolved_voice, resolved_language, speed)
    _synthesize_to_file(speechsdk, synthesizer, ssml, output_path)

if __name__ == "__main__":
    raise SystemExit(main())
