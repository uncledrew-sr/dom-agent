"""
Step 1 검증 스크립트

실행:
    python tests/test_step1_browser.py

확인 항목:
    1. 브라우저가 정상 실행/종료되는가?
    2. 네이버로 이동하고 타이틀을 읽을 수 있는가?
    3. HTML이 비어 있지 않은가?
    4. 스크린샷이 저장되는가?
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.browser import BrowserController


async def main():
    print("=" * 50)
    print("Step 1 — BrowserController 검증")
    print("=" * 50)

    async with BrowserController(headless=False, slow_mo=200) as bc:
        # 1. 네이버 이동
        await bc.navigate("https://www.naver.com")
        title = await bc.get_title()
        url = await bc.current_url()
        print(f"\n[✓] 타이틀 : {title}")
        print(f"[✓] URL    : {url}")

        # 2. HTML 길이 확인
        html = await bc.get_html()
        print(f"[✓] HTML   : {len(html):,} chars")
        assert len(html) > 1000, "HTML이 너무 짧습니다!"

        # 3. 스크린샷
        await bc.take_screenshot("logs/step1_naver.png")
        print("[✓] 스크린샷 저장 완료")

    print("\n모든 Step 1 검증 통과!\n")


if __name__ == "__main__":
    asyncio.run(main())
