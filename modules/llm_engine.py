"""OpenRouter 무료 Qwen 모델 호출: 발언 -> Context Memory 갱신 + COP/상황판/일지 구조화 출력.

OpenRouter는 OpenAI 호환 Chat Completions API를 제공하므로 `openai` SDK를
base_url만 바꿔서 그대로 사용한다. 무료(:free) Qwen 모델은 provider별로
strict tool-calling 지원이 들쭉날쭉하므로, tool 강제 대신 "순수 JSON만
출력하라"는 프롬프트 지시 + 코드펜스 제거 + json.loads 재시도 방식으로
JSON을 강제한다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import openai
import streamlit as st

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# OpenRouter 무료 Qwen 모델 slug. 해커톤 당일 특정 모델이 무료 목록에서 빠졌다면
# https://openrouter.ai/models?q=qwen 에서 ":free" 접미사가 붙은 다른 Qwen 모델로 교체하세요.
DEFAULT_QWEN_MODEL = "qwen/qwen3-235b-a22b:free"

REQUIRED_KEYS = ("context_memory", "cop_layout", "situation_board", "operation_log_entry")

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


@dataclass
class LLMResult:
    data: dict
    latency_seconds: float
    input_tokens: int
    output_tokens: int


def _get_client() -> openai.OpenAI:
    api_key = st.secrets.get("OPENROUTER_API_KEY", "")
    if not api_key or "여기에" in api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY가 설정되지 않았습니다. .streamlit/secrets.toml 또는 "
            "Streamlit Cloud Secrets에 OpenRouter API 키를 등록하세요. "
            "(무료 발급: https://openrouter.ai/keys)"
        )
    return openai.OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)


def _extract_json(raw_text: str) -> dict:
    text = raw_text.strip()
    text = _CODE_FENCE_RE.sub("", text).strip()

    # 모델이 JSON 앞뒤로 군더더기 텍스트를 붙이는 경우, 첫 '{'부터 마지막 '}'까지만 취한다.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("응답에서 JSON 객체를 찾을 수 없습니다.")
    text = text[start : end + 1]

    parsed = json.loads(text)
    missing = [k for k in REQUIRED_KEYS if k not in parsed]
    if missing:
        raise ValueError(f"필수 키 누락: {missing}")
    return parsed


def analyze_utterance(
    system_prompt: str,
    few_shot_messages: list[dict],
    user_turn: str,
    max_retries: int = 2,
) -> LLMResult:
    """발언 1건을 분석하여 구조화된 결과를 반환한다. JSON 파싱 실패 시 최대 max_retries회 재시도."""
    client = _get_client()
    model = st.secrets.get("QWEN_MODEL", DEFAULT_QWEN_MODEL)

    messages = [
        {"role": "system", "content": system_prompt},
        *few_shot_messages,
        {"role": "user", "content": user_turn},
    ]

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        start = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2048,
                temperature=0.2,
                response_format={"type": "json_object"},
                extra_headers={
                    "HTTP-Referer": "https://voice-cue.local",
                    "X-Title": "VOICE-CUE",
                },
            )
        except openai.APIStatusError as e:
            last_error = e
            continue
        except openai.APIConnectionError as e:
            last_error = e
            continue

        latency = time.monotonic() - start

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice and choice.message else None
        if not content:
            last_error = ValueError("모델이 빈 응답을 반환했습니다.")
            continue

        try:
            parsed = _extract_json(content)
        except (ValueError, json.JSONDecodeError) as e:
            last_error = e
            continue

        usage = response.usage
        return LLMResult(
            data=parsed,
            latency_seconds=latency,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    raise RuntimeError(f"LLM 호출이 {max_retries + 1}회 모두 실패했습니다: {last_error}") from last_error
