# 2026 금융 AI Challenge 제출 운영 런북

이 문서는 저장소 밖의 권한이 필요한 마지막 작업만 운영자가 수행하도록 만든 체크리스트다.
코드·문서·배포 구성의 이상은 `scripts/submission_preflight.py`가 먼저 차단한다.

## 마감과 가용 시간

- 예선 제출 마감: **2026-09-07 10:00 KST**
- 예선 제출물: 기획서 PDF, 기능 명세서 PDF, 실행 가능한 웹 URL
- 웹 URL 필수 가용 시간: **2026-09-07 11:00 KST ~ 2026-09-11 23:59 KST**
- 본선 진출 시 최종 제출 마감: **2026-10-08 23:59 KST**
- 본선 제출물: 최종 발표자료 PDF, 소스코드 ZIP
- 정본: <https://daker.ai/public/hackathons/2026-finance-ai-challenge>

모든 시각은 Asia/Seoul 기준이다. 운영자는 Daker 공지에 변경이 없는지 업로드 직전에 다시
확인한다.

## 1. 참가자 정보 입력

실명은 저장소에 커밋하지 않는다.

```powershell
Copy-Item docs\competition\submission_profile.example.json `
  docs\competition\submission_profile.local.json
notepad docs\competition\submission_profile.local.json
```

채울 칸은 넷이다.

| 키 | 무엇을 넣나 |
|---|---|
| `team_name` | **Daker 등록 화면에 보이는 이름을 글자 단위로 그대로.** 서비스 이름이 아니다 |
| `member_names` | 등록된 구성원 실명. 팀이면 팀장부터 쉼표로 구분 |
| `reviewer_accounts_provided` | 심사위원에게 직원 계정을 줄 것인가 (현재 결정: `true`) |
| `reviewer_account_instructions` | 그 계정의 아이디와 비밀번호, 그리고 어디로 들어가는지 |

> **개인 참가라면 `team_name` 에 무엇을 넣나.** 공식 양식의 「팀명」 칸은 등록된 이름과
> 같아야 한다고만 적는다. 개인으로 신청했으면 Daker 제출 화면이 보여주는 이름(보통 본인
> 실명)을 그대로 옮긴다. **서비스 이름 `Home_Compass` 를 넣지 않는다** — 그것은 등록명이
> 아니다. 확실하지 않으면 Daker 제출 화면을 열어 눈으로 확인하고 옮겨 적는다.

### 심사 계정 — 3단계보다 **먼저 하지 않는다**

계정 안내에는 실제 비밀번호가 들어간다. 그 값은 3단계에서 Render에 입력할 때 정해지므로
**순서를 지킨다.**

1. 3단계에서 Render Blueprint에 두 비밀번호를 입력한다.
2. **같은 값**을 `reviewer_account_instructions` 에 적는다.
3. 그 다음 PDF를 다시 만든다.

이 순서를 어기면 PDF에 적힌 비밀번호로 로그인이 안 되고, 심사위원은 F7~F10을 재현하지
못한 채 「완료」라고 적힌 표만 본다.

안내 문구 예시 (배포 주소와 비밀번호는 실제 값으로 바꾼다):

```text
상담원: 시민 화면 우상단에서 counselor / <실제-비밀번호> 로 로그인
규칙관리자: https://배포주소/admin/ 에서 rulemanager / <실제-비밀번호> 로 로그인
```

> ⚠️ **이 값들은 공개 URL에 대한 접근 권한이다.** PDF를 받은 사람은 누구나 승인·반려를
> 누를 수 있고 영구 디스크라 흔적이 남는다. 사용자가 이 위험을 알고 「넣는다」를 선택했다.
> 그래도 비밀번호는 **저장소에 커밋하지 않는다** — `submission_profile.local.json` 은
> `.gitignore` 대상이고 소스 ZIP에도 들어가지 않는다.

칸을 채운 뒤 PDF를 다시 만든다.

```powershell
python docs\competition\build_submission_pdfs.py --strict
```

`--strict` 는 네 칸 중 하나라도 자리표시자(`__운영자_` 로 시작)면 **거부한다.**
`scripts\submission_preflight.py` 도 같은 것을 다시 본다.

### 증거 화면 — PDF 를 만들기 **전에** 뽑는다

두 PDF 의 부록은 실제 화면 캡처를 싣는다. 그 이미지는 `output\evidence\` 에 있고
**그 디렉터리는 `.gitignore` 대상이라 새로 받은 저장소에서는 비어 있다.** 비어 있으면
생성기는 빈 부록을 내는 대신 **부록을 통째로 생략한다** — 쪽수도 제목도 그대로여서
**빠진 것을 눈으로 알아채기 어렵다.**

서버를 띄운 채로 돌린다.

```powershell
# 창 하나: 서버
python scripts\start_server.py

# 창 둘: 캡처 → PDF 재생성
python docs\competition\capture_evidence.py
python docs\competition\build_submission_pdfs.py --strict
```

`submission_preflight.py` 의 `evidence screenshots` 항목이 이것을 확인한다 — 이미지가
0장이면 `PENDING` 이다.

## 2. 배포 전 프로덕션 컨테이너 리허설

Render에 올리기 전에 같은 이미지·같은 환경변수로 로컬에서 한 번 띄운다. Render는 배포 실패를
되돌려 주지만 필수 가용 시간 안의 장애는 되돌려 주지 않는다.

```powershell
docker build -t home-compass .
docker volume create home-compass-data
docker run -d --name home-compass-rehearsal -p 8000:8000 `
  -v home-compass-data:/var/data `
  -e HOME_COMPASS_ENV=production `
  -e HOME_COMPASS_COOKIE_SECURE=true `
  -e HOME_COMPASS_STORE_URL=sqlite:///var/data/home_compass.db `
  -e HOME_COMPASS_LOG_FILE=/var/data/observability.jsonl `
  -e HOME_COMPASS_SEED_COUNSELOR_PASSWORD=<16자 이상> `
  -e HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD=<16자 이상> `
  home-compass
docker inspect -f '{{.State.Health.Status}}' home-compass-rehearsal   # healthy
```

★ **이 컨테이너에 평문 HTTP로 로그인해 보는 것은 로그인을 검증하지 못한다.** 운영 모드는
쿠키에 `Secure`를 붙이므로 브라우저는 HTTPS가 아닌 출처에서 그 쿠키를 저장하지 않는다.
`http://127.0.0.1`은 브라우저와 curl이 신뢰 출처로 취급해 통과시키므로 그 확인은 거짓
음성이다. Render는 HTTPS로 종단하고 컨테이너에는 HTTP로 넣으므로, 리허설도 앞에 TLS를
종단하는 프록시를 세우고 그 너머에서 확인해야 실제 배포와 같은 모양이 된다. 프록시 없이
확인할 수 있는 것은 `/api/health`와 익명 진단까지다.

프록시 뒤에서 다음 다섯을 확인한다. 하나라도 실패하면 Render에 올리지 않는다.

1. `GET /api/health` → 200 `{"status":"ok",...}`
2. `POST /api/analyze` (쿠키 없음) → 200, 응답에 `internal` 키가 **없다**
3. `POST /api/auth/login` (`counselor`) → 200, 이어지는 `GET /api/auth/session`이
   `authenticated: true`
4. `POST /api/auth/login` (`rulemanager`) → 200, `GET /api/admin/drafts` → 200
5. `GET /admin/` → 200

이어서 재배포 경로를 확인한다. 영구 디스크는 남고 컨테이너만 바뀌는 것이 Render의 재배포다.

```powershell
docker rm -f home-compass-rehearsal
# 같은 docker run 을 다시 실행한 뒤
docker logs home-compass-rehearsal   # [startup] store ready 가 다시 나오고 기동이 거부되지 않는다
```

### 시드 비밀번호 회전

시드는 멱등이다. 이미 있는 계정의 비밀번호는 덮어쓰지 않으므로, **환경변수를 바꿔
재기동해도 비밀번호는 바뀌지 않는다.** 영구 디스크가 붙은 뒤로는 대시보드 값을 고치는 것이
비밀번호 변경 경로가 아니다. 기동은 이 경우 stderr에 다음을 출력한다.

```
[인증] 이미 있는 계정이라 주입된 시드 비밀번호를 적용하지 않았습니다: counselor
```

디스크를 비우지 않는다. 그것은 승인된 RuleVersion과 감사원장을 함께 지운다. 시드 계정 행만
지우고 새 값으로 재기동한다. 사용자 id가 `user:{username}`으로 결정적이라 재시드가 같은 id를
복구하므로 `approval_record`·`audit_event`의 참조는 끊기지 않는다.

`sqlite3` CLI는 쓰지 않는다. 이미지가 `python:3.13-slim`이라 그 바이너리가 없다. 컨테이너
안(Render Shell, Linux)에서 파이썬으로 지운다.

```sh
python - <<'PY'
import sqlite3
conn = sqlite3.connect("/var/data/home_compass.db")
conn.execute("DELETE FROM app_user WHERE username IN ('counselor','rulemanager')")
conn.commit()
PY
```

리허설 컨테이너라면 밖에서 `docker exec -i home-compass-rehearsal python - <<'PY' ... PY`로
같은 것을 넣는다. 그 다음 대시보드에서 두 비밀번호를 새 값으로 바꾸고 재배포(또는 컨테이너
재기동)한다.

두 계정을 함께 지우는 이유는 남은 한쪽이 다음 기동에서 다시 무음으로 무시되기 때문이다.
스키마는 건드리지 않는다 — `DELETE`만 하고 `ALTER TABLE`은 하지 않는다. 이 절차는
`backend/tests/api/test_env_boundary.py::TestDocumentedRotationPath`가 검증한다.

### 로그에 비밀이 없는지 확인

컨테이너 로그에 비밀번호와 세션 토큰이 없는지 본다. 비밀번호를 환경변수로 주입하고 계정이
처음 만들어지면 아무것도 출력되지 않는다. 주입하지 않으면 무작위 비밀번호가 stderr에 1회
출력되며, 그것은 운영 배포에서 나오면 안 되는 신호다.

```powershell
docker logs home-compass-rehearsal 2>&1 | Select-String -Pattern '\[인증\]'
```

- 첫 기동(빈 디스크) + 비밀번호 주입 → **출력이 없어야 한다.**
- 재기동 + 같은 비밀번호 → 출력이 없어야 한다.
- 재기동 + **바뀐** 비밀번호 → 위의 `적용하지 않았습니다` 한 줄이 나온다. 값도 해시도
  찍히지 않는다. 이 줄이 나왔는데 비밀번호를 바꿀 의도였다면 위 회전 절차를 밟는다.

`[설정]`으로 시작하는 줄이 나오면 `.env`에 배포 경계 키를 적은 것이다. 그 값들은 적용되지
않는다 — `render.yaml`의 envVars나 `docker run -e`로 옮긴다.

```powershell
docker logs home-compass-rehearsal 2>&1 | Select-String -Pattern '\[설정\]'   # 출력이 없어야 한다
```

## 3. Render에 공개 배포

저장소 최종 커밋을 운영자의 GitHub/GitLab 원격에 올린 뒤 Render Dashboard에서 이 저장소의
`render.yaml`로 **New Blueprint Instance**를 만든다. 구성은 현재 Render 공식 Blueprint
스펙의 Docker runtime, Singapore region, 단일 유료 인스턴스, 1 GB 영구 디스크,
`/api/health` 헬스체크를 사용한다.

Blueprint 생성 화면에서 아래 두 `sync: false` 값을 각각 16자 이상의 서로 다른 임의
비밀번호로 입력한다. 저장소나 메신저에 값 자체를 기록하지 않는다.

- `HOME_COMPASS_SEED_COUNSELOR_PASSWORD`
- `HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD`

비밀번호 후보는 로컬에서 다음 명령을 두 번 실행해 만들 수 있다.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

### 라이브 AI 상담 — 키는 **생성 화면에서** 넣는다

`render.yaml`이 `OPENAI_API_KEY`와 `OPENAI_MODEL`을 `sync: false`로 선언하므로 Blueprint
생성 화면에 두 칸이 함께 뜬다. **거기서 넣는다.** 만들고 나서 대시보드로 추가하면 그것은
재배포이고, 영구 디스크가 붙은 서비스는 무중단 배포가 안 된다 — 세션이 끊기고 짧은
중단이 생긴다. 가용 시간 안에서는 그 중단을 감당할 수 없다.

> **`OPENAI_MODEL`을 비우지 않는 편이 안전하다.** 비우면 `config.DEFAULT_OPENAI_MODEL`
> (`gpt-5.4-mini`)을 쓰는데, **그 id가 계정에서 거부되면 호출이 실패하고 응답이 조용히
> 템플릿 모드로 내려간다.** 화면의 칩은 「LLM 라이브 모드」 대신 오프라인을 가리키고,
> 심사위원은 생성형 AI가 동작하지 않는 서비스를 본다. 본인 계정에서 실제로 쓸 수 있는
> 모델 id를 직접 적는다.

키가 없어도 모든 핵심 판정과 템플릿 상담은 동작한다. 넣지 않기로 하면 4단계의
`live LLM` 항목이 `PENDING`으로 남고 그것이 맞는 상태다.

> ⚠️ **`/api/chat`에는 호출 제한이 없다.** 익명 공개 엔드포인트이므로 배포 주소를 아는
> 사람은 누구나 호출할 수 있고, 그만큼 API 요금이 나간다. URL은 Daker 제출 화면에만
> 넣고 다른 곳에 공유하지 않는다. 그리고 **OpenAI 계정에서 이 기간에 쓸 사용량 상한을
> 직접 걸어 둔다** — 상한에 걸리면 서비스가 죽는 것이 아니라 템플릿 모드로 내려가므로
> 판정 기능은 계속 동작한다.

영구 디스크가 붙은 서비스는 재배포 중 짧은 중단이 생길 수 있으므로, **2026-09-07
10:30 KST 이후에는 코드·설정 변경과 수동 재배포를 멈춘다.** 서비스 삭제나 일시정지도
2026-09-12 00:10 KST까지 하지 않는다.

## 4. 외부 URL 최종 검사

Render가 발급한 `https://...onrender.com` URL을 시크릿/로그아웃 브라우저와 다른 네트워크
(예: 휴대전화 LTE/5G)에서 각각 연다. 이어서 자동 검사를 실행한다.

```powershell
python scripts\package_submission.py
python scripts\submission_preflight.py --strict --url https://배포주소
```

검사는 HTTPS 헬스체크와 익명 샘플 진단을 실제 URL에 호출해 월 상한 860,000원·권장액
730,000원 및 근거 필드가 반환되는지 확인한다. 모두 `PASS`가 아니면 Daker에 URL을 넣지
않는다.

마지막 `live LLM` 항목은 **`/api/chat`을 실제로 한 번 호출한다.** `/api/health`의 `llm`은
「키가 있고 SDK를 불러올 수 있다」까지만 말하므로, 모델 id가 거부되면 그 값은 여전히
`openai`인데 실제 응답은 템플릿이다. 그 간극을 여기서 닫는다 — `mode=live`여야 통과다.

브라우저에서는 다음도 직접 확인한다.

1. 첫 화면에서 `예시 프로필 채우기`를 누른다.
2. 희망지역이 `서울 마포구`인지 확인하고 `주거비 진단 시작`을 누른다.
3. 월 상한 86만원, 권장액 73만원, 정책 적격 4건/조건부 1건/부적격 3건을 확인한다.
4. AI 상담 질문 하나를 눌러 응답과 현재 모드 칩(라이브 또는 템플릿)을 확인한다.
5. 390px 모바일 폭에서도 가로 스크롤이나 잘린 핵심 문구가 없는지 확인한다.

## 5. Daker 업로드

2026-09-07 10:00 KST 전에 Daker 제출 화면에서 다음 세 항목을 등록하고, 업로드 완료 화면을
캡처해 운영자 보관소에 저장한다.

- `output/pdf/2026_금융_AI_Challenge_기획서_Home_Compass.pdf`
- `output/pdf/2026_금융_AI_Challenge_기능명세서_Home_Compass.pdf`
- 4단계에서 검증한 공개 HTTPS URL

PDF를 열어 첫 표의 팀명·구성원 실명을 마지막으로 확인한다. 파일명만 보고 업로드하지 않는다.
업로드 이후 URL을 다시 한 번 열고 `/api/health` 응답을 확인한다.

## 6. 가용 시간 모니터링

필수 가용 시간 동안 Render의 Health/Events를 오전·오후 각 1회 확인한다. 장애가 발생하면
코드 변경보다 먼저 최근 Events, `/api/health`, 영구 디스크 마운트, 환경변수 누락을 본다.
서비스가 정상화된 뒤 `submission_preflight.py --strict --url ...`을 다시 실행한다.

## 7. 본선 진출 시

현재 저장소에는 재생성 가능한 19장 기술설명서와 소스 ZIP 빌더가 준비돼 있다. 발표 내용과
실제 본선 시연 상태를 최종 반영한 뒤 PowerPoint에서 PDF로 내보내고, 아래 ZIP을 다시 만든다.

```powershell
python docs\competition\build_ppt.py
python scripts\package_submission.py
```

- 발표 원본: `docs/competition/기술설명서_Home_Compass.pptx`
- 제출용 발표 PDF: `output/pdf/최종발표자료_Home_Compass.pdf`
- 제출용 소스 ZIP: `output/submission/Home_Compass_source.zip`

소스 ZIP에는 해시가 포함된 `SUBMISSION_MANIFEST.json`이 들어가며 `.env`, 참가자 로컬 프로필,
가상환경, 생성 output은 자동 제외된다.
