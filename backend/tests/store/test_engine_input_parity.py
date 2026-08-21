"""이관은 구조 변경이다 — **판정 숫자가 바뀌면 안 된다** (SPEC 10.2 1-①).

앞의 `test_seed.py` 는 저장소가 내놓는 *입력*이 파일과 같은지를 본다. 여기서는 한 걸음 더
가서 그 입력을 **실제 엔진에 넣고 나온 판정 결과**를 두 경로에서 비교한다. 입력이 같아도
타입이 미묘하게 달라지면(예: bool 이 int 로) 결과가 갈릴 수 있고, 그것은 입력 비교로는
안 잡힌다.

`engines` 는 W-engines 소유이고 1-① 에서 상수 주입 시그니처가 바뀐다. 그때 이 파일이
깨지면 그것은 오탐이 아니라 **컷오버 순서를 정하라는 신호**다 (SPEC 9.4 직렬화 규칙).

> 그 컷오버가 실제로 일어났다 (PR #7 + PR #8). 엔진이 상수 매핑을 주입받게 되면서
> 이 파일의 호출부를 맞췄고, 그러면서 **비교 대상이 하나 늘었다** — 아래 참조.

> ★ 그리고 한 번 더 일어났다 (Wave 2 지역·정책 컷오버). **파일 경로 쪽 변이 바뀌었다** —
> 예전에는 `engines.file_regions()` · `file_policies()` 였는데 그 둘이 사라졌다.
> `lru_cache` 로 데이터 파일을 읽던 경로이고 SPEC 2.3 이 금지하는 프로세스 수명
> 캐시였다. 테스트를 살리려고 엔진에 파일 I/O 를 남기면 이번 컷오버가 자기 목적을
> 배반하므로, 대신 **`store/seed.py` 가 읽는 그 파일을 여기서 직접 읽는다.**
> 대조의 논지는 그대로다 — 왼쪽은 저장소를 거친 입력, 오른쪽은 파일에서 온 입력이다.

## 상수 매핑도 같은 위험을 진다

이 파일의 원래 논지는 "입력이 같아도 타입이 미묘히 달라지면 결과가 갈리는데 그것은 입력
비교로 안 잡힌다" 였다. 상수 매핑은 정확히 같은 위험을 진다. `ModelConstant.value` 는
SQLite 에 JSON 으로 저장되고, JSON 은 **dict 의 int 키도 tuple 도 모른다** —
`living_cost_by_household` 의 `{1: ...}` 는 `{"1": ...}` 로, `jeonse_loan_priority` 의
tuple 은 list 로 돌아올 수 있다. 그러면 `size in by_household` 가 조용히 거짓이 되고
판정이 갈린다.

그래서 양변에 **같은 매핑을 넣지 않는다.**

    저장소 경로 = 저장소가 꺼낸 데이터 + 저장소가 꺼낸 상수 매핑
    파일 경로   = 파일 데이터        + 계약 파일로 만든 상수 매핑

같은 매핑을 양쪽에 넣으면 상수 왕복 결함이 두 변에서 똑같이 상쇄되어 영원히 숨는다.
"""

from __future__ import annotations

import json

import pytest
from conftest import T0
from seed_constants import frozen_seed

from home_compass.engines import guarantee_deposit_cap_for
from home_compass.engines.eligibility import evaluate_policies
from home_compass.engines.risk import scan_deposit_risk
from home_compass.store.seed import (
    SEED_DATA_DIR,
    seed_model_constants,
    seed_policies,
    seed_regions,
)


def _seed_file(name: str) -> list:
    """`store/seed.py` 가 읽는 그 파일을 같은 자리에서 읽는다. 경로를 두 벌로 두지 않는다."""
    return json.loads((SEED_DATA_DIR / name).read_text(encoding="utf-8"))[
        name.removesuffix(".json")
    ]


def file_regions() -> list:
    """엔진이 받는 dict 만 꺼낸다.

    굳힌 시드(결정 #40)의 한 항목은 `payload` + 계보 둘이다. 엔진에 넘어가는 것은
    `payload` 뿐이며, `to_engine_dict()` 가 내놓는 것과 같은 모양이다.
    """
    return [entry["payload"] for entry in _seed_file("regions.json")]


def file_policies() -> list:
    return _seed_file("policies.json")

#: 계약 파일(`frozen_current_value`)로 만든 매핑 — 파일 경로 쪽 변에만 쓴다.
CONTRACT_CONSTANTS = frozen_seed()

PROFILE = {
    "age": 29,
    "annualIncomeKRW": 42_000_000,
    "monthlyNetIncomeKRW": 2_900_000,
    "liquidAssetsKRW": 60_000_000,
    "existingDebtMonthlyKRW": 150_000,
    "householdSize": 1,
    "isHomeless": True,
    "isNewlywed": False,
    "isSMEWorker": True,
    "regionCode": "11440",
}


def test_eligibility_verdicts_are_identical_through_the_store(store):
    """같은 프로필을 파일 경로와 저장소 경로로 각각 판정해 결과를 통째로 비교한다."""
    seed_policies(store, at=T0)
    seed_model_constants(store)
    from_store = [v.payload for v in store.rule_versions.active(T0)]

    assert evaluate_policies(
        PROFILE, from_store, "서울 마포구", constants=store.model_constants.as_mapping()
    ) == evaluate_policies(
        PROFILE, file_policies(), "서울 마포구", constants=CONTRACT_CONSTANTS
    )


@pytest.mark.parametrize("code", [r["code"] for r in file_regions()])
def test_risk_scores_are_identical_through_the_store(store, code):
    """전 지역을 돈다. 한 지역만 보면 bool/실수 왕복 결함을 놓친다."""
    seed_regions(store)
    seed_model_constants(store)
    stored = store.regions.get(code).to_engine_dict()
    original = next(r for r in file_regions() if r["code"] == code)

    def score(region: dict, constants) -> dict:
        return scan_deposit_risk(
            deposit_krw=region["jeonseMedianKRW"],
            jeonse_ratio_pct=region["jeonseRatioPct"],
            loan_amount_krw=150_000_000,
            guarantee_available=bool(region["guaranteeAvailable"]),
            market_risk=region["marketRisk"],
            region_name=region["name"],
            guarantee_deposit_cap_krw=guarantee_deposit_cap_for(region, constants=constants),
            constants=constants,
        )

    assert score(stored, store.model_constants.as_mapping()) == score(
        original, CONTRACT_CONSTANTS
    )


def test_no_policy_disappears_or_appears_in_the_move(store):
    seed_policies(store, at=T0)
    assert [v.payload["id"] for v in store.rule_versions.active(T0)] == [
        p["id"] for p in file_policies()
    ]


def test_no_region_field_changes_type_in_the_move(store):
    """SQLite 에는 bool 이 없다. `guaranteeAvailable` 이 1 로 돌아오면 리스크 판정이 바뀐다."""
    seed_regions(store)
    for stored_region, original in zip(store.regions.list(), file_regions()):
        engine_dict = stored_region.to_engine_dict()
        for key, value in original.items():
            assert type(engine_dict[key]) is type(value), f"{original['code']}.{key}"


def _type_shape(value) -> str:
    """중첩 타입까지 본다. 겉이 dict 로 같아도 키가 int -> str 로 바뀌면 판정이 갈린다."""
    if isinstance(value, dict):
        inner = sorted({f"{_type_shape(k)}:{_type_shape(v)}" for k, v in value.items()})
        return "dict[" + ",".join(inner) + "]"
    if isinstance(value, (list, tuple)):
        inner = sorted({_type_shape(item) for item in value})
        return f"{type(value).__name__}[" + ",".join(inner) + "]"
    return type(value).__name__


def test_no_model_constant_changes_type_in_the_move(store):
    """상수 매핑의 왕복도 타입까지 같아야 한다 (위 지역 테스트와 같은 논지).

    위 두 테스트가 양변에 서로 다른 매핑을 넣으므로 타입이 갈리면 판정 비교에서도 잡힌다.
    다만 그때 나오는 것은 "점수가 다르다" 뿐이라 원인을 가리키지 못한다. 여기서 **어느 키의
    무슨 타입이 어긋났는지**를 직접 말하게 한다.
    """
    seed_model_constants(store)
    stored = store.model_constants.as_mapping()

    assert set(stored) == set(CONTRACT_CONSTANTS), "저장소와 계약의 키 집합이 다르다."
    for key, expected in CONTRACT_CONSTANTS.items():
        assert _type_shape(stored[key]) == _type_shape(expected), key
        assert stored[key] == expected, key
