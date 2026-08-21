# SPEC 6-A 실기동 손 검증 — 상담원 신고 → 규칙관리자 큐

`TestClient` 가 아니라 **실제 `python -m uvicorn` 워커 1개**를 띄우고 소켓으로 쳤다
(SPEC 9.3 #3). 아래는 그 실행의 출력 그대로다. 재현 절차는 이 파일 끝에 있다.

기록해 두는 이유는 SPEC 10.2 의 6-A 완료 기준 셋이 **각각 어디서 보이는지**를 남기기
위해서다 — 1번은 4절, 2번은 2절, 3번은 마지막 `AuditEvent` 목록이다.

```
# SPEC 6-A 실기동 손 검증 — uvicorn 워커 1개 (http://127.0.0.1:60790)
# 2026-08-14T18:11:04.658351+00:00

--- 저장소 전 ---
AnomalyReport : 0건
RuleDraft     : 1건  [('manual-draft-1', 'pending')]
RuleVersion   : 8건

--- 1. 상담원으로 로그인해 실제로 신고를 올린다 ---
POST /api/auth/login -> 200 role=counselor
POST /api/reports -> 200
{
  "id": "report:ea2b57abe656411dbff8e9620147c661",
  "reporter": "counselor",
  "at": "2026-08-14T18:11:04.992669+00:00",
  "targetKind": "policy",
  "targetId": "buttress_youth",
  "targetField": "status",
  "reason": "고객 앞에서 이 제도가 지난달 종료됐다는 안내를 받았다고 들었습니다.",
  "status": "open",
  "mergedDraftIds": [
    "manual-draft-1"
  ]
}

--- 2. 상담원은 여전히 규칙을 바꿀 수 없다 (SoD) ---
POST /api/admin/drafts/manual-draft-1/approve -> 403 forbidden
GET  /api/admin/reports (상담원) -> 403 forbidden

--- 3. 대상은 항목으로 한정된다 (SPEC 7.1) ---
POST /api/reports (자유 텍스트 대상) -> 400 unknown_target_field
응답에 사유 본문이 되비쳤는가: False

--- 4. 규칙관리자로 로그인해 큐에서 그것을 본다 ---
POST /api/auth/login -> 200 role=rule_manager
GET  /api/admin/reports -> 200
{
  "reports": [
    {
      "id": "report:ea2b57abe656411dbff8e9620147c661",
      "reporter": "counselor",
      "at": "2026-08-14T18:11:04.992669+00:00",
      "targetKind": "policy",
      "targetId": "buttress_youth",
      "targetField": "status",
      "reason": "고객 앞에서 이 제도가 지난달 종료됐다는 안내를 받았다고 들었습니다.",
      "status": "open",
      "mergedDraftIds": [
        "manual-draft-1"
      ]
    }
  ]
}

GET  /api/admin/drafts -> 200 (초안 목록에 신고가 섞이지 않는다: ['manual-draft-1'])
GET  /api/admin/drafts/manual-draft-1 -> 200 reports=[{"id": "report:ea2b57abe656411dbff8e9620147c661", "reporter": "counselor", "at": "2026-08-14T18:11:04.992669+00:00", "targetKind": "policy", "targetId": "buttress_youth", "targetField": "status", "reason": "고객 앞에서 이 제도가 지난달 종료됐다는 안내를 받았다고 들었습니다.", "status": "open", "mergedDraftIds": []}]

--- 5. 초안을 승인해도 신고 기록은 그대로다 (병합 ≠ 기록 통합) ---
POST /api/admin/drafts/manual-draft-1/approve -> 200 ruleVersionId=approval:manual-draft-1
GET  /api/admin/reports -> 신고 1건 · mergedDraftIds=[] (초안이 pending 을 벗어나 단독 항목이 된다)

--- 저장소 후 ---
AnomalyReport : 1건
    report:ea2b57abe656411dbff8e9620147c661 | counselor | policy:buttress_youth#status | open | 고객 앞에서 이 제도가 지난달 종료됐다는 안내를 받았다고 들었습니다.
RuleDraft     : 1건  [('manual-draft-1', 'approved')]
RuleVersion   : 9건

--- AuditEvent (append-only, 기록 순) ---
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | buttress_youth | success | {"ruleVersionId": "seed:buttress_youth", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | youth_monthly_loan | success | {"ruleVersionId": "seed:youth_monthly_loan", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | newlywed_jeonse | success | {"ruleVersionId": "seed:newlywed_jeonse", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | youth_rent_support | success | {"ruleVersionId": "seed:youth_rent_support", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | seoul_youth_rent | success | {"ruleVersionId": "seed:seoul_youth_rent", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | seoul_deposit_interest | success | {"ruleVersionId": "seed:seoul_deposit_interest", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | housing_dream_savings | success | {"ruleVersionId": "seed:housing_dream_savings", "origin": "seed"}
    2026-08-14T18:11:03.139277+00:00 | system:seed  | rule_version.seed | hug_deposit_guarantee | success | {"ruleVersionId": "seed:hug_deposit_guarantee", "origin": "seed"}
    2026-08-14T18:11:04.960210+00:00 | counselor    | auth.login     | counselor | success | {"role": "counselor"}
    2026-08-14T18:11:04.992669+00:00 | counselor    | report.create  | policy:buttress_youth#status | created | {"reportId": "report:ea2b57abe656411dbff8e9620147c661", "reason": "고객 앞에서 이 제도가 지난달 종료됐다는 안내를 받았다고 들었습니다."}
    2026-08-14T18:11:05.003267+00:00 | counselor    | authz.denied   | draft.decide | denied | {"reason": "forbidden"}
    2026-08-14T18:11:05.010709+00:00 | counselor    | authz.denied   | report.read | denied | {"reason": "forbidden"}
    2026-08-14T18:11:05.023042+00:00 | counselor    | auth.logout    | counselor | success | 
    2026-08-14T18:11:05.030675+00:00 | rulemanager  | auth.login     | rulemanager | success | {"role": "rule_manager"}
    2026-08-14T18:11:05.081727+00:00 | rulemanager  | rule.approve   | manual-draft-1 | success | {"policyId": "buttress_youth", "ruleVersionId": "approval:manual-draft-1"}

```

## 재현

```
HOME_COMPASS_SEED_COUNSELOR_PASSWORD=... HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD=... HOME_COMPASS_STORE_URL=sqlite://./var/manual.db python -m uvicorn home_compass.main:app --host 127.0.0.1 --port 8000 --workers 1
```

그 뒤 상담원으로 로그인해 `POST /api/reports`, 규칙관리자로 로그인해
`GET /api/admin/reports` 를 친다. 화면으로 하려면 `/` 에서 상담원으로 로그인해 제도
카드의 「이상 신고」를 누르고, `/admin` 에서 규칙관리자로 로그인해 왼쪽 큐의
「현장 신고」 목록을 본다.

## 이 출력에서 읽어야 하는 것

- **신고가 별도 유형으로 쌓인다** — `GET /api/admin/drafts` 는 초안만, `GET
  /api/admin/reports` 는 신고만 돌려준다. 한 목록에 섞이지 않는다
- **신고로 규칙이 바뀌지 않는다** — 신고 전후로 `RuleVersion` 이 8건 그대로다.
  9건이 된 것은 그 뒤 **규칙관리자가 초안을 승인**했기 때문이며 신고 때문이 아니다.
  상담원의 승인 시도는 403 이고 그 거부가 `authz.denied` 로 남았다
- **병합해도 양쪽 `AuditEvent` 가 보존된다** — `report.create`(actor=counselor)와
  `rule.approve`(actor=rulemanager)가 각각 남아 있다. 병합은 화면 조립이지 기록의
  통합이 아니다
- **초안이 `pending` 을 벗어나면 신고는 단독 항목으로 돌아간다** — 5절의
  `mergedDraftIds=[]` 가 그것이다. SPEC 6.4 가 이 병합 규칙을 **잠정**이라고 적었고,
  이 동작은 재검토 대상이다
