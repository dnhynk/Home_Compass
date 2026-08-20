"""SPEC 4.5 · 4.6 · 10.2 5단계 — 일괄 승인 (소유자: `api`).

4.5 는 「동일 유형 다건은 일괄 승인을 허용한다」고 하고, 4.6 은 그것이 **원자적**이되
`ApprovalRecord` 는 **건별**이라고 못박는다. 둘은 같은 문장의 두 절이 아니라 서로 다른
층위의 요구다 — **원자성은 반영에 걸리고 기록에는 걸리지 않는다.**

    반영(RuleVersion) : 한 건이라도 실패하면 전체가 없다
    기록(ApprovalRecord · AuditEvent) : 승인된 건마다 하나씩 남는다

**이 파일의 지배적 실패 양상은 [일괄이 검토를 건너뛰는 통로가 되는 것]이다.** 그래서
여기서 고정하는 것은 「묶어서 빨리 된다」가 아니라 「묶어도 건별 흔적이 남는다」와
「하나가 틀어지면 아무것도 안 일어난다」 둘이다.

D5 (서로 다른 초안이 같은 정책을 가리키는 경우)는 별도 절에서 다룬다. 그것은 저장소가
막지 못하는 자리이고(PR #58 「검증하지 않은 것」), 일괄 승인이 그 자리를 훨씬 자주 밟는다.

격리: 케이스마다 자기 `tmp_path` 저장소를 만들어 `FIRSTHOME_STORE_URL` 을 그쪽으로 돌린다.
`conftest.py` 의 세션 저장소는 여기서 건드리지 않는다.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from firsthome import main as main_module
from firsthome.auth import CSRF_HEADER_NAME, ensure_seed_accounts
from firsthome.main import app
from firsthome.store import STORE_URL_ENV, PolicySource, RuleDraft, create_store
from firsthome.store.seed import seed_all

T0 = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)

COUNSELOR_PW = os.environ["FIRSTHOME_SEED_COUNSELOR_PASSWORD"]
RULE_MANAGER_PW = os.environ["FIRSTHOME_SEED_RULE_MANAGER_PASSWORD"]

BATCH_PATH = "/api/admin/drafts/batch-approve"

#: 원문. 초안 둘이 같은 원문을 근거로 삼아도 무방하다 — 이 파일이 재는 것은 근거가 아니라
#: 반영의 원자성이다. 근거 대조는 `test_admin_review.py` 소관이다.
SOURCE_TEXT = (
    "청년전용 버팀목전세자금대출 신청 연령은 만 19세 이상 39세 이하입니다. "
    "서울시 청년 임차보증금 이자지원 대상 연소득은 5,500만원 이하입니다."
)


def draft_payload(policy_id: str, *, age_max: int, max_amount: int) -> dict:
    return {
        "policy_id": policy_id,
        "criteria": {
            "ageMin": 19,
            "ageMax": age_max,
            "annualIncomeMaxKRW": 55_000_000,
            "assetMaxKRW": None,
            "requireHomeless": True,
            "requireNewlywed": False,
            "requireSME": False,
            "regionPrefixes": None,
        },
        "maxAmountKRW": max_amount,
        "rateRangePct": [1.8, 3.1],
        "conditionalChecks": [],
        "not_found": ["/criteria/assetMaxKRW"],
    }


# --------------------------------------------------------------------------
# 픽스처 — `test_approval_concurrency.py` 와 같은 모양이다 (이 디렉터리의 관례)
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'batch.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
        store.policy_sources.add(
            PolicySource(
                id="src-batch",
                text=SOURCE_TEXT,
                source_ref="https://nhuf.molit.go.kr/",
                fetched_at=T0,
                attribution="주택도시기금 공고",
            )
        )
    monkeypatch.setenv(STORE_URL_ENV, url)
    return url


@pytest.fixture
def clock(monkeypatch):
    """고정 시계. `supersede` 가 `at > previous.effective_from` 을 요구하므로 벽시계로
    두면 이 파일이 재는 것이 원자성이 아니라 순서 불변식이 된다."""
    holder = {"now": T0}
    monkeypatch.setattr(main_module, "request_now", lambda: holder["now"])
    return holder


@pytest.fixture
def client(store_url, clock) -> TestClient:
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def seed_draft(store_url: str, draft_id: str, policy_id: str, **kwargs) -> str:
    with create_store(store_url) as store:
        store.rule_drafts.add(
            RuleDraft(
                id=draft_id,
                policy_source_id="src-batch",
                policy_id=policy_id,
                status="pending",
                payload=draft_payload(policy_id, **kwargs),
                created_at=T0,
            )
        )
    return draft_id


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def as_rule_manager(client: TestClient) -> str:
    return login(client, "rulemanager", RULE_MANAGER_PW)


def as_counselor(client: TestClient) -> str:
    return login(client, "counselor", COUNSELOR_PW)


def batch(client: TestClient, csrf: str | None, draft_ids: list[str], reason: str | None = None):
    body: dict = {"draftIds": draft_ids}
    if reason is not None:
        body["reason"] = reason
    headers = {} if csrf is None else {CSRF_HEADER_NAME: csrf}
    return client.post(BATCH_PATH, json=body, headers=headers)


def snapshot(store_url: str) -> dict:
    """반영의 흔적 전부. 원자성은 [이 스냅샷이 통째로 그대로인가] 로 잰다."""
    with create_store(store_url) as store:
        return {
            "ruleVersions": sorted(v.id for v in store.rule_versions.list()),
            "approvals": sorted((r.target_id, r.decision) for r in store.approvals.list()),
            "draftStatus": sorted((d.id, d.status) for d in store.rule_drafts.list()),
            "audit": sorted(
                (e.action, e.target, e.outcome)
                for e in store.audit.list()
                if e.action.startswith("rule.")
            ),
        }


# ==========================================================================
# 1. 권한 — 화면이 버튼을 숨기는 것에 기대지 않는다 (SPEC 6.1)
# ==========================================================================

class TestTheBatchEndpointIsBehindTheRuleManagerRole:
    def test_anonymous_is_refused(self, client, store_url):
        seed_draft(store_url, "d-anon", "buttress_youth", age_max=39, max_amount=250_000_000)
        before = snapshot(store_url)
        response = batch(client, None, ["d-anon"])
        assert response.status_code == 401, response.text
        assert snapshot(store_url) == before

    def test_a_counselor_session_is_refused(self, client, store_url):
        seed_draft(store_url, "d-counselor", "buttress_youth", age_max=39, max_amount=250_000_000)
        csrf = as_counselor(client)
        before = snapshot(store_url)
        response = batch(client, csrf, ["d-counselor"])
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"
        assert snapshot(store_url) == before

    def test_the_counselor_denial_is_audited(self, client, store_url):
        seed_draft(store_url, "d-audit", "buttress_youth", age_max=39, max_amount=250_000_000)
        csrf = as_counselor(client)
        batch(client, csrf, ["d-audit"])
        with create_store(store_url) as store:
            denials = [e for e in store.audit.list() if e.action == "authz.denied"]
        assert any(e.actor == "counselor" and e.target == "draft.decide" for e in denials)

    def test_a_missing_csrf_token_is_refused(self, client, store_url):
        seed_draft(store_url, "d-csrf", "buttress_youth", age_max=39, max_amount=250_000_000)
        as_rule_manager(client)
        before = snapshot(store_url)
        response = client.post(BATCH_PATH, json={"draftIds": ["d-csrf"]})
        assert response.status_code == 403, response.text
        assert snapshot(store_url) == before


# ==========================================================================
# 2. 건별 기록 — 「일괄 승인도 건별 ApprovalRecord 를 남긴다」 (SPEC 4.5 · 10.2 5단계)
# ==========================================================================

class TestABatchLeavesOneRecordPerDraft:
    def test_two_drafts_produce_two_approval_records_and_two_rule_versions(self, client, store_url):
        seed_draft(store_url, "d-1", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-2", "seoul_deposit_interest", age_max=41, max_amount=210_000_000)
        csrf = as_rule_manager(client)

        response = batch(client, csrf, ["d-1", "d-2"], reason="현장 확인 완료")
        assert response.status_code == 200, response.text

        body = response.json()
        assert [r["draftId"] for r in body["results"]] == ["d-1", "d-2"]
        assert {r["decision"] for r in body["results"]} == {"approved"}

        with create_store(store_url) as store:
            approvals = store.approvals.list()
            versions = {v.id: v for v in store.rule_versions.list()}
        # 건별이다 — 묶었다고 하나로 합치지 않는다.
        assert len(approvals) == 2
        assert {a.target_id for a in approvals} == {"approval:d-1", "approval:d-2"}
        assert all(a.decision == "approved" for a in approvals)
        assert "approval:d-1" in versions and "approval:d-2" in versions

    def test_each_draft_gets_its_own_audit_event(self, client, store_url):
        seed_draft(store_url, "d-1", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-2", "seoul_deposit_interest", age_max=41, max_amount=210_000_000)
        csrf = as_rule_manager(client)
        assert batch(client, csrf, ["d-1", "d-2"]).status_code == 200

        with create_store(store_url) as store:
            approvals = [e for e in store.audit.list() if e.action == "rule.approve"]
        assert sorted(e.target for e in approvals) == ["d-1", "d-2"]

    def test_the_reason_is_carried_onto_every_record(self, client, store_url):
        seed_draft(store_url, "d-1", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-2", "seoul_deposit_interest", age_max=41, max_amount=210_000_000)
        csrf = as_rule_manager(client)
        assert batch(client, csrf, ["d-1", "d-2"], reason="일괄 검토 2026-08-14").status_code == 200

        with create_store(store_url) as store:
            reasons = {r.target_id: r.reason for r in store.approvals.list()}
        assert reasons == {
            "approval:d-1": "일괄 검토 2026-08-14",
            "approval:d-2": "일괄 검토 2026-08-14",
        }

    def test_a_single_draft_batch_is_the_same_as_a_single_approval(self, client, store_url):
        seed_draft(store_url, "d-only", "buttress_youth", age_max=39, max_amount=250_000_000)
        csrf = as_rule_manager(client)
        assert batch(client, csrf, ["d-only"]).status_code == 200
        with create_store(store_url) as store:
            assert store.rule_drafts.get("d-only").status == "approved"
            assert store.rule_versions.get("approval:d-only") is not None


# ==========================================================================
# 3. 원자성 — 「한 건이라도 실패하면 전체가 반영되지 않는다」 (SPEC 4.6)
# ==========================================================================

class TestNothingIsReflectedWhenAnyDraftFails:
    def test_an_already_decided_draft_aborts_the_whole_batch(self, client, store_url):
        seed_draft(store_url, "d-ok", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-dead", "seoul_deposit_interest", age_max=41, max_amount=210_000_000)
        csrf = as_rule_manager(client)
        # 먼저 한 건을 단건으로 승인해 둔다 — 일괄이 밟게 될 현실적인 상태다.
        assert client.post(
            "/api/admin/drafts/d-dead/approve", json={}, headers={CSRF_HEADER_NAME: csrf}
        ).status_code == 200

        before = snapshot(store_url)
        response = batch(client, csrf, ["d-ok", "d-dead"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "draft_already_decided"
        # **아무것도 반영되지 않는다** — 성공했을 d-ok 까지 없다.
        assert snapshot(store_url) == before

    def test_the_surviving_draft_is_left_pending_not_claimed(self, client, store_url):
        """선점만 하고 놓아 준 초안이 결정 칸에 갇히면 재시도조차 막힌다."""
        seed_draft(store_url, "d-ok", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-dead", "seoul_deposit_interest", age_max=41, max_amount=210_000_000)
        csrf = as_rule_manager(client)
        assert client.post(
            "/api/admin/drafts/d-dead/reject",
            json={"reason": "원문 불일치"},
            headers={CSRF_HEADER_NAME: csrf},
        ).status_code == 200

        assert batch(client, csrf, ["d-ok", "d-dead"]).status_code == 409
        with create_store(store_url) as store:
            assert store.rule_drafts.get("d-ok").status == "pending"

        # 그리고 다시 시도하면 통과해야 한다 — 실패가 초안을 못 쓰게 만들지 않았다.
        assert batch(client, csrf, ["d-ok"]).status_code == 200

    def test_an_unknown_draft_id_aborts_the_whole_batch(self, client, store_url):
        seed_draft(store_url, "d-ok", "buttress_youth", age_max=39, max_amount=250_000_000)
        csrf = as_rule_manager(client)
        before = snapshot(store_url)
        response = batch(client, csrf, ["d-ok", "d-nope"])
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "draft_not_found"
        assert snapshot(store_url) == before

    def test_an_empty_batch_is_refused(self, client, store_url):
        csrf = as_rule_manager(client)
        response = batch(client, csrf, [])
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "draft_ids_required"

    def test_the_same_draft_twice_in_one_request_is_refused(self, client, store_url):
        """같은 초안을 두 번 실으면 [한 번만 일어난다]가 요청 안에서 깨진다."""
        seed_draft(store_url, "d-1", "buttress_youth", age_max=39, max_amount=250_000_000)
        csrf = as_rule_manager(client)
        before = snapshot(store_url)
        response = batch(client, csrf, ["d-1", "d-1"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "duplicate_draft_id"
        assert snapshot(store_url) == before


# ==========================================================================
# 4. D5 — 서로 다른 초안이 같은 정책을 가리키는 경우
# ==========================================================================
#
# PR #58 이 막은 것은 **같은 초안**의 중복 승인이다. 초안 A·B 가 같은 `policy_id` 를
# 승인하면 둘 다 선점에 성공하고 `supersede` 에서 하나가 `StoreError` 로 터진다 —
# 409 가 아니라 **500**. 코디네이터 판정에 따라 **API 계층에서** 막는다.
#
# ★ 이것은 회피이지 해결이 아니다. 저장소 계층은 여전히 이 경합을 막지 못하며,
#   그 사실은 PR 본문 ⑥ 에 적힌다.

class TestTwoDraftsForOnePolicyAreRefusedBeforeAnythingIsWritten:
    def test_the_batch_is_refused_with_409(self, client, store_url):
        seed_draft(store_url, "d-a", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-b", "buttress_youth", age_max=34, max_amount=200_000_000)
        csrf = as_rule_manager(client)

        before = snapshot(store_url)
        response = batch(client, csrf, ["d-a", "d-b"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "duplicate_policy_target"
        assert snapshot(store_url) == before

    def test_a_batch_blocked_after_claiming_releases_every_claim(self, client, store_url):
        """선점까지 갔다가 막힌 경로 — **초안이 결정 칸에 갇히면 안 된다.**

        같은 정책의 다른 초안이 **같은 시각에** 이미 승인돼 있으면 `supersede` 의 순서
        불변식에 걸린다. 그 검사는 선점 **뒤**에 오므로 이 경우에만 [선점을 놓아 주는]
        경로가 실제로 돈다. 이 자리가 없으면 원복 코드는 한 번도 실행되지 않는다.
        """
        seed_draft(store_url, "d-first", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-late", "buttress_youth", age_max=34, max_amount=200_000_000)
        csrf = as_rule_manager(client)
        assert client.post(
            "/api/admin/drafts/d-first/approve", json={}, headers={CSRF_HEADER_NAME: csrf}
        ).status_code == 200

        before = snapshot(store_url)
        response = batch(client, csrf, ["d-late"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "rule_version_window_conflict"
        # 500 이 아니고, 초안은 다시 pending 이다.
        assert snapshot(store_url) == before
        with create_store(store_url) as store:
            assert store.rule_drafts.get("d-late").status == "pending"

    def test_the_message_names_the_policy_so_the_reviewer_can_act(self, client, store_url):
        seed_draft(store_url, "d-a", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-b", "buttress_youth", age_max=34, max_amount=200_000_000)
        csrf = as_rule_manager(client)
        message = batch(client, csrf, ["d-a", "d-b"]).json()["error"]["message"]
        assert "buttress_youth" in message

    def test_the_500_this_guard_replaces_is_reachable_without_it(self, client, store_url):
        """대조군 — 가드가 막는 것이 **실재하는 500** 임을 같은 하네스로 확인한다.

        가드를 통과하는 경로(단건 승인 두 번)로 같은 상태를 만들면 두 번째가 `StoreError`
        로 터진다. 이 단언이 깨지면 저장소가 그 사이에 고쳐졌다는 뜻이고, 그때는 이
        가드가 회피가 아니라 잉여가 된다 — 그 사실을 여기서 알아야 한다.
        """
        seed_draft(store_url, "d-a", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-b", "buttress_youth", age_max=34, max_amount=200_000_000)
        csrf = as_rule_manager(client)

        first = client.post(
            "/api/admin/drafts/d-a/approve", json={}, headers={CSRF_HEADER_NAME: csrf}
        )
        assert first.status_code == 200, first.text

        # 같은 정책의 두 번째 초안. 같은 시각이므로 `supersede` 의 순서 불변식에 걸린다.
        with pytest.raises(Exception) as excinfo:
            client.post(
                "/api/admin/drafts/d-b/approve", json={}, headers={CSRF_HEADER_NAME: csrf}
            )
        assert "effective_to" in str(excinfo.value) or "종료된" in str(excinfo.value)


# ==========================================================================
# 5. 승인 없이는 판정이 바뀌지 않는다 (SPEC 10.2 5단계 · 원칙 2)
# ==========================================================================

class TestTheBatchIsTheOnlyThingThatMovesTheVerdict:
    def _policy(self, client, policy_id: str) -> dict:
        response = client.post("/api/analyze", json=PROFILE)
        assert response.status_code == 200, response.text
        return next(p for p in response.json()["policies"] if p["id"] == policy_id)

    def test_a_pending_batch_changes_nothing_and_approving_it_does(self, client, store_url):
        seed_draft(store_url, "d-1", "buttress_youth", age_max=39, max_amount=250_000_000)
        seed_draft(store_url, "d-2", "seoul_deposit_interest", age_max=41, max_amount=210_000_000)

        before = copy.deepcopy(self._policy(client, "buttress_youth"))
        assert before["maxAmountKRW"] != 250_000_000

        csrf = as_rule_manager(client)
        assert batch(client, csrf, ["d-1", "d-2"]).status_code == 200

        after = self._policy(client, "buttress_youth")
        assert after["maxAmountKRW"] == 250_000_000


#: `/api/analyze` 로 판정을 한 번 물어보는 데 쓰는 프로필. 회귀 모집단
#: (`contracts/regression_profiles.json`)의 `baseline` 과 같은 값이며, 여기서는
#: [승인 전후로 값이 움직였는가] 하나만 보므로 세트 전체를 끌어오지 않는다.
PROFILE = {
    "age": 28,
    "annualIncomeKRW": 42_000_000,
    "monthlyNetIncomeKRW": 3_000_000,
    "liquidAssetsKRW": 40_000_000,
    "existingDebtMonthlyKRW": 300_000,
    "householdSize": 1,
    "regionCode": "11440",
    "isHomeless": True,
    "isNewlywed": False,
    "isSMEEmployee": True,
    "preferredType": "any",
}
