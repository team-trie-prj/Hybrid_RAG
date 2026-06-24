"""LLM 프로바이더 — Gemini 3.5 Flash (google-genai SDK).

GEMINI_API_KEY (또는 GOOGLE_API_KEY)가 있으면 Gemini로 에이전트 루프를 돈다.
없으면 agent.py의 오프라인 규칙 라우터가 동작한다.

모델 ID는 GEMINI_MODEL 환경변수로 덮어쓸 수 있다(기본 gemini-3.5-flash).
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# 일시적 장애(과부하/레이트리밋)는 재시도로 흡수 → 폴백 전에 Gemini에 기회를 더 준다.
RETRYABLE = ("503", "unavailable", "429", "resource_exhausted", "500", "internal", "timeout")
MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))


def gemini_available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _generate_with_retry(client, contents, config):
    """503/429 등 일시적 오류면 지수 백오프로 재시도. 그 외 오류는 즉시 전파."""
    delay = 1.5
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.models.generate_content(model=MODEL, contents=contents, config=config)
        except Exception as e:  # google.genai 예외 계층 대신 메시지 기반 판별(SDK 버전 호환)
            if attempt < MAX_RETRIES and any(s in str(e).lower() for s in RETRYABLE):
                time.sleep(delay)
                delay *= 2
                continue
            raise


def run_agent(
    question: str,
    system: str,
    tools_spec: list[dict[str, Any]],
    dispatch: Callable[[str, dict], Any],
    max_turns: int = 6,
) -> tuple[str, list[str]]:
    """Gemini 수동 function-calling 멀티턴 루프.

    tools_spec: [{name, description, input_schema(JSON schema)} ...]
    dispatch:   (tool_name, args) -> JSON 직렬화 가능한 결과
    반환: (최종 텍스트, 호출된 도구명 리스트)
    """
    from google import genai
    from google.genai import types

    client = genai.Client()  # GEMINI_API_KEY / GOOGLE_API_KEY 자동 인식

    declarations = [
        {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
        for t in tools_spec
    ]
    tools = types.Tool(function_declarations=declarations)
    config = types.GenerateContentConfig(
        system_instruction=system, tools=[tools], temperature=0,
    )

    contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=question)])]
    used: list[str] = []

    for _ in range(max_turns):
        resp = _generate_with_retry(client, contents, config)
        cand = resp.candidates[0]
        parts = cand.content.parts or []
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        if not calls:
            text = "".join(p.text for p in parts if getattr(p, "text", None)) or "(빈 응답)"
            return text, used

        contents.append(cand.content)  # 모델의 tool_call 턴 누적
        fr_parts = []
        for call in calls:
            used.append(call.name)
            result = dispatch(call.name, dict(call.args or {}))
            fr_parts.append(
                types.Part.from_function_response(name=call.name, response={"result": result})
            )
        contents.append(types.Content(role="user", parts=fr_parts))

    return "(function call 한도 초과)", used
