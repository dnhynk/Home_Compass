"""SPEC 8.1 — `/api/health` 의 배치 상태 · 데이터 신선도 (소유자: `api`).

8.1 은 「`/api/health` 에 **배치 상태 · 데이터 신선도 추가**」를 이름으로 지시했는데
Part 10 의 어느 단계 완료 기준에도 그 항목이 없었다. 7단계는 같은 지표를
`rule_manager` 전용 `/api/admin/status` 로만 냈고, 8.1 이 정한 자리는 비어 있었다.

이 파일이 재는 것은 넷이다.

## (가) 값이 실제로 흘러오는가

두 블록이 계약을 만족하면서 **영원히 `null`** 인 상태가 이 변경의 조용한 실패 지점이다.
계약 검증만으로는 초록불이 되므로 값을 심고 되찾는다.

## (나) 없는 값을 0 이나 [없음] 으로 뭉개지 않는가

**`null` 이 두 층에 있고 뜻이 다르다.** 블록 자체가 `null` 이면 [저장소를 읽지 못했다]
이고, 블록 **안**의 `null` 은 [읽었으나 아직 없다] 다. 두 사실을 한 값으로 뭉치면
화면은 깨진 저장소를 [배치가 아직 안 돌았다]로 그린다.

## (다) 익명에 여는 것이 최소인가

`/api/health` 는 익명 경로다. 코디네이터 경계는 배치에서 **마지막 실행의 성공/실패와
그 시각**만, 신선도에서 **요약 하나**만 허용했다. 「최소로 한다」는 판단이지 자명한
것이 아니므로 **뺀 것을 검사로 적어 둔다** — 적지 않으면 다음 사람이 [있으면 편하니까]
로 하나씩 되돌려 놓는다.

## (라) 7.2 화면과 같은 사실을 말하는가

배치는 `build_batch_status`(7.2)를 투영한 것이다. 두 벌로 세면 두 화면이 다른 수를
말할 수 있고, 그때 어느 쪽이 맞는지는 아무도 모른다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_compass import main as main_module
from home_compass.auth import ensure_seed_accounts
from home_compass.main import app
from home_compass.store import create_store
from home_compass.store.errors import ProvenanceError
from home_compass.store.models import AuditEvent
from home_compass.store.seed import seed_all

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI = REPO_ROOT / "contracts" / "openapi.json"

T0 = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
HEALTH = "/api/health"
STATUS = "/api/admin/status"

RULE_MANAGER_PW = os.environ["HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD"]

#: 관측 기준시점은 **숫자 오프셋**이어야 한다 (`contracts/provenance.schema.json` — `Z` 금지).
#: `main._parse_at` 도 tz 없는 값을 버리므로, 오프셋 없는 문자열은 신선도에 오르지 못한다.
OLDER = "2026-07-02T00:00:00+09:00"
NEWER = "2026-08-09T00:00:00+09:00"


# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

@pytest.fixture
def store_path(tmp_path) -> Path:
    return tmp_path / "health.db"


@pytest.fixture
def store_url(store_path, monkeypatch) -> str:
    url = f"sqlite://{store_path}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
    monkeypatch.setenv("HOME_COMPASS_STORE_URL", url)
    return url


@pytest.fixture
def client(store_url, monkeypatch) -> TestClient:
    monkeypatch.setattr(main_module, "request_now", lambda: T0)
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


@pytest.fixture(autouse=True)
def no_provider_keys(monkeypatch):
    """`llm` 의 전제를 **개발자 머신에서 물려받지 않고 여기서 명시로 만든다.**

    ★ 이 파일은 `llm == "offline"` 을 두 곳에서 단정하면서 그 전제를 아무 데도 적지
      않았다. 저장소 루트에 `.env` 가 있으면 `config` 가 import 시점에 그것을
      `os.environ` 으로 올리고 `"openai"` 가 나온다 — **로컬에서만 빨간불이고 CI 는
      초록이다.** `tests/conftest.py` 가 개발자 로컬 DB 에 기대지 않는 이유로 적은 것과
      같은 부류이며(Part 0-A 「각자는 맞는데 합치면 틀린」), 방향만 반대다.

    ★★ **단정을 없애지 않는다.** `llm` 은 SPEC 7.2 의 지표이고, 없애면 이 파일이
      [순수 추가] 를 재던 자리 하나를 잃는다. 재는 것은 그대로 두고 전제만 옮긴다 —
      이 파일이 `clear_all_observed` 로 이미 한 번 한 일이다.

    빈 문자열인 이유는 `tests/crosscheck/test_boot_smoke.py` 의 `_server_env` 가 같은
    문제를 같은 방법으로 이미 풀었기 때문이다. `clean_env_value("")` 가 거짓이라
    `resolve_provider()` 는 offline 을 고르고, **키가 `os.environ` 에 있으므로**
    `load_env_file` 이 `.env` 값으로 덮지 못한다 (`override=False`). 지워 버리면
    그 두 번째 성질을 잃는다.
    """
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "")


def health_of(client: TestClient) -> dict:
    response = client.get(HEALTH)
    assert response.status_code == 200, response.text
    return response.json()


def add_run(store_url: str, run_id: str, outcome: str, *, at: datetime) -> None:
    with create_store(store_url) as store:
        store.audit.append(AuditEvent(
            id=f"audit-{run_id}", actor="system:ingest", at=at,
            action=main_module.MARKET_RUN_ACTION, target=run_id, outcome=outcome,
            # 실행 식별자와 실패 사유는 감사기록에 **남는다.** 익명 경로가 그것을 싣지
            # 않는다는 것이 8.1 경계이며, 아래 (다) 가 새어 나오지 않는지를 본다.
            after={"runId": run_id, "committed": outcome == "success",
                   "error": "connection refused to 시세 소스"},
        ))


def set_observed(store_url: str, index: int, observed_at: str | None) -> None:
    """지역 하나의 **요약 계보**에 관측 기준시점을 심는다.

    `field_provenance` 를 비우는 이유는 `Region.provenance_for` 가 필드별 항목이 없을 때
    요약을 그 필드의 계보로 쓰기 때문이다 — 여덟 필드가 같은 값을 가리키게 되어 기대값이
    하나로 정해진다.
    """
    with create_store(store_url) as store:
        region = store.regions.list()[index]
        provenance = replace(region.provenance, observed_at=observed_at)
        store.regions.upsert(replace(region, provenance=provenance, field_provenance={}))


def clear_all_observed(store_url: str) -> None:
    """전 지역을 **관측 없음** 으로 만든다.

    ★ 계약 결정 #40 (8단계) 전까지는 **시드가 곧 이 상태였다.** 시드가 실수집 결과로
      굳으면서 전 지역이 실제 `observed_at` 을 갖게 됐고, 「시드에는 관측이 없다」를
      전제로 삼던 아래 검사들이 과녁을 잃었다. 전제를 시드에서 물려받지 않고 **여기서
      명시로 만든다** — 시드가 또 바뀌어도 그 검사들이 재는 것은 그대로다.

    `verification` 을 함께 내리는 것이 이 함수의 유일한 기교다.
    `contracts/provenance.schema.json` 이 `observed_at` 을 `verified`/`stale` 에만
    필수로 걸기 때문이며, 그러므로 이것은 계보를 위조하는 것이 아니라 **[출처를 확인하지
    못했고 따라서 기준시점도 없다]** 는 실제로 성립하는 상태를 만드는 것이다.
    """
    with create_store(store_url) as store:
        for region in store.regions.list():
            provenance = replace(
                region.provenance, observed_at=None, verification="unverified")
            store.regions.upsert(
                replace(region, provenance=provenance, field_provenance={}))


# ==========================================================================
# 1. 순수 추가 (SPEC 8.1 「기존 필드명 변경 금지」)
# ==========================================================================

class TestItIsAPureAddition:
    def test_the_existing_two_fields_are_untouched(self, client):
        body = health_of(client)
        assert body["status"] == "ok"
        assert body["llm"] == "offline"

    def test_the_llm_field_still_follows_the_resolved_provider(self, client, monkeypatch):
        """★ 위의 `offline` 단정이 **[늘 offline]** 을 굳히지 않는다.

        전제를 명시로 고정하면 그 대가로 [상수로 하드코딩해도 통과한다] 는 구멍이
        생긴다. 늘 켜져 있는 표시·무조건 통과하는 검사는 이 저장소가 이름 붙인 실패
        양상이므로, 값이 실제로 따라 움직이는 것을 여기서 함께 잰다.

        키를 심는 것뿐이라 프로바이더를 부르지 않는다 — `get_llm_mode()` 는 키의
        존재와 SDK import 가능성만 본다. 두 SDK 는 `requirements.txt` 의 의존성이다.
        """
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-that-is-never-called")
        assert health_of(client)["llm"] == "openai"

    def test_status_still_means_the_process_is_alive_not_the_data_is_fine(
            self, client, store_url):
        """`status` 의 **뜻**도 바꾸지 않았다.

        배치가 실패해도 `status` 는 `ok` 다. 여기서 `ok` 를 흔들면 이름만 남기고 뜻을
        바꾼 것이며, 그것은 8.1 이 막으려던 사고와 같은 종류다 — 프론트는 이 값 하나로
        [백엔드 연결됨] 을 판정한다.
        """
        add_run(store_url, "run-failed", "failed", at=T0)
        body = health_of(client)
        assert body["status"] == "ok"
        assert body["batch"]["lastOutcome"] == "failed"

    def test_the_response_matches_the_committed_contract(self, client):
        """계약 파일과 맞는지는 **커밋본**으로 본다 (D-12 · SPEC 8.2 #1).

        재생성본과 비교하면 코드만 바꾼 변경이 스스로 통과한다.
        """
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        document = json.loads(OPENAPI.read_text(encoding="utf-8"))
        base = "http://contract/openapi.json"
        registry = Registry().with_resource(
            base, Resource.from_contents(document, default_specification=DRAFT202012))
        validator = Draft202012Validator(
            {"$ref": base + "#/components/schemas/HealthResponse"}, registry=registry)
        errors = list(validator.iter_errors(health_of(client)))
        assert not errors, [e.message for e in errors]

    def test_it_stays_anonymous(self, client):
        """익명 경로 그대로다. 8.1 이 정한 자리가 여기이므로 게이트를 새로 걸지 않는다."""
        assert client.get(HEALTH).status_code == 200
        assert client.get(STATUS).status_code == 401


# ==========================================================================
# 2. ★ 값이 실제로 흘러온다 — 배치 상태
# ==========================================================================

class TestTheBatchStateComesFromTheStore:
    def test_a_fresh_store_says_nothing_rather_than_zero(self, client):
        """블록은 **있고** 그 안이 `null` 이다. [읽었으나 아직 없다] 는 관측된 사실이다."""
        assert health_of(client)["batch"] == {"lastRunAt": None, "lastOutcome": None}

    def test_it_reports_the_last_run(self, client, store_url):
        add_run(store_url, "run-1", "success", at=T0 - timedelta(days=2))
        body = health_of(client)
        assert body["batch"]["lastOutcome"] == "success"
        assert body["batch"]["lastRunAt"] == (T0 - timedelta(days=2)).isoformat()

    def test_a_later_failure_replaces_an_earlier_success(self, client, store_url):
        """★ **마지막** 실행이다. 최근 실패를 옛 성공이 가리면 화면이 정반대를 말한다."""
        add_run(store_url, "run-1", "success", at=T0 - timedelta(days=2))
        add_run(store_url, "run-2", "failed", at=T0 - timedelta(hours=1))
        body = health_of(client)
        assert body["batch"]["lastOutcome"] == "failed"
        assert body["batch"]["lastRunAt"] == (T0 - timedelta(hours=1)).isoformat()

    def test_the_last_run_is_the_latest_one_not_the_last_one_written(self, client, store_url):
        """★ **위 검사는 삽입순과 시각순이 같아서 통과했다.** 여기서 갈라 놓는다.

        위 `test_a_later_failure_replaces_an_earlier_success` 는 뒤 시각을 뒤에 넣는다.
        그 배치에서는 [마지막에 넣은 것] 과 [시각이 가장 늦은 것] 이 같은 행이라 두
        규칙 중 어느 것으로 골라도 답이 같고, 그래서 그 검사는 **틀린 규칙도 통과시킨다.**

        갈리게 만드는 방법은 하나뿐이다 — `AuditEvent` 는 append-only 라 행을 고쳐
        만들 수 없고, **넣는 순서를 뒤집는** 것만 할 수 있다. 지어낸 상황이 아니다.
        시드가 실행 기록을 나중에 넣거나, 두 프로세스가 순서를 섞어 쓰거나, 배치가
        지난 시각으로 기록을 남기면 그대로 일어난다.

        그리고 이 칸이 어긋나면 **화면에 단서가 없다.** 익명 응답에는 `lastRunAt` 과
        `lastOutcome` 둘뿐이라 「마지막 배치는 성공」이라는 문장을 반증할 것이 없다.
        """
        add_run(store_url, "run-late", "success", at=T0 - timedelta(hours=1))
        add_run(store_url, "run-early", "failed", at=T0 - timedelta(days=2))

        body = health_of(client)
        assert body["batch"]["lastOutcome"] == "success"
        assert body["batch"]["lastRunAt"] == (T0 - timedelta(hours=1)).isoformat()

    def test_per_region_rows_are_not_mistaken_for_runs(self, client, store_url):
        """`market.ingest` 는 지역별 행이다. 실행 1회가 10회로 잡히면 시각도 틀린다."""
        with create_store(store_url) as store:
            for index in range(10):
                store.audit.append(AuditEvent(
                    id=f"audit-ingest-{index}", actor="system:ingest", at=T0,
                    action="market.ingest", target=f"1144{index}", outcome="updated",
                ))
        assert health_of(client)["batch"]["lastRunAt"] is None


# ==========================================================================
# 3. ★ 값이 실제로 흘러온다 — 데이터 신선도
# ==========================================================================

class TestTheFreshnessSummaryComesFromTheStore:
    def test_a_store_without_observations_says_nothing_rather_than_zero(
            self, client, store_url):
        """블록은 **있고** 그 안이 `null` 이다 — [읽었으나 아직 없다].

        ★ 이 검사는 예전에 시드를 그대로 썼다. 계약 결정 #40 이 시드를 실수집 결과로
          굳히면서 시드가 더 이상 [관측 없음] 이 아니게 됐다. 재는 것은 그대로 두고
          **전제만 명시로 옮겼다** (`clear_all_observed`).
        """
        clear_all_observed(store_url)
        assert health_of(client)["freshness"] == {"oldestObservedAt": None}

    def test_the_seeded_store_now_reports_a_real_observation(self, client, store_url):
        """★ 계약 결정 #40 의 결과가 이 칸에 **처음으로** 실제 값을 싣는다.

        8.1 을 지은 워커가 자기 ⑥ 에 「잰 저장소에 `observed_at` 있는 필드가 0이었다」고
        적었다. 시드가 실수집으로 굳으면서 그 0이 채워졌고, 이 경로가 계약을 만족하면서
        **영원히 `null`** 일 수 있다는 (가) 의 조용한 실패 지점이 실데이터로 닫힌다.

        기대값을 리터럴로 박지 않는다 — 저장소에서 **세어 유도한다.** 수집 시각은 다시
        수집하면 또 바뀌므로, 굳혀 두면 다음 수집 때 이 검사가 또 깨진다.
        """
        with create_store(store_url) as store:
            expected = min(
                p.observed_at
                for region in store.regions.list()
                for p in (region.provenance_for(n) for n in region.field_provenance)
                if p.observed_at is not None
            )
        observed = health_of(client)["freshness"]["oldestObservedAt"]
        assert observed is not None, "시드가 실수집으로 굳었는데 신선도가 비었다"
        assert observed == expected

    def test_it_reports_the_oldest_observation(self, client, store_url):
        set_observed(store_url, 0, NEWER)
        set_observed(store_url, 1, OLDER)
        assert health_of(client)["freshness"]["oldestObservedAt"] == OLDER

    def test_regions_without_an_observation_do_not_win(self, client, store_url):
        """`null` 은 [가장 오래됨] 이 아니다. 섞이면 신선도가 통째로 `null` 이 된다."""
        clear_all_observed(store_url)
        set_observed(store_url, 0, NEWER)
        assert health_of(client)["freshness"]["oldestObservedAt"] == NEWER

    def test_the_offset_guarantee_is_enforced_at_the_store_not_here(self, client, store_url):
        """SPEC 2.1 「UTC 로 뭉개지 않는다」 — 오프셋 없는 값은 **저장소가 거부한다.**

        ★ 처음에는 [오프셋 없는 값을 심고 `/api/health` 가 그것을 버리는지] 를 보려
          했는데, 값이 저장소를 통과하지 못했다 (`contracts/provenance.schema.json`).
          `main._parse_at` 의 tz 검사는 그 위에 겹친 이중 방어이고 이 경로로는 닿지
          않는다. 그러므로 여기서 확인할 것은 **경계가 저장소에 있다**는 사실과, 그
          결과로 이 응답의 시각이 언제나 오프셋을 달고 나간다는 것이다.
        """
        with pytest.raises(ProvenanceError):
            set_observed(store_url, 0, "2026-01-01T00:00:00")

        clear_all_observed(store_url)
        set_observed(store_url, 1, NEWER)
        observed = health_of(client)["freshness"]["oldestObservedAt"]
        assert observed == NEWER
        assert re.search(r"[+-][0-9]{2}:[0-9]{2}$", observed), observed

    def test_it_looks_at_field_level_lineage_not_only_the_summary(self, client, store_url):
        """★ 요약의 `observed_at` 은 필드들 중 가장 **늦은** 값이다.

        (`ingest.market.pipeline._commit`.) 요약만 보면 가장 오래된 사실이 가려지고,
        신선도 칸이 실제보다 새것으로 보인다 — 관측 화면이 낼 수 있는 가장 나쁜 방향이다.
        """
        with create_store(store_url) as store:
            region = store.regions.list()[0]
            summary = replace(region.provenance, observed_at=NEWER)
            fields = {name: replace(p, observed_at=OLDER)
                      for name, p in region.field_provenance.items()}
            assert fields, "지역에 필드별 계보가 없다 — 이 검사가 과녁을 잃었다"
            store.regions.upsert(
                replace(region, provenance=summary, field_provenance=fields))
        assert health_of(client)["freshness"]["oldestObservedAt"] == OLDER


# ==========================================================================
# 4. ★ 익명에 여는 것은 최소다 — **뺀 것을 적어 둔다**
# ==========================================================================

class TestTheAnonymousPayloadStaysMinimal:
    @pytest.fixture
    def loaded(self, client, store_url) -> dict:
        add_run(store_url, "run-1", "failed", at=T0)
        set_observed(store_url, 0, OLDER)
        return health_of(client)

    def test_the_top_level_has_exactly_four_keys(self, loaded):
        assert set(loaded) == {"status", "llm", "batch", "freshness"}

    def test_the_batch_block_is_the_last_run_and_nothing_else(self, loaded):
        """실행 식별자 · 오류 본문 · 대상 지역 목록은 싣지 않는다 (코디네이터 경계)."""
        assert set(loaded["batch"]) == {"lastRunAt", "lastOutcome"}

    def test_the_batch_aggregate_stays_behind_the_role_gate(self, loaded):
        """실행 횟수 · 성공률 · 분모 문장은 `/api/admin/status` 에 남는다 (SPEC 7.2)."""
        for omitted in ("runs", "succeeded", "failed", "successRatePct", "denominator"):
            assert omitted not in loaded["batch"]

    def test_the_freshness_block_is_one_summary_and_nothing_else(self, loaded):
        """필드별 계보와 `provenance` 전문은 `/api/analyze` 의 몫이다 (D-13)."""
        assert set(loaded["freshness"]) == {"oldestObservedAt"}

    def test_there_is_no_data_grade_here(self, loaded):
        """등급은 **판정에 쓰인 사실**에 걸린다. `/api/health` 에는 판정이 없다."""
        assert "dataGrade" not in json.dumps(loaded)

    def test_no_run_identifier_or_error_body_leaks(self, loaded):
        """감사기록에는 둘 다 있다. 익명 응답으로 새어 나오지 않는 것이 경계다."""
        serialized = json.dumps(loaded, ensure_ascii=False)
        assert "run-1" not in serialized
        assert "connection refused" not in serialized

    def test_no_region_code_or_name_leaks(self, loaded, store_url):
        with create_store(store_url) as store:
            region = store.regions.list()[0]
        serialized = json.dumps(loaded, ensure_ascii=False)
        assert region.code not in serialized
        assert region.name not in serialized


# ==========================================================================
# 5. ★ 7.2 화면과 같은 사실을 말한다 — 두 벌로 세지 않았다
# ==========================================================================

class TestItProjectsTheSameFactAsTheStatusScreen:
    def test_the_last_run_agrees_with_the_status_screen(self, client, store_url):
        add_run(store_url, "run-1", "success", at=T0 - timedelta(days=3))
        add_run(store_url, "run-2", "failed", at=T0 - timedelta(days=1))

        health = health_of(client)
        login = client.post("/api/auth/login",
                            json={"username": "rulemanager", "password": RULE_MANAGER_PW})
        assert login.status_code == 200, login.text
        status = client.get(STATUS)
        assert status.status_code == 200, status.text
        batch = status.json()["batch"]

        assert health["batch"]["lastRunAt"] == batch["lastRunAt"]
        assert health["batch"]["lastOutcome"] == batch["lastOutcome"]


# ==========================================================================
# 6. ★ 저장소를 읽지 못해도 200 이다 — 그러나 **말없이** 넘어가지 않는다
# ==========================================================================

class TestAnUnreadableStoreDoesNotKillTheProbe:
    """생존 신호는 저장소가 깨져도 답해야 한다.

    여기서 500 을 내면 8.1 의 [순수 추가] 가 **전에 없던 실패 경로를 만든 변경**이 된다 —
    계약이 이 오퍼레이션에 선언한 응답은 200 하나뿐이고, `frontend/app.js checkHealth`
    와 `admin/app.js connect` 는 이 경로 하나로 [백엔드 연결됨] 을 판정한다.
    """

    @pytest.fixture
    def wrecked(self, client, store_path) -> dict:
        # 제품 코드를 건드리지 않는다. 요청마다 `store_from_env()` 로 새로 여므로
        # 파일을 쓰레기로 덮으면 다음 요청이 실제로 터진다
        # (`tests/api/test_log_hygiene.py` 의 `_STORE_WRECKAGE` 와 같은 수법).
        store_path.write_bytes(b"NOT-A-SQLITE-DATABASE" * 64)
        return health_of(client)

    def test_it_still_answers_two_hundred(self, wrecked):
        assert wrecked["status"] == "ok"
        assert wrecked["llm"] == "offline"

    def test_the_blocks_are_null_so_the_response_says_it_could_not_tell(self, wrecked):
        """★ **삼킨 것이 아니다.** 못 읽었다는 사실이 응답에 드러난다 (SPEC 6.2)."""
        assert wrecked["batch"] is None
        assert wrecked["freshness"] is None

    def test_that_is_a_different_fact_from_nothing_recorded_yet(
            self, client, store_path, store_url):
        """★ 블록 `null` 과 블록 **안**의 `null` 을 한 값으로 뭉치지 않는다.

        뭉치면 화면은 깨진 저장소를 [배치가 아직 안 돌았다] 로 그린다 — 관측 화면이
        낼 수 있는 가장 나쁜 거짓말이 그 방향이다. 같은 서버에서 두 상태를 나란히 본다.

        ★ [아직 없다] 쪽 상태는 계약 결정 #40 이후 **명시로 만든다** — 시드가 실수집으로
          굳어 더 이상 빈 상태가 아니다 (위 `clear_all_observed` 주석).
        """
        clear_all_observed(store_url)
        empty = health_of(client)
        assert empty["batch"] == {"lastRunAt": None, "lastOutcome": None}
        assert empty["freshness"] == {"oldestObservedAt": None}

        store_path.write_bytes(b"NOT-A-SQLITE-DATABASE" * 64)
        broken = health_of(client)
        assert broken["batch"] is None and broken["freshness"] is None
        assert broken["batch"] != empty["batch"]
        assert broken["freshness"] != empty["freshness"]
