"""SPEC 7.1 필수 기록 4종이 **실제로 남는지** (소유자: `api` · SPEC 10.2 7단계 기준 ①).

7.1 은 넷을 필수라고 적었다 — 「규칙 승인·반려 / 로그인 및 실패 / 배치 실행 결과 /
권한 거부」. 7단계의 산출물은 기능이 아니라 **증거**이므로, 이 파일은 넷을 각각
**API 를 실제로 쳐서 만들고 저장소를 열어 확인한다.** `record(...)` 를 부르는 줄이
코드에 있다는 것은 증거가 아니다.

## 착수 시점 전수 확인 (7단계 · 관측)

| 필수 기록 | action | 남기는 곳 | 착수 시점 |
|---|---|---|---|
| 규칙 승인 | `rule.approve` | `main._apply_decision` | 있었다 |
| 규칙 반려 | `rule.reject` | 같은 곳 | 있었다 |
| 로그인 성공 | `auth.login` (`outcome=success`) | `main.login_endpoint` | 있었다 |
| 로그인 실패 | `auth.login` (`outcome=failure`) | 같은 곳 | 있었다 |
| 권한 거부 | `authz.denied` | `main._record_denial` | 있었다 |
| 배치 실행 결과 | `market.run` | `ingest.market.pipeline` | **없었다** |

마지막 행이 이 단계가 닫은 것이다. 지역별 `market.ingest` 행은 있었으나 **실행의
경계가 없었고**, 그래서 7.2 의 배치 성공률이 분모를 셀 수 없었다 (근거와 실측은
`backend/tests/ingest/test_batch_run_record.py` 의 모듈 docstring).

배치 쪽은 별도 프로세스라 이 파일이 아니라 그쪽 테스트가 진다. 여기서는 **상태
엔드포인트가 그 기록을 실제로 읽는지**까지만 확인한다 — 남기는 것과 읽히는 것은
다른 사실이고, 둘 중 하나만 있으면 화면은 여전히 비어 있다.

## 개인정보 (SPEC 7.1)

넷을 남기면서 **프로필이 함께 남지 않는지**를 같은 파일에서 잰다. 판정 요청은 감사기록에
아무것도 남기지 않는 것이 규칙이며(「요청 메타만」), 남기지 않는다는 것은 세는 것으로는
확인되지 않는다 — 저장소 전문을 문자열로 훑어 값이 없음을 본다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from home_compass import main as main_module
from home_compass.auth import AUDIT_DENIED, AUDIT_LOGIN, AUDIT_LOGOUT, CSRF_HEADER_NAME, ensure_seed_accounts
from home_compass.main import AUDIT_RULE_DECISION, app
from home_compass.store import PolicySource, RuleDraft, create_store
from home_compass.store.seed import seed_all

T0 = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)

COUNSELOR_PW = os.environ["HOME_COMPASS_SEED_COUNSELOR_PASSWORD"]
RULE_MANAGER_PW = os.environ["HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD"]

APPROVE_DRAFT = "audit-draft-approve"
REJECT_DRAFT = "audit-draft-reject"

#: 판정 요청에 실을 **눈에 띄는 숫자들.** 아무 데도 남으면 안 된다 (SPEC 7.1).
#: 값이 특이한 이유는 우연히 다른 곳에서 나오는 숫자와 겹치지 않게 하기 위해서다.
PROFILE = {
    "age": 37,
    "annualIncomeKRW": 73_412_000,
    "monthlyNetIncomeKRW": 4_931_000,
    "liquidAssetsKRW": 61_237_000,
    "existingDebtMonthlyKRW": 812_000,
    "householdSize": 4,
    "regionCode": "11440",
}

#: 위 프로필에서 **문자열로 찾을 수 있는 자국.** 정수 그대로와 콤마 표기 둘 다 본다 —
#: 어느 쪽으로 새는지는 새는 코드가 정하지 우리가 정하지 않는다.
PROFILE_MARKS = tuple(
    mark
    for value in (PROFILE["annualIncomeKRW"], PROFILE["monthlyNetIncomeKRW"],
                  PROFILE["liquidAssetsKRW"], PROFILE["existingDebtMonthlyKRW"])
    for mark in (str(value), f"{value:,}")
)


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'audit.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
        store.policy_sources.add(
            PolicySource(id="src-audit", text="제1조 신청 연령은 만 19세 이상.",
                         source_ref=None, fetched_at=T0)
        )
        for draft_id in (APPROVE_DRAFT, REJECT_DRAFT):
            store.rule_drafts.add(
                RuleDraft(id=draft_id, policy_source_id="src-audit",
                          policy_id=f"policy-{draft_id}", status="pending",
                          payload={"policy_id": f"policy-{draft_id}", "criteria": {}},
                          created_at=T0)
            )
    monkeypatch.setenv("HOME_COMPASS_STORE_URL", url)
    return url


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "observability.jsonl"
    monkeypatch.setenv("HOME_COMPASS_LOG_FILE", str(path))
    return path


@pytest.fixture
def client(store_url, log_file, monkeypatch) -> TestClient:
    monkeypatch.setattr(main_module, "request_now", lambda: T0)
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def events(store_url: str, action: str) -> list:
    with create_store(store_url) as store:
        return store.audit.list(action=action)


def all_events(store_url: str) -> list:
    with create_store(store_url) as store:
        return store.audit.list()


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login",
                           json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


# ==========================================================================
# 1. 규칙 승인·반려 (필수 기록 ①)
# ==========================================================================

class TestRuleDecisionsAreRecorded:
    def test_an_approval_leaves_an_audit_event(self, client, store_url):
        csrf = login(client, "rulemanager", RULE_MANAGER_PW)
        response = client.post(f"/api/admin/drafts/{APPROVE_DRAFT}/approve",
                               json={"reason": "공고 대조 완료"},
                               headers={CSRF_HEADER_NAME: csrf})
        assert response.status_code == 200, response.text

        recorded = events(store_url, AUDIT_RULE_DECISION["approved"])
        assert len(recorded) == 1
        assert recorded[0].actor == "rulemanager"
        assert recorded[0].target == APPROVE_DRAFT
        assert recorded[0].at == T0

    def test_a_rejection_leaves_an_audit_event(self, client, store_url):
        csrf = login(client, "rulemanager", RULE_MANAGER_PW)
        response = client.post(f"/api/admin/drafts/{REJECT_DRAFT}/reject",
                               json={"reason": "3조 인용이 원문과 다르다"},
                               headers={CSRF_HEADER_NAME: csrf})
        assert response.status_code == 200, response.text

        recorded = events(store_url, AUDIT_RULE_DECISION["rejected"])
        assert len(recorded) == 1
        assert recorded[0].actor == "rulemanager"
        assert recorded[0].target == REJECT_DRAFT

    def test_a_refused_decision_leaves_no_decision_record(self, client, store_url):
        """★ 거부된 결정이 기록되면 원장이 **일어나지 않은 일**을 말한다.

        승인은 한 번만 일어나야 하고(SPEC 4.6), 두 번째 시도는 409 다. 그 시도가
        `rule.approve` 를 하나 더 남기면 나중에 이 초안은 두 번 승인된 것으로 읽힌다.
        """
        csrf = login(client, "rulemanager", RULE_MANAGER_PW)
        headers = {CSRF_HEADER_NAME: csrf}
        client.post(f"/api/admin/drafts/{APPROVE_DRAFT}/approve",
                    json={"reason": "첫 번째"}, headers=headers)
        again = client.post(f"/api/admin/drafts/{APPROVE_DRAFT}/approve",
                            json={"reason": "두 번째"}, headers=headers)
        assert again.status_code == 409, again.text
        assert len(events(store_url, AUDIT_RULE_DECISION["approved"])) == 1


# ==========================================================================
# 2. 로그인 및 실패 (필수 기록 ②)
# ==========================================================================

class TestLoginsAndFailuresAreRecorded:
    def test_a_successful_login_is_recorded(self, client, store_url):
        login(client, "counselor", COUNSELOR_PW)
        recorded = events(store_url, AUDIT_LOGIN)
        assert [e.outcome for e in recorded] == ["success"]
        assert recorded[0].actor == "counselor"
        assert recorded[0].after == {"role": "counselor"}

    def test_a_failed_login_is_recorded_and_carries_no_password(self, client, store_url):
        secret = "이-비밀번호는-틀렸다-9182"
        response = client.post("/api/auth/login",
                               json={"username": "counselor", "password": secret})
        assert response.status_code == 401

        recorded = events(store_url, AUDIT_LOGIN)
        assert [e.outcome for e in recorded] == ["failure"]
        assert recorded[0].actor == "counselor"
        # **비밀번호는 어디에도 없다.** 실패 사유는 분류이지 입력값이 아니다.
        assert secret not in json.dumps(recorded[0].after or {}, ensure_ascii=False)
        assert recorded[0].after == {"reason": "invalid_credentials"}

    def test_a_login_for_an_unknown_account_is_recorded_too(self, client, store_url):
        """없는 계정이 조용히 지나가면 **계정 열거 시도**가 원장에 안 남는다."""
        response = client.post("/api/auth/login",
                               json={"username": "없는사람", "password": "x"})
        assert response.status_code == 401
        recorded = events(store_url, AUDIT_LOGIN)
        assert [(e.actor, e.outcome) for e in recorded] == [("없는사람", "failure")]

    def test_logout_is_recorded(self, client, store_url):
        csrf = login(client, "counselor", COUNSELOR_PW)
        assert client.post("/api/auth/logout", json={},
                           headers={CSRF_HEADER_NAME: csrf}).status_code == 200
        assert [e.outcome for e in events(store_url, AUDIT_LOGOUT)] == ["success"]


# ==========================================================================
# 3. 권한 거부 (필수 기록 ④)
# ==========================================================================

class TestAuthorizationDenialsAreRecorded:
    def test_an_anonymous_denial_is_recorded(self, client, store_url):
        assert client.get("/api/admin/drafts").status_code == 401
        recorded = events(store_url, AUDIT_DENIED)
        assert len(recorded) == 1
        assert recorded[0].actor == "anonymous"
        assert recorded[0].outcome == "denied"
        # `target` 은 **시도한 동작**이다. 없으면 [무엇을 하려다 막혔는가] 가 사라진다.
        assert recorded[0].target == "draft.read"
        assert recorded[0].after == {"reason": "unauthenticated"}

    def test_a_counselor_denial_names_the_actor(self, client, store_url):
        """★ 이것이 SoD 의 기록이다 — **누가** 무엇을 시도해서 막혔는가."""
        login(client, "counselor", COUNSELOR_PW)
        assert client.get("/api/admin/drafts").status_code == 403

        recorded = events(store_url, AUDIT_DENIED)
        assert [e.actor for e in recorded] == ["counselor"]
        assert recorded[0].target == "draft.read"
        assert recorded[0].after == {"reason": "forbidden"}

    def test_the_status_screen_is_behind_the_same_gate_and_the_denial_is_recorded(
            self, client, store_url):
        """7단계 신규 경로도 같은 게이트 뒤에 있고, 거부도 같은 원장에 남는다."""
        login(client, "counselor", COUNSELOR_PW)
        assert client.get("/api/admin/status").status_code == 403
        recorded = events(store_url, AUDIT_DENIED)
        assert [(e.actor, e.target) for e in recorded] == [("counselor", "status.read")]


# ==========================================================================
# 4. 배치 실행 결과 (필수 기록 ③) — 읽히는 것까지 확인한다
# ==========================================================================

class TestTheBatchRunRecordReachesTheScreen:
    def test_with_no_batch_history_the_screen_says_so_instead_of_zero(
            self, client, store_url):
        """★ **0% 로 채우지 않는다.** 아직 안 돈 것과 실패율 0% 는 다른 사실이다."""
        login(client, "rulemanager", RULE_MANAGER_PW)
        batch = client.get("/api/admin/status").json()["batch"]
        assert batch["runs"] == 0
        assert batch["successRatePct"] is None
        assert batch["lastRunAt"] is None

    def test_the_screen_counts_the_run_records(self, client, store_url):
        """성공 2 · 실패 1 을 심고 화면이 66.7% 를 내는지 본다."""
        from home_compass.store.models import AuditEvent

        with create_store(store_url) as store:
            for index, outcome in enumerate(("success", "success", "failed"), start=1):
                store.audit.append(AuditEvent(
                    id=f"audit-run-{index}", actor="system:ingest", at=T0,
                    action=main_module.MARKET_RUN_ACTION,
                    target=f"market-run-{index:06d}", outcome=outcome,
                    after={"runId": f"market-run-{index:06d}",
                           "committed": outcome == "success"},
                ))

        login(client, "rulemanager", RULE_MANAGER_PW)
        batch = client.get("/api/admin/status").json()["batch"]
        assert batch["runs"] == 3
        assert batch["succeeded"] == 2
        assert batch["failed"] == 1
        assert batch["successRatePct"] == 66.7
        assert batch["lastOutcome"] == "failed"
        # 분모가 무엇인지가 숫자 옆에 실려 나간다 (코디네이터 지시).
        assert "market.run" in batch["denominator"]

    def test_the_action_name_matches_the_batch_that_writes_it(self):
        """★ `api` 는 `ingest` 를 import 하지 않는다 (SPEC 1.2 의존 그래프).

        그래서 action 문자열이 두 벌 존재하고, **어긋나면 화면이 조용히 0 을 그린다** —
        읽는 쪽이 없는 action 을 물으면 빈 목록이 오고 그것은 [배치가 안 돌았다] 와
        구분되지 않는다. 두 벌을 잇는 것은 이 테스트뿐이므로 여기서 붙든다.
        """
        from home_compass.ingest.extraction import EXTRACTION_ACTION
        from home_compass.ingest.market.pipeline import ACTION_RUN

        assert main_module.MARKET_RUN_ACTION == ACTION_RUN
        assert main_module.EXTRACTION_ACTION == EXTRACTION_ACTION


# ==========================================================================
# 5. ★ 프로필은 남지 않는다 (SPEC 7.1 「요청 메타만」)
# ==========================================================================

class TestTheCitizenProfileNeverReachesTheAuditLog:
    def test_an_analyze_request_leaves_no_audit_event_at_all(self, client, store_url):
        """판정 요청은 원장에 아무것도 남기지 않는다. 남길 것이 없기 때문이다."""
        before = len(all_events(store_url))
        assert client.post("/api/analyze", json=PROFILE).status_code == 200
        assert len(all_events(store_url)) == before

    def test_no_audit_row_anywhere_carries_a_profile_number(self, client, store_url):
        """★ **세는 것으로는 확인되지 않는다.** 원장 전문을 문자열로 훑는다.

        판정 · 채팅 · 로그인 · 승인 · 반려 · 거부를 한 줄기로 친 뒤, 저장소에 남은 감사
        기록 전부를 직렬화해 프로필 값의 자국이 있는지 본다. 「그 엔드포인트는 기록을
        안 한다」는 코드를 읽은 결과이고, 이것은 저장소를 연 결과다.
        """
        client.post("/api/analyze", json=PROFILE)
        client.post("/api/chat", json={"message": "전세와 월세 중 뭐가 나을까요",
                                       "profile": PROFILE})
        client.get("/api/admin/drafts")                       # 익명 거부
        csrf = login(client, "rulemanager", RULE_MANAGER_PW)
        client.post(f"/api/admin/drafts/{APPROVE_DRAFT}/approve",
                    json={"reason": "대조 완료"}, headers={CSRF_HEADER_NAME: csrf})
        client.post(f"/api/admin/drafts/{REJECT_DRAFT}/reject",
                    json={"reason": "원문과 다르다"}, headers={CSRF_HEADER_NAME: csrf})

        rows = all_events(store_url)
        assert rows, "감사기록이 하나도 없다 — 이 검사가 아무것도 확인하지 못한다"
        serialised = json.dumps(
            [{"actor": e.actor, "action": e.action, "target": e.target,
              "outcome": e.outcome, "before": e.before, "after": e.after} for e in rows],
            ensure_ascii=False, default=str,
        )
        leaked = [mark for mark in PROFILE_MARKS if mark in serialised]
        assert not leaked, f"프로필 값이 감사기록에 남았다 (SPEC 7.1): {leaked}"
