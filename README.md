# Home_Compass

A housing-finance decision aid for young Korean renters: deterministic engines compute affordability, 5-year costs, policy eligibility and deposit risk, while an LLM only explains the results.

청년 임차 가구가 보증금·월세·대출 조건을 함께 비교하고, 상담사와 정책 운영자가 같은 근거를 검토할 수 있도록 만든 주거 금융 의사결정 서비스입니다.

2026 금융 AI Challenge 개인 참가 프로젝트로 개발하고 있습니다. 특정 금융기관의 상품을 추천하거나 심사를 대신하지 않으며, 입력값과 공개 정책·시장 데이터에 기반한 의사결정 보조 정보를 제공합니다.

## 왜 만들었나

- **비교 기준이 흩어져 있다.** 월세, 전세대출 이자, 관리비, 보증금의 기회비용이 서로 다른 화면과 단위로 제시되어, 월 납입액만 보면 보증금 부담과 장기 총비용이 가려집니다.
- **정책 조건이 복잡하고 자주 바뀐다.** 나이·소득·자산·무주택·지역 조건이 정책마다 다르고 공고문은 비정형 문서라, 검색만으로는 "왜 제외되는가"와 "무엇을 더 확인해야 하는가"에 답하기 어렵습니다.
- **금융 판단을 LLM에 맡기면 흔들린다.** 언어모델이 금액 계산과 자격 판정까지 하면 같은 입력에도 결과가 달라지고, 잘못 추출된 규칙은 모든 사용자에게 퍼집니다.

## 핵심 기능

- 시민용 분석: 생활비·기존 부채 상환액·비상자금 버퍼를 뺀 월 주거비 상한과 권장액, 전세·반전세·월세 시나리오의 5년 총비용(TCO)·현재가치(NPV)·월 환산비용 비교
- 정책 탐색: 사용자 조건과 정책 규칙을 대조하고 조건별 근거·제외 사유를 함께 표시
- 보증금 위험 점검: 전세가율, 대출 비중, 보증금 규모, 지역 시장 상황을 반영한 위험 신호
- AI 상담: OpenAI 또는 Anthropic 연동, 키가 없거나 호출이 실패하면 규칙 기반 오프라인 응답
- 상담원 확장: 판정 근거·내부 필드 확인, 요약본 출력과 정보 수정 요청(데이터 이상 신고)
- 정책 운영 워크플로: 정책 원문 수집, 규칙 초안 검증, 판정 영향도 확인, 승인·반려, 일괄 승인과 감사 이력

## 설계 포인트

- **판정 경로에 LLM이 없습니다.** 금액과 적격 판정은 `backend/src/home_compass/engines/`의 네 결정론적 엔진(지불능력·정책 적격·총비용·보증금 위험)이 계산합니다. 엔진 패키지가 `llm`을 import하지 않는다는 의존 방향은 아키텍처 테스트가 강제합니다.
- **LLM은 도구를 호출해 설명만 합니다.** 상담 에이전트는 엔진을 도구(tool calling)로 호출해 받은 숫자만 인용하도록 지시되며, 직접 계산한 숫자를 쓰지 않습니다. 설명 문장이 엔진 값을 잘못 옮길 가능성은 남아 있으며, 판정 결과 자체는 바뀌지 않습니다.
- **AI가 만든 규칙은 사람 승인 전까지 효력이 없습니다.** 정책 원문에서 LLM이 추출한 규칙 초안은 스키마·원문 인용 검증을 거쳐 검토 큐에 쌓이고, 규칙 관리자가 원문 근거와 기존 사례의 판정 변화를 확인해 승인해야 활성 규칙이 됩니다.
- **모든 사실에 출처를 붙입니다.** 분석 응답에는 데이터의 출처·관측 시각·검증 상태(provenance)와 데이터 등급이 함께 실립니다. 검증되지 않은 값은 거부하지 않고 등급을 붙여 드러냅니다.
- **모델 상수의 근거를 계약으로 관리합니다.** 엔진이 쓰는 상수는 `contracts/model_constants.json`에 값·단위·출처 분류와 함께 등재되고, 규범적으로 고른 값은 감도분석 대상이 됩니다.
- **백엔드 없이도 같은 숫자를 냅니다.** `frontend/local_engine.js`는 엔진의 JS 이식이며, 상수·정책·지역 데이터는 생성물(`frontend/generated/`)에서 가져옵니다. 같은 입력에 같은 결과가 나오는지 테스트로 대조합니다.

## 기술 스택

- 백엔드: Python 3.11+, FastAPI, Uvicorn, Pydantic
- 저장소: SQLite (기본값), JSON Schema 2020-12 계약 검증(`jsonschema`)
- 인증: Argon2id 비밀번호 해시(`argon2-cffi`), 세션 쿠키와 CSRF 방어, 상담원·규칙 관리자 역할 구분
- LLM: OpenAI·Anthropic SDK (선택), 키가 없으면 오프라인 템플릿
- 프론트엔드: Vanilla JS·HTML·CSS (시민 화면, 규칙 관리자 화면)
- 외부 데이터: 국토교통부 실거래가 OpenAPI
- 테스트·배포: pytest, GitHub Actions, Docker, Render Blueprint(`render.yaml`)

## 현재 상태

[![CI](https://github.com/dnhynk/Home_Compass/actions/workflows/ci.yml/badge.svg)](https://github.com/dnhynk/Home_Compass/actions/workflows/ci.yml)

- 2026 금융 AI Challenge 예선 제출용 MVP입니다. 예선 기간에는 개인 PC와 Tailscale Funnel로 공개 운영했으며, 공개 데모 URL은 이 저장소에 싣지 않습니다.
- 기본 데이터는 서울 등 10개 지역 시세와 8개 정책입니다. 정책 수치는 시연용 예시이며, 지역 시세 일부 필드는 출처가 특정되지 않은 미검증(`unverified`) 값으로 표시됩니다.
- 정책 검토 큐에는 LLM 추출 결과로 만든 규칙 초안이 시드됩니다. 새 공고의 상시 자동 수집·재추출은 연결되어 있지 않습니다.
- 세션 저장소가 프로세스 메모리에 있어 단일 인스턴스·단일 worker로만 운영할 수 있습니다.

## 구조

```text
frontend/                    시민용 Vanilla JS 화면
admin/                       규칙 관리자 검토·승인 화면
backend/src/home_compass/       FastAPI API, 계산 엔진, 인증, 저장소, 수집 파이프라인
backend/tests/               단위·통합·계약·교차 검증 테스트
contracts/                   손으로 쓴 검증 계약과 생성된 OpenAPI 스냅샷
data/                        정책 원문 입력
scripts/                     개발 기동, 시드, 수집, 계약 생성, 검증 도구
docs/                        설계·운영·검증 문서
```

브라우저와 API는 같은 오리진에서 제공됩니다. 현재 세션 저장소는 프로세스 메모리를 사용하므로 Uvicorn은 반드시 단일 worker로 실행해야 합니다.

## 빠른 시작

요구 사항은 Python 3.11 이상입니다. Windows에서는 저장소 루트에서 다음 명령으로 의존성 설치, 테스트, 데이터 시드와 서버 기동을 한 번에 수행할 수 있습니다.

```bat
scripts\dev.bat
```

수동으로 실행하려면:

```powershell
python -m pip install -r backend\requirements.txt
python scripts\seed_store.py
Set-Location backend\src
python -m uvicorn home_compass.main:app --host 127.0.0.1 --port 8000 --workers 1
```

기동 후 사용할 주소:

- 시민 화면: http://127.0.0.1:8000/
- 규칙 관리자 화면: http://127.0.0.1:8000/admin/
- API 문서: http://127.0.0.1:8000/docs
- 상태 확인: http://127.0.0.1:8000/api/health

처음 시드할 때 상담사와 정책 운영자 비밀번호를 지정하려면 서버 기동 전에 `HOME_COMPASS_SEED_COUNSELOR_PASSWORD`와 `HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD`를 셸 또는 비밀 저장소에서 주입합니다. 실제 값이나 대입문은 저장소 파일에 기록하지 마세요.

개발 환경에서 두 값을 생략하면 임시 비밀번호가 표준 오류에 한 번 출력됩니다. 공개 배포는
`HOME_COMPASS_ENV=production`일 때 두 비밀번호(각 16자 이상)와 Secure 쿠키 설정이 없으면
기동을 거부합니다.

## 선택적 LLM 연동

저장소 루트의 `.env.example`을 `.env`로 복사하고 사용할 제공자의 키를 입력합니다.

```powershell
Copy-Item .env.example .env
```

- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`

우선순위는 OpenAI, Anthropic, 오프라인 순입니다. API 키가 없어도 시민 분석, 정책 판정, 리스크 계산과 운영 워크플로는 동작합니다.

## 저장소와 경로 설정

주요 런타임 환경변수:

| 변수 | 용도 |
| --- | --- |
| `HOME_COMPASS_STORE_URL` | 저장소 URL. 기본값은 `backend/var/home_compass.db`를 사용하는 SQLite |
| `HOME_COMPASS_LOG_FILE` | 구조화 JSONL 로그 경로 |
| `HOME_COMPASS_FRONTEND_DIR` | 시민용 정적 파일 디렉터리 |
| `HOME_COMPASS_ADMIN_DIR` | 운영용 정적 파일 디렉터리 |
| `HOME_COMPASS_CONTRACTS_DIR` | JSON Schema·OpenAPI 계약 디렉터리 |
| `MOLIT_API_KEY` | 국토교통부 실거래가 OpenAPI 인증키 |

공개 배포에서는 단일 인스턴스·단일 worker와 영구 볼륨의 SQLite를 전제로 합니다.

## 공개 배포

예선 제출 서비스는 개인 PC에서 서버를 루프백에만 바인딩하고 Tailscale Funnel로 HTTPS 주소를
연결해 운영했습니다. 절차는 [`docs/competition/PC_HOSTING.md`](docs/competition/PC_HOSTING.md)에 있습니다.

저장소 루트의 `Dockerfile`은 저장소 시드, 운영 설정 검증, 단일 worker 기동을 한 경로로
묶습니다. `render.yaml`은 Singapore 리전, 영구 디스크, HTTPS Secure 쿠키, 헬스체크를
포함한 Render Blueprint로, 선택 가능한 유료 대안입니다. 두 운영 계정 비밀번호는 Blueprint
생성 화면에서 비밀값으로 입력하며 저장소에는 남지 않습니다.

로컬에서 컨테이너만 스모크하려면 HTTPS 프록시가 없으므로 개발 모드로 실행합니다.
Render 배포는 `render.yaml`이 운영 모드와 Secure 쿠키를 강제합니다.

```powershell
docker build -t home-compass .
docker run --rm -p 8000:8000 `
  -e HOME_COMPASS_ENV=development `
  -e HOME_COMPASS_COOKIE_SECURE=false `
  home-compass
```

실제 제출 순서와 외부 URL 검증 방법은
[`docs/competition/SUBMISSION_RUNBOOK.md`](docs/competition/SUBMISSION_RUNBOOK.md)에 있습니다.

## 데이터 파이프라인

시장 데이터 파이프라인은 국토교통부 실거래가 원천을 수집·정규화·검증한 뒤 승인된 스냅샷만 분석에 사용합니다. 정책 파이프라인은 원문과 추출 초안을 분리하고, 계약 검증·승인·감사 이력을 거쳐 활성 규칙으로 전환합니다.

원천 수집 예시:

```powershell
$env:MOLIT_API_KEY = "<service-key>"
Push-Location backend\src
python -m home_compass.ingest.market --from-env
Pop-Location
```

상세 옵션은 같은 디렉터리에서 `python -m home_compass.ingest.market --help`로 확인할 수 있습니다. 저장소 구성은 [저장소 문서](backend/src/home_compass/store/README.md)를 참고하세요.

## API와 계약

주요 공개 API는 지역 목록, 시장·정책 메타데이터, 시민 분석, AI 상담, 인증과 리포트·정책 운영 엔드포인트로 구성됩니다. 실행 중인 서버의 `/docs`에서 현재 계약을 확인할 수 있습니다.

HTTP 계약의 커밋된 스냅샷은 `contracts/openapi.json`이며 애플리케이션 코드에서 생성됩니다. 같은 디렉터리의 provenance·규칙 초안·모델 상수 스키마는 사람이 관리하는 입력 계약입니다. 생성 산출물은 다음 명령으로 갱신합니다.

```powershell
python scripts\gen_contracts.py
```

## 검증

```powershell
python -m pytest backend\tests -q
python scripts\gen_contracts.py --check
python scripts\check_dev_bat.py
```

첫 명령은 전체 자동 테스트이고, 두 번째 명령은 생성 계약의 바이트 일치를 확인합니다. 마지막 명령은 Windows에서 `dev.bat`이 실제 서버까지 기동하는 수동 스모크입니다.

## 상세 문서

- [기술 스펙](docs/engineering/SPEC.md): 범위 결정, AI 활용 경계, 데이터 계보, 검증 기준
- [시장 데이터 도출](docs/engineering/market/DERIVATION.md), [수집 원천](docs/engineering/collection/SOURCES.md)
- [실사 기록](docs/engineering/diligence/FINDINGS.md): 모델 상수와 정책 조건의 출처 조사
- [계약 디렉터리](contracts/README.md), [저장소 문서](backend/src/home_compass/store/README.md)
- [제출 런북](docs/competition/SUBMISSION_RUNBOOK.md), [PC 배포 운영](docs/competition/PC_HOSTING.md), [제출 전 최종 감사](docs/competition/FINAL_AUDIT_2026-09-05.md)
- 개발 운영 기록: [코디네이터 운영 절차](docs/engineering/COORDINATION.md), [인계 문서](docs/engineering/HANDOFF.md), [리허설](docs/engineering/REHEARSAL.md)

## 고지

Home_Compass의 결과는 정보 제공 목적이며 금융상품의 승인, 법률·세무 자문 또는 투자 권유가 아닙니다. 실제 계약 전에는 최신 원문과 해당 기관의 공식 안내를 확인해야 합니다.
