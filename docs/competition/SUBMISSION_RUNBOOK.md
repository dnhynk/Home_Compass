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

`team_name`은 Daker 등록 팀명과 글자 단위로 맞추고, `member_names`에는 등록된 구성원 실명을
쉼표로 구분해 입력한다. 그 다음 실명 반영 PDF를 다시 만든다.

```powershell
python docs\competition\build_submission_pdfs.py --strict
```

`submission_profile.local.json`은 `.gitignore` 대상이며 소스 ZIP에도 들어가지 않는다.

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

```powershell
# Render Shell 또는 리허설 컨테이너에서
sqlite3 /var/data/home_compass.db "DELETE FROM app_user WHERE username IN ('counselor','rulemanager');"
# 대시보드에서 두 비밀번호를 새 값으로 바꾼 뒤 재배포(또는 컨테이너 재기동)
```

두 계정을 함께 지우는 이유는 남은 한쪽이 `injected_password_ignored`로 다시 무음이 되기
때문이다. 스키마는 건드리지 않는다 — `DELETE`만 하고 `ALTER TABLE`은 하지 않는다.
이 절차는 `backend/tests/api/test_env_boundary.py::TestDocumentedRotationPath`가 검증한다.

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

라이브 AI 상담을 시연하려면 Render 서비스의 Secret에 `OPENAI_API_KEY`와 선택적으로
`OPENAI_MODEL`을 추가하고 재배포한다. 키가 없어도 모든 핵심 판정과 템플릿 상담은 동작한다.

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
