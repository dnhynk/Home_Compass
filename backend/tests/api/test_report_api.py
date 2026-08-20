"""SPEC 6.4 · 6.1 · 7.1 — 상담원 이상 신고 경로 (소유자: `api`).

6.4 가 이 경로를 만든 이유는 표시가 아니라 **유입**이다 — 「이 피드백 경로가 없으면
현장에서 발견된 오류가 시스템에 들어오지 못한다」. 그래서 이 파일이 재는 것은
[엔드포인트가 200 을 내는가] 가 아니라 SPEC 10.2 의 6-A 완료 기준 **셋** 이다.

    1. 신고가 **별도 유형**으로 큐에 쌓인다 (추출 draft 와 구분된다)
    2. ★★ **신고로 규칙이 바뀌지 않는다** (권한 테스트 — SoD 유지)
    3. 병합해도 **신고와 draft 의 `AuditEvent` 가 각각 독립 보존**된다

## 이 과업의 지배적 실패 양상 둘을 여기서 붙든다

**(가) 신고를 「작은 draft」로 만드는 것.** 그래서 2번을 두 각도로 잰다 — 상담원 세션이
승인 API 에서 거부되는 것과, **신고를 아무리 만들어도 `RuleVersion` 이 생기지 않는 것.**
앞의 하나만으로는 부족하다. 신고가 어딘가에서 조용히 규칙으로 승격되는 경로가 있다면
그것은 승인 API 가 아니라 신고 API 쪽에 생긴다.

**(나) 개인정보** (SPEC 7.1 의 표). 사유는 자유 입력이라 고객 상황이 섞일 수 있다.
구조로 막을 수 있는 것은 **대상**뿐이므로 대상이 정책·시세 항목으로 한정되는지를 재고,
그 위에 **오류 응답이 입력값을 되비추지 않는지**를 함께 잰다 — 검증 실패 응답이 값을
인용하는 순간 사유 본문이 로그·스크린샷·버그리포트로 새어 나간다.

격리: 케이스마다 자기 `tmp_path` 저장소를 만들어 `FIRSTHOME_STORE_URL` 을 그쪽으로 돌린다.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from firsthome import main as main_module
from firsthome.auth import CSRF_HEADER_NAME, ensure_seed_accounts
from firsthome.main import AUDIT_REPORT_CREATED, Policy, app
from firsthome.store import PolicySource, RuleDraft, create_store
from firsthome.store.models import POLICY_REPORT_FIELDS, REGION_FACT_FIELDS
from firsthome.store.seed import seed_all

T0 = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)

COUNSELOR_PW = os.environ["FIRSTHOME_SEED_COUNSELOR_PASSWORD"]
RULE_MANAGER_PW = os.environ["FIRSTHOME_SEED_RULE_MANAGER_PASSWORD"]

REPORTS = "/api/reports"
ADMIN_REPORTS = "/api/admin/reports"

#: 시드가 심는 정책 하나. 신고 대상이 **실재해야** 한다는 것을 API 가 본다.
SEEDED_POLICY = "buttress_youth"
SEEDED_REGION = "11440"

#: 고객 상황이 섞인 자유 입력의 대역. 이 문자열이 오류 응답에 되비쳐 나오면 안 된다.
PRIVATE_REASON = "고객이 이 제도가 지난달에 없어졌다고 한다"


def body(**over) -> dict:
    payload = {
        "targetKind": "policy",
        "targetId": SEEDED_POLICY,
        "targetField": "status",
        "reason": PRIVATE_REASON,
    }
    payload.update(over)
    return payload


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'reports.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
        store.policy_sources.add(
            PolicySource(id="src-report", text="제1조 신청 연령은 만 19세 이상.",
                         source_ref=None, fetched_at=T0)
        )
    monkeypatch.setenv("FIRSTHOME_STORE_URL", url)
    return url


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(main_module, "request_now", lambda: T0)


@pytest.fixture
def client(store_url, clock) -> TestClient:
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login",
                           json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def as_counselor(client: TestClient) -> str:
    return login(client, "counselor", COUNSELOR_PW)


def as_rule_manager(client: TestClient) -> str:
    return login(client, "rulemanager", RULE_MANAGER_PW)


def file_report(client: TestClient, csrf: str, **over):
    return client.post(REPORTS, json=body(**over), headers={CSRF_HEADER_NAME: csrf})


def add_draft(store_url: str, draft_id: str, policy_id: str, *, status: str = "pending") -> None:
    with create_store(store_url) as store:
        store.rule_drafts.add(
            RuleDraft(id=draft_id, policy_source_id="src-report", policy_id=policy_id,
                      status=status, payload={"policy_id": policy_id, "criteria": {}},
                      created_at=T0)
        )


def audit_of(store_url: str, action: str) -> list:
    with create_store(store_url) as store:
        return store.audit.list(action=action)


# ==========================================================================
# 1. 권한 (SPEC 6.1) — 누가 신고할 수 있고 누가 큐를 보는가
# ==========================================================================

class TestWhoMayFileAReport:
    def test_anonymous_cannot_file_one(self, client):
        """SPEC 6.4 — **익명은 안 된다.** 신고자가 없는 신고는 감사추적을 끊는다."""
        assert client.post(REPORTS, json=body()).status_code == 401

    def test_a_counselor_can(self, client):
        """★ 6.4 의 출발점 — 최전선 탐지자가 실제로 올릴 수 있어야 한다."""
        csrf = as_counselor(client)
        response = file_report(client, csrf)
        assert response.status_code == 200, response.text
        assert response.json()["reporter"] == "counselor"

    def test_a_rule_manager_can_too(self, client):
        csrf = as_rule_manager(client)
        assert file_report(client, csrf).status_code == 200

    def test_a_state_change_still_needs_the_csrf_token(self, client):
        """SPEC 6.3 — 신고 생성도 상태변경이다."""
        as_counselor(client)
        assert client.post(REPORTS, json=body()).status_code == 403


class TestWhoMaySeeTheQueue:
    def test_anonymous_is_refused(self, client):
        assert client.get(ADMIN_REPORTS).status_code == 401

    def test_a_counselor_is_refused(self, client):
        """신고 큐는 규칙관리자의 작업대다. 올리는 것과 보는 것은 다른 권한이다."""
        as_counselor(client)
        assert client.get(ADMIN_REPORTS).status_code == 403

    def test_a_rule_manager_sees_it(self, client):
        assert as_rule_manager(client) and client.get(ADMIN_REPORTS).status_code == 200


# ==========================================================================
# 2. ★★ 신고로 규칙이 바뀌지 않는다 (SPEC 10.2 6-A · 6.1 SoD)
# ==========================================================================

class TestAReportChangesNoRule:
    def test_a_counselor_session_is_still_refused_at_the_approval_api(self, client, store_url):
        """SoD 는 신고 경로가 생겨도 그대로다 — 신고는 제안이지 변경이 아니다."""
        add_draft(store_url, "d-1", SEEDED_POLICY)
        csrf = as_counselor(client)
        file_report(client, csrf)

        denied = client.post("/api/admin/drafts/d-1/approve", json={"reason": "상담원이 승인을 시도한다"},
                             headers={CSRF_HEADER_NAME: csrf})
        assert denied.status_code == 403, denied.text

    def test_filing_reports_creates_no_rule_version(self, client, store_url):
        """★ 승인 API 거부만으로는 부족하다 — **신고 API 자체**가 규칙을 낳지 않아야 한다."""
        with create_store(store_url) as store:
            before = {v.id for v in store.rule_versions.list()}
            drafts_before = {d.id for d in store.rule_drafts.list()}

        csrf = as_counselor(client)
        for field_name in POLICY_REPORT_FIELDS:
            assert file_report(client, csrf, targetField=field_name).status_code == 200

        with create_store(store_url) as store:
            assert {v.id for v in store.rule_versions.list()} == before
            # 신고가 「작은 draft」로 새지 않는다 (계약 결정 #38).
            assert {d.id for d in store.rule_drafts.list()} == drafts_before

    def test_the_verdict_does_not_move_after_a_report(self, client):
        """SPEC 2.3 — 판정에 참여하는 것은 승인된 규칙뿐이다. 신고는 거기 없다."""
        profile = {"regionCode": SEEDED_REGION, "annualIncomeKRW": 42_000_000}
        before = client.post("/api/analyze", json=profile).json()

        csrf = as_counselor(client)
        file_report(client, csrf)

        after = client.post("/api/analyze", json=profile).json()
        assert after["policies"] == before["policies"]


# ==========================================================================
# 3. ★ 대상은 정책·시세 항목으로 한정된다 (SPEC 7.1 · 계약 결정 #38)
# ==========================================================================

class TestTheTargetIsAnItemNotFreeText:
    @pytest.mark.parametrize("bad", [
        {"targetField": "고객 김OO 님 상황"},
        {"targetField": ""},
        {"targetKind": "customer"},
        {"targetField": "maxAmountKRW", "targetKind": "region", "targetId": SEEDED_REGION},
    ])
    def test_a_target_outside_the_closed_list_is_refused(self, client, bad):
        csrf = as_counselor(client)
        response = file_report(client, csrf, **bad)
        assert response.status_code == 400, response.text

    def test_a_target_that_does_not_exist_is_refused(self, client):
        """항목 이름만 맞고 **대상이 없는** 신고는 큐에서 아무도 처리할 수 없다."""
        csrf = as_counselor(client)
        assert file_report(client, csrf, targetId="no_such_policy").status_code == 400
        assert file_report(client, csrf, targetKind="region", targetId="99999",
                           targetField="jeonseMedianKRW").status_code == 400

    @pytest.mark.parametrize("field_name", REGION_FACT_FIELDS)
    def test_every_market_fact_is_reportable(self, client, field_name):
        csrf = as_counselor(client)
        response = file_report(client, csrf, targetKind="region",
                               targetId=SEEDED_REGION, targetField=field_name)
        assert response.status_code == 200, response.text

    def test_an_empty_reason_is_refused(self, client):
        csrf = as_counselor(client)
        assert file_report(client, csrf, reason="   ").status_code == 400

    def test_the_policy_item_list_is_derived_from_the_response_schema(self):
        """★ 목록이 **세 번째 사본**이 되지 않게 한다 (코디네이터 조건 ②).

        상담원은 화면에서 본 것을 신고한다. 그 화면이 그리는 것은 판정 응답의 `Policy`
        이므로, 신고 가능한 항목은 그 스키마에서 유도되어야 한다. 손으로 적어 두면
        스키마가 바뀔 때 조용히 어긋나고, 그때 화면에는 있는데 신고는 400 이 된다.

        빠지는 둘에는 각각 이유가 있다 —
          · `id`   : 대상 그 자체(`targetId`)이지 신고할 **항목**이 아니다
          · `disclaimer` : 엔진이 붙이는 고정 문구다. 데이터가 아니므로 고칠 대상이 없다
        """
        assert set(POLICY_REPORT_FIELDS) == set(Policy.model_fields) - {"id", "disclaimer"}


# ==========================================================================
# 4. 개인정보 — 사유 본문이 되비쳐 나오지 않는다 (SPEC 7.1)
# ==========================================================================
#
# 대상은 구조로 닫았다. **사유 본문은 못 닫는다** — 그래서 최소한 [우리가 만든 경로로
# 새지 않는 것] 을 고정한다. 검증 실패 응답이 입력값을 인용하는 것이 가장 흔한 누출이다.

class TestTheReasonTextIsNotEchoedBack:
    @pytest.mark.parametrize("bad", [
        {"reason": PRIVATE_REASON, "targetField": "없는항목"},
        {"reason": PRIVATE_REASON, "targetId": "no_such_policy"},
        {"reason": PRIVATE_REASON * 400},          # max_length 초과 -> 422
        {"reason": 5},                              # 타입 오류 -> 422
    ])
    def test_no_error_response_quotes_the_free_text(self, client, bad):
        csrf = as_counselor(client)
        response = file_report(client, csrf, **bad)
        assert response.status_code in (400, 422), response.text
        assert PRIVATE_REASON not in response.text

    def test_the_target_id_is_not_reflected_either(self, client):
        """대상 식별자도 클라이언트가 준 문자열이다. 되비추면 그 자리가 곧 반사 경로다."""
        csrf = as_counselor(client)
        response = file_report(client, csrf, targetId="<script>alert(1)</script>")
        assert response.status_code == 400
        assert "script" not in response.text


# ==========================================================================
# 5. 신고가 별도 유형으로 큐에 쌓인다 (SPEC 10.2 6-A 첫째)
# ==========================================================================

class TestTheQueueKeepsTheTwoTypesApart:
    def test_a_report_shows_up_in_the_report_queue(self, client):
        csrf = as_counselor(client)
        file_report(client, csrf)
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})

        as_rule_manager(client)
        queue = client.get(ADMIN_REPORTS).json()["reports"]
        assert len(queue) == 1
        assert queue[0]["targetId"] == SEEDED_POLICY
        assert queue[0]["reason"] == PRIVATE_REASON
        assert queue[0]["status"] == "open"

    def test_it_never_shows_up_in_the_draft_queue(self, client, store_url):
        """★ 「별도 유형」의 뜻 — 초안 목록이 신고를 하나도 모르는 상태여야 한다."""
        add_draft(store_url, "d-1", SEEDED_POLICY)
        csrf = as_counselor(client)
        file_report(client, csrf)
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})

        as_rule_manager(client)
        drafts = client.get("/api/admin/drafts").json()["drafts"]
        assert [d["id"] for d in drafts] == ["d-1"]


# ==========================================================================
# 6. 신고와 draft 의 충돌 — SPEC 6.4 의 **잠정** 규칙
# ==========================================================================
#
# > 잠정 규칙이다. 실제 운영에서 신고 빈도와 draft 빈도의 비율을 본 뒤 재검토한다.
#
# 그 문장이 이 절의 전제다. 여기서 고정하는 것은 [지금 이렇게 동작한다] 이지
# [이것이 옳다] 가 아니다.

class TestTheProvisionalMergeRule:
    def test_a_report_on_the_same_policy_merges_with_the_pending_draft(self, client, store_url):
        add_draft(store_url, "d-1", SEEDED_POLICY)
        csrf = as_counselor(client)
        filed = file_report(client, csrf).json()
        assert filed["mergedDraftIds"] == ["d-1"]

    def test_a_report_with_no_draft_stands_alone_in_the_queue(self, client):
        """「신고만 있고 draft 가 없으면 신고 단독 항목으로 큐에 남는다」."""
        csrf = as_counselor(client)
        assert file_report(client, csrf).json()["mergedDraftIds"] == []

    def test_a_decided_draft_is_no_longer_a_merge_target(self, client, store_url):
        """결정이 끝난 초안은 검토 항목이 아니다 — 거기 붙이면 다시 열리는 것처럼 보인다."""
        add_draft(store_url, "d-done", SEEDED_POLICY, status="approved")
        csrf = as_counselor(client)
        assert file_report(client, csrf).json()["mergedDraftIds"] == []

    def test_a_market_report_never_merges(self, client, store_url):
        """병합 조건은 「대상 **정책**이 같으면」이다. 시세 신고에는 짝이 없다."""
        add_draft(store_url, "d-1", SEEDED_POLICY)
        csrf = as_counselor(client)
        filed = file_report(client, csrf, targetKind="region", targetId=SEEDED_REGION,
                            targetField="jeonseMedianKRW").json()
        assert filed["mergedDraftIds"] == []

    def test_the_review_screen_sees_the_report_as_draft_context(self, client, store_url):
        """「검토자는 *기계가 이렇게 추출했고, 현장에서는 이런 문제가 보고됐다* 를 함께 본다」."""
        add_draft(store_url, "d-1", SEEDED_POLICY)
        csrf = as_counselor(client)
        file_report(client, csrf)
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})

        as_rule_manager(client)
        detail = client.get("/api/admin/drafts/d-1").json()
        assert [r["reason"] for r in detail["reports"]] == [PRIVATE_REASON]

    def test_an_unrelated_policy_is_not_attached(self, client, store_url):
        add_draft(store_url, "d-other", "newlywed_jeonse")
        csrf = as_counselor(client)
        file_report(client, csrf)
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf})

        as_rule_manager(client)
        assert client.get("/api/admin/drafts/d-other").json()["reports"] == []


# ==========================================================================
# 7. ★ 병합해도 양쪽 `AuditEvent` 가 보존된다 (SPEC 10.2 6-A 셋째 · 6.4 · 7.1)
# ==========================================================================

class TestBothAuditTrailsSurviveTheMerge:
    def test_filing_records_who_when_what_and_why(self, client, store_url):
        """SPEC 6.4 — 신고자·시각·대상·사유를 남긴다. 넷 전부다."""
        csrf = as_counselor(client)
        filed = file_report(client, csrf).json()

        events = audit_of(store_url, AUDIT_REPORT_CREATED)
        assert len(events) == 1
        event = events[0]
        assert event.actor == "counselor"           # 신고자
        assert event.at == T0                       # 시각
        assert SEEDED_POLICY in event.target        # 대상
        assert event.after["reason"] == PRIVATE_REASON   # 사유
        assert event.after["reportId"] == filed["id"]

    def test_the_two_trails_stay_separate_after_a_merge(self, client, store_url):
        """★ 병합은 **보여 주는 방식**이지 기록을 합치는 것이 아니다.

        신고 하나와 초안 하나가 같은 정책을 가리키는 상태에서 초안을 승인한 뒤,
        두 사건이 **각각** 남아 있는지를 본다. 하나로 뭉치면 [현장이 무엇을 보고했는가] 와
        [규칙관리자가 무엇을 승인했는가] 가 사후에 갈리지 않는다.
        """
        add_draft(store_url, "d-1", SEEDED_POLICY)
        counselor_csrf = as_counselor(client)
        assert file_report(client, counselor_csrf).json()["mergedDraftIds"] == ["d-1"]
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: counselor_csrf})

        manager_csrf = as_rule_manager(client)
        approved = client.post("/api/admin/drafts/d-1/approve", json={"reason": "현장 신고 확인"},
                               headers={CSRF_HEADER_NAME: manager_csrf})
        assert approved.status_code == 200, approved.text

        report_events = audit_of(store_url, AUDIT_REPORT_CREATED)
        approval_events = audit_of(store_url, "rule.approve")
        assert len(report_events) == 1 and len(approval_events) == 1
        assert report_events[0].actor == "counselor"
        assert approval_events[0].actor == "rulemanager"
        assert report_events[0].id != approval_events[0].id

    def test_the_report_trail_survives_the_draft_being_rejected_too(self, client, store_url):
        add_draft(store_url, "d-1", SEEDED_POLICY)
        counselor_csrf = as_counselor(client)
        file_report(client, counselor_csrf)
        client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: counselor_csrf})

        manager_csrf = as_rule_manager(client)
        client.post("/api/admin/drafts/d-1/reject", json={"reason": "원문과 다르다"},
                    headers={CSRF_HEADER_NAME: manager_csrf})

        assert len(audit_of(store_url, AUDIT_REPORT_CREATED)) == 1
        assert len(audit_of(store_url, "rule.reject")) == 1
