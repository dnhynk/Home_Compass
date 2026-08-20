# KB 첫집 나침반 (FirstHome Compass) — 프로토타입

> "내가 지금 얼마짜리 집에 살아도 되는가?"에 **숫자로** 답하고,
> 그 결정을 실행할 **정책·금융상품까지 연결**하는 청년 주거 금융 의사결정 에이전트.

---

## 1. 실행법 (3줄)

```bat
cd C:\Users\dongh\KB_AI\prototype
run.bat
:: 브라우저에서 http://127.0.0.1:8000 접속
```

`run.bat`은 의존성 설치 → 엔진 테스트 → uvicorn 기동을 한 번에 수행합니다.
수동으로 실행하려면:

```bat
python -m pip install -r requirements.txt
cd backend
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

### 🔑 API 키는 선택 사항입니다

**키가 하나도 없어도 전 기능이 정상 동작합니다.** 프로필 분석·시나리오 비교·정책 매칭·
리스크 스캔은 전부 로컬 결정론적 엔진이 계산하므로 네트워크조차 필요 없습니다.
AI 상담 탭만 규칙 기반 한국어 템플릿(`offline` 모드)으로 응답합니다.

키를 넣으면 **LLM 상담이 활성화**되어, 자연어 질문을 받아 4대 엔진을 tool calling으로
호출하고 근거 기반 답변을 생성합니다.

| 우선순위 | 환경변수 | 프로바이더 | `/api/health` 의 `llm` |
|---|---|---|---|
| 1 | `OPENAI_API_KEY` | OpenAI function calling | `openai` |
| 2 | `ANTHROPIC_API_KEY` | Anthropic tool use | `anthropic` |
| 3 | (없음) | 규칙 기반 한국어 템플릿 | `offline` |

설정 방법 — 리포지토리 루트에 `.env` 파일을 두면 자동으로 읽습니다
(`prototype/.env.example` 참고, `python-dotenv` 불필요):

```
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=            # 비워두면 gpt-5.4-mini
```

셸 환경변수로도 됩니다. 셸 값이 `.env` 값보다 우선합니다.

```bat
set OPENAI_API_KEY=sk-proj-...
```

> `.env`는 `.gitignore`에 등록되어 있으며 `prototype/` 안에는 실제 키를 두지 않습니다.
> 값에 따옴표나 홑화살괄호가 섞여도(`<sk-proj-...>`) 자동으로 제거됩니다.

---

## 2. 아키텍처

```
                          ┌───────────────────────────────────────────┐
   브라우저 (Vanilla JS)   │  prototype/frontend/  index.html/app.js   │
                          │  프로필 입력 → 대시보드 → AI 상담 채팅      │
                          └────────────────────┬──────────────────────┘
                                               │ fetch (JSON)
                     ┌─────────────────────────▼──────────────────────┐
                     │  FastAPI  app.py   (CORS + 정적파일 서빙)       │
                     │  /api/health  /api/regions                      │
                     │  /api/analyze  /api/chat                        │
                     └───────┬─────────────────────────┬───────────────┘
                             │                         │
              ┌──────────────▼───────────┐   ┌─────────▼──────────────────┐
              │  engines/__init__.py     │   │  engines/agent.py   (A1)   │
              │  analyze() 오케스트레이션 │◀──│  TOOL_SPECS 단일 정의       │
              │  E1 → E2 → E3 → E4       │   │   ├ to_openai_tools()      │
              └──────────────┬───────────┘   │   └ to_anthropic_tools()   │
                             │               │  ┌──────────────────────┐  │
                             │               │  │1 OpenAI  (function   │  │
                             │               │  │          calling)    │  │
                             │               │  │2 Anthropic (tool use)│  │
                             │               │  │3 offline 한국어 템플릿│  │
                             │               │  └──────────────────────┘  │
                             │               └─────────────┬──────────────┘
                             │                             │
                             │               ┌─────────────▼──────────────┐
                             │               │  engines/config.py         │
                             │               │  .env 탐색·파싱 (무의존성)  │
                             │               │  프로바이더 우선순위 결정   │
                             │               └────────────────────────────┘
      ┌──────────────┬───────┴───────┬────────────────┐
      ▼              ▼               ▼                ▼
┌───────────┐  ┌───────────┐  ┌────────────┐  ┌────────────┐
│ E1        │  │ E2        │  │ E3         │  │ E4         │
│ 주거지불   │  │ 정책·상품  │  │ 전월세     │  │ 보증금     │
│ 능력      │  │ 적격성     │  │ 총비용     │  │ 리스크     │
│affordabi- │  │eligibility│  │ TCO / NPV  │  │ 스캐너     │
│lity.py    │  │.py        │  │ tco.py     │  │ risk.py    │
└─────┬─────┘  └─────┬─────┘  └─────┬──────┘  └─────┬──────┘
      └──────────────┴──────────────┴───────────────┘
                             │
                   ┌─────────▼──────────┐
                   │ data/policies.json │  정책 10건 (source + disclaimer 필수)
                   │ data/regions.json  │  지역 10곳 (서울4·경기2·지방4)
                   └────────────────────┘

  핵심 설계 원칙: LLM은 자연어 인터페이스일 뿐, 숫자는 100% 결정론적 엔진이 계산한다.
  → 4대 엔진은 순수 함수(입출력만 존재, 시계·난수·I/O 없음)이며
    모든 반환값에 `rationale: list[str]` 근거 배열을 포함한다. (설명가능성 / XAI)
```

### 디렉토리

```
prototype/
├─ backend/
│  ├─ app.py                 FastAPI 진입점 (CORS · 정적 서빙 · 오류 봉투)
│  ├─ engines/
│  │  ├─ __init__.py         analyze() 오케스트레이터 + 데이터 로더
│  │  ├─ config.py           .env 탐색/파싱 + 프로바이더 우선순위 (무의존성)
│  │  ├─ common.py           공용 순수 헬퍼 (금액 포맷·반올림)
│  │  ├─ affordability.py    E1 주거지불능력
│  │  ├─ eligibility.py      E2 정책·상품 적격성 룰엔진
│  │  ├─ tco.py              E3 전월세 총비용/NPV 비교
│  │  ├─ risk.py             E4 전세보증금 리스크 스캐너
│  │  └─ agent.py            A1 3단 프로바이더 (OpenAI / Anthropic / offline)
│  ├─ data/{policies,regions}.json
│  └─ tests/test_engines.py  pytest 44개
├─ frontend/                 (W2 담당)
├─ .env.example              키 템플릿 (실제 키는 리포지토리 루트 .env 에)
├─ requirements.txt
├─ run.bat
└─ README.md
```

---

## 3. API 표

Base URL: `http://127.0.0.1:8000`

| Method | Path | 권한 | 설명 |
|---|---|---|---|
| `GET` | `/api/health` | 익명 | 헬스체크 · LLM 프로바이더 · **배치 상태 · 데이터 신선도** (SPEC 8.1) |
| `GET` | `/api/regions` | 익명 | 지역 시세 |
| `GET` | `/api/meta` | 익명 | 엔진 버전 · 고지 문구 |
| `POST` | `/api/analyze` | 익명 (로그인 시 확장) | **메인** — E1~E4 일괄 실행 + `dataGrade` · `provenance` (D-13) |
| `POST` | `/api/chat` | 익명 | 자연어 상담 (tool-calling) |
| `POST` | `/api/auth/login` · `/logout` | — | 서버 세션 (`HttpOnly` 쿠키 + CSRF) |
| `GET` | `/api/auth/session` | 익명 | 내가 누구인가. 익명은 401 이 아니라 200 |
| `POST` | `/api/reports` | **상담원**+ | 이상 신고 생성 (SPEC 6.4) |
| `GET` | `/api/admin/drafts` | **규칙관리자** | 추출 초안 대기 큐 |
| `GET` | `/api/admin/drafts/{id}` | **규칙관리자** | 초안 상세 — 원문 세그먼트 · 근거 span |
| `GET` | `/api/admin/drafts/{id}/impact` | **규칙관리자** | 승인 시 판정이 어떻게 바뀌는가 (SPEC 4.4 #2) |
| `POST` | `/api/admin/drafts/{id}/approve` · `/reject` | **규칙관리자** | 승인·반려. 반려에는 사유가 필수 |
| `POST` | `/api/admin/drafts/batch-approve` | **규칙관리자** | 일괄 승인 — 반영은 원자적, 기록은 건별 |
| `GET` | `/api/admin/reports` | **규칙관리자** | 이상 신고 큐 (초안과 별도 유형) |
| `GET` | `/api/admin/audit` | **규칙관리자** | 감사추적 (append-only) |
| `GET` | `/api/admin/status` | **규칙관리자** | 관측 지표 (SPEC 7.2) |
| `GET` | `/docs` | 익명 | 자동 생성 API 문서 (Swagger UI) |

> **이 표는 요약이고 정본은 `contracts/openapi.json` 이다.** 응답 필드·단위·반올림·타임아웃은
> 그 파일이 코드에서 생성하며 재생성 diff 테스트가 커밋본과 바이트 비교한다 (SPEC D-12).
> **권한 검사는 API 계층이 한다** — 화면이 버튼을 숨기는 것으로 대신하지 않는다 (SPEC 6.1).

### 열거형

| 필드 | 값 |
|---|---|
| `affordability.band` | `safe` \| `caution` \| `risk` |
| `policies[].status` | `eligible` \| `conditional` \| `ineligible` |
| `scenarios[].verdict` | `affordable` \| `stretch` \| `unaffordable` |
| `scenarios[].type` | `jeonse` \| `monthly` |
| `risk.factors[].impact` | `low` \| `medium` \| `high` |
| `risk.band` | `low` \| `medium` \| `high` |
| 요청 `preferredType` | `jeonse` \| `monthly` \| `any` |

### 오류 응답 (공통)

모든 4xx/5xx는 동일한 봉투를 사용합니다.

```json
{ "error": { "code": "invalid_region", "message": "알 수 없는 지역 코드입니다: 00000" } }
```

| HTTP | code | 발생 조건 |
|---|---|---|
| 400 | `invalid_region` | `regionCode`가 `regions.json`에 없음 |
| 422 | `validation_error` | 타입/범위/열거형 위반 |
| 500 | `internal_error` | 처리되지 않은 예외 |

### 요청 예시

```bat
curl -X POST http://127.0.0.1:8000/api/analyze ^
  -H "Content-Type: application/json" ^
  -d "{\"age\":28,\"annualIncomeKRW\":42000000,\"monthlyNetIncomeKRW\":3000000,\"liquidAssetsKRW\":40000000,\"existingDebtMonthlyKRW\":300000,\"householdSize\":1,\"regionCode\":\"11440\",\"isHomeless\":true,\"isNewlywed\":false,\"isSMEEmployee\":true,\"preferredType\":\"any\"}"
```

모든 요청 필드는 **선택**입니다(누락 시 안전한 기본값 사용). `regionCode`를 비우면
첫 번째 지역이 기본 적용됩니다.

---

## 4. 4대 엔진 산식 요약

| 엔진 | 핵심 산식 | 주요 상수 |
|---|---|---|
| **E1** 주거지불능력 | `상한 = min(가처분소득×30%, 소득−생활비−부채−버퍼)`<br>`권장 = min(상한×85%, 소득×25%)` | 생활비 1인 120만원(+가구원), 버퍼 소득의 10% |
| **E2** 적격성 | 연령·소득·자산·무주택·신혼·중소기업·지역 요건을 항목별로 판정<br>하드 요건 실패 → `ineligible` / 외부 확인 필요 → `conditional` | 경계값 마진 5% |
| **E3** 총비용 | `TCO = 이자 + 월세 + 관리비 + 기회비용 + 보증료` (5년)<br>`NPV = Σ Cₜ/(1+r)^t`, `월환산 = TCO/60` | 기회비용·할인율 연 3.0%, 보증료 연 0.15%, LTV 80% |
| **E4** 보증금 리스크 | 전세가율 + 보증보험 가능성 + 대출비중 + 보증금 규모 + 지역 여건<br>합산 0~100 (낮을수록 안전) | `low ≤34`, `medium ≤64`, `high >64` |

> **보증금은 비용이 아니다.** 계약 종료 시 돌려받으므로 총비용에는 포함하지 않고,
> 묶이는 자기자본의 **기회비용만** 반영합니다. 이것이 단순 월세 비교와의 결정적 차이입니다.

---

## 5. 테스트

```bat
cd backend
python -m pytest tests -q
```

44개 테스트가 4대 엔진의 경계값(0소득 / 고소득 / 과다부채 / 다인가구 /
연령·지역 부적격 / 보증금 0원), 결정론성, API 계약 형태, 오류 봉투,
그리고 프로바이더 추상화(.env 파싱·우선순위·툴 스키마 변환 일치)를 검증합니다.

테스트는 **키가 있어도 절대 실제 API를 호출하지 않습니다** — LLM 관련 테스트는
`no_keys` 픽스처로 offline 경로를 강제합니다.

---

## 6. 데이터 정직성 고지

- `data/*.json`의 모든 정책·시세 수치는 **프로토타입 시연용 예시**이며, 각 항목에
  `source`(출처 기관)와 `disclaimer` 필드를 필수로 포함합니다.
- 실제 KB 상품의 구체적 금리·한도는 사용하지 않았습니다. 정책 조건은 공개된
  일반 요건(만 19~34세, 무주택 등) 수준으로만 기술했습니다.
- 응답의 `meta.disclaimer`와 각 정책의 `disclaimer`가 항상 함께 전달되므로
  UI 하단에 반드시 노출해야 합니다.

> 프로토타입 시연용 예시 수치입니다. 실제 조건은 취급 금융기관 고시 기준을 따릅니다.

---

## 7. LLM 프로바이더 설계

### 툴 스키마 단일 정의

4대 엔진의 툴 스키마는 `engines/agent.py`의 **`TOOL_SPECS` 한 곳에만** 정의되어 있고,
`to_openai_tools()` / `to_anthropic_tools()`가 각 SDK 포맷으로 기계적으로 변환합니다.
두 프로바이더의 툴 정의가 구조적으로 어긋날 수 없으며, 이를 테스트로 강제합니다.

```
TOOL_SPECS  ─┬─ to_openai_tools()    → {"type":"function","function":{name,description,parameters}}
             └─ to_anthropic_tools() → {name, description, input_schema}
```

### 모델 선택 근거

기본 모델은 **`gpt-5.4-mini`** 입니다 — 기억에 의존한 하드코딩이 아니라, 실제 키로
`client.models.list()`(121개 확인) 후 후보군에 **실제 function calling 요청을 보내
검증**하고, 전체 2턴 루프(툴 콜 → 엔진 결과 주입 → 한국어 최종 답변) 품질과 지연을
비교해 선정했습니다. mini 티어라 대화형 응답에 적합한 비용·지연을 유지하면서도,
비교 대상 중 유일하게 `stretch` 판정과 실제 의사결정 변수(보증금 조달 가능 여부)까지
짚어냈습니다. `OPENAI_MODEL` 환경변수로 덮어쓸 수 있습니다.

### `.env` 로딩

`python-dotenv`에 의존하지 않고 `engines/config.py`가 직접 처리합니다.
`prototype/backend/`에서 상위 디렉토리로 올라가며 `.env`를 탐색하고,
BOM·CRLF·`export ` 접두사·주석을 허용하며, 값에서 앞뒤 **공백·따옴표·홑화살괄호(`<>`)**
를 반복 제거합니다(`"<sk-proj-...>"` → `sk-proj-...`). 실제로 발생한 붙여넣기 사고를
방어하기 위한 것이며, 값 내부 문자는 건드리지 않습니다.

허용 목록(`OPENAI_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`)에
있는 키만 가져오므로 `.env`가 `PATH` 같은 변수를 오염시킬 수 없습니다.
이미 설정된 셸 환경변수가 `.env` 값보다 우선하므로, `set OPENAI_API_KEY=` 로
일시적으로 offline 모드를 강제할 수 있습니다.

### 장애 시 동작

live 프로바이더 호출이 어떤 이유로든(SDK 미설치·네트워크·API 오류·빈 응답) 실패하면
**예외를 사용자에게 노출하지 않고** offline 템플릿 결과로 자동 강등하며, 응답에
`degradedFrom` 필드로 어떤 프로바이더가 실패했는지 남깁니다. 시연 중 스택 트레이스가
화면에 뜨는 일은 없습니다.
