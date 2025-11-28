"""CLI sample: python e2e_test.py --stt-testset stt_testset.csv --dataset zoo_dataset.csv --keywords answer_keywords.csv"""
from __future__ import annotations

import argparse
from datetime import datetime
import sys
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from chatbase_client import ChatbaseError, ask_chatbase
from scoring import check_answer_with_keywords
from stt_client import transcribe_file
from constants import TAIWAN_ANIMALS
from llm_client import evaluate_answer_with_llm
from text_utils import normalize_text


DATASET_COLUMN_ALIASES = {
    "id": ["id", "編號"],
    "question": ["zh_question", "中文問題", "Q-ch", "Q_CH", "Q_ch", "QCH"],
    "Ans-ch": ["Ans-ch", "中文回答", "Answer-ch", "A-ch"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-end STT + Chatbase testing")
    parser.add_argument("--stt-testset", default="stt_testset.csv", help="STT testset CSV")
    parser.add_argument("--dataset", default="zoo_dataset.csv", help="QA dataset CSV")
    parser.add_argument(
        "--keywords",
        default=None,
        help="Optional answer keywords CSV for auto grading",
    )
    parser.add_argument("--outdir", default="results", help="Directory for result CSVs")
    parser.add_argument("--language", default=None, help="Override STT language code")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for dry runs")
    parser.add_argument(
        "--intent-strict",
        action="store_true",
        help="Enable exact match intent evaluation",
    )
    parser.add_argument(
        "--use-llm-eval",
        action="store_true",
        help="Use LLM (OpenAI) to evaluate answer correctness",
    )
    parser.add_argument(
        "--autosave",
        action="store_true",
        help="在每筆樣本完成後即時更新結果 CSV，方便測試中途檢視",
    )
    parser.add_argument(
        "--dataset-id-column",
        default="id",
        help="Dataset ID 欄位名稱或別名（例如 編號）",
    )
    parser.add_argument(
        "--dataset-question-column",
        default="zh_question",
        help="題目欄位名稱（例如 中文問題 / Q-ch）",
    )
    return parser.parse_args()


def load_keywords(path: Optional[str]) -> Dict[int, str]:
    if not path:
        return {}
    keywords_path = Path(path)
    if not keywords_path.exists():
        raise FileNotFoundError(f"Keywords file not found: {keywords_path}")
    df = pd.read_csv(keywords_path, low_memory=False)
    keyword_map: Dict[int, str] = {}
    for _, row in df.iterrows():
        raw_id = row.get("id")
        if pd.isna(raw_id):
            continue
        try:
            key = int(raw_id)
        except (TypeError, ValueError):
            print(f"Skipping keyword row with invalid id: {raw_id}")
            continue
        value = row.get("check_keywords_zh")
        if isinstance(value, str) and value.strip():
            keyword_map[key] = value
    return keyword_map


def _persist_results(
    rows: list[dict],
    outdir: Path,
    timestamp: str,
    output_path: Path,
) -> None:
    result_df = pd.DataFrame(rows)
    result_df.to_csv(output_path, index=False)

    error_mask = result_df["error"].notna() if not result_df.empty else pd.Series(dtype=bool)
    if "ai_correct" in result_df.columns:
        error_mask = error_mask | result_df["ai_correct"].apply(lambda value: value is False)
    if "e2e_success" in result_df.columns:
        error_mask = error_mask | result_df["e2e_success"].apply(lambda value: value is False)
    error_df = result_df[error_mask] if not result_df.empty else result_df
    if not error_df.empty:
        error_path = outdir / f"error_cases_e2e_{timestamp}.csv"
        error_df.to_csv(error_path, index=False)


def _resolve_dataset_column(columns: list[str], preferred: str, key: str) -> str:
    normalized = [str(col).strip() for col in columns]
    normalized_map = {col: col for col in normalized}
    lowered_map = {col.lower(): col for col in normalized}

    search_order = []
    if preferred:
        search_order.append(preferred)
    search_order.extend(DATASET_COLUMN_ALIASES.get(key, []))

    for candidate in search_order:
        cand = str(candidate).strip()
        if cand in normalized_map:
            return normalized_map[cand]
        lower = cand.lower()
        if lower in lowered_map:
            actual = lowered_map[lower]
            return normalized_map[actual]
    raise ValueError(f"找不到資料集欄位 {preferred!r} (key={key})")


def load_dataset_questions(
    dataset_path: str,
    id_column: str,
    question_column: str,
) -> Dict[int, str]:
    df = pd.read_csv(dataset_path, low_memory=False)
    df.columns = [str(col).strip() for col in df.columns]
    resolved_id = _resolve_dataset_column(df.columns.tolist(), id_column, "id")
    resolved_question = _resolve_dataset_column(df.columns.tolist(), question_column, "question")

    question_map: Dict[int, str] = {}
    for _, row in df.iterrows():
        raw_id = row.get(resolved_id)
        if pd.isna(raw_id):
            continue
        try:
            question_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        text = row.get(resolved_question)
        if isinstance(text, str) and text.strip():
            question_map[question_id] = text.strip()
    return question_map


def evaluate_row(
    row: pd.Series,
    keyword_map: Dict[int, str],
    language: str | None,
    intent_strict: bool,
    question_map: Dict[int, str],
    **kwargs,
) -> dict:
    wav_path = row["wav_path"]
    ref_transcript = str(row["ref_transcript"])
    stt_raw = transcribe_file(wav_path, language_code=language, phrase_hints=TAIWAN_ANIMALS)
    stt_normalized = normalize_text(stt_raw)
    ref_normalized = normalize_text(ref_transcript)

    stt_intent_hit = None
    if intent_strict:
        stt_intent_hit = stt_normalized == ref_normalized

    chatbase_response = ask_chatbase(stt_normalized)
    ai_answer = chatbase_response["answer_text"]

    canonical_id = row.get("canonical_query_id") or row.get("id")
    question_text = None
    keywords = None
    if canonical_id is not None:
        try:
            canonical_int = int(canonical_id)
        except (TypeError, ValueError):
            canonical_int = None
        if canonical_int is not None:
            keywords = keyword_map.get(canonical_int)
            question_text = question_map.get(canonical_int)

    ai_correct: Optional[bool] = None
    missing_keywords: Optional[list[str]] = None
    llm_reason: Optional[str] = None
    
    # Priority: LLM Eval > Keyword Eval
    use_llm = kwargs.get("use_llm_eval", False)
    
    if use_llm and question_text:
        # We need a reference answer. If keywords are used as reference, that's weak.
        # Ideally we should have a 'reference_answer' column in dataset.
        # For now, let's assume 'keywords' might contain the gist, OR we rely on the fact 
        # that the dataset might have an answer column.
        # Looking at zoo_dataset.csv, there is 'Ans-ch'. Let's fetch it.
        reference_answer = kwargs.get("reference_answer_map", {}).get(canonical_id)
        
        if reference_answer:
            llm_result = evaluate_answer_with_llm(question_text, reference_answer, ai_answer)
            ai_correct = llm_result["is_correct"]
            llm_reason = llm_result["reason"]
        else:
            # Fallback to keywords if no full reference answer found (unlikely if map is built)
            if keywords:
                 ai_correct, missing_keywords = check_answer_with_keywords(ai_answer, keywords)
    
    elif keywords:
        ai_correct, missing_keywords = check_answer_with_keywords(ai_answer, keywords)

    e2e_success: Optional[bool] = None
    if ai_correct is not None:
        e2e_success = bool(stt_intent_hit) if intent_strict else True
        e2e_success = e2e_success and ai_correct

    return {
        "id": row["id"],
        "wav_path": wav_path,
        "ref_transcript": ref_transcript,
        "question_text": question_text,
        "stt_raw": stt_raw,
        "stt_normalized": stt_normalized,
        "ai_answer": ai_answer,
        "stt_intent_hit": stt_intent_hit,
        "ai_correct": ai_correct,
        "e2e_success": e2e_success,
        "conversation_id": chatbase_response.get("conversation_id"),
        "keywords_used": keywords,
        "missing_keywords": ", ".join(missing_keywords) if missing_keywords else None,
        "llm_reason": llm_reason,
        "error": None,
    }


def main() -> int:
    args = parse_args()

    for required in (args.stt_testset, args.dataset):
        if not Path(required).exists():
            print(f"Required input not found: {required}", file=sys.stderr)
            return 1

    df = pd.read_csv(args.stt_testset)
    if args.limit:
        df = df.head(args.limit)

    question_map = load_dataset_questions(
        args.dataset, args.dataset_id_column, args.dataset_question_column
    )
    
    # Also load reference answers for LLM eval
    # Assuming standard column name 'Ans-ch' or similar. We can reuse load_dataset_questions logic 
    # but we need a new helper or just call it again with different column.
    # Let's quickly check zoo_dataset.csv columns again.
    # It has 'Ans-ch'.
    answer_map = load_dataset_questions(
        args.dataset, args.dataset_id_column, "Ans-ch"
    )

    keyword_map = load_keywords(args.keywords)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    output_path = outdir / f"e2e_results_{timestamp}.csv"

    rows = []
    for _, row in df.iterrows():
        try:
            result = evaluate_row(
                row,
                keyword_map,
                args.language,
                args.intent_strict,
                question_map,
                use_llm_eval=args.use_llm_eval,
                reference_answer_map=answer_map,
            )
        except (ChatbaseError, Exception) as exc:  # pragma: no cover - best-effort logging
            result = {
                "id": row.get("id"),
                "wav_path": row.get("wav_path"),
                "ref_transcript": row.get("ref_transcript"),
                "question_text": None,
                "stt_raw": "",
                "stt_normalized": "",
                "ai_answer": "",
                "stt_intent_hit": None,
                "ai_correct": None,
                "e2e_success": None,
                "conversation_id": None,
                "keywords_used": None,
                "missing_keywords": None,
                "error": str(exc),
            }
            print(f"Error processing id={row.get('id')}: {exc}")
        rows.append(result)
        if args.autosave:
            _persist_results(rows, outdir, timestamp, output_path)

    _persist_results(rows, outdir, timestamp, output_path)
    print(f"Saved E2E results to {output_path}")

    result_df = pd.DataFrame(rows)
    stt_values = [value for value in result_df["stt_intent_hit"].tolist() if isinstance(value, bool)]
    ai_values = [value for value in result_df["ai_correct"].tolist() if isinstance(value, bool)]
    e2e_values = [value for value in result_df["e2e_success"].tolist() if isinstance(value, bool)]

    if stt_values:
        print(f"STT Intent Accuracy: {sum(stt_values) / len(stt_values):.2%}")
    if ai_values:
        print(f"AI Answer Accuracy: {sum(ai_values) / len(ai_values):.2%}")
    if e2e_values:
        print(f"End-to-End Accuracy: {sum(e2e_values) / len(e2e_values):.2%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
