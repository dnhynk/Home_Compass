"""1-③ — F-1 슈바베 재정의 · F-2 권장액 상한 통합 (SPEC 5.2 · 5.2.1 · 5.2.2 · 10.2).

## F-1 이 무엇을 고쳤는가

이전 구현은 이랬다.

    recommended = min(max_cost * haircut, net_income * ratio_cap)
    schwabe     = recommended / net_income

권장 주거비를 소득으로 나눈 값이므로, 비율 상한이 걸리는 구간에서는 `ratio_cap` 을
그대로 되돌려준다. **측정값을 가장한 상수**였고, 사용자에게 아무 정보도 주지 않았다.
1-② 골든에서 24.3% 가 나온 것도 같은 항등식의 산물이다 (그때는 잔여여력이 구속해
`max_cost * 0.85 / net` 이 나왔을 뿐, 여전히 상수의 되풀이다).

슈바베지수는 통상 **실제 주거비 / 소득**이다. 그래서 측정 대상을 사용자가 검토 중인
**각 시나리오**로 옮겼다 — `scenarios[].schwabeIndexPct = 월환산비용 / 월실수령액`.

**이 파일의 존재 이유는 그것이 다시 항등식이 되지 않음을 증명하는 것이다** (SPEC 10.2
1-③: "시나리오마다 다른 값을 낸다 — 항등식이 아님을 테스트로 증명하라").

## F-2 가 무엇을 고쳤는가

`0.30 x 0.85 = 0.255` 와 `0.25` 가 2% 차이로 겹쳐, 구간에 따라 각각 유효해졌다.
`affordability.recommended_ratio_cap` 을 폐기하고 단일 규칙만 남겼다.

    recommended = floor_to(max_cost * recommended_haircut)

근거는 두 상수가 **같은 축이 아니라는** 것이다 — 소득비중 축은 준거가 있는
`housing_cost_ratio_cap`(0.30, RIR 수도권 임차 18.4%) 이 이미 단독으로 지고 있었고,
`recommended_ratio_cap` 은 그 위에 얹힌 준거 없는 중복이었다. 남은 `recommended_haircut`
은 다른 축(상한 대비 안전마진)이며 **실제로 구속한 상한**에 붙는다.
전체 근거와 기각한 안 B 는 `contracts/model_constants.json` 의 해당 entry 에 있다.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from home_compass.common import floor_to  # noqa: E402
from home_compass.engines import analyze, required_constant_keys  # noqa: E402
from home_compass.engines.affordability import assess_affordability  # noqa: E402
from home_compass.engines.tco import evaluate_scenario  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed, load_registry  # noqa: E402

CONSTANTS = frozen_seed()

# SPEC 2.3 컷오버 — 지역·정책도 주입받는다 (`decision_inputs.py`).
REGIONS = store_regions()
POLICIES = store_policies(FROZEN_NOW)

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


def _profile(**overrides) -> dict:
    return {**BASE_PROFILE, **overrides}


def _schwabes(profile: dict) -> list[float]:
    result = analyze(profile, constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    return [s["schwabeIndexPct"] for s in result["scenarios"]]


# ==========================================================================
# F-1 — 슈바베지수는 시나리오별 측정값이다 (SPEC 5.2.1)
# ==========================================================================

def test_schwabe_lives_on_scenarios_not_on_affordability():
    """SPEC 5.2.1 — `affordability.schwabeIndexPct` 는 제거됐고 대체 필드를 두지 않는다.

    권장액의 소득 대비 비율이 필요하면 클라이언트가
    `recommendedMonthlyHousingCostKRW / breakdown.netIncome` 으로 재현한다.
    측정값이 아닌 것을 응답에 측정값처럼 실어 두지 않는 것이 F-1 의 요지다.
    """
    result = analyze(BASE_PROFILE, constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)

    assert "schwabeIndexPct" not in result["affordability"]
    assert not [k for k in result["affordability"] if "schwabe" in k.lower()], (
        "다른 이름으로 같은 값이 최상위에 되돌아왔다 (SPEC 5.2.1 '최상위 단일값을 두지 않는다')")
    for scenario in result["scenarios"]:
        assert "schwabeIndexPct" in scenario, scenario["id"]


def test_schwabe_differs_between_scenarios():
    """★ SPEC 10.2 1-③ 의 완료 기준 — 시나리오마다 **다른 값**을 낸다.

    전부 같은 값이면 F-1 을 고치지 않은 것이다. 측정 대상(월환산비용)이 시나리오마다
    다르므로 값도 달라야 한다.
    """
    values = _schwabes(BASE_PROFILE)
    assert len(values) >= 4, values
    assert len(set(values)) == len(values), (
        f"시나리오별 슈바베가 중복이다 — 측정값이 아니라 상수일 가능성이 있다: {values}")


def test_schwabe_is_the_measured_ratio_of_that_scenarios_cost_to_income():
    """정의 그대로인가 — 월환산비용 / 월실수령액.

    측정 **대상**이 무엇인지가 계약이다. 다른 분자(권장액·상한)를 쓰면 F-1 이 되돌아온다.
    """
    result = analyze(BASE_PROFILE, constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    net = result["affordability"]["breakdown"]["netIncome"]
    for scenario in result["scenarios"]:
        assert scenario["schwabeIndexPct"] == round(
            scenario["monthlyEquivalentCostKRW"] / net * 100, 1
        ), scenario["id"]


def test_schwabe_is_not_an_identity_on_any_registry_constant():
    """★ 항등식이 아님의 직접 증명.

    이전 구현의 병증은 "출력이 어떤 상수를 그대로 되돌려준다" 였다. 그래서 **레지스트리의
    어떤 (d) 비율 상수도** 소득 대비 백분율로 환산했을 때 전 시나리오에 고정으로 나타나지
    않음을 본다. 상수 하나를 콕 집어 25.0 과 비교하면 그 상수만 피해 가는 구현을
    통과시킨다.
    """
    ratio_constants = {
        entry["key"]: entry["frozen_current_value"] * 100
        for entry in load_registry()["entries"]
        if entry["value_type"] == "ratio"
    }
    assert ratio_constants, "레지스트리에서 비율 상수를 못 찾았다 — 검사가 무력하다"

    values = set(_schwabes(BASE_PROFILE))
    pinned = {
        key: value for key, value in ratio_constants.items()
        if {round(value, 1)} == values
    }
    assert not pinned, f"슈바베가 상수를 그대로 되돌려준다 (F-1 미수정): {pinned}"


def test_schwabe_moves_with_income_at_a_fixed_scenario():
    """같은 시나리오·같은 지역이라도 소득이 다르면 값이 다르다.

    분모가 실제로 소득이라는 것 — 이전 구현에서는 비율 상한이 걸리는 한 소득이
    무엇이든 같은 숫자가 나왔다.
    """
    poor = analyze(_profile(monthlyNetIncomeKRW=2_000_000), constants=CONSTANTS,
                   regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    rich = analyze(_profile(monthlyNetIncomeKRW=8_000_000), constants=CONSTANTS,
                   regions=REGIONS, policies=POLICIES, now=FROZEN_NOW)
    by_id = {s["id"]: s for s in poor["scenarios"]}

    compared = 0
    for scenario in rich["scenarios"]:
        twin = by_id.get(scenario["id"])
        if twin is None or twin["monthlyEquivalentCostKRW"] != scenario["monthlyEquivalentCostKRW"]:
            continue
        compared += 1
        assert twin["schwabeIndexPct"] > scenario["schwabeIndexPct"], scenario["id"]
    assert compared, "비용이 같은 시나리오 쌍이 없어 비교하지 못했다"


def test_schwabe_orders_the_same_way_the_monthly_cost_does():
    """더 비싼 시나리오가 더 높은 슈바베를 갖는다 — 분모가 시나리오마다 흔들리지 않는다."""
    scenarios = analyze(BASE_PROFILE, constants=CONSTANTS, regions=REGIONS,
                        policies=POLICIES, now=FROZEN_NOW)["scenarios"]
    by_cost = sorted(scenarios, key=lambda s: s["monthlyEquivalentCostKRW"])
    values = [s["schwabeIndexPct"] for s in by_cost]
    assert values == sorted(values), values


# --- 불변식이 바뀐다 (SPEC 5.3 — 상한을 뗀다) -------------------------------

def test_schwabe_may_exceed_100_because_it_is_now_a_measurement():
    """★ SPEC 5.2.1 — 측정값이 되는 순간 `<= 100` 은 성립하지 않는다.

    주거비가 소득을 넘는 시나리오는 실재한다. 상한을 다시 걸면 그것은 측정값을
    자르는 것이고, F-1 이 없앤 바로 그 병증(상수가 값을 정하는 것)으로 되돌아간다.
    """
    values = _schwabes(_profile(monthlyNetIncomeKRW=1_000_000, liquidAssetsKRW=0))
    assert max(values) > 100, f"소득을 넘는 주거비 시나리오가 나오지 않았다: {values}"


@pytest.mark.parametrize("net_income", [0, 1_000_000, 3_000_000, 30_000_000])
def test_schwabe_is_never_negative(net_income):
    """SPEC 5.3 — `0 <= scenarios[].schwabeIndexPct`. 하한만 남는다.

    소득 0 은 이 부등식의 **대상이 아니다** — 미정의라 `null` 이지 음수가 아니다.
    """
    for value in _schwabes(_profile(monthlyNetIncomeKRW=net_income, annualIncomeKRW=0)):
        if net_income == 0:
            assert value is None
        else:
            assert value >= 0


# --- 미정의는 측정값이 아니다 (코디네이터 판단 1, 8.2 절차 2026-08-14) ---------

def test_zero_income_reports_null_because_the_ratio_is_undefined():
    """★ 소득이 0이면 주거비/소득은 **정의되지 않는다.** `0.0` 이 아니라 `null` 이다.

    이전 구현은 `ratio()` 의 0분모 규약(0.0)을 그대로 응답에 실었고, 화면은 그것을
    「소득의 0%를 주거비로 쓴다」로 읽는다. **거짓이다.** F-1 이 고친 것이
    「항등식이 측정값 행세를 하는 것」이었고 이것은 「미정의가 측정값 행세를 하는
    것」이라 같은 결함이 다른 자리에 있는 것이다.
    """
    assert _schwabes(_profile(monthlyNetIncomeKRW=0, annualIncomeKRW=0)) == [None] * 4


def test_zero_cost_and_undefined_are_different_values():
    """★ 0.0 과 `null` 이 실제로 구분되는가 — 둘이 같은 값이면 구분이 사라진다.

    「주거비가 0이다」(0.0)와 「소득이 없어 잴 수 없다」(`null`)는 다른 사실이다.
    소득이 있고 비용이 0인 시나리오는 `analyze()` 경로의 지역 데이터로는 만들 수
    없어(관리비만 있어도 비용이 0을 넘는다) 엔진 함수를 직접 호출해 세운다.
    """
    zero_cost = evaluate_scenario(
        "unit_zero_cost",
        "비용이 0인 시나리오",
        "monthly",
        deposit_krw=0,
        monthly_rent_krw=0,
        maintenance_fee_krw=0,
        loan_amount_krw=0,
        loan_rate_pct=0.0,
        liquid_assets_krw=0,
        affordable_max_krw=1_000_000,
        affordable_recommended_krw=800_000,
        monthly_net_income_krw=3_000_000,
        guarantee_deposit_cap_krw=700_000_000,
        constants=CONSTANTS,
    )
    undefined = evaluate_scenario(
        "unit_undefined",
        "소득이 0인 시나리오",
        "monthly",
        deposit_krw=0,
        monthly_rent_krw=0,
        maintenance_fee_krw=0,
        loan_amount_krw=0,
        loan_rate_pct=0.0,
        liquid_assets_krw=0,
        affordable_max_krw=0,
        affordable_recommended_krw=0,
        monthly_net_income_krw=0,
        guarantee_deposit_cap_krw=700_000_000,
        constants=CONSTANTS,
    )

    assert zero_cost["monthlyEquivalentCostKRW"] == 0
    assert zero_cost["schwabeIndexPct"] == 0.0
    assert undefined["schwabeIndexPct"] is None
    assert zero_cost["schwabeIndexPct"] is not undefined["schwabeIndexPct"]


# ==========================================================================
# F-2 — 권장액 상한은 단일 규칙이다 (SPEC 5.2.2)
# ==========================================================================

def test_the_dropped_constant_is_gone_from_every_key_source():
    """폐기는 코드에서만 하는 것이 아니다 — 레지스트리·조회 목록 양쪽에서 사라져야 한다."""
    dropped = "affordability.recommended_ratio_cap"
    assert dropped not in required_constant_keys()
    assert dropped not in {entry["key"] for entry in load_registry()["entries"]}
    assert "affordability.recommended_haircut" in required_constant_keys()


@pytest.mark.parametrize(
    "net_income", [2_000_000, 2_400_000, 2_600_000, 3_000_000, 4_000_000, 8_000_000, 30_000_000]
)
def test_recommendation_is_one_rule_across_every_regime(net_income):
    """★ 구간에 따라 다른 상한이 유효해지지 않는다 — 그것이 F-2 가 지적한 결함이다.

    비율상한이 구속하든 잔여여력이 구속하든, 권장액은 **언제나** 상한 x 안전마진이다.
    """
    result = assess_affordability(net_income, 0, 0, 0, 1, constants=CONSTANTS)
    expected = floor_to(
        result["maxMonthlyHousingCostKRW"] * CONSTANTS["affordability.recommended_haircut"]
    )
    assert result["recommendedMonthlyHousingCostKRW"] == expected


def test_the_recommendation_no_longer_pins_to_a_flat_share_of_income():
    """비율상한이 구속하는 구간에서 권장액이 소득의 정확히 25%로 고정되던 항등식이 사라졌다.

    통합 후 그 구간의 실효 소득비중은 `0.30 x 0.85 = 25.5%` 이며, **이 값에도 공표 준거는
    없다** — 레지스트리의 `normative_statement` 가 그 사실을 적고 있다.
    """
    net = 30_000_000  # 잔여여력이 넉넉해 비율상한이 구속하는 구간
    result = assess_affordability(net, 0, 0, 0, 1, constants=CONSTANTS)
    share = result["recommendedMonthlyHousingCostKRW"] / net

    assert result["maxMonthlyHousingCostKRW"] == floor_to(
        net * CONSTANTS["affordability.housing_cost_ratio_cap"])
    assert share == pytest.approx(0.255, abs=1e-4)
    assert share != pytest.approx(0.25, abs=1e-6)


@pytest.mark.parametrize(
    "net_income", [0, 1_200_000, 2_000_000, 3_000_000, 8_000_000, 30_000_000]
)
def test_recommended_never_exceeds_max(net_income):
    """SPEC 5.3 불변식 `recommended <= max`.

    통합 전에는 `min()` 의 두 번째 항이 우연히 이것을 지켜 주기도 했다. 이제는
    안전마진이 1 이하라는 사실 하나가 지킨다.

    ★ **이 불변식은 프로덕션 경로 전용이다.** 감도분석 하네스
    (`tests/sensitivity.py`)는 일부러 비현실적인 상수값을 넣어 보는 곳이므로
    거기서 `recommended <= max` 가 깨지는 것은 결함이 아니라 하네스가 하는 일
    그 자체다. 그래서 그쪽에는 이 assert 를 걸지 않고, 안전마진 1 초과가
    **정의역 밖**이라는 사실을 표에 드러낸다 (코디네이터 판단 2).
    """
    result = assess_affordability(net_income, 0, 0, 0, 1, constants=CONSTANTS)
    assert result["recommendedMonthlyHousingCostKRW"] <= result["maxMonthlyHousingCostKRW"]


@pytest.mark.parametrize("net_income", [2_000_000, 2_200_000, 2_600_000, 3_000_000, 30_000_000])
def test_the_stretch_verdict_stays_reachable(net_income):
    """★ 기각한 안 B 가 무너뜨렸을 것 — 권장액과 상한 사이에 폭이 남아야 한다.

    `tco.py` 의 verdict 는 `<= aff_rec` 이면 affordable, `<= aff_max` 면 stretch 다.
    둘이 같아지는 순간 stretch 는 도달 불가능해지고 3분류가 조용히 2분류가 된다.
    안 B(haircut 폐기)는 잔여여력이 세게 구속하는 저소득 구간에서 정확히 그렇게 됐고,
    그 구간은 1-② 이후 다수다. 되돌아오면 여기서 잡힌다.
    """
    result = assess_affordability(net_income, 0, 0, 0, 1, constants=CONSTANTS)
    max_cost = result["maxMonthlyHousingCostKRW"]
    if max_cost <= 0:
        pytest.skip("상한이 0이면 verdict 는 unaffordable 하나뿐이다")
    assert result["recommendedMonthlyHousingCostKRW"] < max_cost
