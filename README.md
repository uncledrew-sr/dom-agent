# sLLM 기반 HTML DOM 트리 파싱 웹 오토메이션 에이전트

> Vision(이미지) 없이 HTML DOM 텍스트만으로 웹을 자율 조작하는 경량 AI 에이전트

---

## 소개

기존 VLM(Vision Language Model) 기반 GUI 에이전트는 화면 스크린샷 전체를 처리하므로 막대한 VRAM과 높은 추론 지연 시간을 요구합니다. 본 프로젝트는 이 한계를 극복하기 위해 **비전 레이어를 완전히 제거**하고, 웹 브라우저의 HTML DOM 트리를 텍스트로 파싱하여 로컬 소형 언어 모델(Gemma-2-2B)과 연동하는 **초경량 웹 오토메이션 에이전트**를 구현합니다.

MacBook Pro 14(Apple Silicon) 단일 온디바이스 환경에서 클라우드 API 없이 실시간으로 동작하며, 원본 HTML 대비 컨텍스트 토큰 사용량을 약 98% 절감합니다.

---

## 시스템 아키텍처

```
사용자 명령 ("네이버에서 날씨 검색해줘")
        │
        ▼
┌───────────────────────────────────────────┐
│              ReAct 에이전트 루프            │
│                                           │
│  ① Observe   Playwright → raw HTML 수집   │
│      │       JS로 data-agent-id 주입       │
│      ▼                                    │
│  ② Think     BeautifulSoup DOM 경량화     │
│      │       noise 제거 + ID 매핑          │
│      │       condensed_text → Gemma-2-2B  │
│      ▼                                    │
│  ③ Act       JSON 액션 파싱               │
│              Playwright 실행              │
│              (click / type / press …)     │
└───────────────────────────────────────────┘
        │
        ▼
   태스크 완료 (URL 변경 감지 또는 done 액션)
```

---

## 기술 스택

| 분류 | 기술 | 버전 | 역할 |
|---|---|---|---|
| **언어** | Python | 3.10+ | 전체 구현 |
| **브라우저 제어** | Playwright | 1.60+ | 동적 웹 페이지 제어 |
| **DOM 파싱** | BeautifulSoup4 | 4.15+ | HTML 경량화 및 요소 추출 |
| **HTML 파서** | lxml | 6.1+ | 고속 HTML 파싱 엔진 |
| **LLM 런타임** | Ollama | 최신 | 로컬 모델 서빙 |
| **LLM 모델** | Gemma-2-2B | 2B params | 웹 액션 추론 (INT4 양자화) |
| **HTTP 클라이언트** | httpx | 0.28+ | Ollama API 비동기 통신 |
| **하드웨어** | Apple Silicon (M-series) | MacBook Pro 14 | 온디바이스 추론 |

---

## 프로젝트 구조

```
dom-agent/
├── agent/
│   ├── __init__.py
│   ├── browser.py        # Playwright 브라우저 제어 모듈
│   ├── dom_parser.py     # BeautifulSoup DOM 경량화 + ID 부여
│   ├── llm.py            # Ollama API 연동 + JSON 출력 강제
│   └── agent.py          # ReAct 메인 에이전트 루프
├── tests/
│   ├── test_step1_browser.py
│   ├── test_step2_dom.py
│   └── test_step3_llm.py
├── output/
│   └── risk_management.md
├── logs/                 # 스크린샷 저장
├── main.py               # 실행 진입점
├── requirements.txt
└── README.md
```

---

## 설치 및 실행

### 1. 사전 요구사항

- Python 3.10 이상
- [Ollama](https://ollama.com) 설치 후 실행

```bash
# Ollama 설치 후 모델 다운로드
ollama pull gemma2:2b
```

### 2. 프로젝트 설정

```bash
# 저장소 클론
git clone <repository-url>
cd dom-agent

# 가상환경 생성 및 의존성 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Playwright 브라우저 설치
playwright install chromium
```

### 3. 실행

```bash
# Ollama 서버 실행 (별도 터미널)
ollama serve

# 에이전트 실행
.venv/bin/python3 main.py "네이버에서 날씨 검색해줘"
.venv/bin/python3 main.py "네이버 뉴스 페이지로 이동해줘"
```

---

## 핵심 구현 상세

### DOM 경량화 파이프라인

전체 HTML(~300KB)을 소형 모델이 처리 가능한 크기(~6KB)로 압축합니다.

```
원본 HTML (~300KB)
  → script / style / svg / 숨겨진 요소 제거
  → <a>, <button>, <input>, <select>, <textarea> 추출
  → data-agent-id 부여 (JS 주입 방식)
  → condensed_text 생성 (~6KB, 약 98% 절감)
```

**condensed_text 출력 예시:**
```
=== 상호작용 가능한 요소 ===
[ID: 13] <input> [TYPEABLE] 검색어를 입력해 주세요 | type=text name=query
[ID: 14] <button> 검색
[ID: 15] <a> 뉴스 | href=/news

=== 페이지 주요 텍스트 ===
<title> NAVER
<h2> 연합뉴스
```

### JSON 액션 포맷

Gemma-2-2B는 항상 아래 포맷의 JSON을 출력합니다:

```json
{"action": "type",  "target_id": 13, "text": "날씨"}
{"action": "click", "target_id": 14}
{"action": "press", "key": "Enter"}
{"action": "done",  "message": "태스크 완료"}
```

### 2B 모델 한계 보완 전략

소형 모델의 추론 한계를 규칙 기반 후처리 레이어로 보완합니다:

| 한계 | 보완 전략 |
|---|---|
| 입력 후 Enter를 스스로 안 누름 | `type` 액션 직후 에이전트가 자동으로 Enter 실행 |
| `<a>` 링크를 입력창으로 오인 | `type` 대상이 `<input>`/`<textarea>` 아니면 자동 교정 |
| `done` 액션 선택 불안정 | URL 변경 감지 시 에이전트가 직접 완료 처리 |
| JSON 포맷 미준수 | 3단계 fallback 파싱 + 최대 3회 재시도 |

---

## 개발 환경

- **OS:** macOS
- **하드웨어:** MacBook Pro 14 (Apple Silicon)
- **메모리 점유:** Gemma-2-2B INT4 기준 약 2GB 미만

---

# dom-agent
