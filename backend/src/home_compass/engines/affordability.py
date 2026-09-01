"""E1 — Affordability engine (주거지불능력 엔진).

Answers "how much housing cost can this household actually absorb?" with a
deterministic, fully explainable calculation. Given identical inputs the
function always returns an identical dict, and every dict carries a
`rationale` list so the UI and the LLM layer can quote the reasoning
instead of inventing it.

Two independent caps are computed and the tighter one wins:

  1. Ratio cap    — a fixed share of disposable income.
  2. Residual cap — income minus living cost, existing debt and a buffer.

Both are prototype heuristics. Every parameter is **injected**, not declared
here: SPEC 5.1.1 removes module-global model parameters so a reviewer reads the
registry (`contracts/model_constants.json`) rather than the code to learn what
drives a number, and so a wrong number can never come from a runtime default.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..common import DISCLAIMER, floor_to, money, pct, ratio, safe_int

BANDS = ("safe", "caution", "risk")


def living_cost_for(household_size: int, *, constants: Mapping[str, object]) -> int:
    """Baseline non-housing living cost for a household of `household_size`."""
    by_household = constants["affordability.living_cost_by_household"]
    extra_per_person = constants["affordability.living_cost_extra_per_person"]
    size = max(1, safe_int(household_size, 1) or 1)
    if size in by_household:
        return by_household[size]
    # Extrapolate from the largest tabulated household rather than a literal
    # boundary — the table's shape decides where extrapolation starts.
    largest = max(by_household)
    return by_household[largest] + (size - largest) * extra_per_person


def assess_affordability(
    monthly_net_income_krw: int,
    annual_income_krw: int = 0,
    liquid_assets_krw: int = 0,
    existing_debt_monthly_krw: int = 0,
    household_size: int = 1,
    *,
    constants: Mapping[str, object],
) -> dict:
    """Compute the affordable monthly housing cost band for one household.

    Returns a dict matching the `affordability` object of the API contract.
    Never raises: every input is coerced, and a zero/blank profile yields a
    zero-cost 'risk' verdict rather than an exception.
    """
    housing_cost_ratio_cap = constants["affordability.housing_cost_ratio_cap"]
    recommended_haircut = constants["affordability.recommended_haircut"]
    buffer_ratio = constants["affordability.buffer_ratio"]
    net_income_from_annual = constants["affordability.net_income_from_annual"]
    safe_cap_ratio = constants["affordability.safe_cap_ratio"]
    safe_debt_ratio = constants["affordability.safe_debt_ratio"]
    caution_cap_ratio = constants["affordability.caution_cap_ratio"]
    caution_debt_ratio = constants["affordability.caution_debt_ratio"]

    rationale: list[str] = []

    net_income = safe_int(monthly_net_income_krw)
    annual_income = safe_int(annual_income_krw)
    debt = safe_int(existing_debt_monthly_krw)
    assets = safe_int(liquid_assets_krw)
    size = max(1, safe_int(household_size, 1) or 1)

    if net_income <= 0 and annual_income > 0:
        net_income = int(annual_income / 12 * net_income_from_annual)
        rationale.append(
            f"월 실수령액이 입력되지 않아 연소득 {money(annual_income)}의 "
            f"{pct(net_income_from_annual * 100, 0)}를 12개월로 나눈 "
            f"{money(net_income)}을 가처분소득으로 추정했습니다."
        )

    living_cost = living_cost_for(size, constants=constants)
    buffer_amount = int(net_income * buffer_ratio)

    ratio_cap = net_income * housing_cost_ratio_cap
    residual_cap = net_income - living_cost - debt - buffer_amount

    max_cost = floor_to(min(ratio_cap, residual_cap)) if net_income > 0 else 0
    # F-2 (SPEC 5.2.2) — 권장액 상한은 **단일 규칙**이다. 이전에는 여기에 상한이 둘이었고
    # (`max_cost * 0.85` vs `net_income * 0.25`) 구간에 따라 각각 유효해졌다. 둘 중
    # `recommended_ratio_cap` 을 폐기했다: 소득비중 축은 준거가 있는
    # `housing_cost_ratio_cap` 이 이미 단독으로 지고 있었고 그 위에 얹힌 준거 없는
    # 중복이었기 때문이다. 남은 안전마진은 **실제로 구속한 상한**에 붙는다 —
    # 비율상한이 이겼든 잔여여력이 이겼든 같은 규칙이다.
    recommended = floor_to(max_cost * recommended_haircut)

    cap_ratio = ratio(max_cost, net_income)
    debt_ratio = ratio(debt, net_income)

    if net_income <= 0:
        band = "risk"
    elif max_cost <= 0:
        band = "risk"
    elif cap_ratio >= safe_cap_ratio and debt_ratio <= safe_debt_ratio:
        band = "safe"
    elif cap_ratio >= caution_cap_ratio and debt_ratio <= caution_debt_ratio:
        band = "caution"
    else:
        band = "risk"

    # --- Explain the result -------------------------------------------------
    if net_income <= 0:
        rationale.append(
            "소득 정보가 없어 감당 가능 주거비를 산출할 수 없습니다. "
            "월 실수령액 또는 연소득을 입력해 주세요."
        )
    else:
        rationale.append(
            f"가처분소득 {money(net_income)} 중 주거비 상한을 "
            f"{pct(housing_cost_ratio_cap * 100, 0)}로 설정했습니다."
        )
        rationale.append(
            f"{size}인 가구 기준 비주거 생활비 {money(living_cost)}, "
            f"기존 부채 상환 {money(debt)}, 비상자금 버퍼 "
            f"{money(buffer_amount)}(소득의 {pct(buffer_ratio * 100, 0)})를 차감하면 "
            f"주거비로 쓸 수 있는 잔여 여력은 {money(max(residual_cap, 0))}입니다."
        )
        if residual_cap < ratio_cap:
            rationale.append(
                "소득 대비 비율보다 실제 잔여 여력이 더 빠듯해, 잔여 여력 기준으로 "
                f"상한을 {money(max_cost)}으로 확정했습니다."
            )
        else:
            rationale.append(
                f"잔여 여력({money(max(residual_cap, 0))})보다 소득 대비 비율 상한이 "
                f"낮아, 상한을 {money(max_cost)}으로 확정했습니다."
            )
        rationale.append(
            f"권장액은 상한 {money(max_cost)}의 {pct(recommended_haircut * 100, 0)}인 "
            f"{money(recommended)}입니다. 상한에 붙여 계약하지 않도록 "
            f"{pct((1 - recommended_haircut) * 100, 0)}의 여유를 둔 값이며, "
            "이 여유폭에는 공표 준거가 없는 우리 기준입니다."
        )
        if debt_ratio > safe_debt_ratio:
            rationale.append(
                f"기존 부채 상환액이 소득의 {pct(debt_ratio * 100)}로 높아 "
                "주거비 여력이 크게 제한됩니다. 부채 상환 계획을 먼저 점검하세요."
            )

    band_message = {
        "safe": "소득 대비 주거비 여력이 안정적인 구간입니다.",
        "caution": "주거비 여력이 빠듯해 주의가 필요한 구간입니다.",
        "risk": "현재 소득·부채 구조로는 주거비 부담이 위험한 구간입니다.",
    }[band]
    rationale.append(band_message)

    if assets > 0:
        rationale.append(
            f"보유 유동자산 {money(assets)}은 보증금 조달 여력 판단에 사용됩니다."
        )

    rationale.append(DISCLAIMER)

    # F-1 (SPEC 5.2.1) — `schwabeIndexPct` 는 여기에 없다. 권장액을 소득으로 나눈 값은
    # 측정값이 아니라 규칙의 되풀이였다. 슈바베지수는 **시나리오별 실제 주거비**로
    # 옮겼다 (`tco.evaluate_scenario`). 대체 필드도 두지 않는다 — 권장액의 소득 대비
    # 비율이 필요한 화면은 `recommendedMonthlyHousingCostKRW / breakdown.netIncome`
    # 으로 재현한다. 둘 다 아래에 실려 있다.
    return {
        "maxMonthlyHousingCostKRW": max_cost,
        "recommendedMonthlyHousingCostKRW": recommended,
        "band": band,
        "breakdown": {
            "netIncome": net_income,
            "livingCost": living_cost,
            "existingDebt": debt,
            "buffer": buffer_amount,
        },
        "rationale": rationale,
    }
