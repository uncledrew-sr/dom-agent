"""
llm.py — Ollama 로컬 API 연동 모듈 (Step 3)

책임:
  - Ollama HTTP API 호출 (/api/chat)
  - 에이전트 시스템 프롬프트 및 사용자 프롬프트 구성
  - 응답에서 JSON 블록 추출 (정규표현식 fallback)
  - 파싱 실패 시 최대 N회 재시도
"""

import re
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL   = "gemma2:2b"
MAX_RETRIES     = 3
REQUEST_TIMEOUT = 60.0  # 로컬 모델은 첫 응답까지 느릴 수 있음

# ── 시스템 프롬프트 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a web automation agent. You control a browser by outputting JSON actions.

AVAILABLE ACTIONS:
  {"action": "click",    "target_id": <int>}
  {"action": "type",     "target_id": <int>, "text": "<string>"}
  {"action": "press",    "key": "<string>"}          -- e.g. "Enter", "Escape"
  {"action": "scroll",   "direction": "down"}
  {"action": "navigate", "url": "<string>"}
  {"action": "done",     "message": "<string>"}      -- task complete
  {"action": "fail",     "message": "<string>"}      -- cannot complete

RULES:
1. Output ONLY a single JSON object. No explanation, no markdown, no extra text.
2. target_id must be one of the [ID: N] numbers shown in the page context.
3. If the task is already complete, use "done".
4. For "type" action, target_id MUST be an <input> or <textarea> element. NEVER type into <a> or <button>.
5. Typing into a search box automatically submits — your next action after "type" should be "done".
6. Never repeat an action that already has "error" in the history. Choose a different target_id or action.
7. If the URL contains search results related to the task, output "done".
"""

# ── 액션 스키마 (검증용) ────────────────────────────────────────────────────────

VALID_ACTIONS = {"click", "type", "press", "scroll", "navigate", "done", "fail"}


# ── 메인 클래스 ────────────────────────────────────────────────────────────────

class OllamaClient:
    """Ollama 로컬 서버와 통신하며 에이전트 액션 JSON을 반환한다."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        max_retries: int = MAX_RETRIES,
    ):
        self.model = model
        self.base_url = base_url
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ── 공개 API ──────────────────────────────────────────────────────────────

    async def decide(
        self,
        task: str,
        page_context: str,
        history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        현재 페이지 상태를 보고 다음 액션을 결정한다.

        Args:
            task: 사용자 원래 목표 (예: "네이버에서 날씨 검색해줘")
            page_context: DOMParser.condensed_text
            history: 이전 액션 요약 리스트 (최대 5개 유지)

        Returns:
            {"action": ..., ...} 형태의 딕셔너리
        """
        user_prompt = self._build_user_prompt(task, page_context, history or [])
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ]

        for attempt in range(1, self.max_retries + 1):
            raw = await self._call_api(messages)
            logger.debug("LLM 원문 응답 (시도 %d):\n%s", attempt, raw)

            parsed = self._extract_json(raw)
            if parsed and self._is_valid(parsed):
                return parsed

            logger.warning("JSON 파싱 실패 (시도 %d/%d): %s", attempt, self.max_retries, raw[:200])
            # 재시도 시 실패한 응답을 컨텍스트에 포함해 모델이 수정하도록 유도
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not valid JSON. "
                    "Output ONLY a JSON object like: "
                    '{"action": "click", "target_id": 1}'
                ),
            })

        raise ValueError(f"모델이 {self.max_retries}회 시도 후에도 유효한 JSON을 반환하지 않았습니다.")

    async def check_server(self) -> bool:
        """Ollama 서버가 실행 중인지 확인한다."""
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _build_user_prompt(
        self,
        task: str,
        page_context: str,
        history: list[dict],
    ) -> str:
        parts = [f"TASK: {task}"]

        if history:
            history_str = "\n".join(
                f"  Step {i+1}: {json.dumps(a, ensure_ascii=False)}"
                for i, a in enumerate(history[-5:])  # 최근 5개만
            )
            parts.append(f"ACTIONS SO FAR:\n{history_str}")

        parts.append(f"CURRENT PAGE:\n{page_context}")
        parts.append("What is the next action? Output JSON only.")

        return "\n\n".join(parts)

    async def _call_api(self, messages: list[dict]) -> str:
        """Ollama /api/chat 엔드포인트를 호출하고 텍스트를 반환한다."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.0,   # 결정론적 출력 — JSON 안정성 향상
                "num_predict": 128,   # 액션 하나면 충분, 긴 응답 방지
            },
        }
        resp = await self._client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """
        텍스트에서 JSON 객체를 추출한다.

        우선순위:
          1. 전체 텍스트가 JSON인 경우
          2. ```json ... ``` 코드블록
          3. 정규표현식으로 첫 번째 { ... } 블록 추출
        """
        # 1. 직접 파싱
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. 코드블록 추출
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass

        # 3. 정규표현식 — 중첩 괄호를 고려한 그리디 매칭
        brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _is_valid(action: dict) -> bool:
        """액션 딕셔너리가 최소 스키마를 만족하는지 확인한다."""
        if "action" not in action:
            return False
        if action["action"] not in VALID_ACTIONS:
            return False
        # click / type 은 target_id 필수
        if action["action"] in ("click", "type") and "target_id" not in action:
            return False
        # type 은 text 필수
        if action["action"] == "type" and "text" not in action:
            return False
        return True
