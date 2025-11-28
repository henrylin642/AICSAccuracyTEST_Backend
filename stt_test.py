"""CLI sample: python stt_test.py --stt-testset stt_testset.csv --outdir results"""
from __future__ import annotations

import argparse
from datetime import datetime
import sys
from pathlib import Path
from statistics import mean
from typing import List

import pandas as pd

from scoring import cer, wer
from stt_client import transcribe_file
from constants import TAIWAN_ANIMALS
from text_utils import normalize_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch STT accuracy evaluation")
    parser.add_argument("--stt-testset", default="stt_testset.csv", help="STT testset CSV")
    parser.add_argument("--outdir", default="results", help="Directory for result CSVs")
    parser.add_argument("--language", default=None, help="Override language code for STT")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for debugging")
    parser.add_argument(
        "--intent-strict",
        action="store_true",
        help="Enable strict exact-match intent evaluation",
    )
    return parser.parse_args()


def evaluate_row(row: pd.Series, language: str | None, intent_strict: bool) -> dict:
    wav_path = row["wav_path"]
    ref_transcript = str(row["ref_transcript"])
    stt_raw = transcribe_file(wav_path, language_code=language, phrase_hints=TAIWAN_ANIMALS)
    stt_normalized = normalize_text(stt_raw)
    ref_normalized = normalize_text(ref_transcript)

    cer_score = cer(ref_normalized, stt_normalized)
    wer_score = wer(ref_normalized, stt_normalized)

    intent_hit = None
    if intent_strict:
        intent_hit = stt_normalized == ref_normalized

    return {
        "id": row["id"],
        "wav_path": wav_path,
        "ref_transcript": ref_transcript,
        "stt_raw": stt_raw,
        "stt_normalized": stt_normalized,
        "cer": cer_score,
        "wer": wer_score,
        "intent_hit": intent_hit,
        "error": None,
    }


def main() -> int:
    args = parse_args()

    testset_path = Path(args.stt_testset)
    if not testset_path.exists():
        print(f"STT testset not found: {testset_path}", file=sys.stderr)
        return 1

    df = pd.read_csv(testset_path)
    if args.limit:
        df = df.head(args.limit)

    rows: List[dict] = []

    for _, row in df.iterrows():
        try:
            result = evaluate_row(row, args.language, args.intent_strict)
        except Exception as exc:  # pragma: no cover - defensive programming
            result = {
                "id": row.get("id"),
                "wav_path": row.get("wav_path"),
                "ref_transcript": row.get("ref_transcript"),
                "stt_raw": "",
                "stt_normalized": "",
                "cer": None,
                "wer": None,
                "intent_hit": None,
                "error": str(exc),
            }
            print(f"Error processing id={row.get('id')}: {exc}")
        rows.append(result)

    result_df = pd.DataFrame(rows)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    output_path = outdir / f"stt_results_{timestamp}.csv"
    result_df.to_csv(output_path, index=False)
    print(f"Saved STT results to {output_path}")

    error_mask = result_df["error"].notna()
    if "intent_hit" in result_df.columns:
        error_mask = error_mask | (result_df["intent_hit"] == False)
    error_df = result_df[error_mask]
    if not error_df.empty:
        error_path = outdir / f"error_cases_stt_{timestamp}.csv"
        error_df.to_csv(error_path, index=False)
        print(f"Saved STT error cases to {error_path}")

    cer_values = [value for value in result_df["cer"].dropna()]
    wer_values = [value for value in result_df["wer"].dropna()]
    intent_values = [
        value
        for value in result_df["intent_hit"].tolist()
        if isinstance(value, bool)
    ]

    if cer_values:
        print(f"Average CER: {mean(cer_values):.4f}")
    if wer_values:
        print(f"Average WER: {mean(wer_values):.4f}")
    if intent_values:
        accuracy = sum(1 for hit in intent_values if hit) / len(intent_values)
        print(f"STT Intent Accuracy: {accuracy:.2%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
