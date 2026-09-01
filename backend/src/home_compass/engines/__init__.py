"""Home_Compass — deterministic decision engines.

`analyze()` is the single orchestration entry point: it runs E1 -> E2 -> E3 -> E4
in dependency order and assembles the exact response object described in the
API contract. Both the HTTP layer (`app.py`) and the LLM layer (`agent.py`)
call this same function, so the numbers a user reads in the dashboard and the
numbers the chatbot quotes can never diverge.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from .affordability import assess_affordability
from ..common import DISCLAIMER, ENGINE_VERSION, money, safe_int  # noqa: F401
from .eligibility import evaluate_policies
from .risk import scan_deposit_risk
from .tco import build_scenarios

__all__ = [
    "analyze",
    "assess_affordability",
    "build_scenarios",
    "evaluate_policies",
    "find_region",
    "guarantee_deposit_cap_for",
    "required_constant_keys",
    "scan_deposit_risk",
    "ENGINE_VERSION",
    "DISCLAIMER",
]


def required_constant_keys() -> tuple[str, ...]:
    """Every model-constant key the engines look up.

    The caller injects the mapping (SPEC 5.1.1) and therefore has to know what
    to inject; declaring it here keeps the boot-time completeness check from
    hard-coding its own copy of the list, which would drift. `analyze` never
    consults this — a key missing at run time still raises `KeyError` from the
    lookup site itself, because a checked list is not a substitute for
    failing closed (Part 0-E #2).

    A function rather than a module-level constant on purpose: `engines/`
    module-level UPPERCASE names are reserved for model parameters, and the
    architecture test reads them that way.
    """
    return (
        "affordability.buffer_ratio",
        "affordability.caution_cap_ratio",
        "affordability.caution_debt_ratio",
        "affordability.housing_cost_ratio_cap",
        "affordability.living_cost_by_household",
        "affordability.living_cost_extra_per_person",
        "affordability.net_income_from_annual",
        "affordability.recommended_haircut",
        "affordability.safe_cap_ratio",
        "affordability.safe_debt_ratio",
        "eligibility.age_cap_imminent_years",
        "eligibility.age_max_unlimited_sentinel",
        "eligibility.amount_unlimited_sentinel_krw",
        "eligibility.boundary_margin",
        "engines.jeonse_loan_priority",
        "engines.monthly_loan_priority",
        "risk.band_low_max",
        "risk.band_medium_max",
        "risk.deposit_size_threshold_1",
        "risk.deposit_size_threshold_2",
        "risk.deposit_size_weight_2",
        "risk.deposit_size_weight_3",
        "risk.exposure_multiplier_low",
        "risk.exposure_multiplier_minimal",
        "risk.guarantee_deposit_cap_metro_krw",
        "risk.guarantee_deposit_cap_other_krw",
        "risk.guarantee_small_deposit_multiplier",
        "risk.guarantee_unavailable_weight",
        "risk.jeonse_ratio_threshold_1",
        "risk.jeonse_ratio_threshold_2",
        "risk.jeonse_ratio_threshold_3",
        "risk.jeonse_ratio_threshold_4",
        "risk.jeonse_ratio_weight_1",
        "risk.jeonse_ratio_weight_2",
        "risk.jeonse_ratio_weight_3",
        "risk.jeonse_ratio_weight_4",
        "risk.jeonse_ratio_weight_5",
        "risk.loan_share_threshold_1",
        "risk.loan_share_threshold_2",
        "risk.loan_share_threshold_3",
        "risk.loan_share_weight_2",
        "risk.loan_share_weight_3",
        "risk.loan_share_weight_4",
        "risk.low_exposure_krw",
        "risk.market_value_pct_high",
        "risk.market_value_pct_low",
        "risk.market_value_pct_medium",
        "risk.market_weight_high",
        "risk.market_weight_medium",
        "risk.metro_sido_code_prefixes",
        "risk.minimal_exposure_krw",
        "tco.deposit_rounding_unit_krw",
        "tco.discount_rate_pct",
        "tco.fallback_conversion_rate_pct",
        "tco.fallback_jeonse_rate_pct",
        "tco.fit_afford_overrun_slope",
        "tco.fit_afford_weight",
        "tco.fit_capital_weight",
        "tco.fit_preference_match_score",
        "tco.fit_preference_mismatch_score",
        "tco.guarantee_rate_table",
        "tco.guarantee_rate_unknown_axis_rule",
        "tco.horizon_years",
        "tco.jeonse_ltv",
        "tco.low_deposit_scenario_deposit_krw",
        "tco.monthly_rounding_unit_krw",
        "tco.opportunity_rate_pct",
        "tco.semi_jeonse_deposit_share",
    )


def guarantee_deposit_cap_for(region: dict, *, constants: Mapping[str, object]) -> int:
    """HUG 반환보증에 **가입 가능한 전세보증금의 상한** — 수도권 7억 / 그 외 5억 (F-4).

    폐기된 `risk.guarantee_limit_krw` 는 이름이 「보증한도」였는데 7억은 보증한도가
    아니다. 보증한도는 「주택가격 x 90% - 선순위채권」이라는 물건별 산식이고
    (FINDINGS.md A3-2), 7억은 **가입요건 ②** 의 보증금 상한이다 (A3-3). 이름과 의미를
    맞추면서 원문이 함께 적은 지역 구분(수도권 / 그 외)도 들어온다.

    지역 구분은 `region["code"]`(행정표준코드)의 시도 접두 2자리로 판별한다. 지역
    데이터에 수도권 플래그가 없기 때문인데, **「수도권 = 서울·인천·경기」 자체는
    아직 원문으로 확인되지 않았다** — 그래서 그 접두 목록은 별도 키
    (`risk.metro_sido_code_prefixes`)로 서고 레지스트리에서 `unverified` 로 남는다.
    검증된 HUG 상한 두 개와 미검증인 지역 정의를 한 상수에 섞지 않기 위한 분리다.
    """
    prefixes = constants["risk.metro_sido_code_prefixes"]
    code = str(region.get("code") or "")
    if any(code.startswith(prefix) for prefix in prefixes):
        return constants["risk.guarantee_deposit_cap_metro_krw"]
    return constants["risk.guarantee_deposit_cap_other_krw"]


def find_region(region_code: str, *, regions: Sequence[dict]) -> dict | None:
    """Look up a region by code. Returns None when the code is unknown.

    `regions` 는 주입받는다 — 여기에 파일이나 저장소를 읽는 경로는 없다 (SPEC 1.2).
    주입 방식은 `constants` 와 **같은 하나**다: 대상은 위치 인자, 주입되는 데이터는
    키워드 전용 (SPEC 5.1.1 "네 엔진이 각자 다른 방식을 발명하지 않도록").
    """
    code = str(region_code or "")
    for region in regions:
        if region.get("code") == code:
            return region
    return None


def _loan_option(
    evaluated: list, priority: tuple, deposit_krw: int = 0, assets_krw: int = 0
) -> dict | None:
    """Pick the usable loan product that best funds this deposit.

    Ranked by how much of the funding gap the product can actually cover, then
    by the cheaper rate. A 1.5% product with a 1억 cap is worse than a 2.9%
    product with a 2억 cap when the gap is 2.4억 — coverage decides feasibility.
    """
    usable = {p["id"]: p for p in evaluated if p["status"] in ("eligible", "conditional")}
    gap = max(0, safe_int(deposit_krw) - safe_int(assets_krw))

    best = None
    for policy_id in priority:
        policy = usable.get(policy_id)
        if not policy:
            continue
        rate_range = policy.get("rateRangePct") or [0.0, 0.0]
        # Upper bound of the published range — conservative on purpose.
        rate = float(rate_range[-1])
        coverage = min(gap, policy["maxAmountKRW"]) if gap else policy["maxAmountKRW"]
        candidate = (coverage, -rate, policy, rate)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        return None
    _, _, policy, rate = best
    return {
        "name": policy["name"],
        "maxAmountKRW": policy["maxAmountKRW"],
        "ratePct": rate,
    }


def _verdict_caveat(best, recommended, affordability, scenarios) -> str:
    """Spell out, in the summary itself, when the top pick exceeds the budget.

    `fitScore` ranks on affordability *and* capital feasibility *and* stated
    preference, so the winner is not always within the recommended ceiling.
    When it is not, the sentence has to say so — and point at the cheapest
    alternative that does fit, if one exists.
    """
    verdict = best.get("verdict")
    if verdict == "affordable":
        return ""

    monthly = safe_int(best.get("monthlyEquivalentCostKRW"))
    over = monthly - safe_int(recommended)
    max_cost = safe_int(affordability.get("maxMonthlyHousingCostKRW"))

    if verdict == "stretch":
        note = (
            f" 다만 이 안은 권장 상한 {money(recommended)}을 {money(over)} 초과하는"
            f" 다소 무리한 선택으로, 감당 가능 상한 {money(max_cost)} 이내이긴 하나"
            " 저축 여력이 줄어드는 점을 감안하셔야 합니다."
        )
    else:
        note = (
            f" 다만 이 안은 감당 가능 상한 {money(max_cost)}을 초과해"
            " 현재 소득 기준으로는 권장하지 않습니다."
        )

    within = [s for s in scenarios if s.get("verdict") == "affordable"]
    if within:
        alt = min(within, key=lambda s: s["monthlyEquivalentCostKRW"])
        note += (
            f" 권장 상한 이내 대안으로는 '{alt['label']}'(월 환산 "
            f"{money(alt['monthlyEquivalentCostKRW'])})이 있습니다."
        )
    else:
        note += (
            " 비교한 대안 중 권장 상한을 만족하는 안이 없어, 보증금을 낮추거나"
            " 인근의 시세가 낮은 지역을 함께 검토하시길 권합니다."
        )
    return note


def _utc_stamp(now: datetime) -> str:
    """주입받은 시각을 `meta.generatedAt` 표기로 찍는다 (SPEC 5.3).

    표기는 **현행 그대로** `%Y-%m-%dT%H:%M:%SZ` 다. 계약 결정 #4 의 「`Z` 표기 금지」는
    `observed_at` · `fetched_at` 에 걸리는 규칙이고, SPEC 2.1 이 「현행 `meta.generatedAt`
    은 `Z` 표기 — 별개 필드이며 변경하지 않는다」고 예외를 적어 두었다.

    `Z` 는 UTC 라는 **주장**이므로 찍기 전에 UTC 로 맞춘다. 타임존 없는 시각은 거부한다 —
    `astimezone()` 이 그것을 시스템 로컬 시각으로 읽어 KST 를 `Z` 로 적어 버리는 경로가
    생기기 때문이다. 시계를 읽지 않게 만들어 놓고 표기가 거짓이 되면 얻은 것이 없다.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(
            "now 는 타임존을 가진 datetime 이어야 합니다 (naive 금지). "
            "api 는 `main.request_now()` 를, 테스트는 `decision_inputs.FROZEN_NOW` 를 넘깁니다."
        )
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: 한글 음절 블록의 처음과 끝 (U+AC00 · U+D7A3). **숫자로 적지 않는다** — 코드포인트를
#: 리터럴로 쓰면 SPEC 5.1.2 의 리터럴 검사가 판정 상수와 구분하지 못한다.
_HANGUL_FIRST, _HANGUL_LAST = "가", "힣"
#: 받침 없는 음절의 NFD 분해 길이 (초성+중성). 받침이 붙으면 하나 늘어난다.
_NO_FINAL = unicodedata.normalize("NFD", _HANGUL_FIRST)


def _subject_josa(word: str) -> str:
    """주격조사 '이/가' 를 앞 글자의 받침으로 고른다.

    이 자리의 주어는 **시나리오 라벨**이라 값에 따라 갈린다 — '…고월세형'(받침 O) 도
    '반전세… + 월세'(받침 X) 도 나온다. 그래서 문장에 '이(가)' 를 박아 두면 심사위원이
    읽는 문장에 교정부호가 그대로 남는다.

    라벨 끝이 한글이 아닐 수 있어(`전세 + 일반 전세자금대출(예시 금리)`) **마지막 한글
    음절**까지 거슬러 본다. 한글이 하나도 없으면 조사를 고를 근거가 없으므로 '이' 로 둔다.
    """
    for ch in reversed(word):
        if not _HANGUL_FIRST <= ch <= _HANGUL_LAST:
            continue
        return "이" if len(unicodedata.normalize("NFD", ch)) > len(_NO_FINAL) else "가"
    return "이"


def _build_summary(region, affordability, scenarios, policies, risk) -> str:
    region_name = region.get("name", "선택 지역")
    recommended = affordability["recommendedMonthlyHousingCostKRW"]
    eligible = [p for p in policies if p["status"] == "eligible"]
    conditional = [p for p in policies if p["status"] == "conditional"]

    if recommended <= 0:
        head = (
            f"{region_name} 기준, 현재 소득·부채 구조로는 감당 가능한 주거비를 산출할 수 없습니다."
        )
    else:
        head = f"{region_name} 기준, 월 {money(recommended)} 이내 주거비가 권장됩니다."

    if scenarios:
        best = scenarios[0]
        body = (
            f" 비교한 {len(scenarios)}개 대안 중 '{best['label']}'"
            f"{_subject_josa(best['label'])} 적합도 "
            f"{best['fitScore']}점으로 가장 잘 맞으며, 5년 총비용 {money(best['tco5yKRW'])}, "
            f"월 환산 {money(best['monthlyEquivalentCostKRW'])}입니다."
        )
        # The top-ranked scenario can still cost more than the recommended
        # ceiling — fitScore also weighs capital feasibility and preference.
        # Saying only "가장 잘 맞습니다" then quoting a number above the
        # recommendation reads as a contradiction, so the overrun is stated
        # in the same sentence and a within-budget alternative is offered.
        body += _verdict_caveat(best, recommended, affordability, scenarios)
    else:
        body = ""

    if eligible:
        names = ", ".join(p["name"] for p in eligible[:2])
        policy_part = f" 지금 바로 신청 가능한 제도는 {names} 등 {len(eligible)}건입니다."
    elif conditional:
        policy_part = f" 추가 서류 확인이 필요한 조건부 제도가 {len(conditional)}건 있습니다."
    else:
        policy_part = " 현재 프로필에 바로 맞는 지원 제도는 확인되지 않았습니다."

    risk_label = {"low": "낮음", "medium": "보통", "high": "높음"}[risk["band"]]
    risk_part = f" 보증금 위험도는 {risk['score']}점({risk_label})입니다."

    return head + body + policy_part + risk_part


def analyze(
    profile: dict,
    *,
    constants: Mapping[str, object],
    regions: Sequence[dict],
    policies: Sequence[dict],
    now: datetime,
) -> dict:
    """Run all four engines for one profile and return the API response object.

    Raises ValueError when `regionCode` is present but unknown, so the HTTP
    layer can turn it into a 400 with the contract's error envelope.

    지역·정책은 **호출자가 매번 주입한다.** 예전에는 이 모듈이
    `backend/src/home_compass/data/*.json` 을 `lru_cache(maxsize=1)` 로 읽었고, 그래서
    배치가 갱신해도 규칙관리자가 승인해도 재기동 전까지 판정에 반영되지 않았다 —
    SPEC 2.3 이 정면으로 금지하는 상태다. 캐시를 살리려면 저장소 갱신에 연동된 무효화가
    있어야 하고, 없으므로 캐시를 두지 않는다. 지금 이 함수에는 I/O 가 한 줄도 없다.

    `policies` 에 무엇이 실릴지는 **호출자의 책임**이다. SPEC 2.3 이 정한 술어
    (`approved` 이고 `effective_from <= now < effective_to`)는 저장소 질의 계층에서
    강제된다 — `store.rule_versions.active(now)` 가 판정 경로가 부르는 유일한 조회이며
    `RuleDraft` 는 거기 실리지 않는다.

    `now` 도 **주입받는다** (SPEC 5.3). 예전에는 이 함수가 `datetime.now(timezone.utc)` 를
    직접 읽어 `meta.generatedAt` 을 만들었고, 그래서 결정성 테스트가 응답 전체를 바이트
    비교하지 못한 채 제외 목록을 두고 있었다 — 5.3 이 「제외 목록은 자라기 때문」이라고
    금지한 그것이다. 기본값을 두지 않는 이유는 상수·지역·정책과 같다: 기본값이 곧 시계
    읽기이고, 그러면 이 인자는 이름만 남는다 (SPEC 5.1.1 fail-closed).

    호출자가 넘기는 시각은 **활성 규칙 질의에 쓴 것과 같은 순간 하나**여야 한다. 두 번
    읽으면 응답이 「어느 시점 기준의 판정인가」에 두 개의 답을 갖게 된다.
    """
    region_code = str(profile.get("regionCode") or "")
    if region_code:
        region = find_region(region_code, regions=regions)
        if region is None:
            raise ValueError(f"알 수 없는 지역 코드입니다: {region_code}")
    else:
        region = regions[0]

    preferred_type = profile.get("preferredType") or "any"
    if preferred_type not in ("jeonse", "monthly", "any"):
        preferred_type = "any"

    # E1 — how much housing cost can this household absorb?
    affordability = assess_affordability(
        constants=constants,
        monthly_net_income_krw=profile.get("monthlyNetIncomeKRW", 0),
        annual_income_krw=profile.get("annualIncomeKRW", 0),
        liquid_assets_krw=profile.get("liquidAssetsKRW", 0),
        existing_debt_monthly_krw=profile.get("existingDebtMonthlyKRW", 0),
        household_size=profile.get("householdSize", 1),
    )

    # E2 — which policies and products does this profile qualify for?
    eligibility = evaluate_policies(
        profile, policies, region.get("name", ""), constants=constants
    )
    # 주입받은 `policies`(규칙 원본)를 덮어쓰지 않는다. 이름이 겹치면 아래에서 어느
    # 쪽을 보고 있는지가 사라지고, 나중에 원본이 한 번 더 필요해질 때 조용히 판정
    # 결과를 원본인 척 넘기게 된다. `_loan_option` 이 이미 이 이름을 쓰고 있다.
    evaluated = eligibility["policies"]

    # 가입 가능한 전세보증금 상한은 E3(보증료를 계상할지)과 E4(가입 가능성을 어떻게
    # 볼지) 둘 다에 쓰인다. 한 번 구해 양쪽에 같은 값을 넘긴다 — 각자 구하게 두면
    # 두 엔진이 다른 상한을 보는 경로가 생긴다.
    guarantee_deposit_cap = guarantee_deposit_cap_for(region, constants=constants)

    # E3 — compare jeonse / semi-jeonse / monthly on 5-year TCO and NPV.
    tco = build_scenarios(
        constants=constants,
        guarantee_deposit_cap_krw=guarantee_deposit_cap,
        region=region,
        profile=profile,
        affordability=affordability,
        jeonse_loan=_loan_option(
            evaluated,
            constants["engines.jeonse_loan_priority"],
            region.get("jeonseMedianKRW", 0),
            profile.get("liquidAssetsKRW", 0),
        ),
        monthly_loan=_loan_option(
            evaluated,
            constants["engines.monthly_loan_priority"],
            region.get("monthlyDepositKRW", 0),
            profile.get("liquidAssetsKRW", 0),
        ),
        preferred_type=preferred_type,
    )
    scenarios = tco["scenarios"]

    # E4 — how risky is the deposit in the best-fitting scenario?
    top = scenarios[0] if scenarios else {"depositKRW": 0, "loanAmountKRW": 0}
    risk = scan_deposit_risk(
        constants=constants,
        guarantee_deposit_cap_krw=guarantee_deposit_cap,
        deposit_krw=top.get("depositKRW", 0),
        jeonse_ratio_pct=region.get("jeonseRatioPct", 0),
        loan_amount_krw=top.get("loanAmountKRW", 0),
        guarantee_available=bool(region.get("guaranteeAvailable", True)),
        market_risk=region.get("marketRisk", "medium"),
        region_name=region.get("name", ""),
    )

    return {
        "affordability": affordability,
        "scenarios": scenarios,
        "policies": evaluated,
        "risk": risk,
        "summary": _build_summary(region, affordability, scenarios, evaluated, risk),
        "meta": {
            "generatedAt": _utc_stamp(now),
            "engineVersion": ENGINE_VERSION,
            "region": {"code": region.get("code", ""), "name": region.get("name", "")},
            "disclaimer": DISCLAIMER,
        },
    }
