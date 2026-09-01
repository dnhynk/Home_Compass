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

## 2. Render에 공개 배포

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

## 3. 외부 URL 최종 검사

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

## 4. Daker 업로드

2026-09-07 10:00 KST 전에 Daker 제출 화면에서 다음 세 항목을 등록하고, 업로드 완료 화면을
캡처해 운영자 보관소에 저장한다.

- `output/pdf/2026_금융_AI_Challenge_기획서_Home_Compass.pdf`
- `output/pdf/2026_금융_AI_Challenge_기능명세서_Home_Compass.pdf`
- 3단계에서 검증한 공개 HTTPS URL

PDF를 열어 첫 표의 팀명·구성원 실명을 마지막으로 확인한다. 파일명만 보고 업로드하지 않는다.
업로드 이후 URL을 다시 한 번 열고 `/api/health` 응답을 확인한다.

## 5. 가용 시간 모니터링

필수 가용 시간 동안 Render의 Health/Events를 오전·오후 각 1회 확인한다. 장애가 발생하면
코드 변경보다 먼저 최근 Events, `/api/health`, 영구 디스크 마운트, 환경변수 누락을 본다.
서비스가 정상화된 뒤 `submission_preflight.py --strict --url ...`을 다시 실행한다.

## 6. 본선 진출 시

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
