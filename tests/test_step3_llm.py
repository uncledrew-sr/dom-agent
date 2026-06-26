"""
Step 3 검증 스크립트

실행:
    .venv/bin/python3 tests/test_step3_llm.py

확인 항목:
    1. Ollama 서버 연결 확인
    2. JSON 추출 로직 단위 테스트 (서버 없이도 가능)
    3. 실제 모델 호출 — 샘플 페이지 컨텍스트로 액션 결정
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.llm import OllamaClient


# ── 1. JSON 추출 단위 테스트 (오프라인) ───────────────────────────────────────
def test_json_extraction():
    print("\n[단위 테스트] JSON 추출 로직")

    cases = [
        # (입력, 예상 action)
        ('{"action": "click", "target_id": 3}',               "click"),
        ('Sure!\n```json\n{"action": "type", "target_id": 1, "text": "날씨"}\n```', "type"),
        ('Here is my answer: {"action": "press", "key": "Enter"} done!', "press"),
    ]

    for raw, expected_action in cases:
        result = OllamaClient._extract_json(raw)
        assert result is not None, f"추출 실패: {raw}"
        assert result["action"] == expected_action, f"액션 불일치: {result}"
        print(f"  [✓] '{raw[:50]}...' → {result}")

    print("[✓] JSON 추출 단위 테스트 통과")


# ── 2. 액션 검증 단위 테스트 ────────────────────────────────────────────────
def test_validation():
    print("\n[단위 테스트] 액션 스키마 검증")

    valid_cases = [
        {"action": "click", "target_id": 1},
        {"action": "type", "target_id": 1, "text": "날씨"},
        {"action": "press", "key": "Enter"},
        {"action": "done", "message": "완료"},
    ]
    invalid_cases = [
        {"action": "fly"},               # 없는 액션
        {"action": "click"},             # target_id 없음
        {"action": "type", "target_id": 1},  # text 없음
    ]

    for case in valid_cases:
        assert OllamaClient._is_valid(case), f"유효해야 하는데 실패: {case}"
        print(f"  [✓] valid: {case}")

    for case in invalid_cases:
        assert not OllamaClient._is_valid(case), f"무효여야 하는데 통과: {case}"
        print(f"  [✓] invalid (정상 차단): {case}")

    print("[✓] 스키마 검증 단위 테스트 통과")


# ── 3. 실제 Ollama 호출 테스트 ────────────────────────────────────────────────
SAMPLE_PAGE_CONTEXT = """\
=== 상호작용 가능한 요소 ===
[ID: 1] <input> 검색어를 입력해 주세요 | type=text name=query
[ID: 2] <button> 검색
[ID: 3] <a> 뉴스 | href=/news
[ID: 4] <a> 쇼핑 | href=/shopping

=== 페이지 주요 텍스트 ===
<title> NAVER
<h2> 연합뉴스
"""


async def test_llm_call():
    async with OllamaClient() as client:
        # 서버 상태 확인
        ok = await client.check_server()
        if not ok:
            print("\n[!] Ollama 서버가 실행되지 않고 있습니다.")
            print("    터미널에서 'ollama serve' 를 먼저 실행하세요.")
            return

        print(f"\n[✓] Ollama 서버 연결 성공 (모델: {client.model})")

        # 실제 추론 호출
        print("\n[LLM 호출] 태스크: '네이버 검색창에 날씨를 입력해줘'")
        action = await client.decide(
            task="네이버 검색창에 날씨를 입력해줘",
            page_context=SAMPLE_PAGE_CONTEXT,
        )

        print(f"[✓] 모델 응답: {action}")
        assert action["action"] in ("type", "click"), f"예상치 못한 액션: {action}"
        print("[✓] LLM 호출 테스트 통과")


if __name__ == "__main__":
    print("=" * 50)
    print("Step 3 — OllamaClient 검증")
    print("=" * 50)

    test_json_extraction()
    test_validation()
    asyncio.run(test_llm_call())

    print("\n모든 Step 3 검증 통과!\n")
