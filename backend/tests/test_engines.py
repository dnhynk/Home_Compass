"""pytest suite for the four deterministic engines + the HTTP layer.

Run from backend/:  python -m pytest -q
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from home_compass.main import app  # noqa: E402
from home_compass.engines import (  # noqa: E402
    analyze,
    find_region,
    guarantee_deposit_cap_for,
)
from home_compass.engines.affordability import assess_affordability  # noqa: E402
from home_compass.llm.agent import (  # noqa: E402
    TOOL_NAMES,
    chat,
    execute_tool,
    get_llm_mode,
    to_anthropic_tools,
    to_openai_tools,
    tool_specs,
)
from home_compass.config import (  # noqa: E402
    clean_env_value,
    find_env_file,
    load_env_file,
    parse_env_text,
    resolve_provider,
)
from home_compass.engines.eligibility import evaluate_policies  # noqa: E402
from home_compass.engines.risk import scan_deposit_risk  # noqa: E402
from home_compass.engines.tco import build_scenarios  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed  # noqa: E402

# SPEC 5.1.1 — 엔진은 상수 매핑을 주입받는다. 테스트는 contracts 의 frozen_current_value 로
# 매핑을 만든다 (기동 경로와 같은지는 `test_engine_constants` 가 등식으로 붙든다).
CONSTANTS = frozen_seed()

# SPEC 2.3 컷오버 — 지역·정책도 주입받는다. `engines.load_regions` · `load_policies` 는
# 없어졌다. 그 둘은 데이터 파일을 `lru_cache` 로 읽어 재기동 전까지 갱신이 판정에
# 반영되지 않게 만들던 경로다. 지금 유일한 출처는 저장소다 (`decision_inputs.py`).
REGIONS = store_regions()
POLICIES = store_policies(FROZEN_NOW)

#: 엔진 함수를 직접 부르는 테스트가 쓰는 가입요건 상한 (F-4). 서울 마포구 기준이며
#: 지역별 판별은 `guarantee_deposit_cap_for` 가 한다.
METRO_CAP = CONSTANTS["risk.guarantee_deposit_cap_metro_krw"]

BASE_PROFILE = {
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

client = TestClient(app)


def _rationale_ok(payload: dict) -> bool:
    r = payload.get("rationale")
    return isinstance(r, list) and len(r) > 0 and all(isinstance(x, str) and x for x in r)


# ==========================================================================
# E1 — Affordability
# ==========================================================================

def test_e1_baseline_matches_contract_example():
    """3M net income / 300k debt / 1 person -> 860k cap, 730k recommended, safe.

    1-② 로 값이 움직였다. 생활비가 출처 없는 120만에서 공표값 1,530,773원으로
    오르면서(가계동향조사 2025년 연간, 주거비 제외) **어느 상한이 구속하는지가 바뀐다** —
    이전에는 비율 상한 900,000(소득의 30%)이 잔여여력보다 낮아 그쪽이 이겼는데,
    이제 잔여여력 869,227 = 3,000,000 − 1,530,773 − 300,000 − 300,000 이 더 낮아
    잔여여력 기준이 상한을 정한다. floor_to 만원 절사로 860,000 이다.
    밴드는 safe 그대로다 — 값은 움직였지만 결론은 뒤집히지 않았다.

    **1-③ F-2 에서도 이 사례의 권장액은 움직이지 않는다.** 잔여여력이 구속하는 구간이라
    이전에도 안전마진 쪽(860,000 × 0.85 = 731,000 → 730,000)이 이기고 있었고, 폐기한
    `recommended_ratio_cap`(소득의 25% = 750,000)은 애초에 구속하지 않았다.
    F-2 가 권장액을 바꾸는 것은 비율상한이 구속하는 구간뿐이다
    (`test_schwabe_and_recommendation.py` 참조).
    """
    result = assess_affordability(3_000_000, 42_000_000, 40_000_000, 300_000, 1, constants=CONSTANTS)
    assert result["maxMonthlyHousingCostKRW"] == 860_000
    assert result["recommendedMonthlyHousingCostKRW"] == 730_000
    assert "schwabeIndexPct" not in result  # F-1 — scenarios[] 로 이동 (SPEC 5.2.1)
    assert result["band"] == "safe"
    assert result["breakdown"] == {
        "netIncome": 3_000_000,
        "livingCost": 1_530_773,
        "existingDebt": 300_000,
        "buffer": 300_000,
    }
    assert _rationale_ok(result)


def test_e1_zero_income_never_crashes_and_is_risk():
    result = assess_affordability(0, 0, 0, 0, 1, constants=CONSTANTS)
    assert result["maxMonthlyHousingCostKRW"] == 0
    assert result["recommendedMonthlyHousingCostKRW"] == 0
    assert "schwabeIndexPct" not in result  # F-1 — scenarios[] 로 이동 (SPEC 5.2.1)
    assert result["band"] == "risk"
    assert _rationale_ok(result)


def test_e1_high_income_is_capped_by_the_ratio_cap_then_the_safety_margin():
    """1-③ F-2 — 이 구간이 통합으로 값이 움직인 유일한 구간이다.

    이전에는 여기서 두 번째 상한(`recommended_ratio_cap`, 소득의 25% = 2,000,000)이
    이겼다. 그 상한을 폐기했으므로 이제는 안전마진만 남아 2,400,000 × 0.85 = 2,040,000
    이다. 소득 대비로는 25.0% → 25.5% (0.5%p) 이고, 밴드·판정은 그대로다.
    """
    result = assess_affordability(8_000_000, 120_000_000, 200_000_000, 0, 1, constants=CONSTANTS)
    assert result["maxMonthlyHousingCostKRW"] == 2_400_000  # 30% ratio cap binds
    assert result["recommendedMonthlyHousingCostKRW"] == 2_040_000  # 상한 × 안전마진 0.85
    assert result["band"] == "safe"


def test_e1_heavy_debt_wipes_out_capacity():
    """Living cost + debt + buffer exceed income -> zero capacity, risk band."""
    result = assess_affordability(1_500_000, 0, 0, 500_000, 1, constants=CONSTANTS)
    assert result["maxMonthlyHousingCostKRW"] == 0
    assert result["band"] == "risk"
    assert any("부채" in line for line in result["rationale"])


def test_e1_larger_household_lowers_the_cap():
    solo = assess_affordability(3_000_000, 0, 0, 0, 1, constants=CONSTANTS)
    family = assess_affordability(3_000_000, 0, 0, 0, 4, constants=CONSTANTS)
    assert family["breakdown"]["livingCost"] > solo["breakdown"]["livingCost"]
    assert family["maxMonthlyHousingCostKRW"] < solo["maxMonthlyHousingCostKRW"]


def test_e1_derives_monthly_income_from_annual_when_missing():
    result = assess_affordability(0, 48_000_000, 0, 0, 1, constants=CONSTANTS)
    assert result["breakdown"]["netIncome"] == 3_400_000  # 48M / 12 * 0.85
    assert result["maxMonthlyHousingCostKRW"] > 0


def test_e1_is_deterministic():
    a = assess_affordability(3_000_000, 42_000_000, 40_000_000, 300_000, 1, constants=CONSTANTS)
    b = assess_affordability(3_000_000, 42_000_000, 40_000_000, 300_000, 1, constants=CONSTANTS)
    assert a == b


# ==========================================================================
# E2 — Eligibility
# ==========================================================================

def test_e2_buttress_is_eligible_for_the_base_profile():
    policies = evaluate_policies(BASE_PROFILE, POLICIES, "서울 마포구", constants=CONSTANTS)["policies"]
    buttress = next(p for p in policies if p["id"] == "buttress_youth")
    assert buttress["status"] == "eligible"
    assert any("만 19~34세" in reason for reason in buttress["reasons"])
    assert any("연소득" in reason for reason in buttress["reasons"])


def test_e2_newlywed_only_product_is_ineligible_when_single():
    policies = evaluate_policies(BASE_PROFILE, POLICIES, "서울 마포구", constants=CONSTANTS)["policies"]
    newlywed = next(p for p in policies if p["id"] == "newlywed_jeonse")
    assert newlywed["status"] == "ineligible"
    assert any("혼인" in reason for reason in newlywed["reasons"])


def test_e2_a_requires_sme_product_is_conditional_pending_proof():
    """`requireSME` 분기 — **합성 정책으로** 건다. 시드 데이터에 묶지 않는다.

    원래 이 테스트는 `sme_youth_deposit` 를 집어 왔다. 그 상품이 폐지되면서
    (2024-12-31 신규 신청 종료, `diligence/FINDINGS-4.md`) 테스트가 깨졌고,
    그때 드러난 사실은 **현행 8개 정책 중 `requireSME` 를 쓰는 것이 하나도 없다**는
    것이다. 즉 엔진의 그 분기는 시드 데이터로는 더 이상 밟히지 않는다.

    그렇다고 테스트를 지우면 살아 있는 분기가 조용히 무검증이 된다. 그래서 검사 대상을
    엔진 분기 자체로 되돌린다 — 어느 상품이 마침 존재하는지와 무관하게 성립한다.
    """
    synthetic = [{
        "id": "synthetic_sme_product",
        "name": "합성 중소기업 재직 상품",
        "category": "대출",
        "summary": "requireSME 분기를 밟기 위한 테스트 전용 정책이다. 시드 데이터가 아니다.",
        "maxAmountKRW": 100_000_000,
        "rateRangePct": [1.2, 1.5],
        "source": "테스트 픽스처",
        "disclaimer": "테스트 전용",
        "criteria": {
            "ageMin": 19, "ageMax": 34,
            "annualIncomeMaxKRW": 50_000_000, "assetMaxKRW": 337_000_000,
            "requireHomeless": True, "requireNewlywed": False,
            "requireSME": True, "regionPrefixes": [],
        },
        "conditionalChecks": ["중소·중견기업 재직 증빙 제출이 필요합니다."],
    }]
    policies = evaluate_policies(
        BASE_PROFILE, synthetic, "서울 마포구", constants=CONSTANTS)["policies"]
    sme = next(p for p in policies if p["id"] == "synthetic_sme_product")
    assert sme["status"] == "conditional"
    assert any("증빙" in reason for reason in sme["reasons"])


def test_no_current_policy_uses_require_sme():
    """위 분기가 **시드 데이터로는 안 밟힌다**는 사실 자체를 고정한다.

    프로필은 여전히 `isSMEEmployee` 를 묻는데 그 값을 소비하는 정책이 없다.
    이것은 결함이 아니라 폐지의 결과이며, 숨기면 다음 사람이 [왜 안 쓰이지]로 시간을 쓴다.
    `requireSME` 정책이 다시 생기면 여기가 빨간불로 알려 준다 — 그때 이 테스트를 지운다.
    """
    assert [p["id"] for p in POLICIES if p["criteria"].get("requireSME")] == []


def test_e2_age_boundary_disqualifies_youth_products():
    older = dict(BASE_PROFILE, age=40)
    policies = evaluate_policies(older, POLICIES, "서울 마포구", constants=CONSTANTS)["policies"]
    buttress = next(p for p in policies if p["id"] == "buttress_youth")
    assert buttress["status"] == "ineligible"
    assert any("40세" in reason for reason in buttress["reasons"])


def test_e2_unlimited_age_cap_does_not_disable_the_age_floor():
    """상한이 무제한 센티넬이어도 **하한은 그대로 거른다** (적대적 리뷰 H3).

    결함은 연령 블록 전체가 `ageMax < 200` 하나에 걸려 있던 것이다. `newlywed_jeonse`
    의 `ageMax` 가 센티넬 200 이라 `200 < 200` 이 False 가 되고, 그 순간 **`ageMin` 19
    검사까지 함께 사라졌다.** 소득·자산은 각각 독립 if 인데 연령만 결합돼 있었다.

    API 는 age 를 `ge=0` 으로만 받으므로(main.py) 이것은 이론적 입력이 아니다. 이 테스트가
    없으면 화면에서 나이 5 를 넣은 심사위원에게 신혼부부 전세자금대출이 **적격**으로 뜬다.
    그리고 더 나쁜 것은, 적용되지 않은 기준이 `reasons` 에서 **존재 자체를 감춘다**는 것이다.
    """
    child = dict(BASE_PROFILE, age=5, isNewlywed=True, annualIncomeKRW=0)
    policies = evaluate_policies(
        child, POLICIES, "서울 마포구", constants=CONSTANTS)["policies"]
    newlywed = next(p for p in policies if p["id"] == "newlywed_jeonse")

    assert newlywed["status"] == "ineligible"
    # 판정만이 아니라 **사유가 보이는지**를 함께 건다. H3 의 핵심이 그것이다.
    assert any("19" in r and "미충족" in r and "5세" in r for r in newlywed["reasons"]),         newlywed["reasons"]


def test_e2_unlimited_age_cap_still_states_the_floor_when_met():
    """하한을 넘긴 쪽도 **충족 사유가 보여야** 한다 — 침묵은 판정 근거가 아니다.

    위 테스트의 짝이다. 하한 검사가 되살아났는지를 실패 쪽에서만 보면, 검사를 통째로
    '항상 미충족'으로 만들어도 통과한다. 통과 쪽에 사유 줄이 서는지까지 봐야 검사가
    실제로 판단하고 있다는 것이 고정된다.
    """
    policies = evaluate_policies(
        dict(BASE_PROFILE, isNewlywed=True), POLICIES, "서울 마포구",
        constants=CONSTANTS)["policies"]
    newlywed = next(p for p in policies if p["id"] == "newlywed_jeonse")

    assert newlywed["status"] in ("eligible", "conditional")
    assert any("19" in r and "충족" in r and "미충족" not in r
               for r in newlywed["reasons"]), newlywed["reasons"]
    # 상한이 없으므로 '연령 상한 임박' caveat 은 절대 서면 안 된다 (나이와 무관하게).
    old = evaluate_policies(
        dict(BASE_PROFILE, age=99, isNewlywed=True), POLICIES, "서울 마포구",
        constants=CONSTANTS)["policies"]
    old_newlywed = next(p for p in old if p["id"] == "newlywed_jeonse")
    assert not any("상한" in r and "임박" in r for r in old_newlywed["reasons"])


def test_e2_policy_declaring_only_an_age_floor_is_still_checked():
    """`ageMin` 만 선언한 정책 — **합성 정책으로** 건다 (`requireSME` 와 같은 이유).

    결함의 두 번째 갈래다. 옛 조건은 `ageMin is not None and ageMax is not None` 이라
    **둘 중 하나만 선언한 정책은 어느 쪽도 검사되지 않았다.** 시드 8개는 모두 두 키를
    함께 갖고 있어 이 갈래는 시드 데이터로 밟히지 않는다. 그래서 엔진 분기 자체를
    대상으로 삼는다 — 어떤 상품이 마침 존재하는지와 무관하게 성립한다.
    """
    floor_only = [{
        "id": "synthetic_floor_only",
        "name": "합성 하한 전용 상품",
        "category": "대출",
        "summary": "ageMin 만 선언된 정책을 밟기 위한 테스트 전용 정책이다. 시드 데이터가 아니다.",
        "maxAmountKRW": 100_000_000,
        "rateRangePct": [1.2, 1.5],
        "source": "테스트 픽스처",
        "disclaimer": "테스트 전용",
        "criteria": {"ageMin": 19},
        "conditionalChecks": [],
    }]

    under = evaluate_policies(
        dict(BASE_PROFILE, age=18), floor_only, "서울 마포구", constants=CONSTANTS)["policies"][0]
    assert under["status"] == "ineligible"
    assert any("19" in r and "미충족" in r for r in under["reasons"]), under["reasons"]

    over = evaluate_policies(
        dict(BASE_PROFILE, age=19), floor_only, "서울 마포구", constants=CONSTANTS)["policies"][0]
    assert over["status"] == "eligible"
    assert any("19" in r and "미충족" not in r for r in over["reasons"]), over["reasons"]


def test_e2_policy_declaring_only_an_age_cap_is_still_checked():
    """짝이 되는 갈래 — `ageMax` 만 선언한 정책. 하한 부재가 상한을 지우지 않는다."""
    cap_only = [{
        "id": "synthetic_cap_only",
        "name": "합성 상한 전용 상품",
        "category": "대출",
        "summary": "ageMax 만 선언된 정책을 밟기 위한 테스트 전용 정책이다. 시드 데이터가 아니다.",
        "maxAmountKRW": 100_000_000,
        "rateRangePct": [1.2, 1.5],
        "source": "테스트 픽스처",
        "disclaimer": "테스트 전용",
        "criteria": {"ageMax": 34},
        "conditionalChecks": [],
    }]

    over = evaluate_policies(
        dict(BASE_PROFILE, age=35), cap_only, "서울 마포구", constants=CONSTANTS)["policies"][0]
    assert over["status"] == "ineligible"
    assert any("34" in r and "미충족" in r for r in over["reasons"]), over["reasons"]

    under = evaluate_policies(
        dict(BASE_PROFILE, age=28), cap_only, "서울 마포구", constants=CONSTANTS)["policies"][0]
    assert under["status"] == "eligible"


def test_e2_fully_unbounded_age_emits_no_age_reason():
    """양쪽 다 무제한이면 연령 사유 줄을 **내지 않는다** (`hug_deposit_guarantee` 0/200).

    `age` 는 `safe_int` 를 지나 항상 0 이상이므로 `ageMin` 0 은 항등식이고 아무도 거르지
    못한다. 거기에 "만 0세 이상 요건 충족" 을 세우면 화면에는 판정에 기여하지 않은 줄이
    하나 늘 뿐이다. **적용됐는데 숨는 것**(H3 가 지적한 결함)과 **적용될 여지가 없는 것**은
    다르게 다룬다.
    """
    for age in (0, 28, 99):
        policies = evaluate_policies(
            dict(BASE_PROFILE, age=age), POLICIES, "서울 마포구",
            constants=CONSTANTS)["policies"]
        hug = next(p for p in policies if p["id"] == "hug_deposit_guarantee")
        assert not any("만 " in r and "세" in r for r in hug["reasons"]), hug["reasons"]


def test_e2_range_policies_keep_the_combined_age_label():
    """두 경계가 모두 실재하면 사유 줄은 **한 줄**이고 문구는 예전 그대로다.

    하한·상한을 각각 판단하도록 고쳤지만 표시까지 둘로 쪼개지는 않았다. 결함은
    '검사되지 않는 경계'였지 '한 줄로 묶인 라벨'이 아니고, 쪼개면 시드 8개 중 6개의
    사유 목록이 이유 없이 흔들린다.
    """
    policies = evaluate_policies(
        BASE_PROFILE, POLICIES, "서울 마포구", constants=CONSTANTS)["policies"]
    buttress = next(p for p in policies if p["id"] == "buttress_youth")
    age_lines = [r for r in buttress["reasons"] if "만 " in r and "세" in r]
    assert age_lines == ["만 19~34세 요건 충족 (28세)"], age_lines


def test_e2_region_scoped_policy_is_ineligible_outside_its_region():
    busan = dict(BASE_PROFILE, regionCode="26350", annualIncomeKRW=25_000_000)
    policies = evaluate_policies(busan, POLICIES, "부산 해운대구", constants=CONSTANTS)["policies"]
    seoul_only = next(p for p in policies if p["id"] == "seoul_youth_rent")
    assert seoul_only["status"] == "ineligible"
    assert any("지역" in reason for reason in seoul_only["reasons"])


def test_e2_every_policy_is_well_formed():
    result = evaluate_policies(BASE_PROFILE, POLICIES, "서울 마포구", constants=CONSTANTS)
    assert len(result["policies"]) >= 8
    for policy in result["policies"]:
        assert policy["status"] in ("eligible", "conditional", "ineligible")
        assert policy["reasons"] and all(isinstance(r, str) for r in policy["reasons"])
        assert policy["source"], f"{policy['id']} is missing a source"
        assert policy["disclaimer"], f"{policy['id']} is missing a disclaimer"
        assert len(policy["rateRangePct"]) == 2
    assert _rationale_ok(result)


# ==========================================================================
# E3 — TCO / NPV
# ==========================================================================

def _scenarios(profile=None):
    profile = profile or BASE_PROFILE
    region = find_region(profile["regionCode"], regions=REGIONS)
    affordability = assess_affordability(
        profile["monthlyNetIncomeKRW"],
        profile["annualIncomeKRW"],
        profile["liquidAssetsKRW"],
        profile["existingDebtMonthlyKRW"],
        profile["householdSize"],
        constants=CONSTANTS,
    )
    return build_scenarios(
        region,
        profile,
        affordability,
        guarantee_deposit_cap_krw=guarantee_deposit_cap_for(region, constants=CONSTANTS),
        constants=CONSTANTS,
    )


def test_e3_tco_equals_the_sum_of_its_components():
    for scenario in _scenarios()["scenarios"]:
        assert scenario["tco5yKRW"] == sum(scenario["components"].values())


def test_e3_npv_is_below_tco_but_positive():
    for scenario in _scenarios()["scenarios"]:
        if scenario["tco5yKRW"] > 0:
            assert 0 < scenario["npv5yKRW"] < scenario["tco5yKRW"]


def test_e3_returns_both_jeonse_and_monthly_options():
    scenarios = _scenarios()["scenarios"]
    assert len(scenarios) >= 4
    types = {s["type"] for s in scenarios}
    assert types == {"jeonse", "monthly"}
    ids = {s["id"] for s in scenarios}
    assert {"jeonse_loan", "semi_jeonse", "monthly_standard", "monthly_low_deposit"} <= ids


def test_e3_scenario_fields_are_within_contract_ranges():
    result = _scenarios()
    for scenario in result["scenarios"]:
        assert scenario["verdict"] in ("affordable", "stretch", "unaffordable")
        assert 0 <= scenario["fitScore"] <= 100
        assert scenario["monthlyEquivalentCostKRW"] >= 0
        assert _rationale_ok(scenario)
    assert _rationale_ok(result)


def test_e3_zero_income_makes_every_scenario_unaffordable():
    broke = dict(BASE_PROFILE, monthlyNetIncomeKRW=0, annualIncomeKRW=0, liquidAssetsKRW=0)
    for scenario in _scenarios(broke)["scenarios"]:
        assert scenario["verdict"] == "unaffordable"


def test_e3_results_are_sorted_by_fit_score_descending():
    scores = [s["fitScore"] for s in _scenarios()["scenarios"]]
    assert scores == sorted(scores, reverse=True)


# ==========================================================================
# E4 — Deposit risk
# ==========================================================================

def test_e4_high_ratio_without_guarantee_is_high_risk():
    result = scan_deposit_risk(
        deposit_krw=300_000_000,
        jeonse_ratio_pct=92.0,
        loan_amount_krw=240_000_000,
        guarantee_available=False,
        market_risk="high",
        region_name="테스트 지역",
        guarantee_deposit_cap_krw=METRO_CAP,
        constants=CONSTANTS,
    )
    assert result["score"] > 64
    assert result["band"] == "high"


def test_e4_low_ratio_with_guarantee_is_low_risk():
    result = scan_deposit_risk(
        deposit_krw=150_000_000,
        jeonse_ratio_pct=58.0,
        loan_amount_krw=0,
        guarantee_available=True,
        market_risk="low",
        region_name="테스트 지역",
        guarantee_deposit_cap_krw=METRO_CAP,
        constants=CONSTANTS,
    )
    assert result["score"] <= 34
    assert result["band"] == "low"


def test_e4_factors_are_well_formed_and_score_is_clamped():
    result = scan_deposit_risk(
        280_000_000,
        71.2,
        200_000_000,
        True,
        "low",
        "서울 마포구",
        guarantee_deposit_cap_krw=METRO_CAP,
        constants=CONSTANTS,
    )
    assert 0 <= result["score"] <= 100
    assert len(result["factors"]) == 5
    for factor in result["factors"]:
        assert factor["impact"] in ("low", "medium", "high")
        assert isinstance(factor["valuePct"], (int, float))
        assert factor["name"] and factor["note"]
    assert _rationale_ok(result)


def test_e4_zero_deposit_carries_almost_no_risk():
    result = scan_deposit_risk(
        0, 0.0, 0, True, "low", "테스트 지역",
        guarantee_deposit_cap_krw=METRO_CAP, constants=CONSTANTS,
    )
    assert result["band"] == "low"
    assert any("보증금이 없어" in line for line in result["rationale"])


# ==========================================================================
# A1 — Agent layer
# ==========================================================================

@pytest.fixture
def no_keys(monkeypatch):
    """Force the offline path — no test may make a live API call."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return monkeypatch


def test_a1_chat_never_raises_without_any_api_key(no_keys):
    assert get_llm_mode() == "offline"
    result = chat("전세랑 월세 중 뭐가 나아?", BASE_PROFILE, [], constants=CONSTANTS,
                  regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    assert result["mode"] == "offline"
    assert result["provider"] == "offline"
    assert result["reply"].strip()
    assert isinstance(result["toolCalls"], list) and result["toolCalls"]
    assert "tool" in result["toolCalls"][0]


def test_a1_offline_handles_garbage_input_gracefully(no_keys):
    for message, profile in (
        ("", {}),
        ("!!!???", {}),
        ("지원 되나요", dict(BASE_PROFILE, regionCode="99999")),
    ):
        result = chat(message, profile, [], constants=CONSTANTS, regions=REGIONS,
                      policies=POLICIES, now=FROZEN_NOW)
        assert result["mode"] == "offline"
        assert isinstance(result["reply"], str) and result["reply"].strip()


def test_a1_offline_intent_routing_picks_the_right_engine(no_keys):
    cases = {
        "전세랑 월세 중 뭐가 나아?": "compare_tco",
        "보증금 떼일 위험 없나요?": "scan_risk",
        "버팀목 대출 받을 수 있나요?": "check_eligibility",
        "월세 얼마까지 감당 가능해?": "assess_affordability",
    }
    for message, expected in cases.items():
        assert chat(message, BASE_PROFILE, [], constants=CONSTANTS,
                    regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)["toolCalls"][0]["tool"] == expected


# ==========================================================================
# Provider abstraction — .env loading, priority, shared tool schema
# ==========================================================================

def test_env_value_cleaning_strips_quotes_brackets_and_space():
    assert clean_env_value("  sk-proj-abc  ") == "sk-proj-abc"
    assert clean_env_value('"sk-proj-abc"') == "sk-proj-abc"
    assert clean_env_value("'sk-proj-abc'") == "sk-proj-abc"
    assert clean_env_value("<sk-proj-abc>") == "sk-proj-abc"
    assert clean_env_value('"<sk-proj-abc>"') == "sk-proj-abc"
    assert clean_env_value(' <"sk-proj-abc"> ') == "sk-proj-abc"
    assert clean_env_value("") == ""
    # characters inside the value are never touched
    assert clean_env_value("sk-a<b>c") == "sk-a<b>c"


def test_env_parser_handles_bom_crlf_export_and_comments():
    text = (
        "﻿# comment line\r\n"
        "\r\n"
        "OPENAI_API_KEY = <sk-proj-xyz> \r\n"
        "export ANTHROPIC_MODEL='claude-sonnet-5'\r\n"
        "MALFORMED_LINE_NO_EQUALS\r\n"
    )
    parsed = parse_env_text(text)
    assert parsed["OPENAI_API_KEY"] == "sk-proj-xyz"
    assert parsed["ANTHROPIC_MODEL"] == "claude-sonnet-5"
    assert "MALFORMED_LINE_NO_EQUALS" not in parsed


def test_env_file_is_discovered_by_walking_up_from_backend(tmp_path):
    root = tmp_path / "repo"
    (root / "prototype" / "backend").mkdir(parents=True)
    (root / ".env").write_text("OPENAI_API_KEY=<sk-found>\n", encoding="utf-8")
    found = find_env_file(root / "prototype" / "backend")
    assert found == root / ".env"
    assert find_env_file(tmp_path / "nowhere") is None


def test_env_loader_only_imports_allowlisted_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=<sk-allow>\nPATH=/evil/path\nRANDOM_SECRET=nope\n", encoding="utf-8"
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    applied = load_env_file(env_file)
    assert applied == {"OPENAI_API_KEY": "sk-allow"}
    assert os.environ["OPENAI_API_KEY"] == "sk-allow"
    assert os.environ.get("RANDOM_SECRET") is None


def test_provider_priority_openai_then_anthropic_then_offline(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    assert resolve_provider() == "openai"

    monkeypatch.delenv("OPENAI_API_KEY")
    assert resolve_provider() == "anthropic"

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert resolve_provider() == "offline"


def test_blank_or_placeholder_key_counts_as_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for blank in ("", "   ", '""', "<>", "<  >"):
        monkeypatch.setenv("OPENAI_API_KEY", blank)
        assert resolve_provider() == "offline", f"{blank!r} should not count as a key"


def test_tool_schema_is_defined_once_and_converted_for_both_sdks():
    SPECS = tool_specs(REGIONS)
    openai_tools = to_openai_tools(REGIONS)
    anthropic_tools = to_anthropic_tools(REGIONS)

    assert len(openai_tools) == len(anthropic_tools) == len(SPECS) == 4

    openai_names = [t["function"]["name"] for t in openai_tools]
    anthropic_names = [t["name"] for t in anthropic_tools]
    assert openai_names == anthropic_names == list(TOOL_NAMES)
    assert set(TOOL_NAMES) == {
        "assess_affordability",
        "check_eligibility",
        "compare_tco",
        "scan_risk",
    }

    # Same JSON Schema object reaches both SDKs — no duplicated definition.
    for spec, oai, ant in zip(SPECS, openai_tools, anthropic_tools):
        assert oai["type"] == "function"
        assert oai["function"]["parameters"] == spec["parameters"]
        assert ant["input_schema"] == spec["parameters"]
        assert oai["function"]["description"] == ant["description"] == spec["description"]
        assert spec["parameters"]["type"] == "object"


def test_every_declared_tool_is_executable(no_keys):
    """A tool the model can call must always resolve to a real engine."""
    for name in TOOL_NAMES:
        payload, summary = execute_tool(name, {}, BASE_PROFILE, constants=CONSTANTS,
                                      regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
        assert "error" not in payload, f"{name} failed"
        assert summary.strip()


def test_unknown_tool_name_is_reported_not_raised():
    payload, summary = execute_tool("nonexistent_tool", {}, BASE_PROFILE, constants=CONSTANTS,
                                  regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    assert "error" in payload
    assert "nonexistent_tool" in summary


def test_region_code_tool_arg_is_constrained_to_real_codes():
    """A model must not be able to invent a region code (observed: 'MA')."""
    spec = next(s for s in tool_specs(REGIONS) if s["name"] == "check_eligibility")
    enum = spec["parameters"]["properties"]["regionCode"]["enum"]
    assert enum == [r["code"] for r in REGIONS]
    assert "MA" not in enum


def test_hallucinated_tool_arg_falls_back_to_the_user_profile():
    """A bad override degrades to the real profile instead of wasting the call."""
    payload, summary = execute_tool("check_eligibility", {"regionCode": "MA"}, BASE_PROFILE,
                                  constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    assert "error" not in payload
    assert payload["policies"], "must still return a usable result"
    assert "_note" in payload and "MA" in payload["_note"]
    assert "유효하지 않아" in summary


def test_unrecoverable_input_still_reports_an_error():
    """If even the base profile is invalid there is nothing to fall back to."""
    payload, summary = execute_tool("scan_risk", {}, {"regionCode": "99999"}, constants=CONSTANTS,
                                  regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    assert "error" in payload
    assert "99999" in summary


# ==========================================================================
# Orchestration + HTTP contract
# ==========================================================================

def test_analyze_returns_every_contract_key():
    result = analyze(BASE_PROFILE, constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    assert set(result) >= {"affordability", "scenarios", "policies", "risk", "summary", "meta"}
    assert result["meta"]["engineVersion"]
    assert result["meta"]["generatedAt"].endswith("Z")
    assert result["meta"]["disclaimer"]
    assert result["summary"].strip()


def test_the_seeded_store_meets_the_brief_minimums():
    """예선 브리프의 커버리지 하한 (D-4). 컷오버 후 이 값의 출처는 저장소다."""
    regions = REGIONS
    assert len(regions) >= 8
    assert sum(1 for r in regions if r["code"].startswith("11")) >= 4  # 서울
    assert sum(1 for r in regions if r["code"].startswith("41")) >= 2  # 경기
    assert len(POLICIES) >= 8
    for region in regions:
        assert region["source"]


def test_http_health_and_regions():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["llm"] in ("openai", "anthropic", "offline")

    regions = client.get("/api/regions")
    assert regions.status_code == 200
    assert len(regions.json()["regions"]) >= 8
    first = regions.json()["regions"][0]
    assert set(first) == {
        "code",
        "name",
        "jeonseMedianKRW",
        "monthlyDepositKRW",
        "monthlyRentKRW",
        "maintenanceFeeKRW",
        "jeonseRatioPct",
        "source",
    }


def test_http_analyze_matches_the_contract_shape():
    response = client.post("/api/analyze", json=BASE_PROFILE)
    assert response.status_code == 200
    body = response.json()

    aff = body["affordability"]
    # SPEC 5.2.1 (1-③) — `schwabeIndexPct` 는 여기서 빠지고 `scenarios[]` 로 갔다.
    assert set(aff) == {
        "maxMonthlyHousingCostKRW",
        "recommendedMonthlyHousingCostKRW",
        "band",
        "breakdown",
        "rationale",
    }
    assert aff["band"] in ("safe", "caution", "risk")

    scenario = body["scenarios"][0]
    assert set(scenario) == {
        "id",
        "label",
        "type",
        "depositKRW",
        "monthlyRentKRW",
        "loanAmountKRW",
        "loanRatePct",
        "monthlyEquivalentCostKRW",
        "tco5yKRW",
        "npv5yKRW",
        "components",
        "fitScore",
        "schwabeIndexPct",
        "verdict",
        "rationale",
    }
    assert set(scenario["components"]) == {
        "interest",
        "rent",
        "maintenance",
        "opportunityCost",
        "insurance",
    }

    policy = body["policies"][0]
    assert set(policy) == {
        "id",
        "name",
        "category",
        "status",
        "reasons",
        "maxAmountKRW",
        "rateRangePct",
        "source",
        "disclaimer",
    }

    assert set(body["risk"]) >= {"score", "band", "factors"}
    assert body["risk"]["band"] in ("low", "medium", "high")
    assert set(body["meta"]) >= {"generatedAt", "engineVersion", "disclaimer"}


def test_http_unknown_region_returns_the_error_envelope():
    response = client.post("/api/analyze", json=dict(BASE_PROFILE, regionCode="00000"))
    assert response.status_code == 400
    body = response.json()
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "invalid_region"


def test_http_invalid_payload_returns_the_error_envelope():
    response = client.post("/api/analyze", json=dict(BASE_PROFILE, preferredType="nope"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_http_chat_returns_contract_shape(no_keys):
    """Offline-forced so the suite never spends tokens or needs a network."""
    response = client.post(
        "/api/chat",
        json={"message": "전세랑 월세 중 뭐가 나아?", "profile": BASE_PROFILE, "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    # Contract fields (§5) must always be present; `provider` is additive.
    assert {"reply", "toolCalls", "mode"} <= set(body)
    assert body["mode"] in ("live", "offline")
    assert body["provider"] in ("openai", "anthropic", "offline")
    assert body["reply"].strip()
    for call in body["toolCalls"]:
        assert set(call) == {"tool", "args", "resultSummary"}


def test_http_health_reports_the_three_provider_values(no_keys):
    assert client.get("/api/health").json()["llm"] == "offline"


def test_http_analyze_accepts_a_minimal_payload():
    """Missing optional fields must default instead of 4xx-ing the frontend."""
    response = client.post("/api/analyze", json={"monthlyNetIncomeKRW": 2_500_000})
    assert response.status_code == 200
    assert response.json()["scenarios"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
