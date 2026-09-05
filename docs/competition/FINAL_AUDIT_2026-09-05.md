# 제출 전 최종 감사 — 2026-09-05

## 판정

사용자 PC + Tailscale Funnel의 무료 공개 배포, 제출자 정보와 PDF 입력을 완료했다.
발급된 HTTPS 주소의 제출 전 검사 **15 PASS, 0 PENDING, 0 FAIL**, 두 심사 계정의
로그인·Secure 쿠키·후속 세션 검사를 통과했다. 실제 주소와 최종 외부 검사 기록은
공개 저장소에 넣지 않고 `output/submission/FINAL_STATUS.md`에 보관한다.
Daker 최종 업로드와 미래 가용성은 완료 판정에 포함하지 않는다.
공식 Computer Use는 앞선 Chrome URL 확인 실패로 중단됐으며 브라우저 시각 재검증은 별도 항목이다.

정본 규정: <https://daker.ai/public/hackathons/2026-finance-ai-challenge>
2026-09-05에 다시 확인했다. 예선 마감은 09-07 10:00 KST, URL 필수 가용 시간은
09-07 11:00 ~ 09-11 23:59 KST이며 접근 불가는 결격 사유다.

## 재현하고 수정한 결함

| 항목 | 변경 전 관측 | 수정 |
|---|---|---|
| Luna 상담 | 단순 API 호출은 성공했지만 도구를 포함한 실제 상담은 HTTP 400 후 템플릿으로 전환 | `gpt-5.6-luna` Chat Completions 도구 호출에 `reasoning_effort=none` 명시 |
| 공개 오류 | 제공자 예외 원문에 포함된 합성 비밀값이 응답에 그대로 노출 | 공개 사유를 고정된 오류 범주 문구로 제한 |
| 응답 계약 | 라이브 응답의 `model`, 재시도·실패 메타데이터가 `additionalProperties=false` 계약에 위배 | 실제 메타데이터를 선택 필드로 선언하고 OpenAPI 재생성 |
| 상태 지표 | 제공자 실패 후 템플릿으로 전환한 호출도 성공으로 기록 | `degradedFrom`이 있는 호출은 실패로 기록 |
| 소스 ZIP | ZIP 내부 해시는 정상이지만 기준 커밋은 과거 `43f7a35` | 최종 소스로 재생성하고 매니페스트 기준 커밋을 확인 |

배포 모델은 사용자 지정 `gpt-5.6-luna`로 PC 운영 환경과 선택 가능한 `render.yaml`에 고정했다.
OpenAI 키는 로컬 `.env`에서 읽었고 저장소·출력 로그에 싣지 않았다.

## 실행 검증

| 검증 | 실제 결과 |
|---|---|
| 변경 전 전체 테스트: `.venv/Scripts/python.exe -m pytest backend/tests -q` | 2,438 passed, 2 skipped, 694.30초 |
| 새 회귀 검사: `backend/tests/llm/test_chat_runtime.py` | 변경 전 5 failed, 수정·지표 검사 추가 후 8 passed |
| 회귀·생성 계약 검사 | 초기 회귀 5건 + 생성 계약·프런트 생성물 56건, 총 61 passed |
| 기존 상태 지표 검사: `backend/tests/api/test_status_metrics.py` | 47 passed |
| 최종 PR 및 main CI | 2,446 passed, 2 skipped; 생성물 일치 강제 검사 통과 |
| 실제 로컬 상담 API | HTTP 200, `mode=live`, `model=gpt-5.6-luna`, 6.24초, 계산 도구 3회 |
| Docker 빌드: `docker build --tag home-compass:final-audit .` | 성공 |
| 같은 이미지의 운영 모드·검증된 로컬 TLS 프록시 | 아래 8개 확인 모두 PASS |

운영 이미지 digest:
`sha256:93c8cdb5055e1aaee5c11b585de7ebc2cf323e8ecc32dcffb3eab0eadfca7766`

1. HTTPS 첫 화면, `/api/health`, `/admin/` 정상.
2. 익명 진단 상한 860,000원·권장 730,000원, 정책 4/1/3, 내부 필드 미노출, 익명 관리자 API 차단.
3. 프로덕션 컨테이너의 Luna 상담 라이브 응답: 8.59초, 도구 2회.
4. 상담원 로그인: 두 쿠키 모두 Secure, 후속 HTTPS 요청에 세션 유지.
5. 규칙관리자 로그인과 초안 조회: 정상, 후속 HTTPS 요청에 세션 유지.
6. 컨테이너를 교체하고 같은 볼륨으로 기동: 11개 테이블 행수 동일.
7. 교체 후 같은 심사 계정 비밀번호로 로그인과 세션 확인 성공.
8. 시작 로그에 API 키·비밀번호·시드 비밀번호 불일치 알림 없음.

로컬 재현 스크립트·비밀 없는 상세 보고서는 `tmp/production-audit/report.json`과
`tmp/audit_production.py`에 보관했다. 이 경로는 Git·Docker·소스 ZIP에서 제외된다.

## 제출 프로필과 PDF

- 사용자에게 받은 개인 참가 등록명·실명을 로컬 프로필에 입력했다.
- 두 심사 계정의 서로 다른 32자 비밀번호를 생성하고 운영 컨테이너에서 검증했다.
- 같은 값을 로컬 프로필의 심사 계정 안내와 실제 PC 운영 환경에 반영했다. 공개 HTTPS 로그인으로 일치를 확인했다.
- `build_submission_pdfs.py --strict`로 기획서 4쪽·기능 명세서 5쪽을 재생성했다.
- Poppler로 9쪽을 렌더링해 이름, 계정 안내, 표, 페이지 구분, 증거 이미지 배치를 확인했다.
- 기존 증거 스크린샷은 09-04 촬영본이다. 이번 변경은 백엔드·배포 설정이며 UI는 변경하지 않았다.

## 실제 무료 배포

- 서버 임대료가 없는 사용자 PC의 Python 서버 + Tailscale Funnel을 선택했다. 유료 Render 서비스는 생성하지 않았다. OpenAI API 이용료는 별도다.
- Git `70ba77a`의 별도 복사본을 운영한다. 원본 작업 디렉터리를 수정해도 서버 코드는 바뀌지 않는다.
- `127.0.0.1:18174`에 단일 Uvicorn 프로세스를 바인딩하고 Funnel만 HTTPS로 연결했다.
- 운영 모드, Secure 쿠키, 영구 SQLite, 시간별 백업을 설정했다.
- `HomeCompass-Submission-Watchdog` 작업은 로그인 시 시작하며 중단된 감독 프로세스를 다시 시작한다. 감독 프로세스는 건강 검사와 서버 재기동을 맡는다.
- 서버 프로세스 트리를 강제 종료한 뒤 21.37초 내 자동 복구됐다. 감독 프로세스 재시작을 포함해 11개 테이블과 심사 계정이 보존됐다. 백업 무결성도 통과했다.
- 공개 HTTPS에서 익명 홈페이지·진단·Luna 라이브 상담, 두 심사 계정의 후속 세션을 확인했다. 관리자 API의 익명 접근과 비밀 파일 경로는 차단됐다.
- `.github/workflows/deployment-check.yml`은 Tailscale이 없는 GitHub 호스팅 환경에서 외부 홈페이지·건강 검사·진단·접근 제어를 확인한다. 실제 실행 결과는 로컬 최종 상태 문서에 기록한다.

## 남은 제출 및 운영 조건

- 공식 Computer Use를 이용한 실제 배포 화면의 브라우저·모바일 폭 재확인과 Daker 최종 업로드는 별도다.
- 09-07 10:30 KST 이후 코드·설정 변경과 재배포를 멈추고, 09-12 00:10 KST까지 PC·인터넷·Windows 로그인·Tailscale을 유지한다.
- Windows 재부팅 후에는 로그인해야 앱이 자동 복구된다. 화면 잠금과 로그아웃은 다르다.
- 현재 자동 절전 대기 값은 AC/DC 모두 0이다. 설정을 변경하지 않았다.
- 이 시점의 성공은 미래 무중단을 보장하지 않는다. 운영 안내는 `PC_HOSTING.md`를 따른다.
