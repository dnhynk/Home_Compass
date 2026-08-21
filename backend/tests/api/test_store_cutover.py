"""컷오버 — 판정이 파일이 아니라 저장소를 본다 (SPEC 2.3 · 1.2, 소유자: `api`).

컷오버 전 `engines/__init__.py` 는 `load_regions` · `load_policies` 를
`lru_cache(maxsize=1)` 로 감싸 `backend/src/home_compass/data/*.json` 을 프로세스당 한 번만
읽었다. SPEC 2.3 이 그 상태를 이름까지 적어 금지한다:

    배치가 갱신해도, 규칙관리자가 승인해도 재기동 전까지 판정에 반영되지 않는다.
    핵심 시연 장면(승인 -> 시민 화면 변화)이 그 자리에서 무너진다.

그래서 2.3 은 요건도 함께 못 박았다 — **저장소를 갱신하고 재기동 없이 판정을 다시 호출해
결과가 바뀌는지 확인한다.** 이 파일이 그 테스트다.

`TestClient` 를 쓰는 것이 여기서는 약점이 아니라 요점이다. **앱을 다시 만들지 않는다** —
같은 프로세스, 같은 `app` 객체에 두 번 친다. 재기동을 끼워 넣는 순간 이 파일은 아무것도
증명하지 못한다. 기동 경로 자체의 검증은 실기동 스모크(`crosscheck/test_boot_smoke.py`)가 진다.

격리: 모든 케이스가 자기 `tmp_path` 저장소를 만들어 `HOME_COMPASS_STORE_URL` 을 그쪽으로
돌린다. `conftest.py` 의 세션 저장소는 읽기 전용이며 여기서 건드리지 않는다.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_compass.main import (
    REGIONS_EMPTY_MESSAGE,
    app,
    boot_require_regions,
    read_active_policies,
    require_regions,
)
from home_compass.store import STORE_URL_ENV, ApprovalRecord, RuleDraft, RuleVersion, User, create_store
from home_compass.store.seed import seed_all

T0 = datetime(2026, 8, 13, tzinfo=timezone.utc)

#: `conftest.py` 가 세션 시작에 시드해 둔 저장소. **import 시점에 붙든다** — 픽스처가
#: 환경변수를 갈아치운 뒤에는 원래 값을 알 수 없다.
SESSION_STORE_URL = os.environ[STORE_URL_ENV]

#: 판정을 지역 시세에 민감하게 만드는 프로필. 전세 시나리오가 실제로 서는 값이다.
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


@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    """이 테스트 전용 저장소를 시드하고 환경변수를 그쪽으로 돌린다."""
    url = f"sqlite://{tmp_path / 'cutover.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
    monkeypatch.setenv(STORE_URL_ENV, url)
    return url


@pytest.fixture
def client(store_url) -> TestClient:
    return TestClient(app)


def _analyze(client: TestClient, **over) -> dict:
    body = dict(PROFILE)
    body.update(over)
    response = client.post("/api/analyze", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _policy_ids(result: dict) -> list[str]:
    return sorted(policy["id"] for policy in result["policies"])


# ==========================================================================
# (a) 재기동 없이 반영된다 — SPEC 2.3 이 명시적으로 요구한 테스트
# ==========================================================================

def test_a_region_update_changes_the_verdict_without_a_restart(client, store_url):
    """배치가 시세를 갱신하면 다음 판정이 곧바로 달라진다.

    컷오버 전에는 이 테스트가 실패한다. 첫 호출이 파일을 `lru_cache` 에 담아 두므로 두 번째
    호출이 같은 숫자를 돌려주기 때문이다.
    """
    before = _analyze(client)
    before_deposits = [s["depositKRW"] for s in before["scenarios"]]

    with create_store(store_url) as store:
        region = store.regions.get("11440")
        store.regions.upsert(
            dataclasses.replace(region, jeonse_median_krw=region.jeonse_median_krw + 120_000_000)
        )

    after = _analyze(client)
    after_deposits = [s["depositKRW"] for s in after["scenarios"]]

    assert after_deposits != before_deposits, (
        "저장소를 갱신했는데 판정이 그대로다 — 재기동 없이 반영되지 않았다 (SPEC 2.3)"
    )


def test_the_regions_endpoint_follows_the_store_without_a_restart(client, store_url):
    """시민 화면의 지역 목록도 같은 규율을 진다."""
    before = client.get("/api/regions").json()["regions"]
    assert before, "시드된 저장소인데 지역이 비었다"

    with create_store(store_url) as store:
        region = store.regions.get("11440")
        store.regions.upsert(dataclasses.replace(region, monthly_rent_krw=region.monthly_rent_krw + 250_000))

    after = client.get("/api/regions").json()["regions"]
    changed = next(r for r in after if r["code"] == "11440")
    was = next(r for r in before if r["code"] == "11440")
    assert changed["monthlyRentKRW"] == was["monthlyRentKRW"] + 250_000


def test_an_approved_rule_version_reaches_the_verdict_without_a_restart(client, store_url):
    """핵심 시연 장면 그 자체 — 규칙관리자가 승인하면 시민 화면이 그 자리에서 바뀐다."""
    before = _policy_ids(_analyze(client))
    assert "demo_new_grant" not in before

    with create_store(store_url) as store:
        store.users.add(
            User(
                id="u-rule-manager",
                username="rule_admin_demo",
                role="rule_manager",
                password_hash="$argon2id$placeholder",
                created_at=T0,
            )
        )
        store.approvals.add(
            ApprovalRecord(
                id="ap-demo",
                actor_user_id="u-rule-manager",
                at=T0,
                target_kind="rule_version",
                target_id="rv-demo",
                decision="approved",
                reason="시연 장면 재현",
            )
        )
        store.rule_versions.add(
            RuleVersion(
                id="rv-demo",
                policy_id="demo_new_grant",
                payload=_policy_payload("demo_new_grant", "시연용 신규 지원"),
                status="approved",
                origin="human_approval",
                effective_from=None,
                effective_to=None,
                supersedes=None,
                approved_by="u-rule-manager",
                provenance=_seed_like_provenance(store_url),
                created_at=T0,
            )
        )

    after = _policy_ids(_analyze(client))
    assert "demo_new_grant" in after, (
        "승인된 규칙이 재기동 없이 판정에 들어오지 않았다 — 시연 장면이 무너진다 (SPEC 2.3)"
    )
    assert set(after) - set(before) == {"demo_new_grant"}


# ==========================================================================
# (b) RuleDraft 는 판정에 새어들지 않는다 — SPEC 2.3 · 5.3 불변식
# ==========================================================================

def test_a_rule_draft_never_reaches_a_verdict(client, store_url):
    """초안은 어떤 경로로도 판정에 참여하지 않는다.

    `RuleDraft.status` 가 `approved` 여도 마찬가지다 — draft 의 승인은 별도의
    `RuleVersion` 을 낳는 사건이지 그 자체가 판정 참여가 아니다 (store 인터페이스 주석).
    """
    baseline = _policy_ids(_analyze(client))

    with create_store(store_url) as store:
        store.policy_sources.add(_policy_source())
        for draft_id, status in (("draft-pending", "pending"), ("draft-approved", "pending")):
            store.rule_drafts.add(
                RuleDraft(
                    id=draft_id,
                    policy_source_id="src-leak-probe",
                    policy_id=f"{draft_id}_policy",
                    status=status,
                    payload=_policy_payload(f"{draft_id}_policy", "초안 제도"),
                    created_at=T0,
                )
            )
        store.rule_drafts.set_status("draft-approved", "approved")

    after = _policy_ids(_analyze(client))
    assert after == baseline, f"초안이 판정에 샜다: {sorted(set(after) - set(baseline))}"


def test_the_verdict_carries_exactly_the_active_rule_versions(client, store_url):
    """판정에 실린 정책 집합 == `rule_versions.active(now)` 의 payload 집합.

    등식으로 걸어 둔다. 부등식(초안이 없다)만 걸면 `list()` 로 바꿔 만료 규칙까지 실어도
    통과한다 — 그것이 이 컷오버에서 실제로 나올 수 있는 실수다.

    ★ 두 가지가 이 테스트를 **판별력 있게** 만든다. 둘 다 변이를 심어 보고 정했다.
      1. 오른쪽 변이 `read_active_policies`(api 헬퍼)가 **아니라 저장소 조회**다.
         헬퍼를 양변에 쓰면 그 헬퍼가 `active()` -> `list()` 로 바뀔 때 두 변이 같이
         움직여 항등식이 된다.
      2. 만료된 규칙을 **먼저 심는다.** 시드 규칙은 전부 무기한이라(`effective_*` 가
         NULL) 그 상태에서는 `list()` 와 `active()` 가 같아서, 심지 않으면 1번을 고쳐도
         변이가 잡히지 않는다. 실제로 그렇게 통과하는 것을 확인하고 이 줄을 넣었다.
    """
    now = datetime.now(timezone.utc)
    with create_store(store_url) as store:
        store.rule_versions.add(
            _seed_version("rv-lapsed", "lapsed_policy", store_url,
                          effective_from=now - timedelta(days=90),
                          effective_to=now - timedelta(days=30))
        )

    result = _analyze(client)
    with create_store(store_url) as store:
        active = store.rule_versions.active(now)
    assert _policy_ids(result) == sorted(v.payload["id"] for v in active)


def test_a_rule_version_outside_its_window_stays_out_of_the_verdict(client, store_url):
    """`effective_from <= now < effective_to` 를 실제로 판정이 따르는지.

    아직 시행 전인 규칙과 이미 만료된 규칙 둘 다 심는다. 한쪽만 심으면 술어의 절반이
    검증되지 않은 채 남는다.
    """
    baseline = _policy_ids(_analyze(client))
    now = datetime.now(timezone.utc)

    with create_store(store_url) as store:
        store.rule_versions.add(
            _seed_version("rv-future", "future_policy", store_url,
                          effective_from=now + timedelta(days=30), effective_to=None)
        )
        store.rule_versions.add(
            _seed_version("rv-expired", "expired_policy", store_url,
                          effective_from=now - timedelta(days=60), effective_to=now - timedelta(days=1))
        )

    assert _policy_ids(_analyze(client)) == baseline, "시행 전/만료 규칙이 판정에 실렸다 (SPEC 2.3)"


# ==========================================================================
# 지역 0건 — 기동 거부 + 런타임 오류 봉투 (코디네이터 결정 2026-08-14)
# ==========================================================================

def _drop_regions(url: str) -> None:
    """저장소 인터페이스에 지역 삭제가 없다. 사고를 흉내 내려면 DB 를 직접 여는 수밖에 없고,
    그것이 곧 이 검사가 상정하는 사고다 (`test_engine_constants` 가 상수에 쓰는 방법과 같다)."""
    conn = sqlite3.connect(url.split("://", 1)[1])
    with conn:
        conn.execute("DELETE FROM region")
    conn.close()


def test_boot_is_refused_when_the_store_has_no_region(store_url):
    """지역 0건은 판정 입력이 아니라 설정 오류다. 기본값으로 메우지 않고 뜨지 않는다.

    상수 하나를 지우면 기동이 거부된다(SPEC 10.2 1-①)와 **같은 모양**이다.
    """
    _drop_regions(store_url)

    with pytest.raises(RuntimeError) as caught:
        boot_require_regions()

    message = str(caught.value)
    assert "지역" in message and "0개" in message, message
    # 시연 중 이 메시지만 보고 조치할 수 있어야 한다.
    assert "seed_store.py" in message, "무엇을 하라는 안내가 없다"
    assert "fail-closed" in message


def test_require_regions_passes_on_a_seeded_store(store_url):
    with create_store(store_url) as store:
        assert require_regions(store), "시드된 저장소인데 지역 검사가 비었다"


def test_an_emptied_region_table_answers_with_the_error_envelope(client, store_url):
    """기동 이후에 비어도 IndexError 가 아니라 표준 오류 봉투로 나간다.

    기동 검사는 기동 이후의 삭제를 못 잡는다. SPEC 2.3 때문에 런타임은 매번 새로 읽으므로
    그 창은 실재한다.
    """
    _drop_regions(store_url)

    for path, payload in (("/api/analyze", PROFILE), ("/api/chat", {"message": "전세와 월세 중 뭐가 나을까요"})):
        response = client.post(path, json=payload)
        assert response.status_code == 500, (path, response.text)
        body = response.json()
        assert set(body) == {"error"}, body
        assert body["error"]["code"] == "regions_unavailable"
        assert body["error"]["message"] == REGIONS_EMPTY_MESSAGE

    response = client.get("/api/regions")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "regions_unavailable"


# ==========================================================================
# 프로세스 수명 캐시가 남아 있지 않은가 — 구조로 본다
# ==========================================================================

#: 판정 경로에 있으면 안 되는 호출. 왼쪽이 캐시(2.3), 오른쪽이 파일 I/O(1.2)다.
_BANNED_CALLS = {"lru_cache", "cache", "open"}
_BANNED_ATTRS = {"lru_cache", "cache", "load", "read_text", "read_bytes"}


def test_the_engines_package_holds_no_memoisation_and_no_file_reader():
    """`store` 에 걸어 둔 것과 같은 구조 검사를 판정 경로에도 건다.

    행동 테스트(위)는 지금 캐시가 없음을 보이고, 이 검사는 **다시 들어오는 것**을 막는다.
    `store/test_no_process_cache.py` 가 저장소 쪽에서 하는 일과 같다.

    문자열 검색이 아니라 AST 로 본다 (`crosscheck/test_architecture.py` 와 같은 방식).
    줄 단위로 훑으면 이 사고를 서술한 주석·docstring 이 스스로 걸린다 — 실제로 처음
    작성했을 때 그렇게 걸렸고, 그런 검사는 결함이 아니라 설명을 금지하게 된다.
    """
    engines_dir = Path(__file__).resolve().parents[2] / "src" / "home_compass" / "engines"
    offenders = []
    for path in sorted(engines_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _BANNED_CALLS:
                    hit = func.id
                elif isinstance(func, ast.Attribute) and func.attr in _BANNED_ATTRS:
                    hit = func.attr
            elif isinstance(node, ast.ImportFrom) and node.module in ("functools", "json", "pathlib"):
                hit = f"from {node.module} import ..."
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("json", "pathlib"):
                        hit = f"import {alias.name}"
            if hit:
                offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')}: {hit}")
    assert not offenders, (
        "engines 에 캐시나 파일 읽기가 되돌아왔다 (SPEC 2.3 · 1.2):\n" + "\n".join(offenders)
    )


def test_these_tests_do_not_mutate_the_session_store(store_url):
    """격리 — 지역을 지우는 케이스가 세션 저장소를 건드리지 않는다.

    새는 순간 뒤에 도는 테스트가 이유 없이 빨간불이 되고, 원인은 순서에 따라 달라져
    재현되지 않는다 (`api/test_boot_constants.py` 가 상수 쪽에서 하는 것과 같은 검사다).
    """
    assert store_url != SESSION_STORE_URL, "픽스처가 세션 저장소를 그대로 쓰고 있다"

    _drop_regions(store_url)  # 이 파일에서 가장 파괴적인 조작을 실제로 해 본다

    with create_store(SESSION_STORE_URL) as session_store:
        assert session_store.regions.list(), "세션 저장소의 지역이 지워졌다"


# ==========================================================================
# 픽스처 헬퍼
# ==========================================================================

def _policy_payload(policy_id: str, name: str) -> dict:
    """엔진이 받는 정책 한 건. 필드는 `data/policies.json` 항목과 같은 모양이다."""
    return {
        "id": policy_id,
        "name": name,
        "category": "loan",
        "maxAmountKRW": 100_000_000,
        "rateRangePct": [2.0, 3.0],
        "source": "테스트 픽스처",
        "disclaimer": "테스트 픽스처입니다.",
        "criteria": {"ageMin": 19, "ageMax": 39},
        "conditionalChecks": [],
    }


def _seed_like_provenance(store_url: str):
    """시드가 쓰는 것과 같은 계보. 값을 지어내지 않으므로 `unverified` 다."""
    from home_compass.store import Provenance

    return Provenance(
        source_kind="statute",
        source_name="테스트 픽스처",
        source_ref=None,
        observed_at=None,
        fetched_at=None,
        verification="unverified",
    )


def _seed_version(version_id: str, policy_id: str, store_url: str, *, effective_from, effective_to):
    return RuleVersion(
        id=version_id,
        policy_id=policy_id,
        payload=_policy_payload(policy_id, f"{policy_id} 제도"),
        status="approved",
        origin="seed",
        effective_from=effective_from,
        effective_to=effective_to,
        supersedes=None,
        approved_by=None,
        provenance=_seed_like_provenance(store_url),
        created_at=T0,
    )


def _policy_source():
    from home_compass.store import PolicySource

    return PolicySource(
        id="src-leak-probe",
        text="만 19세 이상 39세 이하 무주택 세대주에게 최대 1억원을 지원한다.",
        source_ref="https://example.invalid/notice/leak-probe",
        fetched_at=T0,
    )
