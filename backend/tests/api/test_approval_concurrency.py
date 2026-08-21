"""SPEC 4.6 — 승인은 한 번만 일어나야 한다 (소유자: `api`).

`test_auth.py` 는 같은 초안에 **순차로** 두 번 치고 두 번째가 409 인 것을 고정한다.
그것으로는 4.6 이 요구한 것을 다 덮지 못한다. 4.6 의 문장은 이렇다:

    위 셋을 각각 테스트로 고정한다. **동시 실행을 흉내 내** 두 번째가 거부되는 것을 확인한다.

순차 두 번은 `_pending_draft_or_error` 의 상태 검사 하나만 지나간다. 검사와 쓰기 사이에
트랜잭션 경계가 없다는 사실은 **두 요청이 그 사이에 겹칠 때만** 드러난다.

**이 파일의 지배적 실패 양상은 [경합을 흉내 냈다고 믿는 것]이다.** 스레드를 띄웠는데 실은
직렬로 돌았다면 초록불은 원자화의 증거가 아니라 흉내가 실패했다는 증거다. 그래서 두 겹으로
막는다 —

  1. 요청마다 시작·종료 시각을 재고, **구간이 실제로 겹쳤는지**를 단언한다.
     겹치지 않았으면 이 테스트는 아무것도 잡지 않았다는 뜻이므로 그 자리에서 실패한다.
  2. 한 번이 아니라 여러 초안에 걸쳐 반복한다. 한 번의 운 좋은 인터리빙에 기대지 않는다.

경합이 진짜인 근거: `main.py` 는 **요청마다** `store_from_env()` 로 저장소를 새로 연다.
따라서 스레드마다 SQLite 커넥션이 다르고, 직렬화는 GIL 이 아니라 DB 잠금이 결정한다.
동기 엔드포인트는 Starlette 의 워커 스레드풀에서 돌므로 파이썬 레벨에서도 겹친다.

격리: 케이스마다 자기 `tmp_path` 저장소를 만들어 `HOME_COMPASS_STORE_URL` 을 그쪽으로 돌리고
세션 원장을 비운다. `conftest.py` 의 세션 저장소는 여기서 건드리지 않는다.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from home_compass import main as main_module
from home_compass.auth import CSRF_HEADER_NAME
from home_compass.auth import ensure_seed_accounts
from home_compass.main import app
from home_compass.store import STORE_URL_ENV, PolicySource, RuleDraft, create_store
from home_compass.store.seed import seed_all

T0 = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)

RULE_MANAGER_PW = os.environ["HOME_COMPASS_SEED_RULE_MANAGER_PASSWORD"]

#: 같은 초안에 동시에 달려드는 요청 수. 2 로는 인터리빙이 운에 좌우된다.
CLAIMERS = 8

#: 경합을 반복하는 횟수. 한 번의 인터리빙에 기대면 그 테스트는 간헐적으로만 참이다.
ROUNDS = 6

#: 승인이 판정을 실제로 움직이도록 시드와 **다른 값**을 담는다.
DRAFT_PAYLOAD = {
    "policy_id": "buttress_youth",
    "criteria": {
        "ageMin": 19,
        "ageMax": 39,
        "annualIncomeMaxKRW": 60_000_000,
        "assetMaxKRW": None,
        "requireHomeless": True,
        "requireNewlywed": False,
        "requireSME": False,
        "regionPrefixes": None,
    },
    "maxAmountKRW": 250_000_000,
    "rateRangePct": [1.8, 3.1],
    "conditionalChecks": [],
    "not_found": ["/criteria/assetMaxKRW"],
}


# --------------------------------------------------------------------------
# 픽스처 — `test_auth.py` 와 같은 모양이다 (모듈마다 자족한다는 이 디렉터리의 관례)
# --------------------------------------------------------------------------

@pytest.fixture
def store_url(tmp_path, monkeypatch) -> str:
    url = f"sqlite://{tmp_path / 'concurrency.db'}"
    with create_store(url) as store:
        seed_all(store, at=T0)
        ensure_seed_accounts(store, now=T0, announce=lambda lines: None)
    monkeypatch.setenv(STORE_URL_ENV, url)
    return url


@pytest.fixture
def clock(monkeypatch):
    """시계를 **손으로 돌린다.** 벽시계로 두면 이 파일이 재는 것이 경합이 아니게 된다.

    회차마다 1초씩 밀어야 하는 이유는 `supersede` 가 `at > previous.effective_from` 을
    요구하기 때문이다 — 한 정책의 승인 이력은 같은 순간에 두 번 열릴 수 없다. 이것은
    경합과 무관한 순서 불변식이고, 고정 시계로 두면 두 번째 회차가 **경합이 아니라 그
    불변식 때문에** 깨져 테스트가 엉뚱한 것을 말하게 된다.
    """
    holder = {"now": T0}
    monkeypatch.setattr(main_module, "request_now", lambda: holder["now"])
    return holder


@pytest.fixture
def client(store_url, clock) -> TestClient:
    main_module.SESSIONS.clear()
    with TestClient(app) as test_client:
        yield test_client
    main_module.SESSIONS.clear()


def as_rule_manager(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login", json={"username": "rulemanager", "password": RULE_MANAGER_PW}
    )
    assert response.status_code == 200, response.text
    return response.json()["csrfToken"]


def seed_draft(store_url: str, draft_id: str) -> str:
    """`pending` 초안 하나를 심는다. 원문도 함께 있어야 계보가 성립한다."""
    with create_store(store_url) as store:
        if store.policy_sources.get("src-1") is None:
            store.policy_sources.add(
                PolicySource(
                    id="src-1",
                    text="청년전용 버팀목전세자금대출 신청 연령은 만 19세 이상 39세 이하입니다.",
                    source_ref="https://nhuf.molit.go.kr/",
                    fetched_at=T0,
                    attribution="주택도시기금 공고",
                )
            )
        store.rule_drafts.add(
            RuleDraft(
                id=draft_id,
                policy_source_id="src-1",
                policy_id="buttress_youth",
                status="pending",
                payload=DRAFT_PAYLOAD,
                created_at=T0,
            )
        )
    return draft_id


# --------------------------------------------------------------------------
# 경합 구동 — 흉내가 실제로 겹쳤는지까지 돌려준다
# --------------------------------------------------------------------------

class _Attempt:
    __slots__ = ("status", "body", "started", "ended")

    def __init__(self, status: int, body: object, started: float, ended: float) -> None:
        self.status = status
        self.body = body
        self.started = started
        self.ended = ended


def _race_approve(client: TestClient, csrf: str, draft_id: str, workers: int) -> list[_Attempt]:
    """`workers` 개의 스레드가 **같은 순간에** 같은 초안을 승인하려 든다.

    스레드 안에서 터진 예외를 들고 나온다. `TestClient` 는 서버 예외를 응답으로 바꾸지
    않고 호출자에게 다시 던지므로, 잡지 않으면 [응답이 비어 있다] 라는 엉뚱한 실패
    메시지만 남고 **무엇이 터졌는지**가 사라진다.
    """
    barrier = threading.Barrier(workers)
    attempts: list[_Attempt | None] = [None] * workers
    crashes: list[BaseException] = []

    def attempt(index: int) -> None:
        barrier.wait()
        started = time.perf_counter()
        try:
            response = client.post(
                f"/api/admin/drafts/{draft_id}/approve",
                json={"reason": f"동시 승인 {index}"},
                headers={CSRF_HEADER_NAME: csrf},
            )
        except BaseException as exc:  # noqa: BLE001 — 스레드 밖으로 들고 나간다
            crashes.append(exc)
            return
        ended = time.perf_counter()
        attempts[index] = _Attempt(response.status_code, response.json(), started, ended)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "승인 요청이 끝나지 않았다 — 교착 의심"
    assert not crashes, (
        "동시 승인이 거부가 아니라 예외로 끝났다 "
        f"({len(crashes)}/{workers}): {[f'{type(e).__name__}: {e}' for e in crashes]}"
    )
    return [a for a in attempts if a is not None]


def _overlapped(attempts: list[_Attempt]) -> bool:
    """구간이 실제로 겹쳤는가 — **흉내가 성립했는지**의 관측이다.

    가장 늦게 시작한 요청이 가장 일찍 끝난 요청보다 먼저 시작했다면 두 구간은 겹친다.
    전부 직렬로 돌았다면 이 값은 거짓이고, 그 실행에서 초록불은 아무 뜻도 없다.
    """
    return max(a.started for a in attempts) < min(a.ended for a in attempts)


# --------------------------------------------------------------------------
# ★ SPEC 4.6 첫째 — 같은 draft 를 두 사람이 승인하는 것을 막는다
# --------------------------------------------------------------------------

class TestSimultaneousApproval:
    def test_the_threads_really_overlap(self, client, store_url):
        """먼저 **흉내가 성립하는지**부터 고정한다.

        이 단언이 깨지면 아래 두 테스트의 초록불은 원자화의 증거가 아니다. 반증 관측을
        본 테스트 안에도 넣지만, 그것이 왜 필요한지는 여기서 따로 말해 둔다.
        """
        draft_id = seed_draft(store_url, "draft-overlap")
        csrf = as_rule_manager(client)
        attempts = _race_approve(client, csrf, draft_id, CLAIMERS)
        assert _overlapped(attempts), (
            "스레드가 직렬로 돌았다 — 이 파일은 아무것도 관측하지 못했다: "
            f"{[(round(a.started, 6), round(a.ended, 6)) for a in attempts]}"
        )

    def test_exactly_one_of_many_simultaneous_approvals_wins(self, client, store_url, clock):
        """동시에 여덟이 달려들어도 200 은 하나고 나머지는 전부 409 다.

        500 이 하나라도 섞이면 그것은 [거부] 가 아니라 [터진 것] 이다. 4.6 은 두 번째
        시도가 **실패** 하라고 했지 서버가 죽으라고 하지 않았다.
        """
        csrf = as_rule_manager(client)
        for round_index in range(ROUNDS):
            clock["now"] = T0 + timedelta(seconds=round_index)
            draft_id = seed_draft(store_url, f"draft-race-{round_index}")
            attempts = _race_approve(client, csrf, draft_id, CLAIMERS)
            assert _overlapped(attempts), f"{round_index} 회차에서 경합이 성립하지 않았다"

            codes = sorted(a.status for a in attempts)
            assert codes == [200] + [409] * (CLAIMERS - 1), (
                f"{round_index} 회차 응답: {codes} / "
                f"{[a.body for a in attempts if a.status not in (200, 409)]}"
            )
            for attempt in attempts:
                if attempt.status == 409:
                    assert attempt.body["error"]["code"] == "draft_already_decided"

    def test_simultaneous_approvals_create_exactly_one_rule_version(self, client, store_url, clock):
        """★ 4.6 — 두 개의 `RuleVersion` 이 생기지 않는다.

        `ApprovalRecord` 도 함께 센다. 승인 기록만 둘이고 버전이 하나면 감사추적은
        [두 번 승인됐다] 고 말하는데 규칙은 한 번만 바뀐 상태가 되고, 그것이 4.6 이
        [감사추적이 사실과 어긋난다] 고 부른 그것이다.
        """
        csrf = as_rule_manager(client)
        for round_index in range(ROUNDS):
            clock["now"] = T0 + timedelta(seconds=round_index)
            draft_id = seed_draft(store_url, f"draft-count-{round_index}")
            attempts = _race_approve(client, csrf, draft_id, CLAIMERS)
            assert _overlapped(attempts), f"{round_index} 회차에서 경합이 성립하지 않았다"

            with create_store(store_url) as store:
                versions = [v for v in store.rule_versions.list() if v.id.endswith(draft_id)]
                assert len(versions) == 1, f"{round_index} 회차에서 버전이 {len(versions)} 개"
                assert versions[0].origin == "human_approval"
                records = store.approvals.list_for(versions[0].id)
                assert len(records) == 1, f"{round_index} 회차 승인 기록 {len(records)} 건"
                assert store.rule_drafts.get(draft_id).status == "approved"

        with create_store(store_url) as store:
            human = [v for v in store.rule_versions.list() if v.origin == "human_approval"]
            assert len(human) == ROUNDS
            # 활성은 언제나 하나다 — 겹쳐 열린 버전이 있으면 판정이 같은 정책을 두 번 센다.
            active = [
                v for v in store.rule_versions.active(clock["now"])
                if v.policy_id == "buttress_youth"
            ]
            assert len(active) == 1


class TestTheClaimIsReleasedWhenTheApprovalCannotFinish:
    def test_a_failed_rule_version_write_puts_the_draft_back_to_pending(
        self, client, store_url, monkeypatch
    ):
        """선점을 앞으로 옮긴 대가를 갚는다.

        선점이 첫 줄로 오면서 [상태는 결정됐는데 `RuleVersion` 은 없다] 는 상태가 새로
        가능해졌다. 그 상태는 초안을 결정 칸에 가둬 **재시도조차** 막으므로, 선점 이후가
        실패하면 `pending` 으로 되돌린다. 되돌리지 않으면 원자화가 [한 번만 일어난다]를
        [한 번도 못 일어난다]로 바꿔 놓는다.
        """
        from home_compass.store.errors import StoreError
        from home_compass.store.sqlite_store import _RuleVersions

        draft_id = seed_draft(store_url, "draft-rollback")
        csrf = as_rule_manager(client)

        # 깃발로 켜고 끈다. `monkeypatch.undo()` 는 이 테스트의 **모든** 패치를 되돌리는데
        # 거기에는 `clock` 픽스처가 건 `request_now` 도 들어 있어, 되돌리는 순간 세션이
        # 만료된 것으로 보인다.
        failing = {"on": True}
        original = _RuleVersions.supersede

        def boom(self, previous_id, new_version, at):
            if failing["on"]:
                raise StoreError("실험: 버전 기록이 실패했다")
            return original(self, previous_id, new_version, at)

        monkeypatch.setattr(_RuleVersions, "supersede", boom)
        with pytest.raises(StoreError):
            client.post(
                f"/api/admin/drafts/{draft_id}/approve",
                json={"reason": "실패할 승인"},
                headers={CSRF_HEADER_NAME: csrf},
            )

        with create_store(store_url) as store:
            assert store.rule_drafts.get(draft_id).status == "pending"
            assert [v.id for v in store.rule_versions.list() if v.origin == "human_approval"] == []

        # 되돌아왔으면 **다시 승인할 수 있어야** 한다 — 그것이 되돌린 이유다.
        failing["on"] = False
        retry = client.post(
            f"/api/admin/drafts/{draft_id}/approve",
            json={"reason": "재시도"},
            headers={CSRF_HEADER_NAME: csrf},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["ruleVersionId"] == f"approval:{draft_id}"


# --------------------------------------------------------------------------
# ★ SPEC 4.6 셋째 — 배치와 승인은 동시에 돈다
# --------------------------------------------------------------------------

class TestBatchRunsAlongsideApproval:
    def test_the_batch_makes_only_pending_while_an_approval_runs(self, client, store_url):
        """배치가 새 초안을 쏟아붓는 동안 승인이 돌아도 승인된 `RuleVersion` 은 멀쩡하다.

        배치를 저장소에 직접 거는 이유는 그것이 배치의 실제 모양이기 때문이다 —
        `ingest` 는 HTTP 를 지나지 않고 `store.rule_drafts.add` 를 부른다. 배치 스레드는
        자기 커넥션을 따로 연다 (SQLite 커넥션은 만든 스레드에 묶인다).
        """
        target = seed_draft(store_url, "draft-under-batch")
        csrf = as_rule_manager(client)

        stop = threading.Event()
        started = threading.Event()
        made: list[str] = []
        failures: list[BaseException] = []

        def batch() -> None:
            try:
                with create_store(store_url) as store:
                    index = 0
                    while not stop.is_set() or index < 20:
                        draft_id = f"batch-{index:03d}"
                        store.rule_drafts.add(
                            RuleDraft(
                                id=draft_id,
                                policy_source_id="src-1",
                                policy_id="buttress_youth",
                                status="pending",
                                payload=DRAFT_PAYLOAD,
                                created_at=T0,
                            )
                        )
                        made.append(draft_id)
                        index += 1
                        started.set()
                        if index >= 200:
                            break
            except BaseException as exc:  # noqa: BLE001 — 스레드 밖으로 들고 나간다
                failures.append(exc)

        worker = threading.Thread(target=batch)
        worker.start()
        assert started.wait(timeout=30), "배치가 시작되지 않았다"

        attempts = _race_approve(client, csrf, target, CLAIMERS)
        stop.set()
        worker.join(timeout=60)
        assert not worker.is_alive(), "배치 스레드가 끝나지 않았다"
        assert not failures, f"배치가 터졌다: {failures}"
        assert len(made) >= 20, f"배치가 만든 초안이 {len(made)} 건뿐이다 — 겹쳤다고 보기 어렵다"

        codes = sorted(a.status for a in attempts)
        assert codes == [200] + [409] * (CLAIMERS - 1), f"응답: {codes}"

        with create_store(store_url) as store:
            # 배치가 만든 것은 pending 뿐이다 — 승인된 버전을 건드리지 않는다.
            assert {store.rule_drafts.get(d).status for d in made} == {"pending"}
            versions = store.rule_versions.list()
            assert [v.id for v in versions if v.origin == "human_approval"] == [
                f"approval:{target}"
            ]
            approved = store.rule_versions.get(f"approval:{target}")
            assert approved.payload["criteria"]["ageMax"] == 39
            assert approved.effective_to is None
            active = [v for v in store.rule_versions.active(T0) if v.policy_id == "buttress_youth"]
            assert [v.id for v in active] == [f"approval:{target}"]
