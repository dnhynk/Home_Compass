"""E3 — Jeonse vs. monthly-rent total cost engine (전월세 총비용 비교 엔진).

The point of this engine is that a deposit is **not** a cost — it comes back
at the end of the lease. What it really costs you is the interest on the money
you borrowed plus the return you gave up on the money you tied up. So every
scenario is decomposed into five comparable components over a 5-year horizon:

    interest         전세자금대출 이자
    rent             월세 합계
    maintenance      관리비 합계
    opportunityCost  보증금에 묶인 자기자본의 기회비용
    insurance        전세보증금반환보증 보증료

TCO is the undiscounted sum; NPV discounts the level monthly outflow at a real
discount rate. All functions are pure and deterministic.

Every rate, horizon, weight and rounding unit is **injected** (SPEC 5.1.1).
The discount rate and the opportunity-cost rate are separate registry keys on
purpose — there is no reason for the two to be the same number (SPEC 5.1).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..common import DISCLAIMER, floor_to, money, pct, ratio, safe_int

VERDICTS = ("affordable", "stretch", "unaffordable")


def _npv(monthly_cost: float, months: int, discount_rate_pct: float) -> int:
    """Present value of a level monthly outflow at the real discount rate."""
    if monthly_cost <= 0:
        return 0
    monthly_rate = (1 + discount_rate_pct / 100) ** (1 / 12) - 1
    if monthly_rate <= 0:
        return int(round(monthly_cost * months))
    factor = (1 - (1 + monthly_rate) ** (-months)) / monthly_rate
    return int(round(monthly_cost * factor))


def guarantee_rate_pct_for(deposit_krw: int, *, constants: Mapping[str, object]) -> float:
    """HUG 보증료율 — 24칸 요율표에서 이 보증금액이 속한 칸의 요율 (F-3).

    표의 축은 셋이다 — **보증금액 4구간 x 주택유형 2종 x 부채비율 3구간**
    (`diligence/excerpts/A3-hug-보증료율표.md`). 폐기된 단일값 0.15 는 그 표의
    어느 칸과도 일치하지 않았다.

    ── 우리 입력에는 세 축 중 하나밖에 없다 ────────────────────────────────
    `deposit` 은 있다. **주택유형과 부채비율은 없다** — 주택유형 필드가 프로필에도
    지역 데이터에도 없고, 부채비율의 분자인 선순위채권도 없다. 그리고 더 근본적으로
    `build_scenarios` 는 특정 물건이 아니라 **지역 중위값**에서 네 시나리오를 만들기
    때문에 「이 물건의 주택유형」은 값이 비어 있는 것이 아니라 붙일 대상이 없다.

    그래서 **없는 축을 어떻게 처리할지를 값이 아니라 규칙으로 세워 분리한다**
    (`tco.guarantee_rate_unknown_axis_rule`, (d) our_choice). 표 자체는 원문확인분
    (a) 이고, 칸을 고르는 규칙만 우리 선택이다. 둘을 한 상수에 섞으면 우리 선택이
    공시값인 척하게 된다 (SPEC Part 0-C).
    """
    table = constants["tco.guarantee_rate_table"]
    rule = constants["tco.guarantee_rate_unknown_axis_rule"]
    if rule != "bracket_max":
        # fail-closed (SPEC 5.1.1). 모르는 규칙에 폴백을 두면 그 폴백이 요율을 정한다.
        raise ValueError(f"알 수 없는 보증료율 조회 규칙입니다: {rule!r}")

    deposit = safe_int(deposit_krw)
    bounds = sorted({row["depositMaxKRW"] for row in table if row["depositMaxKRW"] is not None})
    bracket = next((bound for bound in bounds if deposit <= bound), None)
    cells = [row["ratePct"] for row in table if row["depositMaxKRW"] == bracket]
    if not cells:
        raise ValueError(f"보증료율표에 보증금액 {deposit} 이 속할 구간이 없습니다.")
    # 주택유형·부채비율을 모르므로 그 구간의 **최고요율**을 쓴다. 원문 주석이
    # 「단독,다중,다가구주택의 경우로서 타전세계약확인서 미제출시 보증금액 구간에
    # 따른 최고요율」이라고 적어 정보 부재 시 발행기관 스스로 최고요율을 적용한다.
    return max(cells)


def size_loan(
    deposit_krw: int,
    liquid_assets_krw: int,
    loan_cap_krw: int,
    *,
    constants: Mapping[str, object],
) -> int:
    """Borrow only what own capital cannot cover, within LTV and product caps."""
    deposit = safe_int(deposit_krw)
    needed = max(0, deposit - safe_int(liquid_assets_krw))
    ceiling = min(int(deposit * constants["tco.jeonse_ltv"]), safe_int(loan_cap_krw))
    return floor_to(min(needed, ceiling), constants["tco.deposit_rounding_unit_krw"])


def evaluate_scenario(
    scenario_id: str,
    label: str,
    scenario_type: str,
    deposit_krw: int,
    monthly_rent_krw: int,
    maintenance_fee_krw: int,
    loan_amount_krw: int,
    loan_rate_pct: float,
    liquid_assets_krw: int,
    affordable_max_krw: int,
    affordable_recommended_krw: int,
    monthly_net_income_krw: int = 0,
    preferred_type: str = "any",
    insurance_enabled: bool = True,
    *,
    guarantee_deposit_cap_krw: int,
    constants: Mapping[str, object],
) -> dict:
    """Score one housing scenario. Returns a contract-shaped scenario dict.

    `monthly_net_income_krw` is the Schwabe denominator (F-1, SPEC 5.2.1). It is
    the same net income the affordability engine worked from, and it is the same
    denominator the RIR reference uses (월 실수령액, Part 0-C), so the published
    statistic and our number measure the same ratio.

    `guarantee_deposit_cap_krw` is HUG's published ceiling on the deposit that
    may be guaranteed at all (수도권 7억 / 그 외 5억, F-4). It is keyword-only and
    has **no default** on purpose — a default here would quietly decide whether a
    household is charged a guarantee fee (SPEC 5.1.1 fail-closed).
    """
    horizon_years = constants["tco.horizon_years"]
    horizon_months = horizon_years * 12
    opportunity_rate_pct = constants["tco.opportunity_rate_pct"]
    discount_rate_pct = constants["tco.discount_rate_pct"]

    deposit = safe_int(deposit_krw)
    rent = safe_int(monthly_rent_krw)
    maintenance = safe_int(maintenance_fee_krw)
    loan = min(safe_int(loan_amount_krw), deposit)
    rate = max(0.0, float(loan_rate_pct or 0.0))
    assets = safe_int(liquid_assets_krw)
    aff_max = safe_int(affordable_max_krw)
    aff_rec = safe_int(affordable_recommended_krw)
    net_income = safe_int(monthly_net_income_krw)

    own_capital = max(0, deposit - loan)
    capital_shortfall = max(0, own_capital - assets)

    # --- 반환보증 가입 여부 (F-5 · F-4) --------------------------------------
    # 폐기된 조건은 `deposit >= 3천만` 이었다. **그 하한에 대응하는 공시 제도가 없다** —
    # 실사가 HUG 상품개요·FAQ 전문에서 「최저」·「3천만」·「하한」을 검색해 0건임을
    # 확인했다 (FINDINGS.md 4절). HUG 가 실제로 거는 문턱은 하한이 아니라 **상한**이다
    # (가입요건 ②: 전세보증금이 수도권 7억 / 그 외 5억 이하일 것).
    #
    # 없는 하한을 (d) 로 재분류해 보존하지 않고 지운 이유 — (d) 는 「우리가 고른
    # 규범」인데 「3천만 미만이면 반환보증에 가입하지 않는다」는 우리가 고를 이유가
    # 없는 명제다. 근거 없는 명제를 our_choice 라벨로 남기면 라벨만 정직해진다.
    #
    # ★ 여기서 확인하는 것은 **가입요건 세 가지 중 보증금 상한 하나뿐이다.** 나머지
    # 둘(선순위채권이 주택가액의 60% 이내 · 보증한도 = 주택가격 x 90% - 선순위채권)은
    # 물건별 값이 입력에 없어 판정할 수 없다. rationale 이 그 사실을 말한다.
    use_insurance = insurance_enabled and 0 < deposit <= safe_int(guarantee_deposit_cap_krw)
    guarantee_rate_pct = guarantee_rate_pct_for(deposit, constants=constants)

    components = {
        "interest": int(round(loan * rate / 100 * horizon_years)),
        "rent": rent * horizon_months,
        "maintenance": maintenance * horizon_months,
        "opportunityCost": int(
            round(own_capital * opportunity_rate_pct / 100 * horizon_years)
        ),
        "insurance": int(
            round(deposit * guarantee_rate_pct / 100 * horizon_years)
        ) if use_insurance else 0,
    }
    tco = sum(components.values())
    monthly_equivalent = floor_to(
        tco / horizon_months, constants["tco.monthly_rounding_unit_krw"]
    )
    npv = _npv(tco / horizon_months, horizon_months, discount_rate_pct)

    # --- Schwabe index (F-1, SPEC 5.2.1) ------------------------------------
    # 실제 주거비 / 소득. **이 시나리오의** 월환산비용을 쓰기 때문에 시나리오마다
    # 다른 값이 나오고, 그것이 이 지표가 측정값이라는 뜻이다. 예전에는 권장액을
    # 소득으로 나눠 상한 상수를 그대로 되돌려줬다 (Part 0-C F-1).
    #
    # 상한을 걸지 않는다 — 주거비가 소득을 넘는 시나리오는 실재하고, 자르는 순간
    # 다시 상수가 값을 정하게 된다 (SPEC 5.3 은 하한 `0 <=` 만 남겼다).
    #
    # 소득이 0이면 주거비/소득은 **정의되지 않는다.** 그래서 `None` 이다 —
    # `ratio()` 의 0분모 규약(0.0)을 그대로 실으면 화면이 「소득의 0%를 주거비로
    # 쓴다」로 읽고, 그것은 거짓이다. F-1 이 고친 것이 「항등식이 측정값 행세를
    # 하는 것」이었고 여기는 「미정의가 측정값 행세를 하는 것」이라 같은 결함이다.
    # 계약 변경(nullable)은 8.2 절차로 승인됐다 (코디네이터 2026-08-14).
    schwabe_index_pct = (
        round(monthly_equivalent / net_income * 100, 1) if net_income > 0 else None
    )

    # --- Verdict ------------------------------------------------------------
    if aff_max <= 0:
        verdict = "unaffordable"
    elif monthly_equivalent <= aff_rec:
        verdict = "affordable"
    elif monthly_equivalent <= aff_max:
        verdict = "stretch"
    else:
        verdict = "unaffordable"

    # --- Fit score (0~100) --------------------------------------------------
    if aff_rec > 0:
        over = ratio(monthly_equivalent, aff_rec)
        afford_weight = constants["tco.fit_afford_weight"]
        afford_score = (
            afford_weight
            if over <= 1
            else max(
                0.0,
                afford_weight - (over - 1) * constants["tco.fit_afford_overrun_slope"],
            )
        )
    else:
        afford_score = 0.0

    capital_weight = constants["tco.fit_capital_weight"]
    if own_capital <= 0:
        capital_score = capital_weight
    else:
        capital_score = capital_weight * (
            1 - min(1.0, ratio(capital_shortfall, own_capital))
        )

    preference_score = (
        constants["tco.fit_preference_match_score"]
        if preferred_type in ("any", scenario_type)
        else constants["tco.fit_preference_mismatch_score"]
    )
    fit_score = int(max(0, min(100, round(afford_score + capital_score + preference_score))))

    # --- Rationale ----------------------------------------------------------
    rationale = [
        f"보증금 {money(deposit)}, 월세 {money(rent)}, 관리비 {money(maintenance)} 기준 "
        f"{horizon_years}년 총비용은 {money(tco)}이며 월 환산 {money(monthly_equivalent)}입니다."
    ]
    if loan > 0:
        rationale.append(
            f"대출 {money(loan)}에 연 {pct(rate, 2)}를 적용해 {horizon_years}년 이자 "
            f"{money(components['interest'])}이 발생합니다."
        )
    else:
        rationale.append("대출 없이 자기자본으로 조달하는 시나리오라 이자 비용이 없습니다.")

    if components["opportunityCost"] > 0:
        rationale.append(
            f"보증금에 묶이는 자기자본 {money(own_capital)}의 기회비용을 연 "
            f"{pct(opportunity_rate_pct, 1)}로 계산해 {money(components['opportunityCost'])}을 "
            "총비용에 포함했습니다. 보증금 자체는 계약 종료 시 돌려받으므로 비용이 아닙니다."
        )
    if components["insurance"] > 0:
        rationale.append(
            f"전세보증금반환보증 보증료율은 HUG 공시 요율표에서 보증금액 {money(deposit)} "
            f"구간의 연 {pct(guarantee_rate_pct, 3)}를 적용해 {horizon_years}년 "
            f"{money(components['insurance'])}을 반영했습니다. 요율표는 주택유형(아파트/기타)과 "
            "부채비율에 따라 다시 갈리는데 두 값이 입력에 없어 해당 구간의 최고요율을 "
            "적용했습니다. 실제 요율은 이보다 낮을 수 있습니다."
        )
        rationale.append(
            "가입요건 중 여기서 확인한 것은 보증금 상한 하나뿐입니다. 선순위채권이 "
            "주택가액의 60% 이내인지, 보증한도(주택가격 x 90% - 선순위채권)를 넘지 않는지는 "
            "물건별로 달라 이 도구가 판단하지 않습니다."
        )
    elif insurance_enabled and deposit > safe_int(guarantee_deposit_cap_krw):
        rationale.append(
            f"보증금 {money(deposit)}이 전세보증금반환보증 가입 가능 상한 "
            f"{money(guarantee_deposit_cap_krw)}을 넘어 보증료를 계상하지 않았습니다. "
            "보증에 가입할 수 없다는 뜻이므로 총비용이 낮은 것이 유리한 조건은 아닙니다."
        )
    if capital_shortfall > 0:
        rationale.append(
            f"필요 자기자본 {money(own_capital)} 대비 보유 자산이 "
            f"{money(capital_shortfall)} 부족합니다. 추가 대출 한도 확인이나 "
            "보증금이 낮은 대안을 함께 검토하세요."
        )
    rationale.append(
        f"현재가치(NPV, 실질할인율 연 {pct(discount_rate_pct, 1)})는 {money(npv)}입니다."
    )
    if net_income > 0:
        rationale.append(
            f"이 안의 슈바베지수(월 주거비 ÷ 월 실수령액)는 "
            f"{pct(schwabe_index_pct)}입니다 — 월 실수령액 {money(net_income)} 기준 "
            f"월 환산비용 {money(monthly_equivalent)}의 비중이며, 권장액이 아니라 "
            "이 시나리오의 실제 비용을 잰 값입니다."
        )
    verdict_message = {
        "affordable": f"월 환산비용이 권장 주거비 {money(aff_rec)} 이내여서 감당 가능합니다.",
        "stretch": (
            f"월 환산비용이 권장액 {money(aff_rec)}은 넘지만 상한 {money(aff_max)} "
            "이내여서 무리하면 가능한 구간입니다."
        ),
        "unaffordable": (
            f"월 환산비용이 감당 가능 상한 {money(aff_max)}을 초과해 권장하지 않습니다."
        ),
    }[verdict]
    rationale.append(verdict_message)

    return {
        "id": scenario_id,
        "label": label,
        "type": scenario_type,
        "depositKRW": deposit,
        "monthlyRentKRW": rent,
        "loanAmountKRW": loan,
        "loanRatePct": round(rate, 2),
        "monthlyEquivalentCostKRW": monthly_equivalent,
        "tco5yKRW": tco,
        "npv5yKRW": npv,
        "components": components,
        "fitScore": fit_score,
        "schwabeIndexPct": schwabe_index_pct,
        "verdict": verdict,
        "rationale": rationale,
    }


def build_scenarios(
    region: dict,
    profile: dict,
    affordability: dict,
    jeonse_loan: dict | None = None,
    monthly_loan: dict | None = None,
    preferred_type: str = "any",
    *,
    guarantee_deposit_cap_krw: int,
    constants: Mapping[str, object],
) -> dict:
    """Generate and rank the four comparison scenarios for one region.

    `jeonse_loan` / `monthly_loan` are optional {name, maxAmountKRW, ratePct}
    dicts derived from the eligibility engine. When absent, a generic bank
    product rate is assumed and the label says so.
    """
    horizon_years = constants["tco.horizon_years"]
    fallback_jeonse_rate_pct = constants["tco.fallback_jeonse_rate_pct"]
    opportunity_rate_pct = constants["tco.opportunity_rate_pct"]
    deposit_rounding_unit = constants["tco.deposit_rounding_unit_krw"]
    monthly_rounding_unit = constants["tco.monthly_rounding_unit_krw"]

    assets = safe_int(profile.get("liquidAssetsKRW"))
    aff_max = safe_int(affordability.get("maxMonthlyHousingCostKRW"))
    aff_rec = safe_int(affordability.get("recommendedMonthlyHousingCostKRW"))
    # 슈바베 분모 (F-1). E1 이 이미 확정한 소득을 그대로 쓴다 — 프로필에서 다시 읽으면
    # 연소득으로부터 추정한 경우(E1 의 net_income_from_annual 경로)와 갈린다.
    net_income = safe_int(affordability.get("breakdown", {}).get("netIncome"))

    jeonse_median = safe_int(region.get("jeonseMedianKRW"))
    std_deposit = safe_int(region.get("monthlyDepositKRW"))
    std_rent = safe_int(region.get("monthlyRentKRW"))
    maintenance = safe_int(region.get("maintenanceFeeKRW"))
    conversion = float(
        region.get("conversionRatePct") or constants["tco.fallback_conversion_rate_pct"]
    )
    guarantee_ok = bool(region.get("guaranteeAvailable", True))

    if jeonse_loan:
        jeonse_cap = safe_int(jeonse_loan.get("maxAmountKRW"))
        jeonse_rate = float(jeonse_loan.get("ratePct") or fallback_jeonse_rate_pct)
        jeonse_label = f"전세 + {jeonse_loan.get('name', '전세자금대출')}"
    else:
        jeonse_cap = int(jeonse_median * constants["tco.jeonse_ltv"])
        jeonse_rate = fallback_jeonse_rate_pct
        jeonse_label = "전세 + 일반 전세자금대출(예시 금리)"

    if monthly_loan:
        monthly_cap = safe_int(monthly_loan.get("maxAmountKRW"))
        monthly_rate = float(monthly_loan.get("ratePct") or fallback_jeonse_rate_pct)
        monthly_label_suffix = f" + {monthly_loan.get('name', '보증금대출')}"
    else:
        monthly_cap = 0
        monthly_rate = fallback_jeonse_rate_pct
        monthly_label_suffix = ""

    scenarios = []

    # 1) Full jeonse, funded with a policy loan where possible.
    scenarios.append(
        evaluate_scenario(
            "jeonse_loan",
            jeonse_label,
            "jeonse",
            jeonse_median,
            0,
            maintenance,
            size_loan(jeonse_median, assets, jeonse_cap, constants=constants),
            jeonse_rate,
            assets,
            aff_max,
            aff_rec,
            net_income,
            preferred_type,
            guarantee_ok,
            guarantee_deposit_cap_krw=guarantee_deposit_cap_krw,
            constants=constants,
        )
    )

    # 2) Semi-jeonse: half the deposit, the remainder converted to rent.
    semi_deposit = floor_to(
        jeonse_median * constants["tco.semi_jeonse_deposit_share"], deposit_rounding_unit
    )
    semi_rent = floor_to(
        (jeonse_median - semi_deposit) * conversion / 100 / 12, monthly_rounding_unit
    )
    scenarios.append(
        evaluate_scenario(
            "semi_jeonse",
            "반전세(보증부월세) — 보증금 절반 + 월세",
            "monthly",
            semi_deposit,
            semi_rent,
            maintenance,
            size_loan(semi_deposit, assets, jeonse_cap, constants=constants),
            jeonse_rate,
            assets,
            aff_max,
            aff_rec,
            net_income,
            preferred_type,
            guarantee_ok,
            guarantee_deposit_cap_krw=guarantee_deposit_cap_krw,
            constants=constants,
        )
    )

    # 3) Standard monthly rent at the regional median.
    scenarios.append(
        evaluate_scenario(
            "monthly_standard",
            f"월세 — 지역 표준 보증금{monthly_label_suffix}",
            "monthly",
            std_deposit,
            std_rent,
            maintenance,
            size_loan(std_deposit, assets, monthly_cap, constants=constants),
            monthly_rate,
            assets,
            aff_max,
            aff_rec,
            net_income,
            preferred_type,
            guarantee_ok,
            guarantee_deposit_cap_krw=guarantee_deposit_cap_krw,
            constants=constants,
        )
    )

    # 4) Low-deposit monthly rent (deposit converted into rent).
    low_deposit = min(constants["tco.low_deposit_scenario_deposit_krw"], std_deposit)
    low_rent = std_rent + floor_to(
        (std_deposit - low_deposit) * conversion / 100 / 12, monthly_rounding_unit
    )
    scenarios.append(
        evaluate_scenario(
            "monthly_low_deposit",
            "월세 — 저보증금·고월세형",
            "monthly",
            low_deposit,
            low_rent,
            maintenance,
            0,
            0.0,
            assets,
            aff_max,
            aff_rec,
            net_income,
            preferred_type,
            guarantee_ok,
            guarantee_deposit_cap_krw=guarantee_deposit_cap_krw,
            constants=constants,
        )
    )

    scenarios.sort(key=lambda s: (-s["fitScore"], s["monthlyEquivalentCostKRW"]))

    best = scenarios[0]
    cheapest = min(scenarios, key=lambda s: s["tco5yKRW"])
    rationale = [
        f"{region.get('name', '선택 지역')} 기준으로 전세·반전세·월세 "
        f"{len(scenarios)}개 시나리오를 {horizon_years}년 총비용(TCO)과 현재가치(NPV)로 "
        "비교했습니다.",
        f"적합도 1위는 '{best['label']}'(적합도 {best['fitScore']}점, 월 환산 "
        f"{money(best['monthlyEquivalentCostKRW'])})입니다.",
        f"5년 총비용이 가장 낮은 대안은 '{cheapest['label']}'({money(cheapest['tco5yKRW'])})입니다.",
    ]
    if best["id"] != cheapest["id"]:
        rationale.append(
            "총비용이 가장 낮은 대안과 적합도 1위가 다릅니다. 자기자본 조달 여력과 "
            "월 현금흐름 중 무엇을 우선할지에 따라 선택이 달라집니다."
        )
    if preferred_type != "any":
        label = "전세" if preferred_type == "jeonse" else "월세"
        rationale.append(f"선호 유형으로 '{label}'을 선택하셔서 적합도 점수에 가점을 반영했습니다.")
    rationale.append(
        f"보증금 자체는 비용에서 제외하고, 묶이는 자기자본의 기회비용(연 "
        f"{pct(opportunity_rate_pct, 1)})만 반영했습니다."
    )
    rationale.append(DISCLAIMER)

    return {"scenarios": scenarios, "rationale": rationale}
