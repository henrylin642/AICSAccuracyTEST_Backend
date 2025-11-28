"""Chatbase API client wrapper."""
from __future__ import annotations

import json
from typing import Any, Dict

import requests

from config import get_chatbase_config


class ChatbaseError(RuntimeError):
    """Raised when Chatbase returns an error."""


def ask_chatbase(question: str, conversation_id: str | None = None) -> Dict[str, Any]:
    """Send a question to Chatbase and return the response payload.

    Args:
        question: The user utterance to send to the bot.
        conversation_id: Optional conversation identifier to continue a session.

    Returns:
        Dict containing at least "answer_text" and "conversation_id" fields.
    """

    cfg = get_chatbase_config()
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "chatbotId": cfg.bot_id,
        "messages": [{"role": "user", "content": question}],
        "temperature": 0.1,
    }
    if conversation_id:
        body["conversationId"] = conversation_id

    try:
        response = requests.post(cfg.api_url, headers=headers, json=body, timeout=30)
    except requests.RequestException as exc:
        raise ChatbaseError(f"Network error calling Chatbase: {exc}") from exc

    if response.status_code >= 400:
        raise ChatbaseError(
            "Chatbase API returned an error: "
            f"{response.status_code} {response.text.strip()}"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ChatbaseError("Failed to parse Chatbase response as JSON") from exc

    answer = (
        payload.get("answer")
        or payload.get("text")
        or payload.get("answer_text")
        or payload.get("reply")
    )

    if not isinstance(answer, str) or not answer.strip():
        raise ChatbaseError("Chatbase response did not include an answer text field")

    conversation = payload.get("conversationId") or payload.get("conversation_id")

    return {
        "answer_text": answer.strip(),
        "conversation_id": conversation,
        "raw": payload,
    }


__all__ = ["ask_chatbase", "ChatbaseError"]
