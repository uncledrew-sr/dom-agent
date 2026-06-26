"""
Step 2 검증 스크립트

실행:
    .venv/bin/python3 tests/test_step2_dom.py

확인 항목:
    1. 노이즈 태그(<script>, <style> 등)가 제거되는가?
    2. 인터랙션 요소에 [ID: N]이 부여되는가?
    3. condensed_text가 MAX_OUTPUT_CHARS 이하인가?
    4. 실제 네이버 페이지에 적용했을 때 결과가 읽기 쉬운가?
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.browser import BrowserController
from agent.dom_parser import DOMParser


# ── 단위 테스트: 간단한 HTML로 파서 동작 확인 ──────────────────────────────
SAMPLE_HTML = """
<html>
<head>
  <script>alert('noise')</script>
  <style>.hidden { display:none }</style>
</head>
<body>
  <h1>검색 포털</h1>
  <input type="text" name="query" placeholder="검색어를 입력하세요">
  <button type="submit">검색</button>
  <a href="/news">뉴스</a>
  <a href="/sports">스포츠</a>
  <div style="display:none"><button>숨겨진 버튼</button></div>
</body>
</html>
"""


def test_unit():
    parser = DOMParser()
    result = parser.parse(SAMPLE_HTML)

    print("\n[단위 테스트] condensed_text:")
    print(result.condensed_text)

    print(f"\n인터랙션 요소 수: {len(result.elements)}")
    for eid, elem in result.elements.items():
        print(f"  ID {eid}: <{elem.tag}> '{elem.text}' | selector={elem.css_selector}")

    # 검증
    assert len(result.elements) >= 4, "인터랙션 요소가 최소 4개여야 합니다"
    assert "script" not in result.condensed_text, "<script> 태그가 남아있습니다"
    assert "숨겨진 버튼" not in result.condensed_text, "숨겨진 요소가 남아있습니다"
    print("\n[✓] 단위 테스트 통과")


# ── 통합 테스트: 실제 네이버 페이지 파싱 ──────────────────────────────────
async def test_naver():
    parser = DOMParser()

    async with BrowserController(headless=False) as bc:
        await bc.navigate("https://www.naver.com")
        html = await bc.get_html()

    result = parser.parse(html, current_url="https://www.naver.com")

    print("\n" + "=" * 50)
    print("[통합 테스트] 네이버 DOM 파싱 결과")
    print("=" * 50)
    print(result.condensed_text)

    print(f"\n총 인터랙션 요소: {len(result.elements)}개")
    print(f"condensed_text 길이: {len(result.condensed_text):,} chars")

    assert len(result.condensed_text) <= 6_500, "텍스트가 너무 깁니다"
    assert len(result.elements) > 0, "인터랙션 요소가 없습니다"
    print("\n[✓] 통합 테스트 통과")


if __name__ == "__main__":
    print("=" * 50)
    print("Step 2 — DOMParser 검증")
    print("=" * 50)

    test_unit()
    asyncio.run(test_naver())

    print("\n모든 Step 2 검증 통과!\n")
