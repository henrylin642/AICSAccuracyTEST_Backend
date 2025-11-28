"""Scoring utilities for STT and QA evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass
class ScoringResult:
    """Convenience container for STT scoring metrics."""

    reference: str
    hypothesis: str
    cer: float
    wer: float


def _levenshtein_distance(ref: Sequence[str], hyp: Sequence[str]) -> int:
    previous_row = list(range(len(hyp) + 1))
    for i, ref_token in enumerate(ref, start=1):
        current_row = [i]
        for j, hyp_token in enumerate(hyp, start=1):
            insertions = current_row[j - 1] + 1
            deletions = previous_row[j] + 1
            substitutions = previous_row[j - 1] + (ref_token != hyp_token)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def cer(ref: str, hyp: str) -> float:
    """Character error rate between reference and hypothesis strings."""

    ref_seq = list(ref)
    hyp_seq = list(hyp)
    if not ref_seq:
        return 0.0 if not hyp_seq else 1.0
    distance = _levenshtein_distance(ref_seq, hyp_seq)
    return distance / len(ref_seq)


def wer(ref: str, hyp: str) -> float:
    """Word error rate between reference and hypothesis (space-delimited)."""

    ref_tokens = ref.split()
    hyp_tokens = hyp.split()
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    distance = _levenshtein_distance(ref_tokens, hyp_tokens)
    return distance / len(ref_tokens)


def check_answer_with_keywords(
    answer: str, keywords: str | Iterable[str]
) -> tuple[bool, list[str]]:
    """Return overall match result and missing keywords (case-insensitive)."""

    if isinstance(keywords, str):
        items = [item.strip() for item in keywords.split(",") if item.strip()]
    else:
        items = [item.strip() for item in keywords if item and item.strip()]

    if not items:
        return False, []

    normalized_answer = answer.lower()
    missing = [keyword for keyword in items if keyword.lower() not in normalized_answer]
    return not missing, missing


__all__ = ["ScoringResult", "cer", "wer", "check_answer_with_keywords"]
