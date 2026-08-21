"""SPEC 7.2 관측 지표 · 7.3 대기 큐 — 상태 화면 (소유자: `api` · 10.2 7단계 기준 ③).

10.2 의 7단계 기준 셋 중 마지막은 「**상태 화면에 7.2 지표가 노출된다**」이고, 7.2 가
이름으로 요구한 것은 다섯이다 — 배치 성공률 · 데이터 신선도 · LLM 호출 성공률과 지연 ·
추출 스키마 실패율 · 승인 대기 건수.

이 파일이 재는 것은 [엔드포인트가 200 을 내는가] 가 아니라 **그 다섯이 무엇을 세었고
없을 때 무엇을 말하는가** 다. 이 화면의 지배적 실패 양상이 둘이기 때문이다.

## (가) 없는 값을 0 으로 채우는 것

「0% 실패율」과 「아직 한 번도 안 돌았다」는 다른 사실이다. 0 으로 그리면 화면이
[문제 없음]을 말하고, 그것은 관측 화면이 낼 수 있는 가장 나쁜 거짓말이다. 그래서 아래
검사들은 **비어 있는 저장소에서 먼저** 돌며 비율 자리가 전부 `null` 인지를 본다.

## (나) 정하지 않은 것을 정한 척하는 것

셋이 미정이고 셋 다 판정하지 않는다 —

  · **추출 성공률 합격선** — 두지 않는다 (사용자 결정 2026-08-14 · 계약 결정 #33)
  · **신선도 임계** — 미정 (SPEC 2.4 · 계약 결정 #39)
  · **대기 큐 SLA N** — 미정 (SPEC 7.3). `overdue` 는 **존재할 수 없는 판정**이다

특히 마지막이 중요하다. 「초과 0건」으로 그리면 그것은 거짓이고, 여기서는 `null` 과
[판정하지 않았다]는 문장이 함께 나가는지를 본다.

## (다) 승인 대기와 신고를 한 수로 뭉치는 것

초안은 승인·반려로 큐를 떠나지만 **신고는 떠나는 경로가 SPEC 의 어느 단계에도 없다.**
더하면 그 합은 밀린 일이 아니라 누적 카운터가 되고, 늘 커지기만 하는 수는 정보가 아니다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_compass import main as main_module
from home_compass.auth import CSRF_HEADER_NAME, ensure_seed_accounts
from home_compass.main import app
from home_compass.store import PolicySource, RuleDraft, create_store
from home_compass.store.models import REGION_FACT_FIELDS, AnomalyReport, AuditEvent
from home_compass.store.seed import seed_all

REPO_ROOT = Path(__file__).resolve().parents[3]
ADMIN_DIR = REPO_ROOT / "admin"

T0 = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
STATUS = "/api/admin/status"

COUNSELOR_PW = os.environ["HOME_COMPASS_SEED_COUNSELOR_PASSWORD"]
RULE_MANAGER_PW = os.environ["HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD"]


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'status.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
        store.policy_sources.add(
            PolicySource(id="src-status", text="제1조 신청 연령은 만 19세 이상.",
                         source_ref=None, fetched_at=T0)
        )
    monkeypatch.setenv("HOME_COMPASS_STORE_URL", url)
    return url


@pytest.fixture
def log_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "observability.jsonl"
    monkeypatch.setenv("HOME_COMPASS_LOG_FILE", str(path))
    return path


@pytest.fixture
def client(store_url, log_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(main_module, "request_now", lambda: T0)
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def as_rule_manager(client: TestClient) -> str:
    response = client.post("/api/auth/login",
                           json={"username": "rulemanager", "password": RULE_MANAGER_PW})
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def status_of(client: TestClient) -> dict:
    response = client.get(STATUS)
    assert response.status_code == 200, response.text
    return response.json()


def add_run(store_url: str, index: int, outcome: str) -> None:
    with create_store(store_url) as store:
        store.audit.append(AuditEvent(
            id=f"audit-run-{index:03d}", actor="system:ingest", at=T0,
            action=main_module.MARKET_RUN_ACTION, target=f"market-run-{index:06d}",
            outcome=outcome,
            after={"runId": f"market-run-{index:06d}", "committed": outcome == "success"},
        ))


def add_extraction(store_url: str, index: int, outcome: str, *,
                   codes: list[str] | None = None, latency_s: float | None = None) -> None:
    after: dict = {"policy_id": f"p-{index}", "policy_source_id": "src-status"}
    if codes is not None:
        after["codes"] = codes
    if latency_s is not None:
        after["latency_s"] = latency_s
    with create_store(store_url) as store:
        store.audit.append(AuditEvent(
            id=f"audit-extract-{index:03d}", actor="system:extract", at=T0,
            action=main_module.EXTRACTION_ACTION, target=f"draft-{index:03d}",
            outcome=outcome, after=after,
        ))


def add_draft(store_url: str, draft_id: str, *, created_at: datetime,
              status: str = "pending") -> None:
    with create_store(store_url) as store:
        store.rule_drafts.add(RuleDraft(
            id=draft_id, policy_source_id="src-status", policy_id=f"policy-{draft_id}",
            status=status, payload={"policy_id": f"policy-{draft_id}", "criteria": {}},
            created_at=created_at,
        ))


def add_report(store_url: str, report_id: str, *, at: datetime) -> None:
    with create_store(store_url) as store:
        store.reports.add(AnomalyReport(
            id=report_id, reporter="counselor", at=at, target_kind="policy",
            target_id="buttress_youth", target_field="status",
            reason="현장에서 다르게 안내되고 있다", status="open",
        ))


# ==========================================================================
# 1. 권한 (SPEC 6.1) — 지표도 대기 큐와 같은 게이트 뒤에 있다
# ==========================================================================

class TestWhoMaySeeTheMetrics:
    def test_anonymous_is_refused(self, client):
        assert client.get(STATUS).status_code == 401

    def test_a_counselor_is_refused(self, client):
        client.post("/api/auth/login",
                    json={"username": "counselor", "password": COUNSELOR_PW})
        assert client.get(STATUS).status_code == 403

    def test_the_rule_manager_gets_it(self, client):
        as_rule_manager(client)
        assert client.get(STATUS).status_code == 200


# ==========================================================================
# 2. ★ 없는 값을 0 으로 채우지 않는다
# ==========================================================================

class TestNothingObservedIsNotZero:
    def test_every_rate_is_null_on_a_fresh_store(self, client):
        """★ 이것이 이 파일의 첫 번째 이유다. 아무것도 안 돈 저장소에서 비율은 값이 없다."""
        as_rule_manager(client)
        status = status_of(client)

        assert status["batch"]["successRatePct"] is None
        assert status["extraction"]["failureRatePct"] is None
        assert status["llm"]["chat"]["successRatePct"] is None
        assert status["llm"]["extraction"]["successRatePct"] is None
        # ★ `oldestAgeDays` 는 여기서 빠졌다. 계약 결정 #40 이 시드를 실수집으로 굳히면서
        #   **시드가 실제 `fetched_at` 을 갖게 됐고**, 그 순간 이 값은 「아직 관측되지 않은
        #   비율」이 아니라 **관측된 사실**이 된다. 이 절이 지키는 것은 「없는 값을 0 으로
        #   채우지 않는다」이지 「무조건 null 이어야 한다」가 아니다.
        #   신선도가 무엇을 보이는지는 TestFreshnessIsObservedButNotJudged 가 진다.
        assert status["queue"]["longestWaitDays"] is None
        assert status["reports"]["longestOpenDays"] is None

    def test_latency_is_null_rather_than_zero_when_nothing_was_measured(self, client):
        as_rule_manager(client)
        latency = status_of(client)["llm"]["extraction"]["latency"]
        assert latency == {"samples": 0, "p50": None, "max": None, "unit": "s"}

    def test_counts_are_zero_because_zero_is_an_observation(self, client):
        """0 이 **관측된 사실**인 자리까지 `null` 로 만들지 않는다 — 그러면 반대 방향의 거짓말이다."""
        as_rule_manager(client)
        status = status_of(client)
        assert status["batch"]["runs"] == 0
        assert status["queue"]["pending"] == 0
        assert status["reports"]["open"] == 0

    def test_a_zero_percent_failure_rate_is_distinguishable_from_no_data(
            self, client, store_url):
        """실패가 0 건인 것과 추출이 한 번도 안 돈 것은 화면에서 갈려야 한다."""
        as_rule_manager(client)
        assert status_of(client)["extraction"]["failureRatePct"] is None

        add_extraction(store_url, 1, "pending")
        after = status_of(client)["extraction"]
        assert after["drafts"] == 1
        assert after["failureRatePct"] == 0.0     # 0% 는 **관측된** 실패율이다


# ==========================================================================
# 3. 배치 성공률 (7.2) — 분모가 무엇인지 화면 옆에 적는다
# ==========================================================================

class TestTheBatchSuccessRate:
    def test_it_counts_run_records(self, client, store_url):
        for index, outcome in enumerate(("success", "failed", "success"), start=1):
            add_run(store_url, index, outcome)
        as_rule_manager(client)
        batch = status_of(client)["batch"]
        assert (batch["runs"], batch["succeeded"], batch["failed"]) == (3, 2, 1)
        assert batch["successRatePct"] == 66.7
        assert batch["lastOutcome"] == "success"

    def test_the_denominator_is_stated(self, client):
        """★ 「성공/전체」는 전체가 무엇인지 말하지 않으면 숫자가 뜻을 갖지 않는다."""
        as_rule_manager(client)
        denominator = status_of(client)["batch"]["denominator"]
        assert "market.run" in denominator
        assert "1회" in denominator or "1 회" in denominator

    def test_per_region_rows_are_not_counted_as_runs(self, client, store_url):
        """지역별 행을 세면 한 실행이 10회로 잡힌다."""
        with create_store(store_url) as store:
            for i in range(10):
                store.audit.append(AuditEvent(
                    id=f"audit-ingest-{i}", actor="system:ingest", at=T0,
                    action="market.ingest", target=f"1144{i}", outcome="updated",
                ))
        as_rule_manager(client)
        assert status_of(client)["batch"]["runs"] == 0


# ==========================================================================
# 4. 신선도 (7.2) — **판정하지 않는다** (계약 결정 #39)
# ==========================================================================

class TestFreshnessIsObservedButNotJudged:
    def test_the_seeded_collection_time_actually_reaches_the_screen(self, client, store_url):
        """★ 이 화면이 **처음으로 실제 취득 시각을 보인다** (계약 결정 #40).

        굳히기 전에는 시드에 `fetched_at` 이 하나도 없어 `oldestFetchedAt` 이 `null` 이었고,
        그래서 이 지표는 「구조만 있고 값이 없는」 자리였다. 실수집을 굳히면서 값이 생겼다.

        **시연일과 벌어지는 것이 정상이다** — 결정 #40 이 그것을 숨기지 않기로 못박았고,
        이 화면이 그 격차가 드러나는 자리다. 그래서 나이를 **판정하지 않고 보이기만** 한다.
        """
        as_rule_manager(client)
        with create_store(store_url) as store:
            stamps = sorted(
                p for region in store.regions.list()
                for p in (region.provenance_for(n).fetched_at for n in REGION_FACT_FIELDS)
                if p
            )

        freshness = status_of(client)["freshness"]
        assert stamps, "굳힌 시드에 취득 시각이 하나도 없다 — 굳히기가 되돌아갔다"
        assert freshness["oldestFetchedAt"] == stamps[0]
        assert freshness["newestFetchedAt"] == stamps[-1]
        assert freshness["oldestAgeDays"] is not None
        # 나이를 **보이되 판정하지 않는다** — 임계가 미정이기 때문이다 (결정 #39).
        assert freshness["thresholdEvaluated"] is False

    def test_the_screen_says_it_did_not_evaluate_the_threshold(self, client):
        as_rule_manager(client)
        freshness = status_of(client)["freshness"]
        assert freshness["thresholdEvaluated"] is False
        assert "미정" in freshness["note"]
        assert "#39" in freshness["note"]

    def test_it_reports_the_verification_mix_the_lineage_already_states(self, client, store_url):
        """계보가 이미 말하고 있는 검증 분포를 그대로 센다.

        ★ **한 번 뒤집힌 단정이다.** 예전에는 `{"unverified": 80}` 이었고 그때는
        시드 8필드가 전부 예시값이라 사실이었다. 계약 결정 #40 이 시드를 실수집으로
        굳히면서 계보가 필드별로 갈렸다 (SPEC 3.1).

        ★ **수를 리터럴로 다시 박지 않는다.** 또 굳히면 또 깨진다. 저장소에서 세어
        비교한다 — 이 화면이 재는 것은 「특정한 수」가 아니라 **「계보가 말하는 것과
        화면이 말하는 것이 같다」**이기 때문이다.
        """
        as_rule_manager(client)
        with create_store(store_url) as store:
            expected: dict[str, int] = {}
            for region in store.regions.list():
                for name in REGION_FACT_FIELDS:
                    key = region.provenance_for(name).verification
                    expected[key] = expected.get(key, 0) + 1

        assert status_of(client)["freshness"]["verification"] == dict(sorted(expected.items()))
        # 그 분포가 **갈려 있다**는 것 자체가 결정 #40 의 산출물이다. 한 종류로 뭉치면
        # 굳히기가 되돌아갔거나 계보가 한 덩어리로 눌린 것이다.
        assert len(expected) >= 2, f"계보가 한 종류뿐이다: {expected}"

    def test_a_collected_value_shows_its_age_without_a_verdict(self, client, store_url):
        from dataclasses import replace

        with create_store(store_url) as store:
            region = store.regions.list()[0]
            provenance = replace(region.provenance,
                                 fetched_at=(T0 - timedelta(days=9)).isoformat())
            store.regions.upsert(replace(region, provenance=provenance,
                                         field_provenance={}))
        as_rule_manager(client)
        freshness = status_of(client)["freshness"]
        assert freshness["oldestAgeDays"] == 9.0
        # 나이는 나왔지만 **판정은 여전히 없다.**
        assert freshness["thresholdEvaluated"] is False


# ==========================================================================
# 5. 추출 스키마 실패율 (7.2) — **합격선이 없다** (계약 결정 #33)
# ==========================================================================

class TestTheExtractionFailureRateHasNoPassLine:
    def test_there_is_no_pass_line_and_the_screen_says_why(self, client):
        as_rule_manager(client)
        extraction = status_of(client)["extraction"]
        assert extraction["passLine"] is None
        assert "합격선" in extraction["note"]
        assert "#33" in extraction["note"]

    def test_the_failure_codes_are_broken_out_rather_than_folded(self, client, store_url):
        """사유를 하나로 접으면 [무엇을 고쳐야 하는가] 가 사라진다 (SPEC 4.2.2 와 같은 규율)."""
        add_extraction(store_url, 1, "pending")
        add_extraction(store_url, 2, "extraction_failed", codes=["schema_invalid"])
        add_extraction(store_url, 3, "extraction_failed",
                       codes=["schema_invalid", "span_not_found"])
        as_rule_manager(client)
        extraction = status_of(client)["extraction"]
        assert extraction["drafts"] == 3
        assert extraction["failed"] == 2
        assert extraction["failureRatePct"] == 66.7
        assert extraction["codes"] == {"schema_invalid": 2, "span_not_found": 1}


# ==========================================================================
# 6. LLM 호출 성공률과 지연 (7.2) — 출처가 둘이고 각자 자기 출처를 적는다
# ==========================================================================

class TestTheLlmMetrics:
    def test_the_extraction_channel_reads_the_audit_log(self, client, store_url):
        add_extraction(store_url, 1, "pending", latency_s=1.5)
        add_extraction(store_url, 2, "pending", latency_s=0.5)
        add_extraction(store_url, 3, "extraction_failed",
                       codes=["schema_invalid"], latency_s=2.5)
        as_rule_manager(client)
        channel = status_of(client)["llm"]["extraction"]
        assert (channel["calls"], channel["succeeded"], channel["failed"]) == (3, 2, 1)
        assert channel["successRatePct"] == 66.7
        assert channel["latency"] == {"samples": 3, "p50": 1.5, "max": 2.5, "unit": "s"}
        assert "AuditEvent" in channel["source"]

    def test_a_record_without_latency_is_counted_as_a_call_but_not_as_a_sample(
            self, client, store_url):
        """★ 7단계 이전 기록에는 `latency_s` 가 없다. 호출 수로 나눠 그리면 그 기록이
        [0초였다] 로 읽힌다 — 그래서 표본 수를 따로 싣는다."""
        add_extraction(store_url, 1, "pending")                    # 지연 없음 (옛 기록)
        add_extraction(store_url, 2, "pending", latency_s=2.0)
        as_rule_manager(client)
        channel = status_of(client)["llm"]["extraction"]
        assert channel["calls"] == 2
        assert channel["latency"]["samples"] == 1
        assert channel["latency"]["max"] == 2.0

    def test_the_chat_channel_reads_the_file_log(self, client, log_path):
        """`/api/chat` 은 익명 경로라 감사 원장에 실을 수 없다. 출처가 파일 로그다."""
        as_rule_manager(client)
        assert client.post("/api/chat", json={"message": "전세와 월세 중 뭐가 나을까요"}
                           ).status_code == 200
        channel = status_of(client)["llm"]["chat"]
        assert channel["calls"] == 1
        assert channel["succeeded"] == 1
        assert channel["successRatePct"] == 100.0
        assert channel["latency"]["samples"] == 1
        assert channel["latency"]["unit"] == "ms"
        assert "파일 로그" in channel["source"]

    def test_a_chat_call_leaves_no_audit_event(self, client, store_url):
        """★ 익명 트래픽이 append-only 원장을 무한히 불리지 않는다 — 지우는 경로가 없다."""
        with create_store(store_url) as store:
            before = len(store.audit.list())
        client.post("/api/chat", json={"message": "안녕하세요"})
        with create_store(store_url) as store:
            assert len(store.audit.list()) == before


# ==========================================================================
# 7. ★ 대기 큐 (7.3) — `overdue` 를 판정하지 않는다
# ==========================================================================

class TestTheQueueDoesNotJudgeOverdue:
    def test_overdue_is_null_and_the_screen_says_it_did_not_judge(self, client):
        """★ 「초과 0건」으로 그리면 그것은 거짓이다. N 이 없으면 그 판정은 존재할 수 없다."""
        as_rule_manager(client)
        queue = status_of(client)["queue"]
        assert queue["overdue"] is None
        assert "판정하지 않" in queue["overdueNote"]
        assert "7.3" in queue["overdueNote"]

    def test_the_pending_count_and_the_longest_wait_are_observed_facts(
            self, client, store_url):
        add_draft(store_url, "draft-old", created_at=T0 - timedelta(days=12))
        add_draft(store_url, "draft-new", created_at=T0 - timedelta(days=2))
        add_draft(store_url, "draft-done", created_at=T0 - timedelta(days=40),
                  status="approved")
        as_rule_manager(client)
        queue = status_of(client)["queue"]
        assert queue["pending"] == 2                 # 결정된 초안은 큐를 떠났다
        assert queue["longestWaitDays"] == 12.0

    def test_no_threshold_constant_was_invented_for_the_queue(self):
        """★ SLA N 을 만들지 않았다. 만들었다면 그것은 `ModelConstant` 에 등재됐을 것이다."""
        registry = json.loads(
            (REPO_ROOT / "contracts" / "model_constants.json").read_text(encoding="utf-8")
        )
        keys = [entry["key"] for entry in registry["entries"]]
        offenders = [k for k in keys
                     if re.search(r"sla|overdue|freshness|stale|pass_line|threshold_days", k)]
        assert not offenders, f"미정이어야 할 임계가 상수로 등재됐다: {offenders}"


# ==========================================================================
# 8. ★★ 승인 대기와 신고를 한 수로 뭉치지 않는다
# ==========================================================================

class TestTheQueueAndTheReportsAreCountedSeparately:
    def test_they_are_two_numbers_in_the_payload(self, client, store_url):
        add_draft(store_url, "draft-a", created_at=T0 - timedelta(days=3))
        add_report(store_url, "report-a", at=T0 - timedelta(days=20))
        add_report(store_url, "report-b", at=T0 - timedelta(days=5))
        as_rule_manager(client)
        status = status_of(client)
        assert status["queue"]["pending"] == 1
        assert status["reports"]["open"] == 2
        # 합계 3 은 어디에도 없다.
        assert "total" not in status["queue"]

    def test_the_report_count_says_it_accumulates(self, client):
        """★ 신고를 닫는 경로가 SPEC 의 어느 단계에도 없다. 그러면 이 수는 누적이다."""
        as_rule_manager(client)
        note = status_of(client)["reports"]["note"]
        assert "누적" in note
        assert "승인 대기" in note

    def test_deciding_a_draft_shrinks_the_queue_but_not_the_reports(
            self, client, store_url):
        """★ 둘의 **동역학이 다르다**는 것을 실제로 보인다. 이것이 더하면 안 되는 이유다."""
        add_draft(store_url, "draft-a", created_at=T0 - timedelta(days=3))
        add_report(store_url, "report-a", at=T0 - timedelta(days=3))
        csrf = as_rule_manager(client)

        before = status_of(client)
        assert (before["queue"]["pending"], before["reports"]["open"]) == (1, 1)

        assert client.post("/api/admin/drafts/draft-a/reject",
                           json={"reason": "원문과 다르다"},
                           headers={CSRF_HEADER_NAME: csrf}).status_code == 200

        after = status_of(client)
        assert after["queue"]["pending"] == 0
        assert after["reports"]["open"] == 1, "신고가 큐를 떠나는 경로는 없다"


# ==========================================================================
# 9. 파일 로그의 상태 — 지표를 믿을 수 있는가
# ==========================================================================

class TestTheLogAccountingIsHonest:
    def test_a_broken_line_is_counted_not_skipped(self, client, log_path):
        """조용히 건너뛰면 분모가 이유 없이 줄고, 성공률이 실제보다 좋아 보인다."""
        as_rule_manager(client)
        client.post("/api/chat", json={"message": "안녕하세요"})
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("이건 JSON 이 아니다\n")

        log = status_of(client)["log"]
        assert log["unreadableLines"] == 1
        assert log["exists"] is True

    def test_the_path_is_shown_so_the_number_can_be_checked(self, client, log_path):
        as_rule_manager(client)
        assert status_of(client)["log"]["path"] == str(log_path)


# ==========================================================================
# 10. 화면 — 파수병
# ==========================================================================
#
# 서버가 `null` 을 내려보내도 화면이 그것을 0 으로 바꾸면 이 단계의 산출물이 무너진다.
# 그래서 화면 소스에 대고 직접 건다.

ADMIN_JS = (ADMIN_DIR / "app.js").read_text(encoding="utf-8")
ADMIN_HTML = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")


def status_block() -> str:
    """`app.js` 에서 **상태 화면이 사는 구간**만 떼어 낸다.

    파일 전체에 거는 검사는 5단계·6-A 가 쓴 문장까지 잡는다 — 「근거 없음이 정상입니다」의
    '정상' 이 판정 배지로 오인되는 식이다. 그러면 파수병이 자기 과녁 밖을 쏘게 되고,
    고치는 방법이 [남의 문구를 바꾸는 것]이 되어 규칙이 무엇을 지키는지가 흐려진다.
    범위를 좁힌 것은 `test_admin_screen.py` 가 `slice` 에 대해 한 것과 같은 이유다.
    """
    opened = ADMIN_JS.index("// 상태 화면 — SPEC 7.2")
    closed = ADMIN_JS.index("function toggleSelected", opened)
    return ADMIN_JS[opened:closed]


STATUS_JS = status_block()


class TestTheScreenNeverFabricatesAMissingNumber:
    def test_the_screen_reads_the_status_endpoint(self):
        assert "/api/admin/status" in ADMIN_JS
        assert 'id="metricGrid"' in ADMIN_HTML
        assert 'id="statusPanel"' in ADMIN_HTML

    def test_the_guard_actually_has_something_to_look_at(self):
        """★ 구간을 좁힌 검사는 **구간이 비면 조용히 통과한다.** 먼저 그것을 막는다."""
        assert len(STATUS_JS) > 2000, f"상태 화면 구간이 너무 짧다: {len(STATUS_JS)}자"
        assert "renderStatus" in STATUS_JS and "metricCard" in STATUS_JS

    def test_a_missing_value_is_rendered_as_words_not_as_zero(self):
        block = re.search(r"function metricCard\(spec\)\s*\{.*?\n  \}", STATUS_JS, re.S)
        assert block is not None, "metricCard 가 없다"
        source = block.group(0)
        assert "is-none" in source, "관측 없음이 값과 같은 모양으로 그려진다"
        assert "spec.missing" in source

    def test_the_screen_does_not_coerce_null_to_zero(self):
        """`|| 0` 한 글자면 이 단계의 규율이 통째로 무너진다."""
        offenders = re.findall(r"\|\|\s*0\b", STATUS_JS)
        assert not offenders, f"화면이 없는 값을 0 으로 바꾼다: {offenders}"

    @pytest.mark.parametrize("token", ["초과 0", "초과 건수", "overdueCount", "isOverdue"])
    def test_the_screen_draws_no_overdue_verdict(self, token):
        """★ N 이 없으면 그 판정은 존재할 수 없다 — 화면에 그 자리를 만들지 않는다.

        `overdueNote` 는 예외다. 그것은 판정이 아니라 **판정하지 않았다는 문장**이다.
        """
        assert token not in STATUS_JS, f"화면이 존재할 수 없는 판정을 그린다: {token}"

    def test_the_screen_says_it_did_not_judge(self):
        assert "overdueNote" in STATUS_JS, "판정하지 않았다는 사실이 화면에 안 실린다"
        assert "판정하지 않습니다" in STATUS_JS

    def test_the_badge_never_adds_the_two_queues_together(self):
        """★ 6-A 워커가 짚은 것 — 더하면 그 수는 밀린 일이 아니라 누적 카운터가 된다."""
        block = re.search(r"function renderQueueBadge\(status\)\s*\{.*?\n  \}",
                          STATUS_JS, re.S)
        assert block is not None, "renderQueueBadge 가 없다"
        source = block.group(0)
        assert "status.queue.pending" in source
        assert "status.reports.open" in source
        assert not re.search(r"pending\s*\+\s*(status\.)?reports", source), "둘을 더한다"
        assert "누적" in source

    @pytest.mark.parametrize("token", [
        "합격입니다", "불합격", "양호", "위험 수준", "정상 범위", "기준 초과", "기준 미달",
    ])
    def test_the_screen_does_not_draw_a_pass_fail_verdict(self, token):
        """임계가 없는 지표에 통과/불통과 문구를 붙이면 없는 판정선이 있는 것처럼 읽힌다.

        ★ 목록에 「합격」 단독이 **없는 이유.** 화면은 「추출 합격선(계약 결정 #33) …이
          미정이므로 통과/불통과를 말할 근거가 없습니다」라고 **적어야** 한다. 그 문장은
          판정이 아니라 판정의 부재를 알리는 것이고, 단어 하나로 막으면 고치는 방법이
          [그 설명을 지우는 것]이 된다. 막으려는 것은 판정이지 판정에 대한 설명이 아니다.
          부재를 실제로 적었는지는 바로 아래 검사가 **양성으로** 확인한다.
        """
        assert token not in STATUS_JS, f"화면이 판정을 그린다: {token}"

    def test_the_screen_names_the_three_undecided_thresholds(self):
        """★ 위 금지가 [아무 말도 안 하는 화면] 으로 통과되지 않게 한다.

        셋을 이름으로 적어야 검토자가 **왜** 판정이 없는지 알 수 있다. 적지 않으면
        화면은 그냥 숫자만 늘어놓은 것이 되고, 그 상태는 판정을 그린 것과 마찬가지로
        [정하지 않은 것을 정한 척] 하는 쪽으로 읽힐 여지를 남긴다.
        """
        for reference in ("#33", "#39", "7.3"):
            assert reference in STATUS_JS, f"미정 근거가 화면에 없다: {reference}"

    def test_the_stylesheet_reserves_colour_for_a_broken_log_not_for_a_verdict(self):
        """색이 판정으로 읽히는 것을 막는다 — 붉은 카드는 [지표가 나쁘다] 가 아니라
        [기록이 새고 있어 이 화면을 믿을 수 없다] 하나뿐이다."""
        css = (ADMIN_DIR / "styles.css").read_text(encoding="utf-8")
        assert ".metric.is-leaking" in css
        assert not re.search(r"\.metric\.(is-good|is-bad|is-pass|is-fail)\b", css)
