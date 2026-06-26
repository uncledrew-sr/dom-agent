"""
browser.py — Playwright 기반 브라우저 제어 모듈 (Step 1)

책임:
  - 브라우저 컨텍스트 생성 및 종료
  - 페이지 네비게이션
  - 현재 페이지의 raw HTML 반환
  - 기본 액션(click, type, scroll, go_back) 실행
"""

import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


class BrowserController:
    """Playwright 브라우저 세션을 관리하고 액션을 실행한다."""

    def __init__(self, headless: bool = False, slow_mo: int = 100):
        """
        Args:
            headless: True면 화면 없이 실행 (디버깅 시 False 권장)
            slow_mo: 각 액션 사이 지연(ms) — 사람처럼 보이게 하고 디버깅을 쉽게 한다
        """
        self._headless = headless
        self._slow_mo = slow_mo

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ------------------------------------------------------------------ #
    #  라이프사이클
    # ------------------------------------------------------------------ #

    async def launch(self) -> None:
        """브라우저를 열고 빈 페이지를 준비한다."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        self._page = await self._context.new_page()
        logger.info("브라우저 실행 완료 (headless=%s)", self._headless)

    async def close(self) -> None:
        """모든 리소스를 정리한다."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("브라우저 종료")

    # ------------------------------------------------------------------ #
    #  컨텍스트 매니저 지원  (async with BrowserController() as bc: ...)
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "BrowserController":
        await self.launch()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    #  페이지 상태 조회
    # ------------------------------------------------------------------ #

    @property
    def page(self) -> Page:
        assert self._page is not None, "브라우저가 실행되지 않았습니다. launch()를 먼저 호출하세요."
        return self._page

    async def current_url(self) -> str:
        return self.page.url

    async def get_html(self) -> str:
        """
        상호작용 가능한 요소에 data-agent-id를 주입한 뒤 HTML을 반환한다.
        BeautifulSoup이 부여한 ID와 실제 브라우저 DOM의 셀렉터가 일치하게 된다.
        """
        await self.page.evaluate("""() => {
            const tags = ['a', 'button', 'input', 'select', 'textarea', 'label'];
            const selector = tags.join(',');
            const elements = document.querySelectorAll(selector);
            let counter = 1;
            elements.forEach(el => {
                // hidden / disabled 요소는 파서와 동일하게 스킵
                if (el.type === 'hidden' || el.disabled || el.getAttribute('aria-hidden') === 'true') return;
                el.setAttribute('data-agent-id', String(counter));
                counter++;
            });
        }""")
        return await self.page.content()

    async def get_title(self) -> str:
        return await self.page.title()

    # ------------------------------------------------------------------ #
    #  네비게이션
    # ------------------------------------------------------------------ #

    async def navigate(self, url: str, timeout: int = 30_000) -> None:
        """
        지정한 URL로 이동한다.

        Args:
            url: 이동할 주소
            timeout: 페이지 load 이벤트 제한(ms)
        """
        logger.info("이동 중: %s", url)
        await self.page.goto(url, wait_until="load", timeout=timeout)
        # networkidle 대신 고정 대기 — 광고/트래커가 많은 사이트에서 timeout 방지
        await asyncio.sleep(1.5)
        logger.info("페이지 로드 완료: %s", await self.get_title())

    async def go_back(self) -> None:
        await self.page.go_back(wait_until="load")
        await asyncio.sleep(1.5)
        logger.info("뒤로 가기 완료")

    # ------------------------------------------------------------------ #
    #  액션 실행 (Step 4에서 에이전트가 호출)
    # ------------------------------------------------------------------ #

    async def click_selector(self, css_selector: str) -> None:
        """CSS 셀렉터로 요소를 클릭한다."""
        logger.info("클릭: %s", css_selector)
        await self.page.click(css_selector, timeout=10_000)
        await asyncio.sleep(1.5)

    async def type_text(self, css_selector: str, text: str) -> None:
        """지정한 입력 필드에 텍스트를 입력한다."""
        logger.info("입력 [%s] → '%s'", css_selector, text)
        await self.page.click(css_selector)
        await self.page.fill(css_selector, text)

    async def press_key(self, key: str) -> None:
        """키보드 키를 누른다 (예: 'Enter', 'Escape')."""
        logger.info("키 입력: %s", key)
        await self.page.keyboard.press(key)
        await asyncio.sleep(1.5)

    async def scroll_down(self, pixels: int = 500) -> None:
        """페이지를 아래로 스크롤한다."""
        await self.page.mouse.wheel(0, pixels)
        await asyncio.sleep(0.5)

    async def take_screenshot(self, path: str = "logs/screenshot.png") -> None:
        """디버깅용 스크린샷을 저장한다."""
        await self.page.screenshot(path=path, full_page=False)
        logger.info("스크린샷 저장: %s", path)
