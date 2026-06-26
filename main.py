"""
main.py — 에이전트 실행 진입점

실행:
    .venv/bin/python3 main.py "네이버에서 날씨 검색해줘"
    .venv/bin/python3 main.py "네이버 뉴스 페이지로 이동해줘"
"""

import asyncio
import logging
import sys

from agent.agent import WebAgent

logging.basicConfig(
    level=logging.WARNING,  # INFO로 바꾸면 상세 로그 출력
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main(task: str) -> None:
    async with WebAgent(headless=False, model="gemma2:2b") as agent:
        result = await agent.run(task)

    print(f"\n{'='*55}")
    status = "성공" if result.success else "실패"
    print(f"  결과: {status} — {result.message}")
    print(f"  총 스텝: {len(result.steps)}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "네이버에서 날씨 검색해줘"
    asyncio.run(main(task))
