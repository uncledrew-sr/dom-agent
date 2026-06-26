"""
dom_parser.py — BeautifulSoup 기반 DOM 경량화 모듈 (Step 2)

책임:
  - 불필요한 태그 제거 (script, style, meta, noscript 등)
  - 상호작용 가능한 태그에 [ID: N] 부여
  - sLLM이 소화할 수 있는 크기로 텍스트 압축
  - 각 ID → CSS 셀렉터 매핑 테이블 반환 (Step 4에서 Playwright가 사용)
"""

import re
import logging
from dataclasses import dataclass, field
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# 완전히 제거할 태그 (내용 포함)
REMOVE_TAGS = {
    "script", "style", "noscript", "svg", "canvas",
    "meta", "link", "head", "iframe", "template",
}

# 상호작용 가능하다고 판단하는 태그
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "label"}

# 구조 맥락을 위해 텍스트만 추출할 태그 (ID 부여 안 함)
CONTEXT_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "span", "div"}

# 텍스트가 이 길이를 넘으면 잘라냄
MAX_TEXT_LEN = 60
# 최종 출력 문자 상한 (2B 모델 컨텍스트 여유분)
MAX_OUTPUT_CHARS = 6_000


@dataclass
class InteractiveElement:
    """에이전트가 타겟팅할 수 있는 단일 요소."""
    elem_id: int
    tag: str
    text: str          # 버튼 레이블, 링크 텍스트, placeholder 등
    attrs: dict        # href, type, name, value 등 주요 속성
    css_selector: str  # Playwright가 클릭/입력에 사용할 셀렉터


@dataclass
class ParsedDOM:
    """dom_parser가 반환하는 최종 결과물."""
    condensed_text: str                          # sLLM에 넘길 텍스트
    elements: dict[int, InteractiveElement] = field(default_factory=dict)  # ID → 요소 매핑


class DOMParser:
    """HTML을 받아 경량화된 텍스트와 인터랙션 맵을 생성한다."""

    def parse(self, raw_html: str, current_url: str = "") -> ParsedDOM:
        """
        Args:
            raw_html: Playwright의 page.content()
            current_url: 상대 경로 링크 필터링에 사용

        Returns:
            ParsedDOM (condensed_text + elements 매핑)
        """
        soup = BeautifulSoup(raw_html, "lxml")

        # 1단계: 불필요한 태그 일괄 제거
        self._strip_noise(soup)

        # 2단계: JS가 이미 심어둔 data-agent-id를 읽어 매핑 테이블 생성
        # (browser.py의 get_html()이 JS로 주입한 값을 신뢰한다)
        elements: dict[int, InteractiveElement] = {}
        for tag in soup.find_all(INTERACTIVE_TAGS):
            raw_id = tag.get("data-agent-id")
            if not raw_id:
                continue
            try:
                elem_id = int(raw_id)
            except ValueError:
                continue
            elem = self._build_element(tag, elem_id)
            if elem is None:
                continue
            elements[elem_id] = elem

        # 3단계: 전체 DOM을 읽기 쉬운 텍스트로 압축
        condensed = self._condense(soup, elements)

        logger.info(
            "DOM 파싱 완료 — 인터랙션 요소 %d개, 텍스트 %d chars",
            len(elements), len(condensed),
        )
        return ParsedDOM(condensed_text=condensed, elements=elements)

    # ------------------------------------------------------------------ #
    #  내부 헬퍼
    # ------------------------------------------------------------------ #

    def _strip_noise(self, soup: BeautifulSoup) -> None:
        """렌더링에 불필요한 태그를 모두 제거한다."""
        for tag_name in REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 주석 제거
        from bs4 import Comment
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        # 숨겨진 요소 제거 (display:none / visibility:hidden)
        for tag in soup.find_all(style=True):
            if not isinstance(tag, Tag) or not tag.attrs:
                continue
            style = tag.get("style", "") or ""
            if "display:none" in style.replace(" ", "") or \
               "visibility:hidden" in style.replace(" ", ""):
                tag.decompose()

    def _build_element(self, tag: Tag, elem_id: int) -> InteractiveElement | None:
        """태그 하나를 InteractiveElement로 변환한다. 의미없는 태그는 None 반환."""
        # hidden / disabled 요소는 상호작용 불가 — 스킵
        if tag.get("type") == "hidden":
            return None
        if tag.has_attr("disabled"):
            return None
        # aria-hidden 처리
        if tag.get("aria-hidden") == "true":
            return None

        tag_name = tag.name

        # 텍스트 추출 (버튼 레이블, 링크 텍스트 등)
        text = tag.get_text(separator=" ", strip=True)
        text = self._truncate(text)

        # placeholder, value, aria-label도 텍스트로 활용
        if not text:
            text = (
                tag.get("placeholder")
                or tag.get("aria-label")
                or tag.get("title")
                or tag.get("value")
                or ""
            )

        # 완전히 빈 요소는 스킵 (숨겨진 버튼 등)
        if not text and tag_name not in {"input", "textarea", "select"}:
            return None

        # 주요 속성만 추출
        attrs = {}
        for attr in ("href", "type", "name", "value", "placeholder", "aria-label"):
            val = tag.get(attr)
            if val:
                attrs[attr] = self._truncate(str(val), max_len=80)

        css_selector = self._build_selector(tag, elem_id)

        return InteractiveElement(
            elem_id=elem_id,
            tag=tag_name,
            text=text,
            attrs=attrs,
            css_selector=css_selector,
        )

    def _build_selector(self, tag: Tag, elem_id: int) -> str:
        """
        Playwright가 실제로 클릭/입력에 사용할 CSS 셀렉터를 생성한다.
        우선순위: id 속성 > name 속성 > data-agent-id (fallback)
        """
        if tag.get("id"):
            return f'#{tag["id"]}'
        if tag.get("name"):
            return f'{tag.name}[name="{tag["name"]}"]'
        # 아직 data-agent-id가 설정되기 전이므로 예약값으로 생성
        return f'[data-agent-id="{elem_id}"]'

    def _condense(self, soup: BeautifulSoup, elements: dict[int, InteractiveElement]) -> str:
        """
        DOM 전체를 한 줄씩 압축된 텍스트로 변환한다.

        형식 예시:
            [ID: 1] <a> 뉴스 | href=/news
            [ID: 2] <input> 검색어를 입력해 주세요 | type=text name=query
            <h2> 오늘의 날씨
        """
        lines: list[str] = []

        # 인터랙션 요소 먼저 출력 (에이전트가 가장 중요하게 보는 정보)
        lines.append("=== 상호작용 가능한 요소 ===")
        for elem_id, elem in elements.items():
            attr_str = " ".join(f"{k}={v}" for k, v in elem.attrs.items()
                                if k not in ("placeholder",))
            # input/textarea는 [TYPEABLE] 태그를 붙여 LLM이 type 대상을 쉽게 식별하게 한다
            typeable = " [TYPEABLE]" if elem.tag in ("input", "textarea") else ""
            line = f"[ID: {elem_id}] <{elem.tag}>{typeable} {elem.text}"
            if attr_str:
                line += f" | {attr_str}"
            lines.append(line)

        # 페이지 내 주요 텍스트 컨텍스트 추가
        lines.append("\n=== 페이지 주요 텍스트 ===")
        for tag in soup.find_all(["h1", "h2", "h3", "p", "title"]):
            text = tag.get_text(strip=True)
            if text and len(text) > 2:
                lines.append(f"<{tag.name}> {self._truncate(text)}")

        result = "\n".join(lines)

        # 최대 길이 초과 시 잘라냄
        if len(result) > MAX_OUTPUT_CHARS:
            result = result[:MAX_OUTPUT_CHARS] + "\n...(이하 생략)"

        return result

    @staticmethod
    def _truncate(text: str, max_len: int = MAX_TEXT_LEN) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_len] + "…" if len(text) > max_len else text
