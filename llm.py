"""
llm.py
------
Helper functions for Groq API calls using the official groq Python SDK.

IMPROVEMENTS v2:
- call_llm_json now retries up to 3 times on JSON parse failure,
  asking the model to fix its own output on each retry.
- Strips both ``` and bare { } extraction as fallback.
- Better error messages with the raw response included.
"""

import json
import os
import re

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _strip_markdown_fences(text: str) -> str:
    """Remove Markdown code fences that the LLM sometimes wraps around JSON."""
    pattern = r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_json_object(text: str) -> str:
    """
    Last-resort extraction: find the first { ... } or [ ... ] block in the text.
    Handles cases where the model adds preamble before the JSON.
    """
    # Try object
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    # Try array
    start = text.find("[")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text


def call_llm(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """Send a chat-completion request and return the assistant's response as a string."""
    chat_completion = _client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return chat_completion.choices[0].message.content


def call_llm_json(
    prompt: str,
    system_prompt: str = "You are a helpful assistant that responds ONLY in valid JSON.",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    max_retries: int = 3,
) -> dict:
    """
    Call the LLM and parse the response as JSON.
    Retries up to `max_retries` times if JSON parsing fails,
    feeding the error back to the model on each attempt.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]

    last_error = None
    last_raw   = ""

    for attempt in range(1, max_retries + 1):
        chat_completion = _client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = chat_completion.choices[0].message.content
        last_raw = raw

        # Try progressively more aggressive cleaning
        for cleaner in [_strip_markdown_fences, _extract_json_object]:
            cleaned = cleaner(raw)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                continue

        # Parsing failed — tell the model what went wrong and retry
        last_error = f"Your response could not be parsed as JSON. Raw output was:\n{raw[:500]}"
        print(f"  [call_llm_json] Attempt {attempt}/{max_retries} failed: {last_error[:120]}")

        # Append the failure + correction request to the message history
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Please respond with ONLY a valid JSON object — no markdown fences, "
                "no explanations, no preamble. Start your response with { and end with }."
            ),
        })

    raise json.JSONDecodeError(
        f"Failed to parse JSON after {max_retries} attempts. Last raw: {last_raw[:300]}",
        last_raw,
        0,
    )