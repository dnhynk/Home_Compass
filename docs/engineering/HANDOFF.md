# HANDOFF: 2026 금융 AI Challenge 예선 제출 — 코디네이터 인계

`run_id`: **`run_b70307c8c66d`** · repository `D:/repos/Home_Compass` · `dnhynk/Home_Compass` (public)
coordinator session `27db16c5-6bbf-4046-a2b0-705b0a7976ba` · 롤오버 자동 승계 **승인됨**

---

## 목표

2026 금융 AI Challenge **예선 제출을 완결한다.**

**완료 기준 (검증 가능한 형태):**

1. `scripts/submission_preflight.py --strict --url <배포주소>` 가 **전 항목 PASS**
2. Daker 제출 화면에 기획서 PDF · 기능명세서 PDF · 배포 URL 등록 완료
3. 배포 URL 이 **2026-09-07 11:00 ~ 09-11 23:59 KST** 접근 가능

## 마감 — 모든 우선순위를 강제한다

| 항목 | 시각 (KST) |
|---|---|
| **예선 제출 마감** (기획서 · MVP · 참가신청 전부) | **2026-09-07 10:00** |
| URL 필수 가용 구간 — **미가용은 결격** | 2026-09-07 11:00 ~ 09-11 23:59 |
| 발표 심사 대상 발표 | 2026-09-22 10:00 |
| 본선 최종 제출 (발표 PDF + 소스 ZIP → `dacon@dacon.io`) | 2026-10-08 23:59 |

정본 <https://daker.ai/public/hackathons/2026-finance-ai-challenge>.
심사는 **내부 비공개 심사위원단 100%**, 기준은 「주제 적합성 · 부적격 여부」.
1,156팀 중 **상위 11팀 내외**만 발표 심사로 간다.

---

## 현재 상태 — 코디네이터가 직접 실행 출력을 본 것만

| 항목 | 확인 방법 |
|---|---|
| 전체 테스트 | `backend/tests` **1879 passed · 2 skipped** + `store` **555 passed** = **2434 · 0 failed** |
| 제출 preflight | **pass=6 · pending=4 · fail=0** (`.venv` 파이썬으로 돌린다) |
| 공식 양식 대조 | `.hwpx` 2종을 대회 페이지에서 받아 `hp:t` 추출. 생성기 섹션 제목이 **7개/5개 항목과 문자 단위 일치** |
| 배포 경로 | ★ T1 이 컨테이너를 **실기동**했다 — 5개 경로 200, 볼륨 유지 재기동 시 11개 테이블 행수·해시 동일(시드 멱등) |
| **H3 판정 결함** | ★ 코디네이터가 직접 재현했다 — `age=0` 이 `newlywed_jeonse` 에 `eligible` 이고 **연령 사유가 한 줄도 없다** |
| **H1 설정 결함** | ★ 직접 재현했다 — `.env` 의 `HOME_COMPASS_COOKIE_SECURE` · `HOME_COMPASS_ENV` 가 조용히 버려지고 `cookie_secure()` 가 `False` |
| 접근성 | ★ 이 저장소에서 **처음 측정했다** (axe-core 4.10.2). 시민 화면 3종 33노드 → 0, 관리자 화면 11건 수정 |

### 미확인 — 아직 실행하지 않은 것

- **Render 실배포를 하지 않았다.** T1 이 증명한 것은 「같은 이미지·환경변수·디스크 배치·HTTPS 종단 형상에서 동작한다」이지 「Render 에서 동작했다」가 아니다
- **리허설 3회 재현을 이 세션이 재현하지 않았다** (이전 Run 의 증거는 `backend/var/rehearsal-evidence/`)
- 스크린리더 미실행 · Edge/Safari 미검증 (Playwright Chromium 만)

### ★ 반드시 지켜야 할 운영 제약 (T1·T6 이 실측)

- **09-07 이후 스키마 변경 금지.** `store/sqlite_schema.py` 는 `CREATE TABLE IF NOT EXISTS` 뿐이고
  마이그레이션 코드가 저장소에 없다. **영구 디스크가 붙은 상태에서 스키마를 바꾸는 배포는 기동에 실패한다**
- **세션은 프로세스 메모리에 있다.** 재배포하면 로그인 세션이 전부 끊긴다. `numInstances: 1` 필수
- **가용 시간 중 재배포 금지.** 영구 디스크 서비스는 무중단 배포가 안 된다
- **평문 HTTP 로 로그인 검증하면 거짓 음성이다.** `http://127.0.0.1` 은 브라우저·curl 이 신뢰 출처로
  취급해 통과시킨다. TLS 종단 프록시 뒤에서 확인해야 한다 (런북 2절)
- **Windows 리허설 함정:** Git Bash 가 `-e KEY=/var/data/...` 를 `C:/Program Files/Git/var/...` 로
  바꾼다. `MSYS_NO_PATHCONV=1` 로 돌린다

### pending 4건은 전부 사람 대기다

`participant identity` · `planning PDF identity` · `feature PDF identity` · `public URL`.
앞의 셋은 **등록 팀명과 구성원 실명**이 `docs/competition/submission_profile.local.json`
(`.gitignore` 대상)에 들어가야 닫힌다. 실명은 저장소에 커밋하지 않는다.

---

## 사용자가 정한 것

| 결정 | 값 |
|---|---|
| 배포 | **Render 유료** — 런북대로. 계정·비밀번호·과금은 사용자가 직접 |
| UI 강도 | **감사 기반 정밀 수정.** 디자인 언어 전면 재설계 금지 |
| 롤오버 | **자동 승계 승인** |
| ★ 모델 | **`fable` 절대 사용 금지.** 배치표 7b·11행이 지정하지만 사용자 지시가 우선 → `claude`/`opus`/`max` |

## 미결 Gate — 사용자 응답 대기

| Gate | 질문 | 무응답 시 |
|---|---|---|
| `gate_7401786a5663` | 팀명 통일 (`첫집나침반` / `Paddle` / 개인참가 / 기타) | 제출 불가 — 반드시 답해야 한다 |
| `gate_74f5571a0eaa` | 심사위원용 관리자 계정을 기능명세서에 넣는가 | 기본값 **미제공** 으로 이미 생성기에 반영됨 |

---

## Task 상태

| Task | id | 결과 |
|---|---|---|
| T1 프로덕션 컨테이너 실기동 | `task_810756b42fe2` | ✅ PR #4 머지 · 정리 완료 |
| T2 공식 양식 대조 감사 | `task_dc8036fd69d6` | ✅ 보고서 (PR 없음) · 정리 완료 |
| T3 시민 화면 정밀 수정 | `task_73b86b498f59` | ✅ PR #7 머지 · 정리 완료 |
| T4 규칙관리자 화면 정밀 수정 | `task_18e7a5da92c1` | ✅ PR #8 머지 · 정리 완료 |
| T5 기획서 설득력 보강 | `task_d61d3d9469df` | ✅ PR #6 머지 · 정리 완료 |
| T6 적대적 리뷰 | `task_a49b5c196d38` | ✅ High 3 / Medium 4 / Low 5 · 정리 완료 |
| T8 배포 안전 경계 (H1·H2) | `task_993ce521f825` | ✅ PR #10 머지 · 정리 완료 |
| T7 연령 판정 결함 (H3) | `task_eea4dd30e53b` | ✅ PR #12 머지 · 정리 완료 |
| D1 결정 전용 (Gate 거치) | `task_fd4840c0b9ea` | Gate `gate_74f5571a0eaa` 대기 |

---

## ★ 회수해야 할 임시 등재 — 회수를 강제하는 검사는 없다

`WORKER_PATHS` 에 이 Run 이 더한 항목 전부를 **T7 머지 직후** 지운다.

워커 배정 넷은 **전부 회수했다** — `W-web-ui`(#7) · `W-admin-ui`(#8) ·
`W-deploy-safety`(#10) · `W-eligibility-fix`(#12). 배정표는 `Coordinator` 하나뿐이고
그것이 저장소가 선언한 정상 상태다.

**남은 것은 하나뿐이다.**

| 항목 | 회수 시점 |
|---|---|
| `Coordinator` 에 더한 8경로 (`Dockerfile` · `.dockerignore` · `render.yaml` · `.env.example` · `auth.py` · `main.py` · `test_auth.py` · `frontend/styles.css`) | **배포 URL 확정 후** |

남기면 미래 PR 의 `owner_guess` 가 선언 순서로 Coordinator 를 돌려주고, Coordinator 는
`CONTRACT_DELEGATED` 에 있으므로 `violations()` 가 **계약 변경을 못 잡는다.**
SPEC 8.2 #5 게이트가 조용히 열린다. PR #81·#85 가 그 사고다.

---

## 다음 작업 (첫 항목은 바로 실행 가능)

**코드 쪽 결함 수정은 전부 닫혔다. 남은 것은 사람이 해야 하는 것과 다듬기다.**

1. **팀명 Gate(`gate_7401786a5663`) 의 답을 받는다.** 이것 없이는 제출할 수 없다 —
   PDF 의 팀명·구성원 실명이 자리표시자인 채로 남는다.
2. **사용자가 Render 에 배포한다.** 런북 2절(컨테이너 리허설) → 3절(배포) 순.
   T1 이 로컬 리허설을 이미 통과시켰으므로 남은 위험은 Render 고유 계층뿐이다.
3. 배포 URL 확보 후 `submission_preflight.py --strict --url <URL>` 전 항목 PASS 확인.
   여기서 처음으로 pending 4건이 전부 닫힌다.
4. `Coordinator` 의 임시 8경로 회수 PR.
5. 남은 다듬기 (아래 「이월된 열린 항목」의 앞 네 개). 마감까지 여유가 있으면 한다.

---

## 작업 규율 — 반복해 깨졌던 것 (여전히 유효)

- 워커 대기는 `check --ack <id> --wait --types … --timeout-ms <n>` **한 번의 결합 호출**로만.
  비하트비트 메시지가 있으면 **처리 전에 ack 하지 않는다**
- ★★ **`ask` 는 터미널로 답할 수 없다.** `orca orchestration reply --id <msg_id> --body <text>` 로만 풀린다
- ★ **미결 Dispatch 가 있으면 텍스트로 턴을 끝내지 않는다.** 배경 진행은 없다
- ★ **`--body`·과업 스펙에 ASCII `"` 를 넣지 마라.** PowerShell 에서 인자가 끊긴다
- **대기를 다른 orca 호출과 같은 턴에서 동시에 실행하지 않는다** — `check` 가 경합해 `ok=False`
- ★ **`gate-create` 는 활성 Dispatch 가 있는 Task 에 붙지 않는다.** 결정 전용 Task 를 따로 만든다
- ★ **의존이 풀려도 Task 가 자동으로 `ready` 가 되지 않는다.** `task-update --status ready` 를 명시적으로 부른다
- ★ **`coord_merge.py` 는 `git reset --hard` 를 쓴다.** 미커밋 변경을 들고 부르면 거부되거나 지워진다
- 사용자는 이 터미널을 보지 않는다. **판단이 필요하면 언제나 `gate-create`**
- PR 본문에 SPEC 9.3 여섯 항목 — 특히 ③ **실행 명령과 출력**, ⑥ **미검증 목록**
- PR 본문 맨 끝에 `<!-- orca-run: run_b70307c8c66d -->` 와 `<!-- orca-task: … -->`.
  **빠지면 Observer 가 조용히 누락한다**
- **CI 가 느리다** — 동시 실행이 겹치면 한 건에 18~20분. 워커를 세워 두지 말고 병렬로 돌려라.
  배정표 등재는 **머지 시점 게이트이지 파일 잠금이 아니다** — 등재 PR 을 기다리지 말고 진행시킨다
- `store` 와 `ingest` 의 `conftest.py` 이름 충돌로 전수 실행이 안 된다. **두 번에 나눠 돌린다**

---

## 이월된 열린 항목

**이번 Run 의 워커들이 발견했고 아직 안 고친 것**

- **정책 사유의 충족/미충족이 같은 체크 표식이다** — 계약에 사유별 `met` 필드가 필요하다 (Coordinator)
- **요약 문장의 조사 처리** — `engines/__init__.py:269` 의 「이(가)」, 그리고 백엔드 원시 enum 이
  `app.js` `humanizeEnums` 를 지나 「(무리)」로 찍힌다. 백엔드·프런트가 함께 걸려 순서 배정이 필요
- **≤620px 에서 직원 로그인 불가** (T3 가 별건으로 분리)
- **지표 카드의 마크다운 별표가 리터럴로 찍힌다** — `main.py:3184,3191`
- **`text` 절반 전체 동등성 비교는 기각했다.** `policies[].reasons` 만 건다 — SPEC 5.3 과
  2026-08-15 결정 조건 4 를 뒤집지 않기 위해서다. 되돌리지 마라

**이전 Run 에서 이월된 것**

- 일괄 승인의 반영 단계 원자성이 불완전하다 — preflight 통과 후 실패하면 앞의 것은 반영된 채 남고
  `RuleVersion` 이 불변이라 되돌릴 수 없다
- `_merged_payload` 의 병합 규칙이 **잠정**이고 4.4 검토 화면과 같은 것을 말하는지 미확인
- `/impact` 응답 시간을 재지 않았다 — `read` 프로필의 500ms 예산 안인지 모른다
- 이상치 문턱을 넘는 지역이 0개 · `isSMEEmployee` 를 소비하는 정책이 없다 ·
  `regionPrefixes` 가 추출 7건 전부 `not_found`
- `archive/work-notes/제출_체크리스트.md` 가 「PPT 15장」이라 적는다 — 19장이다.
  그 디렉터리는 **예선 제출의 기록**이라 고쳐 쓰면 기록이 아니게 된다. 손대지 않는다
