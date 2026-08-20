# Home_Compass

청년 임차 가구가 보증금·월세·대출 조건을 함께 비교하고, 상담사와 정책 운영자가 같은 근거를 검토할 수 있도록 만든 주거 금융 의사결정 서비스입니다.

2026 금융 AI Challenge 개인 참가 프로젝트로 개발하고 있습니다. 특정 금융기관의 상품을 추천하거나 심사를 대신하지 않으며, 입력값과 공개 정책·시장 데이터에 기반한 의사결정 보조 정보를 제공합니다.

## 제공 기능

- 시민용 분석: 월 부담액, 초기 필요자금, 비상자금, DSR과 스트레스 금리를 반영한 시나리오 비교
- 정책 탐색: 사용자 조건과 정책 규칙을 대조하고 근거·제외 사유를 함께 표시
- AI 상담: OpenAI 또는 Anthropic 연동, 키가 없을 때는 규칙 기반 오프라인 응답
- 상담원 확장: 판정 근거·내부 필드 확인, 요약본 출력과 데이터 이상 신고
- 정책 운영 워크플로: 정책 원문 수집, 초안 검증, 승인, 배치 처리와 감사 이력

핵심 계산과 판정은 결정론적 엔진이 담당합니다. LLM은 설명과 대화에만 사용되며 계산 결과나 정책 적격 판정을 임의로 바꾸지 않습니다.

## 구조

```text
frontend/                    시민용 Vanilla JS 화면
admin/                       규칙 관리자 검토·승인 화면
backend/src/firsthome/       FastAPI API, 계산 엔진, 인증, 저장소, 수집 파이프라인
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
python -m uvicorn firsthome.main:app --host 127.0.0.1 --port 8000 --workers 1
```

기동 후 사용할 주소:

- 시민 화면: http://127.0.0.1:8000/
- 규칙 관리자 화면: http://127.0.0.1:8000/admin/
- API 문서: http://127.0.0.1:8000/docs
- 상태 확인: http://127.0.0.1:8000/api/health

처음 시드할 때 상담사와 정책 운영자 비밀번호를 지정하려면 서버 기동 전에 `FIRSTHOME_SEED_COUNSELOR_PASSWORD`와 `FIRSTHOME_SEED_RULE_MANAGER_PASSWORD`를 셸 또는 비밀 저장소에서 주입합니다. 실제 값이나 대입문은 저장소 파일에 기록하지 않습니다.

개발 환경에서 두 값을 생략하면 임시 비밀번호가 표준 오류에 한 번 출력됩니다. 공개 배포 설정은 별도 하드닝 작업에서 fail-closed 방식으로 전환할 예정입니다.

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
| `FIRSTHOME_STORE_URL` | 저장소 URL. 기본값은 `backend/var/firsthome.db`를 사용하는 SQLite |
| `FIRSTHOME_LOG_FILE` | 구조화 JSONL 로그 경로 |
| `FIRSTHOME_FRONTEND_DIR` | 시민용 정적 파일 디렉터리 |
| `FIRSTHOME_ADMIN_DIR` | 운영용 정적 파일 디렉터리 |
| `FIRSTHOME_CONTRACTS_DIR` | JSON Schema·OpenAPI 계약 디렉터리 |
| `MOLIT_API_KEY` | 국토교통부 실거래가 OpenAPI 인증키 |

공개 배포에서는 단일 인스턴스·단일 worker와 영구 볼륨의 SQLite를 전제로 합니다. 호스팅별 설정과 보안 경계는 배포 하드닝 후 이 문서에 확정합니다.

## 데이터 파이프라인

시장 데이터 파이프라인은 국토교통부 실거래가 원천을 수집·정규화·검증한 뒤 승인된 스냅샷만 분석에 사용합니다. 정책 파이프라인은 원문과 추출 초안을 분리하고, 계약 검증·승인·감사 이력을 거쳐 활성 규칙으로 전환합니다.

원천 수집 예시:

```powershell
$env:MOLIT_API_KEY = "<service-key>"
Push-Location backend\src
python -m firsthome.ingest.market --from-env
Pop-Location
```

상세 옵션은 같은 디렉터리에서 `python -m firsthome.ingest.market --help`로 확인할 수 있습니다. 저장소 구성은 [저장소 문서](backend/src/firsthome/store/README.md)를 참고하세요.

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

첫 명령은 전체 자동 테스트이고, 두 번째 명령은 생성 계약의 바이트 일치를 확인합니다. 마지막 명령은 Windows에서 `dev.bat`이 실제 서버까지 기동하는 수동 스모크입니다. 전체 테스트 수는 구현과 함께 변하므로 README에 고정하지 않습니다. 실행 결과가 없는 상태에서 완료나 정상 동작을 주장하지 않습니다.

## 고지

Home_Compass의 결과는 정보 제공 목적이며 금융상품의 승인, 법률·세무 자문 또는 투자 권유가 아닙니다. 실제 계약 전에는 최신 원문과 해당 기관의 공식 안내를 확인해야 합니다.
