"""Client for LLM-based evaluation."""
from __future__ import annotations

import json
import logging
import os
from typing import TypedDict

from openai import OpenAI

from config import _require_env

LOGGER = logging.getLogger(__name__)


class EvaluationResult(TypedDict):
    is_correct: bool
    score: int
    reason: str


def _get_openai_client() -> OpenAI:
    api_key = _require_env("OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def evaluate_answer_with_llm(
    question: str, reference: str, answer: str
) -> EvaluationResult:
    """Evaluate if the answer is correct based on the reference using LLM.

    Args:
        question: The user's question.
        reference: The standard/correct answer (ground truth).
        answer: The AI's generated answer to evaluate.

    Returns:
        A dictionary containing 'is_correct' (bool) and 'reason' (str).
    """
    client = _get_openai_client()

    prompt = f"""
    You are an expert judge evaluating the correctness of an AI assistant's response.

    Question: {question}
    Standard Answer (Ground Truth): {reference}
    AI Answer: {answer}

    Task:
    1. Determine if the AI Answer is factually consistent with the Standard Answer.
    2. Assign a score from 0 to 100.
       - 100: Perfect match in meaning and key details.
       - 80-99: Correct meaning, minor missing details or slight phrasing differences.
       - 60-79: Mostly correct, but misses some important details or includes minor inaccuracies.
       - 40-59: Partially correct, but misses key information or has noticeable errors.
       - 0-39: Incorrect, irrelevant, or hallucinated.

    Output Format:
    Return ONLY a JSON object with the following format:
    {{
        "is_correct": true/false,  // true if score >= 60
        "score": <int 0-100>,
        "reason": "Brief explanation of your judgment"
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful and strict evaluator."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from OpenAI")

        result = json.loads(content)
        return {
            "is_correct": result.get("is_correct", False),
            "score": result.get("score", 0),
            "reason": result.get("reason", "No reason provided"),
        }

    except Exception as exc:
        LOGGER.error("LLM evaluation failed: %s", exc)
        return {
            "is_correct": False,
            "reason": f"Evaluation failed: {str(exc)}",
        }
