"""교차 테스트 — 회귀·감도분석 프로필 세트 (SPEC 9.2.2, 코디네이터 소유).

세트는 계약이다. 바뀌면 골든 스냅샷이 통째로 바뀌므로 SPEC 8.2 절차를 따른다.

이 파일이 지키는 것은 둘이다.

1. **선언과 내용이 어긋나지 않는가** — 프로필을 넣고 축을 안 적거나, 축만 적고 프로필을
   안 넣으면 실패한다. 세트가 커질 때 [무엇을 왜 넣었는가]가 사라지는 것을 막는다.
2. **선언한 축이 실제로 열리는가** — 이쪽이 본체다. `axes` 에 적은 문장은 사람이 쓴
   주장이고, 주장은 코드가 바뀌면 조용히 거짓이 된다. 예를 들어 `non_metro` 가 여는 것은
   [비수도권 상한 5억]인데, 누가 `metro_sido_code_prefixes` 에 '26' 을 넣으면 그 프로필은
   더 이상 아무 분기도 열지 않으면서 이름만 남는다. 그 상태를 여기서 잡는다.

★ 축이 실제로 열리는지를 **판정 결과로** 확인한다. 상수를 다시 읽어 비교하면 그건 계약을
  계약으로 검증하는 것이라 아무것도 보장하지 못한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "backend" / "src"
TESTS = REPO_ROOT / "backend" / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

PROFILE_SET_PATH = REPO_ROOT / "contracts" / "regression_profiles.json"

#: SPEC 9.2.2 가 이름으로 못박은 축. 이 넷은 사라지면 안 된다.
SPEC_REQUIRED_AXES = ("zero_income", "very_high_income", "age_over_max", "unknown_region")


@pytest.fixture(scope="module")
def profile_set() -> dict:
    return json.loads(PROFILE_SET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def by_id(profile_set) -> dict:
    return {entry["id"]: entry["profile"] for entry in profile_set["profiles"]}


def test_the_set_is_versioned(profile_set):
    """버전이 없으면 [세트 변경 = 계약 변경](SPEC 9.2.2)을 추적할 수 없다."""
    assert profile_set["setVersion"]


def test_profile_ids_are_unique(profile_set):
    ids = [entry["id"] for entry in profile_set["profiles"]]
    assert len(ids) == len(set(ids)), f"중복 id: {sorted({i for i in ids if ids.count(i) > 1})}"


def test_every_profile_declares_an_axis_and_every_axis_has_a_profile(profile_set, by_id):
    """선언과 내용의 1:1. 축 없이 프로필만 늘리는 것이 [커버리지 확보] 착각의 시작이다."""
    declared = set(profile_set["axes"])
    present = set(by_id)
    assert declared == present, (
        f"축만 있고 프로필이 없는 것: {sorted(declared - present)} / "
        f"프로필만 있고 축 설명이 없는 것: {sorted(present - declared)}")


def test_the_spec_named_axes_are_still_present(profile_set):
    """SPEC 9.2.2 가 이름으로 요구한 축이 사라지지 않았는가."""
    missing = [a for a in SPEC_REQUIRED_AXES if a not in profile_set["axes"]]
    assert not missing, f"SPEC 9.2.2 가 명시한 축이 빠졌다: {missing}"


def test_the_uncovered_note_is_not_empty(profile_set):
    """**덮이지 않는 것을 적어 두는 칸이 비면 안 된다.**

    비어 있으면 [전부 덮었다]로 읽힌다. SPEC 9.2.2 는 커버리지 주장을 금지한다.
    실제로 `tco.fallback_conversion_rate_pct` 는 프로필로 덮을 수 없다 — 그 폴백은 지역이
    `conversionRatePct` 를 **갖지 않을 때만** 걸리는데 시드 지역 10건이 전부 갖고 있고,
    프로필은 지역을 고를 뿐 지역의 필드를 지우지 못한다.
    """
    assert profile_set.get("$uncovered"), "덮이지 않는 것을 적는 칸이 비어 있다"


# --- 선언한 축이 실제로 열리는가 (본체) --------------------------------------


@pytest.fixture(scope="module")
def decide(by_id):
    from firsthome.engines import analyze
    from decision_inputs import FROZEN_NOW, store_policies, store_regions
    from seed_constants import frozen_seed

    constants, regions, policies = frozen_seed(), store_regions(), store_policies(FROZEN_NOW)

    def run(profile_id: str) -> dict:
        return analyze(
            by_id[profile_id], constants=constants, regions=regions, policies=policies,
            now=FROZEN_NOW)

    return run


def test_non_metro_actually_selects_a_different_guarantee_cap(by_id):
    """F-4 수도권/비수도권 분기가 실제로 갈리는가 — 7억 대 5억."""
    from firsthome.engines import guarantee_deposit_cap_for
    from decision_inputs import store_regions
    from seed_constants import frozen_seed

    constants = frozen_seed()
    regions = {r["code"]: r for r in store_regions()}
    metro = guarantee_deposit_cap_for(regions[by_id["baseline"]["regionCode"]], constants=constants)
    other = guarantee_deposit_cap_for(regions[by_id["non_metro"]["regionCode"]], constants=constants)
    assert metro != other, (
        "non_metro 프로필이 baseline 과 같은 가입요건 상한을 받는다. "
        "risk.metro_sido_code_prefixes 가 바뀌어 이 프로필이 아무 분기도 열지 않는다.")


def test_metro_gyeonggi_is_metro_but_not_seoul(by_id):
    """수도권 접두가 '11' 만이 아님을 고정한다. 시드가 서울뿐이면 '41'·'28' 이 죽은 값이 된다."""
    from firsthome.engines import guarantee_deposit_cap_for
    from decision_inputs import store_regions
    from seed_constants import frozen_seed

    constants = frozen_seed()
    regions = {r["code"]: r for r in store_regions()}
    code = by_id["metro_gyeonggi"]["regionCode"]
    assert not code.startswith("11"), "metro_gyeonggi 가 서울 지역을 가리킨다"
    metro_cap = guarantee_deposit_cap_for(
        regions[by_id["baseline"]["regionCode"]], constants=constants)
    assert guarantee_deposit_cap_for(regions[code], constants=constants) == metro_cap, (
        "경기 지역이 수도권으로 판별되지 않는다 — 접두 목록에서 '41' 이 빠졌을 수 있다.")


def test_non_metro_no_guarantee_actually_has_no_guarantee(by_id):
    """`guaranteeAvailable=False` 경로가 실제로 열리는가."""
    from decision_inputs import store_regions

    regions = {r["code"]: r for r in store_regions()}
    region = regions[by_id["non_metro_no_guarantee"]["regionCode"]]
    assert region.get("guaranteeAvailable") is False, (
        "이 프로필의 지역이 보증 가능으로 바뀌었다 — 더 이상 그 경로를 열지 않는다.")


def test_household_four_actually_uses_the_four_person_living_cost(decide, by_id):
    """가구원수별 생활비의 4인 값이 **실제로 판정에 쓰이는가** (계약 결정 #14).

    나머지 프로필이 전부 1인이라, 이 프로필이 없으면 실사를 들여 확정한 4인 값이
    한 번도 쓰이지 않은 채 등재만 되어 있게 된다.
    """
    from seed_constants import frozen_seed

    expected = frozen_seed()["affordability.living_cost_by_household"][4]
    used = decide("household_four")["affordability"]["breakdown"]["livingCost"]
    base = decide("baseline")["affordability"]["breakdown"]["livingCost"]
    assert used == expected, f"4인 생활비가 계약값과 다르다: {used} != {expected}"
    assert used != base, "4인 프로필이 1인과 같은 생활비를 쓴다 — 축이 열리지 않았다"


def test_the_added_region_axes_do_not_all_collapse_to_one_verdict(decide):
    """지역 축 넷이 **서로 다른 결과**를 내는가.

    전부 같은 숫자로 붕괴하면 프로필만 늘고 검증력은 그대로다. 이 표가 커지는 것이
    곧 규율이 무너지는 신호라는 5.1.2 의 논지와 같다.
    """
    ids = ["baseline", "non_metro", "non_metro_no_guarantee", "metro_gyeonggi",
           "max_jeonse_region"]
    scores = {i: decide(i)["risk"]["score"] for i in ids}
    assert len(set(scores.values())) > 1, f"지역 축이 전부 같은 위험 점수로 붕괴했다: {scores}"
