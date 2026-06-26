"""
agent.py — ReAct 기반 메인 에이전트 루프 (Step 4)

Observe → Think → Act 사이클을 반복하며 사용자 태스크를 수행한다.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from agent.browser import BrowserController
from agent.dom_parser import DOMParser
from agent.llm import OllamaClient

logger = logging.getLogger(__name__)

MAX_STEPS = 15  # 무한 루프 방지


@dataclass
class StepRecord:
    step: int
    url: str
    action: dict
    note: str = ""


@dataclass
class AgentResult:
    success: bool
    message: str
    steps: list[StepRecord] = field(default_factory=list)


class WebAgent:
    """
    Observe-Think-Act 루프로 웹 태스크를 자율 수행한다.

    사용 예:
        async with WebAgent() as agent:
            result = await agent.run("네이버에서 날씨 검색해줘")
    """

    def __init__(
        self,
        headless: bool = False,
        model: str = "gemma2:2b",
        max_steps: int = MAX_STEPS,
    ):
        self._browser = BrowserController(headless=headless, slow_mo=300)
        self._parser = DOMParser()
        self._llm = OllamaClient(model=model)
        self._max_steps = max_steps

    async def __aenter__(self) -> "WebAgent":
        await self._browser.launch()
        return self

    async def __aexit__(self, *_) -> None:
        await self._browser.close()
        await self._llm.close()

    # ── 메인 진입점 ──────────────────────────────────────────────────────────

    async def run(self, task: str, start_url: str = "https://www.naver.com") -> AgentResult:
        """
        주어진 태스크를 수행하고 결과를 반환한다.

        Args:
            task: 자연어 목표 (예: "네이버에서 날씨 검색해줘")
            start_url: 시작 페이지
        """
        print(f"\n{'='*55}")
        print(f"  태스크: {task}")
        print(f"{'='*55}")

        await self._browser.navigate(start_url)

        history: list[dict] = []
        records: list[StepRecord] = []
        prev_url = start_url.rstrip("/")

        for step in range(1, self._max_steps + 1):
            print(f"\n── Step {step} ──────────────────────────────────────")

            # ① Observe: DOM 파싱
            html = await self._browser.get_html()
            url  = await self._browser.current_url()
            dom  = self._parser.parse(html, current_url=url)

            print(f"[Observe] URL: {url}")
            print(f"[Observe] 인터랙션 요소 {len(dom.elements)}개 감지")

            # ② Think: LLM 추론
            print("[Think]  LLM 추론 중...")
            action = await self._llm.decide(
                task=task,
                page_context=dom.condensed_text,
                history=history,
            )
            print(f"[Think]  액션 결정: {action}")

            records.append(StepRecord(step=step, url=url, action=action))

            # ③ Act: 액션 실행
            done, result, error_note = await self._execute(action, dom)

            # 성공/실패 여부를 히스토리에 포함해 LLM이 다음 스텝에서 참고하도록 한다
            history_entry = dict(action)
            if error_note:
                history_entry["error"] = error_note
            history.append(history_entry)

            if done:
                return AgentResult(success=result["success"], message=result["message"], steps=records)

            # type 액션 후 URL이 바뀌었으면 태스크 완료로 판단
            current_url = (await self._browser.current_url()).rstrip("/")
            if action.get("action") == "type" and current_url != prev_url:
                print(f"[Auto]   URL 변경 감지 → 태스크 완료")
                return AgentResult(success=True, message=f"검색 완료: {current_url}", steps=records)
            prev_url = current_url

        return AgentResult(
            success=False,
            message=f"최대 스텝({self._max_steps})에 도달했습니다.",
            steps=records,
        )

    # ── 액션 실행기 ──────────────────────────────────────────────────────────

    async def _execute(self, action: dict, dom) -> tuple[bool, dict, str]:
        """
        액션을 실행한다.

        Returns:
            (loop_should_stop, result_dict, error_note)
        """
        act = action.get("action")

        try:
            if act == "done":
                msg = action.get("message", "태스크 완료")
                print(f"[Act]    완료: {msg}")
                return True, {"success": True, "message": msg}, ""

            elif act == "fail":
                msg = action.get("message", "태스크 실패")
                print(f"[Act]    실패: {msg}")
                return True, {"success": False, "message": msg}, ""

            elif act == "click":
                elem = dom.elements.get(action["target_id"])
                if not elem:
                    raise ValueError(f"ID {action['target_id']} 요소를 찾을 수 없습니다.")
                print(f"[Act]    클릭: {elem.css_selector} ('{elem.text}')")
                await self._browser.click_selector(elem.css_selector)

            elif act == "type":
                elem = dom.elements.get(action["target_id"])
                if not elem:
                    raise ValueError(f"ID {action['target_id']} 요소를 찾을 수 없습니다.")
                # <a>, <button>은 type 불가 — LLM 오선택을 코드에서 차단
                if elem.tag not in ("input", "textarea"):
                    # TYPEABLE 요소 중 첫 번째를 자동 선택
                    fallback = next(
                        (e for e in dom.elements.values() if e.tag in ("input", "textarea")),
                        None,
                    )
                    if fallback is None:
                        raise ValueError("페이지에 입력 가능한 요소가 없습니다.")
                    print(f"[Act]    type 대상 자동 교정: ID {elem.elem_id}(<{elem.tag}>) → ID {fallback.elem_id}(<{fallback.tag}>)")
                    elem = fallback
                text = action["text"]
                print(f"[Act]    입력: '{text}' → {elem.css_selector}")
                await self._browser.type_text(elem.css_selector, text)
                # 2B 모델은 "입력 후 Enter" 추론을 못하므로 에이전트가 직접 처리
                print("[Act]    자동 Enter 입력")
                await self._browser.press_key("Enter")

            elif act == "press":
                key = action.get("key", "Enter")
                print(f"[Act]    키 입력: {key}")
                await self._browser.press_key(key)

            elif act == "scroll":
                print("[Act]    스크롤 다운")
                await self._browser.scroll_down()

            elif act == "navigate":
                url = action.get("url", "")
                print(f"[Act]    이동: {url}")
                await self._browser.navigate(url)

            else:
                logger.warning("알 수 없는 액션: %s", act)

        except Exception as e:
            short_err = str(e).split("\n")[0][:120]
            logger.error("액션 실행 오류: %s", e)
            print(f"[Act]    오류: {short_err}")
            return False, {}, f"FAILED: {short_err}"

        return False, {}, ""
